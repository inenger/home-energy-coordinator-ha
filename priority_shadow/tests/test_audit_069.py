"""Regrese nálezů A01–A09 přes deník, model, publisher a opakovaný přenos."""
import base64,copy,json,tempfile,unittest,zlib
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,MagicMock
from energy import ram_control as c,priority,night,publish_status as pub,journal_transport as transport,monitor_payload as monitor
from energy.store import Store,unpack,pack
from test_ram_control import data,result,stamp
from test_control_journal import patch_value
from test_night import state
class AuditTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'evidence.sqlite';self.store=Store(self.path)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def step(self,s,states=None):return c.observe(self.store,data(stamp(s))if states is None else states,result(stamp(s)))
 def ready(self):self.step(0);return self.step(5)
 def test_busy_readback_prevents_first_takeover_and_recovers_with_two_frames(self):
  for s in(0,5):
   ss=data(stamp(s));patch_value(ss,c.READBACKS[0],'Power Control Mode');v=self.step(s,ss);self.assertFalse(v['session']['owned']);self.assertEqual(v['session']['target_ac_w'],0)
  self.assertEqual(self.step(10)['session']['target_ac_w'],0);self.assertEqual(self.step(15)['session']['target_ac_w'],500)
 def test_both_owner_reports_must_be_fresh_and_known(self):
  for eid in(c.REMOTE_MODE,c.READBACKS[0]):
   for value in('Disabled','unknown','unavailable'):
    ss=data(stamp(0));row=next(x for x in ss if x['entity_id']==eid);row['state']=value;row['last_reported']='2026-01-14T02:00:00+00:00'
    self.assertTrue(c.owner_errors({x['entity_id']:x for x in ss},stamp(0)))
 def test_ev_only_and_partial_phase_reports_do_not_renew_frame(self):
  self.step(0)
  for s in(5,10):
   ss=data(stamp(0))
   for row in ss:
    if row['entity_id'].startswith('sensor.solax_api_charge_power_')or row['entity_id']==night.IDS['grid_l1_w']:row['last_reported']=stamp(s)
   v=self.step(s,ss);self.assertFalse(v['session']['owned']);self.assertEqual(v['session']['target_ac_w'],0)
  self.assertEqual(self.step(15)['session']['target_ac_w'],0) # fresh complete frame follows rejected skew
  self.assertGreater(self.step(20)['session']['target_ac_w'],0)
 def test_ramp_grid_energy_balance_and_lease_expiry(self):
  v=self.ready();a=v['session']['previous']['allocation'];target=v['session']['target_ac_w'];expected=sum(p['base_w']+p['planned_ev_w']for p in a['phase'])+target
  self.assertAlmostEqual(a['grid_model_w'],expected)
  held=data(stamp(5));self.step(10,held);self.step(15,held);v=self.step(20,held);m=v['session']['shadow_model']
  self.assertEqual(v['session']['target_ac_w'],0);self.assertAlmostEqual(m['battery_kwh_ac'],500*15/3600000);self.assertAlmostEqual(m['grid_kwh_ac'],expected*15/3600000);self.assertEqual(m['covered_s'],15)
 def test_gap_still_does_not_bridge_even_with_unexpired_old_intent(self):
  self.ready();v=self.step(14);self.assertEqual(v['session']['shadow_model']['covered_s'],0);self.assertEqual(v['session']['target_ac_w'],0)
 def test_raw_high_current_remains_visible_when_PUI_rejected(self):
  self.ready();ss=data(stamp(10));patch_value(ss,night.IDS['grid_l1_a'],30);patch_value(ss,night.IDS['grid_l1_w'],-8000);v=self.step(10,ss);stats=v['session']['statistics'];p=v['recent_samples'][0]['phase'][0]
  self.assertEqual(v['session']['target_ac_w'],0);self.assertEqual(p['actual_grid_a'],30);self.assertEqual(p['current_quality'],'unverified_phase');self.assertIsNone(p['planned_grid_a']);self.assertEqual(stats['measured_phase_max_a']['L1'],30);self.assertEqual(stats['measured_exceedance_samples'],1);self.assertGreater(stats['unverified_current_samples'],0)
 def test_missing_current_does_not_become_zero_or_prove_complete_statistics(self):
  self.ready();ss=data(stamp(10));patch_value(ss,night.IDS['grid_l2_a'],'unavailable');v=self.step(10,ss)
  self.assertIsNone(v['recent_samples'][0]['phase'][1]['actual_grid_a']);self.assertGreater(v['session']['statistics']['missing_current_phase_samples'],0)
 def test_oversize_live_publisher_is_lossless_and_bounded(self):
  v=self.ready();v['large_context']={'value':'český podklad '*5000};attrs={**v,'observed_at':stamp(5),'software_version':'synthetic','device_actions':0}
  req=pub.request(c.SENSOR,{'state':'active','attributes':attrs},'http://synthetic','synthetic');sent=json.loads(req.data)['attributes']
  self.assertLessEqual(len(monitor.encoded(sent)),14000);self.assertEqual(monitor.unpacked(sent),attrs)
  bad=copy.deepcopy(sent);bad['packed_attributes']['sha256']='0'*64
  with self.assertRaises(ValueError):monitor.unpacked(bad)
 def test_uncompressible_over_budget_is_rejected_before_any_HTTP(self):
  import random,string
  rng=random.Random(69);huge=''.join(rng.choice(string.ascii_letters)for _ in range(50000))
  with self.assertRaisesRegex(ValueError,'BUDGET'):pub.request(c.SENSOR,{'state':'active','attributes':{'huge':huge}},'http://synthetic','synthetic')
 def test_outbox_acknowledges_recorder_not_http_and_survives_restart(self):
  v=self.ready();status=transport.enqueue(self.store,v);head=status['queued_seq'];self.assertGreater(head,0)
  class Client:
   def __init__(self):self.sent=[];self.records=[];self.fail=False
   def publish(self,attrs):
    if self.fail:raise TimeoutError()
    self.sent.append(copy.deepcopy(attrs))
   def history(self,begin,end):return [[{'attributes':a}for a in self.records]]
  client=Client();worker=transport.Publisher(self.path,client);now=datetime.fromisoformat(stamp(10));worker.tick(now)
  self.assertEqual(transport.status(self.store)['recorded_seq'],0);self.assertTrue(client.sent)
  restarted=transport.Publisher(self.path,client);restarted.tick(now+timedelta(seconds=21));self.assertGreater(len(client.sent),head)
  client.records=[copy.deepcopy(a)for a in client.sent];restarted.tick(now+timedelta(seconds=22));self.assertEqual(transport.status(self.store)['recorded_seq'],head)
  n=len(client.sent);restarted.tick(now+timedelta(seconds=23));self.assertEqual(len(client.sent),n)
 def test_receipt_with_bad_payload_does_not_acknowledge(self):
  v=self.ready();transport.enqueue(self.store,v)
  class Client:
   def __init__(self):self.sent=[]
   def publish(self,a):self.sent.append(a)
   def history(self,*args):return [[{'attributes':{**a,'data':'tampered'}}for a in self.sent]]
  client=Client();worker=transport.Publisher(self.path,client);now=datetime.fromisoformat(stamp(10));worker.tick(now);worker.tick(now+timedelta(seconds=1));self.assertEqual(transport.status(self.store)['recorded_seq'],0)
 def test_session_without_new_rows_is_deduplicated_and_every_row_recoverable(self):
  v=self.ready();first=transport.enqueue(self.store,v);again=transport.enqueue(self.store,v);self.assertEqual(first['queued_seq'],again['queued_seq'])
  ss=self.step(10);transport.enqueue(self.store,ss);batches={}
  for seq,payload in self.store.db.execute('SELECT seq,payload FROM journal_transport_outbox ORDER BY seq'):
   p=unpack(payload);self.assertLess(len(monitor.encoded(p)),14000);batches.setdefault(p['batch_id'],[]).append(p)
  events={};samples={}
  for batch,parts in batches.items():
   raw=zlib.decompress(b''.join(base64.b64decode(p['data'])for p in sorted(parts,key=lambda p:p['part_index'])));self.assertEqual(__import__('hashlib').sha256(raw).hexdigest(),batch);delta=json.loads(raw)
   for e in delta['events']:events[e['id']]=e
   for s in delta['samples']:samples[s['at']]=s
  self.assertEqual(len(events),ss['session']['event_count']);self.assertEqual(len(samples),ss['session']['statistics']['sample_count'])
 def test_late_previous_day_restore_keeps_its_day_in_transport(self):
  self.ready();transport.enqueue(self.store,c.view(self.store,stamp(5),data(stamp(5))))
  at=(datetime.fromisoformat(stamp(0))+timedelta(days=1)).isoformat();v=c.observe(self.store,data(at),result(at));transport.enqueue(self.store,v)
  groups={}
  for payload, in self.store.db.execute('SELECT payload FROM journal_transport_outbox ORDER BY seq'):
   p=unpack(payload);groups.setdefault(p['batch_id'],[]).append(p)
  seen=set()
  for parts in groups.values():
   delta=json.loads(zlib.decompress(b''.join(base64.b64decode(p['data'])for p in sorted(parts,key=lambda p:p['part_index']))));day=delta['session']['day'];seen.add(day)
   self.assertTrue(all(e['day']==day for e in delta['events']));self.assertTrue(all(s['day']==day for s in delta['samples']))
  self.assertEqual(len(seen),2)
 def test_network_failure_and_recorder_timeout_are_visible_without_ack(self):
  transport.enqueue(self.store,self.ready())
  class Client:
   def __init__(self):self.fail=True;self.sent=[];self.records=[]
   def publish(self,a):
    if self.fail:raise TimeoutError('synthetic')
    self.sent.append(a)
   def history(self,*args):return[[{'attributes':p}for p in self.records]]
  client=Client();worker=transport.Publisher(self.path,client);now=datetime.fromisoformat(stamp(10));worker.tick(now);self.assertEqual(transport.status(self.store)['status'],'degraded');self.assertEqual(transport.status(self.store)['recorded_seq'],0)
  client.fail=False;worker.tick(now+timedelta(seconds=1));worker.tick(now+timedelta(seconds=40));self.assertEqual(transport.status(self.store)['error_code'],'RECORDER_CONFIRMATION_TIMEOUT');self.assertEqual(transport.status(self.store)['recorded_seq'],0)
  client.records=client.sent;worker.tick(now+timedelta(seconds=41));self.assertEqual(transport.status(self.store)['pending_chunks'],0);self.assertEqual(transport.status(self.store)['status'],'ok')
 def test_stream_client_allowlist_excludes_physical_entities(self):
  with self.assertRaises(ValueError):transport.request_parts('select.solax_charger_use_mode',{'state':'Manual Mode','attributes':{}})
 def test_phase_report_rollbacks_do_not_increase_power(self):
  self.ready();ss=data(stamp(5));v=self.step(10,ss);self.assertEqual(v['session']['target_ac_w'],500)
  ss=data(stamp(0));v=self.step(12,ss);self.assertEqual(v['session']['target_ac_w'],500);self.assertFalse(v['recent_samples'][0]['new_frame'])
 def test_receipt_range_uses_state_timestamp_not_later_ack_time(self):
  transport.enqueue(self.store,self.ready());published=[]
  class Client:
   def publish(self,a):published.append(a)
   def history(self,*args):return[[{'attributes':a,'last_updated':stamp(10)}for a in published]]
  worker=transport.Publisher(self.path,Client());worker.tick(datetime.fromisoformat(stamp(10)));worker.tick(datetime.fromisoformat(stamp(20)))
  bounds=transport.status(self.store)['days']['2026-01-15'];self.assertEqual(datetime.fromisoformat(bounds['first_recorded_at']),datetime.fromisoformat(stamp(10)))
 def test_uncompressible_payload_keeps_exact_full_evidence(self):
  import random,string
  rng=random.Random(70);attrs={'at':stamp(5),'unique':''.join(rng.choice(string.ascii_letters)for _ in range(50000))}
  try:pub.request(c.SENSOR,{'state':'active','attributes':attrs},'http://synthetic','synthetic')
  except monitor.PayloadOverflow as error:
   self.assertEqual(error.entity_id,c.SENSOR);monitor.record_overflow(self.store,error,stamp(5))
  else:self.fail('Expected visible overflow')
  row=self.store.db.execute('SELECT payload FROM monitor_overflow_evidence').fetchone();self.assertEqual(unpack(row[0]),attrs)
 def test_internal_journal_failure_reaches_main_fail_closed_path(self):
  from energy import priority_observer as obs
  from datetime import datetime
  import contextlib,io
  self.ready();published=[];folder=Path(self.tmp.name);(folder/'options.json').write_text('{}')
  class Stop:
   done=False
   def is_set(self):return self.done
   def wait(self,s):self.done=True
  class Clock:
   @staticmethod
   def now(tz):return datetime.fromisoformat(stamp(10)).astimezone(tz)
  res=result(stamp(10));res.update(active=True,priority='ev',selected={'reason':'ev_first'},collection_health={'status':'ok'})
  maintenance=MagicMock();maintenance.snapshot.return_value={};maintenance.close.return_value=False
  monitoring=MagicMock();monitoring.submit.side_effect=lambda x,failure=False:published.append(copy.deepcopy(x));monitoring.snapshot.return_value={'status':'ok'};monitoring.start.return_value=monitoring
  with patch.object(obs,'DATA',folder),patch.object(obs,'Path',side_effect=lambda p:folder/'options.json'if p=='/data/options.json'else Path(p)),patch.object(obs,'datetime',Clock),patch.object(obs,'ReadOnlyHA')as client,patch.object(obs,'Maintenance',return_value=maintenance),patch.object(obs.journal_transport,'Publisher'),patch.object(obs,'STOP',Stop()),patch.object(obs.signal,'signal'),patch.object(obs,'archive_forecasts'),patch.object(obs,'observe_priority',return_value=res),patch.object(obs.control_journal,'observe',side_effect=ValueError('synthetic')),patch.object(obs,'MonitorPublisher',return_value=monitoring) ,contextlib.redirect_stdout(io.StringIO()):
   client.return_value.priority_states.return_value=data(stamp(10));obs.main()
  run=unpack(self.store.db.execute('SELECT payload FROM ram_control_sessions').fetchone()[0]);self.assertEqual(run['target_ac_w'],0);self.assertEqual(run['status'],'waiting_for_recovery');self.assertEqual(published[0]['collection_health']['status'],'failed');self.assertTrue(any(unpack(p)['kind']=='collection_failure'for p, in self.store.db.execute('SELECT payload FROM ram_control_events')))
