"""Native hot backups: a verified online snapshot, without stopping the controller.

Raw SQLite files remain in native archives as the stopped-app fallback. A hot
archive additionally contains native-backup.zip. Only the live installation
has the excluded native-backup-source-id sentinel: restarting it must NEVER
roll its database back to the snapshot. A restored archive lacks that sentinel
and restores the validated snapshot before any worker opens SQLite.
"""
from __future__ import annotations
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
from .core import VERSION

BUNDLE = "native-backup.zip"
SENTINEL = "native-backup-source-id"
MAX_DATABASE = 9 * 1024**3

def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

@contextmanager
def lock(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".native-backup.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield

def checked_copy(source, target, deadline):
    """Bounded, incremental SQLite online backup; no application writer lock."""
    def progress(*_):
        if time.monotonic() > deadline:
            raise TimeoutError("NATIVE_BACKUP_DEADLINE")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=.25)) as src:
        with closing(sqlite3.connect(target, timeout=.25)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=.02)
            dst.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("NATIVE_BACKUP_INTEGRITY_FAILED")
            if dst.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("NATIVE_BACKUP_FOREIGN_KEY_FAILED")
            dst.execute("PRAGMA journal_mode=DELETE")
    target.chmod(0o600)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())

def _prepare_snapshot(root=Path("/data"), database=None, timeout=90):
    root = Path(root)
    database = Path(database) if database else root / "evidence/evidence.sqlite"
    if not database.is_file():
        raise FileNotFoundError("NATIVE_BACKUP_SOURCE_MISSING")
    deadline = time.monotonic() + timeout
    # WAL may hold the newest pages; size alone is only a conservative
    # resource guard, never a freshness or integrity assertion.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        size = src.execute("PRAGMA page_count").fetchone()[0] * src.execute("PRAGMA page_size").fetchone()[0]
    if size > MAX_DATABASE or shutil.disk_usage(root).free < 2 * size + 64 * 1024**2:
        raise RuntimeError("NATIVE_BACKUP_SPACE_REQUIRED")
    generation = uuid.uuid4().hex
    # An atomic bundle contains both manifest and DB, preventing torn pairs.
    with tempfile.TemporaryDirectory(prefix=".native-backup-", dir=root) as work:
        work = Path(work)
        snapshot = work / "evidence.sqlite"
        checked_copy(database, snapshot, deadline)
        manifest = {"format": "sqlite-online-v1", "generation": generation,
                    "software_version": VERSION,
                    "snapshot_completed_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": sha256(snapshot), "bytes": snapshot.stat().st_size,
                    "scope": "committed SQLite evidence; not volatile controller RAM"}
        pending = work / BUNDLE
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(snapshot, "evidence.sqlite")
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        with pending.open("rb") as stream:
            os.fsync(stream.fileno())
        # Sentinel is deliberately excluded from the native archive.
        marker = work / SENTINEL
        marker.write_text(generation)
        with marker.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(marker, root / SENTINEL)
        os.replace(pending, root / BUNDLE)
        sync_dir(root)
    return manifest

def prepare(root=Path('/data'),database=None,timeout=90):
    from . import native_backup_holder as holder
    root=Path(root);database=Path(database)if database else root/'evidence/evidence.sqlite'
    with lock(root):
        if not database.is_file():raise FileNotFoundError('NATIVE_BACKUP_SOURCE_MISSING')
        handle=holder.start(root,database)
        try:return _prepare_snapshot(root,database,timeout)
        except BaseException:
            holder.stop(root)
            raise


def finish(root=Path("/data")):
    root = Path(root)
    with lock(root):
        from . import native_backup_holder as holder
        lost=(root/holder.LEASE).exists() and not holder.active(root)
        holder.stop(root)
        # After tar completion the running installation needs no stale snapshot.
        # Remove bundle FIRST: a crash must never leave bundle without sentinel.
        (root / BUNDLE).unlink(missing_ok=True)
        sync_dir(root)
        (root / SENTINEL).unlink(missing_ok=True)
        sync_dir(root)
        if lost:raise RuntimeError('NATIVE_BACKUP_HOLDER_LOST_BEFORE_FINISH')

def restore(root=Path("/data"), database=None, timeout=90):
    root = Path(root)
    database = Path(database) if database else root / "evidence/evidence.sqlite"
    with lock(root):
        bundle = root / BUNDLE
        sentinel = root / SENTINEL
        if not bundle.exists():
            return {"status": "no_native_snapshot"}
        if sentinel.exists():
            # Even a crash/restart midway through a backup cannot rewind live DB.
            if not database.is_file():
                raise RuntimeError("NATIVE_BACKUP_LIVE_DATABASE_MISSING")
            return {"status": "live_installation_snapshot_not_restored"}
        deadline = time.monotonic() + timeout
        with tempfile.TemporaryDirectory(prefix=".native-backup-", dir=root) as work:
            work = Path(work)
            with zipfile.ZipFile(bundle) as archive:
                if set(archive.namelist()) != {"evidence.sqlite", "manifest.json"}:
                    raise ValueError("NATIVE_BACKUP_INVALID_MEMBERS")
                if archive.getinfo("manifest.json").file_size > 16384:
                    raise ValueError("NATIVE_BACKUP_INVALID_MANIFEST")
                manifest = json.loads(archive.read("manifest.json"))
                if (manifest.get("format") != "sqlite-online-v1" or
                    not isinstance(manifest.get("generation"), str) or
                    len(manifest["generation"]) != 32 or
                    any(c not in "0123456789abcdef" for c in manifest["generation"])):
                    raise ValueError("NATIVE_BACKUP_INVALID_MANIFEST")
                size = archive.getinfo("evidence.sqlite").file_size
                if size != manifest.get("bytes") or not 0 < size <= MAX_DATABASE:
                    raise ValueError("NATIVE_BACKUP_INVALID_SIZE")
                if shutil.disk_usage(root).free < 3 * size + 64 * 1024**2:
                    raise RuntimeError("NATIVE_RESTORE_SPACE_REQUIRED")
                snapshot = work / "evidence.sqlite"
                with archive.open("evidence.sqlite") as source, snapshot.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
            if sha256(snapshot) != manifest.get("sha256"):
                raise ValueError("NATIVE_BACKUP_HASH_MISMATCH")
            validated = work / "validated.sqlite"
            checked_copy(snapshot, validated, deadline)
            database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            originals = root / "native-restore-original" / manifest["generation"]
            originals.mkdir(parents=True, exist_ok=True, mode=0o700)
            for suffix in ("", "-wal", "-shm", "-journal"):
                old = Path(str(database) + suffix)
                saved = originals / old.name
                if old.exists() and not saved.exists():
                    shutil.copy2(old, saved)
                    with saved.open("rb") as stream:
                        os.fsync(stream.fileno())
            sync_dir(originals)
            # No workers exist yet. A crash before completion retries the same
            # verified bundle; original files have already been preserved.
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(database) + suffix).unlink(missing_ok=True)
            os.replace(validated, database)
            sync_dir(database.parent)
            # Keep bundle until installation is marked live; next start skips it.
            sentinel.write_text(manifest["generation"])
            with sentinel.open("rb") as stream:
                os.fsync(stream.fileno())
            sync_dir(root)
            return {"status": "restored_native_snapshot", **manifest}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "finish", "restore"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        os.nice(10)
    except OSError:
        pass
    print(json.dumps({"native_backup": {"prepare": prepare, "finish": finish, "restore": restore}[args.action]()},
                     sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
