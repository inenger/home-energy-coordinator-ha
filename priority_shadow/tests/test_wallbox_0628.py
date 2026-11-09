"""Authoritative wallbox, settled learning and bounded writer transactions."""
import copy,json,tempfile,threading,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from energy import wallbox,priority,night,soc_runtime,phase_budget,journal_transport as jt,isolated_control as iso
from energy.store import Store,pack,unpack
from energy.sqlite_writes import gate_for,Gate
from test_night import state
from test_priority import inputs,AT
from test_night_fixes_0623 import drive_startup

class WallboxAuthority(unittest.TestCase):
 def points(self,power=0,status='Available',cable='on'):
  rows=inputs();by={s['entity_id']:s for s in rows}
  for eid,value,unit in [(night.IDS['ev_w'],power,'W'),(night.IDS['ev_state'],status,None),(night.IDS['ev_connected'],cable,None)]:
   s=state(eid,value,AT);s['attributes']['unit_of_measurement']=unit;by[eid]=s
  return priority.checked_points(list(by.values()),AT)
 def test_tessie_cannot_claim_connected_or_charging_against_wallbox(self):
  p=self.points();self.assertEqual(p['ev_connected']['value'],'off')
  self.assertEqual(p['ev_connected']['entity_id'],wallbox.STATUS_ID)
  self.assertEqual(p['ev_connected_supplementary']['value'],'on')
 def test_tessie_cannot_hide_wallbox_charging(self):
  p=self.points(11000,'Charging','off');o=wallbox.observation(p)
  self.assertEqual(o['connected'],'on');self.assertEqual(o['activity'],'charging')
 def test_zero_power_is_not_disconnection_without_wallbox_status(self):
  p=self.points(0,'unavailable','on');self.assertIsNone(p['ev_connected']['value'])
 def test_stale_power_and_status_do_not_fall_back_to_cloud(self):
  p=self.points(11000,'Charging');p['ev_w']['age_seconds']=16;p['ev_state']['age_seconds']=16
  self.assertIsNone(wallbox.observation(p)['connected'])
 def test_suspended_wallbox_preserves_connection_without_claiming_power(self):
  p=self.points(0,'Suspended EV','off');o=wallbox.observation(p)
  self.assertEqual(o['connected'],'on');self.assertEqual(o['activity'],'connected_idle')
 def test_real_fast_loop_is_independent_of_tessie(self):
  from energy import isolated_control as iso
  from test_ram_control import data,stamp
  from test_control_journal import patch_value
  from test_instant_fill import SESSION
  results=[]
  for cloud in ['on','off','unavailable']:
   mem=iso.MemoryControl()
   try:
    for sec in [0,5,10]:
     rows=data(stamp(sec));patch_value(rows,night.IDS['ev_connected'],cloud);patch_value(rows,night.IDS['ev_soc'],'unavailable')
     result,journal=mem.step(rows,{'session':{**SESSION,'day':stamp(sec)[:10]}},stamp(sec))
    results.append((result['selected']['battery_ac_w'],journal['session']['target_ac_w'],journal['recent_samples'][0]['input_errors']))
   finally:mem.close()
  self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2])
 def test_planner_connection_and_limit_are_wallbox_authoritative(self):
  rows=inputs();by={s['entity_id']:s for s in rows}
  for eid,value,unit in [(night.IDS['ev_w'],0,'W'),(night.IDS['ev_state'],'Available',None),(night.IDS['ev_connected'],'on',None),(soc_runtime.IDS['tesla_limit_a'],0,'A'),(night.IDS['ev_limit_a'],16,'A')]:
   s=state(eid,value,AT);s['attributes']['unit_of_measurement']=unit;by[eid]=s
  out=soc_runtime.inputs(list(by.values()),AT,{'ac_kwh_per_soc_pct':.8},{},[],False)
  self.assertEqual(out['ev_connected'],'off');self.assertEqual(out['ev_need_ac_kwh'],0)
  self.assertGreater(out['ev_max_ac_kw'],0);self.assertEqual(out['tesla_current_limit_supplementary_a'],0)

 def test_lifecycle_events_come_from_wallbox_in_production_loop(self):
  evidence,monitor=drive_startup();events=monitor.results[-1]['control_journal']['recent_events']
  kinds=[e['kind']for e in events]
  self.assertIn('wallbox_charge_started',kinds);self.assertIn('wallbox_charge_stopped',kinds)
  for e in events:
   if e['kind'].startswith('wallbox_charge_'):
    self.assertEqual(e['wallbox']['power_entity_id'],wallbox.POWER_ID);self.assertEqual(e['device_actions'],0)


