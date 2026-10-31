"""Bounded, read-only evidence for the 03:00–05:00 battery shadow scenario.

These calculations are descriptive. Active power and an assumed power factor
cannot protect a 25 A breaker; no actuator writes exist in this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from .core import TZ, VERSION, instant
from .store import pack, unpack

INTERVAL = 15
IDS = {
    'house_w': 'sensor.solax_house_load',
    'ev_w': 'sensor.solax_api_charge_power_total',
    'ev_connected': 'binary_sensor.tesla_model_y_juniper_nabijeci_kabel',
    'ev_soc': 'sensor.tesla_model_y_juniper_uroven_baterie',
    'ev_target_soc': 'number.tesla_model_y_juniper_nabijeci_limit',
    'battery_soc': 'sensor.solax_battery_capacity',
    'battery_dc_w': 'sensor.solax_battery_power_charge',
    'battery_v': 'sensor.solax_battery_voltage_charge',
    'battery_a': 'sensor.solax_battery_current_charge',
    'battery_limit_a': 'number.solax_battery_charge_max_current',
    'inverter_mode': 'select.solax_charger_use_mode',
    'manual_mode': 'select.solax_manual_mode_select',
    'main_breaker_limit_a': 'number.solax_main_breaker_current_limit',
    'ev_limit_a': 'number.solax_api_max_charge_current_setting',
    'ev_state': 'sensor.solax_api_charging_status',
    'forecast_today': 'sensor.solcast_pv_forecast_forecast_today',
    'forecast_polled': 'sensor.solcast_pv_forecast_api_last_polled',
}
for phase in (1, 2, 3):
    IDS.update({
        f'grid_l{phase}_w': f'sensor.solax_measured_power_l{phase}',
        f'inverter_l{phase}_w': f'sensor.solax_inverter_power_l{phase}',
        f'voltage_l{phase}_v': f'sensor.solax_inverter_voltage_l{phase}',
        f'ev_l{phase}_a': f'sensor.solax_api_charge_current_l{phase}',
        f'grid_l{phase}_a': f'sensor.solax_inverter_solax_grid_current_l{phase}',
        f'grid_voltage_l{phase}_v': f'sensor.solax_grid_voltage_l{phase}',
    })


def window(at):
    local = instant(at).astimezone(TZ)
    minute = local.hour * 60 + local.minute
    return 175 <= minute < 305  # 02:55–05:05, Prague local time


def ensure_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS night_sessions(
            day TEXT PRIMARY KEY, payload BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS night_samples(
            at TEXT PRIMARY KEY, day TEXT NOT NULL, payload BLOB NOT NULL);
        CREATE INDEX IF NOT EXISTS night_samples_day ON night_samples(day,at);
        CREATE TABLE IF NOT EXISTS night_summaries(
            day TEXT PRIMARY KEY, payload BLOB NOT NULL);
    ''')


def point(state, at):
    if state is None:
        return {'value': None, 'quality': 'missing', 'age_seconds': None}
    if state.get('snapshot_error'):
        return {'value':None,'quality':state['snapshot_error'],'age_seconds':None,'last_reported':state.get('last_reported'),'last_updated':state.get('last_updated'),'report_source':state.get('report_source')}
    raw = state.get('state')
    age = None
    try:
        age = (instant(at) - instant(state['last_reported'])).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    if raw in ('unknown', 'unavailable', None, ''):
        value, quality = None, str(raw or 'missing')
    else:
        try:
            value = float(raw)
            if not math.isfinite(value): raise ValueError()
            quality = 'valid'
        except (ValueError, TypeError):
            value, quality = str(raw)[:80], 'text'
    return {'value': value, 'quality': quality, 'age_seconds': round(age, 2) if age is not None else None,
            'last_reported': state.get('last_reported'), 'last_updated': state.get('last_updated'),
            'report_source': state.get('report_source','ha_rest_state')}


def valid(points, key, age=90):
    p = points[key]
    return (p['quality'] == 'valid' and isinstance(p['value'], (int, float))
            and p['age_seconds'] is not None and 0 <= p['age_seconds'] < age)


def stable_state(points, key, max_age):
    """A known HA state is usable for a descriptive plan, not proof of a live device."""
    return valid(points, key, max_age)


def target_for(kwh):
    return 90 if kwh < 5 else 80 if kwh < 10 else 70 if kwh < 15 else 30


def build_session(store, day, at, points):
    """Build a forecast capture with its real availability; no persistence."""
    forecast = points['forecast_today']
    archived = store.available_forecast(IDS['forecast_today'], at)
    archived_value = None
    if archived:
        try: archived_value = float(archived['payload']['state'])
        except (ValueError, TypeError, KeyError): pass
    reported = forecast.get('last_reported')
    same_day = False
    try: same_day = instant(reported).astimezone(TZ).date().isoformat() == day
    except (ValueError, TypeError, AttributeError): pass
    known = (archived is not None and instant(archived['available_at']) <= instant(at)
             and instant(archived['available_at']).astimezone(TZ).date().isoformat() == day)
    if (known and same_day and valid(points,'forecast_today',26*3600)
            and isinstance(forecast['value'], (int, float)) and 0 <= forecast['value'] < 100
            and archived_value == forecast['value']):
        value = forecast['value']; target = target_for(value); status = 'captured'
    else:
        value = target = None; status = 'missing_forecast_at_capture'
    session = {'schema_version': 1, 'day': day, 'captured_at': at, 'policy_version': VERSION,
               'forecast_kwh': value, 'target_soc_pct': target, 'forecast_state_last_reported': forecast.get('last_reported'),
               'forecast_archived_available_at': archived['available_at'] if known else None,
               'forecast_polled_state': points['forecast_polled']['value'], 'status': status,
               'note': 'HA today state observed on this local date; archive availability precedes capture. Provider issue time is unverified.'}
    return session


def capture_session(store, day, at, points):
    if store.db.execute('SELECT 1 FROM night_sessions WHERE day=?', (day,)).fetchone(): return
    session=build_session(store,day,at,points)
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO night_sessions VALUES(?,?)',(day,pack(session)))

def derive(points, at, session):
    local = instant(at).astimezone(TZ)
    active = 180 <= local.hour * 60 + local.minute < 300
    rows = []
    for i in (1, 2, 3):
        keys = (f'grid_l{i}_w', f'inverter_l{i}_w', f'voltage_l{i}_v')
        if all(valid(points, k) for k in keys) and 180 < points[keys[2]]['value'] < 260:
            meter, inverter, voltage = (points[k]['value'] for k in keys)
            house = max(0, inverter - meter)
            rows.append({'phase': i, 'house_w': house, 'model_room_w': max(0, math.floor(22 * voltage * .9 - house))})
        else:
            rows.append({'phase': i, 'house_w': None, 'model_room_w': None})
    binding = min(rows, key=lambda r: r['model_room_w'])['phase'] if all(r['model_room_w'] is not None for r in rows) else None
    room = 3 * min(r['model_room_w'] for r in rows) if binding is not None else None
    target = session.get('target_soc_pct') if session else None
    reason = 'outside_charge_window' if not active else 'missing_frozen_forecast' if target is None else None
    if reason is None and room is None: reason = 'invalid_phase_input'
    if reason is None and not (stable_state(points,'battery_soc',3*3600)
                               and stable_state(points,'battery_v',2*3600)
                               and stable_state(points,'battery_limit_a',7*86400)):
        reason = 'invalid_battery_input'
    if reason is None and not 100 < points['battery_v']['value'] < 500:reason = 'invalid_battery_voltage'
    if reason is None and not 0 <= points['battery_limit_a']['value'] <= 100:reason = 'invalid_battery_limit'
    if reason is None and target == 0:reason = 'forecast_no_charge'
    if reason is None and points['battery_soc']['value'] >= target:reason = 'target_reached'
    proposed = None
    if reason is None:
        cap = points['battery_limit_a']['value'] * points['battery_v']['value'] / .9
        proposed = max(0, math.floor(min(room, cap) / 100) * 100)
        reason = 'room_available' if proposed > 0 else 'no_phase_room'
    elif reason in ('forecast_no_charge','target_reached','outside_charge_window'):
        proposed = 0
    return {'phase': rows, 'binding_phase': binding, 'model_room_w': room,
            'proposed_ac_w': proposed, 'reason': reason, 'target_soc_pct': target,
            'assumption': '22 A per phase, power factor 0.9, DC/AC factor 0.9; unchanged HA states are not device heartbeats; not breaker protection'}


def record(store, states, at):
    if not window(at): return None
    ensure_schema(store.db)
    day = instant(at).astimezone(TZ).date().isoformat()
    by_id = {s['entity_id']: s for s in states}
    points = {key: point(by_id.get(eid), at) for key, eid in IDS.items()}
    if by_id.get(IDS['forecast_today'],{}).get('attributes',{}).get('unit_of_measurement')!='kWh':points['forecast_today']['quality']='unit_mismatch'
    local = instant(at).astimezone(TZ)
    if 180 <= local.hour * 60 + local.minute:
        capture_session(store, day, at, points)
    row = store.db.execute('SELECT payload FROM night_sessions WHERE day=?', (day,)).fetchone()
    session = unpack(row[0]) if row else None
    result = {'schema_version': 1, 'at': at, 'day': day, 'points': points,
              'shadow': derive(points, at, session)}
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO night_samples VALUES(?,?,?)',(at,day,pack(result)))
    return result


def summarize(store, day):
    ensure_schema(store.db)
    rows = [unpack(x[0]) for x in store.db.execute('SELECT payload FROM night_samples WHERE day=? ORDER BY at',(day,))]
    if not rows:return None
    session_row = store.db.execute('SELECT payload FROM night_sessions WHERE day=?',(day,)).fetchone()
    session = unpack(session_row[0]) if session_row else None
    active = [r for r in rows if 180 <= (instant(r['at']).astimezone(TZ).hour*60+instant(r['at']).astimezone(TZ).minute) < 300]
    energy = {k:0.0 for k in ('house_kwh','ev_kwh_ac','battery_kwh_dc','grid_import_kwh_ac','proposed_kwh_ac')}
    coverage = {k:0.0 for k in energy}
    for a,b in zip(active,active[1:]):
        dt=(instant(b['at'])-instant(a['at'])).total_seconds()
        if not 0 < dt <= 30:continue
        pa=a['points'];sh=a['shadow'];values={}
        for key,point_key in (('house_kwh','house_w'),('ev_kwh_ac','ev_w'),('battery_kwh_dc','battery_dc_w')):
            if valid(pa,point_key):values[key]=pa[point_key]['value']
        if all(valid(pa,f'grid_l{i}_w') for i in (1,2,3)):
            values['grid_import_kwh_ac']=max(0,-sum(pa[f'grid_l{i}_w']['value'] for i in (1,2,3)))
        if sh['proposed_ac_w'] is not None:values['proposed_kwh_ac']=sh['proposed_ac_w']
        for key,value in values.items():
            energy[key]+=value*dt/3600000
            coverage[key]+=dt
    soc=[(r['at'],r['points']['battery_soc']['value']) for r in active if stable_state(r['points'],'battery_soc',3*3600)]
    phase_min={f'L{i}':min((r['shadow']['phase'][i-1]['model_room_w'] for r in active
                            if r['shadow']['phase'][i-1]['model_room_w'] is not None),default=None) for i in (1,2,3)}
    result={'schema_version':1,'day':day,'sample_count':len(rows),'active_sample_count':len(active),
            'covered_minutes':round(coverage['house_kwh']/60,2),'coverage_minutes':{k:round(v/60,2) for k,v in coverage.items()},
            'charge_window_minutes':120,
            'phase_min_room_w':phase_min,'battery_soc_first_last':(soc[0],soc[-1]) if soc else None,
            'frozen_session':session,'energy':{k:round(v,4) for k,v in energy.items()},
            'reason_counts':{k:sum(r['shadow']['reason']==k for r in active)
                             for k in {r['shadow']['reason'] for r in active}},
            'limitations':['Descriptive shadow, not observed savings or breaker protection.',
                           'Each energy series has its own valid 15-second coverage; gaps and unchanged power reports older than 90 seconds are excluded.',
                           'AC and DC energies are separate.']}
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO night_summaries VALUES(?,?)',(day,pack(result)))
    return result


def recent(store, day=None):
    ensure_schema(store.db)
    if day is None:
        row=store.db.execute('SELECT day FROM night_samples ORDER BY at DESC LIMIT 1').fetchone()
        day=row[0] if row else None
    if not day:return {'status':'waiting','samples':[],'summary':None}
    rows=[unpack(x[0]) for x in store.db.execute('SELECT payload FROM night_samples WHERE day=? ORDER BY at',(day,))]
    row=store.db.execute('SELECT payload FROM night_summaries WHERE day=?',(day,)).fetchone()
    return {'status':'ok','day':day,'samples':rows[-600:],'summary':unpack(row[0]) if row else None}
