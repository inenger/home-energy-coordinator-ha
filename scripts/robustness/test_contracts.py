"""Souběhy poruch a celé noční okno přes produkční smyčku; syntetické vstupy."""
import copy,math,queue,sqlite3,tempfile,time,unittest
from pathlib import Path
from energy import isolated_control as iso,journal_transport as transport,priority_collection as col,night
from energy.store import Store,unpack
from energy.core import instant
from test_ram_control import data,result,stamp
from test_control_isolation_0620 import Clock,Stop,Monitor
from test_recovery_0622 import Latched,wait_for

def retrying_writer(path,options,inbox,output,bootstrap,stopping):
 store=Store(path,timeout=.05);bootstrap.put(iso.seed_from(store));pending=None;ack=0
 try:
  while not stopping.is_set():
   if pending is None:
    try:pending=inbox.get(timeout=.05)
    except queue.Empty:
     iso.latest(output,{'ack':ack,'storage_health':{'status':'ok'}});continue
   try:
    iso.persist_batch(store,pending);transport.enqueue(store,pending['result']['control_journal'])
    ack=pending['seq'];pending=None
    iso.latest(output,{'ack':ack,'storage_health':{'status':'ok'}})
   except sqlite3.OperationalError:
    iso.latest(output,{'ack':ack,'storage_health':{'status':'degraded','error_code':'synthetic_disk_lock'}})
    stopping.wait(.02)
 finally:store.close()
class RetryBridge(iso.EvidenceBridge):
 def new_process(self):
  return self.ctx.Process(target=retrying_writer,args=(self.path,self.options,self.inbox,self.output,self.bootstrap,self.stop),daemon=True)
class WindowClient(col.SnapshotCollector):
 def __init__(self,clock):
  super().__init__(None,defer_failure_persistence=True);self.clock=clock;self.injected=set()
 def priority_states(self):
  sec=self.clock.sec
  for at in [600,1800,3600]:
   if sec>=at and at not in self.injected:
    self.injected.add(at);self.failed(TimeoutError('synthetic transient'))
    with self.condition:
     self.pending_failure['control_first_at']=stamp(sec)
     if len(self.injected)==1:self.pending_failure['first_at']=stamp(sec)
  with self.condition:
   self.states=data(stamp(sec));self.received=time.monotonic();self.error=None
   if 2400<=sec<2410:next(s for s in self.states if s['entity_id']==night.IDS['grid_l2_a'])['state']='unavailable'
  return super().priority_states()
class WindowStop:
 def __init__(self,clock):self.clock=clock;self.steps=0
 def is_set(self):return self.clock.sec>=7260
 def wait(self,delay):
  self.steps+=1
  if self.steps>4000:raise AssertionError('Unbounded scheduling loop')
  self.clock.sec+=delay

class RobustnessContracts(unittest.TestCase):
 def test_disk_lock_input_failure_and_worker_death_recover_together(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';bridge=RetryBridge(path,{}).start();seed=None;lock=None
   def booted():
    nonlocal seed
    seed=bridge.seed();return seed is not None
   try:
    wait_for(self,booted);lock=sqlite3.connect(path);lock.execute('BEGIN IMMEDIATE')
    class Adapter:
     loss=bridge.loss
     def seed(self):return seed
     def snapshot(self):return {**bridge.snapshot(),'analysis':result(stamp(0))}
     def submit(self,*a,**k):return bridge.submit(*a,**k)
    clock=Clock();client=Latched(clock);monitor=Monitor();stop=Stop(clock);original=stop.wait
    def wait(delay):original(delay);time.sleep(.01)
    stop.wait=wait
    iso.run_loop(client,Adapter(),monitor,stop,clock.now,lambda:clock.sec)
    self.assertEqual(sum(v['collection_health']['status']=='failed'for v in monitor.results),1)
    self.assertEqual(bridge.ack,0)
    self.assertGreater(monitor.results[-1]['control_journal']['session']['target_ac_w'],0)
    bridge.process.terminate();lock.rollback();lock.close();lock=None
    wait_for(self,lambda:bridge.snapshot()['committed_seq']==bridge.last_accepted)
    self.assertEqual(bridge.guard.restarts,1);self.assertEqual(bridge.loss['batches'],0)
    store=Store(path)
    try:
     run=unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
     self.assertEqual(run,monitor.results[-1]['control_journal']['session'])
     self.assertEqual(run['event_count'],store.db.execute('SELECT count(*)FROM ram_control_events').fetchone()[0])
     self.assertEqual(run['statistics']['sample_count'],store.db.execute('SELECT count(*)FROM ram_control_samples').fetchone()[0])
     self.assertGreater(store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
    finally:store.close()
   finally:
    if lock:lock.close()
    bridge.close()

 def test_complete_two_hour_window_repeated_failures_and_exact_close(self):
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite');clock=Clock();client=WindowClient(clock)
   metrics={'steps':0,'failures':0,'resumed':False};final={}
   class Evidence:
    loss={'batches':0}
    def seed(self):return {}
    def snapshot(self):return {'status':'ok','analysis':result(clock.now()),'transport':{}}
    def submit(self,rows,states,value,failure_generation=None):
     metrics['steps']+=1
     batch={'runtime':'synthetic-window','seq':metrics['steps'],'at':value['at'],'rows':rows,'loss':{}}
     iso.persist_batch(store,batch);iso.persist_batch(store,batch);transport.enqueue(store,value['control_journal']);return True
   class Sink:
    def snapshot(self):return {'status':'ok'}
    def submit(self,value):
     run=value['control_journal']['session'];target=run['target_ac_w']
     if not math.isfinite(target)or target<0:raise AssertionError('Invalid target')
     if value['collection_health']['status']=='failed':
      metrics['failures']+=1
      if target!=0:raise AssertionError('Input failure did not stop')
     if clock.sec>3620 and target>0:metrics['resumed']=True
     if target>0:
      intent=run['last_intent']
      if not 0<(instant(intent['expires_at'])-instant(intent['at'])).total_seconds()<=10:raise AssertionError('Invalid lease')
      if instant(intent['expires_at'])>instant(run['window_end']):raise AssertionError('Lease beyond window')
     for sample in value['control_journal'].get('recent_samples',[])[:1]:
      for phase in sample.get('phase',[]):
       amps=phase.get('planned_grid_a')
       if amps is not None and abs(amps)>25+1e-6:raise AssertionError('Phase envelope exceeded')
     final['value']=copy.deepcopy(value);return True
   try:
    iso.run_loop(client,Evidence(),Sink(),WindowStop(clock),clock.now,lambda:clock.sec)
    run=final['value']['control_journal']['session']
    self.assertEqual(metrics['failures'],3);self.assertTrue(metrics['resumed'])
    self.assertTrue(run['closed_at']);self.assertEqual(run['target_ac_w'],0)
    self.assertGreaterEqual(metrics['steps'],1440)
    self.assertEqual(unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0]),run)
    self.assertEqual(run['statistics']['sample_count'],store.db.execute('SELECT count(*)FROM ram_control_samples').fetchone()[0])
    self.assertEqual(run['event_count'],store.db.execute('SELECT count(*)FROM ram_control_events').fetchone()[0])
    events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
    self.assertEqual(sum(e['kind']=='collection_failure'for e in events),3)
    self.assertTrue(all(e['device_actions']==0 and e['persistent_writes']==0 for e in events))
    self.assertEqual(store.db.execute('PRAGMA quick_check').fetchone()[0],'ok')
   finally:store.close()
