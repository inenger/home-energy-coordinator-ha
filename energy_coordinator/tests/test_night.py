import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from energy import night
from energy.store import Store


def state(eid, value, at):
    return {'entity_id': eid, 'state': str(value), 'last_reported': at, 'last_updated': at}


def states(at, forecast='8.4', phase_w=4000):
    vals = {'house_w': 12000, 'ev_w': 11000, 'battery_soc': 60,
            'battery_dc_w': 0, 'battery_v': 237, 'battery_a': 0,
            'battery_limit_a': 30, 'forecast_today': forecast}
    for i in (1, 2, 3):
        vals.update({f'grid_l{i}_w':-3000, f'inverter_l{i}_w':phase_w-3000,
                     f'voltage_l{i}_v':230, f'ev_l{i}_a':16})
    return [state(night.IDS[k],v,at) for k,v in vals.items()]


class NightTests(unittest.TestCase):
    def test_freeze_forecast_and_capture_late_honestly(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'test.sqlite')
            try:
                a='2026-10-21T01:00:15+00:00';b='2026-10-21T01:00:30+00:00'
                first=night.record(store,states(a),a)
                second=night.record(store,states(b,forecast='16'),b)
                self.assertEqual(first['shadow']['target_soc_pct'],80)
                self.assertEqual(second['shadow']['target_soc_pct'],80)
                self.assertEqual(night.recent(store)['status'],'ok')
                self.assertEqual(night.recent(store)['samples'][0]['shadow']['binding_phase'],1)
                self.assertEqual(night.recent(store)['samples'][0]['shadow']['proposed_ac_w'],1600)
            finally:store.close()

    def test_unavailable_or_stale_is_not_zero(self):
        at='2026-10-21T01:00:00+00:00'
        points={k:night.point(s,at) for k,s in
                ((key,next((x for x in states(at) if x['entity_id']==eid),None)) for key,eid in night.IDS.items())}
        points['grid_l2_w']['age_seconds']=120
        shadow=night.derive(points,at,{'target_soc_pct':80})
        self.assertIsNone(shadow['proposed_ac_w'])
        self.assertEqual(shadow['reason'],'invalid_phase_input')

    def test_summary_counts_only_short_valid_intervals(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'test.sqlite')
            try:
                base=datetime(2026,10,21,1,0,tzinfo=timezone.utc)
                for seconds in (0,15,120):
                    at=(base+timedelta(seconds=seconds)).isoformat()
                    night.record(store,states(at),at)
                report=night.summarize(store,'2026-10-21')
                self.assertEqual(report['covered_minutes'],.25)
                self.assertAlmostEqual(report['energy']['ev_kwh_ac'],.0458,places=4)
                self.assertEqual(report['active_sample_count'],3)
                self.assertEqual(report['frozen_session']['target_soc_pct'],80)
            finally:store.close()

    def test_no_collection_outside_window(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'test.sqlite')
            try:self.assertIsNone(night.record(store,[], '2026-10-21T15:00:00+00:00'))
            finally:store.close()


if __name__=='__main__':unittest.main()
