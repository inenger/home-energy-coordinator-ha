# Historical coupled-loop regression baseline; current runtime proof: verify_control_isolation_0620.py
"""Syntetické důkazy celé main cesty; bez HA a bez soukromých vstupů."""
import sys,os,json
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from test_collection_fixes_0618 import CollectionFixTests
out={}
for work in (0,1,2,3):
 case=CollectionFixTests()
 run,samples,events,waits,*_=case.drive(work_s=work)
 stops=[e for e in events if e['kind']=='would_stop_charge']
 out['work_'+str(work)]={'work_s':work,'samples':len(samples),
  'logical_expirations':sum(e['reason']=='logical_lease_expired'for e in stops),
  'stops':len(stops),'control_only_ticks':sum(p.get('analytics_scheduling',{}).get('deferred_for_control_deadline',False)for p in case.plans),
  'atomic_receipts_retained':all(s.get('collection_snapshot',{}).get('sequence')is not None for s in samples),
  'original_report_evidence_retained':all(s.get('input_reports')and s.get('owner_reports')for s in samples),
  'physical_actions':sum(e['device_actions']for e in events)}
 assert not stops
 assert out['work_'+str(work)]['atomic_receipts_retained']
 assert out['work_'+str(work)]['original_report_evidence_retained']
case=CollectionFixTests();run,samples,events,*_=case.drive(work_s=3,dropout=True)
out['dropout']={'stops':sum(e['kind']=='would_stop_charge'for e in events),
 'invalid_samples':sum(bool(s['input_errors'])for s in samples),
 'invalid_samples_all_zero':all(s['ram_target_ac_w']==0 for s in samples if s['input_errors']),
 'physical_actions':sum(e['device_actions']for e in events)}
assert out['dropout']['stops']and out['dropout']['invalid_samples']and out['dropout']['invalid_samples_all_zero']
target=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/collection-0618'));target.mkdir(exist_ok=True,parents=True)
(target/'collection-probes.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
