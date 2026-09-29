import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from energy.core import *
from energy.store import Store
from energy.collector import ReadOnlyHA
from energy.simulator import Model,State,step,trip,compare_terminal,residual_non_ev,demo

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.spec={'entity_id':'sensor.x','unit':'W','min':0,'max':10000,'required_for_quality':True}
    def s(self,v,unit='W'): return {'state':v,'attributes':{'unit_of_measurement':unit}}
    def test_missing(self): self.assertEqual(normalize(self.spec,None)['quality'],'missing')
    def test_unavailable_not_zero(self): self.assertIsNone(normalize(self.spec,self.s('unavailable'))['value'])
    def test_nan(self): self.assertEqual(normalize(self.spec,self.s('NaN'))['quality'],'invalid_number')
    def test_infinity(self): self.assertEqual(normalize(self.spec,self.s('inf'))['quality'],'invalid_number')
    def test_units(self): self.assertEqual(normalize(self.spec,self.s('2','kW'))['value'],2000)
    def test_bad_units(self): self.assertEqual(normalize(self.spec,self.s('2','A'))['quality'],'unit_mismatch')
    def test_negative(self): self.assertEqual(normalize(self.spec,self.s('-1'))['quality'],'out_of_range')
    def test_stale_unchanged_not_assumed(self): self.assertEqual(normalize(self.spec,self.s('0'))['source_freshness'],'not_proven_by_poll')
    def test_no_naive_time(self): self.assertRaises(ValueError,instant,'2026-09-28T12:00:00')
    def test_season_vs_tariff(self):
        s=season_context('2026-09-28T12:00:00+00:00'); self.assertEqual((s['season'],s['tariff_season']),('autumn','summer'))
    def test_march(self):
        s=season_context('2026-03-10T12:00:00+00:00'); self.assertEqual((s['season'],s['tariff_season']),('spring','winter'))
    def test_dst_fold(self):
        a=instant('2026-10-25T02:30:00+02:00'); b=instant('2026-10-25T02:30:00+01:00'); self.assertEqual((b-a).total_seconds(),3600)
    def test_dst_spring(self): self.assertEqual(season_context('2026-03-29T01:30:00+00:00')['local_date'],'2026-03-29')
    def test_no_services(self): self.assertRaises(ValueError,ReadOnlyHA('http://localhost','/not-used').get,'/api/services/switch/turn_on')
    def test_no_arbitrary_read(self): self.assertRaises(ValueError,ReadOnlyHA('http://localhost','/not-used').get,'/api/states/lock.front')
    def test_no_credential_url(self): self.assertRaises(ValueError,ReadOnlyHA,'http://user:secret@localhost','none')
    def test_gap_no_fabrication(self): self.assertIsNone(interval_energy(1,2,300))
    def test_reset_not_new_consumption(self): self.assertIsNone(interval_energy(20,0,60))
    def test_known_delta(self): self.assertEqual(interval_energy(1,1.5,60),.5)
    def test_privacy(self):
        sample=build_sample([{'entity_id':'sensor.phone','state':'address','attributes':{'latitude':1}}],{'p':self.spec},'2026-09-28T10:00:00+00:00','2026-09-28T09:59:59+00:00','h')
        self.assertNotIn('latitude',canonical(sample)); self.assertNotIn('address',canonical(sample))
    def test_unknown_parameters_block(self):
        d=evaluate({'observed_at':'2026-09-28T10:00:00+00:00','season':'autumn','tariff_season':'summer','config_hash':'x','quality':{'missing_required':[]}},
                   {'missing_approvals':{'reserve':None},'ev_low_pv_rule':{'enabled':False}})
        self.assertEqual(d['executed_actions'],[]); self.assertIsNone(d['financial_savings_czk'])
    def test_version_asof(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'s.sqlite')
            for i,value in enumerate((10,20,10)):
                at=f'2026-09-28T0{i}:00:00+00:00'; s=build_sample([],{},at,at,'h')
                st.record(s,{},[('f',{'forecast':value})],{})
            self.assertIsNone(st.available_forecast('f','2026-09-27T23:59:59+00:00'))
            self.assertEqual(st.available_forecast('f','2026-09-28T01:30:00+00:00')['payload']['forecast'],20)
            self.assertEqual(st.summary()['forecast_versions'],3)
            self.assertEqual(st.available_forecast('f','2026-09-28T02:30:00+00:00')['payload']['forecast'],10)
            self.assertEqual(st.summary()['samples'],3); st.close()
    def test_export_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'s.sqlite'); at='2026-09-28T00:00:00+00:00'
            st.record(build_sample([],{},at,at,'h'),{},[],{})
            x=st.export('2026-09-28'); h=x.pop('content_sha256'); self.assertEqual(h,digest(x)); st.close()

