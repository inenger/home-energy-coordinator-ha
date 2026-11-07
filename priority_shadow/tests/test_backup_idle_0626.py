"""Real WAL lifecycle and idle publisher/analytics paths; synthetic data only."""
import os,json,sqlite3,subprocess,sys,tarfile,tempfile,threading,time,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import MagicMock,patch
from energy import native_backup as nb,journal_transport as transport
from energy.ancillary_analytics import Analytics,schema as analytics_schema
from energy.sqlite_writes import gate_for,WriterTimeout
from energy.store import Store
from test_native_backup_0624 import archive_data

class BackupIdleTests(unittest.TestCase):
 def tearDown(self):
  try:from energy import native_backup_holder as holder
  except ImportError:return
  for root in tuple(holder._children):holder.stop(Path(root))
 def database(self,root):
  path=root/'evidence/evidence.sqlite';s=Store(path)
  with s.db:s.db.execute('CREATE TABLE paired(n PRIMARY KEY,mirror)');s.db.execute('INSERT INTO paired VALUES(1,1)')
  s.close();return path
 def test_pre_hook_pins_wal_across_last_writer_close_and_archive_restore(self):
  with tempfile.TemporaryDirectory()as folder:
   base=Path(folder);root=base/'live';root.mkdir();path=self.database(root)
   manifest=nb.prepare(root)
   writer=sqlite3.connect(path);writer.execute('INSERT INTO paired VALUES(2,2)');writer.commit()
   wal=Path(str(path)+'-wal');shm=Path(str(path)+'-shm');self.assertTrue(wal.exists());self.assertTrue(shm.exists())
   # Capture the paths exactly as an archiver would, then close/reopen all
   # evidence-worker connections before opening them for tar.
   enumerated=[wal,shm];writer.close()
   for i in range(3,7):
    with closing(sqlite3.connect(path))as writer:writer.execute('INSERT INTO paired VALUES(?,?)',(i,i));writer.commit()
   for file in enumerated:self.assertTrue(file.exists(),'last writer removed '+file.name)
   with tarfile.open(base/'enumerated.tar','w')as tar:
    for file in enumerated:tar.add(file,arcname=file.name)
   archive_data(root,base/'native.tar');nb.finish(root)
   with tarfile.open(base/'native.tar')as tar:
    self.assertFalse(any('.native-backup-holder'in n for n in tar.getnames()))
    tar.extractall(base/'restore',filter='data')
   restored=base/'restore/data';receipt=nb.restore(restored);self.assertEqual(receipt['sha256'],manifest['sha256'])
   with closing(sqlite3.connect(restored/'evidence/evidence.sqlite'))as db:self.assertEqual(db.execute('SELECT *FROM paired').fetchall(),[(1,1)])
 def test_holder_has_no_transaction_or_device_access_and_writes_continue(self):
  from energy import native_backup_holder as holder
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);path=self.database(root);nb.prepare(root)
   with closing(sqlite3.connect(path,timeout=.05))as db:
    db.execute('BEGIN IMMEDIATE');db.execute('INSERT INTO paired VALUES(2,2)');db.commit()
   self.assertTrue(holder.active(root));nb.finish(root);self.assertFalse(holder.active(root))
   self.assertFalse((root/holder.LEASE).exists());self.assertFalse((root/holder.READY).exists())
 def test_failed_snapshot_releases_holder_and_does_not_report_success(self):
  from energy import native_backup_holder as holder
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);self.database(root)
   with patch.object(nb,'checked_copy',side_effect=OSError('synthetic I/O')),self.assertRaises(OSError):nb.prepare(root)
   self.assertFalse(holder.active(root));self.assertFalse((root/holder.LEASE).exists());self.assertFalse((root/nb.BUNDLE).exists())
 def test_duplicate_backup_rejected_without_replacing_active_snapshot(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);self.database(root);nb.prepare(root);before=nb.sha256(root/nb.BUNDLE)
   with self.assertRaisesRegex(RuntimeError,'ALREADY_ACTIVE'):nb.prepare(root)
   self.assertEqual(nb.sha256(root/nb.BUNDLE),before);nb.finish(root)
 def test_lost_holder_is_reported_not_false_success(self):
  from energy import native_backup_holder as holder
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);path=self.database(root);handle=holder.start(root,path)
   import signal
   os.kill(handle['pid'],signal.SIGTERM)
   deadline=time.monotonic()+3
   while holder.active(root)and time.monotonic()<deadline:time.sleep(.05)
   self.assertFalse(holder.active(root))
   with self.assertRaisesRegex(RuntimeError,'HOLDER_LOST'):nb.finish(root)
 def test_uncleanly_stopped_raw_fallback_preserves_committed_wal(self):
  with tempfile.TemporaryDirectory()as folder:
   base=Path(folder);root=base/'stopped';root.mkdir();path=self.database(root)
   code="import sqlite3,os,sys;d=sqlite3.connect(sys.argv[1]);d.execute('PRAGMA journal_mode=WAL');d.execute('INSERT INTO paired VALUES(2,2)');d.commit();os._exit(0)"
   subprocess.run([sys.executable,'-c',code,str(path)],check=True)
   self.assertTrue(Path(str(path)+'-wal').exists());archive_data(root,base/'stopped.tar')
   with tarfile.open(base/'stopped.tar')as tar:tar.extractall(base/'restore',filter='data')
   restored=base/'restore/data';self.assertEqual(nb.restore(restored)['status'],'no_native_snapshot')
   with closing(sqlite3.connect(restored/'evidence/evidence.sqlite'))as db:self.assertEqual(db.execute('SELECT *FROM paired ORDER BY n').fetchall(),[(1,1),(2,2)])
 def hold(self,path):
  entered=threading.Event();release=threading.Event();gate=gate_for(path)
  def owner():
   gate.acquire(False,1);entered.set()
   try:release.wait(3)
   finally:gate.release()
  thread=threading.Thread(target=owner,name='synthetic-writer');thread.start();self.assertTrue(entered.wait(1));return release,thread
 def test_existing_store_open_and_idle_workers_do_not_take_writer_gate(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';store=Store(path);transport.schema(store.db);analytics_schema(store.db);store.close()
   release,thread=self.hold(path)
   try:
    reader=Store(path,timeout=.02)
    try:
     self.assertEqual(reader.db.execute('SELECT count(*)FROM objects').fetchone()[0],0)
     with self.assertRaises(WriterTimeout):
      with reader.db:reader.db.execute("INSERT INTO objects VALUES('must-wait','test',x'00')")
    finally:reader.close()
    publisher=transport.Publisher(path,client=MagicMock());publisher.tick()
    analytics=Analytics(path,MagicMock());self.assertFalse(analytics.tick());self.assertEqual(analytics.snapshot()['health']['status'],'ok')
    self.assertFalse(analytics.snapshot()['health'].get('retry_count',0))
   finally:release.set();thread.join(3)
 def test_missing_schema_still_initializes_and_full_sync_is_kept(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';store=Store(path)
   with store.db:store.db.execute('DROP INDEX samples_day')
   store.close();store=Store(path)
   try:
    self.assertIsNotNone(store.db.execute("SELECT name FROM sqlite_master WHERE name='samples_day'").fetchone())
    self.assertEqual(store.db.execute('PRAGMA synchronous').fetchone()[0],2)
   finally:store.close()

 def test_hook_parent_exit_keeps_holder_alive_until_separate_finish(self):
  from energy import native_backup_holder as holder
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);path=self.database(root)
   code="from energy import native_backup as n;from pathlib import Path;import sys;n.prepare(Path(sys.argv[1]))"
   subprocess.run([sys.executable,'-c',code,str(root)],cwd=Path(__file__).resolve().parents[1],check=True)
   self.assertTrue(holder.active(root))
   with closing(sqlite3.connect(path))as db:db.execute('INSERT INTO paired VALUES(2,2)');db.commit()
   self.assertTrue(Path(str(path)+'-wal').exists());nb.finish(root);self.assertFalse(holder.active(root))
 def test_holder_deadline_releases_lease_without_false_backup_success(self):
  from energy import native_backup_holder as holder
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);path=self.database(root);holder.start(root,path,hold_seconds=5)
   deadline=time.monotonic()+8
   while holder.active(root)and time.monotonic()<deadline:time.sleep(.05)
   self.assertFalse(holder.active(root))
   with self.assertRaisesRegex(RuntimeError,'HOLDER_LOST'):nb.finish(root)

 def test_native_filter_excludes_only_incomplete_json_and_overflow_files(self):
  with tempfile.TemporaryDirectory()as folder:
   base=Path(folder);root=base/'live';root.mkdir();self.database(root)
   (root/'evidence/priority-live.json.tmp').write_text('incomplete')
   (root/'evidence/priority-live.json').write_text('complete')
   overflow=root/'evidence/monitor-overflow';overflow.mkdir()
   (overflow/'pending-synthetic').write_text('incomplete')
   (overflow/'complete.json.zlib').write_text('retained')
   archive_data(root,base/'native.tar')
   with tarfile.open(base/'native.tar')as tar:
    names=tar.getnames();self.assertNotIn('data/evidence/priority-live.json.tmp',names)
    self.assertNotIn('data/evidence/monitor-overflow/pending-synthetic',names)
    self.assertIn('data/evidence/priority-live.json',names)
    self.assertIn('data/evidence/monitor-overflow/complete.json.zlib',names)
    self.assertIn('data/evidence/evidence.sqlite',names)
