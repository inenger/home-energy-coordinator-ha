"""Native archive -> verified restore -> production seed/control, synthetic only."""
from contextlib import closing
import json
from pathlib import Path, PurePath
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch
from energy import native_backup as nb, isolated_control as iso, journal_transport
from energy.store import Store, unpack
from test_control_isolation_0620 import Clock, Stop, Client, Evidence, Monitor

ROOT = Path(__file__).resolve().parents[1]

def archive_data(root, target):
    # Same suffix matching contract as Supervisor _is_excluded_by_filter.
    import re
    section=(ROOT/'config.yaml').read_text().split('backup_exclude:',1)[1].split('init:',1)[0]
    excludes=re.findall(r'  - "([^\"]+)"',section)
    def excluded(name):
        parts=PurePath(name).relative_to('data').parts
        paths=[PurePath(*parts[:i])for i in range(1,len(parts)+1)]
        return any(p.match(x)for p in paths for x in excludes)
    # securetar filters each archive-relative name BEFORE stat/open/recursion.
    with tarfile.open(target,'w')as tar:
        def add(path,name):
            if excluded(name):return
            tar.add(path,arcname=name,recursive=False)
            if path.is_dir() and not path.is_symlink():
                for child in path.iterdir():add(child,name+'/'+child.name)
        add(root,'data')


def seed_database(root):
    clock = Clock(); evidence = Evidence(); monitor = Monitor()
    iso.run_loop(Client(clock), evidence, monitor, Stop(clock, 30), clock.now, lambda: clock.sec)
    db = root / "evidence/evidence.sqlite"
    store = Store(db)
    for seq, (rows, states, value, generation) in enumerate(evidence.rows, 1):
        iso.persist_batch(store, {"runtime": "synthetic-native", "seq": seq,
            "at": value["at"], "rows": rows, "loss": {}, "states": states, "result": value})
        journal_transport.enqueue(store, value["control_journal"])
    store.close()
    return db, evidence, monitor

