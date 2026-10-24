"""RPi companion integration for immutable SOC proposals and local calibration."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
from .core import TZ, instant, digest, VERSION
from .store import pack, unpack
from . import night, priority, weather
from .pricing import valid
from .soc_calibration import Household, fit_pv, validate_household, pre_window,archived_weather
from .soc_history import read_gzip, atomic_gzip, minute_hours, fit_ev, covered_forecast
from .soc_planner import plan, window, solar_periods, POLICY as SOC_POLICY, PLAN_STATUSES
from .soc_evidence import seal,verify
from .phase_budget import from_db as phase_budget_from_db

SHARE=Path('/share/home-energy-priority-shadow')
MAIN=Path('/share/home-energy-coordinator/evidence.sqlite')
HISTORY=SHARE/'soc-history.json.gz'
IDS={
 'house_w':'sensor.solax_house_load','ev_w':'sensor.solax_api_charge_power_total',
 'ev_counter':'sensor.solax_api_charge_added_total','ev_soc':'sensor.tesla_model_y_juniper_uroven_baterie',
 'soc':'sensor.solax_battery_capacity','pv_counter':'sensor.solax_today_s_solar_energy',
 'pv_w':'sensor.solax_pv_power_total','inverter_w':'sensor.solax_inverter_power',
 'export_limit_w':'number.solax_export_control_user_limit',
 'outdoor_c':'sensor.current_outdoor_temperature_bt1_30002',
 'sunrise':'sensor.sun_next_rising','battery_temperature':'sensor.solax_battery_temperature',
 'tesla_limit_a':'number.tesla_model_y_juniper_nabijeci_proud',
 'tariff':'sensor.cez_indi_cenik',
 'forecast_day3':'sensor.solcast_pv_forecast_forecast_day_3',
 'battery_discharge_limit_a':'number.solax_battery_discharge_max_current',
}


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS soc_observations(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS soc_observation_day ON soc_observations(day,at);
    CREATE TABLE IF NOT EXISTS soc_decisions(at TEXT PRIMARY KEY,day TEXT NOT NULL,hash TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS soc_decision_day ON soc_decisions(day,at);
    CREATE TABLE IF NOT EXISTS soc_model_versions(hash TEXT PRIMARY KEY,at TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS soc_reviews(day TEXT PRIMARY KEY,payload BLOB NOT NULL);''')


def _number(by,eid,at,unit,ttl=180):
    s=by.get(eid);p=night.point(s,at)
    if (p['quality']!='valid' or not valid(p.get('value')) or p['age_seconds'] is None
            or not 0<=p['age_seconds']<ttl or (s or {}).get('attributes',{}).get('unit_of_measurement')!=unit):return None
    return p['value']


def observation(states,at):
    by={s['entity_id']:s for s in states};row={'at':at,'software_version':VERSION}
    for key in ('house_w','ev_w','pv_w','inverter_w','export_limit_w'):
        row[key]=_number(by,IDS[key],at,'W')
    for key in ('ev_counter','pv_counter'):row[key]=_number(by,IDS[key],at,'kWh',26*3600)
    for key in ('soc','ev_soc'):row[key]=_number(by,IDS[key],at,'%',10800)
    row['outdoor_c']=_number(by,IDS['outdoor_c'],at,'°C',7200)
    return row


def inputs(states,at,ev_model,options,weather_rows,use_temperature):
    by={s['entity_id']:s for s in states};pp=priority.checked_points(states,at)
    result={'soc':_number(by,IDS['soc'],at,'%',10800),
            'outdoor_c':_number(by,IDS['outdoor_c'],at,'°C',7200),
            'battery_temperature_c':_number(by,IDS['battery_temperature'],at,'°C',7200),
            'sunrise':by.get(IDS['sunrise'],{}).get('state'),
            'priority':priority.LABELS.get(priority.value(pp,'priority')),
            'phase_voltages':[],'weather_rows':weather_rows,'use_temperature':use_temperature,
            'ev_calibration':{k:v for k,v in ev_model.items() if k!='sessions'},
            'reserve_soc_approved':None,'reserve_soc':15,
            'reserve_source':'empirical_energy_map_reference_not_control_policy'}
    approved=options.get('planner_approved_reserve_soc')
    if approved not in (None,''):
        try:approved=float(approved)
        except (TypeError,ValueError):approved=None
        if valid(approved) and 0<=approved<=95:
            result.update(reserve_soc=approved,reserve_soc_approved=approved,reserve_source='explicit_app_option')
    for i in (1,2,3):
        eid=night.IDS[f'grid_voltage_l{i}_v'];v=_number(by,eid,at,'V')
        if v is None:v=_number(by,night.IDS[f'voltage_l{i}_v'],at,'V')
        result['phase_voltages'].append(v)
    v=_number(by,night.IDS['battery_v'],at,'V',7200);a=_number(by,night.IDS['battery_limit_a'],at,'A',7*86400)
    result['battery_charge_max_dc_kw']=min(10.,v*a/1000) if valid(v) and valid(a) and 100<v<500 and 0<=a<=100 else None
    discharge_a=_number(by,IDS['battery_discharge_limit_a'],at,'A',7*86400)
    result['battery_discharge_max_dc_kw']=min(10.,v*discharge_a/1000) if valid(v) and valid(discharge_a) and 100<v<500 and 0<=discharge_a<=100 else None
    cap=options.get('planner_inverter_ac_limit_kw')
    try:cap=float(cap) if cap not in (None,'') else None
    except (ValueError,TypeError):cap=None
    result['inverter_ac_limit_kw']=cap if valid(cap) and 0<cap<=100 else None
    result['inverter_limit_source']='explicit_app_option' if result['inverter_ac_limit_kw'] else 'unconfirmed'
    evsoc=priority.value(pp,'ev_soc') if priority.numeric(pp,'ev_soc',10800) else None
    evtarget=priority.value(pp,'ev_target_soc') if priority.numeric(pp,'ev_target_soc',7*86400) else None
    cable_point=pp.get('ev_connected',{})
    cable=priority.value(pp,'ev_connected') if cable_point.get('age_seconds') is not None and 0<=cable_point['age_seconds']<10800 else None
    amps=priority.value(pp,'ev_limit_a') if priority.numeric(pp,'ev_limit_a',7*86400) else None
    carlimit=_number(by,IDS['tesla_limit_a'],at,'A',7*86400)
    if valid(carlimit):amps=min(amps,carlimit) if valid(amps) else carlimit
    volts=result['phase_voltages']
    result['ev_max_ac_kw']=amps*sum(volts)/1000 if valid(amps) and all(valid(x) for x in volts) else None
    if cable=='off' or valid(evsoc) and valid(evtarget) and evsoc>=evtarget:
        result['ev_need_ac_kwh']=0.;result['ev_max_ac_kw']=result['ev_max_ac_kw'] or 0.
        result['ev_requirement_source']='currently_disconnected_or_target_already_met'
    elif cable=='on' and valid(evsoc) and valid(evtarget) and valid(ev_model.get('ac_kwh_per_soc_pct')):
        result['ev_need_ac_kwh']=max(0.,evtarget-evsoc)*ev_model['ac_kwh_per_soc_pct']
        result['ev_requirement_source']='observed_ac_per_soc_candidate_assuming_connected_until_05'
    else:
        result['ev_need_ac_kwh']=None;result['ev_requirement_source']='missing_ev_requirement_or_calibration'
    result['ev_soc']=evsoc;result['ev_target_soc']=evtarget;result['ev_connected']=cable
    result['planning_phase_load_assumption']='balanced_future_house_not_breaker_protection'
    return result


def _versions(store,at):
    rows=store.db.execute('''SELECT v.entity,v.available_at,v.hash,o.payload FROM versions v
       JOIN objects o ON o.hash=v.hash WHERE v.available_at<=? AND v.available_at>=? ORDER BY v.id DESC''',
       (at,(instant(at)-timedelta(hours=48)).isoformat()))
    result={'solar':[],'tariff':[]}
    for entity,available,key,blob in rows:
        value={'available_at':available,'hash':key,'payload':unpack(blob)}
        if entity==IDS['tariff']:result['tariff'].append(value)
        elif entity.startswith('sensor.solcast_pv_forecast_forecast_'):result['solar'].append(value)
    return result


def _external_context(now):
    """Read portable main evidence only; never open it through the mutable Store."""
    if not MAIN.exists():return [],{'status':'main_evidence_unavailable'}
    db=sqlite3.connect('file:'+str(MAIN)+'?mode=ro',uri=True)
    try:
        row=db.execute("SELECT v.available_at,o.payload FROM versions v JOIN objects o ON o.hash=v.hash WHERE v.entity LIKE 'weather_forecast:%:hourly' AND v.available_at<=? ORDER BY v.id DESC LIMIT 1",(now.isoformat(),)).fetchone()
        forecasts=[]
        if row and 0<=(now-instant(row[0])).total_seconds()<8*3600:
            payload=unpack(row[1])
            if payload.get('units',{}).get('temperature_unit')=='°C':forecasts=payload.get('forecast',[])
        cutoff=(now-timedelta(days=60)).isoformat()
        rows=[dict(zip(('at','power_w','energy_total_kwh','soc'),r)) for r in db.execute('SELECT at,power_w,energy_total_kwh,soc FROM ev_obs WHERE at>=? AND at<=? ORDER BY at',(cutoff,now.isoformat()))]
        return forecasts,fit_ev(rows)
    finally:db.close()


def weather_versions(db,now,days=16):
    cutoff=(now-timedelta(days=days)).isoformat()
    return [{'available_at':at,'hash':key,'payload':unpack(blob)} for at,key,blob in db.execute(
        "SELECT v.available_at,v.hash,o.payload FROM versions v JOIN objects o ON o.hash=v.hash WHERE v.entity LIKE 'weather_forecast:%:hourly' AND v.available_at>=? AND v.available_at<=? ORDER BY v.id",(cutoff,now.isoformat()))]


def calibration_weather(store,now):
    result=weather_versions(store.db,now)
    if MAIN.exists():
        db=sqlite3.connect('file:'+str(MAIN)+'?mode=ro',uri=True)
        try:result+=weather_versions(db,now)
        finally:db.close()
    return list({(r['available_at'],r['hash']):r for r in result}.values())


def record_decision(store,result):
    result=seal(result)
    with store.db:store.db.execute('INSERT OR IGNORE INTO soc_decisions VALUES(?,?,?,?)',
       (result['issued_at'],result['day'],result['decision_hash'],pack(result)))
    return result


class PlannerService:
    def __init__(self,options=None):
        self.options=options or {};self.history=None;self.household=None;self.pv_models={}
        self.house_validation={};self.weather=[];self.ev_model={};self.next_refresh=0.;self.next_plan=0.;self.latest=None;self.error=None
        self.next_weather=0.;self.weather_meta={};self.weather_archive=[]

    def refresh(self,store,now):
        schema(store.db)
        if self.history is None:
            if not HISTORY.exists():raise ValueError('SOC_HISTORY_NOT_IMPORTED')
            self.history=read_gzip(HISTORY)
        # Own minute observations provide future hours and constraint flags.
        cutoff=(now-timedelta(days=3)).astimezone(TZ).date().isoformat()
        raw=[unpack(r[0]) for r in store.db.execute('SELECT payload FROM soc_observations WHERE day>=? ORDER BY at',(cutoff,))]
        house,actual=minute_hours(raw);today=now.astimezone(TZ).date().isoformat()
        old={r['at']:r for r in self.history['house_hours']}
        for r in house:
            if r['day']<today:old.setdefault(r['at'],r)
        self.history['house_hours']=sorted(old.values(),key=lambda r:r['at'])
        pairs={(r['target'],r['forecast_available_at'],r.get('coverage_schema')):r for r in self.history['pv_pairs']}
        for r in actual:
            target=instant(r['target']);day=target.astimezone(TZ).date()
            if day.isoformat()>=today:continue
            decision=pre_window(day.isoformat())
            versions=_versions(store,decision.astimezone(timezone.utc).isoformat())
            solar=solar_periods(versions['solar'],decision)
            matched=covered_forecast(r,solar)
            if matched is None:continue
            key=(r['target'],matched['forecast_available_at'],r['coverage_schema'])
            pairs.setdefault(key,{**r,**matched,'day':day.isoformat(),
                    'source':'own_minute_snapshots_and_prior_decision_archive',
                    'boundary':'native_dc_counter_times_0.966_ac_proxy'})
        self.history['pv_pairs']=list(pairs.values())
        self.history['updated_at']=now.isoformat();atomic_gzip(HISTORY,self.history)
        self.pv_models=fit_pv(self.history['pv_pairs'],now)
        self.weather_archive=calibration_weather(store,now)
        self.house_validation=validate_household(self.history['house_hours'],now,self.weather_archive)
        self.household=Household(self.history['house_hours'],now)
        try:self.weather,self.ev_model=_external_context(now)
        except (OSError,ValueError,sqlite3.Error):self.weather=[];self.ev_model={'status':'main_context_read_failed'}
        manifest={'at':now.isoformat(),'policy':SOC_POLICY,'version':VERSION,
                  'history_source':self.history['source'],'house_hours':len(self.history['house_hours']),
                  'pv_pairs':len(self.history['pv_pairs']),'pv_models':self.pv_models,
                  'house_validation':self.house_validation,'house_data_hash':self.household.source_hash,'battery_model':self.history['battery_model'],
                  'ev_calibration':self.ev_model,'device_actions':0}
        key=digest(manifest)
        with store.db:store.db.execute('INSERT OR IGNORE INTO soc_model_versions VALUES(?,?,?)',(key,now.isoformat(),pack(manifest)))
        self.model_key=key;self.next_refresh=time.monotonic()+6*3600

    def observe(self,store,states,at,client=None):
        now=instant(at);schema(store.db)
        row=observation(states,at);minute=now.replace(second=0,microsecond=0).isoformat()
        with store.db:store.db.execute('INSERT OR IGNORE INTO soc_observations VALUES(?,?,?)',
             (minute,now.astimezone(TZ).date().isoformat(),pack(row)))
        day,start,end,horizon=window(now)
        if self.options.get('planner_enabled',True) is not True:
            self.latest=record_decision(store,{'status':'disabled','device_actions':0,'day':day,
                'issued_at':at,'target_soc_pct':None,'mode':'observe_only','live_ready':False})
            return view(self.latest)
        try:
            if self.history is None or self.household is None or time.monotonic()>=self.next_refresh:self.refresh(store,now)
            if client and time.monotonic()>=self.next_weather:
                weather.poll(store,client,states,{'weather_types':['hourly'],'weather_interval_seconds':3600},now)
                self.next_weather=time.monotonic()+3600
            r=store.db.execute("SELECT v.available_at,v.hash,o.payload FROM versions v JOIN objects o ON o.hash=v.hash WHERE v.entity LIKE 'weather_forecast:%:hourly' AND v.available_at<=? ORDER BY v.id DESC LIMIT 1",(at,)).fetchone()
            candidates=self.weather_archive+([{'available_at':r[0],'hash':r[1],'payload':unpack(r[2])}] if r else [])
            current=archived_weather(candidates,now)
            self.weather=current['payload'].get('forecast',[]) if current else []
            self.weather_meta={'available_at':current['available_at'],'source_hash':current['hash']} if current else {}
            # New day, selected priority or pre-window freeze trigger immediately.
            choice=next((s['state'] for s in states if s['entity_id']==priority.HELPER),None)
            freeze=start-timedelta(minutes=5)<=now<start
            force=self.latest is None or self.latest.get('day')!=day or choice!=getattr(self,'last_choice',None)
            force=force or freeze and not self.latest.get('pre_window_capture',False)
            if time.monotonic()>=self.next_plan or force:
                snapshot=inputs(states,at,self.ev_model,self.options,self.weather,self.house_validation.get('use_temperature',False))
                snapshot['weather_provenance']=self.weather_meta
                snapshot['power_budget']=phase_budget_from_db(store.db,at)
                result=plan(now,snapshot,self.history,self.pv_models,self.household,_versions(store,at))
                result['pre_window_capture']=freeze;result['model_version_hash']=self.model_key
                result['house_validation']=self.house_validation
                result['calibration_summary']={'house_hours':len(self.history['house_hours']),
                     'pv_pairs':len(self.history['pv_pairs']),'accepted_pv_models':sum(v['accepted'] for v in self.pv_models.values()),
                     'pv_models':self.pv_models,'history_last_day':self.household.last_day,
                     'battery_fit_period':self.history['battery_model']['fit_period']}
                result=record_decision(store,result)
                self.latest=result;self.last_choice=choice;self.next_plan=time.monotonic()+(600 if result['status'] in PLAN_STATUSES else 60)
            self.error=None
            return view(self.latest)
        except Exception as e:
            self.error=type(e).__name__;self.next_refresh=time.monotonic()+600
            error={'status':'calculation_unavailable','error_code':self.error,'target_soc_pct':None,
                    'day':day,'issued_at':at,'mode':'observe_only','device_actions':0,
                    'input_snapshot':locals().get('snapshot'),
                    'model_version_hash':getattr(self,'model_key',None),
                    'fallback':'legacy_table_reference_only_no_control_change'}
            self.latest=record_decision(store,error)
            return view(self.latest)


def view(result):
    if not result:return {'status':'waiting_for_calculation','device_actions':0}
    keys=('power_budget','attainable_soc_05','target_shortfall_soc_pct','target_reached_all_scenarios','target_semantics','schema_version','policy','issued_at','day','status','target_soc_pct','decision_reason','warnings',
          'window_start','window_end','horizon_end','horizon_complete','current_soc','soc_at_03_estimate','soc_at_05_estimate',
          'night_charge_ac_kwh','first_sustained_pv_cover_at','sunrise','objective','selection_method','season',
          'priority_alternatives','ev_requirement','ev_deficit_ac_kwh','demand_fully_met','allocation_policy','economic_comparison','model_hash','model_version_hash','decision_hash','decision_hash_schema','night_plan_eligible','assumptions','missing_inputs','corrections','pre_window_capture')
    out={k:result.get(k) for k in keys if k in result}
    out.update(mode='observe_only',device_actions=0,live_ready=False)
    if 'priority_alternatives' in out:
        out['priority_alternatives']={k:{f:v for f,v in x.items() if f!='selected'} for k,x in out['priority_alternatives'].items()}
    selected=result.get('selected') or {}
    out['selected_scenarios']=selected.get('scenarios',{})
    out['candidates']=[{'target_soc_pct':r['target_soc_pct'],'feasible':r.get('feasible_all_scenarios'),
         'soc_at_05':r['scenarios']['central']['soc_at_05'],'target_reached_all_scenarios':all(v.get('target_reached',True) for v in r['scenarios'].values()),'regret_czk':r.get('max_regret_czk'),'ev_deficit_ac_kwh':r['scenarios']['central'].get('unserved_ev_ac_kwh'),'grid_charge_ac_kwh':r['scenarios']['central']['grid_charge_ac_kwh'],
         'import_cost_czk':r['scenarios']['central']['import_cost_czk'],
         'terminal_credit_czk':r['scenarios']['central']['terminal_inventory_credit_czk']} for r in result.get('candidates',[])]
    summary=result.get('calibration_summary') or {}
    out['calibration_summary']={k:v for k,v in summary.items() if k!='pv_models'}
    out['house_validation']=result.get('house_validation')
    grouped={};first=None
    for r in result.get('timeline',[]):
        start=r.get('start',r['at']);end=r.get('end',(instant(start)+timedelta(hours=r['hours'])).isoformat())
        if instant(start).astimezone(TZ).date().isoformat()!=result.get('day'):continue
        if first is None and 'soc_start' in r:
            first={'at':start,'hours':0.,'house_ac_kwh':0.,'pv_ac_kwh':0.,'soc':r['soc_start']}
        key=int(instant(start).timestamp()//3600)
        g=grouped.setdefault(key,{'at':end,'hours':0.,'house_ac_kwh':0.,'pv_ac_kwh':0.,'soc':None})
        for k in ('hours','house_ac_kwh','pv_ac_kwh'):g[k]+=r[k]
        g['at']=end;g['soc']=r.get('soc_end',r['soc'])
    out['profile']=([first] if first else [])+list(grouped.values())
    out['profile_time_basis']='interval_end_with_initial_state'
    return out


def session_plan(store,day,at):
    """Latest decision only: an invalid newer decision revokes the previous plan."""
    try:
        rows=store.db.execute('SELECT at,hash,payload FROM soc_decisions WHERE day=? AND at<=? ORDER BY at DESC LIMIT 1',(day,at))
        for stored_at,key,blob in rows:
            r=unpack(blob)
            if (r.get('status') in PLAN_STATUSES and r.get('target_soc_pct') is not None
                    and r.get('horizon_complete') is True and r.get('day')==day and r.get('issued_at')==stored_at):
                if (0<=(instant(at)-instant(r['issued_at'])).total_seconds()<=1800
                        and verify(r)['verified'] and key==r.get('decision_hash')):return r
    except sqlite3.OperationalError:pass
    return None


def review(store,audits,at):
    """Observed outcomes alongside unexecuted proposals, never measured savings."""
    schema(store.db)
    for actual in (audits or {}).get('days',[])[:7]:
        day=actual.get('day')
        if not day or store.db.execute('SELECT 1 FROM soc_reviews WHERE day=?',(day,)).fetchone():continue
        # Share the exact latest/hash/complete-horizon gate with night replay.
        # UTC arithmetic also selects the second 02:55 on an autumn change.
        cutoff=pre_window(day);start=cutoff+timedelta(minutes=5)
        proposal=session_plan(store,day,start.isoformat())
        if not proposal or instant(proposal['issued_at'])<cutoff:continue
        observations=[unpack(x[0]) for x in store.db.execute('SELECT payload FROM soc_observations WHERE day=? ORDER BY at',(day,))]
        hours,pv=minute_hours(observations)
        if len(hours)<12 or actual.get('pv_kwh') is None:continue
        expected=defaultdict(lambda:[0.,0.])
        for slot in proposal.get('forecast_periods',[]):
            h=int(slot['start']//3600)*3600;duration=(slot['end']-slot['start'])/3600
            expected[h][0]+=slot['house_kw']*duration;expected[h][1]+=duration
        errors=[]
        for h in hours:
            t=instant(h['at']).timestamp();entry=expected.get(t)
            if entry and entry[1]>=.9:errors.append(abs(h['house_without_ev_kwh']-entry[0]/entry[1]))
        daylight={int(x['start']//3600)*3600 for x in proposal.get('forecast_periods',[])
                  if x['raw_pv_kw']>.1 and datetime.fromtimestamp(x['start'],TZ).date().isoformat()==day}
        constrained=any(x.get('constrained') is True for x in pv
                        if int(instant(x['target']).timestamp()) in daylight)
        comparison_solar=[{'start':x['start'],'end':x['end'],'kw':x['pv_ac_kw'],
                           'available_at':proposal['issued_at'],'source_hash':proposal['decision_hash']}
                          for x in proposal.get('forecast_periods',[])]
        common=[]
        for actual_hour in pv:
            matched=covered_forecast(actual_hour,comparison_solar)
            if matched is not None:common.append((actual_hour,matched))
        covered={int(instant(x['target']).timestamp()) for x,_ in common
                 if x.get('coverage_seconds',0)>=3600-1e-6 and x.get('constrained') is False}
        constraint_known=bool(daylight) and daylight<=covered
        common_forecast=sum(f['forecast_ac_kwh'] for _,f in common)
        common_actual=sum(x['actual_ac_proxy_kwh'] for x,_ in common)
        estimate=sum(x['pv_ac_kw']*(x['end']-x['start'])/3600 for x in proposal.get('forecast_periods',[])
              if datetime.fromtimestamp(x['start'],TZ).date().isoformat()==day)
        value={'day':day,'reviewed_at':at,'decision_hash':proposal['decision_hash'],
               'target_soc_pct':proposal['target_soc_pct'],'actual_soc_05':actual.get('soc_05'),
               'actual_night_charge_dc_kwh':actual.get('night_charge_dc_kwh'),
               'forecast_ac_kwh':estimate,'actual_dc_kwh':actual['pv_kwh'],
               'actual_ac_proxy_kwh':actual['pv_kwh']*.966,'constraint_observed':constrained,
               'constraint_status':'observed' if constrained else 'clear_in_covered_daylight' if constraint_known else 'unknown_coverage',
               'review_schema':'soc-review-valid-common-intervals-v2',
               'pv_comparison_basis':'common_observed_intervals',
               'comparison_forecast_ac_kwh':common_forecast if common else None,
               'comparison_actual_ac_proxy_kwh':common_actual if common else None,
               'pv_common_hours':sum(x['coverage_seconds'] for x,_ in common)/3600,
               'pv_error_ac_proxy_kwh':common_actual-common_forecast if constraint_known and not constrained else None,
               'house_common_hours':len(errors),'house_mae_kw':sum(errors)/len(errors) if errors else None,
               'plan_executed':False,'measured_savings_czk':None,
               'note':'Actual SOC is operational context, not an error of an unexecuted charging plan.'}
        with store.db:store.db.execute('INSERT OR IGNORE INTO soc_reviews VALUES(?,?)',(day,pack(value)))
    return [unpack(x[0]) for x in store.db.execute('SELECT payload FROM soc_reviews ORDER BY day DESC LIMIT 7')]
