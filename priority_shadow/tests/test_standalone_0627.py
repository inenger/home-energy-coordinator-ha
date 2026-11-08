"""Standalone handover, WAL lifecycle and monitoring cadence; synthetic only."""
import copy,gzip,json,tempfile,threading,time,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from energy.store import Store,pack
from energy.core import digest
from energy import standalone_context as ctx,soc_runtime as soc
from energy.soc_history import fit_ev,atomic_gzip
from energy.sqlite_writes import gate_for,WriterTimeout
from energy.sqlite_checkpoint import Checkpointer
from energy.priority_publication import MonitorPublisher
from test_soc_fixes_062 import ev_rows
from test_soc_fixes import MODEL
from test_deep_fixes_0613 import monitor
from energy.monitor_payload import unpacked

class StandaloneTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'evidence.sqlite';self.s=Store(self.path);soc.schema(self.s.db);__import__("energy.priority",fromlist=["schema"]).schema(self.s.db)
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def bundle(self,rows=None):
  rows=ev_rows()if rows is None else rows
  entity='weather_forecast:weather.synthetic:hourly';payload={'forecast_type':'hourly','entity_id':'weather.synthetic','units':{'temperature_unit':'°C'},'forecast':[]};v={'entity':entity,'available_at':rows[0]['at'],'payload':payload,'hash':digest({'entity':entity,'payload':payload})}
  data={'source':'synthetic-original-archive','source_captured_at':rows[-1]['at'],'ev_rows':rows,'weather_versions':[v]};b={'schema':ctx.SCHEMA,'data':data,'sha256':digest(data)};p=self.root/'context.json.gz'
  with gzip.open(p,'wt')as f:json.dump(b,f)
  return p,b
 def test_import_restart_idempotency_weather_availability_and_exact_calibration(self):
  p,b=self.bundle();receipt=ctx.import_context(self.s,p);self.assertEqual(receipt['ev_rows'],len(ev_rows()));now=datetime.fromisoformat(ev_rows()[-1]['at'])+timedelta(minutes=1)
  before=fit_ev(ev_rows());self.assertEqual(fit_ev(ctx.ev_rows(self.s,now)),before)
  self.s.close();self.s=Store(self.path);self.assertEqual(ctx.import_context(self.s,p),receipt)
  self.assertEqual(self.s.db.execute('select count(*)from versions').fetchone()[0],1)
  self.assertEqual(soc.calibration_weather(self.s,now)[0]['available_at'],b['data']['weather_versions'][0]['available_at'])
 def test_corrupt_bundle_rejected_before_any_rows(self):
  p,b=self.bundle();b['data']['ev_rows'][0]['soc']=99
  with gzip.open(p,'wt')as f:json.dump(b,f)
  with self.assertRaisesRegex(ValueError,'IMPORT_HASH'):ctx.import_context(self.s,p)
  self.assertEqual(self.s.db.execute('select count(*)from standalone_ev_history').fetchone()[0],0)
 def test_conflict_never_rewrites_existing_history(self):
  p,b=self.bundle();ctx.import_context(self.s,p);b['data']['ev_rows'][0]['soc']=99;b['sha256']=digest(b['data'])
  with gzip.open(p,'wt')as f:json.dump(b,f)
  with self.assertRaisesRegex(ValueError,'EV_CONFLICT'):ctx.import_context(self.s,p)
  self.assertEqual(self.s.db.execute('select soc from standalone_ev_history order by at limit 1').fetchone()[0],20)
 def test_own_new_rows_continue_after_import_and_future_rows_excluded(self):
  p,b=self.bundle();ctx.import_context(self.s,p);last=datetime.fromisoformat(ev_rows()[-1]['at']);at=(last+timedelta(minutes=1)).isoformat();future=(last+timedelta(days=1)).isoformat()
  for t in [at,future]:
   with self.s.db:self.s.db.execute('insert into soc_observations values(?,?,?)',(t,t[:10],pack({'at':t,'ev_w':0,'ev_counter':408,'ev_soc':30})))
  rows=ctx.ev_rows(self.s,last+timedelta(minutes=2));self.assertEqual(rows[-1]['at'],at);self.assertNotIn(future,[r['at']for r in rows])
 def test_handover_gap_does_not_invent_complete_session(self):
  rows=ev_rows(days=1,gap=True);p,b=self.bundle(rows);ctx.import_context(self.s,p);now=datetime.fromisoformat(rows[-1]['at'])+timedelta(minutes=1)
  self.assertEqual(fit_ev(ctx.ev_rows(self.s,now))['sessions'],[])
 def test_planner_refresh_and_decision_without_legacy_runtime_database(self):
  p,b=self.bundle();history=self.root/'history.gz';atomic_gzip(history,{'source':'synthetic','house_hours':[],'pv_pairs':[],'battery_model':{**MODEL,'fit_period':'synthetic'}})
  now=datetime.fromisoformat(ev_rows()[-1]['at'])+timedelta(minutes=1);at=now.isoformat();planner=soc.PlannerService()
  with patch.object(ctx,'BUNDLE',p),patch.object(soc,'HISTORY',history),patch.object(soc,'plan',return_value={'status':'no_comparable_feasible_plan','day':now.date().isoformat(),'issued_at':at,'target_soc_pct':None}):
   result=planner.observe(self.s,[],at)
  self.assertEqual(result['status'],'no_comparable_feasible_plan');self.assertEqual(planner.ev_model['ac_kwh_per_soc_pct'],.8)
  self.assertEqual(self.s.db.execute('select count(*)from soc_decisions').fetchone()[0],1)
 def test_wal_survives_short_connection_close_and_full_durability_kept(self):
  self.s.close();keeper=Checkpointer(self.path).start()
  try:
   for n in range(3):
    s=Store(self.path)
    self.assertEqual(s.db.execute('pragma synchronous').fetchone()[0],2);self.assertEqual(s.db.execute('pragma wal_autocheckpoint').fetchone()[0],0)
    with s.db:s.db.execute('insert into failures(at,code)values(?,?)',(str(n),'synthetic'))
    s.close();self.assertTrue(Path(str(self.path)+'-wal').exists())
   s=Store(self.path);self.assertEqual(s.db.execute('select count(*)from failures').fetchone()[0],3);s.close()
  finally:self.assertTrue(keeper.close());self.s=Store(self.path)
 def test_active_sql_phase_visible_to_waiting_writer(self):
  entered=threading.Event();release=threading.Event();errors=[]
  def work():
   try:
    s=Store(self.path);s.db.create_function('hold',0,lambda:(entered.set(),release.wait(3),1)[-1])
    with s.db:s.db.execute('SELECT hold()').fetchone()
    s.close()
   except Exception as e:errors.append(e)
  worker=threading.Thread(target=work,name='synthetic-owner');worker.start();self.assertTrue(entered.wait(1))
  try:
   s=Store(self.path,timeout=.02)
   with self.assertRaises(WriterTimeout)as failure:
    with s.db:pass
   diag=failure.exception.writer_diagnostic;self.assertEqual(diag['owner_thread'],'synthetic-owner');self.assertEqual(diag['operation'],'SELECT');s.close()
  finally:release.set();worker.join()
  self.assertFalse(errors)

