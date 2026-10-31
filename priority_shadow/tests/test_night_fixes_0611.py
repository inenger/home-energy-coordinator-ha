"""Celé cesty oprav C01–C03; všechny podklady jsou syntetické."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from energy import priority,night,ram_control as c,journal_transport as transport,publish_status as pub,priority_observer as obs
from energy.collector import ReadOnlyHA
from energy.storage import sqlite_bytes
from energy.core import forecast_payloads
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
class FixTests(unittest.TestCase):
 def test_scalar_update_between_rest_and_template_keeps_complete_input(self):
  before=data(stamp(10));after=copy.deepcopy(before);eid=night.IDS['grid_l1_w']
  for row in after:
   if row['entity_id']==eid:row['state']=str(float(row['state'])-1);row['last_updated']=stamp(11);row['last_reported']=stamp(11)
  rows=[{**s,'context':s.get('context',{}),'report_source':'ha_live_state_template'}for s in after]
  client=ReadOnlyHA()
  with patch.object(client,'get',return_value=before),patch.object(client,'_query',return_value=json.dumps(rows))as query:joined=client.priority_states()
  template=query.call_args.args[1]['template'];self.assertIn('s.attributes.get',template);self.assertIn('s.context.user_id',template);self.assertNotIn('now()',template)
  with tempfile.TemporaryDirectory()as tmp:
   store=Store(Path(tmp)/'evidence.sqlite')
   try:
    c.observe(store,data(stamp(0)),result(stamp(0)));c.observe(store,data(stamp(5)),result(stamp(5)));v=c.observe(store,joined,result(stamp(12)));transport.enqueue(store,v)
    self.assertGreater(v['session']['target_ac_w'],0);self.assertFalse(v['recent_samples'][0]['input_errors']);self.assertFalse(any(unpack(p)['kind']=='would_stop_charge'for p, in store.db.execute('SELECT payload FROM ram_control_events')))
   finally:store.close()
 def test_missing_and_unavailable_are_not_unit_mismatch(self):
  self.assertEqual(priority.checked_points([],stamp(0))['grid_l1_w']['quality'],'missing')
  row=next(s for s in data()if s['entity_id']==night.IDS['grid_l1_w']);row['state']='unavailable';row['attributes']={}
  self.assertEqual(priority.checked_points([row],stamp(0))['grid_l1_w']['quality'],'unavailable')
  row['state']='100';row['attributes']['unit_of_measurement']='A';self.assertEqual(priority.checked_points([row],stamp(0))['grid_l1_w']['quality'],'unit_mismatch')
 def test_complex_forecast_race_retries_without_losing_scalars(self):
  eid=night.IDS['forecast_today'];rest={'entity_id':eid,'state':'10','attributes':{'unit_of_measurement':'kWh','detailedForecast':[{'pv_estimate':1}]},'last_updated':stamp(0),'last_reported':stamp(0)}
  live={**rest,'state':'11','last_updated':stamp(5),'last_reported':stamp(5),'context':{},'report_source':'ha_live_state_template'}
  client=ReadOnlyHA();correct={**rest,'state':'11','last_updated':stamp(5)}
  with patch.object(client,'get',side_effect=[[rest],[correct]])as get,patch.object(client,'_query',return_value=json.dumps([live])):out=client.priority_states()
  self.assertEqual(get.call_count,2);self.assertNotIn('snapshot_error',out[0]);self.assertEqual(out[0]['attributes']['detailedForecast'],rest['attributes']['detailedForecast'])
 def test_unresolved_forecast_race_is_explicit_and_never_archived(self):
  eid=night.IDS['forecast_today'];rest={'entity_id':eid,'state':'10','attributes':{'unit_of_measurement':'kWh'},'last_updated':stamp(0),'last_reported':stamp(0)};live={**rest,'state':'11','last_updated':stamp(5),'context':{},'report_source':'ha_live_state_template'}
  client=ReadOnlyHA()
  with patch.object(client,'get',return_value=[rest]),patch.object(client,'_query',return_value=json.dumps([live])):out=client.priority_states()
  self.assertEqual(night.point(out[0],stamp(10))['quality'],'snapshot_race');self.assertEqual(list(forecast_payloads(out)),[])
 def test_malformed_atomic_metadata_rejected(self):
  client=ReadOnlyHA();row={**data()[0],'report_source':'ha_live_state_template','context':{}}
  for change in ({'attributes':None},{'context':None}):
   with patch.object(client,'get',return_value=data()),patch.object(client,'_query',return_value=json.dumps([{**row,**change}])):self.assertRaises(ValueError,client.priority_states)
 def test_sqlite_sidecar_disappears_but_database_remains_required(self):
  with tempfile.TemporaryDirectory()as tmp:
   folder=Path(tmp);(folder/'evidence.sqlite').write_bytes(b'x'*20);(folder/'evidence.sqlite-wal').write_bytes(b'y'*10)
   self.assertEqual(sqlite_bytes(folder,True),30);(folder/'evidence.sqlite-wal').unlink();self.assertEqual(sqlite_bytes(folder,True),20)
   (folder/'evidence.sqlite').unlink();self.assertRaises(FileNotFoundError,sqlite_bytes,folder,True);self.assertEqual(sqlite_bytes(folder),0)
 def test_sqlite_other_io_errors_are_not_hidden(self):
  with patch.object(Path,'stat',side_effect=PermissionError('synthetic')):self.assertRaises(PermissionError,sqlite_bytes,Path('/synthetic'))
 def test_error_location_contains_no_exception_message_or_url(self):
  try:raise FileNotFoundError(2,'sensitive message','/private/evidence.sqlite-wal')
  except FileNotFoundError as error:r=obs.failure_result(stamp(5),error,stamp(0))
  h=r['collection_health'];self.assertEqual(h['error_file'],'evidence.sqlite-wal');self.assertTrue(h['error_location']);self.assertNotIn('sensitive',json.dumps(h));self.assertNotIn('/private',json.dumps(h))
 def test_controller_projection_is_versioned_and_does_not_rewrite_models(self):
  with tempfile.TemporaryDirectory()as tmp:
   st=Store(Path(tmp)/'evidence.sqlite')
   try:
    c.observe(st,data(),result());v=c.observe(st,data(stamp(5)),result(stamp(5)));original=copy.deepcopy(v['session']);rows=pub.priority_history_view([{'day':original['day'],'models':{}}],v['sessions']);self.assertEqual(rows[0]['controller']['model_scope'],'ramped_controller_shadow');self.assertEqual(v['session'],original);self.assertEqual(rows[0]['controller']['software_version'],original['software_version'])
    x=pub.priority_plan_view({'control_journal':v});self.assertEqual(x['controller']['target_ac_w'],original['target_ac_w']);self.assertEqual(x['allocation_model_scope'],'ideal_instant_allocation')
   finally:st.close()