class NativeBackupTests(unittest.TestCase):
    def tearDown(self):
        # Fixtures that delete the whole fake installation must reap the new
        # hook child too; production finish runs in the separate post-hook.
        from energy import native_backup_holder as holder
        for root in tuple(holder._children):holder.stop(Path(root))

    def test_config_uses_hot_hooks_and_keeps_raw_sqlite_stopped_fallback(self):
        config = (ROOT / "config.yaml").read_text()
        self.assertIn("backup: hot", config)
        self.assertIn("python3 -m energy.native_backup prepare", config)
        self.assertIn("python3 -m energy.native_backup finish", config)
        self.assertIn('  - "native-backup-source-id"', config)
        self.assertNotIn("backup: cold", config)
        self.assertNotIn("evidence.sqlite", config)
        source = (ROOT / "energy/priority_observer.py").read_text()
        self.assertLess(source.index("restored = restore_native_backup("), source.index("EvidenceBridge(DATA/"))

    def test_hot_archive_restore_exact_committed_state_then_new_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); root = base / "live"; root.mkdir()
            db, evidence, monitor = seed_database(root)
            before = sqlite3.connect(db)
            expected = {table: list(before.execute("SELECT * FROM " + table)) for table in
                ("ram_control_events", "ram_control_samples", "control_evidence_batches",
                 "control_analytics_pending", "journal_transport_outbox")}
            before.close()
            manifest = nb.prepare(root)
            # New writes after the snapshot cannot make its archive inconsistent.
            writer = sqlite3.connect(db)
            writer.execute("CREATE TABLE later_write(v)")
            writer.execute("INSERT INTO later_write VALUES(1)"); writer.commit()
            native = base / "native.tar"; archive_data(root, native)
            with tarfile.open(native) as tar:
                names = tar.getnames()
                self.assertIn("data/" + nb.BUNDLE, names)
                self.assertNotIn("data/" + nb.SENTINEL, names)
                tar.extractall(base / "restore", filter="data")
            nb.finish(root)
            self.assertFalse((root / nb.BUNDLE).exists())
            restored_root = base / "restore/data"
            receipt = nb.restore(restored_root)
            self.assertEqual(receipt["sha256"], manifest["sha256"])
            self.assertEqual(receipt["status"], "restored_native_snapshot")
            store = Store(restored_root / "evidence/evidence.sqlite")
            try:
                for table, rows in expected.items():
                    self.assertEqual(list(store.db.execute("SELECT * FROM " + table)), rows)
                self.assertIsNone(store.db.execute("SELECT name FROM sqlite_master WHERE name='later_write'").fetchone())
                seed = iso.seed_from(store)
            finally:
                store.close()
            clock = Clock(); clock.sec = 60
            class Restored(Evidence):
                def seed(self): return seed
            after = Monitor()
            iso.run_loop(Client(clock), Restored(), after, Stop(clock, 80), clock.now, lambda: clock.sec)
            self.assertEqual(after.results[0]["control_journal"]["session"]["target_ac_w"], 0)
            self.assertGreater(after.results[1]["control_journal"]["session"]["target_ac_w"], 0)
            self.assertTrue(all(v["device_actions"] == 0 for v in after.results))
            writer.close()

    def test_live_restart_during_backup_never_rewinds_or_removes_wal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); db, _, _ = seed_database(root)
            nb.prepare(root)
            writer = sqlite3.connect(db); writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE later(v)"); writer.execute("INSERT INTO later VALUES(42)"); writer.commit()
            self.assertEqual(nb.restore(root)["status"], "live_installation_snapshot_not_restored")
            self.assertEqual(writer.execute("SELECT v FROM later").fetchone(), (42,))
            self.assertTrue(Path(str(db) + "-wal").exists())
            writer.close()

    def test_blocked_snapshot_hook_does_not_pause_production_control(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); seed_database(root)
            entered = threading.Event(); release = threading.Event(); errors = []
            actual = nb.checked_copy
            def slow(*args):
                entered.set()
                if not release.wait(4): raise TimeoutError("test release missing")
                return actual(*args)
            def hook():
                try: nb.prepare(root)
                except BaseException as error: errors.append(error)
            with patch.object(nb, "checked_copy", side_effect=slow):
                thread = threading.Thread(target=hook); thread.start()
                self.assertTrue(entered.wait(2))
                try:
                    clock = Clock(); evidence = Evidence(); monitor = Monitor()
                    iso.run_loop(Client(clock), evidence, monitor, Stop(clock, 100), clock.now, lambda: clock.sec)
                    samples = [v["control_journal"]["recent_samples"][0] for v in monitor.results]
                    self.assertGreater(len(samples), 15)
                    self.assertGreater(samples[-1]["ram_target_ac_w"], 0)
                    self.assertFalse(any(v["collection_health"]["status"] == "failed" for v in monitor.results))
                    self.assertTrue(thread.is_alive())
                finally:
                    release.set(); thread.join(5)
            self.assertFalse(errors)

    def test_snapshot_online_backup_with_continuous_wal_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); db, _, _ = seed_database(root)
            ready = threading.Event(); stop = threading.Event(); errors = []
            def write():
                try:
                    with closing(sqlite3.connect(db)) as connection:
                        connection.execute("CREATE TABLE paired(n INTEGER PRIMARY KEY, mirror INTEGER)")
                        ready.set()
                        n = 0
                        while not stop.is_set():
                            with connection:
                                connection.execute("INSERT INTO paired VALUES(?,?)", (n, n))
                            n += 1; stop.wait(.001)
                except BaseException as e: errors.append(e)
            thread = threading.Thread(target=write); thread.start(); self.assertTrue(ready.wait(2))
            try: manifest = nb.prepare(root)
            finally: stop.set(); thread.join(3)
            self.assertFalse(errors)
            (root / nb.SENTINEL).unlink()
            self.assertEqual(nb.restore(root)["sha256"], manifest["sha256"])
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(connection.execute("SELECT count(*) FROM paired WHERE n!=mirror").fetchone(), (0,))

    def test_tampered_snapshot_fails_before_touching_existing_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); db, _, _ = seed_database(root); nb.prepare(root)
            with zipfile.ZipFile(root / nb.BUNDLE) as archive:
                manifest = archive.read("manifest.json"); content = archive.read("evidence.sqlite")
            with zipfile.ZipFile(root / nb.BUNDLE, "w") as archive:
                archive.writestr("manifest.json", manifest)
                archive.writestr("evidence.sqlite", b"x" + content[1:])
            (root / nb.SENTINEL).unlink(); original = nb.sha256(db)
            with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"): nb.restore(root)
            self.assertEqual(nb.sha256(db), original)

    def test_missing_source_and_deadline_fail_preparation_not_false_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(FileNotFoundError): nb.prepare(root)
            db, _, _ = seed_database(root)
            with self.assertRaises(TimeoutError): nb.prepare(root, timeout=-1)
            self.assertFalse((root / nb.BUNDLE).exists())

    def test_stopped_app_archive_without_hook_restores_raw_sqlite_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); root = base / "stopped"; root.mkdir()
            db, _, _ = seed_database(root); original = nb.sha256(db)
            native = base / "stopped.tar"; archive_data(root, native)
            with tarfile.open(native) as tar: tar.extractall(base / "restore", filter="data")
            restored_root = base / "restore/data"
            self.assertEqual(nb.restore(restored_root)["status"], "no_native_snapshot")
            self.assertEqual(nb.sha256(restored_root / "evidence/evidence.sqlite"), original)

    def test_partial_restore_retries_and_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); db, _, _ = seed_database(root); manifest = nb.prepare(root)
            (root / nb.SENTINEL).unlink(); original = nb.sha256(db)
            actual = nb.os.replace
            def fail_before_replace(source, target):
                if Path(target) == db: raise OSError("synthetic power loss before final rename")
                return actual(source, target)
            with patch.object(nb.os, "replace", side_effect=fail_before_replace):
                with self.assertRaises(OSError): nb.restore(root)
            self.assertEqual(nb.sha256(db), original)
            saved = root / "native-restore-original" / manifest["generation"] / db.name
            self.assertEqual(nb.sha256(saved), original)
            self.assertEqual(nb.restore(root)["status"], "restored_native_snapshot")
            self.assertEqual(nb.restore(root)["status"], "live_installation_snapshot_not_restored")

if __name__ == "__main__":
    unittest.main()
