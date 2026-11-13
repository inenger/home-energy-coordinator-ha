"""One-shot, crash-safe offline compaction of the *true* addon data.

Runs before any EvidenceBridge/worker starts. Only with an explicit operator
request in /share. On failure do NOT replace the active SQLite database.
"""
from __future__ import annotations
import datetime,json,os,shutil,sqlite3,time,hashlib,traceback
from pathlib import Path
from .store import pack,unpack
from .core import digest
from .soc_storage import prepare as soc_prepare,store_objects,read as soc_read,FORMAT,FIELDS,MIN_RECORD_BYTES
from .priority_sample_storage import prepare as priority_prepare,store_parts as priority_store_parts,read as priority_read,schema as priority_schema

ROOT=Path("/share/hec-recovery/live-db-0633-20261113")
REQUEST=ROOT/"REQUEST.json"
SNAPSHOT=ROOT/"full-original.sqlite"
CANDIDATE=ROOT/"working-candidate.sqlite"
RESULT=ROOT/"migration-status.json"

def status(name,**more):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    out={"status":name,"at":datetime.datetime.now(datetime.timezone.utc).isoformat(),**more}
    temp=RESULT.with_suffix(".tmp")
    temp.write_text(json.dumps(out,indent=2,ensure_ascii=False))
    os.replace(temp,RESULT)
    print(json.dumps({"evidence_compaction":out},ensure_ascii=False),flush=True)
    return out

def cached_prepare(value,raw,cache):
    if len(raw)<MIN_RECORD_BYTES:
        return raw,()
    inline=dict(value);refs={};objects=[]
    for field in FIELDS:
        if field not in inline:continue
        obj=inline.pop(field)
        old=cache.get(field)
        if old is not None and old[0]==obj:
            key,packed=old[1],old[2]
        else:
            key=digest({"field":field,"value":obj})
            packed=pack(obj)
            cache[field]=(obj,key,packed)
        refs[field]=key
        objects.append((key,field,packed))
    if not objects:return raw,()
    compressed=pack({"storage_format":FORMAT,"inline":inline,"refs":refs})
    if len(compressed)>=len(raw)-512:return raw,()
    return compressed,tuple(objects)

def count_summary(db):
    result={}
    for table in ("soc_decisions","priority_samples","ram_control_samples",
                  "journal_transport_outbox","journal_transport_receipts","night_samples",
                  "soc_observations","control_evidence_batches"):
        result[table]=db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    result["ack"]=unpack(db.execute("SELECT payload FROM journal_transport_meta WHERE key='ack'").fetchone()[0])
    result["max_seq"]=db.execute("SELECT coalesce(max(seq),0) FROM journal_transport_outbox").fetchone()[0]
    return result

def _backup(source):
    if SNAPSHOT.exists():
        # A crash may leave a protected valid backup. Never overwrite it.
        x=sqlite3.connect("file:"+str(SNAPSHOT)+"?mode=ro&immutable=1",uri=True)
        try:
            if x.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                raise RuntimeError("OLD_SNAPSHOT_CORRUPTED")
        finally:x.close()
        return
    tmp=ROOT/"original-incomplete.sqlite"
    tmp.unlink(missing_ok=True)
    src=sqlite3.connect("file:"+str(source)+"?mode=ro",uri=True,timeout=15)
    dst=sqlite3.connect(tmp,timeout=15)
    try:
        src.backup(dst,pages=4096,sleep=.1)
        assert dst.execute("PRAGMA quick_check").fetchone()[0]=="ok"
        assert not dst.execute("PRAGMA foreign_key_check").fetchall()
    finally:dst.close();src.close()
    os.chmod(tmp,0o600)
    os.replace(tmp,SNAPSHOT)
    status("original_snapshot_verified",bytes=SNAPSHOT.stat().st_size)

