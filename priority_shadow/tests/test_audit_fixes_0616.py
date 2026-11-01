"""A15-01: acknowledgement follows persisted stop/outbox, never collection success."""
import unittest,time,tempfile,sqlite3,copy,contextlib,io
from pathlib import Path
from datetime import datetime
from unittest.mock import patch,MagicMock
from energy.priority_collection import SnapshotCollector,CollectionFailure
from energy import priority_collection as collection,priority_observer as obs,ram_control as c
from energy.store import Store,unpack
from test_ram_control import data,result,stamp

class AuditFixTests(unittest.TestCase):
 def test_unacknowledged_error_survives_success_restart_and_old_ack(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'failure.json';worker=SnapshotCollector(None,failure_path=path)
   worker.failed(TimeoutError());first=copy.deepcopy(worker.pending_failure)
   worker.states=[];worker.received=time.monotonic();worker.error=None
   with self.assertRaises(CollectionFailure):worker.priority_states()
   restored=SnapshotCollector(None,failure_path=path)
   self.assertEqual(restored.pending_failure,first)
   restored.failed(OSError())
   self.assertFalse(restored.acknowledge_failure(first['generation']))
   self.assertEqual(restored.pending_failure['first_at'],first['first_at'])
   self.assertTrue(restored.acknowledge_failure(restored.generation))
   self.assertIsNone(SnapshotCollector(None,failure_path=path).pending_failure)

 def test_failed_persistence_does_not_clear_pending_error(self):
  worker=SnapshotCollector(None)
  with patch.object(worker,'persist',side_effect=OSError('synthetic disk error')):
   worker.failed(TimeoutError())
   with self.assertRaises(OSError):worker.acknowledge_failure(worker.generation)
   self.assertIsNotNone(worker.pending_failure)
   with self.assertRaises(CollectionFailure):worker.priority_states()

 def test_main_acknowledges_after_stop_and_outbox_at_original_failure_time(self):
  with tempfile.TemporaryDirectory() as folder:
   folder=Path(folder);s=Store(folder/'evidence.sqlite')
   for t in [0,5]:c.observe(s,data(stamp(t)),result(stamp(t)))
   class Clock:
    now_s=6
    @staticmethod
    def now(tz):return datetime.fromisoformat(stamp(Clock.now_s)).astimezone(tz)
   class Stop:
    n=0
    def is_set(self):return self.n>=4
    def wait(self,seconds):self.n+=1;Clock.now_s+=5
   worker=SnapshotCollector(None,failure_path=folder/'collection-failure.json')
   with patch.object(collection,'datetime',Clock):worker.failed(TimeoutError())
   generation=worker.generation;Clock.now_s=10
   calls=[0];saved=[];acks=[];real_ack=worker.acknowledge_failure
   def connect(p,**kwargs):
    calls[0]+=1
    if calls[0]==1:raise sqlite3.OperationalError('synthetic locked database')
    return Store(p,**kwargs)
   def read():
    worker.states=data(stamp(Clock.now_s));worker.received=time.monotonic();worker.error=None
    return SnapshotCollector.priority_states(worker)
   def ack(g):
    events=[unpack(p) for p, in s.db.execute('SELECT payload FROM ram_control_events')]
    self.assertTrue(any(e['kind']=='collection_failure' and e['at']==stamp(6) for e in events))
    self.assertGreater(s.db.execute('SELECT count(*) FROM journal_transport_outbox').fetchone()[0],0)
    acks.append(g);return real_ack(g)
   def observed(store,states,at,finish_closed=False):
    return {**result(at),'selected':{'reason':'ev_first','battery_ac_w':1000},'active':True,'collection_health':{'status':'ok'}}
   maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
   monitor=MagicMock();monitor.snapshot.return_value={}
   with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json' if p=='/data/options.json' else Path(p)),patch.object(obs,'SnapshotCollector',return_value=worker),patch.object(worker,'start',return_value=worker),patch.object(worker,'priority_states',side_effect=read),patch.object(worker,'acknowledge_failure',side_effect=ack),patch.object(obs,'ReadOnlyHA'),patch.object(obs,'Store',side_effect=connect),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs,'MonitorPublisher',return_value=MagicMock(start=lambda:monitor)),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',Stop()),patch.object(obs,'datetime',Clock),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=observed),patch.object(obs,'atomic_json',side_effect=lambda p,v:saved.append(copy.deepcopy(v))),contextlib.redirect_stdout(io.StringIO()):
    obs.main()
   self.assertEqual(acks,[generation])
   self.assertEqual(saved[0]['unpersisted_failure_at'],stamp(6))
   self.assertIsNone(SnapshotCollector(None,failure_path=worker.failure_path).pending_failure)
   samples=[unpack(p) for p, in s.db.execute('SELECT payload FROM ram_control_samples ORDER BY at')]
   self.assertEqual(next(p for p in samples if p['at']==stamp(20))['ram_target_ac_w'],0)
   self.assertGreater(next(p for p in samples if p['at']==stamp(25))['ram_target_ac_w'],0)
   run=unpack(s.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
   self.assertAlmostEqual(run['shadow_model']['battery_kwh_ac'],500/3600000)
   s.close()
