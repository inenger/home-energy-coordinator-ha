"""Pure 03-05 SOC optimizer. Scenario regret, conserved energy, no actuator API."""
from datetime import datetime, time, timedelta, timezone
import math
from copy import deepcopy
from .core import TZ, instant, digest
from .pricing import valid
from .soc_energy import Battery
from .soc_calibration import correction, season
from .power_allocation import allocate_power
from .soc_evidence import seal
from .phase_budget import limits, checked

POLICY='soc-energy-scenarios-v5-attainable-targets'
PLAN_STATUSES=('conditional_shadow_plan','partial_shadow_plan')


def window(now):
    local=now.astimezone(TZ);day=local.date()+(timedelta(days=1) if local.hour>=5 else timedelta())
    start=datetime.combine(day,time(3),TZ).astimezone(timezone.utc)
    end=datetime.combine(day,time(5),TZ).astimezone(timezone.utc)
    horizon=datetime.combine(day+timedelta(days=1),time(3),TZ).astimezone(timezone.utc)
    return day.isoformat(),start,end,horizon


def solar_periods(versions,now):
    chosen={};conflicts=set()
    for version in versions:
        try:available=instant(version['available_at'])
        except (KeyError,TypeError,ValueError):continue
        if available>now or (now-available).total_seconds()>30*3600:continue
        p=version.get('payload') or {}
        if p.get('dataCorrect') is False or p.get('unit_of_measurement')!='kWh':continue
        rows=p.get('detailedForecast') or p.get('detailedHourly') or []
        hours=.5 if p.get('detailedForecast') else 1.
        try:total=sum(r['pv_estimate']*hours for r in rows);declared=float(p['state'])
        except (TypeError,KeyError,ValueError):continue
        if not valid(total) or not valid(declared) or abs(total-declared)>max(.15,.03*declared):continue
        for r in rows:
            try:t=instant(r['period_start']).timestamp();power=r['pv_estimate']
            except (TypeError,KeyError,ValueError):continue
            if not valid(power) or not 0<=power<=30:continue
            row={'start':t,'end':t+hours*3600,'kw':power,'low_kw':r.get('pv_estimate10'),
                 'high_kw':r.get('pv_estimate90'),'available_at':available.isoformat(),
                 'source_hash':version.get('hash') or digest(p)}
            old=chosen.get(t)
            if old is None or instant(old['available_at'])<available:chosen[t]=row;conflicts.discard(t)
            elif instant(old['available_at'])==available and abs(old['kw']-power)>.001:conflicts.add(t)
    return [v for k,v in sorted(chosen.items()) if k not in conflicts]


def prices(versions,now):
    result=[]
    for version in versions:
        try:available=instant(version['available_at'])
        except (KeyError,TypeError,ValueError):continue
        if available>now or (now-available).total_seconds()>30*3600:continue
        p=version.get('payload') or {}
        for kind in ('today','tomorrow'):
            if p.get(kind+'_valid') is False:continue
            for r in p.get(kind) or []:
                try:a=instant(r['start']).timestamp();b=instant(r['end']).timestamp();v=r['price']
                except (KeyError,TypeError,ValueError):continue
                if not valid(v) or not 0<b-a<=3600:continue
                result.append({'start':a,'end':b,'price':v,'available_at':available.timestamp(),
                               'source_hash':version.get('hash') or digest(p)})
    return result


def _price(rows,t):
    found=[r for r in rows if r['start']<=t<r['end']]
    if not found:return None
    newest=max(r['available_at'] for r in found);values={r['price'] for r in found if r['available_at']==newest}
    return values.pop() if len(values)==1 else None


def _solar(rows,t):
    found=[r for r in rows if r['start']<=t<r['end']]
    if not found:return None
    return max(found,key=lambda r:r['available_at'])


def _temperature(rows,t,current):
    matches=[r for r in rows if abs(instant(r['datetime']).timestamp()-t)<=3600 and valid(r.get('temperature'))]
    return min(matches,key=lambda r:abs(instant(r['datetime']).timestamp()-t))['temperature'] if matches else current


