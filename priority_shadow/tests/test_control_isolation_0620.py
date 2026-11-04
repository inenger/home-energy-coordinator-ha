"""Produkční run_loop → RAM → asynchronní evidence; pouze syntetické vstupy."""
import copy,queue,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from energy import isolated_control as iso,ram_control as c,priority_collection as col,priority_observer as obs
from energy.store import Store,unpack,pack
from test_ram_control import data,result,stamp
from test_night import state

class Clock:
 def __init__(self):self.sec=0
 def now(self):return stamp(self.sec)
class Stop:
 def __init__(self,clock,end=100):self.clock=clock;self.end=end;self.waits=[]
 def is_set(self):return self.clock.sec>=self.end
 def wait(self,n):
  assert .25<=n<=5,n
  self.waits.append(n);self.clock.sec+=n
class Client:
 def __init__(self,clock,dropout=False):self.clock=clock;self.dropout=dropout;self.acks=[]
 def priority_states(self):
  at=stamp(self.clock.sec)
  if self.dropout and 20<=self.clock.sec<40:raise TimeoutError('synthetic input outage')
  states=data(at);states[0]['collection_snapshot']={'sequence':int(self.clock.sec)+1,
   'received_at':at,'request_started_at':at,'request_duration_s':0,'poll_interval_s':1}
  return states
 def snapshot(self):return {'night_poll_interval_s':1,'base_poll_interval_s':2.5}
 def request_acknowledge_failure(self,g):self.acks.append(g)
class Evidence:
 def __init__(self,capacity=1000,health='ok'):
  self.rows=[];self.results=[];self.capacity=capacity;self.health=health;self.loss={'batches':0};self.seeded=False
 def seed(self):self.seeded=True;return {}
 def snapshot(self):return {'analysis':result(stamp(0)),'status':self.health,'transport':{}}
 def submit(self,rows,states,value,failure_generation=None):
  self.results.append(copy.deepcopy(value))
  if len(self.rows)>=self.capacity:self.loss['batches']+=1;return False
  self.rows.append((copy.deepcopy(rows),copy.deepcopy(states),copy.deepcopy(value),failure_generation));return True
class Monitor:
 def __init__(self):self.results=[]
 def submit(self,value):self.results.append(copy.deepcopy(value))
 def snapshot(self):return {'status':'ok'}

def drive(dropout=False,capacity=1000,health='ok',evidence=None):
 clock=Clock();client=Client(clock,dropout);evidence=evidence or Evidence(capacity,health);monitor=Monitor()
 iso.run_loop(client,evidence,monitor,Stop(clock),clock.now,lambda:clock.sec)
 return evidence,monitor

def probe_writer(path,inbox,output,bootstrap,stopping):
 """Skutečný spawn+SQLite worker, bez klienta HA či monitorovacích služeb."""
 store=Store(path,timeout=.03)
 try:
  bootstrap.put(iso.seed_from(store));pending=None;ack=0
  while not stopping.is_set():
   if pending is None:
    try:pending=inbox.get(timeout=.05)
    except queue.Empty:continue
   try:
    iso.persist_batch(store,pending);ack=pending['seq'];pending=None
    iso.latest(output,{'ack':ack,'storage_health':{'status':'ok'}})
   except sqlite3.OperationalError:
    iso.latest(output,{'ack':ack,'storage_health':{'status':'degraded','error_code':'SQLITE_BUSY'}})
    stopping.wait(.01)
 finally:store.close()