class CadenceTests(unittest.TestCase):
 def drain(self,p):
  while p.tick():pass
 def test_large_latest_monitors_rate_limited_scalars_remain_fast_and_recovery_urgent(self):
  sent=[];p=MonitorPublisher({},send=lambda e,v:sent.append((e,v)))
  with patch('energy.priority_publication.time.monotonic',return_value=100):p.submit(monitor(0));self.drain(p)
  sent.clear()
  with patch('energy.priority_publication.time.monotonic',return_value=105):p.submit(monitor(5));self.drain(p)
  ids=[e for e,_ in sent];self.assertNotIn('sensor.nocni_stinovy_plan',ids);self.assertIn('sensor.nocni_stinovy_baterie_vykon',ids);self.assertIn('sensor.nocni_stinove_vstupy',ids)
  sent.clear();bad=monitor(10);bad['collection_health']={'status':'failed'}
  with patch('energy.priority_publication.time.monotonic',return_value=106):p.submit(bad,True);self.drain(p)
  self.assertIn('sensor.nocni_stinovy_plan',[e for e,_ in sent]);sent.clear()
  with patch('energy.priority_publication.time.monotonic',return_value=107):p.submit(monitor(15));self.drain(p)
  self.assertIn('sensor.nocni_stinovy_plan',[e for e,_ in sent])
 def test_pending_latest_snapshot_not_lost_and_heartbeat_keeps_real_timestamp(self):
  sent=[];p=MonitorPublisher({},send=lambda e,v:sent.append((e,v)))
  with patch('energy.priority_publication.time.monotonic',return_value=100):p.submit(monitor(0));p.submit(monitor(5));self.drain(p)
  self.assertTrue(all(unpacked(v['attributes'])['observed_at']==monitor(5)['at']for _,v in sent));sent.clear()
  with patch('energy.priority_publication.time.monotonic',return_value=161):p.submit(monitor(65));self.drain(p)
  self.assertEqual(len(sent),12)

