"""Regrese uzavření neúplné noci, restartu a pokračující publikace."""
import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from energy import priority, night, priority_observer as observer, publish_status
from energy.store import Store, pack, unpack
from energy.soc_runtime import schema as soc_schema
from test_instant_fill import points
from test_night import state

AT='2026-01-15T02:59:45+00:00'
NEXT='2026-01-16T02:00:00+00:00'

def states(at, missing=()):
    mapping={**night.IDS, **priority.EXTRA}
    out=[state(mapping[k], p['value'], at) for k,p in points().items() if k in mapping and k not in missing]
    return out+[state(priority.HELPER, 'Elektromobil', at)]

def seed(store):
    night.ensure_schema(store.db); soc_schema(store.db)
    model={'discharge_curve':[[0,0],[50,5],[100,10]],'dc_cycle_efficiency':.9,'grid_efficiency':.9,'source_hash':'synthetic'}
    with store.db:
        store.db.execute('INSERT INTO soc_model_versions VALUES(?,?,?)',('synthetic','2026-01-14T20:00:00+00:00',pack({'at':'2026-01-14T20:00:00+00:00','battery_model':model})))

class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'e.sqlite'
        self.store=Store(self.path); seed(self.store)
    def tearDown(self):
        self.store.close(); self.tmp.cleanup()
    def observe(self, missing=()):
        return priority.observe(self.store,states(AT,missing),AT,True,allocation_policy='instant-max-fill-v1')
    def test_incomplete_phase_uses_identity_and_keeps_unknown(self):
        self.observe(('grid_l1_a',))
        result=priority.finish(self.store,'2026-01-15')
        self.assertIsNone(result['phase_max_measured_a']['L1'])
        self.assertGreater(result['phase_max_measured_a']['L2'],0)
        self.assertEqual(result['phase_observation_counts'],{'L1':0,'L2':1,'L3':1})
        self.assertEqual(result['policy'],'instant-max-fill-v1')
        self.assertEqual(result['models']['ev']['covered_s'],0)
    def test_empty_phases_finish_and_idempotence(self):
        self.observe(('grid_l1_a','grid_l2_a','grid_l3_a'))
        first=priority.finish(self.store,'2026-01-15')
        self.assertEqual(first['phase_max_measured_a'],{'L1':None,'L2':None,'L3':None})
        self.assertEqual(priority.finish(self.store,'2026-01-15'),first)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM priority_summary_revisions').fetchone()[0],1)
    def test_legacy_summary_is_not_overwritten(self):
        self.observe(); old={'day':'2026-01-15','version':'old','immutable':True}
        with self.store.db:self.store.db.execute('INSERT INTO priority_summaries VALUES(?,?)',('2026-01-15',pack(old)))
        self.assertEqual(priority.finish(self.store,'2026-01-15'),old)
    def test_restart_catchup_then_new_night_and_publish(self):
        self.observe(('grid_l2_a',)); self.store.close(); self.store=Store(self.path)
        result=observer.observe_priority(self.store,states(NEXT),NEXT)
        self.assertEqual(result['collection_health']['status'],'ok')
        self.assertGreater(result['selected']['battery_ac_w'],0)
        self.assertIsNotNone(priority._get(self.store,'priority_summaries','2026-01-15'))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM priority_samples WHERE day=?',('2026-01-16',)).fetchone()[0],1)
        opener=MagicMock(); opener.open.return_value.__enter__.return_value.status=201
        with patch.object(publish_status.urllib.request,'build_opener',return_value=opener),patch.object(publish_status,'read_token',return_value='synthetic'):
            publish_status.publish_priority(result,{'ha_base_url':'http://example.test'})
        self.assertGreater(opener.open.call_count,5)
    def test_one_failed_summary_does_not_block_next_cycle_or_night(self):
        self.observe()
        with patch.object(priority,'finish',side_effect=ValueError('synthetic')):
            result=observer.observe_priority(self.store,states(NEXT),NEXT)
        self.assertEqual(result['collection_health']['status'],'degraded')
        self.assertEqual(result['collection_health']['summary_errors'],[{'day':'2026-01-15','error_code':'ValueError'}])
        self.assertGreater(result['selected']['battery_ac_w'],0)
        again=observer.observe_priority(self.store,states('2026-01-16T02:00:15+00:00'),'2026-01-16T02:00:15+00:00')
        self.assertGreater(again['progress']['models']['ev']['covered_s'],0)
        self.assertEqual(again['collection_health']['status'],'ok')
    def test_failure_monitor_exposes_last_success_without_old_power(self):
        result=observer.failure_result('2026-01-15T03:00:00+00:00',ValueError('private text'),AT)
        self.assertEqual(result['at'],AT)
        self.assertIsNone(result['selected']['battery_ac_w'])
        self.assertEqual(result['collection_health']['error_code'],'ValueError')
        self.assertNotIn('private text',json.dumps(result))
        opener=MagicMock(); opener.open.return_value.__enter__.return_value.status=201
        with patch.object(publish_status.urllib.request,'build_opener',return_value=opener),patch.object(publish_status,'read_token',return_value='synthetic'):
            publish_status.publish_priority_failure(result,{'ha_base_url':'http://example.test'})
        reqs=[c.args[0] for c in opener.open.call_args_list]
        self.assertTrue(all(r.full_url.rsplit('/',1)[-1] in publish_status.IDS for r in reqs))
        self.assertTrue(all(json.loads(r.data)['state']=='unknown' for r in reqs[1:]))
        self.assertFalse(any('nocni_stinovy_souhrn' in r.full_url for r in reqs))
