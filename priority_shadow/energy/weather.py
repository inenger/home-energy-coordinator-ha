"""Archive HA forecasts and compare hourly temperature with an explicit local sensor."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean
from bisect import bisect_left
import math
import re
from .core import instant, digest
from .store import pack, unpack
from .telemetry import ensure_schema, finite, celsius, limited_attrs

KINDS={'daily':1,'hourly':2,'twice_daily':4}
FIELDS=('datetime','condition','temperature','templow','apparent_temperature','dew_point','humidity',
        'pressure','wind_speed','wind_gust_speed','wind_bearing','cloud_coverage','precipitation',
        'precipitation_probability','uv_index','is_daytime')


def request_parts(entity,kind):
    if not re.fullmatch(r'weather\.[a-z0-9_]+',entity) or kind not in KINDS:
        raise ValueError('Only weather.get_forecasts is allowed')
    return '/api/services/weather/get_forecasts?return_response', {'entity_id':entity,'type':kind}


def clean_response(body, entity, kind, attrs):
    rows=body.get('service_response',{}).get(entity,{}).get('forecast')
    if not isinstance(rows,list) or not 0<len(rows)<=500: raise ValueError('Invalid forecast response')
    out=[]
    for row in rows:
        if not isinstance(row,dict): continue
        try: target=instant(row['datetime']).astimezone(timezone.utc).isoformat()
        except (KeyError,TypeError,ValueError): continue
        clean=limited_attrs(row,FIELDS);clean['datetime']=target;out.append(clean)
    if not out: raise ValueError('Empty forecast')
    return {'schema_version':1,'entity_id':entity,'forecast_type':kind,'forecast':out,
        'units':limited_attrs(attrs,('temperature_unit','pressure_unit','wind_speed_unit','precipitation_unit')),
        'provider_issued_at':None,'source_kind':'provider_forecast',
        'availability_definition':'first received by coordinator; provider issue time unavailable'}


def record_version(store, entity, payload, at):
    h=digest({'entity':entity,'payload':payload})
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',(h,entity,pack(payload)))
        last=store.db.execute('SELECT hash FROM versions WHERE entity=? ORDER BY id DESC LIMIT 1',(entity,)).fetchone()
        if not last or last[0]!=h:
            store.db.execute('INSERT INTO versions(entity,available_at,hash) VALUES(?,?,?)',(entity,at,h))


def poll(store, client, states, cfg, now):
    ensure_schema(store.db)
    if not cfg.get('weather_enabled',True): return {'status':'disabled'}
    targets=[s for s in states if s.get('entity_id','').startswith('weather.')]
    due=[];period=cfg.get('weather_interval_seconds',3600)
    for state in targets:
        features=(state.get('attributes') or {}).get('supported_features',0)
        for kind in cfg.get('weather_types',['hourly','daily']):
            if kind not in KINDS: continue
            if isinstance(features,int) and features and not features & KINDS[kind]: continue
            entity=state['entity_id']
            old=store.db.execute('SELECT at,status FROM weather_attempts WHERE entity=? AND kind=?',(entity,kind)).fetchone()
            retry=period if not old or old[1]=='ok' else max(period,21600)
            if old and (now-instant(old[0])).total_seconds()<retry: continue
            due.append((old[0] if old else '',entity,kind,state))
    results=[]
    for _,entity,kind,state in sorted(due,key=lambda r:r[:3])[:2]:
        status='ok'
        try:
            raw=client.weather_forecast(entity,kind)
            payload=clean_response(raw,entity,kind,state.get('attributes') or {})
            at=datetime.now(timezone.utc).isoformat()
            record_version(store,'weather_forecast:'+entity+':'+kind,payload,at)
        except Exception as e:
            status=type(e).__name__;at=datetime.now(timezone.utc).isoformat()
        with store.db:
            store.db.execute('INSERT OR REPLACE INTO weather_attempts VALUES(?,?,?,?)',(entity,kind,at,status))
        results.append({'entity':entity,'kind':kind,'status':status})
    return {'status':'ok' if targets else 'no_weather_entities','sources':len(targets),
            'requests':results,'deferred':max(0,len(due)-2)}


def lead_bucket(hours):
    for lo,hi,label in ((0,6,'0-6h'),(6,24,'6-24h'),(24,48,'24-48h'),(48,96,'48-96h'),(96,192,'96-192h')):
        if lo<=hours<hi: return label
    return None


def comparison(forecasts, observations, reference, now):
    measures={}
    for r in observations:
        if not finite(r.get('value_c')): continue
        try:
            at=instant(r['reported_at']).timestamp();first=instant(r['first_seen']).timestamp()
            if not 0<=first-at<=1800 or first>now.timestamp(): continue
        except (KeyError,ValueError,TypeError): continue
        measures[at]=r['value_c']
    times=sorted(measures);chosen={}
    for version in forecasts:
        p=version.get('payload') or {}
        if p.get('forecast_type')!='hourly': continue
        try: available=instant(version['available_at']).timestamp()
        except (KeyError,TypeError,ValueError): continue
        for row in p.get('forecast',[]):
            try: target=instant(row['datetime']).timestamp()
            except (KeyError,ValueError,TypeError): continue
            if target>=now.timestamp() or available>target: continue
            bucket=lead_bucket((target-available)/3600)
            expected=celsius(row.get('temperature'),p.get('units',{}).get('temperature_unit'))
            if not bucket or expected is None or not times: continue
            pos=bisect_left(times,target);candidates=times[max(0,pos-1):pos+1]
            nearest=min(candidates,key=lambda t:abs(t-target)) if candidates else None
            if nearest is None or abs(nearest-target)>600: continue
            key=(p['entity_id'],target,bucket)
            if key in chosen and chosen[key]['available_ts']>=available: continue
            chosen[key]={'provider':p['entity_id'],'target':row['datetime'],'bucket':bucket,
                'forecast_c':expected,'actual_c':measures[nearest],
                'actual_reported_at':datetime.fromtimestamp(nearest,timezone.utc).isoformat(),
                'available_at':version['available_at'],'available_ts':available}
    groups=defaultdict(list)
    for r in chosen.values(): groups[(r['provider'],r['bucket'])].append(r['actual_c']-r['forecast_c'])
    metrics=[{'provider':provider,'lead_bucket':bucket,'n':len(xs),'mae_c':round(mean(abs(x) for x in xs),3),
        'bias_c':round(mean(xs),3),'rmse_c':round(math.sqrt(mean(x*x for x in xs)),3)} for (provider,bucket),xs in sorted(groups.items())]
    return {'status':'ok' if chosen else 'collecting_pairs','reference_entity':reference,
        'reference_kind':'explicit_local_sensor','metrics':metrics,
        'pairs':[{k:v for k,v in r.items() if k!='available_ts'} for r in sorted(chosen.values(),key=lambda r:r['target'])[-240:]],
        'note':'Daily high/low is not instantaneous temperature. Provider current weather is never ground truth.'}


def summary(store, now, reference):
    ensure_schema(store.db);cutoff=(now-timedelta(days=7)).astimezone(timezone.utc).isoformat()
    versions=[{'available_at':at,'payload':unpack(p)} for at,p in store.db.execute('''
      SELECT v.available_at,o.payload FROM versions v JOIN objects o ON o.hash=v.hash
      WHERE v.entity LIKE 'weather_forecast:%' AND v.available_at>=? ORDER BY v.available_at''',(cutoff,))]
    observations=[dict(zip(('reported_at','first_seen','value_c'),r)) for r in store.db.execute(
        'SELECT reported_at,first_seen,value_c FROM temperature_observations WHERE entity=? AND reported_at>=? ORDER BY reported_at',(reference,cutoff))]
    result=comparison(versions,observations,reference,now)
    result['attempts']=[dict(zip(('entity','kind','at','status'),r)) for r in store.db.execute('SELECT * FROM weather_attempts')]
    result['forecast_versions']=len(versions);latest={}
    for v in versions: latest[(v['payload']['entity_id'],v['payload']['forecast_type'])]=v
    result['latest']=list(latest.values())
    return result
