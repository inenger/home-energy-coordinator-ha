"""Trvalý stínový deník převzetí → regulace → předání. Neobsahuje akční adaptér."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
import math
from .core import TZ, VERSION, instant, digest
from .store import pack, unpack
from .automation_context import CONFIG_SHA256

POLICY='control-journal-v1'
SENSOR='sensor.nocni_stinovy_ridici_denik'
AUTOMATIONS=(
 'automation.ev_priorita_nabijeni_zapnuti_2',
 'automation.ev_priorita_nabijeni_zapnuti',
 'automation.ev_priorita_nabijeni_vypnuti',
 'automation.baterie_nabijeni_levny_proud_zapnuti_2',
 'automation.baterie_nabijeni_levny_proud_vypnuti_2',
)
CURRENT='number.solax_battery_charge_max_current'
MODE='select.solax_charger_use_mode'
FORCE='select.solax_manual_mode_select'
FLAG='input_boolean.ev_nabijeni_priorita'
MANAGED=(*AUTOMATIONS, CURRENT, MODE, FORCE, FLAG)
ENTITY_IDS=(*MANAGED,'sensor.solax_api_charge_power_total')
LABELS={CURRENT:'Limit nabíjení baterie · A DC',MODE:'Režim SolaXu',FORCE:'Ruční povel SolaXu',FLAG:'Příznak EV priority'}
CAUTIONS=[
 'Pouze virtuální změny; žádné potvrzení zápisu ani fyzického obnovení.',
 'Původní automatizace dál běží. Nové reakce ohřevu po jejich vypnutí nejsou fyzicky ověřené.',
 'Převod AC/DC, reakční rezerva a fyzická odezva nejsou ověřené pro ostré řízení.',
 'Rozpoznání cizí změny vychází z pozorovaných stavů; všechny ruční zásahy nelze zaručeně zachytit.',
]


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS control_sessions(day TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS control_events(id INTEGER PRIMARY KEY,day TEXT NOT NULL,at TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS control_events_day ON control_events(day,id);
    CREATE TABLE IF NOT EXISTS control_samples(at TEXT PRIMARY KEY,day TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS control_samples_day ON control_samples(day,at);''')


def number(x):
    try:
        n=float(x)
        return n if math.isfinite(n) and not isinstance(x,bool) else None
    except (TypeError,ValueError):return None


def read(states):
    result={}
    for s in states:
        eid=s.get('entity_id')
        if eid not in ENTITY_IDS:continue
        raw=s.get('state');a=s.get('attributes',{});v=number(raw) if eid==CURRENT else raw
        if raw in ('unavailable','unknown','',None):v=None
        result[eid]={'value':v,'label':a.get('friendly_name',LABELS.get(eid,eid)),
            'unit':a.get('unit_of_measurement'),'min':a.get('min'),'max':a.get('max'),'step':a.get('step'),
            'options':a.get('options',[]),'last_updated':s.get('last_updated'),
            'manual_context':bool((s.get('context') or {}).get('user_id'))}
    return result


def snapshot_errors(values):
    errors=[]
    for eid in MANAGED:
        p=values.get(eid,{})
        if p.get('value') is None:errors.append(eid);continue
        if eid in (*AUTOMATIONS,FLAG) and p['value'] not in ('on','off'):errors.append(eid)
    p=values.get(CURRENT,{})
    lo,hi,step=[number(p.get(k)) for k in ('min','max','step')]
    if p.get('unit')!='A' or None in (lo,hi,step) or not (0==lo<=hi<=100 and 0<step<=1):errors.append('invalid_current_metadata')
    elif p.get('value') is not None and not lo<=p['value']<=hi:errors.append('current_out_of_range')
    if values.get(FORCE,{}).get('value')!='Stop Charge and Discharge':errors.append('unowned_manual_charge_or_discharge')
    if not {'Stop Charge and Discharge','Force Charge'}<=set(values.get(FORCE,{}).get('options',[])):errors.append('manual_options_unverified')
    if 'Manual Mode' not in values.get(MODE,{}).get('options',[]):errors.append('mode_options_unverified')
    return sorted(set(errors))


def current_proposal(result,meta):
    """Omezení skutečného registru; zaokrouhlení dolů nemůže zvýšit AC požadavek."""
    s=result.get('selected',{});a=result.get('actual',{})
    power=number(s.get('battery_ac_w'));v=number(a.get('battery_v'));eta=number(s.get('grid_charge_efficiency_assumption'))
    if power is None or v is None or eta is None or not (power>=0 and 100<v<500 and .5<=eta<=1):return None,'invalid_charge_inputs'
    lo,hi,step=[number(meta.get(k)) for k in ('min','max','step')]
    if None in (lo,hi,step) or meta.get('unit')!='A' or not(0==lo<=hi<=100 and 0<step<=1):return None,'invalid_current_metadata'
    if number(s.get('ev_reallocated_w')) is not None and s['ev_reallocated_w']>max(100,(number(a.get('ev_w')) or 0)*.03):
        return None,'requires_ev_control_not_implemented'
    dc_limit=number(s.get('battery_dc_limit_w'))
    if dc_limit is None or dc_limit<0:return None,'invalid_dc_limit'
    wanted=min(power*eta/v,hi,dc_limit/v)
    if wanted<lo:return None,'current_below_register_minimum'
    val=Decimal(str(lo))+((Decimal(str(wanted))-Decimal(str(lo)))/Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(step))
    amps=float(val);ac=amps*v/eta
    if ac>power+1e-6:return None,'rounded_current_exceeds_power'
    phases=s.get('phase') or []
    if len(phases)!=3:return None,'invalid_phase_input'
    for p in phases:
        nums=[number(p.get(k)) for k in ('base_w','planned_ev_w','voltage_v','power_factor')]
        if any(n is None for n in nums):return None,'invalid_phase_input'
        base,ev,u,pf=nums
        if u<=0 or pf<=0 or (base+ev+ac/3)/(u*pf)>25+1e-7:return None,'phase_limit_exceeded'
    return amps,s.get('reason') or 'allocated_power'


def event(db,run,at,kind,eid=None,before=None,after=None,reason=None,**extra):
    row={'at':at,'day':run['day'],'kind':kind,'entity_id':eid,
        'label':run.get('snapshot',{}).get(eid,{}).get('label',LABELS.get(eid,eid)),
        'before':before,'after':after,'reason':reason,'policy':POLICY,'software_version':VERSION,
        'applied_to_control':False,'device_actions':0,**extra}
    cursor=db.execute('INSERT INTO control_events(day,at,payload) VALUES(?,?,?)',(run['day'],at,pack(row)))
    run['event_count']=run.get('event_count',0)+1
    return cursor.lastrowid


def change(db,run,at,eid,wanted,reason,kind='would_set'):
    own=run['owned'][eid]
    if own.get('conflict') or own['virtual']==wanted:return False
    previous=own['virtual'];own['virtual']=wanted;own['changed']=True
    event(db,run,at,kind,eid,previous,wanted,reason,**({'decision':run.get('decision_context',{})} if eid==CURRENT else {}))
    if eid==CURRENT and kind=='would_set':
        key='current_increases' if wanted>previous else 'current_decreases'
        run['counts'][key]+=1
    return True


def external_changes(db,run,values,at):
    for eid,own in run['owned'].items():
        p=values.get(eid,{});v=p.get('value')
        if v is None:continue
        manual=p.get('manual_context') and p.get('last_updated')!=own.get('last_updated')
        if v!=own.get('last_observed') or manual:
            conflict=manual or (v!=own['virtual'] and eid!=FLAG)
            event(db,run,at,'observed_external_change',eid,own.get('last_observed'),v,
                  'manual_context' if manual else 'origin_unknown',conflicts_with_virtual_plan=conflict)
            if conflict:
                own['conflict']={'at':at,'observed':v,'source':'manual_context' if manual else 'origin_unknown'}
                if eid in (CURRENT,MODE,FORCE):run['suspended']=True
        own['last_observed']=v;own['last_updated']=p.get('last_updated')


def stop(db,run,at,reason):
    change(db,run,at,FORCE,'Stop Charge and Discharge',reason,'would_stop_charge')
    change(db,run,at,CURRENT,0.,reason)
    # Stop má platit ve virtuálním Manual Mode i při nulovém počátečním požadavku.
    change(db,run,at,MODE,'Manual Mode',reason)


def close(db,run,values,result,at):
    """Nejprve ukončit vlastní nabíjení, pak vrátit parametry a automatizace."""
    if not run.get('owned'):
        run.update(status='not_started',closed_at=at,restoration_status='not_needed',exact_restore=None)
        event(db,run,at,'window_closed',reason='no_takeover',scheduled_at=run['window_end']);return
    external_changes(db,run,values,at)
    if not run.get('restoration_attempted_at'):
        previous=run.get('last_current_sample');stats=run.get('statistics')
        if previous and stats and previous.get('proposed_dc_a') is not None:
            dt=(instant(run['window_end'])-instant(previous['at'])).total_seconds()
            if 0<dt<=30 and (instant(at)-instant(run['window_end'])).total_seconds()<=30:
                stats['covered_s']+=dt;stats['current_amp_seconds']+=previous['proposed_dc_a']*dt
        run['last_current_sample']=None
    if not run.get('restoration_attempted_at') or run['owned'][FORCE]['virtual']=='Force Charge':
        if run['owned'][FORCE]['virtual']=='Force Charge':run['counts']['stops']+=1
        stop(db,run,at,'window_end')
    comparisons=[];unresolved=0;conditional=0;pending=0
    diagnostics=run.setdefault('restore_diagnostics',{})
    for eid in (CURRENT,MODE,FORCE,FLAG,*AUTOMATIONS):
        own=run['owned'][eid];observed=values.get(eid,{}).get('value');status='unchanged'
        if observed is None or own.get('conflict'):
            status='unresolved_external_change' if own.get('conflict') else 'unresolved_missing_state'
            if diagnostics.get(eid)!=status:event(db,run,at,'would_skip_restore',eid,own['virtual'],observed,status)
            diagnostics[eid]=status
            unresolved+=1;pending+=int(observed is None and not own.get('conflict'))
        elif own.get('changed'):
            if eid==FLAG and own['before']=='off' and own['virtual']=='on':
                point=next((s for s in result.get('_states_for_control',[]) if s.get('entity_id')=='sensor.solax_api_charge_power_total'),None)
                from .night import point as read_point
                p=read_point(point,at);fresh=p['quality']=='valid' and p['age_seconds'] is not None and 0<=p['age_seconds']<90
                if not fresh or p['value']>=50 or observed=='on':
                    status='conditional_handoff' if fresh else 'unresolved_ev_state'
                    if diagnostics.get(eid)!=status:event(db,run,at,'would_handoff',eid,own['virtual'],own['virtual'],status)
                    diagnostics[eid]=status
                    conditional+=1 if fresh else 0;unresolved+=0 if fresh else 1;pending+=0 if fresh else 1
                else:
                    change(db,run,at,eid,own['before'],'restore_snapshot','would_restore');status='would_restore'
            else:
                change(db,run,at,eid,own['before'],'restore_snapshot','would_restore');status='would_restore'
        comparisons.append({'entity_id':eid,'label':run['snapshot'][eid]['label'],'before':own['before'],
             'virtual_after':own['virtual'],'observed_actual':observed,'status':status})
    run.update(status='restore_pending' if pending else 'closed',closed_at=None if pending else at,restoration_attempted_at=at,restoration=comparisons,
        restoration_status='restore_pending' if pending else 'requires_review' if unresolved else 'conditional_handoff' if conditional else 'would_restore_all',
        unresolved_count=unresolved,exact_restore=not unresolved and not conditional and all(x['before']==x['virtual_after'] for x in comparisons))
    if not pending:event(db,run,at,'window_closed',reason=run['restoration_status'],scheduled_at=run['window_end'])
    elif not run.get('pending_reported'):
        event(db,run,at,'restore_pending',reason='missing_current_state',scheduled_at=run['window_end']);run['pending_reported']=True



def complete_pending(store,states,result,at):
    """Dokončení starého virtuálního vlastníka při přechodu na RAM politiku.

    Nevolá starý observe ani nezačíná nové nabíjení. Původní snapshot, verze
    a události zůstávají zachované; nové předání má skutečný čas zotavení.
    """
    db=store.db;schema(db);now=instant(at);values=read(states)
    with db:
        for day,payload in list(db.execute('SELECT day,payload FROM control_sessions ORDER BY day')):
            run=unpack(payload)
            if run.get('closed_at'):continue
            if not run.get('migration_handoff_started_at'):
                # Po upgradu nesmí starý model dál držet Force Charge.
                run['last_current_sample']=None
                if run.get('owned'):
                    if run['owned'].get(FORCE,{}).get('virtual')=='Force Charge':run['counts']['stops']+=1
                    stop(db,run,at,'migration_handoff')
                event(db,run,at,'legacy_handoff_started',reason='migration_handoff')
                run['migration_handoff_started_at']=at
            previous=run.get('last_processed_at')
            if previous and instant(previous)>now:
                run.update(status='waiting_clock_recovery',migration_resume_after=previous)
            else:
                close(db,run,values,{**result,'_states_for_control':states},at)
            db.execute('UPDATE control_sessions SET payload=? WHERE day=?',(pack(run),day))


def observe(store,states,result):
    db=store.db;schema(db);at=result['at'];now=instant(at);local=now.astimezone(TZ);day=local.date().isoformat();values=read(states)
    active=180<=local.hour*60+local.minute<300
    with db:
        # Nedokončené předání se po restartu dohání skutečným časem, ne zpětným datováním.
        for d,payload in list(db.execute('SELECT day,payload FROM control_sessions ORDER BY day'))[-14:]:
            run=unpack(payload)
            if not run.get('closed_at') and instant(run['window_end'])<=now:
                close(db,run,values,{**result,'_states_for_control':states},at)
                db.execute('UPDATE control_sessions SET payload=? WHERE day=?',(pack(run),d))
        unresolved_owner=any(unpack(p).get('owned') and not unpack(p).get('closed_at') and d<day for d,p in db.execute('SELECT day,payload FROM control_sessions'))
        if active and not unresolved_owner:
            row=db.execute('SELECT payload FROM control_sessions WHERE day=?',(day,)).fetchone();run=unpack(row[0]) if row else None
            if run is None:
                start=datetime.combine(local.date(),time(3),TZ).astimezone(timezone.utc)
                run={'day':day,'first_seen_at':at,'window_start':start.isoformat(),'window_end':(start+timedelta(hours=2)).isoformat(),
                    'status':'awaiting_inputs','owned':{},'snapshot':{},'counts':{'current_increases':0,'current_decreases':0,'stops':0},
                    'mode':'observe_only','device_actions':0,'policy':POLICY,'software_version':VERSION,'event_count':0,
                    'reviewed_automation_config_hash':CONFIG_SHA256,'config_live_validation':False,'live_ready':False}
            if run.get('last_processed_at')!=at and not run.get('closed_at'):
                if run.get('last_processed_at') and (now-instant(run['last_processed_at'])).total_seconds()>45:
                    event(db,run,at,'sampling_gap',reason='unobserved_intermediate_changes',gap_seconds=(now-instant(run['last_processed_at'])).total_seconds())
                if not run['owned']:
                    errors=snapshot_errors(values);amps,reason=current_proposal(result,values.get(CURRENT,{}))
                    if amps is None:errors.append(reason)
                    if errors:
                        text=';'.join(sorted(set(errors)))
                        if run.get('blocked_reason')!=text:event(db,run,at,'preflight_blocked',reason=text)
                        run['blocked_reason']=text
                    else:
                        run['snapshot']={eid:values[eid] for eid in MANAGED};run['snapshot_hash']=digest(run['snapshot'])
                        run['owned']={eid:{'before':values[eid]['value'],'virtual':values[eid]['value'],'last_observed':values[eid]['value'],'last_updated':values[eid].get('last_updated'),'changed':False} for eid in MANAGED}
                        run.update(status='active',started_at=at,late_start_seconds=max(0,(now-instant(run['window_start'])).total_seconds()))
                        event(db,run,at,'snapshot_saved',reason='before_first_virtual_change',snapshot_hash=run['snapshot_hash'])
                        for eid in AUTOMATIONS:change(db,run,at,eid,'off','exclusive_virtual_owner','would_disable_automation')
                        change(db,run,at,FLAG,'on','retain_load_priority_until_handoff')
                run['decision_context']={'binding_phase':result.get('selected',{}).get('binding_phase'),
                    'battery_ac_w':result.get('selected',{}).get('battery_ac_w'),'battery_voltage_v':result.get('actual',{}).get('battery_v'),
                    'charge_efficiency_assumption':result.get('selected',{}).get('grid_charge_efficiency_assumption'),
                    'phase':[{k:p.get(k) for k in ('phase','grid_current_a','planned_model_a')} for p in result.get('selected',{}).get('phase',[])]}
                proposed=None;reason=run.get('blocked_reason','awaiting_inputs')
                if run['owned']:
                    external_changes(db,run,values,at)
                    proposed,reason=current_proposal(result,run['snapshot'][CURRENT])
                    if run.get('suspended'):proposed=None;reason='external_control_change'
                    if proposed is None or proposed==0:
                        stop(db,run,at,reason)
                        if run.get('last_control_reason')!=reason:
                            event(db,run,at,'control_blocked' if proposed is None else 'no_charge_request',reason=reason);run['counts']['stops']+=1
                    else:
                        change(db,run,at,CURRENT,proposed,reason)
                        change(db,run,at,MODE,'Manual Mode','enable_virtual_charge')
                        change(db,run,at,FORCE,'Force Charge','enable_virtual_charge')
                    run['last_control_reason']=reason;run['status']='suspended' if run.get('suspended') else 'active'
                phase=[{'phase':p.get('phase'),'actual_grid_a':p.get('grid_current_a'),'planned_grid_a':p.get('planned_model_a')} for p in result.get('selected',{}).get('phase',[])]
                sample={'at':at,'day':day,'proposed_dc_a':proposed,'actual_limit_dc_a':values.get(CURRENT,{}).get('value'),
                    'actual_charge_dc_a':result.get('actual',{}).get('battery_a'),'ev_w':result.get('actual',{}).get('ev_w'),'reason':reason,
                    'virtual_limit_dc_a':run.get('owned',{}).get(CURRENT,{}).get('virtual') if not run.get('owned',{}).get(CURRENT,{}).get('conflict') else None,
                    'binding_phase':result.get('selected',{}).get('binding_phase'),'phase':phase,'device_actions':0}
                stats=run.setdefault('statistics',{'sample_count':0,'current_min_a':None,'current_max_a':None,'current_amp_seconds':0.,'covered_s':0.,'model_phase_max_a':{},'measured_phase_max_a':{},'model_exceedance_samples':0,'measured_exceedance_samples':0})
                previous=run.get('last_current_sample')
                if previous:
                    dt=(now-instant(previous['at'])).total_seconds()
                    if 0<dt<=30 and previous.get('proposed_dc_a') is not None:
                        stats['covered_s']+=dt;stats['current_amp_seconds']+=previous['proposed_dc_a']*dt
                if proposed is not None:
                    stats['current_min_a']=proposed if stats['current_min_a'] is None else min(stats['current_min_a'],proposed)
                    stats['current_max_a']=proposed if stats['current_max_a'] is None else max(stats['current_max_a'],proposed)
                for prefix,key in [('model','planned_grid_a'),('measured','actual_grid_a')]:
                    exceed=False
                    for p in phase:
                        val=number(p.get(key))
                        if val is None or p.get('phase') not in (1,2,3):continue
                        name='L'+str(p['phase']);stats[prefix+'_phase_max_a'][name]=max(stats[prefix+'_phase_max_a'].get(name,0),abs(val));exceed=exceed or abs(val)>25+1e-7
                    stats[prefix+'_exceedance_samples']+=int(exceed)
                stats['sample_count']+=1;run['last_current_sample']={'at':at,'proposed_dc_a':proposed}
                db.execute('INSERT OR IGNORE INTO control_samples VALUES(?,?,?)',(at,day,pack(sample)))
                run['last_processed_at']=at
                db.execute('INSERT OR REPLACE INTO control_sessions VALUES(?,?)',(day,pack(run)))
    return view(store,at,values)



def record_failure(store,at,error_code):
    db=store.db;schema(db)
    with db:
        for day,payload in list(db.execute('SELECT day,payload FROM control_sessions ORDER BY day DESC LIMIT 14')):
            run=unpack(payload)
            if run.get('closed_at') or not run.get('owned'):continue
            if instant(at)>=instant(run['window_end']):close(db,run,{}, {},at)
            else:
                if run.get('status')!='waiting_for_recovery':
                    event(db,run,at,'collection_failure',reason=error_code)
                    if run['owned'][FORCE]['virtual']=='Force Charge':run['counts']['stops']+=1
                stop(db,run,at,'collection_failure');run['status']='waiting_for_recovery';run['last_current_sample']=None
            db.execute('UPDATE control_sessions SET payload=? WHERE day=?',(pack(run),day))
    return view(store,at)

def view(store,at,values=None):
    db=store.db;rows=[unpack(r[0]) for r in db.execute('SELECT payload FROM control_sessions ORDER BY day DESC LIMIT 14')]
    run=rows[0] if rows else None;day=run['day'] if run else None
    events=[]
    for eid,payload in db.execute('SELECT id,payload FROM control_events ORDER BY id DESC LIMIT 24'):
        events.append({'id':eid,**unpack(payload)})
    samples=[unpack(r[0]) for r in db.execute('SELECT payload FROM control_samples ORDER BY at DESC LIMIT 2')]
    summaries=[{k:r.get(k) for k in ('day','status','started_at','closed_at','counts','event_count','restoration_status','unresolved_count','exact_restore','late_start_seconds','statistics')} for r in rows]
    local=instant(at).astimezone(TZ);next_day=local.date()+timedelta(days=1 if local.hour>=5 else 0)
    next_start=datetime.combine(next_day,time(3),TZ).isoformat()
    return {'observed_at':at,'next_window_start':next_start,'status':run['status'] if run else 'waiting_for_window','policy':POLICY,'device_actions':0,'applied_to_control':False,
        'session':run,'sessions':summaries,'recent_events':events,'recent_samples':samples,'display_limit':24,'cautions':CAUTIONS,
        'preview':[{'entity_id':eid,'label':(values or {}).get(eid,{}).get('label',LABELS.get(eid,eid)),
                    'actual_value':(values or {}).get(eid,{}).get('value'),'role':'pause_conflicting_automation' if eid in AUTOMATIONS else 'managed_parameter'} for eid in MANAGED]}
