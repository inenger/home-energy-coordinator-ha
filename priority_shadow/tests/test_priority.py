import tempfile, unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from energy import priority,night
from energy.store import Store
from test_night import states,archive,state

AT='2026-10-23T01:00:00+00:00'

def inputs(at=AT,soc=60,choice='Elektromobil'):
    ss=states(at)
    for s in ss:
        if s['entity_id']==night.IDS['battery_soc']:s['state']=str(soc)
    ss.extend(state(priority.EXTRA[f'ev_l{i}_w'],11000/3,at) for i in (1,2,3))
    ss.append(state(priority.HELPER,choice,at))
    return ss


def points(ss,at=AT):
    by={s['entity_id']:s for s in ss}
    return {k:night.point(by.get(eid),at) for k,eid in {**night.IDS,**priority.EXTRA}.items()}


class PriorityTests(unittest.TestCase):
    def test_priority_allocation_no_double_count(self):
        pp=points(inputs());session={'forecast_kwh':8.4,'target_soc_pct':80}
        ev=priority.allocate(pp,AT,session,60,'ev');bat=priority.allocate(pp,AT,session,60,'battery')
        self.assertEqual(ev['ev_ac_w'],11000)
        self.assertGreater(bat['battery_ac_w'],ev['battery_ac_w'])
        self.assertLess(bat['ev_ac_w'],ev['ev_ac_w'])
        for r in (ev,bat):
            self.assertLessEqual(r['grid_model_w'],13662)
            self.assertTrue(all(p['planned_model_a']<=22 for p in r['phase']))
            self.assertEqual(r['device_actions'],0);self.assertFalse(r['live_ready'])

    def test_30kwh_discharge_rule_and_missing_forecast(self):
        pp=points(inputs())
        for f,expected in [(29.999,True),(30,False),(None,True)]:
            r=priority.allocate(pp,AT,{'forecast_kwh':f,'target_soc_pct':0},60,'ev')
            self.assertEqual(r['forbid_discharge'],expected)
        self.assertIsNone(priority.allocate(pp,AT,None,60,'ev')['ev_ac_w'])

    def test_stale_or_mismatched_phase_not_zero(self):
        pp=points(inputs());pp['grid_l2_w']['age_seconds']=120
        r=priority.allocate(pp,AT,{'forecast_kwh':8.4,'target_soc_pct':80},60,'ev')
        self.assertEqual(r['reason'],'invalid_phase_input');self.assertIsNone(r['battery_ac_w'])
        pp=points(inputs());pp['ev_l2_w']['value']=100
        self.assertEqual(priority.allocate(pp,AT,{'forecast_kwh':8.4,'target_soc_pct':80},60,'ev')['reason'],'inconsistent_ev_phases')

    def test_minimum_ev_pauses_not_unphysical_low_current(self):
        pp=points(inputs());pp['battery_limit_a']['value']=50
        r=priority.allocate(pp,AT,{'forecast_kwh':8.4,'target_soc_pct':80},60,'battery')
        self.assertEqual(r['ev_ac_w'],0)

    def test_target_reached_and_outside_window(self):
        pp=points(inputs());r=priority.allocate(pp,AT,{'forecast_kwh':8.4,'target_soc_pct':80},80,'battery')
        self.assertEqual(r['battery_ac_w'],0);self.assertEqual(r['ev_ac_w'],11000)
        self.assertEqual(priority.allocate(pp,'2026-10-23T03:00:00+00:00',None,60,'ev')['reason'],'outside_window')

    def test_sequential_model_survives_restart_and_selection_change(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'p.sqlite';store=Store(path);night.ensure_schema(store.db)
            archive(store,'2026-10-22T22:01:00+00:00')
            night.record(store,inputs(),AT)
            a=priority.observe(store,inputs(),AT);store.close()
            store=Store(path)
            try:
                at='2026-10-23T01:00:15+00:00';night.record(store,inputs(at,soc=10),at)
                b=priority.observe(store,inputs(at,soc=10,choice='Baterie SolaX'),at)
                self.assertGreater(b['progress']['models']['selected']['soc_pct'],60)
                self.assertEqual(b['priority'],'battery')
                self.assertGreater(b['progress']['models']['selected']['covered_s'],0)
                self.assertEqual(len(priority.recent(store)['samples']),2)
                c=priority.finish(store,'2026-10-23')
                self.assertEqual(c['priority_changes'],1)
                self.assertEqual(priority.finish(store,'2026-10-23'),c)
            finally:store.close()

    def test_gap_excluded_and_missing_priority_is_not_ev(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'p.sqlite');night.ensure_schema(store.db)
            try:
                archive(store,'2026-10-22T22:01:00+00:00');night.record(store,inputs(),AT)
                priority.observe(store,inputs(),AT)
                at='2026-10-23T01:03:00+00:00'
                b=priority.observe(store,inputs(at,choice='unavailable'),at)
                self.assertEqual(b['selected']['reason'],'missing_priority')
                self.assertIsNone(b['selected']['battery_ac_w'])
                self.assertEqual(b['progress']['models']['selected']['covered_s'],0)
                self.assertEqual(b['progress']['gap_s'],180)
            finally:store.close()

    def test_measured_currents_and_margin_are_recorded_without_claiming_live_ready(self):
        ss=inputs()
        ss.extend(state(night.IDS[f'grid_l{i}_a'],v,AT) for i,v in enumerate((18,21,23),1))
        r=priority.allocate(points(ss),AT,{'forecast_kwh':8.4,'target_soc_pct':80},60,'ev')
        self.assertEqual([p['current_headroom_a'] for p in r['phase']],[4,1,-1])
        self.assertFalse(r['live_ready'])

    def test_monitoring_publisher_cannot_target_device(self):
        from energy.publish_status import request
        self.assertRaises(ValueError,request,'number.solax_battery_charge_max_current',{'state':30},'http://ha','test')
        self.assertRaises(ValueError,request,priority.HELPER,{'state':'Baterie SolaX'},'http://ha','test')
        self.assertIn('/api/states/sensor.nocni_stinovy_plan',request('sensor.nocni_stinovy_plan',{'state':'ok'},'http://ha','test').full_url)
