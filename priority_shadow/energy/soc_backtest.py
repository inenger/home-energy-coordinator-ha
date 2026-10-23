"""RPi-only causal battery-plan replay; no retrospective issued decisions.

EV demand is deliberately zero in this isolated battery replay. Its result does
not validate combined EV scheduling or represent measured operational savings.
Full private inputs/results are written to the RPi, stdout is aggregate only.
"""
import argparse
from collections import Counter
from datetime import date,datetime,timedelta,time,timezone
import json
from pathlib import Path
import sqlite3
from .core import TZ,instant
from .store import unpack
from .soc_history import read_gzip,atomic_gzip
from .soc_calibration import Household,fit_pv,validate_household,pre_window
from .soc_planner import plan
from .night import target_for
from .soc_runtime import weather_versions


def replay(db,history,day):
    now=pre_window(day.isoformat())
    result={'day':day.isoformat(),'decision_at':now.isoformat(),'issued_historically':False,
            'ev_requirement_ac_kwh':0,'replay_kind':'isolated_battery_no_ev',
            'measured_savings_czk':None,'device_actions':0}
    sample=db.execute('SELECT available_at,payload FROM samples WHERE available_at<=? ORDER BY available_at DESC LIMIT 1',(now.isoformat(),)).fetchone()
    if not sample or (now-instant(sample[0])).total_seconds()>180:
        return {**result,'status':'missing_asof_soc_sample'}
    signals=unpack(sample[1])['signals']
    def value(key,ttl=180):
        s=signals.get(key,{})
        reported=s.get('last_reported')
        if s.get('quality')!='valid' or not reported or not 0<=(now-instant(reported)).total_seconds()<=ttl:return None
        return s.get('value')
    # These two are explicit modelling assumptions, never device settings.
    inputs={'soc':value('battery_soc',10800),'reserve_soc':15,'reserve_soc_approved':None,
            'battery_charge_max_dc_kw':7.,'battery_discharge_max_dc_kw':7.,'phase_voltages':[230.]*3,'priority':'battery',
            'ev_need_ac_kwh':0.,'ev_max_ac_kw':0.,'use_temperature':False,
            'outdoor_c':value('outdoor_temp',7200),'weather_rows':[]}
    result['power_and_phase_assumptions']={'battery_charge_max_dc_kw':7,'battery_discharge_max_dc_kw':7,'phase_voltages':[230]*3}
    versions={'solar':[],'tariff':[]}
    cutoff=(now-timedelta(hours=30)).isoformat()
    for entity,available,key,blob in db.execute('''SELECT v.entity,v.available_at,v.hash,o.payload FROM versions v
        JOIN objects o ON o.hash=v.hash WHERE v.available_at<=? AND v.available_at>=?
        AND (v.entity='sensor.cez_indi_cenik' OR v.entity LIKE 'sensor.solcast_pv_forecast_forecast_%')''',(now.isoformat(),cutoff)):
        versions['tariff' if entity=='sensor.cez_indi_cenik' else 'solar'].append({'available_at':available,'hash':key,'payload':unpack(blob)})
    weather=db.execute("SELECT o.payload FROM versions v JOIN objects o ON o.hash=v.hash WHERE v.entity LIKE 'weather_forecast:%:hourly' AND v.available_at<=? AND v.available_at>=? ORDER BY v.id DESC LIMIT 1",(now.isoformat(),(now-timedelta(hours=8)).isoformat())).fetchone()
    if weather:
        p=unpack(weather[0])
        if p.get('units',{}).get('temperature_unit')=='°C':inputs['weather_rows']=p['forecast']
    validation=validate_household(history['house_hours'],now,weather_versions(db,now));inputs['use_temperature']=validation.get('use_temperature',False)
    p=plan(now,inputs,history,fit_pv(history['pv_pairs'],now),Household(history['house_hours'],now),versions)
    result.update(status=p['status'],plan=p,house_validation=validation)
    if p.get('status')=='conditional_shadow_plan':
        daily=p['reference_forecast_day_kwh'];legacy=target_for(daily)
        result.update(target_soc_pct=p['target_soc_pct'],legacy_table_target_soc_pct=legacy,
                      forecast_day_raw_kwh=daily,horizon_complete=p['horizon_complete'])
        prior=next((r for r in p['candidates'] if r['target_soc_pct']==legacy),None)
        if prior:
            result['legacy_comparison']={'feasible_all_scenarios':prior['feasible_all_scenarios'],
                'central_inventory_adjusted_cost_difference_czk':
                    prior['scenarios']['central']['inventory_adjusted_cost_czk']-p['selected']['scenarios']['central']['inventory_adjusted_cost_czk'],
                'meaning':'model_score_difference_only_same_horizon_and_terminal_valuation_not_measured_savings'}
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--history',required=True)
    p.add_argument('--from-day',required=True);p.add_argument('--through-day',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();first=date.fromisoformat(a.from_day);last=date.fromisoformat(a.through_day)
    if first<date(2026,8,1):raise ValueError('July battery fit cannot be used before its fitting period ended')
    db=sqlite3.connect('file:'+str(Path(a.database).resolve())+'?mode=ro',uri=True);history=read_gzip(a.history);rows=[]
    try:
        while first<=last:
            rows.append(replay(db,history,first));first+=timedelta(days=1)
    finally:db.close()
    summary={'replay_days':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
             'valid_targets':dict(Counter(str(r['target_soc_pct']) for r in rows if 'target_soc_pct' in r)),
             'complete_horizons':sum(r.get('horizon_complete',False) for r in rows),
             'kind':'isolated_battery_no_ev','issued_historically':False,'measured_savings_czk':None,'device_actions':0}
    atomic_gzip(a.output,{'summary':summary,'days':rows});print(json.dumps(summary))


if __name__=='__main__':main()
