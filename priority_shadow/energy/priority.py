"""Persisted dual-priority night replay. Pure allocations; no device/service API."""
from __future__ import annotations
from datetime import datetime, timezone
import math
from . import night
from .core import TZ, VERSION, instant, digest
from .store import pack, unpack
from .power_allocation import allocate_power

HELPER='input_select.nocni_stinova_priorita'
LABELS={'Elektromobil':'ev','Baterie SolaX':'battery'}
POLICY='night-priority-v9-partial-dual-targets'
ASSUMPTIONS={'phase_limit_a':22,'breaker_a':25,'power_factor':.9,
             'charge_efficiency':.9,'battery_usable_kwh':10.4,
             'ev_min_phase_a':6,'fast_report_limit_seconds':90,
             'phase_current_verified':False,'pv_forecast_measurement_boundary_verified':False,'bms_and_inverter_limits_verified':False,'battery_capacity_source':'catalogue_not_calibrated',
             'ev_request_source':'measured_wallbox_power_no_future_demand',
             'phase_balance_tolerance_w':500,
             'grid_model':'house_without_ev_plus_allocated_ev_and_battery_no_generation_credit'}
EXTRA={'inverter_run_mode':'sensor.solax_run_mode','forecast_tomorrow':'sensor.solcast_pv_forecast_forecast_tomorrow',
       'priority':HELPER,'ev_energy_total':'sensor.solax_api_charge_added_total',
       'battery_out_today':'sensor.solax_battery_output_energy_today',
       'battery_in_today':'sensor.solax_battery_input_energy_today'}
