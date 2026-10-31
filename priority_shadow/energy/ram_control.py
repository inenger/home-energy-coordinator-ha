"""Stínový výkonový regulátor. Bez akčního adaptéru, bez zápisu registrů SolaXu.

Výstup je logický W AC požadavek a odhad A DC. Převod na konkrétní VPP paket
zůstává zablokován, dokud není ověřena hranice AC/DC a vypršení povelu.
"""
from datetime import datetime,time,timedelta,timezone
import math
from . import control_journal as legacy,priority,night
from .core import TZ,VERSION,instant,digest
from .store import pack,unpack

POLICY='volatile-power-shadow-v2'
SENSOR=legacy.SENSOR
RUN_MODE='sensor.solax_run_mode'
REMOTE_MODE='sensor.solax_modbus_power_control'
RAM_TARGET='virtual.solax_charge_ac_w'
READBACKS=(
 'sensor.solax_inverter_solax_remotecontrol_readback_mode',
 'sensor.solax_inverter_solax_remotecontrol_mode_8_pv_power_limit_readback',
 'sensor.solax_inverter_solax_remotecontrol_mode_8_battery_power_target_readback',
 'sensor.solax_inverter_solax_remotecontrol_mode_8_timeout_readback',
 'sensor.solax_inverter_solax_remotecontrol_mode_8_next_motion_readback',
)
ENTITY_IDS=(*legacy.ENTITY_IDS,RUN_MODE,REMOTE_MODE,*READBACKS,'sensor.solax_inverter_communication_health')
FAST_KEYS=tuple(k for i in (1,2,3) for k in (f'grid_l{i}_a',f'grid_voltage_l{i}_v',f'grid_l{i}_w',f'inverter_l{i}_w',f'ev_l{i}_w'))
SOLAX_KEYS=tuple(k for k in FAST_KEYS if not k.startswith('ev_'))
MAX_AGE_S=15
MAX_REPORT_SKEW_S=2
RAMP_UP_AC_W_S=100
POWER_STEP_W=100


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS ram_control_sessions(day TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS ram_control_events(id INTEGER PRIMARY KEY,day TEXT NOT NULL,at TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS ram_events_day ON ram_control_events(day,id);
    CREATE TABLE IF NOT EXISTS ram_control_samples(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS ram_samples_day ON ram_control_samples(day,at);''')


def intent(ac_w,at,expires_at=None):
    """Jediný přípustný výstup této vrstvy; nejde o HA službu ani Modbus paket."""
    if isinstance(ac_w,bool) or not isinstance(ac_w,(int,float)) or not math.isfinite(ac_w) or ac_w<0:
        raise ValueError('Invalid logical power')
    expiry=instant(expires_at) if expires_at is not None else instant(at)+timedelta(seconds=10)
    if not 0<(expiry-instant(at)).total_seconds()<=10:
        raise ValueError('Invalid logical expiry')
    return {'kind':'volatile_power_intent','logical_battery_ac_w':ac_w,'at':at,
        'storage_class':'volatile_intent_only','persistent_writes':0,'device_actions':0,
        'wire_command':None,'physical_control_ready':False,'expires_at':expiry.isoformat()}


def validate_intent(candidate):
    if not isinstance(candidate,dict) or candidate!=intent(candidate.get('logical_battery_ac_w'),candidate.get('at'),candidate.get('expires_at')):
        raise ValueError('Unknown or persistent write is forbidden')
    return candidate


def input_valid_until(points,by,window_end):
    """Absolute HA report deadlines, never a renewed measurement timestamp.

    Reusing a still valid frame may hold/reduce power, never increase it or
    count it as a new frame. Every intent ends no later than these original
    input deadlines, the window boundary, and ten seconds from its issue.
    """
    limits=[(points[k],MAX_AGE_S) for k in (*FAST_KEYS,'ev_w')]
    limits.extend((points[k],age) for k,age in
        [('battery_v',30),('battery_limit_a',7*86400),('battery_soc',10800)])
    limits.extend(({'last_reported':by[e].get('last_reported')},MAX_AGE_S)
        for e in (RUN_MODE,REMOTE_MODE,READBACKS[0]))
    return min([instant(window_end)]+[instant(p['last_reported'])+timedelta(seconds=age) for p,age in limits])


def bounded_intent(ac_w,at,valid_until):
    return validate_intent(intent(ac_w,at,min(instant(at)+timedelta(seconds=10),valid_until).isoformat()))


def capabilities(states):
    by={s['entity_id']:s for s in states}
    available=[e for e in READBACKS if by.get(e,{}).get('state') not in (None,'unknown','unavailable','')]
    return {'readback_available':available,'readback_missing':[e for e in READBACKS if e not in available],
        'wire_mapping_verified':False,'ac_dc_boundary_verified':False,'timeout_verified':False,
        'firmware_support_verified':False,'physical_control_ready':False,'eeprom_writes':0,
        'blocking_reasons':['no_actuator_adapter','wire_mapping_not_verified','power_boundary_not_verified','timeout_not_physically_verified'],
        'mode8_documented_power_boundary':'battery DC port; conversion efficiency unverified',
        'mode8_documented_duration_register':'0xA6', 'mode8_documented_next_motion_register':'0xA7',
        'mapping_review':'Mode8 direct labels for 0xA6/0xA7 must be reconciled with readback Timeout/NextMotion 0x1A6/0x1A7; no packet emitted',
        'forbidden_dynamic_targets':[legacy.CURRENT,legacy.MODE,legacy.FORCE,'unknown_storage_class']}


def inputs(states,at):
    points=priority.checked_points(states,at);by={s['entity_id']:s for s in states};errors=[];details=[]
    for key in (*FAST_KEYS,'ev_w'):
        if not priority.numeric(points,key,MAX_AGE_S):
            errors.append(key);details.append({'key':key,'entity_id':points[key].get('entity_id'),'quality':points[key].get('quality'),'age_seconds':points[key].get('age_seconds')})
    for key,age in [('battery_v',30),('battery_limit_a',7*86400),('battery_soc',10800)]:
        if not priority.numeric(points,key,age):errors.append(key)
    mode=night.point(by.get(RUN_MODE),at)
    if mode.get('value')!='Normal Mode' or mode.get('age_seconds') is None or not 0<=mode['age_seconds']<MAX_AGE_S:
        errors.append('run_mode_not_normal_or_stale')
    reports=[points[k].get('last_reported') for k in SOLAX_KEYS]
    skew=None
    if all(reports):
        stamps=[instant(t) for t in reports];skew=(max(stamps)-min(stamps)).total_seconds()
        if skew>MAX_REPORT_SKEW_S:errors.append('incoherent_phase_reports')
    else:errors.append('missing_phase_report_times')
    reports_by_key={k:points[k].get('last_reported') for k in SOLAX_KEYS}
    signature=digest(reports_by_key)
    return points,sorted(set(errors)),{'invalid_inputs':details,'report_skew_s':skew,
        'coherence_basis':'bounded HA live reports; physical atomicity unverified','signature':signature,'solax_reports':reports_by_key,
        'phase_measurements':[{k:priority.value(points,f'{key}_l{i}{suffix}') for k,key,suffix in [('grid_current_a','grid','_a'),('voltage_v','grid_voltage','_v'),('grid_power_w','grid','_w'),('inverter_w','inverter','_w'),('ev_w','ev','_w')]} for i in (1,2,3)]}


def event(db,run,at,kind,eid=None,before=None,after=None,reason=None,**extra):
    row={'at':at,'day':run['day'],'kind':kind,'entity_id':eid,'before':before,'after':after,'reason':reason,
        'label':'Dočasný požadavek baterie · model W AC' if eid==RAM_TARGET else run.get('snapshot',{}).get(eid,{}).get('label',eid),
        'policy':POLICY,'software_version':VERSION,'device_actions':0,'applied_to_control':False,
        'persistent_writes':0,**extra}
    cursor=db.execute('INSERT INTO ram_control_events(day,at,payload) VALUES(?,?,?)',(run['day'],at,pack(row)))
    run['event_count']+=1
    return cursor.lastrowid


def virtual(db,run,at,eid,wanted,reason,kind='would_set'):
    own=run['owned'][eid]
    if own.get('conflict') or own['virtual']==wanted:return
    before=own['virtual'];own['virtual']=wanted;own['changed']=True
    event(db,run,at,kind,eid,before,wanted,reason)


def stop(db,run,at,reason):
    previous=run.get('target_ac_w',0)
    if previous:
        event(db,run,at,'would_stop_charge',RAM_TARGET,previous,0,reason);run['counts']['stops']+=1
    run['target_ac_w']=0.;run['good_frames']=0;run['previous']=None
    run['last_intent']=validate_intent(intent(0.,at))


def changes(db,run,values,by,at):
    # Trvalé parametry pouze pozorujeme; nikdy je virtuálně nepřepisujeme.
    for eid,own in run.get('owned',{}).items():
        p=values.get(eid,{});v=p.get('value')
        if v is None:continue
        manual=p.get('manual_context') and p.get('last_updated')!=own.get('last_updated')
        if v!=own.get('last_observed') or manual:
            conflict=bool(manual or eid in (legacy.CURRENT,legacy.MODE,legacy.FORCE))
            event(db,run,at,'observed_external_change',eid,own.get('last_observed'),v,'manual_context' if manual else 'origin_unknown',conflicts_with_virtual_plan=conflict)
            if conflict:
                own['conflict']=True;run['suspended']=True
        own['last_observed']=v;own['last_updated']=p.get('last_updated')
    observed=by.get(REMOTE_MODE,{}).get('state')
    readback=by.get(READBACKS[0],{}).get('state')
    if observed not in (None,'unknown','unavailable','Disabled') or readback not in (None,'unknown','unavailable','Disabled'):
        if not run.get('suspended'):event(db,run,at,'control_blocked',reason='unowned_remote_control')
        run['suspended']=True


def owner_errors(by,at):
    """Stejné ověření vlastníka před převzetím i během relace; ne pouze text Disabled."""
    errors=[]
    for eid in (REMOTE_MODE,READBACKS[0]):
        point=night.point(by.get(eid),at)
        if point.get('value')!='Disabled':errors.append('remote_owner_not_disabled:'+eid)
        age=point.get('age_seconds')
        if age is None or not 0<=age<MAX_AGE_S:errors.append('remote_owner_missing_or_stale:'+eid)
    return errors


def advance_previous(run,at):
    """Integrace nejvýše do konce logické lease; skutečná mezera se nepřemosťuje."""
    previous=run.get('previous')
    if not previous:return
    start=instant(previous['at']);end=min(instant(at),instant(run['window_end']),instant(previous.get('expires_at') or run['last_intent']['expires_at']))
    dt=(end-start).total_seconds();elapsed=(instant(at)-start).total_seconds()
    if 0<dt<=7.5 and 0<elapsed<=7.5:
        priority.advance(run['shadow_model'],previous['allocation'],dt,(previous['at'],end.isoformat()))
        run['statistics']['covered_s']+=dt
        run['statistics']['current_amp_seconds']+=previous['amps']*dt
    run['previous']=None


def close(db,run,values,by,states,at):
    if not run.get('restoration_attempted_at') and 0<=(instant(at)-instant(run['window_end'])).total_seconds()<=7.5:
        advance_previous(run,run['window_end'])
    stop(db,run,at,'window_end');comparisons=[];pending=False;conflicts=False;conditional=False
    for eid in (legacy.CURRENT,legacy.MODE,legacy.FORCE,legacy.FLAG,*legacy.AUTOMATIONS):
        own=run.get('owned',{}).get(eid)
        if not own:continue
        actual=values.get(eid,{}).get('value');status='unchanged'
        if own.get('conflict'):conflicts=True;status='unresolved_external_change'
        elif actual is None:status='unresolved_missing_state';pending=True
        elif own.get('changed'):
            if eid==legacy.FLAG and own['before']=='off':
                p=night.point(by.get('sensor.solax_api_charge_power_total'),at)
                if p.get('quality')!='valid' or p.get('age_seconds') is None or not 0<=p['age_seconds']<MAX_AGE_S:
                    status='unresolved_ev_state';pending=True
                elif p['value']>=50 or actual=='on':status='conditional_handoff';conditional=True
                else:virtual(db,run,at,eid,own['before'],'restore_snapshot','would_restore');status='would_restore'
            else:virtual(db,run,at,eid,own['before'],'restore_snapshot','would_restore');status='would_restore'
        comparisons.append({'entity_id':eid,'label':run['snapshot'][eid]['label'],'before':own['before'],'virtual_after':own['virtual'],'observed_actual':actual,'status':status})
    restoration='restore_pending' if pending else 'requires_review' if conflicts else 'conditional_handoff' if conditional else 'would_restore_all' if run.get('owned') else 'not_needed'
    first=run.get('restoration_status')!=restoration
    run.update(restoration=comparisons,restoration_status=restoration,status='restore_pending' if pending else 'closed' if run.get('owned') else 'not_started',
        closed_at=None if pending else at,restoration_attempted_at=at,exact_restore=not pending and not conflicts and not conditional and bool(run.get('owned')),
        unresolved_count=sum(x['status'].startswith('unresolved') for x in comparisons))
    if first:event(db,run,at,'restore_pending' if pending else 'window_closed',reason=restoration,scheduled_at=run['window_end'])


def observe(store,states,result):
    db=store.db;schema(db);at=result['at'];now=instant(at);local=now.astimezone(TZ);day=local.date().isoformat()
    values=legacy.read(states);by={s['entity_id']:s for s in states};active=180<=local.hour*60+local.minute<300
    points,errors,diagnostic=inputs(states,at)
    # Starý pozorovací deník dokončí pouze předání; nikdy už nepokračuje v nabíjení.
    legacy.complete_pending(store,states,result,at)
    with db:
        clock_blocked=False
        for d,p in list(db.execute('SELECT day,payload FROM ram_control_sessions ORDER BY day')):
            prior=unpack(p)
            if prior.get('closed_at'):continue
            future=prior.get('clock_recovery_after') or prior.get('last_processed_at')
            if future and instant(future)>now:
                if not prior.get('clock_recovery_after'):
                    stop(db,prior,at,'clock_rollback')
                    event(db,prior,at,'clock_rollback',reason='clock_moved_backwards',resume_after=future)
                prior.update(clock_recovery_after=future,status='waiting_clock_recovery')
                db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(prior),d));clock_blocked=True
            elif prior.get('clock_recovery_after'):
                event(db,prior,at,'clock_recovered',reason='clock_monotonic_again')
                prior.pop('clock_recovery_after');prior.update(good_frames=0,accepted_solax_reports=None,previous=None)
                db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(prior),d))
        if clock_blocked:return view(store,at,states)
        for d,p in list(db.execute('SELECT day,payload FROM ram_control_sessions ORDER BY day')):
            run=unpack(p)
            if not run.get('closed_at') and instant(run['window_end'])<=now:
                changes(db,run,values,by,at);close(db,run,values,by,states,at)
                db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(run),d))
        pending=any(not unpack(p).get('closed_at') and d!=day for d,p in db.execute('SELECT day,payload FROM ram_control_sessions'))
        # Případná předchozí relace starého deníku se nesmí převzít druhým vlastníkem.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='control_sessions'").fetchone():
            pending=pending or any(not unpack(p).get('closed_at') and unpack(p).get('owned') for p, in db.execute('SELECT payload FROM control_sessions'))
        if active and not pending:
            row=db.execute('SELECT payload FROM ram_control_sessions WHERE day=?',(day,)).fetchone();run=unpack(row[0]) if row else None
            if not run:
                start=datetime.combine(local.date(),time(3),TZ).astimezone(timezone.utc)
                run={'day':day,'first_seen_at':at,'window_start':start.isoformat(),'window_end':(start+timedelta(hours=2)).isoformat(),
                    'policy':POLICY,'software_version':VERSION,'status':'awaiting_inputs','event_count':0,'owned':{},'snapshot':{},
                    'counts':{'current_increases':0,'current_decreases':0,'stops':0,'power_increases':0,'power_decreases':0},
                    'target_ac_w':0.,'good_frames':0,'mode':'observe_only','device_actions':0,'persistent_writes':0,'live_ready':False,
                    'statistics':{'sample_count':0,'covered_s':0.,'current_amp_seconds':0.,'current_min_a':None,'current_max_a':None,'model_phase_max_a':{},'measured_phase_max_a':{},'model_exceedance_samples':0,'measured_exceedance_samples':0}}
            if run.get('last_processed_at')==at:return view(store,at,states)
            if run.get('closed_at'):return view(store,at,states)
            dt=(now-instant(run.get('last_processed_at',at))).total_seconds()
            if dt>7.5:
                event(db,run,at,'sampling_gap',reason='fast_loop_gap',gap_seconds=dt);stop(db,run,at,'fast_loop_gap')
            # Poslední platný úsek se účtuje dříve, než stop smaže previous.
            if dt<=7.5:advance_previous(run,at)
            if run.get('target_ac_w',0)>0 and now>=instant(run['last_intent']['expires_at']):
                stop(db,run,at,'logical_lease_expired')
            model=run.get('shadow_model')
            if (model is None or not run.get('owned')) and priority.numeric(points,'battery_soc',10800):
                model=run['shadow_model']=priority.empty_model(priority.value(points,'battery_soc'))
            allocation=priority.allocate(points,at,result.get('session'),model['soc_pct'] if model else None,result.get('priority'))
            reason=allocation.get('reason');wanted=allocation.get('battery_ac_w')
            if wanted is None:errors.append(reason or 'invalid_charge_inputs')
            if allocation.get('ev_reallocated_w',0)>max(100,(priority.value(points,'ev_w') or 0)*.03):errors.append('requires_ev_control_not_implemented')
            for eid in legacy.MANAGED:
                if values.get(eid,{}).get('value') is None:errors.append('missing_managed_state:'+eid)
            if values.get(legacy.FORCE,{}).get('value') not in (None,'Stop Charge and Discharge'):errors.append('unowned_manual_charge_or_discharge')
            errors.extend(owner_errors(by,at))
            if run.get('owned'):changes(db,run,values,by,at)
            if run.get('suspended'):errors.append('external_control_change')
            valid_until=None;renewal=None
            if not errors:
                valid_until=input_valid_until(points,by,run['window_end'])
                if valid_until<=now:errors.append('input_validity_deadline_reached')
            errors=sorted(set(errors))
            reports=diagnostic['solax_reports'];accepted=run.get('accepted_solax_reports')
            if accepted:
                try:invalid_reference=any(instant(accepted[k])>now for k in SOLAX_KEYS)
                except (KeyError,ValueError,TypeError):invalid_reference=True
                if invalid_reference:
                    stop(db,run,at,'invalid_accepted_frame_time')
                    event(db,run,at,'frame_reference_reset',reason='invalid_accepted_frame_time')
                    run['accepted_solax_reports']=None;accepted=None
            # EV report ani jediná aktualizovaná fáze nepotvrdí novou celou sadu SolaXu.
            new_frame=all(reports.values()) and (not accepted or all(instant(reports[k])>instant(accepted[k]) for k in SOLAX_KEYS))
            # Odmítnutá data nesmějí posunout referenci pro další obnovu.
            if new_frame and not errors:run['accepted_solax_reports']=reports
            run['last_signature']=diagnostic['signature']
            if errors:
                reason=';'.join(errors);stop(db,run,at,reason)
                if run.get('last_reason')!=reason:event(db,run,at,'control_blocked' if run.get('owned') else 'preflight_blocked',reason=reason,diagnostic=diagnostic,allocation_missing_inputs=allocation.get('missing_inputs',[]))
            elif new_frame:
                run['good_frames']+=1
                if run['good_frames']>=2:
                    if not run['owned']:
                        run['snapshot']={e:values[e] for e in legacy.MANAGED};run['snapshot_hash']=digest(run['snapshot'])
                        run['owned']={e:{'before':values[e]['value'],'virtual':values[e]['value'],'last_observed':values[e]['value'],'last_updated':values[e].get('last_updated'),'changed':False} for e in legacy.MANAGED}
                        run.update(started_at=at,late_start_seconds=max(0,(now-instant(run['window_start'])).total_seconds()))
                        event(db,run,at,'snapshot_saved',reason='before_first_virtual_change',snapshot_hash=run['snapshot_hash'])
                        for e in legacy.AUTOMATIONS:virtual(db,run,at,e,'off','exclusive_virtual_owner','would_disable_automation')
                        virtual(db,run,at,legacy.FLAG,'on','retain_load_priority_until_handoff')
                    old=run['target_ac_w'];desired=math.floor(max(0.,wanted)/POWER_STEP_W)*POWER_STEP_W
                    target=min(desired,old+RAMP_UP_AC_W_S*min(5,max(0.,dt))) if desired>old else desired
                    target=math.floor(target/POWER_STEP_W)*POWER_STEP_W
                    bounded_intent(target,at,valid_until);run['target_ac_w']=target
                    if target!=old:
                        event(db,run,at,'would_set',RAM_TARGET,old,target,reason,
                            storage_class='volatile_intent_only',wire_command=None,decision={'binding_phase':allocation.get('binding_phase'),'battery_ac_w':target})
                        k='power_increases' if target>old else 'power_decreases';run['counts'][k]+=1
                    run['last_intent']=bounded_intent(target,at,valid_until);renewal='new_coherent_frame'
                else:reason='waiting_second_coherent_frame'
            # Stejný snímek nezvyšuje výkon ani nepotvrzuje nové čtení zařízení.
            else:
                reason='waiting_new_frame'
                # Nižší známý bezpečný limit respektujeme i bez obnovení lease.
                if run.get('owned') and wanted is not None:
                    reduced=math.floor(max(0.,wanted)/POWER_STEP_W)*POWER_STEP_W
                    if reduced<run['target_ac_w']:
                        old=run['target_ac_w'];run['target_ac_w']=reduced
                        event(db,run,at,'would_set',RAM_TARGET,old,reduced,'decrease_without_new_frame')
                        run['counts']['power_decreases']+=1
                        if run.get('last_intent'):
                            run['last_intent']=intent(reduced,run['last_intent']['at'],run['last_intent']['expires_at'])
                # Proactive hold renewal only while the preceding lease is still
                # alive. Expired leases, failures and invalid inputs retain the
                # full stop/two-new-frame recovery. Original report deadlines cap
                # this renewal; a repeated frame cannot keep itself fresh.
                if run.get('owned') and run['target_ac_w']>0 and now<instant(run['last_intent']['expires_at']):
                    previous_expiry=run['last_intent']['expires_at']
                    held=bounded_intent(run['target_ac_w'],at,valid_until)
                    if instant(held['expires_at'])>instant(previous_expiry):
                        run['last_intent']=held;renewal='held_validated_frame'
                        event(db,run,at,'would_renew',RAM_TARGET,run['target_ac_w'],run['target_ac_w'],
                            'hold_within_original_report_deadlines',previous_expires_at=previous_expiry,
                            expires_at=held['expires_at'],input_valid_until=valid_until.isoformat())
            actual=result.get('actual',{});eta=allocation.get('grid_charge_efficiency_assumption');bv=priority.value(points,'battery_v')
            amps=run['target_ac_w']*eta/bv if eta and bv else None
            allocation={**allocation,'battery_ac_w':run['target_ac_w']}
            valid_phase={p['phase']:p for p in allocation.get('phase',[])}
            if len(valid_phase)==3:
                allocation['grid_model_w']=sum(p['base_w']+p.get('planned_ev_w',p['ev_w']) for p in valid_phase.values())+run['target_ac_w']
            phase=[]
            for i in (1,2,3):
                p=valid_phase.get(i);current=priority.value(points,f'grid_l{i}_a') if priority.numeric(points,f'grid_l{i}_a',MAX_AGE_S) else None
                planned=(p['base_w']+p.get('planned_ev_w',p['ev_w'])+run['target_ac_w']/3)/(p['voltage_v']*p['power_factor'])+p.get('current_offset_a',0) if p and not errors else None
                phase.append({'phase':i,'actual_grid_a':current,'planned_grid_a':planned,
                    'current_quality':'validated_phase' if current is not None and p else 'unverified_phase' if current is not None else 'missing_or_stale'})
            sample={'at':at,'day':day,'policy':POLICY,'proposed_dc_a':amps,'virtual_limit_dc_a':amps,'ram_target_ac_w':run['target_ac_w'],
                'actual_limit_dc_a':values.get(legacy.CURRENT,{}).get('value'),'actual_charge_dc_a':actual.get('battery_a'),
                'reason':reason,'binding_phase':allocation.get('binding_phase'),'phase':phase,'device_actions':0,'persistent_writes':0,
                'report_skew_s':diagnostic['report_skew_s'],'frame_signature':diagnostic['signature'],'new_frame':new_frame,
                'hardware_response_verified':False,'input_errors':errors,
                'intent_renewal':renewal,'intent_expires_at':run.get('last_intent',{}).get('expires_at'),
                'input_valid_until':valid_until.isoformat() if valid_until else None}
            stats=run['statistics'];stats['sample_count']+=1
            for key in ('unverified_current_samples','missing_current_phase_samples'):stats.setdefault(key,0)
            stats['unverified_current_samples']+=int(any(p['current_quality']=='unverified_phase' for p in phase))
            stats['missing_current_phase_samples']+=sum(p['actual_grid_a'] is None for p in phase)
            stats['measured_current_basis']='all fresh numeric current reports; P/UI validation quality shown separately'
            if amps is not None:
                stats['current_min_a']=min(stats['current_min_a'],amps) if stats['current_min_a'] is not None else amps
                stats['current_max_a']=max(stats['current_max_a'],amps) if stats['current_max_a'] is not None else amps
            for prefix,key in [('model','planned_grid_a'),('measured','actual_grid_a')]:
                vals=[abs(p[key]) for p in phase if p[key] is not None];stats[prefix+'_exceedance_samples']+=int(any(v>25+1e-7 for v in vals))
                for p in phase:
                    v=p[key]
                    if v is not None:stats[prefix+'_phase_max_a']['L'+str(p['phase'])]=max(stats[prefix+'_phase_max_a'].get('L'+str(p['phase']),0),abs(v))
            # Model po neplatném vzorku nebo bez převzetí nenabíjí.
            run['previous']={'at':at,'amps':amps or 0.,'allocation':allocation,'expires_at':run.get('last_intent',intent(0.,at))['expires_at']} if not errors and run.get('owned') else None
            run.update(last_processed_at=at,last_reason=reason,status='suspended' if run.get('suspended') else 'active' if run.get('owned') else 'awaiting_inputs',
                interface=capabilities(states),operating_context={'run_status':{'entity_id':RUN_MODE,'label':'Provozní stav měniče','value':by.get(RUN_MODE,{}).get('state')},
                 'charge_strategy':{'entity_id':legacy.MODE,'label':'Skutečná strategie · pouze čtení','value':values.get(legacy.MODE,{}).get('value')}})
            db.execute('INSERT INTO ram_control_samples VALUES(?,?,?)',(at,day,pack(sample)))
            db.execute('INSERT OR REPLACE INTO ram_control_sessions VALUES(?,?)',(day,pack(run)))
    return view(store,at,states)


def record_failure(store,at,error_code):
    schema(store.db)
    with store.db:
        for day,p in list(store.db.execute('SELECT day,payload FROM ram_control_sessions ORDER BY day DESC')):
            run=unpack(p)
            if run.get('closed_at'):continue
            # Krátký, již platný požadavek končí skutečným stopem, ne posledním vzorkem.
            advance_previous(run,at)
            stop(store.db,run,at,'collection_failure')
            if run.get('status')!='waiting_for_recovery':event(store.db,run,at,'collection_failure',reason=error_code)
            run.update(status='waiting_for_recovery',last_signature=None)
            if instant(at)>=instant(run['window_end']):close(store.db,run,{}, {},[],at)
            store.db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(run),day))
    return view(store,at,[])


def summary(run):
    """Projekce původní relace; uložené modely ani minulá data nepřepočítává."""
    if not run:return None
    fields=('day','status','started_at','closed_at','counts','event_count','restoration_status','statistics','policy','persistent_writes','software_version','shadow_model','target_ac_w','last_processed_at','last_intent')
    return {**{k:run.get(k)for k in fields},'model_scope':'ramped_controller_shadow'}


def view(store,at,states):
    schema(store.db)
    rows=[unpack(p) for p, in store.db.execute('SELECT payload FROM ram_control_sessions ORDER BY day DESC LIMIT 14')]
    if not rows:
        legacy.schema(store.db);old=legacy.view(store,at,legacy.read(states))
    else:old={}
    run=rows[0] if rows else old.get('session');events=[{'id':i,**unpack(p)} for i,p in store.db.execute('SELECT id,payload FROM ram_control_events ORDER BY id DESC LIMIT 24')]
    samples=[unpack(p) for p, in store.db.execute('SELECT payload FROM ram_control_samples ORDER BY at DESC LIMIT 2')]
    local=instant(at).astimezone(TZ);next_day=local.date()+timedelta(days=int(local.hour>=5))
    summaries=[summary(r) for r in rows]
    handoffs=[]
    if store.db.execute("SELECT 1 FROM sqlite_master WHERE name='control_sessions'").fetchone():
        for payload, in store.db.execute('SELECT payload FROM control_sessions ORDER BY day DESC'):
            item=unpack(payload)
            if item.get('migration_handoff_started_at'):
                handoffs.append({k:item.get(k)for k in ('day','software_version','status','closed_at','restoration_status','exact_restore','restoration','migration_handoff_started_at','migration_resume_after')})
                if len(handoffs)>=14:break
    return {**old,'legacy_handoffs':handoffs,'observed_at':at,'next_window_start':datetime.combine(next_day,time(3),TZ).isoformat(),'policy':POLICY,
        'status':run['status'] if run else 'waiting_for_window','session':run,'sessions':summaries or old.get('sessions',[]),
        'recent_events':events or old.get('recent_events',[]),'recent_samples':samples or old.get('recent_samples',[]),
        'interface':capabilities(states),'device_actions':0,'applied_to_control':False,'persistent_writes':0,
        'cadence_s':5,'cautions':['Pouze logický výkonový model. Převod do VPP paketu, AC/DC hranice a vypršení povelu nejsou ověřené.',
            'Žádné změny proudového registru, strategie nabíjení ani ručního povelu SolaXu.','Čerstvost HA hlášení není fyzický heartbeat; atomická měření nejsou doložená.'],
        'preview':[{'entity_id':e,'label':v.get('label',e),'actual_value':v['value'],'role':'pause_conflicting_automation' if e in legacy.AUTOMATIONS else 'read_only_persistent_setting'} for e,v in legacy.read(states).items() if e in legacy.MANAGED]}
