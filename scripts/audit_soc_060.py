"""Independent read-only audit probes for the deployed 0.6.0 SOC companion.

Run on the RPi. This script never creates a Store on production evidence,
changes options, invokes device services, or rewrites imported history. Full
private outputs remain in --output-dir; stdout contains aggregate findings.
"""
import argparse
import copy
from datetime import datetime,timedelta,timezone,time
import gzip
import json
from pathlib import Path
import sqlite3
from statistics import mean,median
import sys


def main():
    cli=argparse.ArgumentParser();cli.add_argument('--source',default='/addons/energy_priority_shadow')
    cli.add_argument('--output-dir',required=True);args=cli.parse_args()
    sys.path.insert(0,args.source)
    from energy.core import TZ,instant,digest
    from energy.soc_energy import Battery
    from energy.soc_planner import simulate,plan,slots,solar_periods,prices
    from energy.soc_calibration import Household,fit_pv,validate_household
    from energy.soc_runtime import session_plan,view
    from energy.store import pack,unpack
    out=Path(args.output_dir);out.mkdir(mode=0o700,parents=True,exist_ok=True)
    findings={};full={}
    # Synthetic inputs are independently specified, not imported from release tests.
    model={'discharge_curve':[[0,-1.5],[15,0],[100,8.5]],
        'charge_curve':[[0,-1.5/.9],[15,0],[100,8.5/.9]],
        'dc_cycle_efficiency':.9,'dc_cycle_low':.9,'grid_efficiency':.9,
        'grid_efficiency_range':[.9,.9],'ac_discharge_efficiency':1.,
        'solar_ac_dc_efficiency':1.,'source_hash':'independent-analytic-fixture'}
    start=instant('2026-06-15T03:00:00+02:00');end=start+timedelta(hours=2)
    base={'soc':15.,'reserve_soc':15.,'battery_max_dc_kw':7.,'phase_voltages':[230.]*3,
          'priority':'battery','ev_need_ac_kwh':4.,'ev_max_ac_kw':11.}
    def row(at,house=2.,pv=0.,price=3.,hours=.5):
        return {'start':at.timestamp(),'end':at.timestamp()+hours*3600,'hours':hours,
                'house_kw':house,'house_low_kw':house,'house_high_kw':house,
                'pv_ac_kw':pv,'pv_low_kw':pv,'pv_high_kw':pv,'price':price}
    r=simulate([row(start)],base,model,95,'central',start,end,1.)
    s=r['timeline'][0];evkw=s['ev_ac_kwh']/s['hours'];batkw=s['charge_grid_ac_kwh']/s['hours']*.9
    findings['ev_minimum_current']={'ev_equivalent_phase_a':evkw*1000/690,
        'configured_min_phase_a':6,'battery_dc_kw':batkw,'battery_at_max':abs(batkw-7)<1e-8,
        'infeasible_continuous_pair':0<evkw*1000/690<6 and abs(batkw-7)<1e-8}
    full['ev_minimum_current']=r
    from energy import priority,night
    def point(value):return {'value':value,'quality':'valid','age_seconds':1}
    pp={k:point(v) for k,v in {'battery_v':7000/30,'battery_limit_a':30,'ev_w':11000}.items()}
    for phase in (1,2,3):
        pp.update({f'grid_l{phase}_w':point(-13000/3),f'inverter_l{phase}_w':point(0),
                   f'voltage_l{phase}_v':point(230),f'ev_l{phase}_w':point(11000/3)})
    allocation=priority.allocate(pp,start.isoformat(),{'forecast_kwh':6,'target_soc_pct':95,
                   'battery_energy_model':Battery(model).snapshot()},15,'battery')
    findings['ev_minimum_current']['priority_replay_ev_kw']=allocation['ev_ac_w']/1000
    full['ev_priority_replay_comparison']=allocation
    # Grid and PV charging are each constrained separately, not in aggregate.
    inp={**base,'battery_max_dc_kw':2.,'ev_need_ac_kwh':0.}
    r=simulate([row(start+timedelta(hours=1.5),house=.1,pv=.5)],inp,model,95,'central',start,end,1.)
    grid_dc=r['grid_charge_ac_kwh']*.9;pv_dc=r['pv_to_battery_ac_equivalent_kwh']
    findings['combined_battery_port_limit']={'configured_dc_kw':2.,'model_combined_dc_kw':(grid_dc+pv_dc)/.5,
          'exceeds_limit':(grid_dc+pv_dc)/.5>2.+1e-8};full['combined_battery_port_limit']=r
    # A zero charge-current setting is incorrectly also a zero discharge limit.
    inp={**base,'soc':80.,'battery_max_dc_kw':0.,'ev_need_ac_kwh':0.}
    r=simulate([row(end,house=1.)],inp,model,0,'central',start,end,1.)
    findings['charge_limit_used_as_discharge_limit']={'available_dc_kwh':Battery(model).available(80),
       'model_discharge_ac_kwh':r['discharge_ac_kwh'],'model_grid_import_ac_kwh':r['import_ac_kwh']}
    # Existing future production without a physical AC cap can exceed the inverter.
    class House:
        last_day='2026-06-14'
        def predict(self,*_):return {'central_kw':.4,'low_kw':.2,'high_kw':.6,'samples':24}
    at=instant('2026-06-15T12:00:00+02:00')
    solar=[{'start':at.timestamp(),'end':at.timestamp()+1800,'kw':9.,'low_kw':8.,'high_kw':10.,
            'available_at':(at-timedelta(hours=9)).isoformat(),'source_hash':'forecast'}]
    tariff=[{'start':at.timestamp(),'end':at.timestamp()+1800,'price':3.,'available_at':0}]
    cal={'summer|3|6-24':{'factor':1.2,'low_multiplier':.8,'high_multiplier':1.4}}
    rows,_,_=slots(at,{'use_temperature':False},House(),cal,solar,tariff,at+timedelta(minutes=30))
    findings['solar_power_cap_absent']={'raw_ac_kw':9.,'corrected_ac_kw':rows[0]['pv_ac_kw'],
         'strong_scenario_ac_kw':rows[0]['pv_high_kw'],'example_inverter_ac_limit_kw':10.}
    # Released hash pipeline includes a previous, then overwritten decision hash.
    preview=Path('/share/hec-recovery/priority-soc-060/preview-full.json')
    if preview.exists():
        p=json.loads(preview.read_text());full['deployed_preview']=p
        findings['decision_hash']={'canonical_payload_matches':p['decision_hash']==digest({k:v for k,v in p.items() if k!='decision_hash'})}
    # Older valid proposals can survive newer invalid decisions.
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE soc_decisions(at TEXT PRIMARY KEY,day TEXT,hash TEXT,payload BLOB)')
    day='2026-06-15';issued=start-timedelta(minutes=5)
    old={'status':'conditional_shadow_plan','target_soc_pct':80,'issued_at':issued.isoformat()}
    bad={'status':'no_comparable_feasible_plan','target_soc_pct':None,'issued_at':(issued+timedelta(minutes=10)).isoformat()}
    db.executemany('INSERT INTO soc_decisions VALUES(?,?,?,?)',[(x['issued_at'],day,str(i),pack(x)) for i,x in enumerate([old,bad])])
    class ReadDB:pass
    store=ReadDB();store.db=db;chosen=session_plan(store,day,(issued+timedelta(minutes=11)).isoformat())
    findings['invalid_newer_decision']={'newest_status':bad['status'],'effective_target_soc':chosen.get('target_soc_pct') if chosen else None}
    priority.schema(db);night.ensure_schema(db)
    saved={'day':day,'planning_source':'soc-energy-scenarios-v1','target_soc_pct':80,
           'battery_energy_model':Battery(model).snapshot()}
    db.execute('INSERT INTO priority_sessions VALUES(?,?)',(day,pack(saved)))
    later=priority.effective_session(store,day,(issued+timedelta(minutes=45)).isoformat(),{})
    findings['invalid_newer_decision']['persisted_session_target_after_45min']=later['target_soc_pct']
    db.close()
    # Independently evaluate temperature model with as-of weather, not actual future temperature.
    seed=Path('/share/home-energy-priority-shadow/soc-history.json.gz')
    with gzip.open(seed,'rt') as f:history=json.load(f)
    now=instant(full['deployed_preview']['issued_at']) if 'deployed_preview' in full else datetime.now(timezone.utc)
    hours=history['house_hours'];validation=validate_household(hours,now)
    full['released_weather_validation']=validation
    boundary=validation.get('train_before')
    if boundary:
        model_house=Household([r for r in hours if r['day']<boundary],instant(boundary+'T00:00:00+00:00'))
        db=sqlite3.connect('file:/share/home-energy-coordinator/evidence.sqlite?mode=ro',uri=True)
        weather_by_day={};errors=[]
        for r in hours:
            if r['day']<boundary or r['day']>=now.astimezone(TZ).date().isoformat() or r.get('quality')!='observed':continue
            day=r['day']
            if day not in weather_by_day:
                decision=datetime.combine(datetime.fromisoformat(day).date(),time(2,55),TZ).astimezone(timezone.utc)
                v=db.execute("SELECT v.available_at,o.payload FROM versions v JOIN objects o ON o.hash=v.hash WHERE v.entity LIKE 'weather_forecast:%:hourly' AND v.available_at<=? AND v.available_at>=? ORDER BY v.id DESC LIMIT 1",(decision.isoformat(),(decision-timedelta(hours=8)).isoformat())).fetchone()
                p=unpack(v[1]) if v else {};weather_by_day[day]=p.get('forecast',[]) if p.get('units',{}).get('temperature_unit')=='°C' else []
            t=instant(r['at']);matches=[x for x in weather_by_day[day] if abs((instant(x['datetime'])-t).total_seconds())<=3600 and isinstance(x.get('temperature'),(float,int))]
            if not matches:continue
            forecast=min(matches,key=lambda x:abs((instant(x['datetime'])-t).total_seconds()))['temperature']
            raw=model_house.predict(t,None);oracle=model_house.predict(t,r.get('temperature_c'));causal=model_house.predict(t,forecast)
            if not raw or not oracle or not causal:continue
            actual=r['house_without_ev_kwh'];errors.append({'at':r['at'],'raw':abs(raw['central_kw']-actual),
                 'oracle_temperature':abs(oracle['central_kw']-actual),'asof_temperature_forecast':abs(causal['central_kw']-actual)})
        db.close();full['weather_holdout']=errors
        findings['weather_holdout']={'matched_hours':len(errors),'released_gate_uses_actual_target_temperature':True,
            'raw_mae_kw':mean(r['raw'] for r in errors) if errors else None,
            'oracle_mae_kw':mean(r['oracle_temperature'] for r in errors) if errors else None,
            'asof_forecast_mae_kw':mean(r['asof_temperature_forecast'] for r in errors) if errors else None}
    # Measurement quantities at 90% coverage are compared against a whole hour.
    from energy.soc_history import minute_hours
    points=[{'at':(start+timedelta(minutes=i)).isoformat(),'house_w':400,'ev_w':0,
             'pv_counter':i/60,'inverter_w':1000,'export_limit_w':9900} for i in range(55)]
    house,pv=minute_hours(points)
    findings['pv_partial_hour_bias']={'covered_minutes':54,'true_constant_pv_kw':1.,
        'actual_proxy_recorded_kwh':pv[0]['actual_ac_proxy_kwh'],'whole_hour_ac_proxy_kwh':.966,
        'bias_fraction':pv[0]['actual_ac_proxy_kwh']/.966-1.}
    rendered=view({'day':'2026-06-15','timeline':full['ev_minimum_current']['timeline']})
    findings['soc_graph_timestamp']={'label':rendered['profile'][0]['at'],
        'soc_pct':rendered['profile'][0]['soc'],'actual_soc_timestamp':(start+timedelta(minutes=30)).isoformat(),
        'offset_minutes':-30}
    if 'deployed_preview' in full:
        original=full['deployed_preview'];issued=instant(original['issued_at'])
        db=sqlite3.connect('file:/share/hec-recovery/priority-soc-060/preview.sqlite?mode=ro',uri=True)
        versions={'solar':[],'tariff':[]}
        for entity,available,key,blob in db.execute('SELECT v.entity,v.available_at,v.hash,o.payload FROM versions v JOIN objects o ON o.hash=v.hash WHERE v.available_at<=?',(original['issued_at'],)):
            kind='tariff' if entity=='sensor.cez_indi_cenik' else 'solar' if entity.startswith('sensor.solcast_pv_forecast_forecast_') else None
            if kind:versions[kind].append({'available_at':available,'hash':key,'payload':unpack(blob)})
        db.close();household=Household(history['house_hours'],issued);pv_models=fit_pv(history['pv_pairs'],issued)
        scenarios={};summaries=[]
        def scenario(name,inputs,source_versions):
            result=plan(issued,inputs,history,pv_models,household,source_versions);scenarios[name]=result
            summaries.append({'case':name,'status':result['status'],'target_soc_pct':result.get('target_soc_pct'),
                'horizon_complete':result.get('horizon_complete'),'grid_charge_ac_kwh':result.get('night_charge_ac_kwh')})
        scenario('reproduce_released_preview',original['input_snapshot'],versions)
        scenario('temperature_gate_off',dict(original['input_snapshot'],use_temperature=False),versions)
        tail_start=instant(original['horizon_end']);tail_end=datetime.combine(instant(original['window_end']).astimezone(TZ).date()+timedelta(days=1),time(3),TZ).astimezone(timezone.utc)
        for price in [0.,1.8078,4.7,10.]:
            variant=copy.deepcopy(versions);tail=[];t=tail_start
            while t<tail_end:
                tail.append({'start':t.isoformat(),'end':(t+timedelta(hours=1)).isoformat(),'price':price});t+=timedelta(hours=1)
            variant['tariff'].append({'available_at':issued.isoformat(),'payload':{'today':tail,'today_valid':True},'hash':'HYPOTHETICAL_TAIL_PRICE_NOT_OBSERVED'})
            scenario('hypothetical_tail_'+str(price),original['input_snapshot'],variant)
        full['plan_sensitivity']=scenarios;findings['plan_sensitivity']=summaries
    # Reference preprocessing by a separate time integral, not a raw hourly mean.
    recent=Path('/share/hec-analysis-20261023/recent.json.gz')
    if recent.exists():
        from collections import defaultdict
        import math
        with gzip.open(recent,'rt') as f:raw=json.load(f)
        ix={key:i for i,key in enumerate(raw['keys'])};bins=defaultdict(lambda:[0.,0.])
        def number(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
        for a,b in zip(raw['rows'],raw['rows'][1:]):
            ta=instant(a[0]).timestamp();tb=instant(b[0]).timestamp()
            if not 0<tb-ta<=90:continue
            house_w,ev_w=a[ix['house_power']],a[ix['ev_power']]
            if not number(house_w) or not number(ev_w) or house_w<0 or ev_w<0 or ev_w>house_w+500:continue
            while ta<tb:
                hour=int(ta//3600)*3600;stop=min(tb,hour+3600);seconds=stop-ta
                bins[hour][0]+=seconds;bins[hour][1]+=(house_w-ev_w)*seconds/3600000;ta=stop
        reference={instant(r['at']).timestamp():r for r in history['house_hours']};errors=[]
        for at,(seconds,energy) in bins.items():
            if seconds>=3420 and at in reference:
                errors.append({'at':reference[at]['at'],'seed_minus_reference_kwh':reference[at]['house_without_ev_kwh']-energy*3600/seconds})
        full['house_integral_comparison']=errors
        findings['house_integral_comparison']={'paired_hours':len(errors),
            'mae_kwh':mean(abs(r['seed_minus_reference_kwh']) for r in errors) if errors else None,
            'bias_kwh':mean(r['seed_minus_reference_kwh'] for r in errors) if errors else None,
            'hours_abs_error_gt_0_5kwh':sum(abs(r['seed_minus_reference_kwh'])>.5 for r in errors)}
    import random
    rng=random.Random(624);violations=0;maximum=0.
    for envelope in [False,True]:
        battery=Battery(history['battery_model'],envelope)
        for _ in range(2500):
            soc=rng.uniform(11,99);before=battery.available(soc)
            mid,accepted,loss=battery.charge_dc(soc,rng.uniform(0,12))
            after,taken=battery.discharge_dc(mid,rng.uniform(0,12),15)
            residual=abs(battery.available(after)-(before+accepted-loss-taken));maximum=max(maximum,residual)
            violations+=residual>1e-8 or after<min(soc,15)-1e-8
    findings['real_battery_curve_balance']={'cases':5000,'violations':violations,'max_abs_residual_kwh':maximum}
    full['findings']=findings
    (out/'probes-full.json').write_text(json.dumps(full,ensure_ascii=False,indent=2))
    (out/'probes-summary.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2))
    print(json.dumps(findings,ensure_ascii=False))


if __name__=='__main__':main()
