"""Conservative tiered evidence retention, with durable ACK/day receipts.

Only *closed, finalized and fully acknowledged* days are eligible. Permanent
summaries, forecasts, revision history, calibration, security events and SOC
decision hashes remain untouched. Physical actions: zero.
"""
import hashlib
from datetime import timedelta,datetime,timezone
from .core import TZ, instant
from .store import pack,unpack
from . import journal_transport,night

RAW_DAYS=14
OBSERVATION_DAYS=90
MIN_GAP_S=12*3600

def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS evidence_retention_meta
       (key TEXT PRIMARY KEY, payload BLOB NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS journal_transport_archive
       (day TEXT PRIMARY KEY, first_seq INTEGER NOT NULL, last_seq INTEGER NOT NULL,
       chunks INTEGER NOT NULL, digest TEXT NOT NULL, archived_at TEXT NOT NULL)""")

def _latest(db):
    row=db.execute("SELECT payload FROM evidence_retention_meta WHERE key='last'").fetchone()
    return unpack(row[0]) if row else {}

def _day_finalized(db,day,table):
    return db.execute(f"SELECT 1 FROM {table} WHERE day=?",(day,)).fetchone() is not None

def _journal_eligible(db,day,ack):
    records=db.execute("SELECT seq,payload FROM journal_transport_outbox WHERE day=? ORDER BY seq",(day,)).fetchall()
    if not records:return None
    seqs=[x[0] for x in records]
    if seqs[-1]>=ack:return None  # Keep live head; preserve nonzero high-water mark.
    rec=db.execute(
       "SELECT count(*) FROM journal_transport_receipts WHERE seq IN "+
       "(SELECT seq FROM journal_transport_outbox WHERE day=?)",
       (day,)).fetchone()[0]
    if rec!=len(records):return None
    run_row=db.execute("SELECT payload FROM ram_control_sessions WHERE day=?",(day,)).fetchone()
    if not run_row:return None
    run=unpack(run_row[0])
    if not run.get("closed_at"):return None
    cursor=journal_transport.get(db,"queued:"+day)
    if not cursor:return None
    if cursor.get("session_hash")!=hashlib.sha256(journal_transport.encoded(run)).hexdigest():return None
    last_event=db.execute("SELECT coalesce(max(id),0) FROM ram_control_events WHERE day=?",(day,)).fetchone()[0]
    last_sample=db.execute("SELECT coalesce(max(rowid),0) FROM ram_control_samples WHERE day=?",(day,)).fetchone()[0]
    if cursor.get("event",0)<last_event or cursor.get("sample",0)<last_sample:
       return None
    return records

def prune(store,now,force=False):
    db=store.db
    schema(db)
    when=instant(now)
    local=when.astimezone(TZ)
    if night.window(when.isoformat()):
        return {"status":"skipped_night_window"}
    last=_latest(db)
    if not force and last.get("completed_at"):
        try:
            if (when-instant(last["completed_at"])).total_seconds()<MIN_GAP_S:
                return {"status":"waiting","last":last}
        except (KeyError,ValueError,TypeError):
            pass
    cutoff=(local.date()-timedelta(days=RAW_DAYS)).isoformat()
    observation_cutoff=(local.date()-timedelta(days=OBSERVATION_DAYS)).isoformat()
    # Bound the cost and number of old days touched in a single maintenance
    # transaction. Allows graceful recovery after a power failure.
    eligible_days=[d for (d,) in db.execute(
        "SELECT DISTINCT day FROM journal_transport_outbox WHERE day<=? ORDER BY day LIMIT 3",(cutoff,))]
    ack=journal_transport.get(db,"ack",0)
    summary={"status":"ok","completed_at":when.isoformat(),"raw_cutoff":cutoff,
             "observation_cutoff":observation_cutoff,"archived_days":[],"removed":{}}
    with db:
        for day in eligible_days:
            records=_journal_eligible(db,day,ack)
            if not records:
                continue
            first,last_seq=records[0][0],records[-1][0]
            digest=hashlib.sha256()
            for seq,blob in records:
                digest.update(str(seq).encode()+b":")
                digest.update(hashlib.sha256(blob).digest())
            old=db.execute("SELECT first_seq,last_seq,chunks,digest FROM journal_transport_archive WHERE day=?",(day,)).fetchone()
            new=(first,last_seq,len(records),digest.hexdigest())
            if old and old!=new:
                raise ValueError("JOURNAL_RETENTION_ARCHIVE_CONFLICT")
            if not old:
                db.execute("INSERT INTO journal_transport_archive VALUES(?,?,?,?,?,?)",
                       (day,*new,when.isoformat()))
            # Old confirmed payload and its duplicate receipt have permanent
            # day/seq/hash digest above. ACK and high-water seq never change.
            db.execute("DELETE FROM journal_transport_receipts WHERE seq IN "
                       "(SELECT seq FROM journal_transport_outbox WHERE day=?)",(day,))
            db.execute("DELETE FROM journal_transport_outbox WHERE day=?",(day,))
            # Defensive: only delete old raw control rows if queued cursors,
            # closed session and all receipts were confirmed.
            # Raw high-frequency samples expire, but consequential control
            # events remain permanently queryable for safety incident review.
            table="ram_control_samples"
            n=db.execute("SELECT count(*) FROM ram_control_samples WHERE day=?",(day,)).fetchone()[0]
            db.execute("DELETE FROM ram_control_samples WHERE day=?",(day,))
            summary["removed"][table]=summary["removed"].get(table,0)+n
            summary["removed"]["journal_transport_outbox"]=summary["removed"].get("journal_transport_outbox",0)+len(records)
            summary["removed"]["journal_transport_receipts"]=summary["removed"].get("journal_transport_receipts",0)+len(records)
            summary["archived_days"].append(day)
        # Sample tables have separate read-model contracts. Delete only after
        # the matching immutable day summary is sealed.
        for table,summary_table in (
            ("priority_samples","priority_summaries"),
            ("night_samples","night_summaries")):
            days=[d for (d,) in db.execute(
                  f"SELECT DISTINCT day FROM {table} WHERE day<=? ORDER BY day LIMIT 3",(cutoff,))]
            for day in days:
                if not _day_finalized(db,day,summary_table):continue
                n=db.execute(f"SELECT count(*) FROM {table} WHERE day=?",(day,)).fetchone()[0]
                db.execute(f"DELETE FROM {table} WHERE day=?",(day,))
                summary["removed"][table]=summary["removed"].get(table,0)+n
        # SOC minute observations aid calibration. Preserve 90 days and never
        # delete SOC decisions, reviews, model versions or daily summaries.
        n=db.execute("SELECT count(*) FROM soc_observations WHERE day<=?",(observation_cutoff,)).fetchone()[0]
        if n:
            db.execute("DELETE FROM soc_observations WHERE day<=?",(observation_cutoff,))
            summary["removed"]["soc_observations"]=n
        db.execute("INSERT OR REPLACE INTO evidence_retention_meta VALUES('last',?)",(pack(summary),))
    return summary
