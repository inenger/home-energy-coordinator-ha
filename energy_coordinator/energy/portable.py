"""Portable, consistent SQLite backup for migration between Supervisor repository IDs."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, os, sqlite3

PORTABLE_DIR=Path("/share/home-energy-coordinator")
PORTABLE_DB=PORTABLE_DIR/"evidence.sqlite"
PORTABLE_META=PORTABLE_DIR/"evidence.json"

def _atomic_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    src=sqlite3.connect(f"file:{source}?mode=ro",uri=True,timeout=10)
    dst=sqlite3.connect(tmp,timeout=10)
    try:
        src.backup(dst)
        row=dst.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0]!="ok": raise RuntimeError("portable backup integrity check failed")
    finally:
        dst.close();src.close()
    os.replace(tmp,target)

def backup(source: Path, version: str) -> dict:
    if not source.exists(): return {"status":"no_database"}
    _atomic_backup(source,PORTABLE_DB)
    meta={"status":"ready","version":version,"created_at":datetime.now(timezone.utc).isoformat(),
          "bytes":PORTABLE_DB.stat().st_size,"contains_credentials":False,
          "purpose":"Home Energy Coordinator repository migration / disaster recovery"}
    tmp=PORTABLE_META.with_suffix(".tmp");tmp.write_text(json.dumps(meta,ensure_ascii=False,indent=2));os.replace(tmp,PORTABLE_META)
    return meta

def restore_if_empty(target: Path) -> dict:
    if target.exists() and target.stat().st_size>0: return {"status":"existing_database_kept"}
    if not PORTABLE_DB.exists(): return {"status":"no_portable_backup"}
    target.parent.mkdir(parents=True,exist_ok=True)
    _atomic_backup(PORTABLE_DB,target)
    return {"status":"restored","bytes":target.stat().st_size}