def slots(now,inputs,household,pv_models,solar,tariff,horizon):
    out=[];t=now.timestamp();warnings=set();stop_reason=None
    while t<horizon.timestamp():
        row=_solar(solar,t);price=_price(tariff,t)
        if row is None or price is None:
            stop_reason='missing_hourly_solar' if row is None else 'missing_hourly_tariff';break
        end=min(horizon.timestamp(),(math.floor(t/1800)+1)*1800,row['end'],
                min((r['end'] for r in tariff if r['start']<=t<r['end']),default=t+1800))
        if end<=t:stop_reason='invalid_time_partition';break
        at=datetime.fromtimestamp(t,timezone.utc)
        temperature=_temperature(inputs.get('weather_rows',[]),t,inputs.get('outdoor_c'))
        prediction=household.predict(at,temperature if inputs.get('use_temperature') else None)
        if prediction is None:stop_reason='missing_household_profile';break
        key,cal=correction(pv_models,at,instant(row['available_at']))
        pv=row['kw']*cal['factor']
        low=cal.get('low_multiplier');high=cal.get('high_multiplier')
        if not valid(low):low=row['low_kw']/pv if valid(row.get('low_kw')) and pv>0 else 1.;warnings.add('provider_scenarios_not_calibrated_probabilities')
        if not valid(high):high=row['high_kw']/pv if valid(row.get('high_kw')) and pv>0 else 1.;warnings.add('provider_scenarios_not_calibrated_probabilities')
        if key is None:warnings.add('solar_calibration_insufficient_for_some_periods')
        if not inputs.get('weather_rows'):warnings.add('temperature_persistence_or_seasonal_fallback')
        cap=inputs.get('inverter_ac_limit_kw')
        pv_low=max(0.,pv*min(1.,low));pv_high=max(pv,pv*high)
        if valid(cap) and cap>0:pv=min(pv,cap);pv_low=min(pv_low,cap);pv_high=min(pv_high,cap)
        else:warnings.add('inverter_ac_limit_unconfirmed')
        out.append({'start':t,'end':end,'hours':(end-t)/3600,'price':price,
                    'house_kw':prediction['central_kw'],'house_low_kw':prediction['low_kw'],
                    'house_high_kw':prediction['high_kw'],'pv_ac_kw':pv,
                    'pv_low_kw':pv_low,'pv_high_kw':pv_high,
                    'raw_pv_kw':row['kw'],'solar_model':key,'solar_factor':cal['factor'],
                    'forecast_available_at':row['available_at'],'load_samples':prediction['samples'],
                    'temperature_c':temperature,'forecast_source_hash':row['source_hash']})
        t=end
    return out,sorted(warnings),stop_reason


def _night_room(inputs,house_kw):
    context=checked(inputs.get('power_budget'))
    shares=inputs.get('house_phase_shares') or context['house_phase_shares']
    return max(0.,3*min(w/1000-house_kw*s for w,s in zip(limits(inputs['phase_voltages'],context),shares)))


