"""02:59 preflight: diagnostics only, never an early session, lease, or action."""
import unittest,tempfile
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from energy import night,priority,ram_control as control,isolated_control as iso,soc_runtime
from energy.store import Store
from test_ram_control import data
from test_instant_fill import SESSION

DAY='2026-01-15'
def at(h,m,s=0):return datetime(2026,1,15,h,m,s,tzinfo=timezone.utc).isoformat()
def plan():return {**SESSION,'day':DAY,'model_available_at':at(0,0)}

class PreflightTests(unittest.TestCase):
 def test_boundary_and_fall_back_fold(self):
  self.assertFalse(night.startup_preflight_window(at(1,58,59)))
  self.assertTrue(night.startup_preflight_window(at(1,59)))
  self.assertTrue(night.startup_preflight_window(at(1,59,59)))
  self.assertFalse(night.startup_preflight_window(at(2,0)))
  self.assertTrue(night.window(at(1,59)))
  tz=ZoneInfo('Europe/Prague')
  first=datetime(2026,10,25,2,59,30,tzinfo=tz,fold=0).astimezone(timezone.utc).isoformat()
  last=datetime(2026,10,25,2,59,30,tzinfo=tz,fold=1).astimezone(timezone.utc).isoformat()
  self.assertFalse(night.startup_preflight_window(first))
  self.assertTrue(night.startup_preflight_window(last))

 def test_analysis_prepares_model_without_opening_a_night_run(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'test.sqlite')
   try:
    soc_runtime.schema(store.db)
    with patch('energy.instant_fill.session',return_value=plan()) as session:
     row=priority.observe(store,data(at(1,59)),at(1,59),require_soc_plan=True,allocation_policy='instant-max-fill-v1')
    self.assertEqual(session.call_count,1)
    self.assertEqual(row['session']['battery_energy_model'],SESSION['battery_energy_model'])
    self.assertFalse(row['active'])
    self.assertEqual(row['selected']['reason'],'outside_window')
    self.assertEqual(row['device_actions'],0)
    self.assertEqual(store.db.execute('SELECT COUNT(*) FROM priority_runs').fetchone()[0],0)
    self.assertEqual(store.db.execute('SELECT COUNT(*) FROM priority_samples').fetchone()[0],0)
    earlier=priority.observe(store,data(at(1,58)),at(1,58),require_soc_plan=True,allocation_policy='instant-max-fill-v1')
    self.assertIsNone(earlier['session'])
   finally:store.close()

 def test_missing_model_then_prepared_and_no_early_lease(self):
  earlier=at(1,59)
  bad=control.startup_preflight(data(earlier),earlier,{'allocation_policy':'instant-max-fill-v1'})
  self.assertEqual(bad['status'],'waiting_for_inputs')
  self.assertIn('missing_battery_energy_model',bad['reason_codes'])
  ready=control.startup_preflight(data(earlier),earlier,plan())
  self.assertEqual(ready['status'],'inputs_prevalidated')
  self.assertFalse(ready['active'])
  self.assertIsNone(ready['control_lease'])
  self.assertTrue(ready['post_window_revalidation_required'])
  self.assertEqual(ready['post_window_frames_verified'],0)
  self.assertTrue(ready['window_start'].endswith('02:00:00+00:00'))
  self.assertIsNone(control.startup_preflight(data(at(2,0)),at(2,0),plan()))

 def test_phase_invalidity_visible_in_preflight(self):
  ss=data(at(1,59))
  for row in ss:
   if row['entity_id']==night.IDS['grid_l2_a']:row['state']='0.1'
  result=control.startup_preflight(ss,at(1,59),plan())
  self.assertIn('invalid_phase_input',result['reason_codes'])
  self.assertEqual(result['device_actions'],0)

 def test_memory_control_needs_two_new_frames_after_boundary(self):
  memory=iso.MemoryControl()
  try:
   before=at(1,59)
   current,journal=memory.step(data(before),{'session':plan()},before)
   self.assertEqual(current['startup_preflight']['status'],'inputs_prevalidated')
   self.assertIsNone(journal['session'])
   for table in ('ram_control_sessions','ram_control_samples','ram_control_events'):
    self.assertEqual(memory.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
   first,j1=memory.step(data(at(2,0)),{'session':plan()},at(2,0))
   self.assertNotIn('startup_preflight',first)
   self.assertFalse(j1['session']['owned'])
   second,j2=memory.step(data(at(2,0,5)),{'session':plan()},at(2,0,5))
   self.assertTrue(j2['session']['owned'])
   self.assertGreater(j2['session']['started_at'],before)
   self.assertEqual(j2['session']['device_actions'],0)
   self.assertFalse(j2['interface']['physical_control_ready'])
  finally:memory.close()

 def test_tariff_provenance_does_not_substitute_other_buy_price_sensor(self):
  from energy import soc_runtime,pricing
  self.assertEqual(soc_runtime.IDS['tariff'],'sensor.cez_indi_cenik')
  row={'available_at':'2026-11-12T02:55:00+01:00','payload':{'today':[
   {'start':'2026-11-12T03:00:00+01:00','end':'2026-11-12T04:00:00+01:00','price':1.8078},
   {'start':'2026-11-12T04:00:00+01:00','end':'2026-11-12T05:00:00+01:00','price':1.8078}]}}
  book=pricing.TariffBook([row])
  for hour in (3,4):
   ts=datetime(2026,11,12,hour,30,tzinfo=ZoneInfo('Europe/Prague')).timestamp()
   self.assertAlmostEqual(book.price(ts),1.8078)
  self.assertAlmostEqual(round(23.63*1.8078,2),42.72)
  # Disagreeing market-based sensor has a different model, never a fallback.
  self.assertNotEqual(book.price(datetime(2026,11,12,3,30,tzinfo=ZoneInfo('Europe/Prague')).timestamp()),7.708)

 def test_pre_window_reports_cannot_be_reused_as_new_frames(self):
  memory=iso.MemoryControl()
  try:
   before=at(1,59)
   memory.step(data(before),{'session':plan()},before)
   _,journal=memory.step(data(before),{'session':plan()},at(2,0,30))
   self.assertFalse(journal['session']['owned'])
   self.assertEqual(journal['session']['target_ac_w'],0)
  finally:memory.close()
