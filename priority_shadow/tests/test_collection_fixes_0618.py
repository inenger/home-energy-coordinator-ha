"""Regrese A16: skutečná main smyčka → RAM → SQLite/outbox, bez HA/služeb."""
import unittest,tempfile,time,copy,contextlib,io,math
from pathlib import Path
from datetime import datetime
from unittest.mock import patch,MagicMock
from energy import priority_observer as obs,priority_collection as collection,ram_control as c,night,priority
from energy.priority_collection import SnapshotCollector
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
from test_night import state

class CollectionFixTests(unittest.TestCase):
 def drive(self,dropout=False,mask=None,poll_period=None,work_s=0,lag_s=4):
  with tempfile.TemporaryDirectory()as folder:
   folder=Path(folder);store=Store(folder/'evidence.sqlite');at_start=10 if mask else 0
   class Clock:
    sec=6 if mask else 0
    @staticmethod
    def now(tz):return datetime.fromisoformat(stamp(Clock.sec)).astimezone(tz)
   class Stop:
    n=0;waits=[]
    def is_set(self):return self.n>=2 if mask else Clock.sec>=125
    def wait(self,seconds):
     assert .25<=seconds<=5,seconds
     self.waits.append(seconds);self.n+=1;Clock.sec+=seconds
     assert self.n<200,'Busy loop'
   stop=Stop();worker=SnapshotCollector(None,failure_path=folder/'failure.json')
   if mask:
    for sec in [0,5]:c.observe(store,data(stamp(sec)),result(stamp(sec)))
    with patch.object(collection,'datetime',Clock):worker.failed(TimeoutError())
   Clock.sec=at_start;read_reports=[];acks=[];real_ack=worker.acknowledge_failure
   def read():
    period=poll_period if poll_period is not None else obs.SnapshotCollector.call_args.kwargs['night_period']
    captured=math.floor(Clock.sec/period)*period
    solar=math.floor((captured-lag_s)/5)*5
    ev=math.floor((captured-lag_s+.2)/8)*8-.2
    if dropout and 16<=Clock.sec<40:ev=7.8
    states=data(stamp(solar))
    for state in states:
     if state['entity_id']in [night.IDS['ev_w'],*[priority.EXTRA[f'ev_l{i}_w']for i in [1,2,3]]]:state['last_reported']=stamp(ev)
    worker.receipt={'sequence':int(captured/period)+1,'request_started_at':stamp(captured),'received_at':stamp(captured),'request_duration_s':0,'poll_interval_s':period}
    read_reports.append((Clock.sec,ev))
    worker.states=states;worker.received=captured;worker.error=None
    return SnapshotCollector.priority_states(worker)
   checks=[0]
   def size(*a,**k):
    checks[0]+=1
    if mask and checks[0]==1:
     if mask=='stat':raise PermissionError('synthetic stat failure')
     return 3*1024**3
    return 0
   def ack(g):
    rows=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
    self.assertTrue(any(e['kind']=='collection_failure'and e['at']==stamp(6)for e in rows))
    self.assertGreater(store.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0],0)
    acks.append(g);return real_ack(g)
   def observed(store,states,at,finish_closed=False):
    Clock.sec+=work_s
    return {**result(at),'selected':{'reason':'ev_first','battery_ac_w':1000},'active':True,'collection_health':{'status':'ok'}}
   maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
   monitor=MagicMock();monitor.snapshot.return_value={}
   output=io.StringIO()
   with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs,'SnapshotCollector',return_value=worker),patch.object(worker,'start',return_value=worker),patch.object(worker,'priority_states',side_effect=read),patch.object(worker,'acknowledge_failure',side_effect=ack),patch.object(obs,'ReadOnlyHA'),patch.object(obs,'sqlite_bytes',side_effect=size),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs,'MonitorPublisher',return_value=MagicMock(start=lambda:monitor)),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',stop),patch.object(obs,'datetime',Clock),patch.object(obs.time,'monotonic',side_effect=lambda:Clock.sec),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=observed),patch.object(obs,'atomic_json'),contextlib.redirect_stdout(output):
    obs.main()
   samples=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_samples ORDER BY at')]
   events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
   row=store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()
   if not row:raise AssertionError(output.getvalue())
   run=unpack(row[0])
   count=store.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0];store.close()
   self.plans=[copy.deepcopy(call.args[0])for call in monitor.submit.call_args_list]
   return run,samples,events,stop.waits,read_reports,acks,count


 def test_actual_main_keeps_delayed_reports_continuous_with_nonzero_work(self):
  for work in (0,1,2,3):
   with self.subTest(work=work):
    run,samples,events,waits,*_=self.drive(work_s=work)
    self.assertFalse([e for e in events if e['kind']=='would_stop_charge'])
    self.assertGreater(run['shadow_model']['battery_kwh_ac'],0)
    energy=0
    for a,b in zip(samples,samples[1:]):
     if a['ram_target_ac_w']<=0:continue
     end=min(datetime.fromisoformat(b['at']),datetime.fromisoformat(a['intent_expires_at']))
     energy+=a['ram_target_ac_w']*max(0,(end-datetime.fromisoformat(a['at'])).total_seconds())/3600000
    self.assertAlmostEqual(energy,run['shadow_model']['battery_kwh_ac'])
    self.assertTrue(all(s['collection_snapshot']['read_at']==s['at']for s in samples))
    deferred=[p for p in self.plans if p.get('analytics_scheduling',{}).get('deferred_for_control_deadline')]
    self.assertTrue(all('command_audit'in p for p in deferred))
    self.assertTrue(all(p['at']<=p['control_journal']['observed_at']for p in deferred))
    self.assertTrue(all(datetime.fromisoformat(s['intent_expires_at'])<=datetime.fromisoformat(s['input_valid_until'])for s in samples if s['ram_target_ac_w']>0))

 def test_true_dropout_still_stops_and_recovers_after_new_frames(self):
  run,samples,events,*_=self.drive(work_s=3,dropout=True)
  self.assertTrue(any(e['kind']=='would_stop_charge'for e in events))
  invalid=[s for s in samples if s['input_errors']]
  self.assertTrue(invalid);self.assertTrue(all(s['ram_target_ac_w']==0 for s in invalid))
  self.assertTrue(any(s['ram_target_ac_w']>0 and datetime.fromisoformat(s['at'])>datetime.fromisoformat(stamp(60))for s in samples))
