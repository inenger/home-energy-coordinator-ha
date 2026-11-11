"""Synthetic contracts: complex-attribute cache and atomic collection receipts."""
import json,time,threading,unittest,copy
from pathlib import Path
from unittest.mock import patch
from energy.collector import ReadOnlyHA
from energy.priority_collection import SnapshotCollector
from energy import night,priority
import test_live_reports
from test_ram_control import stamp

class CollectionContextTests(unittest.TestCase):
 def test_scalars_are_always_live_without_reloading_all_states(self):
  client=ReadOnlyHA();a=test_live_reports.LiveReportsTests().snapshot(stamp(0));b=copy.deepcopy(a);b[0].update(state='1000',last_reported=stamp(5))
  with patch.object(client,'get',return_value=a)as get,patch.object(client,'_query',side_effect=[json.dumps(a),json.dumps(b)])as query:
   first=client.priority_states();second=client.priority_states()
  self.assertEqual(get.call_count,1);self.assertEqual(query.call_count,2)
  self.assertEqual(first[0]['last_reported'],stamp(0));self.assertEqual(second[0]['last_reported'],stamp(5));self.assertEqual(second[0]['state'],'1000')

 def test_complex_change_requests_async_refresh_and_copies_attributes(self):
  eid=night.IDS['forecast_today']
  def row(value,at):return {'entity_id':eid,'state':str(value),'attributes':{'detailedForecast':[{'pv_estimate':value}]},'context':{},'last_updated':at,'last_reported':at,'report_source':'ha_live_state_template'}
  a=row(10,stamp(0));b=row(11,stamp(5));client=ReadOnlyHA()
  def ready():
   deadline=time.monotonic()+2
   while client._context_refreshing and time.monotonic()<deadline:time.sleep(.01)
   self.assertFalse(client._context_refreshing)
  with patch.object(client,'get',side_effect=[[a],[b]])as get,patch.object(client,'_query',side_effect=lambda *args,**kwargs:json.dumps([a]if client._query.call_count==1 else [b])):
   client.priority_context();ready()
   first=client.priority_states();first[0]['attributes']['detailedForecast'][0]['pv_estimate']=999
   second=client.priority_states();self.assertEqual(second[0]['snapshot_error'],'snapshot_race')
   ready();third=client.priority_states()
  self.assertEqual(get.call_count,2)
  self.assertEqual(third[0]['attributes']['detailedForecast'][0]['pv_estimate'],11)
  self.assertNotIn('snapshot_error',third[0])

 def test_context_refreshes_after_sixty_seconds_without_waiting_for_rest(self):
  clock=[0];client=ReadOnlyHA();rows=test_live_reports.LiveReportsTests().snapshot(stamp(0))
  def ready():
   deadline=time.monotonic()+2
   while client._context_refreshing and time.monotonic()<deadline:time.sleep(.01)
   self.assertFalse(client._context_refreshing)
  with patch('energy.collector.time.monotonic',side_effect=lambda:clock[0]),patch.object(client,'get',return_value=rows)as get,patch.object(client,'_query',return_value=json.dumps(rows)):
   client.priority_states();ready()
   clock[0]=59;client.priority_states();self.assertEqual(get.call_count,1)
   clock[0]=60;client.priority_states();ready();self.assertEqual(get.call_count,2)

 def test_collection_receipt_belongs_to_same_snapshot_and_is_not_heartbeat(self):
  entered=threading.Event();release=threading.Event()
  class Client:
   calls=0
   def priority_states(self):
    self.calls+=1
    if self.calls>1:entered.set();release.wait(1)
    return [{'entity_id':'sensor.synthetic','state':'1','last_reported':stamp(0)}]
  worker=SnapshotCollector(Client(),period=.01).start()
  try:
   first=worker.priority_states();self.assertTrue(entered.wait(1));second=worker.priority_states()
   self.assertEqual(first,second);self.assertEqual(first[0]['last_reported'],stamp(0))
   receipt=first[0]['collection_snapshot'];self.assertEqual(receipt['sequence'],1)
   self.assertLessEqual(receipt['request_started_at'],receipt['received_at'])
  finally:release.set();worker.close()

 def test_night_period_is_bounded_and_only_active_in_observation_window(self):
  worker=SnapshotCollector(None,period=2.5,night_period=1)
  self.assertEqual(worker.effective_period(stamp(0)),1)
  self.assertEqual(worker.effective_period('2026-01-15T12:00:00+00:00'),2.5)

 def test_extended_control_evidence_survives_transport_and_payload_budget(self):
  import tempfile
  from energy import ram_control as c,journal_transport,publish_status,monitor_payload
  from energy.store import Store,unpack
  from test_ram_control import data,result
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite')
   try:
    for sec in (0,5,10):
     at=stamp(sec);r=result(at);r['collection_snapshot']={'sequence':sec+1,'received_at':at,'request_started_at':at,'read_at':at}
     journal=c.observe(store,data(at),r);journal['transport']=journal_transport.enqueue(store,journal)
    self.assertIn(c.REMOTE_MODE,journal['recent_samples'][0]['owner_reports'])
    self.assertIn('ev_w',journal['recent_samples'][0]['input_reports'])
    packets=publish_status.prepare_priority({'at':at,'version':'synthetic','selected':{},'control_journal':journal})
    self.assertTrue(all(len(monitor_payload.encoded(payload['attributes']))<=14000 for _,payload in packets))
    self.assertGreater(store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0],0)
    self.assertTrue(all(len(monitor_payload.encoded(unpack(p)))<=14000 for p, in store.db.execute('SELECT payload FROM journal_transport_outbox')))
   finally:store.close()