def simulate(rows,inputs,model,target,scenario,night_start,night_end,terminal_price):
    stress=scenario=='low_pv_high_load';bright=scenario=='high_pv_low_load'
    battery=Battery(model,envelope=stress,dc_efficiency=model.get('dc_cycle_low') if stress else None)
    eta_grid=model.get('grid_efficiency_range',[.85,.95])[0 if stress else 1] if stress or bright else model.get('grid_efficiency',.9)
    eta_ac=model.get('ac_discharge_efficiency',.977);eta_solar=model.get('solar_ac_dc_efficiency',.966)
    soc=inputs['soc'];reserve=inputs['reserve_soc'];ev_remaining=inputs['ev_need_ac_kwh']
    ev_import_cost=0.
    import_kwh=cost=grid_charge=solar_to_battery=solar_to_ev=discharged=spill=stored_loss=0.
    profile=[];soc03=soc05=None;first_cover=None;cover_start=None
    charge_limit=inputs['battery_charge_max_dc_kw'];discharge_limit=inputs['battery_discharge_max_dc_kw']
    ac_cap=inputs.get('inverter_ac_limit_kw')
    ac_cap=ac_cap if valid(ac_cap) and ac_cap>0 else None
    for row in rows:
        dt=row['hours'];t=row['start'];night=night_start.timestamp()<=t<night_end.timestamp()
        house=row['house_high_kw'] if stress else row['house_low_kw'] if bright else row['house_kw']
        pv=row['pv_low_kw'] if stress else row['pv_high_kw'] if bright else row['pv_ac_kw']
        if ac_cap is not None:pv=min(pv,ac_cap)
        house_e=house*dt;pv_e=pv*dt;direct=min(house_e,pv_e);deficit=house_e-direct;surplus=pv_e-direct
        if soc03 is None and abs(t-night_start.timestamp())<1e-5:soc03=soc
        before_soc=soc;charge_ac=ev_ac=ev_grid_ac=pv_ev_ac=discharge_ac=pv_charge_ac=0.;segments=[]
        if night:
            remaining=dt;elapsed=0.
            # Constant instantaneous powers between target/EV-completion events.
            # A short EV session is a real >=6 A segment, never a subminimum
            # average alongside a battery already at its maximum for all time.
            for _ in range(12):
                if remaining<=1e-10:break
                full_need=battery.dc_to_target(soc,100)
                pv_dc_kw=min(surplus/dt/eta_solar,charge_limit) if full_need>1e-9 else 0.
                target_need=battery.dc_to_target(soc,max(soc,target)) if target else 0.
                request=(max(0.,charge_limit-pv_dc_kw)/eta_grid*1000) if target_need>1e-9 else 0.
                ev_request=inputs['ev_max_ac_kw']*1000 if ev_remaining>1e-9 else 0.
                bat_w,ev_w=allocate_power(_night_room(inputs,house)*1000,request,ev_request,
                                         6*sum(inputs['phase_voltages']),inputs['priority'])
                bat_kw=bat_w/1000;ev_kw=ev_w/1000;rate_dc=bat_kw*eta_grid+pv_dc_kw
                # Net AC import is independent of the conservative phase budget.
                # Use only PV left after the simultaneous DC battery flow.
                pv_ev_kw=min(ev_kw,max(0.,surplus/dt-pv_dc_kw*eta_solar))
                ev_grid_kw=ev_kw-pv_ev_kw
                duration=remaining
                if ev_kw>0:duration=min(duration,ev_remaining/ev_kw)
                if rate_dc>0:
                    duration=min(duration,full_need/rate_dc)
                    if target_need>1e-9:duration=min(duration,target_need/rate_dc)
                if duration<=1e-12:raise ValueError('INVALID_CHARGE_EVENT_DURATION')
                soc,accepted,loss=battery.charge_dc(soc,rate_dc*duration,100)
                if abs(accepted-rate_dc*duration)>1e-7:raise ValueError('CHARGE_PORT_ENERGY_MISMATCH')
                charge_ac+=bat_kw*duration;ev_ac+=ev_kw*duration;pv_charge_ac+=pv_dc_kw*eta_solar*duration
                ev_grid_ac+=ev_grid_kw*duration;pv_ev_ac+=pv_ev_kw*duration
                ev_remaining=max(0.,ev_remaining-ev_kw*duration);stored_loss+=loss
                segments.append({'start':datetime.fromtimestamp(t+elapsed*3600,timezone.utc).isoformat(),
                    'end':datetime.fromtimestamp(t+(elapsed+duration)*3600,timezone.utc).isoformat(),
                    'hours':duration,'ev_ac_kw':ev_kw,'battery_grid_dc_kw':bat_kw*eta_grid,
                    'ev_grid_ac_kw':ev_grid_kw,'pv_to_ev_ac_kw':pv_ev_kw,
                    'battery_pv_dc_kw':pv_dc_kw,'battery_total_dc_kw':rate_dc,
                    'room_ac_kw':_night_room(inputs,house)})
                elapsed+=duration;remaining=max(0.,remaining-duration)
            if remaining>1e-9:raise ValueError('UNRESOLVED_CHARGE_EVENTS')
            grid_charge+=charge_ac;solar_to_battery+=pv_charge_ac;solar_to_ev+=pv_ev_ac
            surplus=max(0.,surplus-pv_charge_ac-pv_ev_ac)
        elif deficit>0:
            # PV and discharge use the same confirmed AC output budget.
            headroom=max(0.,ac_cap-pv) if ac_cap is not None else float('inf')
            soc,dc=battery.discharge_dc(soc,min(deficit/eta_ac,discharge_limit*dt,headroom*dt/eta_ac),reserve)
            discharge_ac=dc*eta_ac;discharged+=discharge_ac;deficit-=discharge_ac
        if not night and surplus>0:
            soc,dc,loss=battery.charge_dc(soc,min(surplus/eta_solar,charge_limit*dt),100)
            solar_to_battery+=dc*eta_solar;surplus-=dc*eta_solar;stored_loss+=loss
            pv_charge_ac=dc*eta_solar
        bought=max(0.,deficit)+charge_ac+ev_grid_ac
        import_kwh+=bought;cost+=bought*row['price'];ev_import_cost+=ev_grid_ac*row['price'];spill+=max(0.,surplus)
        if row['end']>=night_end.timestamp() and soc05 is None:soc05=soc
        cover=t>=night_end.timestamp() and pv>=house
        if cover and cover_start is None:cover_start=t
        if not cover:cover_start=None
        if cover_start is not None and row['end']-cover_start>=3600 and first_cover is None:first_cover=cover_start
        profile.append({'at':datetime.fromtimestamp(row['end'],timezone.utc).isoformat(),
                        'start':datetime.fromtimestamp(t,timezone.utc).isoformat(),
                        'end':datetime.fromtimestamp(row['end'],timezone.utc).isoformat(),'hours':dt,
                        'house_ac_kwh':house_e,'pv_ac_kwh':pv_e,'import_ac_kwh':bought,
                        'charge_grid_ac_kwh':charge_ac,'discharge_ac_kwh':discharge_ac,
                        'ev_ac_kwh':ev_ac,'pv_to_battery_ac_kwh':pv_charge_ac,
                        'ev_grid_ac_kwh':ev_grid_ac,'pv_to_ev_ac_kwh':pv_ev_ac,
                        'inverter_ac_kw':(pv_e-pv_charge_ac+discharge_ac)/dt,
                        'unused_pv_ac_kwh':max(0.,surplus),'soc':soc,'soc_start':before_soc,'soc_end':soc,
                        'price':row['price'],'charge_segments':segments})
    terminal=max(0.,battery.available(soc)-battery.available(reserve))*eta_ac*terminal_price
    # Same terminal valuation and fulfilled EV need for every candidate within
    # each scenario. This score is not a measured bill or a savings claim.
    battery_feasible=soc05 is not None and soc05>=reserve-.5
    target_reached=soc05 is not None and (target==0 or soc05>=target-.5)
    feasible=ev_remaining<=.05 and battery_feasible and target_reached
    return {'scenario':scenario,'feasible':feasible,'battery_feasible':battery_feasible,'target_reached':target_reached,
            'target_shortfall_soc_pct':max(0.,target-soc05) if soc05 is not None and target else 0.,
            'ev_import_cost_czk':ev_import_cost,'house_battery_adjusted_cost_czk':cost-terminal-ev_import_cost,'import_cost_czk':cost,'import_ac_kwh':import_kwh,
            'terminal_inventory_credit_czk':terminal,'inventory_adjusted_cost_czk':cost-terminal,
            'grid_charge_ac_kwh':grid_charge,'pv_to_battery_ac_equivalent_kwh':solar_to_battery,
            'pv_to_ev_ac_kwh':solar_to_ev,
            'discharge_ac_kwh':discharged,'unused_pv_ac_kwh':spill,'dc_storage_and_soc_envelope_loss_kwh':stored_loss,
            'soc_at_03':soc03,'soc_at_05':soc05,'soc_at_end':soc,'unserved_ev_ac_kwh':max(0.,ev_remaining),
            'first_sustained_pv_cover_at':datetime.fromtimestamp(first_cover,timezone.utc).isoformat() if first_cover else None,
            'grid_charge_efficiency_assumed':eta_grid,'battery_model_kind':battery.snapshot()['kind'],
            'timeline':profile}


