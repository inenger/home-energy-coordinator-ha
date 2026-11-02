"""Independent synthetic probes; never contains real night measurements."""
import sqlite3,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from energy import ram_control as c,priority,journal_transport,publish_status,monitor_payload
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
from test_control_journal import patch_value
import test_collection_fixes_0618

class NightAuditTests(unittest.TestCase):
 def test_real_writer_contention_reaches_main_stop_outbox_and_recovery(self):
  original=c.event;errors=[];injected=[False]
  def event(db,run,at,kind,*args,**kwargs):
   if not injected[0]and kind=='would_set'and at>=stamp(20):
    path=db.execute('PRAGMA database_list').fetchone()[2]
    other=sqlite3.connect(path,timeout=.01)
    other.execute('BEGIN IMMEDIATE');injected[0]=True
    try:
     try:return original(db,run,at,kind,*args,**kwargs)
     except sqlite3.OperationalError as error:errors.append(error.sqlite_errorname);raise
    finally:other.rollback();other.close()
   return original(db,run,at,kind,*args,**kwargs)
  case=test_collection_fixes_0618.CollectionFixTests()
  with patch.object(c,'event',side_effect=event):
   run,samples,events,waits,reports,acks,chunks=case.drive()
  self.assertEqual(errors,['SQLITE_BUSY'])
  failures=[p for p in case.plans if p.get('collection_health',{}).get('status')=='failed']
  self.assertEqual(len(failures),1);self.assertEqual(failures[0]['collection_health']['error_code'],'OperationalError')
  self.assertTrue(any(e['kind']=='collection_failure'and e['reason']=='OperationalError'for e in events))
  stops=[e for e in events if e['kind']=='would_stop_charge'];self.assertTrue(stops)
  self.assertTrue(any(s['ram_target_ac_w']>0 and s['at']>stops[0]['at']for s in samples))
  self.assertGreater(chunks,0);self.assertTrue(all(e['device_actions']==e['persistent_writes']==0 for e in events))

 def test_inconsistent_power_current_is_blocked_with_exact_evidence_and_recovery(self):
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite')
   try:
    for sec in (0,5):c.observe(store,data(stamp(sec)),result(stamp(sec)))
    states=data(stamp(10))
    from energy import night
    patch_value(states,night.IDS['grid_l1_a'],4);patch_value(states,night.IDS['grid_voltage_l1_v'],230);patch_value(states,night.IDS['grid_l1_w'],-980)
    journal=c.observe(store,states,result(stamp(10)))
    sample=journal['recent_samples'][0];self.assertIn('invalid_phase_input',sample['input_errors']);self.assertEqual(sample['ram_target_ac_w'],0)
    self.assertEqual(sample['input_reports']['grid_l1_w']['value'],-980)
    self.assertEqual(sample['input_reports']['grid_l1_a']['value'],4)
    self.assertNotEqual(sample['input_reports']['grid_l1_a']['entity_id'],sample['input_reports']['grid_l1_a_reported']['entity_id'])
    blocked=next(e for e in journal['recent_events']if e['kind']=='control_blocked')
    self.assertIn('grid_l1_a',blocked['allocation_missing_inputs'])
    journal['transport']=journal_transport.enqueue(store,journal)
    packets=publish_status.prepare_priority({'at':stamp(10),'selected':{},'control_journal':journal})
    self.assertTrue(all(len(monitor_payload.encoded(p['attributes']))<=14000 for _,p in packets))
    first=c.observe(store,data(stamp(15)),result(stamp(15)));self.assertEqual(first['recent_samples'][0]['ram_target_ac_w'],0)
    second=c.observe(store,data(stamp(20)),result(stamp(20)));self.assertGreater(second['recent_samples'][0]['ram_target_ac_w'],0)
   finally:store.close()
if __name__=='__main__':unittest.main()
