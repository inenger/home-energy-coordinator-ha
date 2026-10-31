"""D02/D03/D06 přes observer, skutečný Store/outbox a oddělené workery."""
import copy,contextlib,io,json,tempfile,threading,time,unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch,MagicMock
from energy import ram_control as c,journal_transport as t,priority_observer as obs,priority_publication as publication
from energy.store import Store,unpack
from test_ram_control import data,result,stamp

def monitor(sec=10):
 return {**result(stamp(sec)),'active':True,'version':'0.6.13',
  'selected':{'reason':'ev_first','ev_ac_w':11040,'battery_ac_w':1000,'grid_model_w':12040},
  'collection_health':{'status':'ok'}}

class DeepFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'evidence.sqlite';self.store=Store(self.path)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def step(self,sec):return c.observe(self.store,data(stamp(sec)),result(stamp(sec)))
 def ready(self):self.step(0);return self.step(5)
 def test_monitor_queue_is_bounded_latest_and_fair(self):
  sent=[];worker=publication.MonitorPublisher({'ha_base_url':'http://synthetic'},send=lambda e,p:sent.append((e,p)))
  for sec in range(100):worker.submit(monitor(sec))
  self.assertLessEqual(worker.snapshot()['pending_entities'],12)
  while worker.tick():pass
  self.assertEqual(len(sent),12);self.assertTrue(all(p['attributes']['observed_at']==stamp(99)for _,p in sent))
  self.assertTrue(all(e.startswith('sensor.nocni_stinov')for e,_ in sent))
 def test_one_failed_monitor_remains_degraded_until_that_entity_recovers(self):
  fail=[True]
  def send(e,p):
   if e=='sensor.nocni_stinovy_plan'and fail[0]:raise TimeoutError()
  worker=publication.MonitorPublisher({'ha_base_url':'http://synthetic'},send=send);worker.submit(monitor())
  self.assertFalse(worker.tick());self.assertTrue(worker.tick())
  self.assertEqual(worker.snapshot()['status'],'degraded')
  self.assertIn('sensor.nocni_stinovy_plan',worker.snapshot()['failed_entities'])
  fail[0]=False
  while worker.tick():pass
  self.assertEqual(worker.snapshot()['status'],'ok')
 def test_submit_does_not_wait_for_inflight_HTTP(self):
  entered=threading.Event();release=threading.Event()
  def send(e,p):entered.set();release.wait(5)
  worker=publication.MonitorPublisher({'ha_base_url':'http://synthetic'},send=send).start()
  try:
   worker.submit(monitor());self.assertTrue(entered.wait(2));start=time.monotonic()
   for sec in range(20):worker.submit(monitor(sec))
   self.assertLess(time.monotonic()-start,1);self.assertLessEqual(worker.snapshot()['pending_entities'],12)
  finally:release.set();self.assertTrue(worker.close())
 def test_failure_replaces_pending_positive_monitors(self):
  worker=publication.MonitorPublisher({'ha_base_url':'http://synthetic'},send=lambda *a:None);worker.submit(monitor())
  failure=obs.failure_result(stamp(15),ValueError('synthetic'),stamp(10));worker.submit(failure,True)
  self.assertEqual(worker.pending['sensor.nocni_stinovy_baterie_vykon']['state'],'unknown')
  self.assertEqual(worker.pending['sensor.nocni_stinovy_plan']['attributes']['collection_health']['status'],'failed')
 def test_two_real_five_second_observations_continue_during_slow_HTTP(self):
  self.ready();folder=Path(self.tmp.name);(folder/'options.json').write_text('{}');origin=time.monotonic()
  class Clock:
   @staticmethod
   def now(tz):return datetime.fromisoformat(stamp(10+time.monotonic()-origin)).astimezone(tz)
  class Stop:
   loops=0
   def is_set(self):return self.loops>=2
   def wait(self,seconds):time.sleep(seconds);self.loops+=1
  class Collector:
   def priority_states(self):return data(Clock.now(None).isoformat())
  class Opener:
   calls=0
   def open(self,request,timeout):
    self.calls+=1
    if not request.full_url.startswith('http://supervisor/core/api/states/sensor.nocni_stinov'):raise AssertionError('Non-monitoring endpoint')
    time.sleep(1)
    class Response:
     status=200
     def __enter__(self):return self
     def __exit__(self,*a):pass
    return Response()
  opener=Opener();maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
  def planned(store,states,at,finish_closed=False):return {**monitor(),'at':at}
  with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs,'datetime',Clock),patch.object(obs,'ReadOnlyHA',return_value=Collector()),patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',Stop()),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',side_effect=planned),patch.object(publication,'read_token',return_value='synthetic'),patch.object(publication.urllib.request,'build_opener',return_value=opener),contextlib.redirect_stdout(io.StringIO()):
   obs.main()
  events=[unpack(p)for p, in self.store.db.execute('SELECT payload FROM ram_control_events')]
  run=unpack(self.store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0])
  self.assertFalse(any(e['kind']=='sampling_gap'for e in events));self.assertGreater(run['target_ac_w'],0);self.assertGreater(opener.calls,0)
  self.assertFalse(json.loads((folder/'priority-live.json').read_text())['fast_loop']['monitoring_http_in_control_thread'])
 def recorder(self,delay):
  class Recorder:
   now=datetime.fromisoformat(stamp(10));published=[]
   def publish(self,a):self.published.append((self.now,copy.deepcopy(a)))
   def history(self,begin,end):
    lo=datetime.fromisoformat(begin);hi=datetime.fromisoformat(end)
    self.last_range=(lo,hi)
    return [[{'attributes':a,'last_updated':at.isoformat()}for at,a in self.published if lo<=at<=hi and (self.now-at).total_seconds()>=delay]]
  return Recorder()
 def test_delayed_recorder_acknowledges_committed_original_and_restart(self):
  v=self.ready();t.enqueue(self.store,v);client=self.recorder(30);worker=t.Publisher(self.path,client)
  for sec in range(10,80):
   if sec==25:worker=t.Publisher(self.path,client)
   client.now=datetime.fromisoformat(stamp(sec));worker.tick(client.now)
  status=t.status(self.store);self.assertEqual(status['recorded_seq'],status['queued_seq']);self.assertEqual(status['pending_chunks'],0)
 def test_receipt_scan_reaches_retry_after_missing_old_recording(self):
  t.enqueue(self.store,self.ready());client=self.recorder(30);worker=t.Publisher(self.path,client)
  worker.tick(client.now);client.published.clear()
  for sec in range(610,680):
   client.now=datetime.fromisoformat(stamp(sec));worker.tick(client.now)
  status=t.status(self.store);self.assertEqual(status['recorded_seq'],status['queued_seq'])
 def test_transport_clock_rollback_retries_and_searches_valid_range(self):
  t.enqueue(self.store,self.ready());client=self.recorder(0);worker=t.Publisher(self.path,client)
  client.now=datetime.fromisoformat(stamp(86410));worker.tick(client.now)
  for sec in (10,11,12):
   client.now=datetime.fromisoformat(stamp(sec));worker.tick(client.now)
   if hasattr(client,'last_range'):self.assertLess(client.last_range[0],client.last_range[1])
  status=t.status(self.store);self.assertEqual(status['recorded_seq'],status['queued_seq'])
 def test_calendar_rollback_revokes_power_without_second_owner(self):
  self.step(86400);v=self.step(86405);energy=v['session']['shadow_model']['battery_kwh_ac']
  for sec in (0,5):v=self.step(sec)
  rows=[unpack(p)for p, in self.store.db.execute('SELECT payload FROM ram_control_sessions')]
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['target_ac_w'],0);self.assertEqual(rows[0]['status'],'waiting_clock_recovery')
  self.assertEqual(rows[0]['shadow_model']['battery_kwh_ac'],energy)
  self.assertEqual(self.step(86410)['session']['target_ac_w'],0);self.assertGreater(self.step(86415)['session']['target_ac_w'],0)
 def test_same_day_rollback_does_not_double_integrate_and_requires_two_frames(self):
  self.ready();v=self.step(10);energy=v['session']['shadow_model']['battery_kwh_ac']
  self.assertEqual(self.step(8)['session']['target_ac_w'],0)
  self.step(9);self.assertEqual(self.step(10)['session']['shadow_model']['battery_kwh_ac'],energy)
  self.assertEqual(self.step(11)['session']['target_ac_w'],0);self.assertGreater(self.step(16)['session']['target_ac_w'],0)
