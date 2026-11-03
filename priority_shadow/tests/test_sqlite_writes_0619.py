"""Real SQLite/thread contention and complete main failures; synthetic data only."""
import sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from energy.store import Store
from energy.sqlite_writes import Gate,WriterTimeout,details
from energy import ram_control as c,priority_observer as obs
from test_ram_control import stamp
import test_collection_fixes_0618

class SQLiteWritesTests(unittest.TestCase):
 def test_main_control_keeps_local_background_writer_out_of_decision_scope(self):
  original=c.event;triggered=[False];attempted=threading.Event();release=threading.Event();threads=[];order=[];problems=[]
  def writer(path):
   attempted.set()
   try:
    store=Store(path)
    try:
     with store.db:
      store.db.execute("INSERT OR IGNORE INTO objects VALUES('synthetic-writer','test',x'00')")
      order.append('background');release.wait(1)
    finally:store.close()
   except BaseException as error:problems.append(error)
  def event(db,run,at,kind,*args,**kwargs):
   if not triggered[0]and kind=='would_set'and at>=stamp(20):
    triggered[0]=True;path=db.execute('PRAGMA database_list').fetchone()[2]
    thread=threading.Thread(target=writer,args=(path,));threads.append(thread);thread.start()
    self.assertTrue(attempted.wait(1));time.sleep(.05)
    try:
     value=original(db,run,at,kind,*args,**kwargs);order.append('control');return value
    finally:release.set()
   return original(db,run,at,kind,*args,**kwargs)
  case=test_collection_fixes_0618.CollectionFixTests()
  try:
   with patch.object(c,'event',side_effect=event):run,samples,events,*_=case.drive()
  finally:
   release.set()
   for thread in threads:thread.join(2)
  self.assertTrue(triggered[0]);self.assertFalse(problems);self.assertEqual(order,['control','background'])
  self.assertFalse([e for e in events if e['kind']=='would_stop_charge'])
  self.assertTrue(all(p.get('collection_health',{}).get('status')!='failed'for p in case.plans))

 def test_waiting_control_has_priority_over_queued_background_writer(self):
  gate=Gate();gate.acquire(False,1);order=[];threads=[]
  def use(name,fast):
   gate.acquire(fast,1)
   try:order.append(name)
   finally:gate.release()
  try:
   for name,fast in [('background',False),('control',True)]:
    thread=threading.Thread(target=use,args=(name,fast));threads.append(thread);thread.start()
   with gate.condition:self.assertTrue(gate.condition.wait_for(lambda:gate.fast_waiters==1,1))
  finally:gate.release()
  for thread in threads:thread.join(2)
  self.assertEqual(order,['control','background'])

 def test_local_wait_is_bounded_and_released_after_exception(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';main=Store(path,timeout=.03);ready=threading.Event();release=threading.Event()
   def hold():
    other=Store(path)
    try:
     with other.db:ready.set();release.wait(2)
    finally:other.close()
   thread=threading.Thread(target=hold);thread.start();self.assertTrue(ready.wait(1))
   try:
    start=time.perf_counter()
    with self.assertRaises(WriterTimeout):
     with main.db:pass
    self.assertLess(time.perf_counter()-start,.2)
   finally:release.set();thread.join(2)
   try:
    with self.assertRaises(ValueError):
     with main.db:raise ValueError('synthetic')
    with main.db:main.db.execute("INSERT INTO objects VALUES('after-rollback','test',x'00')")
   finally:main.close()

 def test_plain_read_remains_available_during_background_write(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';reader=Store(path);ready=threading.Event();release=threading.Event()
   def hold():
    store=Store(path)
    try:
     with store.db:
      store.db.execute("INSERT INTO objects VALUES('uncommitted','test',x'00')");ready.set();release.wait(2)
    finally:store.close()
   thread=threading.Thread(target=hold);thread.start();self.assertTrue(ready.wait(1))
   try:
    self.assertIsNone(reader.db.execute("SELECT hash FROM objects WHERE hash='uncommitted'").fetchone())
   finally:release.set();thread.join(2);reader.close()

 def test_external_sqlite_failure_keeps_native_code_message_in_main_and_journal(self):
  original=c.event;injected=[False]
  def event(db,run,at,kind,*args,**kwargs):
   if not injected[0]and kind=='would_set'and at>=stamp(20):
    injected[0]=True;path=db.execute('PRAGMA database_list').fetchone()[2];other=sqlite3.connect(path,timeout=.01);other.execute('BEGIN IMMEDIATE')
    try:return original(db,run,at,kind,*args,**kwargs)
    finally:other.rollback();other.close()
   return original(db,run,at,kind,*args,**kwargs)
  case=test_collection_fixes_0618.CollectionFixTests()
  with patch.object(c,'event',side_effect=event):run,samples,events,*_=case.drive()
  failed=next(p for p in case.plans if p.get('collection_health',{}).get('status')=='failed')
  detail=failed['collection_health']['storage_error'];self.assertEqual(detail['sqlite_errorname'],'SQLITE_BUSY');self.assertEqual(detail['sqlite_errorcode'],sqlite3.SQLITE_BUSY)
  self.assertIn('locked',detail['message'])
  event=next(e for e in events if e['kind']=='collection_failure')
  self.assertEqual(event['storage_error'],detail)
  self.assertTrue(any(e['kind']=='would_stop_charge'for e in events))
  self.assertTrue(any(s['ram_target_ac_w']>0 and s['at']>event['at']for s in samples))

 def test_other_sqlite_errors_are_not_treated_as_retryable_collection_success(self):
  error=sqlite3.OperationalError('synthetic disk I/O error')
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite')
   try:
    with self.assertRaises(sqlite3.OperationalError):
     with store.db:raise error
   finally:store.close()
  health=obs.failure_result(stamp(0),error,None)['collection_health']
  self.assertEqual(health['status'],'failed');self.assertEqual(health['storage_error']['message'],'synthetic disk I/O error')
  self.assertIsNone(details(ValueError('synthetic')))

 def test_soc_compression_does_not_hold_writer_gate(self):
  from energy import soc_runtime
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';main=Store(path,timeout=.03);started=threading.Event();release=threading.Event();problems=[];pack=soc_runtime.pack
   def slow_pack(value):started.set();release.wait(1);return pack(value)
   def write():
    store=Store(path)
    try:
     soc_runtime.schema(store.db)
     soc_runtime.record_decision(store,{'issued_at':stamp(0),'day':'2026-01-15','status':'synthetic','device_actions':0})
    except BaseException as error:problems.append(error)
    finally:store.close()
   with patch.object(soc_runtime,'pack',side_effect=slow_pack):
    thread=threading.Thread(target=write);thread.start();self.assertTrue(started.wait(1))
    try:
     with main.db:main.db.execute("INSERT INTO objects VALUES('control-during-compression','test',x'00')")
    finally:release.set();thread.join(2);main.close()
   self.assertFalse(problems)
