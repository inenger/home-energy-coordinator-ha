"""Mode/submode through production MemoryControl, FIFO flush and original restoration."""
import copy,tempfile,unittest
from pathlib import Path
from energy import ram_control as c,control_journal as legacy,isolated_control as iso,journal_transport as transport
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
from test_control_journal import patch_value

class ManualModeTests(unittest.TestCase):
 def states(self,second,mode='Back Up Mode',submode='Force Charge'):
  ss=data(stamp(second));patch_value(ss,legacy.MODE,mode);patch_value(ss,legacy.FORCE,submode)
  return ss
 def test_takeover_all_stored_submodes_under_known_passive_strategies(self):
  for mode in c.PASSIVE_WORK_MODES:
   for submode in c.MANUAL_SUBMODES:
    with self.subTest(mode=mode,submode=submode):
     mem=iso.MemoryControl()
     try:
      for t in [0,5,10]:
       ss=self.states(t,mode,submode);before=copy.deepcopy(ss)
       _,journal=mem.step(ss,result(stamp(t)),stamp(t));self.assertEqual(ss,before)
      self.assertGreater(journal['session']['target_ac_w'],0)
      self.assertFalse(journal['manual_control']['manual_submode_applies'])
      self.assertEqual(journal['session']['owned'][legacy.FORCE]['virtual'],submode)
      self.assertEqual(len(journal['recent_samples'][0]['owner_reports']),5)
     finally:mem.close()
 def test_active_manual_charge_and_discharge_still_block(self):
  for submode in ['Force Charge','Force Discharge']:
   mem=iso.MemoryControl()
   try:
    for t in [0,5,10]:_,j=mem.step(self.states(t,'Manual Mode',submode),result(stamp(t)),stamp(t))
    self.assertFalse(j['session']['owned']);self.assertEqual(j['session']['target_ac_w'],0)
    self.assertIn('unowned_manual_charge_or_discharge',j['recent_samples'][0]['input_errors'])
   finally:mem.close()
 def test_stopped_manual_mode_still_allows_shadow_takeover(self):
  mem=iso.MemoryControl()
  try:
   for t in [0,5]:_,j=mem.step(self.states(t,'Manual Mode','Stop Charge and Discharge'),result(stamp(t)),stamp(t))
   self.assertGreater(j['session']['target_ac_w'],0)
  finally:mem.close()
 def test_missing_unknown_and_stale_mode_or_submode_cannot_authorize(self):
  for eid in [legacy.MODE,legacy.FORCE]:
   for kind in ['missing','unknown','stale','unrecognized']:
    mem=iso.MemoryControl()
    try:
     for t in [0,5,10]:
      ss=self.states(t)
      if kind=='missing':ss=[s for s in ss if s['entity_id']!=eid]
      else:
       row=next(s for s in ss if s['entity_id']==eid)
       if kind=='stale':row['last_reported']=stamp(-20)
       else:row['state']='unknown'if kind=='unknown'else'unsupported-future-mode'
      _,j=mem.step(ss,result(stamp(t)),stamp(t))
     self.assertEqual(j['session']['target_ac_w'],0);self.assertFalse(j['session']['owned'])
     self.assertIsNone(j['manual_control']['manual_charge_or_discharge_active'])
    finally:mem.close()
 def test_strategy_report_caps_lease(self):
  mem=iso.MemoryControl()
  try:
   for t in [0,5,10]:
    ss=self.states(t)
    if t==10:next(s for s in ss if s['entity_id']==legacy.MODE)['last_reported']=stamp(-3)
    _,j=mem.step(ss,result(stamp(t)),stamp(t))
   self.assertGreater(j['session']['target_ac_w'],0)
   sample=j['recent_samples'][0]
   self.assertEqual(sample['input_valid_until'],stamp(12))
   self.assertEqual(sample['intent_expires_at'],stamp(12))
  finally:mem.close()
 def test_manual_activation_during_owned_session_stops_and_preserves_override(self):
  mem=iso.MemoryControl()
  try:
   for t in [0,5]:_,j=mem.step(self.states(t),result(stamp(t)),stamp(t))
   self.assertGreater(j['session']['target_ac_w'],0)
   ss=self.states(10,'Manual Mode','Force Charge')
   _,j=mem.step(ss,result(stamp(10)),stamp(10))
   self.assertEqual(j['session']['target_ac_w'],0)
   self.assertTrue(j['session']['suspended'])
   self.assertIn('unowned_manual_charge_or_discharge',j['recent_samples'][0]['input_errors'])
  finally:mem.close()
 def test_remote_owner_remains_blocking_in_backup_mode(self):
  mem=iso.MemoryControl()
  try:
   for t in [0,5]:
    ss=self.states(t);patch_value(ss,c.REMOTE_MODE,'Enabled Power Control')
    _,j=mem.step(ss,result(stamp(t)),stamp(t))
   self.assertFalse(j['session']['owned']);self.assertEqual(j['session']['target_ac_w'],0)
  finally:mem.close()
 def test_disk_transport_and_close_keep_original_inactive_submode(self):
  with tempfile.TemporaryDirectory()as folder:
   mem=iso.MemoryControl();disk=Store(Path(folder)/'e.sqlite')
   try:
    original=None
    for seq,t in enumerate([0,5,10,7200],1):
     ss=self.states(t);_,j=mem.step(ss,result(stamp(t)),stamp(t))
     if t==10:original=j['session']['owned'][legacy.FORCE]['before']
     batch={'runtime':'synthetic-mode','seq':seq,'at':stamp(t),'loss':{},'rows':mem.delta()}
     iso.persist_batch(disk,batch);iso.persist_batch(disk,batch)
     transport.enqueue(disk,j)
    run=unpack(disk.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
    self.assertEqual(original,'Force Charge');self.assertEqual(run['owned'][legacy.FORCE]['virtual'],original)
    self.assertTrue(run['closed_at'])
    for payload, in disk.db.execute('SELECT payload FROM ram_control_events'):
     e=unpack(payload);self.assertEqual(e['device_actions'],0);self.assertEqual(e['persistent_writes'],0)
     self.assertNotIn(e['entity_id'],[legacy.MODE,legacy.FORCE,legacy.CURRENT])
    self.assertGreater(disk.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
   finally:mem.close();disk.close()

 def test_production_loop_accepts_backup_force_charge_and_persists_positive_result(self):
  from test_control_isolation_0620 import Clock,Stop,Client,Evidence,Monitor
  from energy import publish_status
  clock=Clock();client=Client(clock);evidence=Evidence();monitor=Monitor()
  original=client.priority_states
  def read():
   states=original();patch_value(states,legacy.MODE,'Back Up Mode');patch_value(states,legacy.FORCE,'Force Charge');return states
  client.priority_states=read
  iso.run_loop(client,evidence,monitor,Stop(clock),clock.now,lambda:clock.sec)
  self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
  self.assertFalse(any(v['collection_health']['status']=='failed'for v in monitor.results))
  self.assertTrue(publish_status.prepare_priority(monitor.results[-1]))
  with tempfile.TemporaryDirectory()as folder:
   disk=Store(Path(folder)/'e.sqlite')
   try:
    for seq,(rows,states,value,generation)in enumerate(evidence.rows,1):
     iso.persist_batch(disk,{'runtime':'synthetic-main','seq':seq,'at':value['at'],'rows':rows,'loss':{}})
    stored=unpack(disk.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
    self.assertEqual(stored,monitor.results[-1]['control_journal']['session'])
    self.assertGreater(transport.enqueue(disk,monitor.results[-1]['control_journal'])['pending_chunks'],0)
   finally:disk.close()
