"""Instantaneous max-fill SHADOW allocation; no actuator or economic SOC gate.

Balanced AC battery power, phase-specific measured EV requests. The measured
P/(U*I) is a consistency proxy, not independently calibrated power factor.
Historical envelopes never replace current measurements. No transient margin
is claimed for control. Only the selected inverter-grid current mapping is used.
"""
import math
from .core import instant,TZ

POLICY='instant-max-fill-v1'

def session(store,day,at,points):
    from . import priority,night
    from .soc_energy import Battery
    from .store import unpack
    base=priority._get(store,'night_sessions',day) or night.build_session(store,day,at,points)
    row=store.db.execute('SELECT payload FROM soc_model_versions WHERE at<=? ORDER BY at DESC LIMIT 1',(at,)).fetchone()
    prior=priority._get(store,'priority_runs',day)
    frozen=(prior or {}).get('assumptions',{}).get('battery_energy_model')
    model=frozen or (Battery(unpack(row[0])['battery_model']).snapshot() if row else None)
    return {**base,'allocation_policy':POLICY,'target_soc_pct':100,'soc_plan_valid':True,
            'soc_plan_status':'instant_max_fill','economic_target_is_advisory':True,
            'battery_energy_model':model,'model_available_at':unpack(row[0]).get('at') if row else None,
            'power_budget':None}