def history(lag=False,house_step=False,pulse=False):
 base=datetime(2026,1,1,3,tzinfo=timezone.utc);out=[]
 for n in range(150):
  at=base+timedelta(seconds=n*5);ev=3680. if 40<=n<110 else 0.;reported=0. if lag and n==40 else ev
  house=1200.+(2300. if house_step and n>=40 or pulse and n==80 else 0.);points={}
  for i in [1,2,3]:
   values={f'grid_voltage_l{i}_v':230.,f'grid_l{i}_w':-(house+ev),f'inverter_l{i}_w':0.,f'ev_l{i}_w':reported,f'grid_l{i}_a':(house+ev)/230.}
   for k,v in values.items():points[k]={'value':v,'quality':'valid','age_seconds':5. if lag and n==40 and k.startswith('ev_')else 0.}
  out.append({'at':at.isoformat(),'inputs':points})
 return out

class SettledReserve(unittest.TestCase):
 def test_lag_is_not_a_16A_house_step(self):
  a=history();b=history(True);at=a[-1]['at'];x=phase_budget.estimate(a,at);y=phase_budget.estimate(b,at)
  self.assertEqual(x['reserve_a'],[.1]*3);self.assertEqual(y['reserve_a'],x['reserve_a'])
  self.assertGreater(sum(y['settlement']['adjusted_step_pairs']),0)
  self.assertTrue(y['settlement']['unknown_pulses_not_proven_absent'])
 def test_real_house_step_during_EV_start_is_preserved(self):
  rows=history(True,True);r=phase_budget.estimate(rows,rows[-1]['at'])
  self.assertGreaterEqual(min(r['reserve_a']),10.)
 def test_brief_house_peak_away_from_EV_transition_is_preserved(self):
  rows=history(True,pulse=True);r=phase_budget.estimate(rows,rows[-1]['at'])
  self.assertGreaterEqual(min(r['reserve_a']),10.)
 def test_future_frames_never_settle_current_decision(self):
  rows=history(True);at=rows[40]['at']
  self.assertEqual(phase_budget.estimate(rows,at),phase_budget.estimate(rows[:41],at))
 def test_database_entrypoint_and_planner_budget_change(self):
  from energy.soc_planner import _night_room
  with tempfile.TemporaryDirectory()as folder:
   s=Store(Path(folder)/'e.sqlite');priority.schema(s.db);rows=history(True)
   try:
    with s.db:s.db.executemany('INSERT INTO priority_samples VALUES(?,?,?)',[(x['at'],x['at'][:10],pack(x))for x in rows])
    before=s.db.execute('SELECT at,payload FROM priority_samples ORDER BY at').fetchall()
    result=phase_budget.from_db(s.db,rows[-1]['at'])
    self.assertEqual(result['reserve_a'],[.1]*3)
    self.assertGreater(_night_room({'phase_voltages':[230.]*3,'power_budget':result},3),_night_room({'phase_voltages':[230.]*3,'power_budget':{**result,'reserve_a':[16.1]*3}},3))
    self.assertEqual(s.db.execute('SELECT at,payload FROM priority_samples ORDER BY at').fetchall(),before)
   finally:s.close()

 def test_from_database_through_full_planner_preserves_old_sealed_decision(self):
  from energy.soc_planner import plan
  from energy.soc_evidence import verify
  from test_soc_planner import fixture
  now,inp,h,versions,house=fixture(pv=6,house=.7,soc=11,season='winter',ev=18)
  rows=history(True)
  for row in rows:row['at']=(datetime.fromisoformat(row['at'])+timedelta(days=13)).isoformat()
  with tempfile.TemporaryDirectory()as folder:
   store=Store(Path(folder)/'e.sqlite');priority.schema(store.db);soc_runtime.schema(store.db)
   try:
    with store.db:store.db.executemany('INSERT INTO priority_samples VALUES(?,?,?)',[(x['at'],x['at'][:10],pack(x))for x in rows])
    corrected=phase_budget.from_db(store.db,now.isoformat())
    old_input={**inp,'power_budget':{**corrected,'reserve_a':[16.1]*3}}
    old=soc_runtime.record_decision(store,plan(now,old_input,h,{},house,versions))
    old_row=store.db.execute('SELECT payload FROM soc_decisions WHERE at=?',(old['issued_at'],)).fetchone()[0]
    new=plan(now+timedelta(seconds=1),{**inp,'power_budget':corrected},h,{},house,versions)
    new=soc_runtime.record_decision(store,new)
    self.assertEqual(old['status'],'no_comparable_feasible_plan')
    self.assertIn(new['status'],('partial_shadow_plan','conditional_shadow_plan'))
    self.assertTrue(verify(old)['verified']);self.assertTrue(verify(new)['verified'])
    self.assertEqual(old_row,store.db.execute('SELECT payload FROM soc_decisions WHERE at=?',(old['issued_at'],)).fetchone()[0])
    self.assertEqual(store.db.execute('SELECT count(*) FROM soc_decisions').fetchone()[0],2)
   finally:store.close()

