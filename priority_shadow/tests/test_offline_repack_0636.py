"""End-to-end, synthetic-only, fail-closed SQLite page repack regression."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from energy import offline_repack as repack


class LosslessRepackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="repack0636-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db = self.base / "evidence.sqlite"
        self.root = self.base / "repack"
        overrides = dict(
            ROOT=self.root,
            REQUEST=self.root / "REQUEST.json",
            STATUS=self.root / "repack-status.json",
            SNAPSHOT=self.root / "full-original.sqlite",
            CANDIDATE=self.root / "lossless-candidate.sqlite",
            COMPLETED=self.root / "COMPLETED.json",
        )
        p = patch.multiple(repack, **overrides)
        p.start()
        self.addCleanup(p.stop)
        self.root.mkdir(parents=True)
        c = sqlite3.connect(self.db)
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE journal_transport_outbox(
               seq INTEGER PRIMARY KEY, day TEXT NOT NULL, at TEXT NOT NULL, payload BLOB NOT NULL);
            CREATE TABLE journal_transport_receipts(
               seq INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE ram_control_samples(
               at TEXT PRIMARY KEY, day TEXT NOT NULL, payload BLOB NOT NULL);
            CREATE TABLE soc_decisions(
               at TEXT PRIMARY KEY, day TEXT NOT NULL, hash TEXT NOT NULL, payload BLOB NOT NULL);
            CREATE TABLE night_samples(at TEXT PRIMARY KEY, day TEXT, payload BLOB NOT NULL);
            CREATE TABLE evidence_retention_meta(key TEXT PRIMARY KEY,payload BLOB NOT NULL);
            CREATE TABLE used_once(id INTEGER PRIMARY KEY,payload BLOB NOT NULL);
        """)
        for n in range(24):
            at=f"2026-11-14T03:{n:02d}:00+01:00"
            blob=(b"\x00"+n.to_bytes(4,"big"))+bytes([n])*6000
            c.execute("INSERT INTO journal_transport_outbox VALUES(?,?,?,?)",
                      (n+1,"2026-11-14",at,blob))
            c.execute("INSERT INTO journal_transport_receipts VALUES(?,?,?)",
                      (n+1,at,"f"*64))
            c.execute("INSERT INTO ram_control_samples VALUES(?,?,?)",(at,"2026-11-14",blob))
            c.execute("INSERT INTO soc_decisions VALUES(?,?,?,?)",
                      (at,"2026-11-14","h"*64,blob))
            c.execute("INSERT INTO night_samples VALUES(?,?,?)",(at,"2026-11-14",blob))
        c.executemany("INSERT INTO used_once VALUES(?,?)",
                      [(n,b"X"*25000) for n in range(1,90)])
        c.execute("DELETE FROM used_once WHERE id<85")
        c.execute("INSERT INTO evidence_retention_meta VALUES(?,?)",
                  ("last", b"same retention bytes"))
        c.commit()
        c.close()

    def request(self):
        repack.REQUEST.write_text(json.dumps({
            "action":"repack_lossless","mode":"observe_only","expected_release":"0.6.36"}))

    def test_full_path_preserves_all_rows_and_transport_receipts(self):
        self.request()
        before=self.db.stat().st_size
        result=repack.run(self.db)
        self.assertEqual(result["status"],"completed")
        self.assertLess(result["after_bytes"],before)
        self.assertGreater(result["verified_rows"],100)
        self.assertTrue(repack.SNAPSHOT.exists())
        self.assertTrue(repack.COMPLETED.exists())
        self.assertFalse(repack.REQUEST.exists())
        a=sqlite3.connect(repack.SNAPSHOT)
        b=sqlite3.connect(self.db)
        try:
            self.assertEqual(repack.count_frontier(a),repack.count_frontier(b))
            for tab in ("ram_control_samples","soc_decisions","journal_transport_outbox",
                        "journal_transport_receipts","night_samples","evidence_retention_meta"):
                self.assertEqual(list(a.execute("SELECT rowid,* FROM "+tab+" ORDER BY rowid")),
                                 list(b.execute("SELECT rowid,* FROM "+tab+" ORDER BY rowid")))
            repack.verify(b)
        finally:
            a.close();b.close()
        self.assertEqual(repack.run(self.db)["status"],"no_request")

    def test_invalid_request_keeps_original_untouched(self):
        repack.REQUEST.write_text(json.dumps({
            "action":"delete_unused_rows","mode":"observe_only","expected_release":"0.6.36"}))
        with self.assertRaisesRegex(ValueError,"INVALID_REPACK_REQUEST"):
            repack.run(self.db)
        self.assertFalse(repack.SNAPSHOT.exists())

    def test_candidate_tampering_rejected_before_swap(self):
        original=sqlite3.connect(self.db)
        before=repack.count_frontier(original);original.close()
        repack.snapshot_original(self.db)
        reader=sqlite3.connect(repack.SNAPSHOT.as_uri()+"?mode=ro&immutable=1",uri=True)
        reader.execute("VACUUM INTO ?",(str(repack.CANDIDATE),))
        reader.close()
        writer=sqlite3.connect(repack.CANDIDATE)
        writer.execute("UPDATE journal_transport_receipts SET sha256='tampered' WHERE seq=5")
        writer.commit();writer.close()
        with self.assertRaisesRegex(ValueError,"REPACK_ROW_OR_PAYLOAD_CHANGED"):
            repack.compare_all(repack.SNAPSHOT,repack.CANDIDATE)
        live=sqlite3.connect(self.db)
        self.assertEqual(before,repack.count_frontier(live))
        live.close()

if __name__=="__main__":
    unittest.main()
