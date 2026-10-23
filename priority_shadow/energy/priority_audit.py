"""Shadow proposal journal and descriptive day audit; no actuator interface."""
from datetime import date,datetime,timedelta,time,timezone
import math
from urllib.parse import urlencode
from .core import TZ,VERSION,instant,digest
from .store import pack,unpack
from . import night

HISTORY_IDS={
 'export_kwh':'sensor.solax_today_s_export_energy',
 'import_kwh':'sensor.solax_today_s_import_energy',
 'pv_kwh':'sensor.solax_today_s_solar_energy',
 'battery_in_kwh':'sensor.solax_battery_input_energy_today',
 'soc':'sensor.solax_battery_capacity',
 'forecast':'sensor.solcast_pv_forecast_forecast_today',
}
EVALUATION_VERSION='day-audit-v3'
JOURNAL_VERSION='intent-v2'
RULES=[{'min_kwh':0,'max_kwh':5,'target_soc_pct':90},
       {'min_kwh':5,'max_kwh':10,'target_soc_pct':80},
       {'min_kwh':10,'max_kwh':15,'target_soc_pct':70},
       {'min_kwh':15,'max_kwh':None,'target_soc_pct':30}]


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS priority_commands(
    id INTEGER PRIMARY KEY,at TEXT NOT NULL,day TEXT NOT NULL,kind TEXT NOT NULL,payload BLOB NOT NULL,UNIQUE(at,kind));
    CREATE TABLE IF NOT EXISTS priority_day_audits(day TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS priority_day_audit_revisions(day TEXT NOT NULL,version TEXT NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(day,version));''')


def journal(store,result):
    """Persist changes in proposals, not repeated sampling or real commands."""
    schema(store.db)
    at=result['at'];day=instant(at).astimezone(TZ).date().isoformat()
    last=store.db.execute('SELECT payload FROM priority_commands ORDER BY id DESC LIMIT 1').fetchone()
    previous=unpack(last[0]) if last else None
    s=result['selected'];actual=result.get('actual') or {}
    active=result['active']
    kind='proposal' if active and s.get('ev_ac_w') is not None and s.get('battery_ac_w') is not None else 'blocked' if active else 'window_end'
    if not active and (not previous or not previous.get('active')):
        if not previous or previous.get('priority')==result['priority']:return
        kind='preference'
    volts=[r.get('voltage_v') for r in s.get('phase',[])]
    u=sum(volts) if len(volts)==3 and all(isinstance(v,(int,float)) and v>0 for v in volts) else None
    batv=actual.get('battery_v')
    row={'at':at,'day':day,'kind':kind,'active':active,'priority':result['priority'],
         'reason':s.get('reason'),'ev_ac_w':s.get('ev_ac_w') if active else None,
         'battery_ac_w':s.get('battery_ac_w') if active else None,
         'ev_model_phase_a':round(s['ev_ac_w']/u,2) if active and s.get('ev_ac_w') is not None and u else None,
         'battery_model_dc_a':round(s['battery_ac_w']*.9/batv,2) if active and s.get('battery_ac_w') is not None and isinstance(batv,(int,float)) and batv>0 else None,
         'target_soc_pct':s.get('target_soc_pct') if active else None,
         'forbid_discharge':s.get('forbid_discharge') if active else None,
         'ev_allocation_mode':s.get('ev_allocation_mode'),
         'ev_setting_limit_a':s.get('ev_setting_limit_a'),
         'journal_version':JOURNAL_VERSION,
         'device_actions':0,'software_version':VERSION}
    def signature(r):
        fields=('day','kind','active','priority','reason','battery_ac_w','target_soc_pct','forbid_discharge','journal_version','ev_allocation_mode','ev_setting_limit_a')
        # A replay following measured demand does not request a new device limit
        # when line voltage/power moves. Keep exact sample powers in the archive.
        ev_key=r.get('ev_allocation_mode') if r.get('ev_allocation_mode')=='follow_measured_demand' else r.get('ev_ac_w')
        return tuple(r.get(k) for k in fields)+(ev_key,)
    if previous and signature(previous)==signature(row):return
    with store.db:store.db.execute('INSERT OR IGNORE INTO priority_commands(at,day,kind,payload) VALUES(?,?,?,?)',(at,day,kind,pack(row)))


def command_summary(store,at):
    schema(store.db)
    day=instant(at).astimezone(TZ).date().isoformat()
    total=store.db.execute('SELECT COUNT(*) FROM priority_commands').fetchone()[0]
    today=dict(store.db.execute('SELECT kind,COUNT(*) FROM priority_commands WHERE day=? GROUP BY kind',(day,)))
    current={}
    for (payload,) in store.db.execute('SELECT payload FROM priority_commands WHERE day=?',(day,)):
        row=unpack(payload)
        if row.get('journal_version')==JOURNAL_VERSION:current[row['kind']]=current.get(row['kind'],0)+1
    return {'observed_at':at,'rows':[unpack(r[0]) for r in store.db.execute('SELECT payload FROM priority_commands ORDER BY id DESC LIMIT 20')],
            'total_records':total,'today':today,'display_limit':20,'device_actions':0,
            'journal_version':JOURNAL_VERSION,
            'today_current_policy':current,
            'definition':'Changes of shadow proposals; repeated identical samples are not commands. No device services are called.'}


def history_path(day):
    d=date.fromisoformat(day);start=datetime.combine(d,time.min,TZ);end=datetime.combine(d+timedelta(days=1),time.min,TZ)
    return '/api/history/period/'+start.astimezone(timezone.utc).isoformat()+'?'+urlencode({
        'filter_entity_id':','.join(HISTORY_IDS.values()),'end_time':end.astimezone(timezone.utc).isoformat(),'minimal_response':''})


def number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None


def samples(series,start,end):
    result=[]
    for row in series:
        try:at=instant(row.get('last_updated') or row['last_changed'])
        except (ValueError,KeyError,TypeError):continue
        if start<=at<end:result.append((at,number(row.get('state'))))
    return sorted(result,key=lambda p:p[0])


def held(rows,at):
    eligible=[r for r in rows if r[0]<=at]
    return eligible[-1][1] if eligible else None


def daily_counter(rows,start):
    """Ignore midnight carry-over. Require early reset; never use daily max."""
    early=[r for r in rows if r[0]<=start+timedelta(minutes=30) and r[1]==0]
    decreases=[b for a,b in zip(rows,rows[1:]) if b[0]<=start+timedelta(minutes=30) and a[1] is not None and b[1] is not None and 0<=b[1]<=.2 and b[1]<a[1]-.001]
    if len(decreases)>1:return None,'multiple_midnight_resets'
    if not early and not decreases:return None,'reset_not_observed'
    reset=(decreases[-1] if decreases else early[0])[0];valid=[r for r in rows if r[0]>=reset]
    if not valid or valid[-1][1] is None:return None,'unavailable_at_end'
    prev=None
    for _,v in valid:
        if v is None:continue
        if v<0 or (prev is not None and v<prev-.001):return None,'counter_decreased_during_day'
        prev=v
    return valid[-1][1],'recorded_daily_counter'


def evaluate_day(day,histories,at,session=None):
    d=date.fromisoformat(day);start=datetime.combine(d,time.min,TZ);end=datetime.combine(d+timedelta(days=1),time.min,TZ)
    if end>instant(at):raise ValueError('Cannot finalize an open day')
    by={s[0].get('entity_id'):s for s in histories if s}
    rows={k:samples(by.get(e,[]),start,end) for k,e in HISTORY_IDS.items()}
    frozen_valid=False
    if session:
        try:
            capture=instant(session['captured_at']);available=instant(session['forecast_archived_available_at'])
            frozen_valid=(session.get('status')=='captured' and session.get('day',day)==day
                          and start+timedelta(hours=3)<=capture<start+timedelta(hours=5)
                          and start<=available<=capture and isinstance(session.get('forecast_kwh'),(int,float))
                          and 0<=session['forecast_kwh']<100)
        except (KeyError,ValueError,TypeError):pass
    result={'day':day,'calculated_at':at,'source':'HA recorder history','source_hash':digest(histories),
            'software_version':VERSION,'device_actions':0,'quality':{},'linked_shadow_night':frozen_valid,'has_shadow_session':bool(session),
            'forecast_source':'frozen_shadow_session' if frozen_valid else 'not_archived_at_shadow_decision',
            'forecast_frozen_kwh':session.get('forecast_kwh') if frozen_valid else None,
            'forecast_captured_at':session.get('captured_at') if frozen_valid else None,
            'target_soc_pct':session.get('target_soc_pct') if frozen_valid else None}
    for k in ('export_kwh','import_kwh','pv_kwh','battery_in_kwh'):
        series=by.get(HISTORY_IDS[k],[]);unit=series[0].get('attributes',{}).get('unit_of_measurement') if series else None
        if unit!='kWh' or any(r.get('attributes',{}).get('unit_of_measurement','kWh')!='kWh' for r in series):result[k]=None;result['quality'][k]='missing_or_mismatched_unit'
        else:result[k],result['quality'][k]=daily_counter(rows[k],start)
    soc_series=by.get(HISTORY_IDS['soc'],[])
    if (not soc_series or soc_series[0].get('attributes',{}).get('unit_of_measurement')!='%'
            or any(r.get('attributes',{}).get('unit_of_measurement','%')!='%' for r in soc_series)):rows['soc']=[]
    rows['soc']=[(t,v if v is not None and 0<=v<=100 else None) for t,v in rows['soc']]
    valid_soc=[v for _,v in rows['soc'] if v is not None]
    at05=start+timedelta(hours=5);at17=start+timedelta(hours=17)
    result.update(soc_05=held(rows['soc'],at05),soc_min=min(valid_soc) if valid_soc else None,
                  soc_max=max(valid_soc) if valid_soc else None,soc_end=rows['soc'][-1][1] if rows['soc'] else None)
    evening=[v for t,v in rows['soc'] if t>=at17 and v is not None]
    first_evening=held(rows['soc'],at17)
    if first_evening is not None:evening.append(first_evening)
    result['evening_min_soc']=min(evening) if evening else None
    before=held(rows['import_kwh'],at17)
    result['evening_import_kwh']=round(result['import_kwh']-before,3) if result['import_kwh'] is not None and before is not None and before<=result['import_kwh'] else None
    before03=held(rows['battery_in_kwh'],start+timedelta(hours=3));after05=held(rows['battery_in_kwh'],at05)
    result['night_charge_dc_kwh']=round(after05-before03,3) if result['battery_in_kwh'] is not None and before03 is not None and after05 is not None and after05>=before03 else None
    # Only pair export increments with SOC at both endpoints and a <=15 min interval.
    paired=high=0.
    if result['export_kwh'] is not None:
        for (t0,v0),(t1,v1) in zip(rows['export_kwh'],rows['export_kwh'][1:]):
            if v0 is None or v1 is None or v1<v0 or not 0<(t1-t0).total_seconds()<=900:continue
            observed=[held(rows['soc'],t0)]+[v for t,v in rows['soc'] if t0<t<t1]+[held(rows['soc'],t1)]
            if any(v is None for v in observed):continue
            delta=v1-v0;paired+=delta
            if min(observed)>=95:high+=delta
    result['export_paired_kwh']=round(paired,3)
    result['export_at_high_soc_kwh']=round(high,3) if rows['soc'] and (paired>0 or result['export_kwh']==0) else None
    result['raw_forecast_difference_kwh']=round(result['pv_kwh']-result['forecast_frozen_kwh'],3) if result['pv_kwh'] is not None and isinstance(result['forecast_frozen_kwh'],(int,float)) else None
    result['forecast_error_kwh']=None
    result['measurement_boundary_verified']=False
    result['forecast_comparison_status']='measurement_boundary_unverified' if frozen_valid else 'no_valid_frozen_forecast'
    result['evaluation_version']=EVALUATION_VERSION
    result['assessment']='observations_only' if not session else 'incomplete_measurements' if not frozen_valid or any(result[k] is None for k in ('pv_kwh','export_kwh','import_kwh','soc_05','soc_end')) else 'descriptive_pair_ready'
    result['interpretation']='Export with high SOC is a review signal. It does not prove excessive night charging or savings; actual operation may differ from the shadow plan.'
    result['soc_quality']='HA recorded states; continuous sensor heartbeat and exact minute of extrema are not proven'
    result['missing_measurements']=[k for k in ('export_kwh','import_kwh','pv_kwh','battery_in_kwh','soc_05','soc_end') if result[k] is None]
    return result


def revised_reports(store):
    """Latest immutable derivation per day for the current evaluation version."""
    reports={}
    for row in store.db.execute('''SELECT payload FROM priority_day_audit_revisions
            WHERE version=? OR version LIKE ? ORDER BY rowid DESC''',(EVALUATION_VERSION,EVALUATION_VERSION+':%')):
        r=unpack(row[0]);reports.setdefault(r['day'],r)
    return reports


def update_day_audit(store,client,at):
    schema(store.db);local=instant(at).astimezone(TZ)
    if (local.hour==0 and local.minute<10) or night.window(at):return
    yesterday=local.date()-timedelta(days=1)
    # One bounded query per call. Catch up missed days without inventing a
    # pre-installation week, and retry partial recordings using fresh history.
    anchors=[yesterday]
    event=store.db.execute("SELECT MIN(at) FROM priority_events").fetchone() if store.db.execute("SELECT 1 FROM sqlite_master WHERE name='priority_events'").fetchone() else None
    if event and event[0]:anchors.append(instant(event[0]).astimezone(TZ).date()-timedelta(days=1))
    for row in store.db.execute('SELECT day FROM priority_day_audits UNION SELECT day FROM priority_day_audit_revisions'):
        anchors.append(date.fromisoformat(row[0]))
    start=max(yesterday-timedelta(days=6),min(anchors));reports=revised_reports(store)
    candidates=[(yesterday-timedelta(days=i)).isoformat() for i in range((yesterday-start).days+1)]
    pending=[d for d in candidates if d not in reports]
    if not pending:pending=[d for d in candidates if reports[d].get('missing_measurements')]
    if not pending:return
    day=pending[0]
    original=store.db.execute('SELECT payload FROM priority_day_audits WHERE day=?',(day,)).fetchone()
    cached=unpack(original[0]) if original else None
    obj=store.db.execute('SELECT payload FROM objects WHERE hash=?',(cached['source_hash'],)).fetchone() if cached and day not in reports else None
    histories=unpack(obj[0]) if obj else client.energy_day_history(day)
    session=None
    for table in ('priority_sessions','night_sessions'):
        exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
        found=store.db.execute(f'SELECT payload FROM {table} WHERE day=?',(day,)).fetchone() if exists else None
        if found:
            session=unpack(found[0]);break
    result=evaluate_day(day,histories,at,session)
    result['source_available_at']=cached.get('calculated_at') if obj else at
    summary=store.db.execute('SELECT payload FROM priority_summaries WHERE day=?',(day,)).fetchone()
    model=unpack(summary[0]).get('models',{}).get('selected',{}) if summary else {}
    result['model_soc_at_covered_end']=model.get('soc_pct')
    result['model_covered_s']=model.get('covered_s')
    result['model_soc_05']=model.get('soc_pct') if model.get('covered_s',0)>=7200 else None
    h=result['source_hash']
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',(h,'priority_day_history',pack(histories)))
        store.db.execute('INSERT OR IGNORE INTO priority_day_audit_revisions VALUES(?,?,?)',(day,EVALUATION_VERSION+':'+h,pack(result)))


def day_summary(store,at,error=None):
    schema(store.db)
    by_day={unpack(r[0])['day']:unpack(r[0]) for r in store.db.execute('SELECT payload FROM priority_day_audits ORDER BY day DESC LIMIT 7')}
    by_day.update(revised_reports(store))
    rows=[by_day[k] for k in sorted(by_day,reverse=True)[:7]]
    errors=[r['forecast_error_kwh'] for r in rows if r.get('forecast_error_kwh') is not None and r.get('measurement_boundary_verified')]
    return {'observed_at':at,'days':rows,'forecast_pairs':sum(r.get('linked_shadow_night',False) for r in rows),
            'validated_forecast_pairs':len(errors),'measurement_boundary_verified':False,
            'forecast_mae_kwh':round(sum(abs(e) for e in errors)/len(errors),3) if errors else None,
            'forecast_bias_kwh':round(sum(errors)/len(errors),3) if errors else None,'rules':RULES,'rule_version':'fve-targets-v2-30pct',
            'status':'history_query_failed' if error else 'observations_available' if rows else 'waiting_for_completed_day',
            'error_code':error,'device_actions':0,'applied_to_control':False,
            'discharge_forbidden_below_forecast_kwh':30,'battery_capacity_kwh_assumption':10.4,
            'note':'Fixed shadow rules. Forecast/production measurement boundary unverified. No automatic tuning or proven savings.'}
