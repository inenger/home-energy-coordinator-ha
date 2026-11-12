"""Regression for truly lossless SOC storage dedup (0.6.32).

This is never an actuator test. Check semantic identity, hash, time lease,
collision, revoked plan and missing shared parts without touching RPi live DB.
"""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

from energy.core import digest
from energy.soc_evidence import verify
from energy.soc_runtime import record_decision,session_plan,schema
from energy.soc_storage import prepare,read
from energy.store import Store,pack


BASE=datetime(2026,11,11,2,55,tzinfo=timezone.utc)
DAY='2026-11-11'


def large_plan(at):
    # Slightly varying yet mostly repeated real-style version inventory.
    versions={'solar':[{'available_at':'2026-11-11T01:00:00+00:00',
                         'hash':str(i),
                         'payload':{'forecast':[{'start':j,'estimate':(i*11+j*7)%130/10,
                                                 'quality':'observed'} for j in range(128)]}}
                        for i in range(8)],
              'tariff':[{'available_at':'2026-11-11T01:00:00+00:00',
                         'payload':{'price':1.8078,'period':j}} for j in range(48)]}
    return {'issued_at':at.isoformat(),'day':DAY,'status':'conditional_shadow_plan',
            'horizon_complete':True,'target_soc_pct':80,
            'forecast_versions':versions,
            'calibration_summary':{'pv_models':{str(i):i*.001 for i in range(100)}},
            'calibration_context':{'evidence':['constant']*500},
            'house_validation':{'accepted':False,'samples':128},
            'battery_energy_model':{'curve':[[i,i/100]for i in range(201)]},
            'history_source':{'model':'history-v1'},
            'assumptions':{'source':'shadow','control_approved':False},
            'policy':'test-no-actions','device_actions':0}


class SharedSocStorage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'decision.sqlite')
        schema(self.store.db)
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_reconstructs_exact_original_and_saved_decision_hash(self):
        p=large_plan(BASE)
        saved=record_decision(self.store,p)
        blob=self.store.db.execute('SELECT payload FROM soc_decisions').fetchone()[0]
        self.assertNotEqual(blob,pack(saved))
        hydrated=read(self.store.db,blob)
        self.assertEqual(pack(hydrated),pack(saved))
        self.assertTrue(verify(hydrated)['verified'])
        self.assertEqual(session_plan(self.store,DAY,(BASE+timedelta(seconds=3)).isoformat()),saved)
        self.assertIsNone(session_plan(self.store,DAY,(BASE+timedelta(minutes=31)).isoformat()))

    def test_duplicates_share_immutable_objects_and_keep_original_protocol(self):
        saved=[]
        for index in range(15):
            saved.append(record_decision(self.store,large_plan(BASE+timedelta(minutes=index))))
        rows=list(self.store.db.execute('SELECT hash,payload FROM soc_decisions ORDER BY at'))
        objects=list(self.store.db.execute('SELECT hash,field,payload FROM soc_decision_parts'))
        self.assertEqual(len(rows),15)
        self.assertLess(len(objects),len(rows)*3)
        original_bytes=sum(len(pack(x)) for x in saved)
        compact_bytes=sum(len(x[1]) for x in rows)+sum(len(x[2]) for x in objects)
        self.assertLess(compact_bytes,original_bytes*.7)
        for (key,blob),original in zip(rows,saved):
            reread=read(self.store.db,blob)
            self.assertEqual(reread,original)
            self.assertEqual(key,reread['decision_hash'])
            self.assertTrue(verify(reread)['verified'])
        self.assertEqual(record_decision(self.store,large_plan(BASE)),saved[0])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM soc_decision_parts').fetchone()[0],len(objects))

    def test_legacy_uncompacted_and_same_timestamp_conflicts(self):
        small={'day':DAY,'issued_at':BASE.isoformat(),'status':'waiting_for_inputs','target_soc_pct':None}
        saved=record_decision(self.store,small)
        blob=self.store.db.execute('SELECT payload FROM soc_decisions').fetchone()[0]
        self.assertEqual(blob,pack(saved))
        self.assertEqual(read(self.store.db,blob),saved)
        with self.assertRaisesRegex(ValueError,'SOC_DECISION_TIMESTAMP_CONFLICT'):
            record_decision(self.store,{**small,'reason':'different'})
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM soc_decisions').fetchone()[0],1)
        self.assertTrue(self.store.db.execute('SELECT 1 FROM soc_decision_revocations').fetchone())

    def test_corrupt_or_missing_part_fails_closed(self):
        record_decision(self.store,large_plan(BASE))
        blob=self.store.db.execute('SELECT payload FROM soc_decisions').fetchone()[0]
        key=self.store.db.execute('SELECT hash FROM soc_decision_parts LIMIT 1').fetchone()[0]
        with self.store.db:self.store.db.execute('DELETE FROM soc_decision_parts WHERE hash=?',(key,))
        with self.assertRaisesRegex(ValueError,'SOC_PART_MISSING_OR_WRONG_FIELD'):
            read(self.store.db,blob)
        self.assertIsNone(session_plan(self.store,DAY,(BASE+timedelta(seconds=2)).isoformat()))

    def test_atomic_object_and_decision_rollback(self):
        # Inject failure after object inserts, before the decision row.
        from energy.soc_storage import store_objects
        def break_after_parts(db,parts):
            store_objects(db,parts)
            raise RuntimeError('injected intermediate storage failure')
        with patch('energy.soc_runtime.store_decision_parts',side_effect=break_after_parts):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                record_decision(self.store,large_plan(BASE))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM soc_decisions').fetchone()[0],0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM soc_decision_parts').fetchone()[0],0)

    def test_offline_downgrade_copy_reconstructs_old_reader_format(self):
        from scripts.materialize_soc_decisions_0632 import materialize
        saved=record_decision(self.store,large_plan(BASE))
        source=Path(self.temp.name)/'decision.sqlite'
        output=Path(self.temp.name)/'downgrade.sqlite'
        result=materialize(source,output)
        self.assertEqual(result['rows_materialized'],1)
        old=sqlite3.connect(output)
        from energy.store import unpack
        blob=old.execute('SELECT payload FROM soc_decisions').fetchone()[0]
        self.assertEqual(unpack(blob),saved)
        self.assertTrue(verify(unpack(blob))['verified'])
        self.assertEqual(old.execute('PRAGMA quick_check').fetchone()[0],'ok')
        old.close()
        # Original SQLite remains compact; the conversion is a new file.
        self.assertNotEqual(self.store.db.execute('SELECT payload FROM soc_decisions').fetchone()[0],blob)

    def test_individual_sha_part_integrity(self):
        record_decision(self.store,large_plan(BASE))
        key,name,packed=self.store.db.execute('SELECT * FROM soc_decision_parts LIMIT 1').fetchone()
        with self.store.db:self.store.db.execute('UPDATE soc_decision_parts SET payload=? WHERE hash=?',(pack('altered'),key))
        blob=self.store.db.execute('SELECT payload FROM soc_decisions').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'SOC_PART_HASH_MISMATCH'):
            read(self.store.db,blob)


if __name__=='__main__':
    unittest.main()