def _migrate():
    src=sqlite3.connect("file:"+str(SNAPSHOT)+"?mode=ro&immutable=1",uri=True)
    wr=sqlite3.connect(CANDIDATE,timeout=30)
    wr.execute("PRAGMA busy_timeout=30000")
    wr.execute("PRAGMA journal_mode=DELETE")
    wr.execute("PRAGMA synchronous=FULL")
    priority_schema(wr)
    soc_stats={"seen":0,"converted":0,"already_compact":0,"small_unchanged":0}
    pri_stats={"seen":0,"converted":0,"unchanged":0}
    cache={}
    try:
        with wr:
            for rowid,at,key,blob in src.execute("SELECT rowid,at,hash,payload FROM soc_decisions ORDER BY rowid"):
                soc_stats["seen"]+=1
                d=unpack(blob)
                if not isinstance(d,dict):
                    raise ValueError("INVALID_HISTORICAL_SOC")
                if d.get("storage_format")==FORMAT:
                    soc_stats["already_compact"]+=1
                    continue
                compact,parts=cached_prepare(d,blob,cache)
                if soc_stats["seen"]<=10 or soc_stats["seen"]%127==0:
                    assert (compact,parts)==soc_prepare(d,blob),"SOC_ENCODING_CHANGED"
                if not parts:
                    soc_stats["small_unchanged"]+=1
                    continue
                store_objects(wr,parts)
                if wr.execute("UPDATE soc_decisions SET payload=? WHERE rowid=? AND hash=?",
                              (compact,rowid,key)).rowcount!=1:
                    raise ValueError("SOC_UPDATE_CONFLICT")
                soc_stats["converted"]+=1
                if soc_stats["seen"]%1000==0:
                    status("migrating_soc",count=soc_stats["seen"],total=src.execute("SELECT count(*) FROM soc_decisions").fetchone()[0])
        with wr:
            for rowid,at,blob in src.execute("SELECT rowid,at,payload FROM priority_samples ORDER BY rowid"):
                pri_stats["seen"]+=1
                d=unpack(blob)
                if not isinstance(d,dict) or d.get("at")!=at:
                    raise ValueError("INVALID_PRIORITY_SAMPLE")
                packed,parts=priority_prepare(d,blob)
                if not parts:
                    pri_stats["unchanged"]+=1
                    continue
                priority_store_parts(wr,parts)
                if wr.execute("UPDATE priority_samples SET payload=? WHERE rowid=? AND at=?",
                              (packed,rowid,at)).rowcount!=1:
                    raise ValueError("PRIORITY_UPDATE_CONFLICT")
                pri_stats["converted"]+=1
                if pri_stats["seen"]%5000==0:
                    status("migrating_priority",count=pri_stats["seen"])
        status("validating_all",soc=soc_stats,priority=pri_stats)
        # Compare every historical SOC and priority row before VACUUM.
        parts={}
        for key,field,blob in wr.execute("SELECT hash,field,payload FROM soc_decision_parts"):
            x=unpack(blob)
            assert digest({"field":field,"value":x})==key
            parts[(key,field)]=x
        for rowid,at,day,key,blob in src.execute("SELECT rowid,at,day,hash,payload FROM soc_decisions"):
            new=wr.execute("SELECT at,day,hash,payload FROM soc_decisions WHERE rowid=?",(rowid,)).fetchone()
            assert new is not None and new[:3]==(at,day,key)
            if new[3]!=blob:
                original=unpack(blob);x=unpack(new[3])
                assert x["storage_format"]==FORMAT
                assert set(x["refs"]).union(x["inline"])==set(original)
                assert not set(x["refs"]).intersection(x["inline"])
                assert all(original[k]==v for k,v in x["inline"].items())
                assert all(original[k]==parts[(h,k)] for k,h in x["refs"].items())
        for rowid,at,day,blob in src.execute("SELECT rowid,at,day,payload FROM priority_samples"):
            new=wr.execute("SELECT at,day,payload FROM priority_samples WHERE rowid=?",(rowid,)).fetchone()
            assert new is not None and new[:2]==(at,day)
            if new[2]!=blob:
                original=unpack(blob);x=priority_read(wr,new[2])
                assert x==original,"PRIORITY_SEMANTIC_MISMATCH"
        # The RAM journal's queued cursor refers to rowids. VACUUM must not
        # reassign them or the bridge could skip/duplicate samples.
        before_cursor=src.execute("SELECT at,rowid FROM ram_control_samples ORDER BY rowid").fetchall()
        before=count_summary(src)
        assert count_summary(wr)==before
        assert wr.execute("PRAGMA quick_check").fetchone()[0]=="ok"
        assert not wr.execute("PRAGMA foreign_key_check").fetchall()
        wr.execute("VACUUM")
        assert wr.execute("PRAGMA quick_check").fetchone()[0]=="ok"
        assert not wr.execute("PRAGMA foreign_key_check").fetchall()
        after_cursor=wr.execute("SELECT at,rowid FROM ram_control_samples ORDER BY rowid").fetchall()
        assert before_cursor==after_cursor,"RAM_ROWID_CURSOR_CHANGED_BY_VACUUM"
        assert count_summary(wr)==before
        assert set(x[0] for x in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).issubset(
            x[0] for x in wr.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        return soc_stats,pri_stats,before
    finally:
        wr.close();src.close()

def _apply(source):
    # No workers are running yet. Source was saved via SQLite online backup.
    # Verify still at the same logical transaction frontier; abort if not.
    old=sqlite3.connect(source,timeout=20)
    snapshot=sqlite3.connect("file:"+str(SNAPSHOT)+"?mode=ro&immutable=1",uri=True)
    try:
        old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert count_summary(old)==count_summary(snapshot),"SOURCE_MOVED_DURING_MIGRATION"
    finally:old.close();snapshot.close()
    target=source.with_name(source.name+".0633-ready")
    target.unlink(missing_ok=True)
    shutil.copyfile(CANDIDATE,target)
    os.chmod(target,0o600)
    with target.open("rb") as f:os.fsync(f.fileno())
    # Old WAL has been checkpointed while addon stopped and can be removed
    # safely. Original committed data remain in SNAPSHOT, protected on /share.
    for suffix in ("-wal","-shm"):
        Path(str(source)+suffix).unlink(missing_ok=True)
    os.replace(target,source)
    fd=os.open(source.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    try:
        test=sqlite3.connect(source)
        try:
            assert test.execute("PRAGMA quick_check").fetchone()[0]=="ok"
            assert not test.execute("PRAGMA foreign_key_check").fetchall()
        finally:test.close()
    except BaseException:
        # The most dangerous window is post-swap validation. Replace the
        # failed new file with the previously verified, immutable snapshot.
        rollback=source.with_name(source.name+".0633-rollback-ready")
        shutil.copyfile(SNAPSHOT,rollback)
        os.chmod(rollback,0o600)
        with rollback.open("rb") as f:os.fsync(f.fileno())
        for suffix in ("-wal","-shm"):
            Path(str(source)+suffix).unlink(missing_ok=True)
        os.replace(rollback,source)
        fd=os.open(source.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        raise

def run(source):
    if not REQUEST.exists():
        return {"status":"no_request"}
    if not source.exists():
        raise FileNotFoundError("ACTIVE_DB_NOT_PRESENT")
    if not ROOT.is_dir():
        raise FileNotFoundError("SHARE_ROOT_NOT_PRESENT")
    request=json.loads(REQUEST.read_text())
    if request.get("mode")!="observe_only" or request.get("action")!="compact_lossless":
        raise ValueError("INVALID_OPTIMIZATION_REQUEST")
    if (ROOT/"COMPLETED.json").exists():
        return {"status":"already_completed"}
    t=time.monotonic()
    try:
        status("starting",active_database=str(source))
        _backup(source)
        if CANDIDATE.exists():CANDIDATE.unlink()
        shutil.copyfile(SNAPSHOT,CANDIDATE)
        os.chmod(CANDIDATE,0o600)
        status("offline_copy_created",size=CANDIDATE.stat().st_size)
        soc,priority,before=_migrate()
        final_size=CANDIDATE.stat().st_size
        status("validated_and_vacuumed",size=final_size,soc=soc,priority=priority)
        _apply(source)
        out={"status":"completed","at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "source_size_bytes":SNAPSHOT.stat().st_size,"new_size_bytes":source.stat().st_size,
             "soc":soc,"priority":priority,"baseline_counts":before,
             "elapsed_seconds":round(time.monotonic()-t,2)}
        (ROOT/"COMPLETED.json").write_text(json.dumps(out,indent=2,ensure_ascii=False))
        status("completed",**out)
        REQUEST.rename(ROOT/"REQUEST.completed.json")
        # Keep original snapshot for recovery; working duplicate is disposable.
        CANDIDATE.unlink(missing_ok=True)
        return out
    except BaseException as error:
        status("failed_or_rolled_back",error=type(error).__name__,message=str(error)[:200])
        raise
