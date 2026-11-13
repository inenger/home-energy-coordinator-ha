"""Synthetic crash-safe migration smoke test: no HA, no private data."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from energy.store import pack
from energy.soc_evidence import seal
from energy.priority_sample_storage import read as read_priority,FORMAT
from energy import offline_compaction as oc

class OfflineCompactionE2E(unittest.TestCase):
    def test_migrate_true_active_db_then_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);active=root/"active";active.mkdir()
            dbpath=active/"evidence.sqlite"
            con=sqlite3.connect(dbpath)
            con.executescript("""
             CREATE TABLE soc_decisions(at TEXT PRIMARY KEY,day TEXT NOT NULL,hash TEXT NOT NULL,payload BLOB NOT NULL);
             CREATE TABLE soc_decision_parts(hash TEXT PRIMARY KEY,field TEXT NOT NULL,payload BLOB NOT NULL);
             CREATE TABLE priority_samples(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
             CREATE TABLE ram_control_samples(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
             CREATE TABLE journal_transport_outbox(seq INTEGER PRIMARY KEY,day TEXT,at TEXT,payload BLOB);
             CREATE TABLE journal_transport_receipts(seq INTEGER PRIMARY KEY,recorded_at TEXT,sha256 TEXT);
             CREATE TABLE journal_transport_meta(key TEXT PRIMARY KEY,payload BLOB NOT NULL);
             CREATE TABLE night_samples(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
             CREATE TABLE soc_observations(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
             CREATE TABLE control_evidence_batches(runtime TEXT,seq INTEGER,at TEXT,payload BLOB);
             """)
            d=seal({"issued_at":"2026-11-13T02:01:00+00:00","day":"2026-11-13",
                    "status":"conditional_shadow_plan","forecast_versions":list(range(1800)),
                    "target_soc_pct":80})
            con.execute("INSERT INTO soc_decisions VALUES(?,?,?,?)",(d["issued_at"],d["day"],d["decision_hash"],pack(d)))
            p={"at":"2026-11-13T03:00:05+00:00","day":"2026-11-13",
               "session":{"forecast":list(range(500))},"inputs":{"ev_w":11000}}
            con.execute("INSERT INTO priority_samples VALUES(?,?,?)",(p["at"],p["day"],pack(p)))
            con.execute("INSERT INTO ram_control_samples VALUES(?,?,?)",("2026-11-13T03:00:05+00:00","2026-11-13",pack({"foo":1})))
            con.execute("INSERT INTO journal_transport_meta VALUES(?,?)",("ack",pack(0)))
            con.commit();con.close()
            work=root/"recovery";work.mkdir()
            (work/"REQUEST.json").write_text(json.dumps({"mode":"observe_only","action":"compact_lossless"}))
            with (patch.object(oc,"ROOT",work),
                  patch.object(oc,"REQUEST",work/"REQUEST.json"),
                  patch.object(oc,"SNAPSHOT",work/"full-original.sqlite"),
                  patch.object(oc,"CANDIDATE",work/"working-candidate.sqlite"),
                  patch.object(oc,"RESULT",work/"migration-status.json")):
                status=oc.run(dbpath)
                self.assertEqual(status["status"],"completed")
                self.assertEqual(status["soc"]["seen"],1)
                self.assertEqual(status["priority"]["seen"],1)
                con=sqlite3.connect(dbpath)
                self.assertEqual(con.execute("PRAGMA quick_check").fetchone(),("ok",))
                self.assertEqual(con.execute("SELECT count(*) FROM soc_decisions").fetchone()[0],1)
                self.assertEqual(con.execute("SELECT count(*) FROM ram_control_samples").fetchone()[0],1)
                converted=con.execute("SELECT payload FROM priority_samples").fetchone()[0]
                self.assertEqual(read_priority(con,converted),p)
                con.close()
                self.assertEqual(oc.run(dbpath)["status"],"no_request")
                self.assertTrue((work/"full-original.sqlite").is_file())
                self.assertTrue((work/"COMPLETED.json").is_file())

if __name__=="__main__":unittest.main()
