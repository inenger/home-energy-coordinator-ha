"""Syntetický audit 0.6.15. Nevolá HA ani zařízení; FAIL je auditní nález."""
import os,sys,json,tempfile,threading,queue,time
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from energy.priority_collection import SnapshotCollector
from energy import ram_control as c,journal_transport
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
out=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/audit-0615'));out.mkdir(parents=True,exist_ok=True)
commands=queue.Queue()
class Client:
 def priority_states(self):
  command=commands.get(timeout=3)
  if isinstance(command,Exception):raise command
  return command
def await_state(worker,predicate):
 deadline=time.monotonic()+3
 while time.monotonic()<deadline:
  with worker.condition:
   if predicate(worker):return
  time.sleep(.002)
 raise AssertionError('Worker synchronization timeout')
worker=SnapshotCollector(Client(),period=.01).start()
results={}
try:
 with tempfile.TemporaryDirectory(dir=out)as folder:
  store=Store(Path(folder)/'synthetic.sqlite')
  for sec in (0,5):
   commands.put(data(stamp(sec)))
   await_state(worker,lambda w:w.states is not None and w.states[0]['last_reported']==stamp(sec))
   view=c.observe(store,worker.priority_states(),result(stamp(sec)))
  before=view['session']['target_ac_w'];assert before>0
  commands.put(TimeoutError('synthetic transient failure'))
  await_state(worker,lambda w:w.error=='TimeoutError')
  observed_error=worker.snapshot()['error_code']
  # Ověřený výpadek nastal mezi dvěma čteními řídicí smyčky.
  commands.put(data(stamp(10)))
  await_state(worker,lambda w:w.error is None and w.states[0]['last_reported']==stamp(10))
  raised=False
  try:states=worker.priority_states()
  except RuntimeError:
   raised=True;view=c.record_failure(store,stamp(10),'collector_failure')
  else:view=c.observe(store,states,result(stamp(10)))
  transport=journal_transport.enqueue(store,view)
  events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
  failures=[e for e in events if e['kind']=='collection_failure']
  results['A15-01']={'worker_error_observed':observed_error,'consumer_was_notified':raised,'power_before_w':before,'power_after_recovery_w':view['session']['target_ac_w'],'failure_events':len(failures),'outbox_chunks':transport['queued_seq'],'contract_met':raised and view['session']['target_ac_w']==0}
  # Kontrolní větev: pokud konzument chybu stihne přečíst, musí fungovat stop.
  commands.put(TimeoutError('persistent until consumed'))
  await_state(worker,lambda w:w.error=='TimeoutError')
  try:worker.priority_states()
  except RuntimeError:view=c.record_failure(store,stamp(12),'collector_failure')
  else:raise AssertionError('Control case did not expose failure')
  recovered=c.observe(store,data(stamp(15)),result(stamp(15)))
  results['persistent_error_control']={'stopped_w':view['session']['target_ac_w'],'first_recovery_frame_w':recovered['session']['target_ac_w'],'contract_met':view['session']['target_ac_w']==0 and recovered['session']['target_ac_w']==0}
  store.close()
finally:
 worker.stop.set();commands.put(data(stamp(20)));worker.close()
(out/'backend-probes.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
