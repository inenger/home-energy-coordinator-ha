"""Operator-authorized one-shot lossless SQLite repack of the *live* addon DB.

Run before EvidenceBridge starts, never from maintenance while writers are
active. No row deletion, no payload rewriting, no shortened retention.
All rowids, BLOB bytes, table counts, schemas and receipt records must agree.
"""
from __future__ import annotations

import datetime
import itertools
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path("/share/hec-db-repack-20261117")
REQUEST = ROOT / "REQUEST.json"
STATUS = ROOT / "repack-status.json"
SNAPSHOT = ROOT / "full-original.sqlite"
CANDIDATE = ROOT / "lossless-candidate.sqlite"
COMPLETED = ROOT / "COMPLETED.json"


def report(state, **facts):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"status": state,
               "at": datetime.datetime.now(datetime.timezone.utc).isoformat(), **facts}
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    os.replace(tmp, STATUS)
    print(json.dumps({"lossless_db_repack": payload}, ensure_ascii=False), flush=True)
    return payload


def verify(db):
    if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise ValueError("REPACK_QUICK_CHECK_FAILED")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("REPACK_FK_CHECK_FAILED")


def count_frontier(db):
    tables = [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    out = {table: db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
           for table in tables}
    for t, col in (("journal_transport_outbox", "seq"),
                   ("journal_transport_receipts", "seq"),
                   ("ram_control_samples", "rowid"),
                   ("soc_decisions", "rowid"),
                   ("priority_samples", "rowid"),
                   ("night_samples", "rowid")):
        if t in out:
            out[t + ".max"] = db.execute(
                'SELECT MAX(' + col + ') FROM "' + t + '"').fetchone()[0]
    return out


def snapshot_original(source):
    if SNAPSHOT.exists():
        # Never overwrite an original snapshot of a previous attempt.
        raise RuntimeError("ORIGINAL_REPACK_SNAPSHOT_ALREADY_EXISTS")
    pending = ROOT / "original-pending.sqlite"
    pending.unlink(missing_ok=True)
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    dst = sqlite3.connect(pending, timeout=20)
    try:
        src.backup(dst, pages=4096, sleep=.05)
        verify(dst)
    finally:
        dst.close()
        src.close()
    pending.chmod(0o600)
    with pending.open("rb") as file:
        os.fsync(file.fileno())
    os.replace(pending, SNAPSHOT)
    return SNAPSHOT.stat().st_size


def compare_all(original, compacted):
    a = sqlite3.connect(SNAPSHOT.as_uri() + "?mode=ro&immutable=1", uri=True)
    b = sqlite3.connect(compacted.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        verify(a)
        verify(b)
        schema = """SELECT type,name,tbl_name,sql FROM sqlite_master
                  WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"""
        if a.execute(schema).fetchall() != b.execute(schema).fetchall():
            raise ValueError("REPACK_SCHEMA_MISMATCH")
        if count_frontier(a) != count_frontier(b):
            raise ValueError("REPACK_COUNT_OR_CURSOR_MISMATCH")
        checked = {}
        for (table,) in a.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            # SQLite VACUUM can reassign hidden rowids; we reject this for ALL
            # tables (not just RAM cursors) to preserve unknown dependencies.
            query = 'SELECT rowid,* FROM "' + table + '" ORDER BY rowid'
            count = 0
            for old, new in itertools.zip_longest(a.execute(query), b.execute(query)):
                if old != new:
                    raise ValueError("REPACK_ROW_OR_PAYLOAD_CHANGED:" + table)
                count += 1
            checked[table] = count
        return checked
    finally:
        a.close()
        b.close()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def swap_candidate(source, frontier):
    # The caller has already stopped ALL addon writers. If source moved
    # since the snapshot was created, abort before touching its live file.
    live = sqlite3.connect(source, timeout=20)
    try:
        live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        verify(live)
        if count_frontier(live) != frontier:
            raise RuntimeError("REPACK_SOURCE_FRONTIER_MOVED")
    finally:
        live.close()
    ready = source.with_name(source.name + ".repack-ready")
    ready.unlink(missing_ok=True)
    shutil.copyfile(CANDIDATE, ready)
    ready.chmod(0o600)
    with ready.open("rb") as f:
        os.fsync(f.fileno())

    # Original committed DB remains safely on /share. No leftover writer
    # can access source after the startup pre-worker stage.
    for suffix in ("-wal", "-shm"):
        Path(str(source) + suffix).unlink(missing_ok=True)
    os.replace(ready, source)
    sync_dir(source.parent)
    try:
        actual = sqlite3.connect(source, timeout=20)
        try:
            verify(actual)
            if count_frontier(actual) != frontier:
                raise RuntimeError("REPACK_POST_SWAP_CURSOR_MISMATCH")
        finally:
            actual.close()
    except BaseException:
        # Reconstruct exact original DB from a verified immutable snapshot.
        restore = source.with_name(source.name + ".repack-rollback")
        shutil.copyfile(SNAPSHOT, restore)
        restore.chmod(0o600)
        with restore.open("rb") as f:
            os.fsync(f.fileno())
        for suffix in ("-wal", "-shm"):
            Path(str(source) + suffix).unlink(missing_ok=True)
        os.replace(restore, source)
        sync_dir(source.parent)
        raise


def run(source):
    if not REQUEST.exists():
        return {"status": "no_request"}
    request = json.loads(REQUEST.read_text())
    if request != {"action": "repack_lossless", "mode": "observe_only",
                   "expected_release": "0.6.36"}:
        raise ValueError("INVALID_REPACK_REQUEST")
    if COMPLETED.exists():
        return {"status": "already_completed"}
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError("REPACK_ACTIVE_DATABASE_MISSING")
    if SNAPSHOT.exists():
        # An interrupted previous attempt must be diagnosed, not silently
        # retried with an out-of-date recovery snapshot.
        raise RuntimeError("REPACK_UNFINISHED_PREVIOUS_ATTEMPT")
    started = time.monotonic()
    try:
        report("starting", original_bytes=source.stat().st_size)
        snapshot_size = snapshot_original(source)
        report("snapshot_verified", original_bytes=snapshot_size)
        if CANDIDATE.exists():
            CANDIDATE.unlink()
        old = sqlite3.connect(SNAPSHOT.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            old.execute("VACUUM INTO ?", (str(CANDIDATE),))
        finally:
            old.close()
        CANDIDATE.chmod(0o600)
        report("vacuum_ready", original_bytes=snapshot_size,
               candidate_bytes=CANDIDATE.stat().st_size)
        counts = compare_all(SNAPSHOT, CANDIDATE)
        frontier = sqlite3.connect(SNAPSHOT.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            summary = count_frontier(frontier)
        finally:
            frontier.close()
        report("all_rows_verified", tables=len(counts), rows=sum(counts.values()),
               original_bytes=snapshot_size, candidate_bytes=CANDIDATE.stat().st_size)
        swap_candidate(source, summary)
        output = {"status": "completed",
                  "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "before_bytes": snapshot_size, "after_bytes": source.stat().st_size,
                  "saved_bytes": snapshot_size-source.stat().st_size,
                  "verified_tables": len(counts), "verified_rows": sum(counts.values()),
                  "duration_seconds": round(time.monotonic()-started, 1)}
        COMPLETED.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        report("completed", **output)
        REQUEST.rename(ROOT / "REQUEST.completed.json")
        CANDIDATE.unlink(missing_ok=True)
        return output
    except BaseException as error:
        report("failed", error_code=type(error).__name__,
               error_message=str(error)[:150])
        raise
