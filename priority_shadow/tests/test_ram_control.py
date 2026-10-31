import ast,copy,json,tempfile,threading,time,unittest
from pathlib import Path
from datetime import datetime,timedelta
from energy import ram_control as c,priority,night,control_journal as old
from energy.store import Store,unpack
from energy.priority_maintenance import Maintenance
from test_control_journal import states as managed,patch_value
from test_instant_fill import points,SESSION
from test_night import state
AT='2026-01-15T02:00:00+00:00';END='2026-01-15T04:00:00+00:00'
def stamp(s):return (datetime.fromisoformat(AT)+timedelta(seconds=s)).isoformat()
def data(at=AT):
 ss=managed(at);mapping={**night.IDS,**priority.EXTRA};already={s['entity_id'] for s in ss}
 for k,p in points().items():
  if k in mapping and mapping[k] not in already:ss.append(state(mapping[k],p['value'],at))
 ss.extend([state(c.RUN_MODE,'Normal Mode',at),state(c.REMOTE_MODE,'Disabled',at),state(c.READBACKS[0],'Disabled',at)])
 return ss
def result(at=AT):return {'at':at,'session':SESSION,'priority':'ev','actual':{'battery_a':0,'battery_v':230,'ev_w':11040}}
class RamControlTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'e.sqlite';self.store=Store(self.path)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def run_at(self,s=0,ss=None):
  at=stamp(s);return c.observe(self.store,ss if ss is not None else data(at),result(at))
 def events(self):return [unpack(p) for p, in self.store.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
 def ready(self):self.run_at();return self.run_at(5)
 def test_two_fresh_frames_and_persistent_settings_untouched(self):
  first=self.run_at();self.assertFalse(first['session']['owned']);v=self.run_at(5)
  self.assertGreater(v['session']['target_ac_w'],0);self.assertLessEqual(v['session']['target_ac_w'],500)
  for e in (old.CURRENT,old.MODE,old.FORCE):self.assertEqual(v['session']['owned'][e]['before'],v['session']['owned'][e]['virtual'])
  self.assertFalse(any(e['entity_id'] in (old.CURRENT,old.MODE,old.FORCE) for e in self.events()))
  self.assertFalse(v['interface']['physical_control_ready']);self.assertIsNone(v['session']['last_intent']['wire_command'])
 def test_unknown_write_classes_rejected(self):
  good=c.intent(100,AT);self.assertEqual(c.validate_intent(good),good)
  for patch in [{'entity_id':old.CURRENT},{'storage_class':'eeprom'},{'wire_command':{'register':0x24}},{'logical_battery_ac_w':float('nan')},{'persistent_writes':1}]:
   with self.assertRaises(ValueError):c.validate_intent({**good,**patch})
  for value in [-1,True,None,float('inf')]:
   with self.assertRaises(ValueError):c.intent(value,AT)
 def test_normal_mode_gate_and_stale_status(self):
  self.ready();ss=data(stamp(10));patch_value(ss,c.RUN_MODE,'Off-Grid')
  v=self.run_at(10,ss);self.assertEqual(v['session']['target_ac_w'],0)
  ss=data(stamp(15));next(s for s in ss if s['entity_id']==c.RUN_MODE)['last_reported']=AT
  v=self.run_at(15,ss);self.assertEqual(v['session']['target_ac_w'],0)
 def test_existing_ram_owner_blocks_even_with_missing_readback(self):
  ss=data();patch_value(ss,c.REMOTE_MODE,'Enabled Power Control')
  self.assertEqual(self.run_at(ss=ss)['session']['target_ac_w'],0)
 def test_inconsistent_phase_stops_and_requires_two_new_frames(self):
  self.ready();ss=data(stamp(10));patch_value(ss,night.IDS['grid_l2_w'],-4600);patch_value(ss,night.IDS['grid_l2_a'],16)
  v=self.run_at(10,ss);self.assertEqual(v['session']['target_ac_w'],0)
  self.assertIn('invalid_phase_input',v['recent_samples'][0]['input_errors'])
  self.assertEqual(self.run_at(15)['session']['target_ac_w'],0)
  self.assertGreater(self.run_at(20)['session']['target_ac_w'],0)
 def test_unchanged_values_with_new_reports_valid_but_same_report_not_new_frame(self):
  self.ready();ss=data(stamp(5));v=self.run_at(10,ss)
  self.assertEqual(v['session']['target_ac_w'],500);self.assertFalse(v['recent_samples'][0]['new_frame'])
  self.assertGreater(self.run_at(15)['session']['target_ac_w'],500) # včasná omezená obnova podržela výkon
  self.assertGreater(self.run_at(20)['session']['target_ac_w'],0)
 def test_report_skew_and_gap_invalidate_continuity(self):
  self.ready();ss=data(stamp(10));next(s for s in ss if s['entity_id']==night.IDS['grid_l2_a'])['last_reported']=stamp(5)
  v=self.run_at(10,ss);self.assertEqual(v['session']['target_ac_w'],0)
  self.run_at(15);v=self.run_at(30)
  self.assertEqual(v['session']['target_ac_w'],0);self.assertTrue(any(e['kind']=='sampling_gap' for e in self.events()))
 def test_restart_no_churn_and_restore_disabled_automation(self):
  ss=data();patch_value(ss,old.AUTOMATIONS[0],'off');self.run_at(ss=ss)
  ss=data(stamp(5));patch_value(ss,old.AUTOMATIONS[0],'off');self.run_at(5,ss)
  self.store.close();self.store=Store(self.path)
  end=data(END);patch_value(end,old.AUTOMATIONS[0],'off');patch_value(end,night.IDS['ev_w'],0)
  v=c.observe(self.store,end,result(END));self.assertEqual(v['session']['status'],'closed')
  self.assertTrue(v['session']['exact_restore']);self.assertEqual(v['session']['owned'][old.AUTOMATIONS[0]]['virtual'],'off')
  n=len(self.events());c.observe(self.store,end,result(stamp(7210)));self.assertEqual(len(self.events()),n)
 def test_missing_restore_then_recovery_and_active_ev_handoff(self):
  self.ready();ss=data(END);patch_value(ss,night.IDS['ev_w'],'unavailable')
  v=c.observe(self.store,ss,result(END));self.assertEqual(v['status'],'restore_pending')
  v=self.run_at(7205);self.assertEqual(v['session']['restoration_status'],'conditional_handoff')
  self.assertFalse(v['session']['exact_restore'])
 def test_config_manual_conflict_not_overwritten(self):
  self.ready();ss=data(stamp(10));patch_value(ss,old.CURRENT,25,stamp(10),True)
  v=self.run_at(10,ss);self.assertEqual(v['session']['target_ac_w'],0)
  ss=data(END);patch_value(ss,old.CURRENT,25)
  v=c.observe(self.store,ss,result(END));self.assertEqual(v['session']['restoration_status'],'requires_review')
  self.assertFalse(any(e['entity_id']==old.CURRENT and e['kind']=='would_restore' for e in self.events()))
 def test_failure_and_late_close_not_backdated(self):
  self.ready();v=c.record_failure(self.store,stamp(8),'TimeoutError');self.assertEqual(v['session']['target_ac_w'],0)
  v=c.record_failure(self.store,stamp(7300),'TimeoutError');self.assertEqual(v['session']['status'],'restore_pending')
  ss=data(stamp(7310));patch_value(ss,night.IDS['ev_w'],0)
  v=self.run_at(7310,ss);self.assertEqual(v['session']['closed_at'],stamp(7310))
 def test_full_five_second_night_phase_limits_and_exact_energy_coverage(self):
  for s in range(0,7200,5):v=self.run_at(s)
  ss=data(END);patch_value(ss,night.IDS['ev_w'],0);v=c.observe(self.store,ss,result(END));run=v['session']
  self.assertEqual(run['statistics']['covered_s'],7195)
  self.assertEqual(run['statistics']['sample_count'],1440);self.assertEqual(run['statistics']['model_exceedance_samples'],0)
  self.assertTrue(run['exact_restore']);self.assertEqual(run['persistent_writes'],0)
  self.assertTrue(all(e['device_actions']==0 and e['persistent_writes']==0 for e in self.events()))
 def test_legacy_evidence_not_modified(self):
  old.schema(self.store.db);self.store.db.execute('INSERT INTO control_sessions VALUES(?,?)',('2000-01-01',__import__('energy.store',fromlist=['pack']).pack({'day':'2000-01-01','closed_at':AT,'owned':{}})));self.store.db.commit()
  before=self.store.db.execute('SELECT * FROM control_sessions').fetchall();self.ready()
  self.assertEqual(before,self.store.db.execute('SELECT * FROM control_sessions').fetchall())
 def test_no_actuator_imports_or_io(self):
  source=Path(c.__file__).read_text();tree=ast.parse(source)
  self.assertFalse(any(isinstance(n,ast.Import) and any(x.name in ('urllib','requests','socket','subprocess') for x in n.names) for n in ast.walk(tree)))
  self.assertNotIn('call_service',source);self.assertNotIn('write_register',source)
 def test_slow_maintenance_does_not_block_control_or_handoff(self):
  entered=threading.Event();release=threading.Event()
  def work(states,at):entered.set();release.wait(5);return {'at':at}
  worker=Maintenance(self.path,{},lambda:None,work=work)
  try:
   worker.submit(data(),AT);self.assertTrue(entered.wait(2));start=time.monotonic();self.ready()
   worker.submit(data(stamp(5)),stamp(5));self.assertEqual(worker.snapshot(),{})
   self.assertLess(time.monotonic()-start,1)
  finally:release.set();self.assertTrue(worker.close())
 def test_logical_lease_expires_without_new_reports(self):
  self.ready();held=data(stamp(5));self.run_at(10,held);self.run_at(15,held);v=self.run_at(20,held)
  self.assertEqual(v['session']['target_ac_w'],0)
  self.assertTrue(any(e['reason']=='logical_lease_expired' for e in self.events()))
  self.assertIsNone(v['session']['last_intent']['wire_command'])
 def test_delayed_takeover_uses_fresh_soc_not_first_waiting_sample(self):
  self.run_at();ss=data(stamp(5));patch_value(ss,night.IDS['battery_soc'],100)
  v=self.run_at(5,ss);self.assertEqual(v['session']['shadow_model']['soc_pct'],100)
  self.assertEqual(v['session']['target_ac_w'],0)
