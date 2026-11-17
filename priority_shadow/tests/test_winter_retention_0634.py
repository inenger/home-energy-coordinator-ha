"""0.6.34 acceptance: winter desired SOC and lossless sealed night retention.

All fixture inputs are synthetic. Historical private replay runs separately on RPi.
"""
import unittest
from datetime import datetime,timedelta,timezone

from energy import night,evidence_retention as ret
from energy.store import pack,unpack
from energy.soc_planner import plan
from energy.soc_runtime import view,inputs as runtime_inputs
from energy.soc_evidence import verify
from test_soc_planner import fixture
from test_compaction_retention_0633 import TieredRetention


class WinterIntent(unittest.TestCase):
    def calc(self,*,temperature=-2,pv=15.3,house=1.4,ev=31.7,priority='ev',heat_pump=1400):
        now,inp,h,v,profile=fixture(season='winter',pv=pv,house=house,ev=ev)
        inp.update(outdoor_c=temperature,priority=priority,heat_pump_w=heat_pump)
        return plan(now,inp,h,{},profile,v)

    def test_frost_15kwh_heating_wants_100_but_keeps_ev_and_no_actions(self):
        r=self.calc()
        self.assertEqual(r['status'],'partial_shadow_plan')
        self.assertEqual(r['target_soc_pct'],100)
        self.assertEqual(r['desired_target_soc_pct'],100)
        self.assertIn(r['winter_demand']['status'],
                      ('cold_deficit','severe_energy_deficit'))
        self.assertIn(r['decision_reason'],
                      ('winter_cold_load_adequacy','severe_energy_deficit'))
        self.assertIsNone(r['physical_charge_target_soc_pct'])
        self.assertEqual(r['device_actions'],0)
        self.assertFalse(r['live_ready'])
        self.assertTrue(verify(r)['verified'])
        self.assertLess(r['attainable_soc_05_pct'],100)
        self.assertGreater(r['target_shortfall_soc_pct']['central'],0)
        self.assertGreater(r['ev_deficit_ac_kwh']['central'],0)
        compact=view(r)
        for key in ('winter_demand','desired_target_soc_pct','economic_target_soc_pct',
                    'attainable_soc_05_pct','physical_charge_target_soc_pct'):
            self.assertIn(key,compact)
        self.assertEqual(compact['device_actions'],0)

    def test_warm_5c_low_pv_and_high_house_need_100(self):
        r=self.calc(temperature=5.2,pv=3.1642,house=1.4)
        self.assertEqual(r['winter_demand']['status'],'severe_energy_deficit')
        self.assertEqual(r['target_soc_pct'],100)
        self.assertEqual(r['desired_target_soc_pct'],100)
        self.assertEqual(r['decision_reason'],'severe_energy_deficit')
        self.assertTrue(r['winter_demand']['energy_deficit_condition_met'])
        self.assertFalse(r['winter_demand']['cold_condition_met'])
        self.assertIsNone(r['physical_charge_target_soc_pct'])
        self.assertEqual(r['device_actions'],0)
        self.assertLess(r['attainable_soc_05_pct'],100)
        self.assertTrue(verify(r)['verified'])
        self.assertEqual(view(r)['desired_target_soc_pct'],100)

    def test_warm_high_load_is_energy_driven_not_falsely_cold(self):
        r=self.calc(temperature=12,pv=15.3,house=1.4)
        self.assertEqual(r['winter_demand']['status'],'severe_energy_deficit')
        self.assertFalse(r['winter_demand']['cold_condition_met'])
        self.assertEqual(r['desired_target_soc_pct'],100)

    def test_warm_high_pv_ordinary_economic(self):
        r=self.calc(temperature=12,pv=65,house=1)
        self.assertEqual(r['winter_demand']['status'],'ordinary_economic_plan')
        self.assertIsNone(r['winter_demand']['desired_target_soc_pct'])
        self.assertEqual(r['desired_target_soc_pct'],r['economic_target_soc_pct'])

    def test_missing_temperature_with_energy_shortfall_can_still_trigger(self):
        r=self.calc(temperature=None,pv=3.1642)
        self.assertEqual(r['winter_demand']['temperature_source'],'no_cold_evidence')
        self.assertEqual(r['winter_demand']['status'],'severe_energy_deficit')
        self.assertEqual(r['target_soc_pct'],100)

    def test_missing_temperature_and_no_energy_shortfall_stays_economic(self):
        r=self.calc(temperature=None,pv=65,house=1)
        self.assertEqual(r['winter_demand']['temperature_source'],'no_cold_evidence')
        self.assertEqual(r['winter_demand']['status'],'no_temperature_asof')
        self.assertEqual(r['target_soc_pct'],r['economic_target_soc_pct'])

    def test_cold_abundant_pv_does_not_force_full(self):
        r=self.calc(temperature=-3,pv=65,house=1)
        self.assertEqual(r['winter_demand']['status'],'ordinary_economic_plan')
        self.assertIsNone(r['winter_demand']['desired_target_soc_pct'])

    def test_pump_watts_only_corrobate_never_double_count(self):
        a=self.calc(heat_pump=None)
        b=self.calc(heat_pump=2300)
        self.assertAlmostEqual(a['winter_demand']['forecast_house_central_kwh'],
                               b['winter_demand']['forecast_house_central_kwh'])
        self.assertEqual(a['winter_demand']['stress_net_demand_kwh'],
                         b['winter_demand']['stress_net_demand_kwh'])
        self.assertEqual(b['winter_demand']['heat_pump_evidence'],'running')

    def test_user_battery_priority_kept_but_not_a_physical_command(self):
        r=self.calc(priority='battery')
        self.assertEqual(r['target_soc_pct'],100)
        self.assertEqual(r['input_snapshot']['priority'],'battery')
        self.assertEqual(r['device_actions'],0)
        deficits=[v['unserved_ev_ac_kwh'] for v in r['selected']['scenarios'].values()]
        if max(deficits)>.05:
            self.assertEqual(r['status'],'partial_shadow_plan')
            self.assertEqual(r['economic_comparison'],'unequal_ev_service_no_savings_claim')

    def test_bt28_fallback_and_stale_heatpump(self):
        at='2026-11-15T01:55:00+00:00'
        def sensor(eid,value,unit,age=0):
            t=(datetime.fromisoformat(at)-timedelta(seconds=age)).isoformat()
            return {'entity_id':eid,'state':str(value),'last_reported':t,
                    'last_updated':t,'attributes':{'unit_of_measurement':unit}}
        from energy.soc_runtime import IDS,observation
        states=[sensor(IDS['outdoor_c'],'unavailable','°C'),
                sensor(IDS['outdoor_secondary_c'],-2.3,'°C'),
                sensor(IDS['heat_pump_w'],1250,'W'),
                sensor(IDS['house_w'],1900,'W')]
        ob=observation(states,at)
        self.assertEqual(ob['outdoor_c'],-2.3)
        self.assertEqual(ob['outdoor_c_source'],'BT28')
        self.assertEqual(ob['heat_pump_w'],1250)
        stale=[dict(s,last_reported='2026-11-14T00:00:00+00:00')
               if s['entity_id']==IDS['heat_pump_w'] else s for s in states]
        self.assertIsNone(observation(stale,at)['heat_pump_w'])