def allocate(points,at,session,model_soc,priority):
    from .priority import numeric,value
    local=instant(at).astimezone(TZ);active=180<=local.hour*60+local.minute<300
    forecast=(session or {}).get('forecast_kwh');model=(session or {}).get('battery_energy_model')
    out={'allocation_policy':POLICY,'priority':priority,'active':active,'target_soc_pct':100,
         'forecast_kwh':forecast,'forbid_discharge':forecast is None or forecast<30,
         'battery_model_soc_pct':model_soc,'phase':[],'device_actions':0,'live_ready':False,
         'ev_ac_w':None,'battery_ac_w':None,'grid_model_w':None,'binding_phase':None,
         'reason':None,'missing_inputs':[],'economic_target_is_advisory':True,
         'ev_ready_by_status':'not_estimated_without_departure_requirement',
         'limits':{'breaker_a':25,'ev_phase_limit_a':16,'transient_margin_a':0,
                   'margin_status':'shadow_only_not_control_approval',
                   'inverter_ac_limit_status':'unverified_not_manufactured',
                   'battery_layout':'balanced_AC_power',
                   'power_factor_status':'instantaneous_measurement_consistency_proxy'}}
    if model:out['battery_energy_model']=model
    if not active:out.update(reason='outside_window',ev_ac_w=0.,battery_ac_w=0.);return out
    if priority not in ('ev','battery'):out['reason']='missing_priority';return out
    for i in (1,2,3):
        keys=[f'grid_l{i}_a',f'grid_voltage_l{i}_v',f'grid_l{i}_w',f'inverter_l{i}_w',f'ev_l{i}_w']
        bad=[k for k in keys if not numeric(points,k)]
        # Keep the unit/source boundary explicit; do not substitute the wallbox API grid current.
        if bad:out['missing_inputs']+=bad;continue
        amps,u,g,inv,ev=[value(points,k) for k in keys]
        if not(all(math.isfinite(v) for v in (amps,u,g,inv,ev)) and 180<u<260 and 0<=abs(amps)<=100 and 0<=ev<=25000):
            out['missing_inputs']+=keys;continue
        if abs(amps)<1 and abs(g)>u*abs(amps)*1.05+50:
            out['missing_inputs'].append(f'grid_l{i}_a');continue
        ratio=abs(g)/(u*abs(amps)) if abs(amps)>=1 else None
        if ratio is not None and not 0<=ratio<=1.05:
            out['missing_inputs'].append(f'grid_l{i}_a');continue
        # Nízký poměr P/UI není chybějící proud. Bez ověřeného účiníku použijeme proudovou trojúhelníkovou mez.
        pf=min(1.,ratio) if ratio is not None and ratio>=.5 else None
        house=inv-g;base=house-ev
        if base< -100:out['missing_inputs'].append(f'inconsistent_house_l{i}');continue
        base=max(0.,base)
        if pf is None:
            # Triangle bound covers current background plus removal of measured EV/inverter.
            base_a=abs(amps)+(abs(inv)+ev)/u
            limit_w=max(0.,25-base_a)*u+base
            pf=1.;proxy='low_current_triangle_bound'
        else:limit_w=25*u*pf;proxy='measured_P_UI'
        if ev>16*u+max(100,ev*.03):out['missing_inputs'].append(f'ev_over_16A_l{i}');continue
        out['phase'].append({'phase':i,'voltage_v':u,'voltage_source':f'grid_voltage_l{i}_v',
          'grid_w':g,'house_w':house,'house_balance_w':house,'base_w':base,'ev_w':ev,
          'grid_current_a':amps,'current_headroom_a':25-abs(amps),'current_report_age_s':points[keys[0]]['age_seconds'],
          'grid_current_entity_id':points[keys[0]].get('entity_id'),
          'grid_current_reported_a':value(points,f'grid_l{i}_a_reported'),
          'api_grid_current_role':'diagnostic_only_never_fallback',
          'power_to_va_ratio':ratio,'power_factor':pf,'proxy_method':proxy,
          'current_offset_a':base_a-base/u if proxy=='low_current_triangle_bound' else 0.,
          'limit_a':25,'limit_w':limit_w,'budget_w':max(0.,limit_w-base),
          'room_w':max(0.,limit_w-house),'model_current_a':house/(u*pf),
          'report_age_s':max(points[k]['age_seconds'] for k in keys)})
    if out['missing_inputs'] or len(out['phase'])!=3:out['reason']='invalid_phase_input';return out
    rows=out['phase']
    if not numeric(points,'ev_w') or abs(sum(r['ev_w'] for r in rows)-value(points,'ev_w'))>max(500,value(points,'ev_w')*.1):out['reason']='inconsistent_ev_phases';return out
    if any(r['base_w']>r['limit_w'] or r['base_w']/(r['voltage_v']*r['power_factor'])+r['current_offset_a']>25 for r in rows):out['reason']='base_load_over_limit';return out
    if not numeric(points,'battery_soc',10800) or model_soc is None or not 0<=model_soc<=100:out['reason']='invalid_battery_soc';return out
    if not model:out['reason']='missing_battery_energy_model';return out
    if not (numeric(points,'battery_v',7200) and numeric(points,'battery_limit_a',7*86400)):
        out['reason']='invalid_battery_limit';return out
    bv,ba=value(points,'battery_v'),value(points,'battery_limit_a');eta=model.get('grid_charge_efficiency')
    if not(100<bv<500 and 0<=ba<=100 and isinstance(eta,(int,float)) and .5<=eta<=1):out['reason']='invalid_battery_limit';return out
    from .soc_energy import coordinate_remaining
    request=min(bv*ba/eta,coordinate_remaining(model,model_soc,100)*3600000/(15*eta))
    out['battery_dc_limit_w']=bv*ba
    out['grid_charge_efficiency_assumption']=eta
    # Optional configured, independently sourced AC limit; unknown is labelled above.
    ac_limit=(session or {}).get('inverter_charge_ac_limit_w')
    if ac_limit is not None:
        if not isinstance(ac_limit,(int,float)) or not math.isfinite(ac_limit) or ac_limit<0:out['reason']='invalid_inverter_limit';return out
        request=min(request,ac_limit);out['limits']['inverter_ac_limit_status']='explicit_session_limit'
    # Replay the measured demand under the 16 A setting; meter tolerance is
    # checked above, not converted into an artificial loss of EV energy.
    ev_req=[r['ev_w'] for r in rows]
    out['limits']['ev_setting_measurement_tolerance']='max(100W,3pct)_per_phase_not_actuator_permission'
    def ev_fit(bat):
        f=min([1.]+[max(0.,r['budget_w']-bat/3)/e for r,e in zip(rows,ev_req) if e>0])
        es=[e*f for e in ev_req]
        # Do not produce sub-6A charging on an active phase.
        if any(0<e<6*r['voltage_v']-1e-6 for r,e in zip(rows,es)):es=[0.]*3
        return es
    if priority=='battery':
        bat=min(request,3*min(r['budget_w'] for r in rows));bat=math.floor((bat+1e-8)/100)*100
        evs=ev_fit(bat)
    else:
        evs=ev_fit(0);bat=min(request,3*min(max(0.,r['budget_w']-e) for r,e in zip(rows,evs)))
        bat=math.floor((bat+1e-8)/100)*100
    for r,e in zip(rows,evs):
        r['planned_ev_w']=e;r['planned_w']=r['base_w']+e+bat/3
        r['planned_model_a']=r['planned_w']/(r['voltage_v']*r['power_factor'])+r['current_offset_a']
        if r['planned_model_a']>25+1e-7:raise ValueError('INSTANT_PHASE_LIMIT_EXCEEDED')
    binding=min(rows,key=lambda r:r['budget_w']-r['planned_ev_w'])['phase']
    out.update(ev_ac_w=sum(evs),battery_ac_w=bat,grid_model_w=sum(r['planned_w'] for r in rows),
      binding_phase=binding,ev_reallocated_w=max(0.,value(points,'ev_w')-sum(evs)),
      ev_measured_request_w=value(points,'ev_w'),ev_allocation_mode='follow_measured_demand' if abs(sum(evs)-value(points,'ev_w'))<1e-6 else 'limited_model',
      reason='target_reached' if model_soc>=100 else 'ev_first' if priority=='ev' else 'battery_first',
      limiting_factors=['battery_full' if model_soc>=100 else 'phase_or_device_limit','100W_downward_quantization'])
    return out
