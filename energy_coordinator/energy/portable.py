"""Portable, consistent SQLite backup for migration between Supervisor repository IDs."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, os, sqlite3, hashlib, re

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

AUXILIARY_FILES=frozenset({'update.json','entity-metadata.json','metadata-attempt.json','status.json','calibration.json','analytics.json','telemetry-overrides.json'})

def _restore_auxiliary(directory):
    """Jen výslovné datové JSON soubory; žádný kód, credential ani libovolná cesta."""
    manifest=PORTABLE_DIR/'migration-aux.json'
    if not manifest.exists():return []
    doc=json.loads(manifest.read_text());files=doc.get('files')
    if doc.get('format')!='evidence-aux-v1' or not isinstance(files,dict)or not set(files)<=AUXILIARY_FILES:
        raise ValueError('Invalid auxiliary migration manifest')
    pending=[]
    for name,expected in files.items():
        if not isinstance(expected,str)or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('Invalid auxiliary hash')
        source=PORTABLE_DIR/'migration-aux'/name
        if source.is_symlink()or source.stat().st_size>32*1024*1024:raise ValueError('Invalid auxiliary source')
        content=source.read_bytes()
        if hashlib.sha256(content).hexdigest()!=expected:raise ValueError('Auxiliary migration hash mismatch')
        json.loads(content);pending.append((name,content))
    # Ověřit všechny soubory před první změnou cíle. Databáze se obnoví až nakonec.
    directory.mkdir(parents=True,exist_ok=True)
    for name,content in pending:
        target=directory/name;tmp=target.with_suffix('.migration-tmp');tmp.write_bytes(content);os.replace(tmp,target)
    receipt={'format':doc['format'],'files':files,'source':'verified_local_migration'}
    (directory/'migration-receipt.json').write_text(json.dumps(receipt,sort_keys=True))
    return sorted(files)

def restore_if_empty(target: Path) -> dict:
    if target.exists() and target.stat().st_size>0:return {'status':'existing_database_kept'}
    if not PORTABLE_DB.exists():return {'status':'no_portable_backup'}
    target.parent.mkdir(parents=True,exist_ok=True)
    restored=_restore_auxiliary(target.parent)
    _atomic_backup(PORTABLE_DB,target)
    result={'status':'restored','bytes':target.stat().st_size}
    if restored:result['auxiliary_files']=restored
    return result
