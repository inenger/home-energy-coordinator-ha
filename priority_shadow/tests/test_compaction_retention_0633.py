"""0.6.33: lossless priority sample refs, ACK-gated tiered retention,
and historic SOC encoder compatibility. All fixtures synthetic.
"""
import hashlib,sqlite3,unittest
from types import SimpleNamespace
from energy import priority_sample_storage as pss,evidence_retention as ret,journal_transport
from energy.store import pack,unpack
from energy.offline_compaction import cached_prepare
from energy.soc_storage import prepare as soc_prepare
from energy.soc_evidence import seal

class SharedPriority(unittest.TestCase):
    def test_exact_hydration_and_dedup(self):
        db=sqlite3.connect(":memory:")
        row={"at":"2026-11-13T03:00:05+00:00","day":"2026-11-13",
             "session":{"forecast":list(range(700)),"policy":"max_fill"},
             "inputs":{"ev_w":11200},"models":{"ev":{"soc":12}}}
        a=pss.encoded(db,row);b=pss.encoded(db,{**row,"at":"2026-11-13T03:00:10+00:00"})
        self.assertEqual(pss.read(db,a),row)
        self.assertEqual(pss.read(db,b)["session"],row["session"])
        self.assertEqual(db.execute("SELECT count(*) FROM priority_sample_parts").fetchone()[0],1)
        self.assertLess(len(a),len(pack(row)))
        db.execute("DELETE FROM priority_sample_parts")
        with self.assertRaises(ValueError):pss.read(db,a)
        db.close()

    def test_legacy_and_malformed(self):
        db=sqlite3.connect(":memory:")
        pss.schema(db)
        legacy={"day":"2026-11-13","at":"2026-11-13T03:00:00+00:00","session":None}
        self.assertEqual(pss.read(db,pack(legacy)),legacy)
        with self.assertRaises(ValueError):
            pss.read(db,pack({"storage_format":pss.FORMAT,"refs":{"session":"wrong"},"inline":{"day":"2026-11-13","at":"2026-11-13T03:00:00+00:00"}}))
        db.close()

    def test_soc_encoded_compatibility(self):
        d=seal({"issued_at":"2026-11-13T02:00:00+00:00","day":"2026-11-13",
              "forecast_versions":[{"forecast":list(range(1600))}],
              "calibration_context":{"context":list(range(120))},
              "battery_energy_model":{"values":list(range(30))},
              "status":"conditional_shadow_plan","target_soc_pct":80})
        raw=pack(d)
        self.assertEqual(cached_prepare(d,raw,{}),soc_prepare(d,raw))

class TieredRetention(unittest.TestCase):
    def fixture(self,ack=2):
        db=sqlite3.connect(":memory:")
        db.executescript("""
        CREATE TABLE ram_control_sessions(day TEXT PRIMARY KEY,payload BLOB);
        CREATE TABLE ram_control_events(id INTEGER PRIMARY KEY,day TEXT,at TEXT,payload BLOB);
        CREATE TABLE ram_control_samples(at TEXT PRIMARY KEY,day TEXT,payload BLOB);
        CREATE TABLE priority_samples(at TEXT PRIMARY KEY,day TEXT,payload BLOB);
        CREATE TABLE priority_summaries(day TEXT PRIMARY KEY,payload BLOB);
        CREATE TABLE night_samples(at TEXT PRIMARY KEY,day TEXT,payload BLOB);
        CREATE TABLE night_summaries(day TEXT PRIMARY KEY,payload BLOB);
        CREATE TABLE soc_observations(at TEXT PRIMARY KEY,day TEXT,payload BLOB);
        """)
        journal_transport.schema(db)
        old="2026-10-20";fresh="2026-11-13"
        oldrun={"day":old,"closed_at":"2026-10-20T05:00:00+00:00"}
        db.execute("INSERT INTO ram_control_sessions VALUES(?,?)",(old,pack(oldrun)))
        db.execute("INSERT INTO ram_control_events VALUES(?,?,?,?)",(1,old,old+"T03:00:01+00:00",pack({"reason":"safe"})))
        db.execute("INSERT INTO ram_control_samples VALUES(?,?,?)",(old+"T03:00:05+00:00",old,pack({"at":"test"})))
        db.execute("INSERT INTO priority_samples VALUES(?,?,?)",(old+"T03:00:05+00:00",old,pack({"at":"test"})))
        db.execute("INSERT INTO night_samples VALUES(?,?,?)",(old+"T03:00:05+00:00",old,pack({"at":"test"})))
        db.execute("INSERT INTO priority_summaries VALUES(?,?)",(old,pack({"day":old,"final":True})))
        db.execute("INSERT INTO night_summaries VALUES(?,?)",(old,pack({"day":old,"final":True})))
        for seq,day in ((1,old),(2,fresh)):
            db.execute("INSERT INTO journal_transport_outbox VALUES(?,?,?,?)",(seq,day,day+"T03:00:05+00:00",pack({"seq":seq})))
            db.execute("INSERT INTO journal_transport_receipts VALUES(?,?,?)",(seq,day+"T03:00:10+00:00","abc"))
        journal_transport.put(db,"ack",ack)
        journal_transport.put(db,"queued:"+old,{"event":1,"sample":1,
          "session_hash":hashlib.sha256(journal_transport.encoded(unpack(pack(oldrun)))).hexdigest()})
        db.commit()
        return db,SimpleNamespace(db=db)

    def test_ack_closed_gate_and_immutable_summary(self):
        db,store=self.fixture()
        result=ret.prune(store,"2026-11-13T11:00:00+00:00",force=True)
        self.assertEqual(result["archived_days"],["2026-10-20"])
        self.assertEqual(db.execute("select count(*) from journal_transport_archive").fetchone()[0],1)
        self.assertEqual(db.execute("select min(seq),max(seq),count(*) from journal_transport_outbox").fetchone(),(2,2,1))
        self.assertEqual(db.execute("select count(*) from journal_transport_receipts").fetchone()[0],1)
        self.assertEqual(journal_transport.get(db,"ack"),2)
        self.assertEqual(db.execute("select count(*) from priority_samples").fetchone()[0],0)
        self.assertEqual(db.execute("select count(*) from priority_summaries").fetchone()[0],1)
        self.assertEqual(db.execute("select count(*) from night_summaries").fetchone()[0],1)
        self.assertEqual(db.execute("select count(*) from ram_control_samples").fetchone()[0],0)
        self.assertEqual(db.execute("select count(*) from ram_control_events").fetchone()[0],1)
        self.assertEqual(ret.prune(store,"2026-11-13T11:01:00+00:00",force=True)["archived_days"],[])
        db.close()

    def test_no_ack_no_raw_removal(self):
        db,store=self.fixture(ack=0)
        result=ret.prune(store,"2026-11-13T11:00:00+00:00",force=True)
        self.assertFalse(result["archived_days"])
        self.assertEqual(db.execute("select count(*) from journal_transport_outbox").fetchone()[0],2)
        self.assertEqual(db.execute("select count(*) from ram_control_samples").fetchone()[0],1)
        db.close()

    def test_skip_active_window(self):
        db,store=self.fixture()
        result=ret.prune(store,"2026-11-13T03:20:00+00:00",force=True)
        self.assertEqual(result["status"],"skipped_night_window")
        self.assertEqual(db.execute("select count(*) from journal_transport_outbox").fetchone()[0],2)
        db.close()

if __name__=="__main__":unittest.main()