class ReceiptScopeTests(unittest.TestCase):
 def test_large_recorder_comparison_outside_writer_then_durable_ack(self):
  from energy import ram_control as c,journal_transport as t
  from test_ram_control import data,result,stamp
  from energy.store import unpack
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'db';s=Store(path);c.observe(s,data(stamp(0)),result(stamp(0)));journal=c.observe(s,data(stamp(5)),result(stamp(5)));t.enqueue(s,journal)
   held=[];sent=[]
   class Attrs(dict):
    def __eq__(self,other):held.append(gate_for(path).owner is not None);return dict.__eq__(self,other)
   class Client:
    def publish(self,attrs):sent.append(copy.deepcopy(attrs))
    def history(self,begin,end):return [[{'attributes':Attrs(attrs),'last_updated':stamp(10)}for attrs in sent]]
   publisher=t.Publisher(path,Client());now=datetime.fromisoformat(stamp(10));publisher.tick(now);publisher.tick(now+timedelta(seconds=5))
   self.assertTrue(held);self.assertFalse(any(held));self.assertEqual(t.status(s)['pending_chunks'],0);s.close()

class StartupSupervisionTests(unittest.TestCase):
 def check_startup(self,bridge,prefix):
  from types import SimpleNamespace
  bridge.process=SimpleNamespace(pid=123,is_alive=lambda:True)
  bridge.worker_started_at=100.;bridge.worker_ready=False;bridge.last_reply=100.
  self.assertIsNone(bridge.worker_problem(105.,.1))
  self.assertEqual(bridge.worker_problem(131.,.1),prefix+'_PROCESS_STARTUP_TIMEOUT')
  bridge.worker_ready=True
  self.assertEqual(bridge.worker_problem(105.,.1),prefix+'_PROCESS_UNRESPONSIVE')
  bridge.worker_ready=False;bridge.process.is_alive=lambda:False
  self.assertEqual(bridge.worker_problem(100.1,.1),prefix+'_PROCESS_EXITED')
  for name in ['inbox','output','bootstrap']:
   q=getattr(bridge,name,None)
   if q is not None:q.cancel_join_thread();q.close()
 def test_monitor_startup_grace_does_not_mask_dead_or_stalled_ready_child(self):
  from energy.isolated_control import MonitorBridge
  self.check_startup(MonitorBridge({}),'MONITOR')
 def test_evidence_startup_grace_does_not_mask_dead_or_stalled_ready_child(self):
  from energy.isolated_control import EvidenceBridge
  self.check_startup(EvidenceBridge('/synthetic/not-opened.sqlite',{}),'EVIDENCE')
