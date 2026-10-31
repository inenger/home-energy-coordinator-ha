"""Synthetic counterexamples against the frozen deployed source; no HA calls."""
import sys,tempfile,json,copy,contextlib,io,os,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,MagicMock
repo=Path(__file__).resolve().parents[1];r=Path(os.environ.get('ENERGY_AUDIT_OUTPUT',Path.cwd()));r.mkdir(parents=True,exist_ok=True);sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from energy import ram_control as c,journal_transport as t,priority_observer as obs,publish_status as pub,priority_publication as publication
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
out={}
with tempfile.TemporaryDirectory()as folder:
 path=Path(folder)/'d.sqlite';store=Store(path)
 for sec in (0,5,10):v=c.observe(store,data(stamp(sec)),result(stamp(sec)))
 c.record_failure(store,stamp(12),'SyntheticFailure')
 v=c.observe(store,data(stamp(20)),result(stamp(20)))
 events=[{'id':i,**unpack(p)}for i,p in store.db.execute('SELECT id,payload FROM ram_control_events ORDER BY id')]
 samples=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_samples ORDER BY at')]
 assert any(e['kind']=='would_stop_charge'and e['at']==stamp(12)for e in events)
 (r/'controller-failure-fixture.json').write_text(json.dumps({'session':v['session'],'events':events,'samples':samples}))
 out['graph_failure_source']={'last_positive_sample':samples[-2]['at'],'explicit_stop_at':stamp(12),'next_zero_sample':samples[-1]['at'],'device_actions':0}
 store.close()
with tempfile.TemporaryDirectory()as folder:
 path=Path(folder)/'d.sqlite';store=Store(path)
 # Two different local days after the wall clock moved backwards by one day.
 for sec in (86400,86405,0,5):v=c.observe(store,data(stamp(sec)),result(stamp(sec)))
 owned=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_sessions')if unpack(p).get('owned')and not unpack(p).get('closed_at')]
 out['clock_rollback_owners']={'open_virtual_owners':len(owned),'days':[s['day']for s in owned],'contract_met':len(owned)<=1}
 store.close()
with tempfile.TemporaryDirectory()as folder:
 path=Path(folder)/'d.sqlite';store=Store(path)
 for sec in (0,5):v=c.observe(store,data(stamp(sec)),result(stamp(sec)))
 t.enqueue(store,v);head=t.status(store)['queued_seq']
 class DelayedRecorder:
  now=datetime.fromisoformat(stamp(10));published=[]
  def publish(self,a):self.published.append((self.now,copy.deepcopy(a)))
  def history(self,begin,end):
   lo=datetime.fromisoformat(begin);hi=datetime.fromisoformat(end)
   return [[{'attributes':a,'last_updated':at.isoformat()}for at,a in self.published if lo<=at<=hi and (self.now-at).total_seconds()>=30]]
 client=DelayedRecorder();worker=t.Publisher(path,client)
 for sec in range(10,191):
  client.now=datetime.fromisoformat(stamp(sec));worker.tick(client.now)
 status=t.status(store)
 out['delayed_recorder']={'commit_delay_s':30,'simulated_seconds':180,'queued_chunks':head,'recorded_chunks':status['recorded_seq'],'published_states':len(client.published),'committed_states':sum((client.now-at).total_seconds()>=30 for at,_ in client.published),'status':status.get('status'),'error':status.get('error_code'),'contract_met':status['recorded_seq']==head}
 store.close()
with tempfile.TemporaryDirectory()as folder:
 base=Path(folder);(base/'options.json').write_text('{}');path=base/'evidence.sqlite';store=Store(path)
 for sec in (0,5):c.observe(store,data(stamp(sec)),result(stamp(sec)))
 origin=time.monotonic()
 class Clock:
  @classmethod
  def now(cls,tz):return datetime.fromisoformat(stamp(10+time.monotonic()-origin)).astimezone(tz)
 class Stop:
  loops=0
  def is_set(self):return self.loops>=2
  def wait(self,seconds):time.sleep(seconds);self.loops+=1
 class Client:
  def priority_states(self):return data(Clock.now(None).isoformat())
 class Opener:
  calls=0
  def open(self,request,timeout):
   self.calls+=1;time.sleep(1)
   class Response:
    status=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
   return Response()
 opener=Opener();maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
 def planned(store,states,at,finish_closed=False):
  return {**result(at),'active':True,'version':'0.6.12','selected':{'reason':'ev_first','ev_ac_w':11040,'battery_ac_w':1000,'grid_model_w':12040},'collection_health':{'status':'ok'}}
 with patch.object(obs,'Path',side_effect=lambda p:base/'options.json' if p=='/data/options.json' else Path(p)),patch.object(obs,'DATA',base),patch.object(obs,'datetime',Clock),patch.object(obs,'ReadOnlyHA',return_value=Client()),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',Stop()),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=planned),patch.object(pub,'read_token',return_value='synthetic'),patch.object(publication,'read_token',return_value='synthetic'),patch.object(pub.urllib.request,'build_opener',return_value=opener),contextlib.redirect_stdout(io.StringIO()):
  obs.main()
 run=unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
 events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
 fast=json.loads((base/'priority-live.json').read_text())['fast_loop']
 out['synchronous_monitoring']={'per_HTTP_latency_s':1,'monitor_HTTP_calls':opener.calls,'last_processed_at':run['last_processed_at'],'sampling_gap_events':[e.get('gap_seconds')for e in events if e['kind']=='sampling_gap'],'stop_reasons':[e['reason']for e in events if e['kind']=='would_stop_charge'],'reported_work_duration_s':fast['last_work_duration_s'],'contract_met':not any(e['kind']=='sampling_gap'for e in events)}
 store.close()
(r/'backend-probes.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