def fake_night(db,day='2026-10-20',complete=True):
    night.ensure_schema(db)
    db.execute('INSERT OR IGNORE INTO night_sessions VALUES(?,?)',
               (day,pack({'day':day,'status':'captured','target_soc_pct':80})))
    start=datetime(2026,10,20,1,0,tzinfo=timezone.utc)
    for n in range(481 if complete else 12):
        at=(start+timedelta(seconds=n*15)).isoformat()
        points={k:{'quality':'valid','age_seconds':0,'value':50 if k=='battery_soc'
                         else 0 if k=='battery_dc_w' else -1000 if k.startswith('grid_l')
                         else 1500} for k in ('house_w','ev_w','battery_soc','battery_dc_w',
                                               'grid_l1_w','grid_l2_w','grid_l3_w')}
        row={'day':day,'at':at,'points':points,
             'shadow':{'proposed_ac_w':0,'reason':'room_available',
                       'phase':[{'model_room_w':123}]*3}}
        db.execute('INSERT OR REPLACE INTO night_samples VALUES(?,?,?)',(at,day,pack(row)))
    db.commit()


class SealedRetention(unittest.TestCase):
    def prepare(self,complete=True):
        db,store=TieredRetention().fixture()
        db.execute('DELETE FROM night_summaries')
        db.execute('DELETE FROM night_samples')
        fake_night(db,complete=complete)
        return db,store

    def test_backfill_then_retention_full_chain(self):
        db,store=self.prepare()
        pre=db.execute('SELECT count(*) FROM night_samples').fetchone()[0]
        self.assertEqual(pre,481)
        self.assertEqual(night.finalize_pending(store,'2026-10-20T03:03:00+00:00')['status'],
                         'skipped_night_window')
        self.assertIsNone(db.execute('SELECT 1 FROM night_summaries').fetchone())
        state=night.finalize_pending(store,'2026-10-20T03:06:00+00:00')
        self.assertEqual(state['days'][0]['status'],'sealed')
        sealed=unpack(db.execute('SELECT payload FROM night_summaries').fetchone()[0])
        self.assertEqual(sealed['source_rows_count'],481)
        self.assertAlmostEqual(sealed['covered_minutes'],119.75)
        self.assertTrue(ret._day_finalized(db,'2026-10-20','night_summaries'))
        self.assertEqual(night.finalize_pending(store,'2026-11-13T10:00:00+00:00')['days'],[])
        output=ret.prune(store,'2026-11-13T11:00:00+00:00',force=True)
        self.assertEqual(output['removed']['night_samples'],481)
        self.assertEqual(db.execute('SELECT count(*) FROM night_samples').fetchone()[0],0)
        self.assertEqual(unpack(db.execute('SELECT payload FROM night_summaries').fetchone()[0]),sealed)
        self.assertEqual(db.execute('SELECT count(*) FROM journal_transport_archive').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM ram_control_events').fetchone()[0],1)
        db.close()

    def test_partial_night_never_authorizes_retention(self):
        db,store=self.prepare(complete=False)
        r=night.finalize_pending(store,'2026-10-20T03:06:00+00:00')
        self.assertEqual(r['days'][0]['status'],'incomplete')
        self.assertFalse(ret._day_finalized(db,'2026-10-20','night_summaries'))
        ret.prune(store,'2026-11-13T11:00:00+00:00',force=True)
        self.assertEqual(db.execute('SELECT count(*) FROM night_samples').fetchone()[0],12)
        db.close()

    def test_tamper_after_seal_retains_source_data(self):
        db,store=self.prepare()
        night.finalize_pending(store,'2026-10-20T03:06:00+00:00')
        db.execute("UPDATE night_samples SET payload=? WHERE at=(SELECT min(at) FROM night_samples)",
                   (pack({'tampered':True}),))
        self.assertFalse(ret._day_finalized(db,'2026-10-20','night_summaries'))
        ret.prune(store,'2026-11-13T11:00:00+00:00',force=True)
        self.assertEqual(db.execute('SELECT count(*) FROM night_samples').fetchone()[0],481)
        db.close()


if __name__=='__main__':
    unittest.main()
