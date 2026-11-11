"""0.6.30 acceptance tests. Historical counterexamples are in docs/history."""
import copy,json,tempfile,threading,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
from energy import isolated_control as iso,priority_observer as observer,soc_runtime
from energy.collector import ReadOnlyHA
from energy.priority_collection import SnapshotCollector,CollectionFailure
from energy.store import Store,pack
from test_ram_control import data,stamp

class ReadinessFixes(unittest.TestCase):
 def test_slow_rest_does_not_block_fast_template_snapshots(self):
  c=ReadOnlyHA('http://synthetic.invalid')
  entered=threading.Event();release=threading.Event()
  def get(path):
   entered.set();release.wait(12);return []
  c.get=MagicMock(side_effect=get);c._query=MagicMock(return_value='[]')
  worker=SnapshotCollector(c,period=.1,max_age=7.5).start()
  try:
   self.assertTrue(entered.wait(2))
   end=time.monotonic()+2
   while worker.snapshot()['snapshot_age_s'] is None and time.monotonic()<end:time.sleep(.02)
   self.assertIsNotNone(worker.snapshot()['snapshot_age_s'])
   time.sleep(.25)
   self.assertGreater(c._query.call_count,1)
   self.assertTrue(worker.snapshot()['thread_alive'])
  finally:release.set();worker.close()

 def test_dead_thread_restarts_with_latched_failure(self):
  c=MagicMock();c.priority_states.side_effect=[SystemExit('synthetic'),data(stamp(20))]
  w=SnapshotCollector(c,period=.1).start()
  try:
   end=time.monotonic()+3
   while w.restart_count<1 and time.monotonic()<end:time.sleep(.02)
   self.assertEqual(w.restart_count,1)
   self.assertTrue(w.snapshot()['thread_alive'])
   with self.assertRaises(CollectionFailure):w.priority_states()
  finally:w.close()

 def test_failure_reason_is_safe_and_semantic(self):
  a=observer.failure_result(stamp(20),RuntimeError('COLLECTION_SNAPSHOT_EXPIRED'),stamp(15))
  b=observer.failure_result(stamp(20),RuntimeError('COLLECTION_WORKER_FAILED:TimeoutError'),stamp(15))
  self.assertEqual(a['collection_health']['reason_code'],'COLLECTION_SNAPSHOT_EXPIRED')
  self.assertEqual(b['collection_health']['reason_code'],'COLLECTION_WORKER_FAILED:TimeoutError')
  c=observer.failure_result(stamp(20),RuntimeError('private token'),stamp(15))
  self.assertNotIn('private token',json.dumps(c))

 def test_evidence_receipt_checks_content_and_old_unknown_hash(self):
  with tempfile.TemporaryDirectory() as folder:
   s=Store(Path(folder)/'evidence.sqlite')
   try:
    b={'runtime':'test','seq':1,'at':stamp(0),'rows':{},'loss':{}}
    iso.persist_batch(s,b)
    iso.persist_batch(s,copy.deepcopy(b))
    altered=copy.deepcopy(b);altered['loss']={'batches':1}
    with self.assertRaisesRegex(ValueError,'EVIDENCE_BATCH_RECEIPT_CONFLICT'):
     iso.persist_batch(s,altered)
    self.assertEqual(s.db.execute('SELECT count(*) FROM control_evidence_batches').fetchone()[0],1)
    with s.db:s.db.execute('DELETE FROM control_batch_receipts WHERE runtime=?',('test',))
    with self.assertRaisesRegex(ValueError,'UNVERIFIABLE'):iso.persist_batch(s,b)
   finally:s.close()

 def test_same_timestamp_invalid_plan_revokes_without_rewriting(self):
  with tempfile.TemporaryDirectory() as folder:
   s=Store(Path(folder)/'evidence.sqlite')
   try:
    soc_runtime.schema(s.db)
    r={'issued_at':stamp(0),'day':stamp(0)[:10],'status':'conditional_shadow_plan',
       'horizon_complete':True,'target_soc_pct':60}
    old=soc_runtime.record_decision(s,r)
    self.assertEqual(soc_runtime.record_decision(s,r),old)
    with self.assertRaisesRegex(ValueError,'SOC_DECISION_TIMESTAMP_CONFLICT'):
     soc_runtime.record_decision(s,{'issued_at':stamp(0),'day':stamp(0)[:10],
                                  'status':'calculation_unavailable','target_soc_pct':None})
    self.assertEqual(s.db.execute('SELECT hash FROM soc_decisions').fetchone()[0],old['decision_hash'])
    self.assertIsNone(soc_runtime.session_plan(s,stamp(0)[:10],stamp(5)))
   finally:s.close()

 def test_heartbeat_does_not_hide_stalled_ack(self):
  b=iso.EvidenceBridge('/synthetic-unused',{})
  try:
   b.worker_ready=True;b.worker_started_at=time.monotonic()-200;b.seq=1
   b.inflight={1:(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()}
   b.process=MagicMock();b.process.pid=123;b.process.is_alive.return_value=True
   b.last={'ack':0,'storage_health':{'status':'degraded','error_code':'WriterTimeout'}}
   with patch.object(b,'restart_worker')as restart:
    for _ in range(5):b.last_reply=time.monotonic();b.guard.tick()
    self.assertEqual(restart.call_count,3)
   self.assertTrue(b.guard.exhausted)
  finally:
   for q in (b.inbox,b.output,b.bootstrap):q.cancel_join_thread();q.close()

 def test_already_committed_inflight_cannot_trigger_false_ack_stall(self):
  b=iso.EvidenceBridge('/synthetic-unused',{})
  try:
   b.worker_ready=True;b.worker_started_at=time.monotonic()-200
   b.ack=2;b.inflight={1:'2026-01-01T00:00:00+00:00',2:'2026-01-01T00:00:00+00:00'}
   b.last_reply=time.monotonic()
   b.process=MagicMock();b.process.pid=123;b.process.is_alive.return_value=True
   self.assertIsNone(b.worker_problem(time.monotonic(),30.))
  finally:
   for q in (b.inbox,b.output,b.bootstrap):q.cancel_join_thread();q.close()

 def test_hard_live_mode_still_rejected(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);options=root/'options.json';options.write_text('{"mode":"live"}')
   real=Path
   with (patch.object(observer,'DATA',root/'evidence'),
       patch.object(observer,'Path',side_effect=lambda p:options if str(p)=='/data/options.json' else real(p)),
       patch.object(observer.os,'umask'),
       patch('energy.native_backup.restore',return_value={'status':'no_snapshot'}),
       patch.object(iso,'EvidenceBridge')as bridge):
    with self.assertRaisesRegex(ValueError,'Only observe_only'):observer.main()
    bridge.assert_not_called()

if __name__=='__main__':unittest.main()
