"""Regrese obnovy: skutečná smyčka, latch, spawn, SQLite a outbox. Bez HA."""
import copy,json,os,queue,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from energy import isolated_control as iso,priority_collection as col,journal_transport as transport
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
from test_control_isolation_0620 import Clock,Stop,Evidence,Monitor,Client

class Latched(col.SnapshotCollector):
 def __init__(self,clock,path=None):super().__init__(None,failure_path=path);self.clock=clock;self.injected=False
 def priority_states(self):
  if self.clock.sec>=10 and not self.injected:
   self.failed(TimeoutError('synthetic'));self.injected=True
   with self.condition:
    self.pending_failure['first_at']=stamp(10);self.pending_failure['control_first_at']=stamp(10)
   self.persist_failure()
  with self.condition:
   self.states=data(stamp(self.clock.sec));self.received=time.monotonic();self.error=None
  return super().priority_states()

def wait_for(test,predicate,seconds=12):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if predicate():return
  time.sleep(.02)
 test.fail('Timed out waiting for synthetic worker')

def resilient_writer(path,options,inbox,output,bootstrap,stopping):
 store=Store(path);bootstrap.put(iso.seed_from(store));ack=0
 marker=Path(options.get('stall_marker',options['crash_marker']+'.unused'))
 if options.get('stall_marker')and not marker.exists():
  marker.write_text('stalled-before-first-batch')
  while not stopping.wait(.1):pass
  store.close();return
 try:
  while not stopping.is_set():
   try:batch=inbox.get(timeout=.1)
   except queue.Empty:
    iso.latest(output,{'ack':ack,'storage_health':{'status':'ok'}});continue
   iso.persist_batch(store,batch);transport.enqueue(store,batch['result']['control_journal'])
   marker=Path(options['crash_marker'])
   if not marker.exists():marker.write_text('committed-before-ack');os._exit(7)
   ack=batch['seq'];iso.latest(output,{'ack':ack,'storage_health':{'status':'ok'}})
 finally:store.close()
class ProbeEvidence(iso.EvidenceBridge):
 def new_process(self):
  return self.ctx.Process(target=resilient_writer,args=(self.path,self.options,self.inbox,self.output,self.bootstrap,self.stop),daemon=True)

def resilient_monitor(cfg,inbox,output,stopping):
 count=0;last=None
 while not stopping.is_set():
  try:value=inbox.get(timeout=.1)
  except queue.Empty:
   iso.latest(output,{'status':'ok','published_packets':count,'pending_entities':0,'received':last});continue
  marker=Path(cfg['crash_marker'])
  if not marker.exists():marker.write_text('first-attempt');os._exit(9)
  count+=1;last=value;iso.latest(output,{'status':'ok','published_packets':count,'pending_entities':0,'received':value})
class ProbeMonitor(iso.MonitorBridge):
 def new_process(self):
  return self.ctx.Process(target=resilient_monitor,args=(self.cfg,self.inbox,self.output,self.stop),daemon=True)