def _plan(now,inputs,history,pv_models,household,versions):
    day,start,end,horizon=window(now)
    result={'schema_version':4,'policy':POLICY,'issued_at':now.isoformat(),'day':day,
            'mode':'observe_only','device_actions':0,'live_ready':False,'target_soc_pct':None,
            'window_start':start.isoformat(),'window_end':end.isoformat(),'status':'waiting_for_inputs',
            'warnings':[],'input_snapshot':deepcopy(inputs),'history_source':deepcopy(history.get('source')),
            'forecast_versions':deepcopy(versions),
            'ev_requirement':{'desired_ac_kwh':inputs.get('ev_need_ac_kwh'),
                'minimum_ac_kwh':None,'departure_at':None,
                'semantics':'desired_target_not_confirmed_departure_requirement'},
            'assumptions':{'export_revenue_not_valued':True,'no_measured_savings':True,
            'house_includes_heat_and_immersion':True,'reserve_soc_approved':inputs.get('reserve_soc_approved'),
            'reserve_reference_soc':inputs.get('reserve_soc'),'phase_mapping_verified':False,
            'ev_presence_assumed_until_05':True,'battery_held_during_cheap_window':True}}
    missing=[]
    for key in ('soc','reserve_soc','battery_charge_max_dc_kw','battery_discharge_max_dc_kw','ev_need_ac_kwh','ev_max_ac_kw'):
        if not valid(inputs.get(key)):missing.append(key)
    if inputs.get('priority') not in ('ev','battery'):missing.append('priority')
    u=inputs.get('phase_voltages')
    if not isinstance(u,list) or len(u)!=3 or any(not valid(v) or not 180<v<260 for v in u):missing.append('phase_voltages')
    if missing:result['missing_inputs']=missing;return result
    if (not 0<=inputs['soc']<=100 or not 0<=inputs['reserve_soc']<=95
            or any(inputs[k]<0 for k in ('battery_charge_max_dc_kw','battery_discharge_max_dc_kw','ev_need_ac_kwh','ev_max_ac_kw'))):
        result['missing_inputs']=['soc_range'];return result
    if not history.get('battery_model'):
        result['missing_inputs']=['battery_calibration'];return result
    result['battery_energy_model']=Battery(history['battery_model']).snapshot()
    result['calibration_context']={'pv_models':deepcopy(pv_models),'house_source_hash':getattr(household,'source_hash',None),'house_last_day':household.last_day}
    solar=solar_periods(versions.get('solar',[]),now);tariff=prices(versions.get('tariff',[]),now)
    rows,warnings,stop=slots(now,inputs,household,pv_models,solar,tariff,horizon)
    result['warnings']=warnings
    result['forecast_periods']=deepcopy(rows)
    if not rows or rows[-1]['end']<end.timestamp()+12*3600:
        result['missing_inputs']=[stop or 'insufficient_horizon'];return result
    result['horizon_end']=datetime.fromtimestamp(rows[-1]['end'],timezone.utc).isoformat()
    result['horizon_complete']=rows[-1]['end']>=horizon.timestamp()
    if not result['horizon_complete']:result['warnings'].append('preview_horizon_limited_to_available_tariff_or_forecast')
    night_prices=[r['price'] for r in rows if start.timestamp()<=r['start']<end.timestamp()]
    if not night_prices:result['missing_inputs']=['night_tariff'];return result
    terminal_price=max(0.,min(night_prices))
    result['power_budget']=deepcopy(checked(inputs.get('power_budget')))
    result['warnings'].append('phase_budget_is_shadow_estimate_not_breaker_protection')
    if result['power_budget']['status']!='empirical_shadow_candidate':result['warnings'].append('legacy_phase_budget_fallback')
    model=history['battery_model'];candidates=[]
    targets=[0]+list(range(max(5,int(math.ceil(inputs['reserve_soc']/5)*5)),96,5))
    scenarios=('central','low_pv_high_load','high_pv_low_load')
    for target in targets:
        variants={s:simulate(rows,inputs,model,target,s,start,end,terminal_price) for s in scenarios}
        candidates.append({'target_soc_pct':target,'scenarios':variants,
                           'feasible_all_scenarios':all(v['feasible'] for v in variants.values()),
                           'service_feasible_all_scenarios':all(v['battery_feasible'] and v['unserved_ev_ac_kwh']<=.05 for v in variants.values())})
    feasible=[r for r in candidates if r['service_feasible_all_scenarios']]
    compact=lambda r:{**r,'scenarios':{s:{k:v for k,v in x.items() if k!='timeline'} for s,x in r['scenarios'].items()}}
    partial=not feasible
    if partial:
        feasible=[r for r in candidates if all(v['battery_feasible'] for v in r['scenarios'].values())]
        if feasible and inputs['priority']=='ev':
            deficit=lambda r:max(v['unserved_ev_ac_kwh'] for v in r['scenarios'].values())
            least=min(deficit(r) for r in feasible)
            feasible=[r for r in feasible if deficit(r)<=least+.05]
    if not feasible:
        result.update(status='no_comparable_feasible_plan',candidates=[compact(r) for r in candidates],
                      missing_inputs=['combined_battery_and_ev_needs_not_feasible_in_window']);return result
    score='house_battery_adjusted_cost_czk' if partial else 'inventory_adjusted_cost_czk'
    best={s:min(r['scenarios'][s][score] for r in feasible) for s in scenarios}
    for r in feasible:
        r['max_regret_czk']=max(r['scenarios'][s][score]-best[s] for s in scenarios)
    winner=min(feasible,key=lambda r:(round(r['max_regret_czk'],6),
               round(max(v['unserved_ev_ac_kwh'] for v in r['scenarios'].values()),6),
               round(r['scenarios']['central']['grid_charge_ac_kwh'],6),r['target_soc_pct']))
    central=winner['scenarios']['central'];model_snapshot=Battery(model).snapshot()
    reference_forecast=sum(r['raw_pv_kw']*r['hours'] for r in rows
                           if datetime.fromtimestamp(r['start'],TZ).date().isoformat()==day)
    corrections={r['solar_model']:r['solar_factor'] for r in rows if r['solar_model']}
    target_complete=all(v['target_reached'] for v in winner['scenarios'].values())
    result.update(status='partial_shadow_plan' if partial or not target_complete else 'conditional_shadow_plan',
                  demand_fully_met=not partial and target_complete,economic_comparison='unequal_ev_service_no_savings_claim' if partial else 'equal_ev_service',
                  allocation_policy=('ev_deficit_then_battery_regret' if inputs['priority']=='ev' else 'battery_regret_then_ev_deficit') if partial else 'full_demand_minimax',
                  ev_deficit_ac_kwh={s:v['unserved_ev_ac_kwh'] for s,v in winner['scenarios'].items()},target_soc_pct=winner['target_soc_pct'],
                  night_plan_eligible=result['horizon_complete'],
                  decision_reason='skip_grid_charge' if winner['target_soc_pct']==0 else 'minimum_scenario_regret',
                  target_reached_all_scenarios=all(v['target_reached'] for v in winner['scenarios'].values()),
                  attainable_soc_05={s:v['soc_at_05'] for s,v in winner['scenarios'].items()},
                  target_shortfall_soc_pct={s:v['target_shortfall_soc_pct'] for s,v in winner['scenarios'].items()},
                  target_semantics='economic_request_under_power_constraints_not_guaranteed_soc',
                  reference_forecast_day_kwh=reference_forecast,
                  objective='grid_import_cost_with_common_terminal_inventory_value',
                  selection_method='partial_service_lexicographic' if partial else 'minimax_regret_no_assumed_scenario_probabilities',
                  terminal_price_czk_kwh=terminal_price,season=season(start),
                  current_soc=inputs['soc'],soc_at_03_estimate=central['soc_at_03'],soc_at_05_estimate=central['soc_at_05'],
                  night_charge_ac_kwh=central['grid_charge_ac_kwh'],first_sustained_pv_cover_at=central['first_sustained_pv_cover_at'],
                  sunrise=inputs.get('sunrise'),battery_energy_model=model_snapshot,
                  corrections=corrections,selected=compact(winner),
                  candidates=[compact(r) for r in candidates],timeline=central['timeline'],
                  forecast_periods=[dict(r) for r in rows],
                  input_snapshot=deepcopy(inputs),history_source=deepcopy(history.get('source')),
                  model_hash=digest({'battery':model,'pv':pv_models,'house_data_hash':getattr(household,'source_hash',None),'house_last_day':household.last_day}))
    if inputs.get('reserve_soc_approved') is None:result['warnings'].append('reserve_15pct_is_modelling_reference_not_approved_control_policy')
    result['warnings']+=['grid_charge_conversion_not_independently_calibrated','future_phase_loads_not_verified',
                         'future_heating_automation_response_not_simulated','solar_ac_reference_is_approximate',
                         'battery_temperature_effect_not_independently_identified']
    return result


def plan(now,inputs,history,pv_models,household,versions):
    result=_plan(now,inputs,history,pv_models,household,versions)
    if result.get('status') in PLAN_STATUSES:
        other='battery' if inputs['priority']=='ev' else 'ev'
        alternate=_plan(now,{**inputs,'priority':other},history,pv_models,household,versions)
        fields=('status','target_soc_pct','ev_deficit_ac_kwh','demand_fully_met','economic_comparison','allocation_policy','selected','horizon_complete','attainable_soc_05','target_shortfall_soc_pct','target_reached_all_scenarios')
        result['priority_alternatives']={inputs['priority']:{k:deepcopy(result.get(k)) for k in fields},
                                       other:{k:deepcopy(alternate.get(k)) for k in fields}}
    return seal(result)