for i in (1,2,3):
    EXTRA[f'ev_l{i}_w']=f'sensor.solax_api_charge_power_l{i}'
    EXTRA[f'grid_l{i}_a_reported']=f'sensor.solax_api_grid_current_l{i}'


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS priority_sessions(day TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS priority_runs(day TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS priority_samples(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS priority_samples_day ON priority_samples(day,at);
    CREATE TABLE IF NOT EXISTS priority_summaries(day TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS priority_events(at TEXT PRIMARY KEY,payload BLOB NOT NULL);''')


def value(points,key):
    p=points.get(key,{})
    return p.get('value') if p.get('quality') in ('valid','text') else None


def numeric(points,key,age=90):
    return key in points and night.valid(points,key,age)


def expected_unit(key):
    if key.endswith('_w'):return 'W'
    if key.endswith('_v') or key=='battery_v':return 'V'
    if key.endswith('_a') or key.endswith('_a_reported'):return 'A'
    if key in ('battery_soc','ev_soc','ev_target_soc'):return '%'
    if key in ('forecast_today','forecast_tomorrow','ev_energy_total','battery_out_today','battery_in_today'):return 'kWh'
    return None


def checked_points(states,at):
    by={s['entity_id']:s for s in states};out={}
    for key,eid in {**night.IDS,**EXTRA}.items():
        state=by.get(eid);p=night.point(state,at);unit=(state or {}).get('attributes',{}).get('unit_of_measurement');wanted=expected_unit(key)
        p.update(unit=unit,entity_id=eid)
        if wanted and unit!=wanted:
            p['quality']='unit_mismatch';p['expected_unit']=wanted
        elif wanted and p['quality']=='text':p['quality']='invalid_numeric'
        if p['quality']=='valid':
            v=p['value']
            if ((wanted=='%' and not 0<=v<=100) or (wanted=='kWh' and v<0) or (wanted=='A' and abs(v)>100)
                    or (key.startswith('forecast_') and not 0<=v<100)
                    or (wanted=='V' and not (100<v<500 if key=='battery_v' else 180<v<260))):p['quality']='out_of_range'
        out[key]=p
    return out


def same_local_day(point,at):
    try:return instant(point['last_reported']).astimezone(TZ).date()==instant(at).astimezone(TZ).date()
    except (KeyError,ValueError,TypeError,AttributeError):return False


def input_quality(points,at=None):
    rows=[]
    labels={'ev_w':'Wallbox · příkon','ev_soc':'Auto · SOC','ev_connected':'Auto · kabel','ev_limit_a':'Wallbox · limit','battery_soc':'Baterie · SOC','battery_dc_w':'Baterie · výkon DC','battery_v':'Baterie · napětí DC','battery_limit_a':'Baterie · limit DC','forecast_today':'FVE · dnes','forecast_tomorrow':'FVE · zítra'}
    for i in (1,2,3):labels.update({f'grid_l{i}_a':f'Proud L{i}',f'grid_voltage_l{i}_v':f'Napětí sítě L{i}',f'voltage_l{i}_v':f'Napětí měniče L{i} · náhradní',
                                  f'grid_l{i}_w':f'Výkon sítě L{i}',f'inverter_l{i}_w':f'Výkon měniče L{i}',f'ev_l{i}_w':f'Výkon auta L{i}'})
    for key,label in labels.items():
        p=points.get(key,{})
        ttl=10800 if key in ('battery_soc','ev_soc') else 7200 if key=='battery_v' else 7*86400 if key in ('ev_limit_a','battery_limit_a') else 26*3600 if key.startswith('forecast_') else 90
        usable=night.valid(points,key,ttl) if key!='ev_connected' else p.get('quality')=='text' and p.get('age_seconds') is not None and 0<=p['age_seconds']<ttl
        q=p.get('quality','missing')
        if at and key.startswith('forecast_') and usable and not same_local_day(p,at):usable=False;q='wrong_day'
        if q in ('valid','text') and not usable:q='stale'
        rows.append({'key':key,'label':label,'entity_id':p.get('entity_id'),'value':p.get('value'),'unit':p.get('unit'),
                     'age_seconds':p.get('age_seconds'),'max_age_seconds':ttl,'quality':q,'usable':usable,'last_reported':p.get('last_reported'),
                     'report_source':p.get('report_source')})
    return {'rows':rows,'unusable_count':sum(not r['usable'] for r in rows),'freshness_basis':'HA last_reported, not physical device heartbeat'}


def effective_session(store,day,at,points,require_soc_plan=False):
    from .soc_runtime import session_plan
    from .soc_planner import POLICY as SOC_POLICY
    prior_run=_get(store,'priority_runs',day)
    legacy_run=bool(prior_run and not prior_run.get('soc_plan_required',False))
    def planned(base):
        if legacy_run:return base
        proposal=session_plan(store,day,at)
        if not proposal:
            if require_soc_plan or base.get('planning_source'):
                return {**base,'planning_source':SOC_POLICY,'target_soc_pct':None,
                        'soc_plan_valid':False,'soc_plan_status':'missing_invalid_or_expired_soc_plan'}
            return base
        old_model=base.get('battery_energy_model') or (prior_run or {}).get('assumptions',{}).get('battery_energy_model')
        new_model=proposal['battery_energy_model']
        if old_model and old_model.get('source_hash')!=new_model.get('source_hash'):
            return {**base,'target_soc_pct':None,'soc_plan_valid':False,'soc_plan_status':'energy_model_changed_mid_session'}
        return {**base,'planning_source':proposal['policy'],
                'original_table_target_soc_pct':base.get('original_table_target_soc_pct',base.get('target_soc_pct')),
                'target_soc_pct':proposal['target_soc_pct'],'soc_plan_decision_hash':proposal['decision_hash'],
                'soc_plan_issued_at':proposal['issued_at'],'battery_energy_model':new_model,
                'soc_plan_status':proposal['status'],'soc_plan_valid':True,
                'ev_deficit_ac_kwh':proposal.get('ev_deficit_ac_kwh'),
                'demand_fully_met':proposal.get('demand_fully_met'),
                'priority_alternatives':proposal.get('priority_alternatives'),
                'reserve_soc_approved':proposal['assumptions'].get('reserve_soc_approved')}
    saved=_get(store,'priority_sessions',day)
    if saved:return planned(saved) if require_soc_plan or saved.get('planning_source') else saved
    original=_get(store,'night_sessions',day)
    if original and original.get('status')=='captured' and original.get('forecast_kwh') is not None:
        candidate=planned(original)
        if candidate.get('soc_plan_valid'):
            with store.db:store.db.execute('INSERT OR IGNORE INTO priority_sessions VALUES(?,?)',(day,pack(candidate)))
        return candidate
    candidate=night.build_session(store,day,at,points)
    if candidate['status']=='captured':
        candidate=planned(candidate)
        candidate['recovery_of_missing_capture']=bool(original)
        if not require_soc_plan or candidate.get('soc_plan_valid'):
            with store.db:store.db.execute('INSERT OR IGNORE INTO priority_sessions VALUES(?,?)',(day,pack(candidate)))
        return candidate
    return original or candidate


def allocate(points,at,session,model_soc,priority):
    """Replace actual EV, never add EV twice. Model ignores generation credit."""
    local=instant(at).astimezone(TZ)
    active=180<=local.hour*60+local.minute<300
    forecast=session.get('forecast_kwh') if session else None
    target=session.get('target_soc_pct') if session else None
    alternative=(session.get('priority_alternatives') or {}).get(priority) if session else None
    alternative_valid=True
    if alternative is not None:
        target=alternative.get('target_soc_pct')
        alternative_valid=alternative.get('status') in ('conditional_shadow_plan','partial_shadow_plan') and alternative.get('horizon_complete') is True
    energy_model=session.get('battery_energy_model') if session else None
    forbid=forecast is None or forecast<30
    rows=[];bad=[]
    for i in (1,2,3):
        voltage_key=f'grid_voltage_l{i}_v' if f'grid_voltage_l{i}_v' in points and numeric(points,f'grid_voltage_l{i}_v') else f'voltage_l{i}_v'
        keys=[f'grid_l{i}_w',f'inverter_l{i}_w',voltage_key]
        good=all(numeric(points,k) for k in keys)
        u=value(points,keys[2])
        good=good and u is not None and 180<u<260
        if good:
            g,inv,u=(value(points,k) for k in keys)
            ev=value(points,f'ev_l{i}_w') if numeric(points,f'ev_l{i}_w') else None
            house=max(0,inv-g);base=max(0,house-max(0,ev)) if ev is not None else None
            limit=22*u*.9
            rows.append({'phase':i,'voltage_v':u,'house_w':round(house,1),'ev_w':ev,
                         'base_w':round(base,1) if base is not None else None,'house_balance_w':inv-g,'grid_w':g,'voltage_source':voltage_key,'room_w':round(max(0,limit-house),1),
                         'budget_w':max(0,limit-base) if base is not None else None,'grid_current_reported_a':value(points,f'grid_l{i}_a_reported'),
                         'model_current_a':round(house/(u*.9),2),'report_age_s':max(points[k]['age_seconds'] for k in keys)})
        else:
            bad.extend(k for k in keys if not numeric(points,k))
            rows.append({'phase':i,'voltage_v':u,'voltage_source':voltage_key,'house_w':None,'ev_w':value(points,f'ev_l{i}_w'),
                         'grid_w':value(points,f'grid_l{i}_w'),'grid_current_reported_a':value(points,f'grid_l{i}_a_reported'),
                         'model_current_a':None,'room_w':None,'budget_w':None,'report_age_s':max(points[k]['age_seconds'] for k in keys) if all(points.get(k,{}).get('age_seconds') is not None for k in keys) else None})
    for r in rows:
        key=f"grid_l{r['phase']}_a"
        current=value(points,key) if numeric(points,key) else None
        if not isinstance(current,(int,float)) or not 0<=abs(current)<=100:current=None
        r['grid_current_a']=current
        r['current_headroom_a']=round(22-abs(current),2) if current is not None else None
        r['current_report_age_s']=points.get(key,{}).get('age_seconds')
        r['power_to_va_ratio']=round(abs(r['grid_w'])/(r['voltage_v']*abs(current)),3) if current and r.get('grid_w') is not None and r.get('voltage_v') else None
    out={'priority':priority,'active':active,'phase':rows,'forecast_kwh':forecast,'target_soc_pct':target,
         'forbid_discharge':forbid,'battery_model_soc_pct':model_soc,'ev_ac_w':None,'battery_ac_w':None,
         'grid_model_w':None,'binding_phase':None,'reason':None,'device_actions':0,'live_ready':False,
         'missing_inputs':sorted(set(bad)),'ev_ready_by_status':'not_estimated_without_calibrated_energy_model'}
    if energy_model:out['battery_energy_model']=energy_model
    reason='outside_window' if not active else 'missing_frozen_forecast' if forecast is None else None
    if active and session and (session.get('soc_plan_valid') is False or not alternative_valid):reason='invalid_soc_plan'
    if reason is None and (bad or any(r['house_w'] is None for r in rows)):reason='invalid_phase_input'
    if reason is None and any(r['house_balance_w'] < -ASSUMPTIONS['phase_balance_tolerance_w'] for r in rows):reason='inconsistent_house_balance'
    if reason is None and (not numeric(points,'ev_w') or any(not numeric(points,f'ev_l{i}_w') for i in (1,2,3))):reason='invalid_ev_input'
    if reason is None and not 0<=value(points,'ev_w')<=25000:reason='invalid_ev_input'
    if reason is None and any(r['base_w']>22*r['voltage_v']*.9 for r in rows):reason='base_load_over_limit'
    if reason is None and any(r['ev_w']<0 or r['ev_w']>r['house_w']+500 for r in rows):reason='inconsistent_ev_phases'
    if reason is None and target and (model_soc is None or not 0<=model_soc<=100):reason='invalid_battery_soc'
    if reason is None and target is None:reason='missing_frozen_forecast'
    if reason is None and target>0 and model_soc<target:
        if not (numeric(points,'battery_v',7200) and numeric(points,'battery_limit_a',7*86400)):
            reason='invalid_battery_limit'
        elif not (100<value(points,'battery_v')<500 and 0<=value(points,'battery_limit_a')<=100):
            reason='invalid_battery_limit'
    if reason:
        out['reason']=reason
        if reason=='outside_window':out.update(ev_ac_w=0,battery_ac_w=0,grid_model_w=None)
        return out
    budget=3*min(r['budget_w'] for r in rows)
    out['binding_phase']=min(rows,key=lambda r:r['budget_w'])['phase']
    ev_request=max(0,value(points,'ev_w'))
    # Three phase sum must agree with actual EV; no replacement from mismatched feeds.
    if abs(sum(r['ev_w'] for r in rows)-ev_request)>max(500,ev_request*.1):
        out['reason']='inconsistent_ev_phases';return out
    if ev_request>1000 and max(r['ev_w'] for r in rows)-min(r['ev_w'] for r in rows)>max(500,ev_request*.1):
        out['reason']='unsupported_ev_phase_layout';return out
    battery_request=0
    if target>0 and model_soc<target:
        if energy_model:
            from .soc_energy import coordinate_remaining
            eta=energy_model['grid_charge_efficiency']
            need=coordinate_remaining(energy_model,model_soc,target)
            battery_request=min(value(points,'battery_limit_a')*value(points,'battery_v')/eta,
                                need*1000/eta*3600/night.INTERVAL)
        else:
            battery_request=min(value(points,'battery_limit_a')*value(points,'battery_v')/.9,
                                (target-model_soc)/100*10.4*1000/.9*3600/night.INTERVAL)
    min_ev=6*sum(r['voltage_v'] for r in rows)
    # This is a power replay, not an actuator: do not manufacture deferred energy
    # by rounding a fully feasible measured EV demand down to 100 W steps.
    bat,ev=allocate_power(budget,battery_request,ev_request,min_ev,priority)
    for r in rows:
        r['planned_w']=round(r['base_w']+(ev+bat)/3,1)
        r['planned_model_a']=round(r['planned_w']/(r['voltage_v']*.9),2)
    out.update(ev_ac_w=ev,battery_ac_w=bat,grid_model_w=round(sum(r['planned_w'] for r in rows)),
               ev_measured_request_w=ev_request,
               ev_allocation_mode='idle' if ev_request==0 else 'follow_measured_demand' if abs(ev-ev_request)<1e-6 else 'limited_model',
               ev_setting_limit_a=value(points,'ev_limit_a') if numeric(points,'ev_limit_a',7*86400) else None,
               ev_reallocated_w=max(0,ev_request-ev),
               reason='forecast_no_charge' if target==0 else 'target_reached' if model_soc>=target else
                      'battery_first' if priority=='battery' else 'ev_first')
    return out


def empty_model(soc):
    return {'soc_pct':soc,'ev_kwh_ac':0.,'battery_kwh_ac':0.,'grid_kwh_ac':0.,
            'ev_reallocated_kwh':0.,'covered_s':0.,'invalid_s':0.,'coverage_fingerprint':'',
            'target_limited_intervals':0}


def advance(model,previous,dt,interval=None):
    if not previous or not previous.get('active') or not 0<dt<=30:return
    if previous.get('ev_ac_w') is None or previous.get('battery_ac_w') is None:
        model['invalid_s']+=dt;return
    fingerprint=model.get('coverage_fingerprint','' if model['covered_s']==0 else None)
    model['coverage_fingerprint']=digest([fingerprint,interval]) if fingerprint is not None and interval else None
    model['covered_s']+=dt
    # A delayed observation must not continue charging beyond the model target.
    # Model a stop within the interval and account for the same capped AC energy
    # in both battery and grid totals. No freed power is reassigned retrospectively.
    battery_w=previous['battery_ac_w'];target=previous.get('target_soc_pct');soc=model['soc_pct']
    if soc is not None and target is not None and target>0:
        energy_model=previous.get('battery_energy_model')
        if energy_model:
            from .soc_energy import coordinate_remaining
            cap=coordinate_remaining(energy_model,soc,target)/energy_model['grid_charge_efficiency']*3600000/dt
        else:cap=max(0,target-soc)/100*10.4/.9*3600000/dt
        if battery_w>cap:
            battery_w=cap;model['target_limited_intervals']=model.get('target_limited_intervals',0)+1
    powers={**previous,'battery_ac_w':battery_w,'grid_model_w':previous.get('grid_model_w',0)-previous['battery_ac_w']+battery_w}
    for field,key in [('ev_kwh_ac','ev_ac_w'),('battery_kwh_ac','battery_ac_w'),
                      ('grid_kwh_ac','grid_model_w'),('ev_reallocated_kwh','ev_reallocated_w')]:
        model[field]+=powers.get(key,0)*dt/3600000
    if model['soc_pct'] is not None:
        energy_model=previous.get('battery_energy_model')
        if energy_model and target and battery_w>0:
            from .soc_energy import advance_coordinate
            model['soc_pct']=advance_coordinate(energy_model,model['soc_pct'],battery_w*dt/3600000,target)
        elif not energy_model:model['soc_pct']=min(100,model['soc_pct']+battery_w*dt/3600000*.9/10.4*100)


def comparison_status(models):
    if not any(m['covered_s']>0 for m in models.values()):return 'no_coverage'
    if any(m['covered_s']>0 and not m.get('coverage_fingerprint') for m in models.values()):return 'coverage_identity_unverified'
    return 'same_covered_intervals' if len({(m['covered_s'],m.get('coverage_fingerprint','')) for m in models.values()})==1 else 'unequal_coverage'


def comparison_context(session):
    if not session:return 'missing_forecast'
    if session.get('target_soc_pct') is None:
        return 'missing_forecast' if session.get('forecast_kwh') is None else 'invalid_soc_plan'
    if session.get('soc_plan_status')=='partial_shadow_plan':return 'partial_ev_service'
    return 'battery_no_request' if session['target_soc_pct']==0 else 'battery_target_present'


def closed_days(store,at):
    """Bounded catch-up, including a previous night after a midnight restart."""
    schema(store.db)
    local=instant(at).astimezone(TZ);today=local.date().isoformat()
    return [r[0] for r in store.db.execute('''SELECT r.day FROM priority_runs r
        LEFT JOIN priority_summaries s ON s.day=r.day WHERE s.day IS NULL
        AND (r.day<? OR (r.day=? AND ?)) ORDER BY r.day LIMIT 7''',
        (today,today,local.hour*60+local.minute>=300))]


def _get(store,table,day):
    row=store.db.execute(f'SELECT payload FROM {table} WHERE day=?',(day,)).fetchone()
    return unpack(row[0]) if row else None


def observe(store,states,at,require_soc_plan=False):
    from . import automation_context
    schema(store.db)
    points=checked_points(states,at)
    choice=LABELS.get(value(points,'priority'))
    local=instant(at).astimezone(TZ);day=local.date().isoformat()
    minute=local.hour*60+local.minute;active=180<=minute<300
    event=store.db.execute('SELECT payload FROM priority_events ORDER BY at DESC LIMIT 1').fetchone()
    last=unpack(event[0]) if event else None
    if not last or last.get('priority')!=choice:
        with store.db:store.db.execute('INSERT OR IGNORE INTO priority_events VALUES(?,?)',
            (at,pack({'at':at,'priority':choice,'raw_option':value(points,'priority'),'source':HELPER,'device_actions':0})))
    session=effective_session(store,day,at,points,require_soc_plan) if active else None
    run=_get(store,'priority_runs',day) if active else None
    if active and run is None:
        soc=value(points,'battery_soc') if numeric(points,'battery_soc',10800) else None
        run={'day':day,'started_at':at,'policy':POLICY,'version':VERSION,'assumptions':ASSUMPTIONS,
             'soc_plan_required':require_soc_plan,
             'soc_initialized_at':at if soc is not None else None,'models':{k:empty_model(soc) for k in ('ev','battery','selected')},'previous':None,
             'observed_ev_kwh_ac':0.,'observed_covered_s':0.,'gap_s':0.,'sample_count':0}
        if (session or {}).get('battery_energy_model'):
            run['assumptions']={**ASSUMPTIONS,'battery_usable_kwh':None,
                'battery_capacity_source':'empirical_energy_soc_curve_July_fit',
                'battery_energy_model':session['battery_energy_model'],
                'grid_conversion_efficiency_verified':False}
    if run and run.get('soc_plan_required') and (session or {}).get('soc_plan_valid'):
        model=session.get('battery_energy_model')
        if model and not run['assumptions'].get('battery_energy_model') and all(m['battery_kwh_ac']==0 for m in run['models'].values()):
            run['assumptions']={**ASSUMPTIONS,'battery_usable_kwh':None,
                'battery_capacity_source':'empirical_energy_soc_curve_July_fit',
                'battery_energy_model':model,'grid_conversion_efficiency_verified':False}
    variants={}
    if run:
        if run.get('soc_initialized_at') is None and all(m['soc_pct'] is None for m in run['models'].values()) and numeric(points,'battery_soc',10800):
            for m in run['models'].values():m['soc_pct']=value(points,'battery_soc')
            run['soc_initialized_at']=at
        previous=run.get('previous');dt=(instant(at)-instant(previous['at'])).total_seconds() if previous else 0
        if previous and 0<dt<=30:
            for k,m in run['models'].items():advance(m,previous['variants'].get(k),dt,(previous['at'],at))
            if previous.get('actual_ev_w') is not None:
                run['observed_ev_kwh_ac']+=max(0,previous['actual_ev_w'])*dt/3600000
                run['observed_covered_s']+=dt
        elif previous:run['gap_s']+=max(0,dt)
        for k in ('ev','battery','selected'):
            p=choice if k=='selected' else k
            variants[k]=allocate(points,at,session,run['models'][k]['soc_pct'],p)
            if k=='selected' and choice is None:
                variants[k].update(reason='missing_priority',ev_ac_w=None,battery_ac_w=None,grid_model_w=None)
        run['sample_count']+=1
        row={'at':at,'day':day,'priority':choice,'session':session,'variants':variants,'inputs':points,
             'actual_ev_w':value(points,'ev_w') if numeric(points,'ev_w') else None,
             'models':{k:dict(m) for k,m in run['models'].items()},'soc_initialized_at':run.get('soc_initialized_at'),'observed_ev_kwh_ac':run['observed_ev_kwh_ac'],
             'observed_covered_s':run['observed_covered_s'],'gap_s':run['gap_s']}
        run['previous']={k:row[k] for k in ('at','variants','actual_ev_w')}
        with store.db:
            store.db.execute('INSERT OR IGNORE INTO priority_samples VALUES(?,?,?)',(at,day,pack(row)))
            store.db.execute('INSERT OR REPLACE INTO priority_runs VALUES(?,?)',(day,pack(run)))
    else:
        variants={'selected':allocate(points,at,None,value(points,'battery_soc'),choice)}
        row=None
    next_key='forecast_today' if minute<300 else 'forecast_tomorrow'
    next_f=value(points,next_key) if numeric(points,next_key,26*3600) and same_local_day(points[next_key],at) else None
    if not isinstance(next_f,(int,float)) or not 0<=next_f<100:next_f=None
    history=[unpack(r[0]) for r in store.db.execute('SELECT payload FROM priority_summaries ORDER BY day DESC LIMIT 14')]
    result={'at':at,'version':VERSION,'mode':'observe_only','device_actions':0,'priority':choice,
            'active':active,'collecting_window':night.window(at),'selected':variants['selected'],
            'alternatives':{k:v for k,v in variants.items() if k!='selected'},
            'input_quality':input_quality(points,at),'actual':{k:value(points,k) for k in ('house_w','ev_w','ev_soc','ev_target_soc','ev_connected',
                      'battery_soc','battery_dc_w','battery_v','battery_a','battery_limit_a','inverter_mode','inverter_run_mode','manual_mode',
                      'main_breaker_limit_a','battery_out_today','battery_in_today')},
            'next_forecast_kwh':next_f,'next_target_soc_pct':night.target_for(next_f) if next_f is not None else None,
            'session':session,'progress':row,'history':history,'assumptions':run.get('assumptions',ASSUMPTIONS) if run else ASSUMPTIONS,
            'readiness':['phase_current_available_pending_ev_load_validation','actuator_response_not_verified','no_actuator_adapter'],
            'ev_parameters_status':'future_soc_and_deadline_not_estimated',
            'comparison_status':comparison_status(row['models']) if row else 'waiting_for_night',
            'comparison_context':comparison_context(session),
            'automation_context':automation_context.snapshot(states,at),
            'note':'Alternatives replay measured EV demand. Reallocated EV kWh are not proven unmet departure energy. See battery model provenance; no measured savings.'}
    return result


def finish(store,day):
    schema(store.db)
    if _get(store,'priority_summaries',day):return _get(store,'priority_summaries',day)
    run=_get(store,'priority_runs',day)
    if not run:return None
    rows=[unpack(r[0]) for r in store.db.execute('SELECT payload FROM priority_samples WHERE day=? ORDER BY at',(day,))]
    if not rows:return None
    last=rows[-1];prev=run['previous'];end=instant(f'{day}T05:00:00'+instant(last['at']).astimezone(TZ).strftime('%z'))
    dt=(end-instant(prev['at'])).total_seconds()
    if 0<dt<=30:
        for k,m in run['models'].items():advance(m,prev['variants'].get(k),dt,(prev['at'],end.isoformat()))
        if prev.get('actual_ev_w') is not None:
            run['observed_ev_kwh_ac']+=max(0,prev['actual_ev_w'])*dt/3600000
            run['observed_covered_s']+=dt
    current_max={f'L{i}':max((abs(x['variants']['selected']['phase'][i-1]['grid_current_a']) for x in rows if x['variants']['selected']['phase'][i-1].get('grid_current_a') is not None),default=None) for i in (1,2,3)}
    result={'day':day,'version':VERSION,'policy':POLICY,'started_at':run['started_at'],
            'sample_count':run['sample_count'],'models':run['models'],'soc_initialized_at':run.get('soc_initialized_at'),
            'uncovered_seconds':{k:max(0,7200-m['covered_s']) for k,m in run['models'].items()},
            'comparison_status':comparison_status(run['models']),
            'comparison_context':comparison_context(last['session']),
            'observed_ev_kwh_ac':run['observed_ev_kwh_ac'],'observed_covered_s':run['observed_covered_s'],
            'gap_s':run['gap_s'],'session':last['session'],
            'priority_changes':sum(rows[i]['priority']!=rows[i-1]['priority'] for i in range(1,len(rows))),
            'reasons':{r:sum(x['variants']['selected']['reason']==r for x in rows) for r in {x['variants']['selected']['reason'] for x in rows}},
            'limits':run.get('assumptions',ASSUMPTIONS),'phase_max_measured_a':current_max,'device_actions':0}
    with store.db:store.db.execute('INSERT OR IGNORE INTO priority_summaries VALUES(?,?)',(day,pack(result)))
    return result


def recent(store,day=None):
    schema(store.db)
    if day is None:
        row=store.db.execute('SELECT day FROM priority_runs ORDER BY day DESC LIMIT 1').fetchone()
        day=row[0] if row else None
    rows=[unpack(r[0]) for r in store.db.execute('SELECT payload FROM priority_samples WHERE day=? ORDER BY at',(day,))] if day else []
    return {'day':day,'samples':rows,'summary':_get(store,'priority_summaries',day) if day else None,
            'history':[unpack(r[0]) for r in store.db.execute('SELECT payload FROM priority_summaries ORDER BY day DESC LIMIT 14')]}
