"""Regrese A16: skutečná main smyčka → RAM → SQLite/outbox, bez HA/služeb."""
import unittest,tempfile,time,copy,contextlib,io,math
from pathlib import Path
from datetime import datetime
from unittest.mock import patch,MagicMock
from energy import priority_observer as obs,priority_collection as collection,ram_control as c,night,priority
from energy.priority_collection import SnapshotCollector
from energy.store import Store,unpack
from test_ram_control import data,result,stamp

class AuditFixTests(unittest.TestCase):
 def drive(self,dropout=False,mask=None):
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
    solar=math.floor(Clock.sec/5)*5
    ev=math.floor((Clock.sec-4+.2)/8)*8-.2
    if dropout and 16<=Clock.sec<40:ev=7.8
    states=data(stamp(solar))
    for state in states:
     if state['entity_id']in [night.IDS['ev_w'],*[priority.EXTRA[f'ev_l{i}_w']for i in [1,2,3]]]:state['last_reported']=stamp(ev)
    read_reports.append((Clock.sec,ev))
    worker.states=states;worker.received=Clock.sec;worker.error=None
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
    return {**result(at),'selected':{'reason':'ev_first','battery_ac_w':1000},'active':True,'collection_health':{'status':'ok'}}
   maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
   monitor=MagicMock();monitor.snapshot.return_value={}
   with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs,'SnapshotCollector',return_value=worker),patch.object(worker,'start',return_value=worker),patch.object(worker,'priority_states',side_effect=read),patch.object(worker,'acknowledge_failure',side_effect=ack),patch.object(obs,'ReadOnlyHA'),patch.object(obs,'sqlite_bytes',side_effect=size),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs,'MonitorPublisher',return_value=MagicMock(start=lambda:monitor)),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',stop),patch.object(obs,'datetime',Clock),patch.object(obs.time,'monotonic',side_effect=lambda:Clock.sec),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=observed),patch.object(obs,'atomic_json'),contextlib.redirect_stdout(io.StringIO()):
    obs.main()
   samples=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_samples ORDER BY at')]
   events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
   run=unpack(store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
   count=store.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0];store.close()
   return run,samples,events,stop.waits,read_reports,acks,count

 def test_deadline_aware_main_keeps_valid_delayed_ev_data_continuous(self):
  run,samples,events,waits,reports,acks,count=self.drive()
  self.assertTrue(all(not s['input_errors']for s in samples))
  self.assertFalse(any(e['kind']=='would_stop_charge'for e in events))
  self.assertTrue(any(w<5 for w in waits));self.assertTrue(any(s['intent_renewal']=='held_validated_frame'for s in samples))
  for s in samples:
   if s['ram_target_ac_w']>0:self.assertLessEqual(datetime.fromisoformat(s['intent_expires_at']),datetime.fromisoformat(s['input_valid_until']))
  energy=sum(a['ram_target_ac_w']*(datetime.fromisoformat(b['at'])-datetime.fromisoformat(a['at'])).total_seconds()/3600000 for a,b in zip(samples,samples[1:]))
  self.assertAlmostEqual(energy,run['shadow_model']['battery_kwh_ac']);self.assertGreater(count,0)
  self.assertTrue(all(ev<=t for t,ev in reports))

 def test_real_ev_dropout_still_stops_and_requires_two_new_solax_frames(self):
  run,samples,events,*_=self.drive(dropout=True)
  self.assertTrue(any(e['kind']=='would_stop_charge'for e in events))
  self.assertTrue(any(s['input_errors']for s in samples))
  recovered=[s for s in samples if datetime.fromisoformat(s['at'])>=datetime.fromisoformat(stamp(40))]
  self.assertEqual(recovered[0]['ram_target_ac_w'],0)
  self.assertGreater(next(s for s in recovered[1:]if s['new_frame'])['ram_target_ac_w'],0)

 def test_storage_budget_preserves_earlier_worker_stop_and_energy(self):
  run,samples,events,waits,reports,acks,count=self.drive(mask='budget')
  self.assertAlmostEqual(run['shadow_model']['battery_kwh_ac'],500/3600000)
  self.assertEqual([e['at']for e in events if e['kind']=='would_stop_charge'],[stamp(6)])
  self.assertEqual(acks,[1]);self.assertGreater(count,0)

 def test_stat_exception_preserves_earlier_worker_stop(self):
  run,*_=self.drive(mask='stat')
  self.assertAlmostEqual(run['shadow_model']['battery_kwh_ac'],500/3600000)

 def test_wait_respects_lease_work_and_outside_window(self):
  journal={'session':{'target_ac_w':500,'last_intent':{'expires_at':stamp(9.8)}}}
  self.assertAlmostEqual(obs.next_wait(stamp(5),0,journal),3.8)
  self.assertAlmostEqual(obs.next_wait(stamp(5),4,journal),.55)
  self.assertEqual(obs.next_wait(stamp(10),0,journal),.25)
  self.assertEqual(obs.next_wait('2026-01-15T10:00:00+00:00',0),60)