class ControlIsolationTests(unittest.TestCase):
 def test_production_loop_never_opens_disk_or_waits_for_sqlite_writer(self):
  original=sqlite3.connect
  def connect(path,*a,**k):
   if path!=':memory:':raise AssertionError('Control opened persistent SQLite')
   return original(path,*a,**k)
  with patch('sqlite3.connect',side_effect=connect),patch('builtins.open',side_effect=AssertionError('Control opened file')):
   evidence,monitor=drive(health='degraded')
  self.assertGreater(len(evidence.rows),15)
  self.assertTrue(all(v['collection_health']['status']=='degraded'for v in monitor.results))
  self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
  events=[unpack(row[-1])for rows,*_ in evidence.rows for row in rows['ram_control_events']]
  self.assertFalse([e for e in events if e['kind']=='would_stop_charge'])
  self.assertTrue(all(v['fast_loop']['disk_io_in_control_thread']is False for v in monitor.results))

 def test_saturated_evidence_keeps_ramping_and_reports_loss(self):
  evidence,monitor=drive(capacity=1)
  self.assertGreater(evidence.loss['batches'],0)
  self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
  self.assertEqual(monitor.results[-1]['evidence_pipeline']['status'],'degraded')
  self.assertFalse(any(v['collection_health']['status']=='failed'for v in monitor.results))

 def test_real_input_outage_still_stops_and_requires_recovery(self):
  evidence,monitor=drive(dropout=True,capacity=1,health='degraded')
  failed=[v for v in monitor.results if v['collection_health']['status']=='failed']
  self.assertTrue(failed);self.assertTrue(all(v['control_journal']['session']['target_ac_w']==0 for v in failed))
  self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)

 def test_real_external_sqlite_lock_does_not_stop_production_loop_then_flushes_exactly(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';store=Store(path);c.schema(store.db)
   lock=sqlite3.connect(path);lock.execute('BEGIN IMMEDIATE')
   evidence,monitor=drive()
   batch={'runtime':'synthetic','seq':1,'at':stamp(0),'loss':{},'rows':evidence.rows[0][0]}
   with self.assertRaises(sqlite3.OperationalError):
    iso.persist_batch(store,batch)
   self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
   lock.rollback();lock.close()
   for i,(rows,states,value,generation)in enumerate(evidence.rows,1):
    batch={'runtime':'synthetic','seq':i,'at':value['at'],'loss':{},'rows':rows}
    iso.persist_batch(store,batch);iso.persist_batch(store,batch)
   self.assertEqual(store.db.execute('SELECT count(*) FROM ram_control_samples').fetchone()[0],len(evidence.rows))
   final=unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
   self.assertEqual(final,monitor.results[-1]['control_journal']['session'])
   self.assertEqual(final['event_count'],store.db.execute('SELECT count(*) FROM ram_control_events').fetchone()[0])
   from energy import journal_transport as transport
   status=transport.enqueue(store,monitor.results[-1]['control_journal'])
   self.assertGreater(status['pending_chunks'],0);store.close()

 def test_conflicting_immutable_row_is_rejected_not_overwritten(self):
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite');evidence,_=drive()
   batch={'runtime':'a','seq':1,'at':stamp(0),'loss':{},'rows':evidence.rows[0][0]}
   iso.persist_batch(store,batch)
   other=copy.deepcopy(batch);other['runtime']='b'
   row=list(other['rows']['ram_control_samples'][0]);row[-1]=pack({'changed':True})
   other['rows']['ram_control_samples'][0]=row
   with self.assertRaisesRegex(ValueError,'IMMUTABLE'):iso.persist_batch(store,other)
   self.assertNotEqual(store.db.execute('SELECT payload FROM ram_control_samples').fetchone()[0],row[-1]);store.close()

 def test_restart_does_not_reuse_previous_lease(self):
  memory=iso.MemoryControl()
  memory.step(data(stamp(0)),result(stamp(0)),stamp(0));memory.step(data(stamp(5)),result(stamp(5)),stamp(5))
  self.assertGreater(c.view(memory,stamp(5),[])['session']['target_ac_w'],0)
  seed=iso.seed_from(memory);memory.close();restored=iso.MemoryControl(seed)
  _,journal=restored.step(data(stamp(6)),result(stamp(6)),stamp(6))
  self.assertEqual(journal['session']['target_ac_w'],0)
  _,journal=restored.step(data(stamp(11)),result(stamp(11)),stamp(11))
  self.assertGreater(journal['session']['target_ac_w'],0);restored.close()

 def test_evidence_queue_is_bounded_and_carries_loss_to_recovery(self):
  bridge=iso.EvidenceBridge('/unused',{},capacity=1)
  # Reálná Queue používá feeder; pro přesné zjištění full zde lokální omezená Queue.
  for q in (bridge.inbox,bridge.output,bridge.bootstrap):q.close()
  bridge.inbox=queue.Queue(1);bridge.output=queue.Queue(2);bridge.bootstrap=queue.Queue(1)
  value={'at':stamp(0)};rows={'ram_control_events':[(1,)],'ram_control_samples':[(1,)]}
  self.assertTrue(bridge.submit(rows,[],value));self.assertFalse(bridge.submit(rows,[],value))
  self.assertEqual(bridge.loss['batches'],1);bridge.flush_pending();bridge.inbox.get()
  bridge.last={'ack':1};bridge.snapshot()
  self.assertTrue(bridge.submit({},[],value))
  bridge.flush_pending();batch=bridge.inbox.get();self.assertEqual(batch['loss']['events'],1);self.assertEqual(batch['loss']['samples'],1)
  self.assertEqual(batch['loss']['first_at'],stamp(0))

 def test_blocked_failure_ack_fsync_does_not_hold_collector_cache_lock(self):
  collector=col.SnapshotCollector(None);collector.failed(TimeoutError())
  collector.states=data(stamp(0));collector.received=time.monotonic();collector.error=None
  entered=threading.Event();release=threading.Event()
  def blocked(*a,**k):entered.set();release.wait(2)
  collector.failure_path=Path('/synthetic')
  with patch.object(col,'atomic_json',side_effect=blocked):
   thread=threading.Thread(target=collector.acknowledge_failure,args=(1,));thread.start()
   self.assertTrue(entered.wait(1))
   start=time.perf_counter()
   with self.assertRaises(col.CollectionFailure):collector.priority_states()
   self.assertLess(time.perf_counter()-start,.2)
   # Novější výpadek nesmí potvrdit starší ack; jeho RAM latch se nezablokuje.
   with collector.condition:
    collector.generation=2;collector.pending_failure={'generation':2,'first_at':stamp(0),'error_code':'TimeoutError'}
   release.set();thread.join(2)
  self.assertEqual(collector.pending_failure['generation'],2)

 def test_spawn_worker_blocked_on_real_disk_while_main_keeps_deciding(self):
  import multiprocessing as mp
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';store=Store(path);c.schema(store.db);store.close()
   bridge=iso.EvidenceBridge(path,{})
   ctx=mp.get_context('spawn')
   bridge.process=ctx.Process(target=probe_writer,args=(str(path),bridge.inbox,bridge.output,bridge.bootstrap,bridge.stop),daemon=True)
   bridge.start()
   seed=None;deadline=time.monotonic()+10
   while seed is None and time.monotonic()<deadline:seed=bridge.seed();time.sleep(.01)
   self.assertIsNotNone(seed)
   lock=sqlite3.connect(path);lock.execute('BEGIN IMMEDIATE')
   class FixtureBridge:
    loss=bridge.loss
    def seed(self):return seed
    def snapshot(self):return {**bridge.snapshot(),'analysis':result(stamp(0))}
    def submit(self,*a,**k):return bridge.submit(*a,**k)
   clock=Clock();monitor=Monitor();stop=Stop(clock)
   original_wait=stop.wait
   def wait(n):original_wait(n);time.sleep(.01)
   stop.wait=wait
   try:
    iso.run_loop(Client(clock),FixtureBridge(),monitor,stop,clock.now,lambda:clock.sec)
    self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
    self.assertTrue(any(v['evidence_pipeline']['status']=='degraded'for v in monitor.results))
    self.assertFalse(any(v['collection_health']['status']=='failed'for v in monitor.results))
    lock.rollback();lock.close()
    deadline=time.monotonic()+10
    while bridge.snapshot()['committed_seq']<bridge.last_accepted and time.monotonic()<deadline:time.sleep(.02)
    self.assertEqual(bridge.snapshot()['committed_seq'],bridge.last_accepted)
    read=sqlite3.connect(path);count=read.execute('SELECT count(*) FROM ram_control_samples').fetchone()[0];read.close()
    self.assertEqual(count,len(monitor.results))
   finally:
    try:lock.close()
    except Exception:pass
    bridge.close()

 def test_overflow_session_closure_is_resent_and_marked_incomplete(self):
  memory=iso.MemoryControl()
  _,j=memory.step(data(stamp(0)),result(stamp(0)),stamp(0))
  memory.delta()
  loss={'days':{stamp(0)[:10]:1},'first_at':stamp(0),'last_at':stamp(0)}
  memory.annotate_loss(loss)
  _,j=memory.step(data(stamp(5)),result(stamp(5)),stamp(5))
  self.assertEqual(j['session']['evidence_integrity']['status'],'incomplete')
  rows=memory.delta();self.assertTrue(rows['ram_control_sessions'])
  memory.retry_sessions();rows=memory.delta()
  self.assertTrue(rows['ram_control_sessions']);memory.close()

 def test_control_side_bridges_never_read_ipc_pipes(self):
  bridge=iso.EvidenceBridge('/unused',{})
  bridge.seed_value={}
  with patch.object(bridge.output,'get_nowait',side_effect=AssertionError('IPC read')),patch.object(bridge.bootstrap,'get_nowait',side_effect=AssertionError('IPC read')):
   self.assertEqual(bridge.seed(),{});bridge.snapshot()
  for q in (bridge.inbox,bridge.output,bridge.bootstrap):q.close()
  monitor=iso.MonitorBridge({})
  with patch.object(monitor.inbox,'put',side_effect=AssertionError('IPC send in control')):
   self.assertTrue(monitor.submit({'at':stamp(0)}));monitor.snapshot()
  for q in (monitor.inbox,monitor.output):q.close()

 def test_future_model_is_not_used_after_clock_rollback(self):
  memory=iso.MemoryControl();analysis=result(stamp(0))
  analysis['session']['model_available_at']=stamp(100)
  for sec in [0,5,10]:
   _,journal=memory.step(data(stamp(sec)),analysis,stamp(sec))
   self.assertEqual(journal['session']['target_ac_w'],0)
  self.assertIn('missing_battery_energy_model',journal['recent_samples'][0]['input_errors']);memory.close()

 def test_clock_rollback_cannot_reopen_archived_day_outside_ram_window(self):
  memory=iso.MemoryControl();end=stamp(7200)
  memory.step(data(stamp(0)),result(stamp(0)),stamp(0));memory.step(data(stamp(5)),result(stamp(5)),stamp(5))
  memory.step(data(end),result(end),end)
  future='2026-02-15T02:00:00+00:00'
  memory.watermark=future
  current,journal=memory.step(data(stamp(10)),result(stamp(10)),stamp(10))
  self.assertEqual(journal['status'],'waiting_clock_recovery')
  self.assertEqual(current['selected']['battery_ac_w'],0)
  self.assertTrue(journal['session']['closed_at']);memory.close()

 def test_persistent_closed_session_cannot_be_replaced_by_new_runtime(self):
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite');c.schema(store.db)
   original=pack({'closed_at':stamp(7200),'day':stamp(0)[:10]})
   store.db.execute('INSERT INTO ram_control_sessions VALUES(?,?)',(stamp(0)[:10],original));store.db.commit()
   batch={'runtime':'new','seq':1,'at':stamp(0),'loss':{},
     'rows':{'ram_control_sessions':[(stamp(0)[:10],pack({'day':stamp(0)[:10],'closed_at':None}))]}}
   with self.assertRaisesRegex(ValueError,'CLOSED_CONTROL_SESSION'):iso.persist_batch(store,batch)
   self.assertEqual(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0],original);store.close()

 def test_closed_session_ram_retention_is_bounded_without_deleting_disk(self):
  memory=iso.MemoryControl()
  with memory.db:
   for day in range(1,25):
    date='2025-12-'+str(day).zfill(2)
    memory.db.execute('INSERT INTO ram_control_sessions VALUES(?,?)',(date,pack({'day':date,'closed_at':date+'T04:00:00+00:00'})))
  rows=memory.delta()
  self.assertEqual(len(rows['ram_control_sessions']),24)
  self.assertEqual(memory.db.execute('SELECT count(*) FROM ram_control_sessions').fetchone()[0],14)
  memory.close()

 def test_entrypoint_wires_isolated_runtime(self):
  import energy.isolated_control as runtime
  evidence=MagicMock();monitor=MagicMock();client=MagicMock()
  with tempfile.TemporaryDirectory()as folder:
   folder=Path(folder)
   with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs.signal,'signal'),patch.object(runtime,'EvidenceBridge',return_value=MagicMock(start=lambda:evidence)),patch.object(runtime,'MonitorBridge',return_value=MagicMock(start=lambda:monitor)),patch.object(obs,'SnapshotCollector',return_value=MagicMock(start=lambda:client)),patch.object(obs,'ReadOnlyHA'),patch.object(runtime,'run_loop')as run:
    obs.main()
   run.assert_called_once_with(client,evidence,monitor,obs.STOP)
   evidence.close.assert_called_once();monitor.close.assert_called_once();client.close.assert_called_once()

if __name__=='__main__':unittest.main()
