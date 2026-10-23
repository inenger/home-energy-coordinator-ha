"""Independent counterexamples, conservation checks and whole-window replay."""
import random,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from energy import night,priority,priority_audit as audit
from energy.store import Store,pack
from test_priority import inputs,points,AT
from test_night import archive
from test_priority_audit import histories,DAY,AT as DAY_AT


class FinalAuditTests(unittest.TestCase):
    def test_small_ev_request_cannot_be_inflated_or_overload_phase(self):
        for demand in (1,99,100,200,300,301,4139.99,4140,4141):
            pp=points(inputs());pp['ev_w']['value']=demand
            for i in (1,2,3):
                pp[f'ev_l{i}_w']['value']=demand/3
                pp[f'inverter_l{i}_w']['value']=4300
                pp[f'grid_l{i}_w']['value']=0
            r=priority.allocate(pp,AT,{'forecast_kwh':20,'target_soc_pct':0},60,'ev')
            self.assertLessEqual(r['ev_ac_w'],demand)
            self.assertTrue(all(p['planned_model_a']<=22 for p in r['phase']))
            self.assertTrue(r['ev_ac_w']==0 or r['ev_ac_w']>=4140)

    def test_randomized_allocations_conserve_demand_and_phase_budget(self):
        rng=random.Random(5722)
        for _ in range(3000):
            pp=points(inputs());demand=rng.uniform(0,20000);pp['ev_w']['value']=demand
            for i in (1,2,3):
                u=rng.uniform(200,250);base=rng.uniform(0,4200)
                pp[f'voltage_l{i}_v']['value']=u
                pp[f'ev_l{i}_w']['value']=demand/3
                pp[f'inverter_l{i}_w']['value']=base+demand/3
                pp[f'grid_l{i}_w']['value']=0
            pp['battery_limit_a']['value']=rng.uniform(0,50)
            r=priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},rng.uniform(0,100),rng.choice(('ev','battery')))
            if r['ev_ac_w'] is None:continue
            self.assertGreaterEqual(r['ev_ac_w'],0);self.assertLessEqual(r['ev_ac_w'],demand+1e-9)
            self.assertGreaterEqual(r['battery_ac_w'],0)
            self.assertLessEqual(r['ev_ac_w']+r['battery_ac_w'],3*min(p['budget_w'] for p in r['phase'])+1e-8)
            for p in r['phase']:self.assertLessEqual(p['planned_w'],22*p['voltage_v']*.9+.11)

    def test_delayed_sample_stops_at_target_and_conserves_ac_energy(self):
        for dt in (15,30):
            m=priority.empty_model(79.99)
            priority.advance(m,{'active':True,'ev_ac_w':4000,'battery_ac_w':1000,'grid_model_w':7000,
                                'ev_reallocated_w':500,'target_soc_pct':80},dt,('a','b'))
            self.assertAlmostEqual(m['soc_pct'],80)
            self.assertAlmostEqual(m['battery_kwh_ac'],.01/100*10.4/.9)
            self.assertAlmostEqual(m['grid_kwh_ac']-m['battery_kwh_ac'],6000*dt/3600000)
            self.assertAlmostEqual(m['ev_kwh_ac'],4000*dt/3600000)
            self.assertEqual(m['target_limited_intervals'],1)

    def test_equal_duration_different_intervals_is_not_comparable(self):
        models={k:priority.empty_model(60) for k in ('ev','battery','selected')}
        self.assertEqual(priority.comparison_status(models),'no_coverage')
        prev={'active':True,'ev_ac_w':0,'battery_ac_w':0,'grid_model_w':1000}
        for k,m in models.items():priority.advance(m,prev,15,('00','15') if k!='battery' else ('15','30'))
        self.assertEqual({m['covered_s'] for m in models.values()},{15})
        self.assertEqual(priority.comparison_status(models),'unequal_coverage')
        models['battery']['coverage_fingerprint']=None
        self.assertEqual(priority.comparison_status(models),'coverage_identity_unverified')

    def test_midnight_restart_finalizes_closed_previous_night(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db)
            archive(st,'2026-10-22T22:01:00+00:00');night.record(st,inputs(),AT)
            priority.observe(st,inputs(),AT)
            self.assertEqual(priority.closed_days(st,AT),[])
            self.assertEqual(priority.closed_days(st,'2026-10-23T22:15:00+00:00'),['2026-10-23'])
            summary=priority.finish(st,'2026-10-23')
            self.assertEqual(summary['comparison_status'],'no_coverage')
            self.assertEqual(priority.closed_days(st,'2026-10-23T22:15:00+00:00'),[])
            st.close()

    def test_complete_night_across_autumn_clock_change_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'x.sqlite';st=Store(path);night.ensure_schema(st.db)
            archive(st,'2026-10-24T22:01:00+00:00')
            start=datetime.fromisoformat('2026-10-25T02:00:00+00:00')
            for i in range(480):
                at=(start+timedelta(seconds=15*i)).isoformat();ss=inputs(at)
                if i==0:night.record(st,ss,at)
                if i==240:st.close();st=Store(path)
                priority.observe(st,ss,at)
            summary=priority.finish(st,'2026-10-25')
            self.assertEqual(summary['comparison_status'],'same_covered_intervals')
            self.assertAlmostEqual(summary['observed_ev_kwh_ac'],22)
            for m in summary['models'].values():
                self.assertEqual(m['covered_s'],7200)
                self.assertLessEqual(m['soc_pct'],80.0000001)
                self.assertGreater(m['soc_pct'],79.9)
            self.assertEqual(summary['device_actions'],0);st.close()

    def test_partial_daily_history_retries_and_keeps_both_sources(self):
        class Client:
            calls=0
            def energy_day_history(self,day):
                self.calls+=1;return [] if self.calls==1 else histories()
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db);priority.schema(st.db)
            c=Client();audit.update_day_audit(st,c,DAY_AT)
            self.assertTrue(audit.day_summary(st,DAY_AT)['days'][0]['missing_measurements'])
            audit.update_day_audit(st,c,'2026-10-22T10:10:00+00:00')
            self.assertEqual(audit.day_summary(st,DAY_AT)['days'][0]['export_kwh'],10)
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM priority_day_audit_revisions').fetchone()[0],2)
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM objects WHERE kind=?',('priority_day_history',)).fetchone()[0],2)
            audit.update_day_audit(st,c,'2026-10-22T10:20:00+00:00')
            self.assertEqual(c.calls,2);st.close()

    def test_history_catchup_prioritizes_missed_days_and_skips_fast_window(self):
        class Client:
            calls=[]
            def energy_day_history(self,day):self.calls.append(day);return []
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db);priority.schema(st.db)
            with st.db:st.db.execute('INSERT INTO priority_events VALUES(?,?)',('2026-10-21T12:00:00+00:00',pack({'priority':'ev'})))
            c=Client();audit.update_day_audit(st,c,'2026-10-24T01:30:00+00:00')
            self.assertEqual(c.calls,[])
            for i in range(3):audit.update_day_audit(st,c,f'2026-10-24T10:{i}0:00+00:00')
            self.assertEqual(c.calls,['2026-10-23','2026-10-22','2026-10-21']);st.close()

    def test_soc_unit_change_and_unpaired_export_are_unknown(self):
        h=histories();h[-2][2]['attributes']['unit_of_measurement']='kWh'
        r=audit.evaluate_day(DAY,h,DAY_AT)
        self.assertIsNone(r['soc_max']);self.assertIsNone(r['export_at_high_soc_kwh'])
        h=histories();r=audit.evaluate_day(DAY,h,DAY_AT)
        self.assertEqual(r['export_paired_kwh'],0)
        self.assertIsNone(r['export_at_high_soc_kwh'])

    def test_quality_covers_phase_power_and_matches_battery_voltage_ttl(self):
        pp=priority.checked_points(inputs(),AT);pp['battery_v']['age_seconds']=3600
        pp['grid_l2_w']['age_seconds']=1000
        q={r['key']:r for r in priority.input_quality(pp)['rows']}
        self.assertTrue(q['battery_v']['usable']);self.assertEqual(q['battery_v']['max_age_seconds'],7200)
        self.assertFalse(q['grid_l2_w']['usable'])
        self.assertTrue(all(f'ev_l{i}_w' in q for i in (1,2,3)))

    def test_future_forecast_timestamp_cannot_freeze_a_session(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db)
            archive(st,'2026-10-22T22:01:00+00:00');ss=inputs()
            for s in ss:
                if s['entity_id']==night.IDS['forecast_today']:s['last_reported']='2026-10-23T02:00:00+00:00'
            r=priority.observe(st,ss,AT)
            self.assertIsNone(r['session']['forecast_kwh'])
            self.assertEqual(r['selected']['reason'],'missing_frozen_forecast');st.close()

    def test_yesterdays_tomorrow_forecast_cannot_be_labeled_as_next_day(self):
        at='2026-10-23T12:00:00+00:00';ss=inputs(at)
        from test_night import state
        ss.append(state(priority.EXTRA['forecast_tomorrow'],8,'2026-10-22T21:59:00+00:00'))
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db)
            r=priority.observe(st,ss,at)
            self.assertIsNone(r['next_forecast_kwh'])
            q={p['key']:p for p in r['input_quality']['rows']}
            self.assertEqual(q['forecast_tomorrow']['quality'],'wrong_day');st.close()

    def test_bad_voltage_numeric_and_negative_house_balance_are_not_valid(self):
        ss=inputs()
        for s in ss:
            if s['entity_id']==night.IDS['battery_v']:s['state']='NaN'
            if s['entity_id']==night.IDS['voltage_l1_v']:s['state']='20'
        pp=priority.checked_points(ss,AT)
        self.assertEqual(pp['battery_v']['quality'],'invalid_numeric')
        self.assertEqual(pp['voltage_l1_v']['quality'],'out_of_range')
        pp=points(inputs());pp['grid_l1_w']['value']=5000;pp['inverter_l1_w']['value']=0
        r=priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},60,'ev')
        self.assertEqual(r['reason'],'inconsistent_house_balance');self.assertIsNone(r['ev_ac_w'])

    def test_incomplete_night_soc_is_not_published_as_model_at_05(self):
        class Client:
            def energy_day_history(self,day):return histories()
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db);priority.schema(st.db)
            with st.db:st.db.execute('INSERT INTO priority_summaries VALUES(?,?)',(DAY,pack({'models':{'selected':{'soc_pct':80,'covered_s':300}}})))
            audit.update_day_audit(st,Client(),DAY_AT)
            r=audit.day_summary(st,DAY_AT)['days'][0]
            self.assertIsNone(r['model_soc_05']);self.assertEqual(r['model_soc_at_covered_end'],80)
            self.assertEqual(r['model_covered_s'],300);st.close()


if __name__=='__main__':unittest.main()
