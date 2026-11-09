"""Synthetic regressions of journal publication and cooperative writer scopes."""
import base64,copy,os,random,tempfile,threading,unittest,zlib
from pathlib import Path
from unittest.mock import MagicMock,patch
from energy import isolated_control as iso,journal_transport as transport,publish_status
from energy.store import Store,unpack
from energy.monitor_payload import encoded,unpacked,PayloadOverflow
from energy.ancillary_analytics import Analytics
from test_night_fixes_0623 import drive_startup

class JournalWriterTests(unittest.TestCase):
 def seed(self,path):
  evidence,monitor=drive_startup();store=Store(path)
  for seq,(rows,states,result,generation)in enumerate(evidence.rows,1):
   iso.persist_batch(store,{'runtime':'synthetic-625','seq':seq,'at':result['at'],'rows':rows,'loss':{},'states':states,'result':result})
  store.close();return monitor.results[-1]
 def test_transport_compression_does_not_block_fifo_analytics(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';result=self.seed(path);entered=threading.Event();release=threading.Event();errors=[]
   original=transport.zlib.compress
   def delayed(*args,**kwargs):
    if threading.current_thread().name=='synthetic-transport' and b'\"events\":' in args[0]:entered.set();release.wait(3)
    return original(*args,**kwargs)
   def enqueue():
    store=Store(path)
    try:transport.enqueue(store,result['control_journal'])
    except BaseException as error:errors.append(error)
    finally:store.close()
   analytics=Analytics(path,MagicMock(),work=lambda store,item:{'at':item['at']})
   with patch.object(transport.zlib,'compress',side_effect=delayed):
    thread=threading.Thread(target=enqueue,name='synthetic-transport');thread.start()
    try:
     self.assertTrue(entered.wait(2));self.assertTrue(analytics.tick(),analytics.snapshot())
     self.assertFalse(release.is_set())
    finally:release.set();thread.join(4)
   self.assertFalse(thread.is_alive());self.assertFalse(errors)
   store=Store(path)
   try:
    before=store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0]
    self.assertGreater(before,0);transport.enqueue(store,result['control_journal'])
    self.assertEqual(before,store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0])
   finally:store.close()
 def test_large_live_preview_keeps_session_and_full_durable_events(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';result=self.seed(path);journal=result['control_journal'];noise=base64.b64encode(random.Random(625).randbytes(24000)).decode()
   journal['recent_events'][0]['diagnostic']={'synthetic_detail':noise}
   journal['transport']={'format':'journal-chunks-v1','stream_id':'synthetic','entity_id':transport.SENSOR}
   before=copy.deepcopy(result)
   for failure in (False,True):
    packets=publish_status.prepare_priority(result,failure)
    attrs=unpacked(next(payload['attributes']for entity,payload in packets if entity=='sensor.nocni_stinovy_ridici_denik'))
    self.assertEqual(attrs['session'],journal['session']);self.assertEqual(attrs['transport'],journal['transport'])
    self.assertEqual(attrs['recent_events'],[])
    self.assertEqual(attrs['preview_source'],'journal_transport')
    self.assertEqual(attrs['preview_omitted_counts']['events'],len(journal['recent_events']))
    self.assertTrue(all(len(encoded(payload['attributes']))<=14000 for entity,payload in packets))
   self.assertEqual(result,before)
   store=Store(path)
   try:
    event=journal['recent_events'][0];payload={k:v for k,v in event.items()if k!='id'}
    # Synthetic event persisted before transport; source is never shortened.
    from energy.store import pack
    with store.db:store.db.execute('UPDATE ram_control_events SET payload=? WHERE id=?',(pack(payload),event['id']))
    transport.enqueue(store,journal)
    parts=[unpack(p)for p, in store.db.execute('SELECT payload FROM journal_transport_outbox ORDER BY seq')]
    groups={}
    for part in parts:groups.setdefault(part['batch_id'],[]).append(part)
    events=[]
    import json
    for group in groups.values():
     raw=zlib.decompress(b''.join(base64.b64decode(x['data'])for x in sorted(group,key=lambda x:x['part_index'])))
     events.extend(json.loads(raw)['events'])
    self.assertEqual(next(e for e in events if e['id']==event['id'])['diagnostic']['synthetic_detail'],noise)
    if os.environ.get('JOURNAL_PROJECTION_FIXTURE'):
     from energy.monitor_payload import bounded
     projected=publish_status.bounded_priority_attributes('sensor.nocni_stinovy_ridici_denik',journal)
     projected=unpacked(projected);projected['transport']=transport.status(store)
     projected['transport'].update(status='ok',pending_chunks=0,days={journal['session']['day']:{'recorded_chunks':len(parts),'queued_chunks':len(parts),'first_recorded_at':result['at']}})
     Path(os.environ['JOURNAL_PROJECTION_FIXTURE']).write_text(json.dumps({'monitor':bounded(projected),'parts':parts,'events':events,'session':journal['session']}))
   finally:store.close()
 def test_non_preview_overflow_still_fails_explicitly(self):
  _,monitor=drive_startup();result=copy.deepcopy(monitor.results[-1])
  result['control_journal']['unrelated_unbounded_field']=base64.b64encode(random.Random(626).randbytes(32000)).decode()
  with self.assertRaises(PayloadOverflow):publish_status.prepare_priority(result)

 def test_retry_details_identify_holder_without_sql_or_values(self):
  from energy.sqlite_writes import gate_for,details,WriterTimeout
  gate=gate_for('/synthetic-writer-diagnostic');entered=threading.Event();release=threading.Event()
  def hold():
   gate.acquire(False,1);entered.set()
   try:release.wait(2)
   finally:gate.release()
  thread=threading.Thread(target=hold,name='synthetic-journal-owner');thread.start()
  try:
   self.assertTrue(entered.wait(1))
   with self.assertRaises(WriterTimeout)as caught:gate.acquire(True,.01)
   diagnostic=details(caught.exception)['writer_diagnostic']
   self.assertEqual(diagnostic['owner_thread'],'synthetic-journal-owner')
   self.assertGreaterEqual(diagnostic['held_seconds'],.01)
   self.assertNotIn('path',diagnostic);self.assertNotIn('sql',diagnostic)
  finally:release.set();thread.join(2)
  self.assertIsNone(gate.diagnostic()['owner_thread'])
 def test_external_busy_keeps_sqlite_identity_and_safe_operation(self):
  import sqlite3
  from energy.sqlite_writes import details
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';store=Store(path,timeout=.01);external=sqlite3.connect(path)
   external.execute('BEGIN IMMEDIATE')
   try:
    with self.assertRaises(sqlite3.OperationalError)as caught:
     with store.db:store.db.execute("INSERT INTO objects VALUES('synthetic','test',x'00')")
    detail=details(caught.exception);self.assertEqual(detail['sqlite_errorname'],'SQLITE_BUSY')
    self.assertEqual(detail['writer_diagnostic']['operation'],'INSERT')
    self.assertNotIn('synthetic',str(detail));self.assertEqual(detail['source'],'sqlite')
   finally:external.rollback();external.close();store.close()

 def test_concurrent_preparation_detects_cursor_conflict_and_retry_is_idempotent(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';result=self.seed(path);barrier=threading.Barrier(2);original=transport.zlib.compress;errors=[]
   def delayed(*args,**kwargs):
    if threading.current_thread().name.startswith('parallel-enqueue') and b'"events":'in args[0]:barrier.wait(3)
    return original(*args,**kwargs)
   def enqueue():
    store=Store(path)
    try:transport.enqueue(store,result['control_journal'])
    except BaseException as error:errors.append(error)
    finally:store.close()
   with patch.object(transport.zlib,'compress',side_effect=delayed):
    threads=[threading.Thread(target=enqueue,name='parallel-enqueue-'+str(i))for i in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(4)
   self.assertTrue(all(not thread.is_alive()for thread in threads))
   self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],transport.JournalQueueChanged)
   store=Store(path)
   try:
    before=list(store.db.execute('SELECT *FROM journal_transport_outbox'))
    transport.enqueue(store,result['control_journal'])
    self.assertEqual(before,list(store.db.execute('SELECT *FROM journal_transport_outbox')))
   finally:store.close()
 def test_failed_outbox_insert_rolls_back_cursor_then_retry_preserves_all_rows(self):
  from energy.sqlite_writes import Connection
  import sqlite3
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';result=self.seed(path);store=Store(path);original=Connection.execute;original_many=Connection.executemany
   def fail(connection,sql,parameters=()):
    if sql.startswith('INSERT INTO journal_transport_outbox'):raise sqlite3.OperationalError('synthetic I/O failure')
    return original(connection,sql,parameters)
   def fail_many(connection,sql,parameters):
    if sql.startswith('INSERT INTO journal_transport_outbox'):
     rows=list(parameters)
     if rows:original(connection,sql,rows[0])
     raise sqlite3.OperationalError('synthetic I/O failure after partial batch')
    return original_many(connection,sql,parameters)
   try:
    with patch.object(Connection,'execute',fail),patch.object(Connection,'executemany',fail_many),self.assertRaises(sqlite3.OperationalError):transport.enqueue(store,result['control_journal'])
    self.assertEqual(store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
    self.assertIsNone(transport.get(store.db,'queued:'+result['control_journal']['session']['day']))
    transport.enqueue(store,result['control_journal'])
    self.assertGreater(store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
    self.assertIsNotNone(transport.get(store.db,'queued:'+result['control_journal']['session']['day']))
   finally:store.close()
