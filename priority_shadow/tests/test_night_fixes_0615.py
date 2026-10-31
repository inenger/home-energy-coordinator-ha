"""Nízký P/UI není chybějící měření; síť nesmí blokovat řídicí smyčku."""
import unittest,threading,time,tempfile
from pathlib import Path
from energy import instant_fill as f,ram_control as c,night
from energy.store import Store
from energy.priority_collection import SnapshotCollector
from test_instant_fill import points,SESSION
from test_ram_control import data,result,stamp
from test_control_journal import patch_value
class NightFixTests(unittest.TestCase):
 def test_low_ratio_uses_current_bound_and_preserves_upper_rejection(self):
  p=points(base=(171,80,76),ev=0);p['grid_l1_a']['value']=1.5
  r=f.allocate(p,stamp(0),SESSION,11,'ev');self.assertIsNotNone(r['battery_ac_w']);row=r['phase'][0]
  self.assertEqual(row['proxy_method'],'low_current_triangle_bound');self.assertAlmostEqual(row['planned_model_a'],1.5+r['battery_ac_w']/3/230);self.assertTrue(all(x['planned_model_a']<=25 for x in r['phase']))
  p['grid_l1_w']['value']=-1000;self.assertEqual(f.allocate(p,stamp(0),SESSION,11,'ev')['reason'],'invalid_phase_input')
 def test_zero_active_power_does_not_divide_by_zero(self):
  p=points(base=(0,80,76),ev=0);p['grid_l1_a']['value']=1.5
  r=f.allocate(p,stamp(0),SESSION,11,'ev');self.assertIsNotNone(r['battery_ac_w']);self.assertLessEqual(r['phase'][0]['planned_model_a'],25)
 def test_low_ratio_controller_and_transport_path(self):
  with tempfile.TemporaryDirectory()as folder:
   s=Store(Path(folder)/'e.sqlite')
   for t in [0,5,10]:
    ss=data(stamp(t))
    for i,(w,a)in enumerate([(171,1.5),(80,.5),(76,.6)],1):
     patch_value(ss,night.IDS[f'grid_l{i}_w'],-w);patch_value(ss,night.IDS[f'grid_l{i}_a'],a);patch_value(ss,f'sensor.solax_api_charge_power_l{i}',0)
    patch_value(ss,'sensor.solax_api_charge_power_total',0);v=c.observe(s,ss,result(stamp(t)))
   self.assertGreater(v['session']['target_ac_w'],0);self.assertFalse(v['recent_samples'][0]['input_errors']);self.assertEqual(v['session']['statistics']['model_exceedance_samples'],0)
   from energy.journal_transport import enqueue
   self.assertGreater(enqueue(s,v)['queued_seq'],0);s.close()
 def test_slow_network_never_blocks_cache_read_and_old_snapshot_expires(self):
  entered=threading.Event();release=threading.Event()
  class Client:
   n=0
   def priority_states(self):
    self.n+=1
    if self.n>1:entered.set();release.wait(2)
    return [{'entity_id':'sensor.synthetic','last_reported':'2026-01-15T02:00:00+00:00'}]
  worker=SnapshotCollector(Client(),period=.01,max_age=.12).start()
  try:
   original=worker.priority_states();self.assertTrue(entered.wait(1));started=time.monotonic();self.assertEqual(worker.priority_states(),original);self.assertLess(time.monotonic()-started,.05)
   time.sleep(.15)
   with self.assertRaisesRegex(RuntimeError,'EXPIRED'):worker.priority_states()
   self.assertEqual(original[0]['last_reported'],'2026-01-15T02:00:00+00:00')
  finally:release.set();worker.close()
 def test_explicit_network_error_revokes_cache(self):
  class Client:
   n=0
   def priority_states(self):
    self.n+=1
    if self.n>1:raise TimeoutError()
    return []
  worker=SnapshotCollector(Client(),period=.01).start()
  try:
   worker.priority_states();time.sleep(.15)
   with self.assertRaisesRegex(RuntimeError,'WORKER_FAILED'):worker.priority_states()
  finally:worker.close()
 def test_collection_cadence_does_not_alias_five_second_device_reports(self):
  import math
  def replay(period):
   with tempfile.TemporaryDirectory()as folder:
    s=Store(Path(folder)/'e.sqlite')
    for i in range(200):
     observed=i*5+.1;last_poll=max(0,math.floor((observed-.2)/period)*period);reported=math.floor(last_poll/5.01)*5.01
     v=c.observe(s,data(stamp(reported)),result(stamp(observed)))
    from energy.store import unpack
    expirations=sum(unpack(p).get('reason')=='logical_lease_expired'for p, in s.db.execute('SELECT payload FROM ram_control_events'));s.close();return expirations
  self.assertGreater(replay(5),0,'Counterexample must expose equal-period sampling alias')
  self.assertEqual(replay(2.5),0,'Faster read-only polling must not renew source timestamps or expire healthy input leases')
 def test_busy_database_does_not_take_ten_seconds_from_control_loop(self):
  import sqlite3
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';s=Store(path)
   c.observe(s,data(stamp(0)),result(stamp(0)));c.observe(s,data(stamp(5)),result(stamp(5)))
   lock=sqlite3.connect(path);lock.execute('BEGIN IMMEDIATE');started=time.monotonic()
   try:
    fast=None
    with self.assertRaises(sqlite3.OperationalError):
     fast=Store(path,timeout=.25);c.record_failure(fast,stamp(6),'synthetic_lock')
    self.assertLess(time.monotonic()-started,1.2)
   finally:
    if fast:fast.close()
    lock.rollback();lock.close()
   c.record_failure(s,stamp(6),'collection_failure_pending');v=c.observe(s,data(stamp(10)),result(stamp(10)))
   self.assertEqual(v['session']['target_ac_w'],0);self.assertGreater(c.observe(s,data(stamp(15)),result(stamp(15)))['session']['target_ac_w'],0);s.close()
 def test_observer_replays_unpersisted_failure_at_original_time(self):
  import sqlite3,copy,contextlib,io,json
  from unittest.mock import patch,MagicMock
  from datetime import datetime
  from energy import priority_observer as obs
  with tempfile.TemporaryDirectory()as folder:
   folder=Path(folder);path=folder/'evidence.sqlite';s=Store(path)
   for t in [0,5]:c.observe(s,data(stamp(t)),result(stamp(t)))
   class Clock:
    now_s=10
    @staticmethod
    def now(tz):return datetime.fromisoformat(stamp(Clock.now_s)).astimezone(tz)
   class Stop:
    n=0
    def is_set(self):return self.n>=3
    def wait(self,seconds):self.n+=1;Clock.now_s+=5
   class Client:
    def start(self):return self
    def priority_states(self):return data(stamp(Clock.now_s))
    def snapshot(self):return {}
    def close(self):return True
   calls=[0];saved=[]
   def connect(p,**kwargs):
    calls[0]+=1
    if calls[0]<=2:raise sqlite3.OperationalError('synthetic locked database')
    return Store(p,**kwargs)
   def observed(store,states,at,finish_closed=False):return {**result(at),'selected':{'reason':'ev_first','battery_ac_w':1000},'active':True,'collection_health':{'status':'ok'}}
   maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False;monitor=MagicMock();monitor.snapshot.return_value={}
   with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs,'SnapshotCollector',return_value=Client()),patch.object(obs,'ReadOnlyHA'),patch.object(obs,'Store',side_effect=connect),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs,'MonitorPublisher',return_value=MagicMock(start=lambda:monitor)),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',Stop()),patch.object(obs,'datetime',Clock),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=observed),patch.object(obs,'atomic_json',side_effect=lambda p,v:saved.append(copy.deepcopy(v))),contextlib.redirect_stdout(io.StringIO()):obs.main()
   self.assertEqual(saved[0]['unpersisted_failure_at'],stamp(10))
   from energy.store import unpack
   events=[unpack(p)for p, in s.db.execute('SELECT payload FROM ram_control_events')]
   self.assertTrue(any(e['kind']=='collection_failure'and e['at']==stamp(10)for e in events))
   samples=[unpack(p)for p, in s.db.execute('SELECT payload FROM ram_control_samples ORDER BY at')]
   self.assertEqual(next(p for p in samples if p['at']==stamp(15))['ram_target_ac_w'],0);self.assertGreater(samples[-1]['ram_target_ac_w'],0)
   run=unpack(s.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0]);self.assertAlmostEqual(run['shadow_model']['battery_kwh_ac'],500*5/3600000);s.close()
