import unittest,copy,random,math,tempfile
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from energy import instant_fill as f,priority,priority_audit as audit
from energy.power_allocation import allocate_power
from energy.store import Store,pack
from energy.soc_runtime import schema as soc_schema
from test_night import archive
AT='2026-10-27T02:00:00+00:00'
MODEL={'charge_coordinate':[[0,0],[100,12]],'grid_charge_efficiency':.9,'source_hash':'synthetic'}
def point(x):return {'value':x,'quality':'valid','age_seconds':1,'unit':'A'}
def points(base=(460,920,230),ev=11040):
 p={k:point(v) for k,v in {'ev_w':ev,'battery_soc':11,'battery_v':230,'battery_limit_a':30}.items()}
 for i,b in enumerate(base,1):
  g=b+ev/3;p.update({f'grid_l{i}_a':point(g/230),f'grid_voltage_l{i}_v':point(230),f'grid_l{i}_w':point(-g),f'inverter_l{i}_w':point(0),f'ev_l{i}_w':point(ev/3),f'grid_l{i}_a_reported':point(-.3)})
 return p
SESSION={'allocation_policy':f.POLICY,'target_soc_pct':100,'forecast_kwh':None,'soc_plan_valid':False,'battery_energy_model':MODEL}
class FillTests(unittest.TestCase):
 def test_no_forecast_no_economic_plan_still_allocates(self):
  r=priority.allocate(points(),AT,SESSION,11,'ev');self.assertEqual(r['ev_ac_w'],11040);self.assertEqual(r['battery_ac_w'],3400);self.assertEqual(r['target_soc_pct'],100)
 def test_weakest_phase_not_total_sum(self):
  r=f.allocate(points(),AT,SESSION,11,'ev');self.assertEqual(r['binding_phase'],2);self.assertTrue(all(x['planned_model_a']<=25 for x in r['phase']))
 def test_no_api_current_substitution(self):
  p=points();p['grid_l2_a']['age_seconds']=100
  r=f.allocate(p,AT,SESSION,11,'ev');self.assertIsNone(r['battery_ac_w']);self.assertEqual(r['reason'],'invalid_phase_input')
 def test_contradictory_current_blocks(self):
  p=points();p['grid_l1_a']['value']=.3
  self.assertEqual(f.allocate(p,AT,SESSION,11,'ev')['reason'],'invalid_phase_input')
 def test_base_over_limit_blocks(self):
  r=f.allocate(points(base=(6000,920,230)),AT,SESSION,11,'ev');self.assertEqual(r['reason'],'base_load_over_limit')
 def test_bms_dc_and_ac_limit(self):
  p=points();p['battery_limit_a']['value']=3
  r=f.allocate(p,AT,SESSION,11,'ev');self.assertLessEqual(r['battery_ac_w']*.9,690)
  r=f.allocate(points(),AT,{**SESSION,'inverter_charge_ac_limit_w':1200},11,'ev');self.assertEqual(r['battery_ac_w'],1200)
 def test_full_and_nearly_full(self):
  self.assertEqual(f.allocate(points(),AT,SESSION,100,'ev')['battery_ac_w'],0)
  r=f.allocate(points(),AT,SESSION,99.99,'ev');self.assertLessEqual(r['battery_ac_w']*15/3600000,.0012/.9+1e-9)
 def test_outside_no_output(self):
  r=f.allocate(points(),'2026-10-27T04:00:00+00:00',SESSION,11,'ev');self.assertEqual(r['battery_ac_w'],0)
 def test_rounding_regression(self):self.assertEqual(allocate_power(5000,899,4500,4140,'battery'),(800,4200))
 def test_partial_battery_is_not_ev_deficit(self):self.assertEqual(priority.comparison_context({'target_soc_pct':70,'soc_plan_status':'partial_shadow_plan','ev_deficit_ac_kwh':0}),'partial_battery_target')
 def test_random_phase_limits_and_energy(self):
  rng=random.Random(65)
  for _ in range(1000):
   p=points(tuple(rng.uniform(100,2200) for i in range(3)),ev=rng.uniform(4200,11000))
   for choice in ['ev','battery']:
    r=f.allocate(p,AT,SESSION,11,choice)
    if r['battery_ac_w'] is not None:
     self.assertTrue(all(x['planned_model_a']<=25+1e-7 for x in r['phase']))
     self.assertTrue(all(x['planned_ev_w']==0 or x['planned_ev_w']/x['voltage_v']>=6-1e-7 for x in r['phase']))
     self.assertAlmostEqual(r['grid_model_w'],sum(x['base_w'] for x in r['phase'])+r['ev_ac_w']+r['battery_ac_w'])
 def test_calendar_reset_preserves_prefix(self):
  start=datetime(2026,10,25,tzinfo=ZoneInfo('Europe/Prague'))
  rows=[(start,70),(start+timedelta(minutes=59),71),(start+timedelta(hours=1),0),(start+timedelta(hours=24),100)]
  n,q=audit.daily_counter(rows,start);self.assertEqual(n,101);self.assertIn('DST',q)
 def test_ordinary_late_reset_and_multiple_resets_rejected(self):
  start=datetime(2026,10,24,tzinfo=ZoneInfo('Europe/Prague'))
  rows=[(start,70),(start+timedelta(minutes=59),71),(start+timedelta(hours=1),0),(start+timedelta(hours=23),100)]
  self.assertIsNone(audit.daily_counter(rows,start)[0])
 def test_sparse_night_counters_dst(self):
  start=datetime(2026,10,25,tzinfo=ZoneInfo('Europe/Prague'))
  rows=[(start,12.7),(start+timedelta(hours=1),0),(start+timedelta(hours=24),13)]
  self.assertEqual(audit.daily_counter(rows,start)[0],13)
 def test_deficit_dictionary(self):
  self.assertEqual(priority.comparison_context({'target_soc_pct':70,'soc_plan_status':'partial_shadow_plan','ev_deficit_ac_kwh':{'central':0}}),'partial_battery_target')
  self.assertEqual(priority.comparison_context({'target_soc_pct':70,'soc_plan_status':'partial_shadow_plan','ev_deficit_ac_kwh':{'central':1}}),'partial_ev_service')
 def test_measured_ev_tolerance_is_not_reallocated_energy(self):
  p=points(ev=11100)
  r=f.allocate(p,AT,SESSION,11,'ev');self.assertEqual(r['ev_ac_w'],11100);self.assertEqual(r['ev_reallocated_w'],0)
 def test_full_observer_path_without_soc_plan(self):
  from test_night import state
  from energy import night
  with tempfile.TemporaryDirectory() as t:
   store=Store(Path(t)/'e.sqlite');night.ensure_schema(store.db);soc_schema(store.db)
   bm={'discharge_curve':[[0,0],[50,5],[100,10]],'dc_cycle_efficiency':.9,'grid_efficiency':.9,'source_hash':'synthetic'}
   with store.db:store.db.execute('insert into soc_model_versions values(?,?,?)',('m','2026-10-26T20:00:00+00:00',pack({'at':'2026-10-26T20:00:00+00:00','battery_model':bm})))
   ss=[];mapping={**night.IDS,**priority.EXTRA}
   for k,v in points().items():
    if k in mapping:ss.append(state(mapping[k],v['value'],AT))
   ss+=[state(priority.HELPER,'Elektromobil',AT)]
   r=priority.observe(store,ss,AT,True,allocation_policy=f.POLICY)
   self.assertEqual(r['selected']['reason'],'ev_first');self.assertGreater(r['selected']['battery_ac_w'],0);self.assertEqual(r['assumptions']['phase_limit_a'],25)
   ss2=[{**x,'last_reported':'2026-10-27T02:00:15+00:00'} for x in ss]
   r=priority.observe(store,ss2,'2026-10-27T02:00:15+00:00',True,allocation_policy=f.POLICY)
   self.assertGreater(r['progress']['models']['ev']['battery_kwh_ac'],0);store.close()