class RecoveryTests(unittest.TestCase):
 def test_fresh_cache_recovers_without_durable_ack_then_flushes_stop_and_outbox(self):
  with tempfile.TemporaryDirectory()as folder:
   clock=Clock();client=Latched(clock,Path(folder)/'failure.json');evidence=Evidence(health='degraded');monitor=Monitor()
   iso.run_loop(client,evidence,monitor,Stop(clock),clock.now,lambda:clock.sec)
   failed=[v for v in monitor.results if v['collection_health']['status']=='failed']
   self.assertEqual(len(failed),1)
   after=[v for v in monitor.results if v['at']>=stamp(15)]
   self.assertEqual(after[0]['control_journal']['session']['target_ac_w'],0)
   self.assertGreater(after[1]['control_journal']['session']['target_ac_w'],0)
   self.assertGreater(after[-1]['control_journal']['session']['target_ac_w'],0)
   self.assertIsNotNone(client.pending_failure)
   # Restart před trvalým ack musí chybu znovu předat; RAM consume se neukládá.
   restored=col.SnapshotCollector(None,failure_path=client.failure_path)
   with self.assertRaises(col.CollectionFailure):restored.priority_states()
   store=Store(Path(folder)/'e.sqlite')
   try:
    for seq,(rows,states,value,generation)in enumerate(evidence.rows,1):
     iso.persist_batch(store,{'runtime':'synthetic','seq':seq,'at':value['at'],'rows':rows,'loss':{}})
     transport.enqueue(store,value['control_journal'])
    events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
    self.assertTrue(any(e['kind']=='collection_failure'for e in events))
    self.assertGreater(store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
    self.assertTrue(client.acknowledge_failure(client.generation))
    self.assertIsNone(col.SnapshotCollector(None,failure_path=client.failure_path).pending_failure)
   finally:store.close()

 def test_loss_after_durable_close_keeps_original_and_next_day_fifo_and_receipt(self):
  with tempfile.TemporaryDirectory()as folder:
   mem=iso.MemoryControl();store=Store(Path(folder)/'e.sqlite');seq=0
   try:
    def flush(t,loss):
     nonlocal seq
     _,j=mem.step(data(stamp(t)),result(stamp(t)),stamp(t));seq+=1
     b={'runtime':'synthetic','seq':seq,'at':stamp(t),'rows':mem.delta(),'loss':loss}
     iso.persist_batch(store,b);iso.persist_batch(store,b);transport.enqueue(store,j);return j
    for t in [0,5,10,7200]:j=flush(t,{})
    old=store.db.execute('SELECT payload FROM ram_control_sessions WHERE day=?',(j['session']['day'],)).fetchone()[0]
    loss={'batches':1,'days':{j['session']['day']:1},'first_at':stamp(7260),'last_at':stamp(7260)}
    mem.annotate_loss(loss);j=flush(7320,loss)
    self.assertEqual(store.db.execute('SELECT payload FROM ram_control_sessions WHERE day=?',(j['session']['day'],)).fetchone()[0],old)
    self.assertEqual(unpack(store.db.execute('SELECT payload FROM control_evidence_batches WHERE seq=?',(seq,)).fetchone()[0]),loss)
    for t in [86400,86405]:j=flush(t,loss)
    self.assertGreater(j['session']['target_ac_w'],0)
    self.assertEqual(store.db.execute('SELECT count(*) FROM ram_control_sessions').fetchone()[0],2)
   finally:mem.close();store.close()

 def test_consumed_generation_cannot_hide_new_failure_or_stale_cache(self):
  w=col.SnapshotCollector(None);w.failed(TimeoutError());g=w.generation
  self.assertTrue(w.consume_failure(g));w.failed(ConnectionError())
  self.assertFalse(w.consume_failure(g))
  with self.assertRaises(col.CollectionFailure):w.priority_states()
  self.assertTrue(w.consume_failure(w.generation))
  with self.assertRaises(RuntimeError):w.priority_states()
  with w.condition:w.error=None;w.states=data();w.received=time.monotonic()-20
  with self.assertRaisesRegex(RuntimeError,'EXPIRED'):w.priority_states()

 def test_blocked_failure_fsync_does_not_block_production_input_worker(self):
  entered=threading.Event();release=threading.Event()
  class Source:
   n=0
   def priority_states(self):
    self.n+=1
    if self.n==1:raise TimeoutError('synthetic')
    return data()
  source=Source()
  def blocked(*a,**k):entered.set();release.wait(5)
  with tempfile.TemporaryDirectory()as folder,patch.object(col,'atomic_json',side_effect=blocked):
   worker=col.SnapshotCollector(source,period=.02,night_period=.02,failure_path=Path(folder)/'failure.json',defer_failure_persistence=True).start()
   try:
    self.assertTrue(entered.wait(2))
    wait_for(self,lambda:source.n>=4,2)
    with self.assertRaises(col.CollectionFailure):worker.priority_states()
    self.assertTrue(worker.consume_failure(worker.generation))
    self.assertTrue(worker.priority_states())
    self.assertIsNotNone(worker.pending_failure)
   finally:release.set();worker.close()

 def test_submit_retains_bounded_replay_without_writing_ipc_on_control_thread(self):
  b=iso.EvidenceBridge('/unused',{},capacity=1)
  try:
   with patch.object(b.inbox,'put_nowait',side_effect=AssertionError('IPC on control')):
    self.assertTrue(b.submit({},[],{'at':stamp(0)}));self.assertFalse(b.submit({},[],{'at':stamp(5)}))
   self.assertEqual(len(b.replay),1);self.assertEqual(b.loss['batches'],1)
  finally:
   for q in (b.inbox,b.output,b.bootstrap):q.close()

 def test_real_worker_crash_after_commit_before_ack_replays_exactly_without_resetting_ram(self):
  with tempfile.TemporaryDirectory()as folder:
   bridge=ProbeEvidence(Path(folder)/'e.sqlite',{'crash_marker':str(Path(folder)/'crash')}).start()
   seed=None
   def ready():
    nonlocal seed
    seed=bridge.seed();return seed is not None
   try:
    wait_for(self,ready,seconds=30)
    class Adapter:
     loss=bridge.loss
     def seed(self):return seed
     def snapshot(self):return {**bridge.snapshot(),'analysis':result(stamp(0))}
     def submit(self,*a,**k):return bridge.submit(*a,**k)
    clock=Clock();monitor=Monitor()
    iso.run_loop(Client(clock),Adapter(),monitor,Stop(clock),clock.now,lambda:clock.sec)
    self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
    wait_for(self,lambda:bridge.snapshot()['committed_seq']==bridge.last_accepted)
    self.assertEqual(bridge.guard.restarts,1,bridge.guard.snapshot());self.assertEqual(bridge.loss['batches'],0)
    store=Store(Path(folder)/'e.sqlite')
    try:
     self.assertEqual(store.db.execute('SELECT count(*)FROM ram_control_samples').fetchone()[0],len(monitor.results))
     run=unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
     self.assertEqual(run,monitor.results[-1]['control_journal']['session'])
     self.assertEqual(run['event_count'],store.db.execute('SELECT count(*)FROM ram_control_events').fetchone()[0])
    finally:store.close()
   finally:bridge.close()

 def test_real_monitor_crash_republishes_latest_result(self):
  with tempfile.TemporaryDirectory()as folder:
   bridge=ProbeMonitor({'crash_marker':str(Path(folder)/'crash')}).start()
   try:
    # Start-up and recovery are separate bounded stages. First prove the
    # spawned worker is ready; the next wait still bounds crash recovery.
    wait_for(self,lambda:bridge.snapshot().get('status')=='ok',seconds=30)
    bridge.submit({'synthetic_revision':1})
    wait_for(self,lambda:bridge.snapshot().get('received')=={'synthetic_revision':1})
    self.assertEqual(bridge.guard.restarts,1)
    bridge.submit({'synthetic_revision':2})
    wait_for(self,lambda:bridge.snapshot().get('received')=={'synthetic_revision':2})
   finally:bridge.close()

 def test_monitor_reports_stalled_publication_and_guard_restart_is_bounded(self):
  bridge=iso.MonitorBridge({})
  try:
   now=time.monotonic();bridge.last_reply=now;bridge.last_progress=now-100
   bridge.last={'status':'ok','pending_entities':2,'published_packets':5}
   self.assertEqual(bridge.snapshot()['error_code'],'MONITOR_PUBLICATION_STALLED')
   with patch.object(bridge,'worker_problem',return_value='synthetic_stall'),patch.object(bridge,'restart_worker')as restart:
    for _ in range(5):bridge.guard.tick()
    self.assertEqual(restart.call_count,3);self.assertTrue(bridge.guard.exhausted)
   self.assertEqual(bridge.snapshot()['status'],'degraded')
  finally:
   for q in (bridge.inbox,bridge.output):q.close()

 def test_frozen_real_writer_is_replaced_and_unconfirmed_batches_are_replayed(self):
  with tempfile.TemporaryDirectory()as folder:
   marker=Path(folder)/'crash';marker.write_text('skip-deliberate-crash')
   bridge=ProbeEvidence(Path(folder)/'e.sqlite',{'crash_marker':str(marker),'stall_marker':str(Path(folder)/'stall')}).start()
   seed=None
   def ready():
    nonlocal seed
    seed=bridge.seed();return seed is not None
   try:
    wait_for(self,ready,seconds=30)
    class Adapter:
     loss=bridge.loss
     def seed(self):return seed
     def snapshot(self):return {**bridge.snapshot(),'analysis':result(stamp(0))}
     def submit(self,*a,**k):return bridge.submit(*a,**k)
    clock=Clock();monitor=Monitor()
    iso.run_loop(Client(clock),Adapter(),monitor,Stop(clock),clock.now,lambda:clock.sec)
    self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
    bridge.last_reply=time.monotonic()-31
    wait_for(self,lambda:bridge.snapshot()['committed_seq']==bridge.last_accepted)
    self.assertEqual(bridge.guard.restarts,1,bridge.guard.snapshot());self.assertEqual(bridge.loss['batches'],0)
    self.assertEqual(bridge.guard.reason,'EVIDENCE_PROCESS_UNRESPONSIVE')
   finally:bridge.close()

 def test_shutdown_during_recovery_cannot_start_another_child(self):
  for bridge in [iso.EvidenceBridge('/unused',{}),iso.MonitorBridge({})]:
   bridge.guard.stop.set()
   with patch('energy.process_supervision.retire'),patch.object(bridge,'new_process')as start:
    bridge.restart_worker();start.assert_not_called()
   channels=[bridge.inbox,bridge.output]
   if hasattr(bridge,'bootstrap'):channels.append(bridge.bootstrap)
   for q in channels:q.close()

 def test_monitor_heartbeat_cannot_hide_preparation_failure(self):
  inbox=queue.Queue();output=queue.Queue(2);stop=threading.Event()
  publisher=MagicMock();publisher.start.return_value=publisher
  publisher.snapshot.return_value={'status':'ok','published_packets':0,'pending_entities':0}
  publisher.submit.side_effect=[ValueError('synthetic malformed result'),None]
  with patch('energy.priority_publication.MonitorPublisher',return_value=publisher),patch.object(iso.os,'nice'):
   thread=threading.Thread(target=iso.monitor_worker,args=({},inbox,output,stop),daemon=True);thread.start()
   try:
    inbox.put({'synthetic_revision':1})
    wait_for(self,lambda:publisher.submit.call_count==1,2)
    time.sleep(.65) # nejméně dva idle heartbeat cykly po chybě přípravy
    health=iso.drain(output,{})
    self.assertEqual(health['status'],'degraded')
    self.assertEqual(health['stage'],'monitor_preparation')
    inbox.put({'synthetic_revision':2})
    wait_for(self,lambda:publisher.submit.call_count==2,2)
    time.sleep(.3)
    self.assertEqual(iso.drain(output,{})['status'],'ok')
   finally:stop.set();thread.join(2)

 def test_entrypoint_requires_deferred_failure_persistence(self):
  import inspect
  from energy import priority_observer
  self.assertIn('defer_failure_persistence=True',inspect.getsource(priority_observer.main))

if __name__=='__main__':unittest.main()
