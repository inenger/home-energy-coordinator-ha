import unittest,tempfile,json
from pathlib import Path
from datetime import datetime,timedelta
from energy import priority,night,priority_audit as audit
from energy.store import Store,pack,unpack
from test_priority import inputs,points,AT
from test_night import archive
from test_priority_audit import histories,DAY,AT as DAY_AT,series

class RegressionTests(unittest.TestCase):
    def test_policy_boundaries_match_displayed_soc_rules(self):
        self.assertEqual([night.target_for(v) for v in (0,4.999,5,9.999,10,14.999,15,30)],[90,90,80,80,70,70,30,30])

    def test_rounding_never_proposes_below_six_amps(self):
        pp=points(inputs());demand=6*3*230
        pp['ev_w']['value']=demand
        for i in (1,2,3):pp[f'ev_l{i}_w']['value']=demand/3
        r=priority.allocate(pp,AT,{'forecast_kwh':20,'target_soc_pct':0},60,'ev')
        self.assertEqual(r['ev_ac_w'],demand)

    def test_phase_measurements_survive_missing_wallbox(self):
        pp=points(inputs());pp['ev_l1_w']['age_seconds']=1000
        r=priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},60,'ev')
        self.assertIsNotNone(r['phase'][0]['house_w'])
        self.assertEqual(r['reason'],'invalid_ev_input');self.assertIsNone(r['ev_ac_w'])

    def test_base_overload_and_single_phase_are_blocked(self):
        pp=points(inputs());pp['inverter_l1_w']['value']=20000
        self.assertEqual(priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},60,'ev')['reason'],'base_load_over_limit')
        pp=points(inputs())
        for i in (1,2,3):pp[f'ev_l{i}_w']['value']=11000 if i==1 else 0;pp[f'inverter_l{i}_w']['value']=10000 if i==1 else 1000
        self.assertEqual(priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},60,'ev')['reason'],'unsupported_ev_phase_layout')

    def test_missing_units_and_out_of_range_soc_are_rejected(self):
        ss=inputs()
        for r in ss:
            if r['entity_id']==night.IDS['grid_l1_w']:r['attributes']['unit_of_measurement']='kW'
            if r['entity_id']==night.IDS['battery_soc']:r['state']='999'
        pp=priority.checked_points(ss,AT)
        self.assertEqual(pp['grid_l1_w']['quality'],'unit_mismatch')
        self.assertEqual(pp['battery_soc']['quality'],'out_of_range')
        self.assertEqual(priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},60,'ev')['reason'],'invalid_phase_input')

    def test_soc_recovers_and_missing_forecast_retries_without_rewriting(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db)
            ss=inputs(soc='unavailable');night.record(st,ss,AT)
            old=st.db.execute('SELECT payload FROM night_sessions').fetchone()[0]
            first=priority.observe(st,ss,AT)
            self.assertIsNone(first['progress']['models']['selected']['soc_pct'])
            at='2026-10-23T01:00:15+00:00';archive(st,at)
            later=priority.observe(st,inputs(at,soc=60),at)
            self.assertEqual(later['selected']['reason'],'ev_first')
            self.assertEqual(later['session']['captured_at'],at)
            self.assertEqual(later['progress']['soc_initialized_at'],at)
            self.assertEqual(st.db.execute('SELECT payload FROM night_sessions').fetchone()[0],old)
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM priority_sessions').fetchone()[0],1)
            st.close()

    def test_source_units_are_retained_and_ui_payload_does_not_duplicate_raw_archive(self):
        from energy.publish_status import priority_plan_view,priority_history_view
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db);archive(st,'2026-10-22T22:01:00+00:00')
            night.record(st,inputs(),AT);r=priority.observe(st,inputs(),AT)
            raw=unpack(st.db.execute('SELECT payload FROM priority_samples').fetchone()[0])
            self.assertEqual(raw['inputs']['ev_w']['unit'],'W')
            view=priority_plan_view(r)
            self.assertNotIn('inputs',view['progress']);self.assertNotIn('history',view)
            summary=priority.finish(st,'2026-10-23');history=priority_history_view([summary]*14)
            self.assertLess(len(json.dumps(history).encode()),14000)
            st.close()

    def test_full_soc_endpoints_do_not_hide_mid_interval_dip_or_unknown(self):
        h=histories();h[0]=series(audit.HISTORY_IDS['export_kwh'],'kWh',[(0,0),(12,0),(12.1,1),(23,5)])
        for middle in (30,'unavailable'):
            h[-2]=series(audit.HISTORY_IDS['soc'],'%',[(0,20),(12,100),(12.04,middle),(12.08,100),(23,60)])
            r=audit.evaluate_day(DAY,h,DAY_AT)
            self.assertEqual(r['export_at_high_soc_kwh'],0 if middle==30 else None)

    def test_daily_evaluation_revision_keeps_original_report_and_raw_source(self):
        from energy.core import digest
        class NoNetwork:
            def energy_day_history(self,day):raise AssertionError('Must use archived source')
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db);priority.schema(st.db);audit.schema(st.db)
            data=histories();h=digest(data);original={'day':DAY,'source_hash':h,'calculated_at':DAY_AT,'soc_end':999}
            with st.db:
                st.db.execute('INSERT INTO objects VALUES(?,?,?)',(h,'priority_day_history',pack(data)))
                st.db.execute('INSERT INTO priority_day_audits VALUES(?,?)',(DAY,pack(original)))
            audit.update_day_audit(st,NoNetwork(),DAY_AT)
            self.assertEqual(unpack(st.db.execute('SELECT payload FROM priority_day_audits').fetchone()[0]),original)
            report=audit.day_summary(st,DAY_AT)['days'][0]
            self.assertEqual(report['soc_end'],30);self.assertFalse(report['measurement_boundary_verified'])
            self.assertEqual(report['source_hash'],h)
            audit.update_day_audit(st,NoNetwork(),DAY_AT)
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM priority_day_audit_revisions').fetchone()[0],1)
            st.close()

if __name__=='__main__':unittest.main()
