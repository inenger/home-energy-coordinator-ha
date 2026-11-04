"""Reproduce known 0.6.21 readiness defects; success means defect reproduced.

Synthetic only, no HA client or device commands. Run from repository root.
This is an audit probe, not a passing readiness or regression certification.
"""
import sys,copy,tempfile,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'priority_shadow'),str(ROOT/'priority_shadow/tests')]
from energy import isolated_control as iso,journal_transport as transport
from energy.store import Store
from test_ram_control import stamp,result
from test_control_isolation_0620 import Clock,Client,Monitor,Evidence
class Schedule:
 def __init__(self,clock):self.clock=clock;self.times=iter([5,10,7195,7200,7260,7320,7380]);self.done=False
 def is_set(self):return self.done
 def wait(self,n):
  try:self.clock.sec=next(self.times)
  except StopIteration:self.done=True
class FaultEvidence(Evidence):
 def __init__(self,path):
  super().__init__();self.disk=Store(path);self.pending=[];self.conflicts=[];self.seq=0
  self.loss={'batches':0,'days':{},'first_at':None,'last_at':None}
 def submit(self,rows,states,value,failure_generation=None):
  self.seq+=1
  if value['at']==stamp(7260):
   self.loss.update(batches=1,days={value['at'][:10]:1},first_at=value['at'],last_at=value['at'])
   return False
  self.pending.append({'runtime':'synthetic','seq':self.seq,'at':value['at'],'loss':copy.deepcopy(self.loss),'rows':copy.deepcopy(rows),'result':copy.deepcopy(value)})
  while self.pending:
   item=self.pending[0]
   try:
    iso.persist_batch(self.disk,item)
    transport.enqueue(self.disk,item['result']['control_journal'])
    self.pending.pop(0)
   except ValueError as error:self.conflicts.append(str(error));break
  return True
def main():
 with tempfile.TemporaryDirectory()as folder:
  e=FaultEvidence(Path(folder)/'e.sqlite');clock=Clock();monitor=Monitor()
  try:
   iso.run_loop(Client(clock),e,monitor,Schedule(clock),clock.now,lambda:clock.sec)
   closed=monitor.results[-1]['control_journal']['session']['closed_at']
   assert closed and e.pending
   assert e.conflicts==['CLOSED_CONTROL_SESSION_CONFLICT']*2,e.conflicts
   assert e.disk.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0]>0
   print(json.dumps({'defect_reproduced':True,'production_path':'run_loop -> RAM -> FIFO persistence -> journal outbox','closed_session_conflicts':len(e.conflicts),'blocked_batches':len(e.pending),'physical_actions':0}))
  finally:e.disk.close()

# Independent recovery probe: real collector latch, synthetic cache and no storage ack.
import time
from energy import priority_collection as col
from test_ram_control import data
from test_control_isolation_0620 import Stop
class Latched(col.SnapshotCollector):
 def __init__(self,clock):super().__init__(None);self.clock=clock;self.injected=False
 def priority_states(self):
  if self.clock.sec>=10 and not self.injected:
   self.failed(TimeoutError('synthetic transient collection timeout'));self.injected=True
   with self.condition:self.pending_failure['first_at']=stamp(self.clock.sec)
  with self.condition:
   self.states=data(stamp(self.clock.sec));self.received=time.monotonic();self.error=None
  return super().priority_states()
def recovery_probe():
 clock=Clock();client=Latched(clock);evidence=Evidence(health='degraded');monitor=Monitor()
 iso.run_loop(client,evidence,monitor,Stop(clock),clock.now,lambda:clock.sec)
 active_before=[v for v in monitor.results if v['at']<stamp(10)]
 after=[v for v in monitor.results if v['at']>=stamp(15)]
 assert active_before[-1]['control_journal']['session']['target_ac_w']>0
 assert all(v['collection_health']['status']=='failed'and v['control_journal']['session']['target_ac_w']==0 for v in after)
 assert client.pending_failure and client.error is None
 out={'defect_reproduced':True,'production_path':'run_loop -> SnapshotCollector.priority_states -> pending failure latch -> RAM failure','fresh_cache_after_transient':True,'still_failed_frames':len(after),'final_target_w':after[-1]['control_journal']['session']['target_ac_w'],'recovery_requires_durable_evidence_ack':True}
 print(json.dumps(out))

if __name__=='__main__':
 main()
 recovery_probe()
