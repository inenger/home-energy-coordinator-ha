"""Broad, typed environmental telemetry, not an authorization to control devices."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import math
import re
from .core import TZ, instant, season_context, digest
from .store import pack, unpack

CLASSES = frozenset('temperature humidity pressure atmospheric_pressure illuminance irradiance wind_speed wind_direction precipitation precipitation_intensity carbon_dioxide carbon_monoxide pm1 pm25 pm10 volatile_organic_compounds power energy energy_storage current voltage power_factor apparent_power reactive_power frequency water volume_flow_rate gas'.split())
UNITS = {'°C':'temperature','°F':'temperature','K':'temperature','W':'power','kW':'power',
    'Wh':'energy','kWh':'energy','MWh':'energy','V':'voltage','A':'current','VA':'apparent_power',
    'var':'reactive_power','kvar':'reactive_power','W/m²':'irradiance','W/m2':'irradiance',
    'lx':'illuminance','hPa':'atmospheric_pressure','Pa':'pressure','mbar':'pressure',
    'Hz':'frequency','mm/h':'precipitation_intensity'}
ATTRS = {
    'weather': ('temperature','apparent_temperature','dew_point','humidity','pressure','wind_bearing',
        'wind_speed','wind_gust_speed','cloud_coverage','visibility','uv_index','temperature_unit',
        'pressure_unit','wind_speed_unit','visibility_unit','precipitation_unit','supported_features'),
    'sun': ('elevation','azimuth','rising','next_rising','next_setting','next_dawn','next_dusk','next_noon','next_midnight'),
    'climate': ('current_temperature','temperature','target_temp_high','target_temp_low','hvac_action',
        'preset_mode','current_humidity','fan_mode'),
    'water_heater': ('current_temperature','temperature','operation_mode','away_mode'),
    'fan': ('percentage','preset_mode'),
}
CONTROL_TERMS = ('solax','nibe','climate_system','hot_water','heating_','battery_',
                 'baterie_','ev_nabijeni','cerpadlo','patrona')
FORBIDDEN = {'person','device_tracker','camera','image','media_player','lock','alarm_control_panel',
             'conversation','calendar','todo','notify','text'}
ENTITY_ID = re.compile(r'^[a-z_]+\.[a-z0-9_]+$')


def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def celsius(value, unit):
    if not finite(value): return None
    return value if unit=='°C' else (value-32)*5/9 if unit=='°F' else value-273.15 if unit=='K' else None


def scalar(v):
    if v is None or isinstance(v,bool): return v
    if finite(v): return v
    if isinstance(v,str): return v[:160]
    return None


def limited_attrs(attrs,keys):
    return {k:scalar(attrs[k]) for k in keys if k in attrs and scalar(attrs[k]) is not None}


def is_selected(state, policy):
    eid=state.get('entity_id','');domain=eid.partition('.')[0];a=state.get('attributes') or {}
    if not ENTITY_ID.fullmatch(eid) or domain in FORBIDDEN: return False
    if eid in policy.get('exclude',[]) or eid.startswith(('sensor.energie_v3_','sensor.energie_v4_')): return False
    if eid in policy.get('include',[]): return True
    if domain=='sensor': return a.get('device_class') in CLASSES or a.get('unit_of_measurement') in UNITS
    if domain in ATTRS: return True
    if domain=='number' and (a.get('device_class') in CLASSES or a.get('unit_of_measurement') in UNITS): return True
    if domain in ('number','select','switch','input_boolean','binary_sensor','time'):
        return any(t in eid.lower() for t in CONTROL_TERMS) or eid=='binary_sensor.workday_sensor'
    return False


def discover(states, at, policy=None, metadata=None):
    policy=policy or {};metadata=metadata or {};points={}
    for state in states:
        if not is_selected(state,policy): continue
        eid=state['entity_id'];domain=eid.partition('.')[0];a=state.get('attributes') or {}
        quantity=a.get('device_class') or UNITS.get(a.get('unit_of_measurement')) or domain
        raw=scalar(state.get('state','unknown'));value=None;quality='valid';unit=a.get('unit_of_measurement')
        if raw is None or str(raw).lower() in ('unknown','unavailable','none',''):
            quality=str(raw).lower() if raw else 'unknown'
        elif domain in ('sensor','number'):
            try:
                value=float(raw)
                if not math.isfinite(value): raise ValueError()
            except (ValueError,TypeError): quality='invalid_number';value=None
            if quantity=='temperature' and value is not None:
                value=celsius(value,unit)
                if value is None: quality='unit_mismatch'
                else: unit='°C'
            if quantity=='humidity' and value is not None and (unit!='%' or not 0<=value<=100):
                quality='out_of_range';value=None
        else: value=raw
        mapping=(policy.get('mappings',{}).get(eid) or {})
        meta=metadata.get(eid) or {}
        role=mapping.get('role','unclassified');source='sensor_report' if domain=='sensor' else 'control_state'
        if domain=='weather': source='provider_current_not_local_observation';role='provider_current'
        if domain=='sun': source='computed_solar_geometry';role='astronomical'
        age=None;report=None
        try:
            report=instant(state.get('last_reported')).astimezone(timezone.utc).isoformat()
            age=(instant(at)-instant(report)).total_seconds()
        except (ValueError,TypeError,AttributeError): pass
        identity={'entity_id':eid,'label':scalar(a.get('friendly_name',eid)),'quantity':quantity,'unit':unit,
            'device_id':scalar(meta.get('device_id')),'area_id':scalar(meta.get('area_id')),
            'area_name':scalar(meta.get('area_name')),'role':role,'zone':scalar(mapping.get('zone')),
            'role_verified':mapping.get('verified') is True,'source_kind':source,'control_eligible':False}
        points[eid]={**identity,'mapping_hash':digest(identity),'value':value,'raw_state':raw,'quality':quality,
            'last_reported':report,'last_updated':scalar(state.get('last_updated')),
            'report_age_seconds':round(age,2) if age is not None else None,
            'freshness':'report_age_is_not_physical_heartbeat',
            'attributes':limited_attrs(a,('state_class',)+ATTRS.get(domain,()))}
    local=instant(at).astimezone(TZ)
    work=next((s.get('state') for s in states if s.get('entity_id')=='binary_sensor.workday_sensor'),None)
    return {'schema_version':1,'at':at,'points':points,'calendar':{**season_context(at),
        'weekday':local.weekday(),'weekend':local.weekday()>=5,'hour':local.hour,
        'utc_offset_seconds':int(local.utcoffset().total_seconds()),'fold':local.fold,
        'workday':True if work=='on' else False if work=='off' else None},
        'quality':{'count':len(points),'valid':sum(p['quality']=='valid' for p in points.values()),
            'unclassified_temperatures':sum(p['quantity']=='temperature' and p['role']=='unclassified' for p in points.values()),
            'poll_is_not_atomic':True,'private_location_or_person_data':False}}


def ensure_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS environment_samples(at TEXT PRIMARY KEY,payload BLOB NOT NULL);
      CREATE TABLE IF NOT EXISTS temperature_observations(
        entity TEXT NOT NULL,reported_at TEXT NOT NULL,first_seen TEXT NOT NULL,value_c REAL NOT NULL,
        PRIMARY KEY(entity,reported_at));
      CREATE INDEX IF NOT EXISTS temperature_by_time ON temperature_observations(reported_at);
      CREATE TABLE IF NOT EXISTS weather_attempts(entity TEXT NOT NULL,kind TEXT NOT NULL,
        at TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(entity,kind));
      CREATE TABLE IF NOT EXISTS telemetry_mappings(hash TEXT PRIMARY KEY,available_at TEXT NOT NULL,payload BLOB NOT NULL);
      CREATE TABLE IF NOT EXISTS analytics_versions(at TEXT PRIMARY KEY,payload BLOB NOT NULL);
      CREATE TABLE IF NOT EXISTS daily_observed(day TEXT NOT NULL,metric TEXT NOT NULL,value REAL,
        first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(day,metric));''')


def record(store, context):
    ensure_schema(store.db)
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO environment_samples VALUES(?,?)',(context['at'],pack(context)))
        for eid,p in context['points'].items():
            meta={k:p.get(k) for k in ('entity_id','label','quantity','unit','role','role_verified','zone','device_id','area_id','area_name','source_kind')}
            store.db.execute('INSERT OR IGNORE INTO telemetry_mappings VALUES(?,?,?)',(p['mapping_hash'],context['at'],pack(meta)))
            if p['quantity']!='temperature' or p['quality']!='valid' or not finite(p['value']): continue
            try:
                report=instant(p['last_reported']).astimezone(timezone.utc)
                if not 0<=(instant(context['at'])-report).total_seconds()<=1800: continue
            except (KeyError,ValueError,TypeError,AttributeError): continue
            store.db.execute('INSERT OR IGNORE INTO temperature_observations VALUES(?,?,?,?)',
                (eid,report.isoformat(),context['at'],p['value']))


def summary(store, now):
    ensure_schema(store.db);cutoff=(now-timedelta(hours=24)).astimezone(timezone.utc).isoformat()
    row=store.db.execute('SELECT payload FROM environment_samples ORDER BY at DESC LIMIT 1').fetchone()
    latest=unpack(row[0]) if row else {};series=defaultdict(list)
    for eid,at,value in store.db.execute('SELECT entity,reported_at,value_c FROM temperature_observations WHERE reported_at>=? ORDER BY reported_at',(cutoff,)):
        xs=series[eid]
        if not xs or (instant(at)-instant(xs[-1]['at'])).total_seconds()>=600: xs.append({'at':at,'value':value})
    return {'status':'ok' if latest else 'collecting','observed_at':latest.get('at'),
        'calendar':latest.get('calendar',{}),'quality':latest.get('quality',{}),
        'points':list(latest.get('points',{}).values()),'temperature_series':dict(series),
        'counts_by_quantity':dict(Counter(p['quantity'] for p in latest.get('points',{}).values())),
        'note':'Unclassified temperatures are archived, never averaged as room temperatures.'}