class WriterScopes(unittest.TestCase):
 def seed(self,path):
  evidence,monitor=drive_startup();s=Store(path)
  for n,(rows,states,result,generation)in enumerate(evidence.rows,1):iso.persist_batch(s,{'runtime':'wallbox-test','seq':n,'at':result['at'],'rows':rows,'loss':{},'states':states,'result':result})
  return s,monitor.results[-1]
 def test_chunk_packing_never_holds_writer_gate(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';s,result=self.seed(path);gate=gate_for(path);original=jt.pack;seen=[]
   def checked(value):
    if isinstance(value,dict)and value.get('format')==jt.FORMAT:
     seen.append(value['seq']);self.assertIsNone(gate.diagnostic()['owner_thread'])
    return original(value)
   try:
    with patch.object(jt,'pack',side_effect=checked):jt.enqueue(s,result['control_journal'])
    self.assertTrue(seen)
    first=s.db.execute('SELECT seq,payload FROM journal_transport_outbox ORDER BY seq').fetchall();jt.enqueue(s,result['control_journal'])
    self.assertEqual(first,s.db.execute('SELECT seq,payload FROM journal_transport_outbox ORDER BY seq').fetchall())
   finally:s.close()
 def test_send_intents_are_durable_before_HTTP_and_writes_are_batched(self):
  with tempfile.TemporaryDirectory()as folder:
   path=Path(folder)/'e.sqlite';s,result=self.seed(path);jt.enqueue(s,result['control_journal']);s.close();published=[];transactions=[]
   class Client:
    def history(self,*a):return []
    def publish(self,attrs):
     r=Store(path)
     try:
      sent=jt.get(r.db,'sent',{});self_sent=sent[str(attrs['seq'])];assert self_sent['first_at']
      assert gate_for(path).diagnostic()['owner_thread']is None
     finally:r.close()
     published.append(attrs)
   from energy import journal_transport as module
   original=module.Store
   def tracked(*args,**kwargs):
    st=original(*args,**kwargs);st.db.set_trace_callback(lambda sql:transactions.append(sql)if sql=='COMMIT'else None);return st
   with patch.object(module,'Store',side_effect=tracked):module.Publisher(path,Client()).tick(datetime(2026,1,1,tzinfo=timezone.utc))
   self.assertTrue(published);self.assertLessEqual(len(transactions),3)
 def test_waiter_timeout_cleans_admission_queue(self):
  g=Gate();held=threading.Event();release=threading.Event()
  def holder():
   g.acquire(False,1);held.set();release.wait(2);g.release()
  t=threading.Thread(target=holder);t.start();self.assertTrue(held.wait(1))
  try:
   from energy.sqlite_writes import WriterTimeout
   with self.assertRaises(WriterTimeout):g.acquire(True,.01)
   self.assertEqual(g.diagnostic()['queued_writers'],0);self.assertEqual(g.fast_waiters,0)
  finally:release.set();t.join(2)

class WriterFairness(unittest.TestCase):
 def test_durable_admission_is_fifo_and_slow_writer_is_not_starved(self):
  g=Gate();g.acquire(False,1);order=[];errors=[];threads=[]
  def worker(n,fast):
   try:g.acquire(fast,3);order.append(n);g.release()
   except BaseException as error:errors.append(error)
  try:
   for n in range(13):
    t=threading.Thread(target=worker,args=(n,n!=0));threads.append(t);t.start()
    deadline=time.monotonic()+1
    while g.diagnostic()['queued_writers']<n+1 and time.monotonic()<deadline:time.sleep(.001)
    self.assertEqual(g.diagnostic()['queued_writers'],n+1)
  finally:g.release()
  for t in threads:t.join(4)
  self.assertFalse(errors);self.assertEqual(order.index(0),8)
  self.assertEqual([x for x in order if x!=0],list(range(1,13)))
