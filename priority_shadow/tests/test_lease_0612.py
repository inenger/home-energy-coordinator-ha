"""Lease renewal under asynchronous five-second HA reporting; no hardware IO."""
import base64,copy,hashlib,json,math,tempfile,unittest,zlib
from datetime import datetime,timedelta
from pathlib import Path
from energy import ram_control as c,journal_transport as transport,night
from energy.store import Store,unpack
from test_ram_control import data,result,stamp
from test_control_journal import patch_value

class LeaseRenewalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'e.sqlite';self.store=Store(self.path)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def step(self,t,reported=None,mutate=None):
  ss=data(stamp(t if reported is None else reported))
  if mutate:mutate(ss)
  return c.observe(self.store,ss,result(stamp(t)))
 def ready(self):self.step(0);return self.step(5)
 def events(self):return [unpack(p)for p, in self.store.db.execute('SELECT payload FROM ram_control_events ORDER BY id')]
 def test_duplicate_holds_power_without_becoming_new_evidence(self):
  self.ready();v=self.step(10,5);run=v['session'];sample=v['recent_samples'][0]
  self.assertEqual(run['target_ac_w'],500);self.assertFalse(sample['new_frame'])
  self.assertEqual(sample['intent_renewal'],'held_validated_frame')
  self.assertEqual(run['good_frames'],2)
  self.assertEqual(set(run['accepted_solax_reports'].values()),{stamp(5)})
  self.assertEqual(run['last_intent']['at'],stamp(10))
  self.assertLessEqual(datetime.fromisoformat(run['last_intent']['expires_at']),datetime.fromisoformat(stamp(20)))
  self.assertGreater(self.step(15.011,15)['session']['target_ac_w'],500)
  self.assertFalse(any(e['reason']=='logical_lease_expired'for e in self.events()))
 def test_identical_reports_cannot_extend_beyond_original_freshness(self):
  self.ready()
  for t in (10,15,19):v=self.step(t,5)
  self.assertEqual(v['session']['target_ac_w'],500)
  self.assertEqual(v['session']['last_intent']['expires_at'],stamp(20))
  v=self.step(20,5);self.assertEqual(v['session']['target_ac_w'],0)
  self.assertTrue(v['recent_samples'][0]['input_errors'])
  self.assertEqual(self.step(25)['session']['target_ac_w'],0)
  self.assertGreater(self.step(30)['session']['target_ac_w'],0)
 def test_owner_and_voltage_deadlines_also_cap_renewal(self):
  self.ready()
  def older_owner(ss):
   for row in ss:
    if row['entity_id']==c.READBACKS[0]:row['last_reported']=stamp(1)
  v=self.step(10,10,older_owner)
  self.assertEqual(v['session']['last_intent']['expires_at'],stamp(16))
  v=self.step(15,15,older_owner)
  self.assertEqual(v['session']['last_intent']['expires_at'],stamp(16))
  v=self.step(16,16,older_owner);self.assertEqual(v['session']['target_ac_w'],0)
 def test_invalid_same_frame_stops_before_any_renewal(self):
  self.ready()
  v=self.step(10,5,lambda ss:patch_value(ss,night.IDS['grid_l1_w'],'unavailable'))
  self.assertEqual(v['session']['target_ac_w'],0)
  self.assertIsNone(v['recent_samples'][0]['intent_renewal'])
  self.assertEqual(self.step(15)['session']['target_ac_w'],0)
  self.assertGreater(self.step(20)['session']['target_ac_w'],0)
 def test_lower_limit_can_only_reduce_on_held_frame(self):
  self.ready()
  v=self.step(10,5,lambda ss:patch_value(ss,night.IDS['battery_limit_a'],0))
  self.assertEqual(v['session']['target_ac_w'],0)
  self.assertFalse(v['recent_samples'][0]['new_frame'])
 def test_actual_expiry_or_sampling_gap_is_not_revived_by_held_frame(self):
  self.ready();v=self.step(16,5)
  self.assertEqual(v['session']['target_ac_w'],0)
  self.assertIsNone(v['recent_samples'][0]['intent_renewal'])
  self.assertEqual(v['session']['shadow_model']['covered_s'],0)
  self.assertEqual(self.step(20)['session']['target_ac_w'],0)
  self.assertGreater(self.step(25)['session']['target_ac_w'],0)
 def test_true_short_lease_expiry_preserves_zero_gap_and_recovery(self):
  self.ready()
  # Healthy collection but an owner report approaches its absolute deadline.
  def owner_old(ss):
   for row in ss:
    if row['entity_id']==c.REMOTE_MODE:row['last_reported']=stamp(0)
  self.step(10,10,owner_old)
  v=self.step(15.011,15)
  self.assertEqual(v['session']['target_ac_w'],0)
  self.assertEqual(v['session']['shadow_model']['covered_s'],10)
  self.assertTrue(any(e['reason']=='logical_lease_expired'for e in self.events()))
  self.assertGreater(self.step(20.011,20)['session']['target_ac_w'],0)
 def test_intent_expiry_is_positive_bounded_and_canonical(self):
  good=c.intent(100,stamp(5),stamp(11));self.assertEqual(c.validate_intent(good),good)
  for expiry in (stamp(5),stamp(4),stamp(15.001)):
   with self.assertRaises(ValueError):c.intent(100,stamp(5),expiry)
  for patch in ({'expires_at':stamp(20)},{'device_actions':1},{'wire_command':{}}):
   with self.assertRaises(ValueError):c.validate_intent({**good,**patch})
 def test_rollback_reports_do_not_extend_lease_or_raise_power(self):
  self.ready();v=self.step(10,0)
  self.assertEqual(v['session']['last_intent']['at'],stamp(5))
  self.assertEqual(v['session']['target_ac_w'],500)
 def test_partial_report_backstep_can_hold_but_never_increase_or_refresh_reports(self):
  self.ready()
  def partial(ss):
   next(row for row in ss if row['entity_id']==night.IDS['grid_l1_w'])['last_reported']=stamp(4.99)
  v=self.step(10,5,partial);run=v['session'];sample=v['recent_samples'][0]
  self.assertEqual(run['target_ac_w'],500);self.assertFalse(sample['new_frame'])
  self.assertEqual(sample['intent_renewal'],'held_validated_frame')
  self.assertEqual(run['good_frames'],2)
  self.assertEqual(set(run['accepted_solax_reports'].values()),{stamp(5)})
  self.assertEqual(run['last_intent']['expires_at'],stamp(19.99))
  self.assertEqual(self.step(15,5,partial)['session']['target_ac_w'],500)
  v=self.step(19.99,5,partial);self.assertEqual(v['session']['target_ac_w'],0)
  self.assertTrue(v['recent_samples'][0]['input_errors'])
 def test_full_asynchronous_night_store_summary_and_outbox_are_consistent(self):
  # Collector is 5 s, physical report cohort is 5.01 s. This includes repeated
  # cohorts, tiny scheduling jitter and a mid-session process/store restart.
  energy=0.;previous=None;samples=[]
  for i in range(1440):
   t=i*5+(0.011 if i%3==2 else 0)
   report=math.floor(t/5.01)*5.01
   v=self.step(t,report);s=v['recent_samples'][0];samples.append(copy.deepcopy(s))
   if previous and previous['ram_target_ac_w']>0:
    start=datetime.fromisoformat(previous['at']);end=min(datetime.fromisoformat(s['at']),datetime.fromisoformat(previous['intent_expires_at']))
    energy+=previous['ram_target_ac_w']*max(0,(end-start).total_seconds())/3600000
   previous=s
   if i==700:self.store.close();self.store=Store(self.path)
  v=self.step(7200,7200);run=v['session']
  start=datetime.fromisoformat(previous['at']);end=min(datetime.fromisoformat(run['window_end']),datetime.fromisoformat(previous['intent_expires_at']))
  energy+=previous['ram_target_ac_w']*max(0,(end-start).total_seconds())/3600000
  self.assertTrue(all(s['ram_target_ac_w']>0 for s in samples[2:]))
  self.assertGreater(sum(s['intent_renewal']=='held_validated_frame' for s in samples),0)
  self.assertFalse(any(e['reason']=='logical_lease_expired'for e in self.events()))
  self.assertAlmostEqual(energy,run['shadow_model']['battery_kwh_ac'],places=9)
  self.assertEqual(c.summary(run)['shadow_model'],run['shadow_model'])
  self.assertEqual(run['statistics']['model_exceedance_samples'],0)
  self.assertEqual(run['target_ac_w'],0);self.assertTrue(run['closed_at'])
  while True:
   before=transport.status(self.store)['queued_seq'];transport.enqueue(self.store,v)
   if transport.status(self.store)['queued_seq']==before:break
  batches={}
  for p, in self.store.db.execute('SELECT payload FROM journal_transport_outbox ORDER BY seq'):
   part=unpack(p);batches.setdefault(part['batch_id'],[]).append(part)
  decoded={};events={}
  for key,parts in batches.items():
   raw=zlib.decompress(b''.join(base64.b64decode(p['data'])for p in sorted(parts,key=lambda p:p['part_index'])))
   self.assertEqual(hashlib.sha256(raw).hexdigest(),key);delta=json.loads(raw)
   decoded.update({s['at']:s for s in delta['samples']});events.update({e['id']:e for e in delta['events']})
  self.assertEqual(list(sorted(decoded)),sorted(s['at']for s in samples))
  self.assertEqual(len(events),run['event_count'])
  self.assertTrue(all(e['device_actions']==e['persistent_writes']==0 for e in events.values()))
