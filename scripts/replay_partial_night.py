"""Read-only RPi reconstruction. Never writes production DBs or sends HA calls.

Legacy rejected proposals lack input_snapshot. Explicit reconstruction provenance
is required; this replay is not an issued plan or a measured savings result.
"""
import argparse
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--at', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    sys.path.insert(0, args.source)
    from energy.core import instant, digest
    from energy.store import unpack
    from energy.soc_history import read_gzip
    from energy.soc_calibration import Household, archived_weather
    from energy.soc_planner import plan, PLAN_STATUSES
    from energy.soc_runtime import _versions, weather_versions
    from energy.soc_evidence import verify
    from energy import priority

    now = instant(args.at)
    output = Path(args.output)
    if not str(output).startswith('/share/hec-recovery/'):
        raise ValueError('Keep private replay on RPi recovery storage')
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect('file:/share/home-energy-priority-shadow/evidence.sqlite?mode=ro', uri=True)
    legacy = unpack(db.execute('SELECT payload FROM soc_decisions WHERE at<=? ORDER BY at DESC LIMIT 1', (args.at,)).fetchone()[0])
    manifest = unpack(db.execute('SELECT payload FROM soc_model_versions WHERE hash=?', (legacy['model_version_hash'],)).fetchone()[0])
    prior = None
    for at, blob in db.execute('SELECT at,payload FROM soc_decisions WHERE at<=? ORDER BY at DESC', (args.at,)):
        candidate = unpack(blob)
        if candidate.get('input_snapshot'):
            prior = candidate
            break
    if prior is None:
        raise ValueError('No archived input baseline; cannot reconstruct')
    sample = unpack(db.execute('SELECT payload FROM night_samples WHERE at<=? ORDER BY at DESC LIMIT 1', (args.at,)).fetchone()[0])
    if (now-instant(sample['at'])).total_seconds()>30:
        raise ValueError('No contemporaneous night snapshot')
    points = sample['points']
    def number(key):
        value = points[key]
        if value.get('quality')!='valid':
            raise ValueError('Invalid reconstructed input '+key)
        return value['value']
    inputs = copy.deepcopy(prior['input_snapshot'])
    inputs.update(soc=number('battery_soc'),ev_soc=number('ev_soc'),ev_target_soc=number('ev_target_soc'),
        phase_voltages=[number('grid_voltage_l%d_v'%i) for i in (1,2,3)])
    inputs['battery_charge_max_dc_kw']=min(10.,number('battery_v')*number('battery_limit_a')/1000)
    inputs['ev_max_ac_kw']=number('ev_limit_a')*sum(inputs['phase_voltages'])/1000
    inputs['ev_need_ac_kwh']=max(0.,inputs['ev_target_soc']-inputs['ev_soc'])*manifest['ev_calibration']['ac_kwh_per_soc_pct']
    weather=archived_weather(weather_versions(db,now),now)
    observation=unpack(db.execute('SELECT payload FROM soc_observations WHERE at<=? ORDER BY at DESC LIMIT 1',(args.at,)).fetchone()[0])
    inputs['outdoor_c']=observation.get('outdoor_c')
    inputs['sunrise']=None  # Informational value was not archived for rejected decisions.
    inputs['weather_rows']=(weather or {}).get('payload',{}).get('forecast',[])
    inputs['use_temperature']=manifest['house_validation']['use_temperature']
    history=read_gzip('/share/home-energy-priority-shadow/soc-history.json.gz')
    history['battery_model']=manifest['battery_model']
    house=Household(history['house_hours'],now)
    versions=_versions(SimpleNamespace(db=db),args.at)
    result={'kind':'retrospective_reconstruction_not_issued_decision','at':args.at,
        'legacy_input_snapshot_missing':True,'baseline_issued_at':prior['issued_at'],
        'contemporaneous_points_at':sample['at'],
        'carried_fields':{'battery_discharge_max_dc_kw':inputs.get('battery_discharge_max_dc_kw'),
                         'sunrise':inputs.get('sunrise'),'outdoor_c':inputs.get('outdoor_c')},
        'house_source_matches_manifest':house.source_hash==manifest['house_data_hash'],
        'assumptions':'Discharge limit carried from prior issued snapshot, sunrise unavailable; not exact original input reproduction.',
        'plan_executed':False,'measured_savings_czk':None,'variants':{}}
    for name in ('ev','battery'):
        proposal=plan(now,{**inputs,'priority':name},history,manifest['pv_models'],house,versions)
        assert verify(proposal)['verified']
        assert all(instant(v['available_at'])<=now for group in versions.values() for v in group)
        (output/(name+'-proposal.json')).write_text(json.dumps(proposal,ensure_ascii=False,indent=2))
        summary={k:proposal.get(k) for k in ('status','target_soc_pct','horizon_complete','allocation_policy','ev_deficit_ac_kwh','soc_at_05_estimate','night_charge_ac_kwh','decision_hash')}
        # Independent measured-power replay with fixed reconstructed targets.
        if proposal['status'] in PLAN_STATUSES and proposal['horizon_complete']:
            model=priority.empty_model(inputs['soc'])
            session={'forecast_kwh':number('forecast_today'),
                     'target_soc_pct':proposal['target_soc_pct'],'soc_plan_valid':True,
                     'battery_energy_model':proposal['battery_energy_model']}
            previous=None;previous_at=None
            for blob, in db.execute('SELECT payload FROM priority_samples WHERE day=? ORDER BY at',(proposal['day'],)):
                row=unpack(blob)
                if previous:
                    dt=(instant(row['at'])-instant(previous_at)).total_seconds()
                    priority.advance(model,previous,dt,(previous_at,row['at']))
                previous=priority.allocate(row['inputs'],row['at'],session,model['soc_pct'],name)
                previous_at=row['at']
            summary['measured_power_replay']=model
        result['variants'][name]=summary
    db.close()
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
