"""Night audit regressions through production paths; no live HA or actuator."""
import base64,copy,json,queue,random,sqlite3,tempfile,threading,time,unittest,zlib
from pathlib import Path
from unittest.mock import patch,MagicMock
from energy import isolated_control as iso,night,priority,journal_transport as transport,publish_status
from energy.store import Store,unpack
from test_control_isolation_0620 import Clock,Stop,Client,Evidence,Monitor
from test_control_journal import patch_value
from test_ram_control import data,result,stamp
from test_recovery_0622 import wait_for

def startup(rows,loads=(1000.,0.,0.)):
 mapping={**night.IDS,**priority.EXTRA};patch_value(rows,mapping['ev_w'],sum(loads))
 for i,(base,load)in enumerate(zip([400.,800.,200.],loads),1):
  for key,value in [(f'ev_l{i}_w',load),(f'grid_l{i}_w',-base-load),(f'grid_l{i}_a',(base+load)/230),
                    (f'inverter_l{i}_w',0),(f'grid_voltage_l{i}_v',230)]:patch_value(rows,mapping[key],value)
 return rows

def drive_startup(choice='ev',loads=(1000.,0.,0.)):
 clock=Clock();client=Client(clock);read=client.priority_states;evidence=Evidence();monitor=Monitor()
 def states():
  rows=startup(read(),loads if clock.sec==10 else(0.,0.,0.))
  patch_value(rows,priority.HELPER,'Elektromobil'if choice=='ev'else'Baterie SolaX')
  # A feasible measured startup also fits when battery demand has priority.
  if choice=='battery':patch_value(rows,night.IDS['battery_limit_a'],3)
  return rows
 client.priority_states=states
 iso.run_loop(client,evidence,monitor,Stop(clock,30),clock.now,lambda:clock.sec)
 return evidence,monitor

def noisy_result():
 _,monitor=drive_startup();value=copy.deepcopy(monitor.results[-1])
 value['soc_optimizer']={'status':'synthetic','uncompressible':base64.b64encode(random.Random(623).randbytes(32000)).decode()}
 return value

