# Historical coupled-loop regression baseline; current runtime proof: verify_control_isolation_0620.py
"""Synthetic verification of complete main/RAM/SQLite/outbox fixes; no HA calls."""
import sys,os,json,math
from pathlib import Path
repo=Path(__file__).resolve().parents[1];sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from test_audit_fixes_0617 import AuditFixTests
case=AuditFixTests();out={}
for name,kwargs in [('delayed_ev',{}),('true_dropout',{'dropout':True}),('masked_budget',{'mask':'budget'}),('masked_stat',{'mask':'stat'})]:
 run,samples,events,waits,reports,acks,chunks=case.drive(**kwargs)
 stops=[e for e in events if e['kind']=='would_stop_charge']
 row={'samples':len(samples),'logical_expiry_stops':sum(e['reason']=='logical_lease_expired'for e in stops),'stop_times':[e['at']for e in stops],'sub_five_second_waits':sum(w<5 for w in waits),'held_frame_renewals':sum(s['intent_renewal']=='held_validated_frame'for s in samples),'invalid_samples':sum(bool(s['input_errors'])for s in samples),'energy_ac_kwh':run['shadow_model']['battery_kwh_ac'],'outbox_parts':chunks,'acknowledged_generations':acks}
 row['contract_met']=(not stops and row['held_frame_renewals']>0)if name=='delayed_ev'else bool(stops)if name=='true_dropout'else math.isclose(row['energy_ac_kwh'],500/3600000,abs_tol=1e-12)
 out[name]=row
assert all(x['contract_met']for x in out.values()),out
target=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/fix-0617'));target.mkdir(parents=True,exist_ok=True);(target/'main-probes.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
