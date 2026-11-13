"""Lossless, content-addressed sharing of immutable priority session snapshots.

Priority samples must hydrate to the same original JSON for audit, phase budgets
and historical replay. No public payload, no device control.
"""
from .core import digest
from .store import pack, unpack

FORMAT = "priority-session-deduplicated-v1"
TABLE = "priority_sample_parts"

def schema(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS priority_sample_parts"
        "(hash TEXT PRIMARY KEY,field TEXT NOT NULL,payload BLOB NOT NULL)"
    )

def prepare(sample, original=None):
    original=original if original is not None else pack(sample)
    session=sample.get("session") if isinstance(sample,dict) else None
    if not isinstance(session,dict):
        return original,()
    value=pack(session)
    if len(value)<160:
        return original,()
    key=digest({"field":"session","value":session})
    inline=dict(sample)
    inline.pop("session")
    compact=pack({"storage_format":FORMAT,"inline":inline,"refs":{"session":key}})
    if len(compact)>=len(original)-128:
        return original,()
    return compact,((key,"session",value),)

def store_parts(db,parts):
    for key,field,blob in parts:
        old=db.execute("SELECT field,payload FROM priority_sample_parts WHERE hash=?",(key,)).fetchone()
        if old is None:
            db.execute("INSERT INTO priority_sample_parts VALUES(?,?,?)",(key,field,blob))
        elif old!=(field,blob):
            raise ValueError("PRIORITY_SAMPLE_PART_HASH_CONFLICT")

def encoded(db,sample):
    """Call within the same writer transaction as INSERT priority_samples."""
    raw,parts=prepare(sample)
    if parts:
        schema(db)
        store_parts(db,parts)
    return raw

def read(db,blob):
    value=unpack(blob)
    if not isinstance(value,dict):
        raise ValueError("PRIORITY_SAMPLE_INVALID")
    if value.get("storage_format")!=FORMAT:
        return value
    inline=value.get("inline");refs=value.get("refs")
    if not isinstance(inline,dict)or not isinstance(refs,dict)or set(refs)!={"session"}:
        raise ValueError("PRIORITY_SAMPLE_INVALID_ENVELOPE")
    if "session" in inline or "at" not in inline or "day" not in inline:
        raise ValueError("PRIORITY_SAMPLE_INVALID_INLINE")
    ref=refs["session"]
    row=db.execute("SELECT field,payload FROM priority_sample_parts WHERE hash=?",(ref,)).fetchone()
    if not row or row[0]!="session":
        raise ValueError("PRIORITY_SAMPLE_MISSING_SESSION")
    session=unpack(row[1])
    if digest({"field":"session","value":session})!=ref:
        raise ValueError("PRIORITY_SAMPLE_SESSION_HASH_MISMATCH")
    return {**inline,"session":session}
