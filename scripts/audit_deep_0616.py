"""Synthetic 0.6.16 audit: complete observer and RAM/SQLite/outbox paths, no HA."""
import sys,os,json,tempfile,time,copy,contextlib,io,math
from pathlib import Path
from datetime import datetime
from unittest.mock import patch,MagicMock
repo=Path(__file__).resolve().parents[1];sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from energy import ram_control as c,priority_observer as obs,priority_collection as collection,journal_transport,night,priority
import historical_observer_0619 as obs  # explicit coupled-loop historical baseline
from energy.priority_collection import SnapshotCollector
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
out=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/audit-0616'));out.mkdir(parents=True,exist_ok=True)
results={}
def main_probe(mask):
 with tempfile.TemporaryDirectory()as folder:
  folder=Path(folder);store=Store(folder/'evidence.sqlite')
  for sec in [0,5]:c.observe(store,data(stamp(sec)),result(stamp(sec)))
  class Clock:
   sec=6
   @staticmethod
   def now(tz):return datetime.fromisoformat(stamp(Clock.sec)).astimezone(tz)
  class Stop:
   n=0
   def is_set(self):return self.n>=2
   def wait(self,_):self.n+=1;Clock.sec+=5
  worker=SnapshotCollector(None,failure_path=folder/'failure.json')
  with patch.object(collection,'datetime',Clock):worker.failed(TimeoutError())
  Clock.sec=10;checks=[0]
  def storage(*a,**k):
   checks[0]+=1;return 3*1024**3 if mask and checks[0]==1 else 0
  def read():
   worker.states=data(stamp(Clock.sec));worker.received=time.monotonic();worker.error=None
   return SnapshotCollector.priority_states(worker)
  def observed(store,states,at,finish_closed=False):
   return {**result(at),'selected':{'reason':'ev_first','battery_ac_w':1000},'active':True,'collection_health':{'status':'ok'}}
  maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
  monitor=MagicMock();monitor.snapshot.return_value={}
  with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs,'SnapshotCollector',return_value=worker),patch.object(worker,'start',return_value=worker),patch.object(worker,'priority_states',side_effect=read),patch.object(obs,'ReadOnlyHA'),patch.object(obs,'sqlite_bytes',side_effect=storage),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs,'MonitorPublisher',return_value=MagicMock(start=lambda:monitor)),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',Stop()),patch.object(obs,'datetime',Clock),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=observed),patch.object(obs,'atomic_json'),contextlib.redirect_stdout(io.StringIO()):
   obs.main()
  run=unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
  events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
  energy=run['shadow_model']['battery_kwh_ac']
  view={'masked_by_storage_budget':mask,'worker_failure_second':6,'consumer_second':10,'expected_ac_kwh':500/3600000,'actual_ac_kwh':energy,'overcount_kwh':energy-500/3600000,'stop_times':[e['at']for e in events if e['kind']=='would_stop_charge'],'failure_times':[e['at']for e in events if e['kind']=='collection_failure'],'outbox_parts':store.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0],'pending_failure_after':worker.pending_failure,'contract_met':math.isclose(energy,500/3600000,abs_tol=1e-12)}
  store.close();return view
results['A16-02_storage_masks_earlier_failure']=main_probe(True)
results['failure_without_mask_control']=main_probe(False)
def cadence(slow_ev,delay=4):
 with tempfile.TemporaryDirectory()as folder:
  s=Store(Path(folder)/'e.sqlite');reads=[]
  for sec in range(0,125,5):
   states=data(stamp(sec));report=(math.floor((sec-delay+.2)/8)*8-.2)if slow_ev else sec
   for state in states:
    if state['entity_id']in [night.IDS['ev_w'],*[priority.EXTRA[f'ev_l{i}_w']for i in [1,2,3]]]:state['last_reported']=stamp(report)
   v=c.observe(s,states,result(stamp(sec)));reads.append(v['recent_samples'][0])
  journal_transport.enqueue(s,v);events=[unpack(p)for p, in s.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
  expiry=[e for e in events if e['reason']=='logical_lease_expired'and e['kind']=='would_stop_charge']
  view={'ev_report_period_s':8 if slow_ev else 5,'delivery_delay_s':delay if slow_ev else 0,'controller_period_s':5,'all_current_frames_valid':all(not x['input_errors']for x in reads),'logical_expiry_stops':len(expiry),'zero_samples_after_start':sum(x['ram_target_ac_w']==0 for x in reads[2:]),'outbox_parts':s.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0],'continuous_model_contract_met':not expiry}
  s.close();return view
results['A16-01_ev_report_cadence']=cadence(True)
results['five_second_ev_control']=cadence(False)
results['eight_second_ev_without_delivery_delay_control']=cadence(True,0)
(out/'backend-probes.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