class StartupTests(unittest.TestCase):
 def test_feasible_one_and_three_phase_startup_reaches_sqlite_outbox_and_monitors_without_stop(self):
  for choice in ('ev','battery'):
   for loads in ((1000.,0.,0.),(500.,600.,700.)):
    with self.subTest(choice=choice,loads=loads),tempfile.TemporaryDirectory()as folder:
     evidence,monitor=drive_startup(choice,loads)
     self.assertTrue(all(v['collection_health']['status']!='failed'for v in monitor.results))
     v=monitor.results[2];sample=v['control_journal']['recent_samples'][0]
     self.assertEqual(sample['input_errors'],[]);self.assertGreater(sample['ram_target_ac_w'],0)
     self.assertEqual(v['selected']['ev_ac_w'],sum(loads));self.assertEqual(v['selected']['ev_reallocated_w'],0)
     self.assertTrue(all(r['planned_model_a']<=25+1e-7 for r in v['selected']['phase']))
     store=Store(Path(folder)/'e.sqlite')
     try:
      for seq,(rows,states,value,generation)in enumerate(evidence.rows,1):
       iso.persist_batch(store,{'runtime':'startup','seq':seq,'at':value['at'],'rows':rows,'loss':{},'states':states,'result':value})
       transport.enqueue(store,value['control_journal'])
      events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
      self.assertFalse([e for e in events if e['kind']=='would_stop_charge'])
      self.assertTrue(all(e['device_actions']==0 for e in events))
      self.assertGreater(store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
      self.assertEqual(store.db.execute('SELECT count(*)FROM control_analytics_pending').fetchone()[0],len(evidence.rows))
      self.assertTrue(publish_status.prepare_priority(v))
     finally:store.close()
 def test_real_curtailment_below_minimum_still_blocks_unimplemented_ev_control(self):
  from test_instant_fill import SESSION
  mem=iso.MemoryControl();analysis={'session':{**SESSION,'day':stamp(0)[:10]},'at':stamp(0)}
  try:
   for sec in (0,5,10):
    rows=startup(data(stamp(sec)),(1000.,0.,0.));patch_value(rows,priority.HELPER,'Baterie SolaX')
    patch_value(rows,night.IDS['battery_limit_a'],60)
    current,journal=mem.step(rows,analysis,stamp(sec))
   self.assertEqual(current['selected']['ev_ac_w'],0)
   self.assertEqual(journal['session']['target_ac_w'],0)
   self.assertIn('requires_ev_control_not_implemented',journal['recent_samples'][0]['input_errors'])
  finally:mem.close()

class MonitorOverflowTests(unittest.TestCase):
 def test_overflow_preserves_full_payload_and_other_entities_publish_within_budget(self):
  from energy.monitor_overflow import OverflowArchive
  from energy.priority_publication import MonitorPublisher
  from energy.monitor_payload import encoded
  value=noisy_result();sent=[]
  with tempfile.TemporaryDirectory()as folder:
   archive=OverflowArchive({'monitor_evidence_dir':folder})
   publisher=MonitorPublisher({},send=lambda e,p:sent.append((e,p)),overflow=archive.capture)
   publisher.submit(value)
   while publisher.tick():pass
   self.assertEqual(len(sent),12)
   self.assertTrue(all(len(encoded(p['attributes']))<=14000 for e,p in sent))
   e,p=next((e,p)for e,p in sent if e.endswith('soc_optimalizace'))
   self.assertEqual(p['state'],'payload_overflow');receipt=p['attributes']['overflow_evidence']
   self.assertTrue(receipt['retained']);self.assertEqual(receipt['entity_id'],e)
   original=json.loads(zlib.decompress((Path(folder)/receipt['archive_key']).read_bytes()))
   self.assertEqual(original['uncompressible'],value['soc_optimizer']['uncompressible'])
   self.assertEqual(archive.health()['status'],'degraded')
   self.assertEqual(publisher.snapshot()['completed_attempts'],12)
 def test_archive_failure_is_truthful_and_does_not_block_unaffected_monitors(self):
  from energy.monitor_overflow import OverflowArchive
  from energy.priority_publication import MonitorPublisher
  with tempfile.TemporaryDirectory()as folder:
   archive=OverflowArchive({'monitor_evidence_dir':folder});archive.limit=1;sent=[]
   p=MonitorPublisher({},send=lambda *a:sent.append(a),overflow=archive.capture);p.submit(noisy_result())
   while p.tick():pass
   receipt=archive.last;self.assertFalse(receipt['retained']);self.assertIn('BUDGET',receipt['archive_message'])
   self.assertEqual(len(sent),12);self.assertFalse(list(Path(folder).glob('*.zlib')))
 def test_worker_heartbeat_preserves_overflow_health_then_recovers_on_valid_preparation(self):
  from energy.priority_publication import MonitorPublisher
  inbox=queue.Queue();output=queue.Queue(2);stop=threading.Event();sent=[]
  with tempfile.TemporaryDirectory()as folder,patch.object(iso.os,'nice'),patch.object(MonitorPublisher,'publish',lambda s,e,p:sent.append((e,p))):
   t=threading.Thread(target=iso.monitor_worker,args=({'monitor_evidence_dir':folder},inbox,output,stop),daemon=True);t.start()
   try:
    inbox.put(noisy_result());wait_for(self,lambda:len(sent)>=12,3);time.sleep(.6)
    h=iso.drain(output,{});self.assertEqual(h['status'],'degraded');self.assertTrue(h['last_overflow']['retained'])
    _,monitor=drive_startup();inbox.put(monitor.results[-1]);wait_for(self,lambda:len(sent)>=24,3);time.sleep(.3)
    h=iso.drain(output,{});self.assertEqual(h['status'],'ok');self.assertEqual(h['overflow_count'],1)
   finally:stop.set();t.join(3)

class AnalyticsTests(unittest.TestCase):
 def seed(self,path):
  evidence,monitor=drive_startup();store=Store(path)
  for seq,(rows,states,value,generation)in enumerate(evidence.rows,1):
   iso.persist_batch(store,{'runtime':'analytics','seq':seq,'at':value['at'],'rows':rows,'loss':{},'states':states,'result':value})
  store.close();return evidence
 def test_local_writer_timeout_retries_fifo_after_restart_without_losing_samples(self):
  from energy.ancillary_analytics import Analytics
  from energy.sqlite_writes import WriterTimeout,gate_for
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';evidence=self.seed(path);seen=[];maintenance=MagicMock()
   analytics=Analytics(path,maintenance,work=lambda store,item:seen.append(item['at'])or {'at':item['at']})
   entered=threading.Event();release=threading.Event();gate=gate_for(path)
   def locked():
    gate.acquire(False,1);entered.set();release.wait(3);gate.release()
   thread=threading.Thread(target=locked);thread.start();self.assertTrue(entered.wait(1))
   try:
    self.assertFalse(analytics.tick());h=analytics.snapshot()['health']
    self.assertEqual(h['status'],'retrying');self.assertEqual(h['last_failure']['error_code'],'WriterTimeout')
    self.assertEqual(h['last_failure']['storage_error']['source'],'local_writer')
   finally:release.set();thread.join(2)
   # A new worker instance discovers the durable queue without an in-memory retry.
   recovered=Analytics(path,maintenance,work=lambda store,item:seen.append(item['at'])or {'at':item['at']})
   while recovered.tick():pass
   self.assertEqual(seen,[x[2]['at']for x in evidence.rows]);self.assertEqual(recovered.snapshot()['health']['pending_items'],0)
   maintenance.submit.assert_called_once()
 def test_partial_analytic_commit_replay_does_not_double_count_energy(self):
  from energy.ancillary_analytics import Analytics
  from energy.sqlite_writes import WriterTimeout
  from energy.soc_runtime import schema
  from energy.store import pack
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';evidence=self.seed(path);store=Store(path);schema(store.db)
   model={'discharge_curve':[[0,0],[50,5],[100,10]],'dc_cycle_efficiency':.9,'grid_efficiency':.9,'source_hash':'synthetic'}
   with store.db:store.db.execute('insert into soc_model_versions values(?,?,?)',('m','2026-01-14T20:00:00+00:00',pack({'at':'2026-01-14T20:00:00+00:00','battery_model':model})))
   reference=sqlite3.connect(Path(folder)/'reference.sqlite');store.db.backup(reference);reference.close()
   store.close();maintenance=MagicMock();maintenance.snapshot.return_value={};a=Analytics(path,maintenance)
   from energy import priority_audit
   with patch.object(priority_audit,'command_summary',side_effect=WriterTimeout('synthetic after analytic commit')):
    self.assertFalse(a.tick())
   while a.tick():pass
   store=Store(path)
   try:
    run=unpack(store.db.execute('SELECT payload FROM priority_runs').fetchone()[0])
    reference_analytics=Analytics(Path(folder)/'reference.sqlite',maintenance)
    while reference_analytics.tick():pass
    reference_store=Store(Path(folder)/'reference.sqlite')
    try:reference_run=unpack(reference_store.db.execute('SELECT payload FROM priority_runs').fetchone()[0])
    finally:reference_store.close()
    self.assertEqual(run['models'],reference_run['models'])
    self.assertEqual(run['observed_ev_kwh_ac'],reference_run['observed_ev_kwh_ac'])
    self.assertEqual(run['sample_count'],len(evidence.rows))
    self.assertEqual(store.db.execute('SELECT count(*)FROM night_samples').fetchone()[0],len(evidence.rows))
    self.assertEqual(store.db.execute('SELECT count(*)FROM priority_samples').fetchone()[0],len(evidence.rows))
    self.assertEqual(a.snapshot()['health']['last_failure']['error_code'],'WriterTimeout')
   finally:store.close()
 def test_sqlite_busy_is_retryable_but_disk_io_is_not_mislabeled(self):
  from energy.ancillary_analytics import retryable,Analytics
  for code,expected in [(sqlite3.SQLITE_BUSY,True),(sqlite3.SQLITE_LOCKED,True),(sqlite3.SQLITE_IOERR,False)]:
   error=sqlite3.OperationalError('synthetic');error.sqlite_errorcode=code
   self.assertEqual(retryable(error),expected)
   with tempfile.TemporaryDirectory()as folder:
    path=Path(folder)/'e.sqlite';self.seed(path);a=Analytics(path,MagicMock(),work=MagicMock(side_effect=error))
    self.assertFalse(a.tick());h=a.snapshot()['health'];self.assertEqual(h['last_failure']['storage_error']['sqlite_errorcode'],code)
    self.assertEqual(h['status'],'retrying'if expected else'degraded')
 def test_blocked_analytics_does_not_delay_durable_batch_ack(self):
  from energy.ancillary_analytics import Analytics
  release=threading.Event();entered=threading.Event();inbox=queue.Queue();output=queue.Queue(20);bootstrap=queue.Queue();stop=threading.Event()
  def blocked(self,store,item):entered.set();release.wait(4);return {'at':item['at']}
  maintenance=MagicMock();maintenance.snapshot.return_value={};publisher=MagicMock();publisher.start.return_value=publisher
  with tempfile.TemporaryDirectory()as folder,patch.object(Analytics,'compute',blocked),patch('energy.priority_maintenance.Maintenance',return_value=maintenance),patch('energy.journal_transport.Publisher',return_value=publisher),patch('energy.priority_observer.backup'),patch.object(iso.os,'nice'):
   path=Path(folder)/'evidence.sqlite';t=threading.Thread(target=iso.evidence_worker,args=(path,{},inbox,output,bootstrap,stop),daemon=True);t.start()
   try:
    bootstrap.get(timeout=2);evidence,_=drive_startup()
    for seq,(rows,states,value,generation)in enumerate(evidence.rows[:3],1):
     inbox.put({'runtime':'blocked','seq':seq,'at':value['at'],'rows':rows,'loss':{},'states':states,'result':value})
    self.assertTrue(entered.wait(2));last={};end=time.monotonic()+2
    while last.get('ack',0)<3 and time.monotonic()<end:last=output.get(timeout=2)
    self.assertEqual(last['ack'],3);self.assertFalse(release.is_set());self.assertEqual(last['storage_health']['status'],'ok')
   finally:release.set();stop.set();t.join(4)

class SupervisionTests(unittest.TestCase):
 def test_rolling_budget_recovers_without_erasing_cumulative_history(self):
  from energy.process_supervision import WorkerGuard
  owner=MagicMock();owner.worker_problem.return_value='synthetic stuck';now=[0.]
  guard=WorkerGuard(owner,clock=lambda:now[0])
  for _ in range(5):guard.tick()
  self.assertEqual(owner.restart_worker.call_count,3);self.assertTrue(guard.exhausted)
  now[0]=299.;guard.tick();self.assertEqual(guard.restarts,3)
  now[0]=300.;guard.tick();self.assertEqual(guard.restarts,4);self.assertFalse(guard.exhausted)
  self.assertEqual(guard.snapshot()['attempts_in_window'],1)
  owner.worker_problem.return_value=None;guard.tick();self.assertEqual(guard.restarts,4)
 def test_responsive_http_outage_does_not_restart_worker_but_frozen_publication_does(self):
  bridge=iso.MonitorBridge({});output=queue.Queue();bridge.stopping=False;now=time.monotonic()
  t=threading.Thread(target=bridge.read_responses,args=(output,bridge.epoch),daemon=True);t.start()
  try:
   bridge.last_progress=now-100
   for n in range(1,8):
    output.put({'status':'degraded','error_code':'TimeoutError','pending_entities':12,'published_packets':0,'completed_attempts':n})
    wait_for(self,lambda:bridge.attempts==n,1)
    self.assertIsNone(bridge.worker_problem(time.monotonic(),30))
   self.assertEqual(bridge.guard.restarts,0)
   bridge.last_progress=time.monotonic()-31;bridge.last_reply=time.monotonic()
   self.assertEqual(bridge.worker_problem(time.monotonic(),30),'MONITOR_PUBLICATION_STALLED')
  finally:
   bridge.stopping=True;t.join(1)
   for q in (bridge.inbox,bridge.output):q.close()
 def test_retired_reader_resources_are_capped_across_rolling_windows(self):
  from energy.process_supervision import reader_budget
  bridge=iso.MonitorBridge({})
  try:
   reader=MagicMock();reader.is_alive.return_value=True;bridge.retired_readers=[reader]*3
   with patch('energy.process_supervision.retire')as retire:
    with self.assertRaisesRegex(RuntimeError,'RETIRED_READER_LIMIT'):bridge.restart_worker()
    retire.assert_not_called()
   reader.is_alive.return_value=False;reader_budget(bridge);self.assertEqual(bridge.retired_readers,[])
   feeder=MagicMock();feeder.is_alive.return_value=True;bridge.retired_feeders=[feeder]*3
   with self.assertRaisesRegex(RuntimeError,'RETIRED_FEEDER_LIMIT'):bridge.restart_worker()
  finally:
   for q in (bridge.inbox,bridge.output):q.close()

if __name__=='__main__':unittest.main()
