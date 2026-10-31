"""Independent synthetic counterexamples for 0.6.13. No HA/device calls.

Writes evidence JSON to ENERGY_AUDIT_OUTPUT; contract_met=false reproduces
a finding. Existing evidence should always use a fresh output directory.
"""
import sys,json,tempfile,copy
from pathlib import Path
from datetime import datetime,timedelta
import os
repo=Path(__file__).resolve().parents[1]
r=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/energy-audit-0613'));r.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from energy import ram_control as c,control_journal as legacy
from energy.store import Store,pack,unpack
from test_ram_control import data,result,stamp
from test_control_journal import patch_value
out={}
with tempfile.TemporaryDirectory(dir=r)as folder:
 s=Store(Path(folder)/'e.sqlite')
 for sec in (0,5,10):v=c.observe(s,data(stamp(sec)),result(stamp(sec)))
 run=copy.deepcopy(v['session']);before=run['shadow_model']['battery_kwh_ac'];power=run['target_ac_w']
 failed=c.record_failure(s,stamp(12),'TimeoutError')['session'];actual=failed['shadow_model']['battery_kwh_ac']-before
 # A validated sample at exactly the same time takes the normal integration route.
 run['day']=run['day'];s.db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(run),run['day']));s.db.commit()
 ss=data(stamp(12));patch_value(ss,c.RUN_MODE,'Off-Grid');normal=c.observe(s,ss,result(stamp(12)))['session'];normal_delta=normal['shadow_model']['battery_kwh_ac']-before
 out['failure_energy']={'logical_power_w':power,'stop_after_s':2,'expected_ac_kwh':power*2/3600000,'record_failure_delta_kwh':actual,'normal_invalid_input_delta_kwh':normal_delta,'contract_met':abs(actual-power*2/3600000)<1e-10}
 s.close()
with tempfile.TemporaryDirectory(dir=r)as folder:
 s=Store(Path(folder)/'e.sqlite')
 for sec in (0,5):v=c.observe(s,data(stamp(sec)),result(stamp(sec)))
 ss=data(stamp(7200));patch_value(ss,'sensor.solax_api_charge_power_total','unavailable');v=c.observe(s,ss,result(stamp(7200)));old_day=v['session']['day'];assert v['session']['status']=='restore_pending'
 # Retained historical closed rows from a portable import/recovery put the pending row beyond the display limit.
 for offset in range(1,15):
  day=(datetime.fromisoformat(stamp(offset*86400))).date().isoformat();closed=copy.deepcopy(v['session']);closed.update(day=day,status='closed',closed_at=stamp(offset*86400+7200));s.db.execute('INSERT INTO ram_control_sessions VALUES(?,?)',(day,pack(closed)))
 s.db.commit();at=stamp(15*86400);ss=data(at);patch_value(ss,'sensor.solax_api_charge_power_total',0);v=c.observe(s,ss,result(at))
 old=unpack(s.db.execute('SELECT payload FROM ram_control_sessions WHERE day=?',(old_day,)).fetchone()[0]);today=datetime.fromisoformat(at).date().isoformat();exists=bool(s.db.execute('SELECT 1 FROM ram_control_sessions WHERE day=?',(today,)).fetchone())
 out['old_pending_recovery']={'old_day':old_day,'old_status_after_fresh_valid_recovery':old['status'],'new_day_session_created':exists,'contract_met':old.get('closed_at')is not None and exists}
 s.close()
(r/'backend-probes.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))

import sys,json,tempfile,copy
from pathlib import Path
import os
repo=Path(__file__).resolve().parents[1]
r=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/energy-audit-0613'));r.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from energy import ram_control as c,control_journal as legacy,priority,night,soc_runtime,instant_fill
from energy.store import Store,pack,unpack
from test_ram_control import data,result,stamp
from test_night import state
from test_control_journal import patch_value,states as legacy_states,result as legacy_result
out={}
with tempfile.TemporaryDirectory(dir=r)as folder:
 s=Store(Path(folder)/'e.sqlite')
 for sec in (0,5):c.observe(s,data(stamp(sec)),result(stamp(sec)))
 ss=data(stamp(7200));patch_value(ss,legacy.CURRENT,'unavailable');patch_value(ss,'sensor.solax_api_charge_power_total',0)
 run=c.observe(s,ss,result(stamp(7200)))['session'];row=next(x for x in run['restoration']if x['entity_id']==legacy.CURRENT)
 out['missing_restore_evidence']={'status':run['status'],'exact_restore':run['exact_restore'],'comparison':row,'contract_met':not run['exact_restore']}
 s.close()
with tempfile.TemporaryDirectory(dir=r)as folder:
 s=Store(Path(folder)/'e.sqlite');v=legacy.observe(s,legacy_states(stamp(0)),legacy_result(stamp(0)));day=v['session']['day'];assert v['session']['owned']
 for sec in (7200,7205,86400,86405):v=c.observe(s,data(stamp(sec)),result(stamp(sec)))
 old=unpack(s.db.execute('SELECT payload FROM control_sessions WHERE day=?',(day,)).fetchone()[0]);new_count=s.db.execute('SELECT count(*) FROM ram_control_sessions').fetchone()[0]
 out['legacy_owner_upgrade']={'old_status':old['status'],'old_closed_at':old.get('closed_at'),'ram_sessions_after_recovery_and_next_night':new_count,'contract_met':old.get('closed_at')is not None and new_count>0}
 s.close()
with tempfile.TemporaryDirectory(dir=r)as folder:
 s=Store(Path(folder)/'e.sqlite');night.ensure_schema(s.db);soc_runtime.schema(s.db)
 bm={'discharge_curve':[[0,0],[50,5],[100,10]],'dc_cycle_efficiency':.9,'grid_efficiency':.9,'source_hash':'synthetic'}
 with s.db:s.db.execute('INSERT INTO soc_model_versions VALUES(?,?,?)',('m','2026-01-14T20:00:00+00:00',pack({'at':'2026-01-14T20:00:00+00:00','battery_model':bm})))
 trace=[]
 for sec in (0,5,10,8,10,15):
  v=priority.observe(s,data(stamp(sec))+[state(priority.HELPER,"Elektromobil",stamp(sec))],stamp(sec),True,instant_fill.POLICY);m=v['progress']['models']['selected'];trace.append({'sec':sec,'covered_s':m['covered_s'],'battery_kwh_ac':m['battery_kwh_ac'],'fingerprint':m['coverage_fingerprint']})
 rowcount=s.db.execute('SELECT count(*) FROM priority_samples').fetchone()[0]
 out['ideal_rollback']={'trace':trace,'unique_persisted_samples':rowcount,'expected_covered_s_max':15,'actual_covered_s':trace[-1]['covered_s'],'contract_met':trace[-1]['covered_s']<=15}
 before=copy.deepcopy(v['progress']['models']['selected']);v=priority.observe(s,data(stamp(15))+[state(priority.HELPER,"Elektromobil",stamp(15))],stamp(15),True,instant_fill.POLICY)
 out['ideal_duplicate']={'prior_covered_s':before['covered_s'],'after_covered_s':v['progress']['models']['selected']['covered_s'],'reported_sample_count':priority._get(s,'priority_runs',v['progress']['day'])['sample_count'],'persisted_samples':s.db.execute('SELECT count(*) FROM priority_samples').fetchone()[0]}
 summary=priority.finish(s,v['progress']['day']);out['ideal_rollback']['final_summary_covered_s']=summary['models']['selected']['covered_s'];out['ideal_rollback']['final_summary_sample_count']=summary['sample_count']
 s.close()
(r/'backend-more.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
