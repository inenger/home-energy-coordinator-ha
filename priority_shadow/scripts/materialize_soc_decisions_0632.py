#!/usr/bin/env python3
"""Offline-only compatible downgrade copy. Never edits the source SQLite database.

Produce a new complete SQLite backup with compact SOC decisions materialized
to their original zlib canonical format, for a carefully supervised rollback.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from energy.soc_evidence import verify
from energy.soc_storage import read
from energy.store import pack,unpack


def materialize(source,output):
    source=Path(source).resolve()
    output=Path(output).resolve()
    if source==output or output.exists():
        raise ValueError('Refusing to overwrite source or existing output')
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    original=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    original.execute('PRAGMA query_only=ON')
    result=sqlite3.connect(output)
    try:
        original.backup(result)
        changed=0
        for at,declared_hash,blob in result.execute(
                'SELECT at,hash,payload FROM soc_decisions ORDER BY at'):
            candidate=unpack(blob)
            if candidate.get('storage_format')!='soc-deduplicated-fields-v1':
                continue
            reconstructed=read(result,blob)
            if reconstructed.get('decision_hash_schema'):
                if not verify(reconstructed)['verified'] or reconstructed['decision_hash']!=declared_hash:
                    raise ValueError('Unsafe materialization: SOC decision integrity')
            with result:
                result.execute('UPDATE soc_decisions SET payload=? WHERE at=?',(pack(reconstructed),at))
            changed+=1
        if result.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise ValueError('SQLite quick_check failed on downgrade copy')
        if result.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Foreign key check failed on downgrade copy')
        for at,declared_hash,blob in result.execute('SELECT at,hash,payload FROM soc_decisions'):
            d=unpack(blob)
            if d.get('decision_hash_schema') and (
                not verify(d)['verified'] or d.get('decision_hash')!=declared_hash):
                raise ValueError('Post-materialization decision/hash mismatch')
        result.close()
        original.close()
        return {'rows_materialized':changed,'result':'verified_offline_copy'}
    except BaseException:
        result.close()
        original.close()
        output.unlink(missing_ok=True)
        raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    dest=Path(a.output).resolve()
    if not str(dest).startswith('/share/hec-recovery/'):
        raise ValueError('Rollback copy must stay in private /share/hec-recovery')
    print(json.dumps(materialize(a.source,a.output),sort_keys=True))


if __name__=='__main__':
    main()
