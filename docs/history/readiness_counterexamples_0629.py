"""Readiness audit counterexamples, not fixes or physical hardware tests.

Passing counterexample tests confirm the documented current limitation. Convert
these assertions into acceptance tests when the corresponding mechanism changes.
All HA calls are replaced with synthetic clients; no live credentials or writes.
"""
import copy,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from energy import isolated_control as iso,priority_observer as observer,ram_control
from energy.collector import ReadOnlyHA
from energy.priority_collection import SnapshotCollector
from energy.priority_publication import MonitorPublisher
from energy.publish_status import prepare_priority
from test_control_isolation_0620 import Clock,Stop,Client,Evidence,Monitor
from test_ram_control import data,result,stamp
from test_control_journal import patch_value

class ReadinessAuditTests(unittest.TestCase):
 def drive(self,fault=False):
  clock=Clock();client=Client(clock);read=client.priority_states;evidence=Evidence();monitor=Monitor()
  def frames():
   rows=read()
   if fault and clock.sec>=15:patch_value(rows,ram_control.RUN_MODE,'Off-Grid')
   return rows
  client.priority_states=frames
  iso.run_loop(client,evidence,monitor,Stop(clock,25),clock.now,lambda:clock.sec)
  return evidence,monitor
 def test_live_option_is_rejected_before_any_bridge_or_actuator_starts(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);options=root/'options.json';options.write_text(json.dumps({'mode':'live'}));real=Path
   def paths(value):return options if str(value)=='/data/options.json'else real(value)
   with patch.object(observer,'DATA',root/'evidence'),patch.object(observer,'Path',side_effect=paths),patch.object(observer.os,'umask'),patch('energy.native_backup.restore',return_value={'status':'no_snapshot'}),patch.object(iso,'EvidenceBridge')as bridge:
    with self.assertRaisesRegex(ValueError,'Only observe_only'):observer.main()
    bridge.assert_not_called()
 def test_fresh_synthetic_reports_never_claim_physical_readiness(self):
  e,m=self.drive();run=m.results[-1]['control_journal']['session'];self.assertGreater(run['target_ac_w'],0)
  self.assertFalse(run['live_ready']);self.assertIsNone(run['last_intent']['wire_command'])
  caps=ram_control.capabilities(data(stamp(20)));self.assertFalse(caps['timeout_verified']);self.assertFalse(caps['wire_mapping_verified']);self.assertFalse(caps['physical_control_ready'])
 def test_counterexample_candidate_power_monitor_can_be_positive_when_control_is_blocked(self):
  e,m=self.drive(fault=True);v=m.results[-1];run=v['control_journal']['session']
  self.assertEqual(run['target_ac_w'],0);self.assertGreater(v['selected']['battery_ac_w'],0)
  packet=next(p for eid,p in prepare_priority(v)if eid=='sensor.nocni_stinovy_baterie_vykon')
  self.assertGreater(float(packet['state']),0);self.assertNotIn('expires_at',packet['attributes'])
  self.assertTrue(v['control_journal']['recent_samples'][0]['input_errors'])
 def test_counterexample_failed_monitor_http_leaves_old_nonzero_state_in_ha(self):
  e,m=self.drive();ha={};fail=[False]
  def send(eid,payload):
   if fail[0]:raise TimeoutError('synthetic monitoring outage')
   ha[eid]=copy.deepcopy(payload)
  p=MonitorPublisher({},send=send);p.submit(m.results[-1])
  while p.tick():pass
  old=ha['sensor.nocni_stinovy_baterie_vykon'];self.assertGreater(float(old['state']),0)
  fail[0]=True;failed=observer.failure_result(stamp(30),TimeoutError('synthetic input outage'),stamp(20));p.submit(failed,failure=True)
  self.assertFalse(p.tick());self.assertEqual(p.snapshot()['status'],'degraded')
  self.assertEqual(ha['sensor.nocni_stinovy_baterie_vykon'],old)
 def test_counterexample_complex_context_refresh_can_expire_fast_cache_and_reach_production_failure_path(self):
  client=ReadOnlyHA('http://synthetic.invalid');entered=threading.Event();release=threading.Event()
  client._priority_context=[];client._priority_context_at=time.monotonic()-61
  def get(path):entered.set();release.wait(15);return[]
  client.get=MagicMock(side_effect=get);client._query=MagicMock(return_value='[]')
  collector=SnapshotCollector(client,period=.1,max_age=7.5)
  collector.states=data(stamp(20));collector.received=time.monotonic()
  collector.start()
  try:
   self.assertTrue(entered.wait(1));self.assertTrue(collector.priority_states())
   time.sleep(7.6)
   with self.assertRaisesRegex(RuntimeError,'COLLECTION_SNAPSHOT_EXPIRED'):collector.priority_states()
   client._query.assert_not_called()
   clock=Clock();clock.sec=20;e=Evidence();m=Monitor()
   iso.run_loop(collector,e,m,Stop(clock,25),clock.now,lambda:clock.sec)
   self.assertEqual(m.results[-1]['collection_health']['status'],'failed')
   health=m.results[-1]['collection_health'];self.assertEqual(health['error_code'],'RuntimeError')
   self.assertTrue(any(x['file']=='priority_collection.py'and x['function']=='priority_states'for x in health['error_location']))
  finally:release.set();collector.close()
 def test_counterexample_dead_collector_thread_has_no_automatic_restart_or_explicit_thread_health(self):
  client=MagicMock();client.priority_states.side_effect=SystemExit('synthetic collector death')
  c=SnapshotCollector(client,period=.1);c.start();c.thread.join(1)
  try:
   self.assertFalse(c.thread.is_alive());self.assertIsNone(c.snapshot()['error_code'])
   with self.assertRaisesRegex(RuntimeError,'COLLECTION_SNAPSHOT_EXPIRED'):c.priority_states()
   self.assertFalse(c.thread.is_alive());self.assertNotIn('thread_alive',c.snapshot())
  finally:c.close()

 def test_counterexample_failure_result_discards_distinct_semantic_runtime_reasons(self):
  a=observer.failure_result(stamp(20),RuntimeError('COLLECTION_SNAPSHOT_EXPIRED'),stamp(15))
  b=observer.failure_result(stamp(20),RuntimeError('COLLECTION_WORKER_FAILED:TimeoutError'),stamp(15))
  self.assertEqual(a['collection_health'],b['collection_health'])
  self.assertNotIn('COLLECTION_SNAPSHOT_EXPIRED',json.dumps(a))
 def test_counterexample_reused_batch_key_does_not_validate_conflicting_immutable_content(self):
  from energy.store import Store,pack
  e,m=self.drive();rows,states,value,generation=e.rows[0]
  with tempfile.TemporaryDirectory()as folder:
   s=Store(Path(folder)/'e.sqlite')
   try:
    batch={'runtime':'synthetic-collision','seq':1,'at':value['at'],'rows':rows,'loss':{}}
    iso.persist_batch(s,batch);changed=copy.deepcopy(batch);row=list(changed['rows']['ram_control_samples'][0]);old=row[-1];row[-1]=pack({'deliberately_conflicting':True});changed['rows']['ram_control_samples'][0]=tuple(row)
    iso.persist_batch(s,changed)
    self.assertEqual(s.db.execute('SELECT payload FROM ram_control_samples WHERE at=?',(row[0],)).fetchone()[0],old)
    self.assertEqual(s.db.execute('SELECT count(*)FROM control_evidence_batches').fetchone()[0],1)
   finally:s.close()
 def test_counterexample_same_time_conflicting_soc_decision_returns_hash_not_stored_and_does_not_revoke(self):
  from energy.store import Store
  from energy import soc_runtime
  with tempfile.TemporaryDirectory()as folder:
   s=Store(Path(folder)/'e.sqlite')
   try:
    soc_runtime.schema(s.db);old=soc_runtime.record_decision(s,{'issued_at':stamp(0),'day':stamp(0)[:10],'status':'conditional_shadow_plan','horizon_complete':True,'target_soc_pct':60})
    newer=soc_runtime.record_decision(s,{'issued_at':stamp(0),'day':stamp(0)[:10],'status':'calculation_unavailable','target_soc_pct':None})
    self.assertNotEqual(old['decision_hash'],newer['decision_hash'])
    stored=s.db.execute('SELECT hash FROM soc_decisions WHERE at=?',(stamp(0),)).fetchone()[0]
    self.assertEqual(stored,old['decision_hash']);self.assertNotEqual(stored,newer['decision_hash'])
    self.assertEqual(soc_runtime.session_plan(s,stamp(0)[:10],stamp(5))['decision_hash'],old['decision_hash'])
   finally:s.close()
 def test_counterexample_responsive_evidence_heartbeat_without_ack_progress_does_not_trigger_recovery(self):
  from datetime import datetime,timedelta,timezone
  b=iso.EvidenceBridge('/synthetic-unused',{})
  try:
   b.worker_ready=True;b.worker_started_at=time.monotonic()-200;b.seq=1
   b.inflight={1:(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()}
   b.process=MagicMock();b.process.pid=123;b.process.is_alive.return_value=True
   b.last={'ack':0,'storage_health':{'status':'degraded','error_code':'WriterTimeout'}}
   with patch.object(b,'restart_worker')as restart:
    for _ in range(3):
     b.last_reply=time.monotonic();b.guard.tick()
    restart.assert_not_called()
   self.assertEqual(b.guard.restarts,0);self.assertEqual(b.snapshot()['pending_or_lost_batches'],1)
   self.assertEqual(b.snapshot()['status'],'degraded');self.assertIsNone(b.guard.problem)
  finally:
   for q in (b.inbox,b.output,b.bootstrap):q.cancel_join_thread();q.close()

 def test_counterexample_real_evidence_retry_heartbeat_can_continue_without_commit_progress(self):
  import queue
  from energy.store import Store
  from energy.sqlite_writes import gate_for
  from datetime import datetime,timedelta,timezone
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'evidence.sqlite';store=Store(path)
   iso.persist_batch(store,{'runtime':'bootstrap','seq':0,'at':stamp(0),'rows':{},'loss':{}});store.close()
   inbox=queue.Queue();output=queue.Queue();bootstrap=queue.Queue();stop=threading.Event()
   maintenance=MagicMock();maintenance.snapshot.return_value={};publisher=MagicMock();publisher.start.return_value=publisher
   analytics=MagicMock();analytics.start.return_value=analytics;analytics.snapshot.return_value={'analysis':{},'health':{'status':'ok','pending_items':0}}
   with patch.object(iso.os,'nice'),patch('energy.priority_maintenance.Maintenance',return_value=maintenance),patch('energy.journal_transport.Publisher',return_value=publisher),patch('energy.ancillary_analytics.Analytics',return_value=analytics),patch('energy.priority_observer.backup'):
    t=threading.Thread(target=iso.evidence_worker,args=(path,{},inbox,output,bootstrap,stop));t.start();bootstrap.get(timeout=2);gate=gate_for(path);gate.acquire(False,1)
    try:
     inbox.put({'runtime':'blocked','seq':1,'at':stamp(0),'rows':{},'loss':{},'result':{'control_journal':{}}})
     failures=[];deadline=time.monotonic()+5
     while len(failures)<3 and time.monotonic()<deadline:
      x=output.get(timeout=2)
      if x.get('storage_health',{}).get('error_code')=='WriterTimeout':failures.append(x)
     self.assertEqual(len(failures),3);self.assertTrue(all(x['ack']==0 for x in failures))
     b=iso.EvidenceBridge('/synthetic-unused',{})
     try:
      b.worker_ready=True;b.worker_started_at=time.monotonic()-200;b.seq=1;b.inflight={1:(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()};b.process=MagicMock();b.process.pid=123;b.process.is_alive.return_value=True
      with patch.object(b,'restart_worker')as restart:
       for x in failures:b.last=x;b.last_reply=time.monotonic();b.guard.tick()
       restart.assert_not_called()
      self.assertEqual(b.snapshot()['status'],'degraded');self.assertEqual(b.guard.restarts,0)
     finally:
      for q in (b.inbox,b.output,b.bootstrap):q.cancel_join_thread();q.close()
    finally:stop.set();gate.release();t.join(4)
    self.assertFalse(t.is_alive())

 def test_counterexample_unknown_sunrise_is_forwarded_as_nondate_planner_metadata(self):
  from energy import soc_runtime
  from test_night import state
  rows=data(stamp(20));rows.append(state(soc_runtime.IDS['sunrise'],'unknown',stamp(20)))
  snapshot=soc_runtime.inputs(rows,stamp(20),{}, {},[],False)
  self.assertEqual(snapshot['sunrise'],'unknown')
