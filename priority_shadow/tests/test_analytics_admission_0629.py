"""Production analytics/gate/SQLite regressions, synthetic evidence only."""
import sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from energy.ancillary_analytics import Analytics
from energy.sqlite_writes import gate_for,Gate,WriterCancelled
from energy.store import Store
import test_night_fixes_0623 as fixtures

class AdmissionTests(unittest.TestCase):
 def seed(self,path):return fixtures.AnalyticsTests().seed(path)
 def wait(self,predicate):
  end=time.monotonic()+3
  while not predicate()and time.monotonic()<end:time.sleep(.005)
  self.assertTrue(predicate())
 def test_long_local_writer_queues_once_without_retry_or_partial_replay(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';evidence=self.seed(path);seen=[];a=Analytics(path,MagicMock(),work=lambda s,i:seen.append(i['at'])or{});g=gate_for(path)
   g.acquire(False,1);t=threading.Thread(target=a.tick);t.start()
   try:
    self.wait(lambda:a.snapshot()['health']['status']=='waiting_writer')
    self.assertEqual(a.retries,0);self.assertEqual(seen,[])
    self.assertEqual(g.fast_waiters,0);self.assertEqual(len(g.waiters),1)
    time.sleep(.06);self.assertEqual(len(g.waiters),1)
   finally:g.release();t.join(2)
   self.assertFalse(t.is_alive());self.assertEqual(a.snapshot()['health']['status'],'ok')
   self.assertEqual(a.writer_waits,1);self.assertEqual(a.retries,0)
   while a.tick():pass
   self.assertEqual(seen,[x[2]['at']for x in evidence.rows]);self.assertEqual(a.snapshot()['health']['pending_items'],0)
 def test_shutdown_cancels_queued_ticket_and_next_instance_replays_original_fifo(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';evidence=self.seed(path);seen=[];a=Analytics(path,MagicMock(),work=lambda s,i:seen.append(i['at'])or{});g=gate_for(path)
   g.acquire(False,1);a.start()
   try:
    self.wait(lambda:len(g.waiters)==1);start=time.monotonic();self.assertTrue(a.close());self.assertLess(time.monotonic()-start,.3)
    self.assertEqual(len(g.waiters),0);self.assertEqual(a.retries,0);self.assertEqual(seen,[])
   finally:g.release();a.close()
   b=Analytics(path,MagicMock(),work=lambda s,i:seen.append(i['at'])or{})
   while b.tick():pass
   self.assertEqual(seen,[x[2]['at']for x in evidence.rows])
 def test_partial_committed_work_waits_without_restarting_job(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';self.seed(path);ready=threading.Event();held=threading.Event();release=threading.Event();calls=[]
   def holder():
    ready.wait(2);s=Store(path)
    try:
     with s.db:held.set();release.wait(3)
    finally:s.close()
   def work(s,item):
    calls.append(item['at'])
    with s.db:s.db.execute("INSERT OR IGNORE INTO objects VALUES('first','synthetic',x'00')")
    ready.set();self.assertTrue(held.wait(2))
    with s.db:s.db.execute("INSERT OR IGNORE INTO objects VALUES('second','synthetic',x'00')")
    return{}
   a=Analytics(path,MagicMock(),work=work);holder_thread=threading.Thread(target=holder);holder_thread.start();t=threading.Thread(target=a.tick);t.start()
   try:
    self.wait(lambda:a.snapshot()['health']['status']=='waiting_writer');self.assertEqual(len(calls),1);self.assertEqual(a.retries,0)
   finally:release.set();holder_thread.join(2);t.join(2)
   self.assertFalse(t.is_alive());self.assertEqual(a.snapshot()['health']['status'],'ok');self.assertEqual(len(calls),1)
 def test_real_sqlite_busy_and_io_failure_are_not_relabelled_as_waits(self):
  for code,retry in [(sqlite3.SQLITE_BUSY,True),(sqlite3.SQLITE_IOERR,False)]:
   with self.subTest(code=code),tempfile.TemporaryDirectory()as folder:
    path=Path(folder)/'e.sqlite';self.seed(path);error=sqlite3.OperationalError('synthetic real SQL boundary');error.sqlite_errorcode=code
    a=Analytics(path,MagicMock(),work=MagicMock(side_effect=error));self.assertFalse(a.tick());h=a.snapshot()['health']
    self.assertEqual(h['status'],'retrying'if retry else'degraded');self.assertEqual(a.retries,1);self.assertEqual(a.writer_waits,0)
    self.assertEqual(h['last_failure']['storage_error']['sqlite_errorcode'],code)
 def test_background_ticket_yields_to_fast_evidence_then_is_served(self):
  gate=Gate();gate.acquire(False,1);order=[];stop=threading.Event();threads=[]
  def run(name,fast):
   gate.acquire(fast,1,cancel=stop if not fast else None)
   try:order.append(name)
   finally:gate.release()
  for name,fast in [('analytics',False),('evidence',True)]:
   t=threading.Thread(target=run,args=(name,fast));threads.append(t);t.start()
  with gate.condition:self.assertTrue(gate.condition.wait_for(lambda:len(gate.waiters)==2,1))
  gate.release()
  for t in threads:t.join(2)
  self.assertEqual(order,['evidence','analytics'])
 def test_existing_evidence_schema_does_not_acquire_ddl_writer_per_batch(self):
  from energy import isolated_control as iso
  from energy.sqlite_writes import Connection
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';evidence=self.seed(path);s=Store(path)
   try:
    rows,states,value,_=evidence.rows[-1]
    with patch.object(Connection,'executescript',side_effect=AssertionError('Repeated schema write')):
     iso.persist_batch(s,{'runtime':'fresh','seq':1,'at':value['at'],'rows':rows,'loss':{},'states':states,'result':value})
   finally:s.close()

 def test_existing_ram_and_legacy_schema_are_reads_but_missing_index_is_repaired(self):
  from energy import ram_control,control_journal,priority,soc_runtime,priority_audit
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';s=Store(path,timeout=.03)
   try:
    for module,index in [(ram_control,'ram_samples_day'),(control_journal,'control_samples_day'),(priority,'priority_samples_day'),(soc_runtime,'soc_observation_day'),(priority_audit,None)]:
     module.schema(s.db);held=threading.Event();release=threading.Event()
     def hold():
      g=gate_for(path);g.acquire(False,1);held.set();release.wait(2);g.release()
     t=threading.Thread(target=hold);t.start();self.assertTrue(held.wait(1))
     try:module.schema(s.db)
     finally:release.set();t.join(2)
     target=index or 'priority_commands'
     with s.db:s.db.execute(('DROP INDEX 'if index else'DROP TABLE ')+target)
     module.schema(s.db)
     self.assertIsNotNone(s.db.execute('SELECT name FROM sqlite_master WHERE name=?',(target,)).fetchone())
   finally:s.close()
