"""A13: čas, energie a dokončení předání přes skutečný Store a monitory."""
import copy,json,tempfile,unittest
from pathlib import Path
from energy import priority,night,soc_runtime,instant_fill,ram_control as c,control_journal as old,journal_transport as transport,publish_status
from energy.monitor_payload import unpacked
from energy.store import Store,pack,unpack
from test_ram_control import data,result,stamp
from test_control_journal import patch_value,states as managed,result as legacy_result
from test_night import state

class IndependentFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'e.sqlite';self.s=Store(self.path)
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def step(self,t,states=None):return c.observe(self.s,data(stamp(t)) if states is None else states,result(stamp(t)))
 def ready(self):self.step(0);return self.step(5)
 def seed_ideal(self):
  night.ensure_schema(self.s.db);soc_runtime.schema(self.s.db)
  bm={'discharge_curve':[[0,0],[50,5],[100,10]],'dc_cycle_efficiency':.9,'grid_efficiency':.9,'source_hash':'synthetic'}
  with self.s.db:self.s.db.execute('INSERT INTO soc_model_versions VALUES(?,?,?)',('m','2026-01-14T20:00:00+00:00',pack({'at':'2026-01-14T20:00:00+00:00','battery_model':bm})))
 def ideal(self,t):return priority.observe(self.s,data(stamp(t))+[state(priority.HELPER,'Elektromobil',stamp(t))],stamp(t),True,instant_fill.POLICY)
 def test_ideal_rollback_restart_summary_never_reuses_an_interval(self):
  self.seed_ideal()
  for t in (0,5,10,8):v=self.ideal(t)
  self.assertEqual(v['selected']['reason'],'clock_rollback');self.assertIsNone(v['selected']['battery_ac_w'])
  self.s.close();self.s=Store(self.path)
  for t in (9,10,15,20):v=self.ideal(t)
  model=v['progress']['models']['selected'];self.assertEqual(model['covered_s'],15);self.assertEqual(v['progress']['gap_s'],5)
  self.assertAlmostEqual(model['battery_kwh_ac'],3400*15/3600000)
  before=self.s.db.execute('SELECT * FROM priority_runs').fetchall();self.ideal(20)
  self.assertEqual(before,self.s.db.execute('SELECT * FROM priority_runs').fetchall())
  summary=priority.finish(self.s,'2026-01-15');self.assertEqual(summary['sample_count'],5);self.assertEqual(summary['models']['selected']['covered_s'],15)
  self.assertEqual(summary['sample_count'],self.s.db.execute('SELECT count(*) FROM priority_samples').fetchone()[0])
 def test_closed_ideal_evidence_is_not_rewritten_by_calendar_rollback(self):
  self.seed_ideal();self.ideal(0);self.ideal(5);priority.finish(self.s,'2026-01-15')
  before=self.s.db.execute('SELECT * FROM priority_runs').fetchall();self.ideal(1)
  self.assertEqual(before,self.s.db.execute('SELECT * FROM priority_runs').fetchall())
 def test_calendar_rollback_does_not_create_an_earlier_ideal_run(self):
  self.seed_ideal();self.ideal(86400);self.ideal(86405);v=self.ideal(0)
  self.assertEqual(v['selected']['reason'],'clock_rollback');self.assertEqual(self.s.db.execute('SELECT count(*) FROM priority_runs').fetchone()[0],1)
 def test_failure_energy_reaches_summary_and_monitor_without_double_count(self):
  self.ready();v=self.step(10);before=v['session']['shadow_model']['battery_kwh_ac']
  j=c.record_failure(self.s,stamp(12),'TimeoutError');run=j['session']
  self.assertAlmostEqual(run['shadow_model']['battery_kwh_ac']-before,1000*2/3600000)
  again=c.record_failure(self.s,stamp(13),'TimeoutError');self.assertEqual(again['session']['shadow_model'],run['shadow_model'])
  packets=publish_status.prepare_priority({'at':stamp(12),'control_journal':j,'collection_health':{'status':'failed'}},True)
  attrs=unpacked(dict(packets)[c.SENSOR]['attributes']);self.assertEqual(attrs['session']['shadow_model'],run['shadow_model'])
  status=transport.enqueue(self.s,j);self.assertGreater(status['queued_seq'],0)
  summary=c.summary(run);self.assertEqual(summary['shadow_model'],run['shadow_model'])
 def test_failure_caps_at_original_expiry_and_does_not_fill_long_gap(self):
  self.ready();ss=data(stamp(10))
  next(x for x in ss if x['entity_id']==c.REMOTE_MODE)['last_reported']=stamp(0)
  v=self.step(10,ss);before=v['session']['shadow_model']['battery_kwh_ac'];self.assertEqual(v['session']['last_intent']['expires_at'],stamp(15))
  v=c.record_failure(self.s,stamp(16),'TimeoutError');self.assertAlmostEqual(v['session']['shadow_model']['battery_kwh_ac']-before,1000*5/3600000)
  self.step(20);v=self.step(25);before=v['session']['shadow_model']['battery_kwh_ac']
  v=c.record_failure(self.s,stamp(33),'TimeoutError');self.assertEqual(v['session']['shadow_model']['battery_kwh_ac'],before)
 def test_failure_near_window_end_counts_only_before_five(self):
  self.ready();self.step(7190);v=self.step(7195);before=v['session']['shadow_model']['battery_kwh_ac'];w=v['session']['target_ac_w']
  v=c.record_failure(self.s,stamp(7202),'TimeoutError');self.assertAlmostEqual(v['session']['shadow_model']['battery_kwh_ac']-before,w*5/3600000)
 def test_missing_unchanged_setting_waits_then_truthfully_completes(self):
  self.ready();ss=data(stamp(7200));patch_value(ss,old.CURRENT,'unavailable');patch_value(ss,'sensor.solax_api_charge_power_total',0)
  v=self.step(7200,ss);run=v['session'];row=next(x for x in run['restoration']if x['entity_id']==old.CURRENT)
  self.assertFalse(run['exact_restore']);self.assertEqual(run['status'],'restore_pending');self.assertEqual(row['status'],'unresolved_missing_state')
  ss=data(stamp(7205));patch_value(ss,'sensor.solax_api_charge_power_total',0);run=self.step(7205,ss)['session'];self.assertTrue(run['exact_restore']);self.assertEqual(run['closed_at'],stamp(7205))
 def test_legacy_upgrade_stops_hands_off_and_requires_new_RAM_frames(self):
  prior=old.observe(self.s,managed(stamp(0)),legacy_result(stamp(0)))['session'];prior['software_version']='0.6.7'
  with self.s.db:self.s.db.execute('UPDATE control_sessions SET payload=?',(pack(prior),))
  old_events=self.s.db.execute('SELECT * FROM control_events').fetchall();v=self.step(5)
  legacy=unpack(self.s.db.execute('SELECT payload FROM control_sessions').fetchone()[0])
  self.assertEqual(legacy['status'],'closed');self.assertEqual(legacy['software_version'],'0.6.7');self.assertEqual(legacy['owned'][old.FORCE]['virtual'],'Stop Charge and Discharge')
  self.assertFalse(v['session']['owned']);self.assertEqual(v['legacy_handoffs'][0]['closed_at'],stamp(5))
  self.assertEqual(old_events,self.s.db.execute('SELECT * FROM control_events ORDER BY id LIMIT ?',(len(old_events),)).fetchall())
  self.s.close();self.s=Store(self.path);v=self.step(10);self.assertTrue(v['session']['owned'])
  self.assertTrue(all(not e['applied_to_control']and e['device_actions']==0 for p, in self.s.db.execute('SELECT payload FROM control_events')for e in [unpack(p)]))
 def test_legacy_missing_restore_blocks_until_recovery_without_second_owner(self):
  old.observe(self.s,managed(stamp(0)),legacy_result(stamp(0)));ss=data(stamp(5));patch_value(ss,old.CURRENT,'unavailable');v=self.step(5,ss)
  self.assertEqual(v['legacy_handoffs'][0]['status'],'restore_pending')
  self.assertEqual(self.s.db.execute('SELECT count(*) FROM ram_control_sessions').fetchone()[0],0)
  self.step(10);v=self.step(15);self.assertTrue(v['session']['owned'])
  self.assertTrue(unpack(self.s.db.execute('SELECT payload FROM control_sessions').fetchone()[0])['closed_at'])
 def test_pending_older_than_display_limit_is_retried(self):
  v=self.ready();ss=data(stamp(7200));patch_value(ss,'sensor.solax_api_charge_power_total','unavailable');v=self.step(7200,ss)
  for i in range(1,15):
   closed=copy.deepcopy(v['session']);closed.update(day=stamp(i*86400)[:10],closed_at=stamp(i*86400+7200),status='closed')
   with self.s.db:self.s.db.execute('INSERT INTO ram_control_sessions VALUES(?,?)',(closed['day'],pack(closed)))
  ss=data(stamp(15*86400));patch_value(ss,'sensor.solax_api_charge_power_total',0);self.step(15*86400,ss)
  run=unpack(self.s.db.execute('SELECT payload FROM ram_control_sessions WHERE day=?',('2026-01-15',)).fetchone()[0]);self.assertIsNotNone(run['closed_at'])
  self.assertTrue(self.s.db.execute('SELECT 1 FROM ram_control_sessions WHERE day=?',(stamp(15*86400)[:10],)).fetchone())