class SimulatorTests(unittest.TestCase):
    def setUp(self): self.m=Model(10,2,60,.95,.9,.9); self.s=State(5,20)
    def runstep(self,**kw):
        options=dict(hours=.25,base_phase_kw=(1,1,1),pv_ac_phase_kw=(0,0,0),buy_price=2)
        options.update(kw); return step(self.s,self.m,**options)
    def test_no_mutation(self): self.runstep(requested_battery_kw=3); self.assertEqual(self.s.battery_kwh,5)
    def test_charge_losses(self):
        new,row=self.runstep(requested_battery_kw=4); self.assertAlmostEqual(new.battery_kwh,5.95); self.assertAlmostEqual(row['battery_loss_kwh'],.05)
    def test_discharge_losses(self):
        new,row=self.runstep(requested_battery_kw=-3.6); self.assertAlmostEqual(new.battery_kwh,4); self.assertAlmostEqual(row['battery_loss_kwh'],.1)
    def test_balance(self):
        new,r=self.runstep(requested_battery_kw=2,requested_ev_kw=5,pv_ac_phase_kw=(.1,.5,1)); self.assertAlmostEqual(r['energy_balance_error_kw'],0)
    def test_reserve(self):
        new,r=self.runstep(requested_battery_kw=-100,hours=1); self.assertGreaterEqual(new.battery_kwh,2)
    def test_full_battery(self):
        s,r=step(State(9.9,20),self.m,hours=1,base_phase_kw=(0,0,0),pv_ac_phase_kw=(0,0,0),requested_battery_kw=10); self.assertAlmostEqual(s.battery_kwh,10)
    def test_competing_loads(self):
        new,r=self.runstep(requested_battery_kw=5,requested_ev_kw=11.04); self.assertLessEqual(max(r['phase_import_a']),25+1e-9)
    def test_unbalanced_phase(self):
        new,r=self.runstep(base_phase_kw=(5,.2,.2),requested_ev_kw=11.04); self.assertEqual(r['ev_ac_kw'],0)
    def test_preexisting_overload(self):
        new,r=self.runstep(base_phase_kw=(6,0,0)); self.assertIn('BASE_LOAD_ALREADY_EXCEEDS_IMPORT_LIMIT',r['flags'])
    def test_no_v2h(self): self.assertRaises(ValueError,self.runstep,requested_ev_kw=-1)
    def test_disconnected(self):
        n,r=self.runstep(requested_ev_kw=10,ev_connected=False); self.assertEqual(n.ev_kwh,20)
    def test_export_cap(self):
        n,r=self.runstep(base_phase_kw=(0,0,0),pv_ac_phase_kw=(8,8,8)); self.assertLessEqual(r['grid_export_kwh']/.25,10+1e-9); self.assertAlmostEqual(r['energy_balance_error_kw'],0)
    def test_ev_capacity(self):
        n,r=step(State(5,59.99),self.m,hours=.25,base_phase_kw=(0,0,0),pv_ac_phase_kw=(0,0,0),requested_ev_kw=11); self.assertLessEqual(n.ev_kwh,60)
    def test_small_remaining_charge_skipped(self):
        n,r=step(State(5,59.99),self.m,hours=.25,base_phase_kw=(0,0,0),pv_ac_phase_kw=(0,0,0),requested_ev_kw=11); self.assertIn('EV_BELOW_MINIMUM_POWER',r['flags'])
    def test_efficiency_invalid(self): self.assertRaises(ValueError,Model,10,2,60,1.1,.9,.9)
    def test_reserve_invalid(self): self.assertRaises(ValueError,Model,10,20,60,.9,.9,.9)
    def test_no_free_trip(self):
        n,short=trip(State(5,2),3); self.assertEqual(n.ev_kwh,0); self.assertEqual(short,1)
    def test_terminal_difference_visible(self): self.assertFalse(compare_terminal(State(2,3),State(4,3))['terminal_comparable'])
    def test_subtract_actual_ev(self): self.assertEqual(residual_non_ev(11,9),2)
    def test_negative_residual_rejected(self): self.assertRaises(ValueError,residual_non_ev,2,10)
    def test_demo_not_real_savings(self):
        r=demo(); self.assertIsNone(r['real_household_savings_czk']); self.assertTrue(r['comparison']['terminal_comparable'])

if __name__=='__main__': unittest.main()

class PublishSafetyTests(unittest.TestCase):
    def test_refuse_actuator_entity(self):
        from energy.publish_status import request
        self.assertRaises(ValueError,request,'switch.anything',{'state':'on'},'http://ha','not-a-real-token')
    def test_refuse_unapproved_prefix_member(self):
        from energy.publish_status import request
        self.assertRaises(ValueError,request,'sensor.energie_v3_other',{'state':'0'},'http://ha','not-a-real-token')
    def test_status_only_exact_path(self):
        from energy.publish_status import request,IDS
        req=request(IDS[0],{'state':'běží','attributes':{}},'http://ha','not-a-real-token')
        self.assertEqual(req.full_url,'http://ha/api/states/'+IDS[0]); self.assertEqual(req.method,'POST')
