"""Local calibration context. No runtime dependency on another addon database."""
from datetime import timedelta
import gzip,json
from pathlib import Path
from .core import instant,digest
from .store import pack,unpack
from .sqlite_writes import schema_ready
BUNDLE=Path('/share/home-energy-priority-shadow/standalone-context.json.gz')
SCHEMA='standalone-context-v1'
def schema(db):
    if schema_ready(db,('standalone_ev_history','standalone_imports')):return
    db.executescript('''CREATE TABLE IF NOT EXISTS standalone_ev_history(at TEXT PRIMARY KEY,power_w REAL,energy_total_kwh REAL,soc REAL);
    CREATE TABLE IF NOT EXISTS standalone_imports(hash TEXT PRIMARY KEY,payload BLOB NOT NULL);''')
def import_context(store,path=None):
    schema(store.db);path=Path(path)if path is not None else BUNDLE
    if not path.exists():return {'status':'no_import_bundle'}
    with gzip.open(path,'rb')as f:raw=f.read(16*1024*1024+1)
    if len(raw)>16*1024*1024:raise ValueError('STANDALONE_IMPORT_TOO_LARGE')
    bundle=json.loads(raw);data=bundle['data'];key=digest(data)
    if bundle.get('schema')!=SCHEMA or bundle.get('sha256')!=key:raise ValueError('STANDALONE_IMPORT_HASH')
    previous=store.db.execute('SELECT payload FROM standalone_imports WHERE hash=?',(key,)).fetchone()
    if previous:return unpack(previous[0])
    ev=data['ev_rows'];forecasts=data['weather_versions']
    if not isinstance(ev,list)or len(ev)>100000 or not isinstance(forecasts,list)or len(forecasts)>5000:raise ValueError('STANDALONE_IMPORT_COUNT')
    # Validate the entire bundle before any insertion; preserve observation times,
    # nulls and unavailable intervals. Do not fabricate fresh availability.
    seen=set()
    for row in ev:
        instant(row['at'])
        if row['at']in seen:raise ValueError('STANDALONE_EV_DUPLICATE')
        seen.add(row['at'])
        for k in ('power_w','energy_total_kwh','soc'):
            if row[k]is not None and(type(row[k])not in (int,float)or not __import__('math').isfinite(row[k])):raise ValueError('STANDALONE_EV_VALUE')
    prepared=[]
    for v in forecasts:
        instant(v['available_at'])
        if not v['entity'].startswith('weather_forecast:')or not v['entity'].endswith(':hourly'):raise ValueError('STANDALONE_FORECAST_KIND')
        if digest({'entity':v['entity'],'payload':v['payload']})!=v['hash']:raise ValueError('STANDALONE_FORECAST_HASH')
        prepared.append((v,pack(v['payload'])))
    for start in range(0,len(ev),128):
        with store.db:
            for row in ev[start:start+128]:
                values=tuple(row[k]for k in ('at','power_w','energy_total_kwh','soc'))
                old=store.db.execute('SELECT *FROM standalone_ev_history WHERE at=?',(values[0],)).fetchone()
                if old is not None and tuple(old)!=values:raise ValueError('STANDALONE_EV_CONFLICT')
                store.db.execute('INSERT OR IGNORE INTO standalone_ev_history VALUES(?,?,?,?)',values)
    for v,blob in prepared:
        with store.db:
            old=store.db.execute('SELECT kind,payload FROM objects WHERE hash=?',(v['hash'],)).fetchone()
            if old is not None and(old[0]!=v['entity']or unpack(old[1])!=v['payload']):raise ValueError('STANDALONE_FORECAST_CONFLICT')
            store.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',(v['hash'],v['entity'],blob))
            if not store.db.execute('SELECT 1 FROM versions WHERE entity=? AND available_at=? AND hash=?',(v['entity'],v['available_at'],v['hash'])).fetchone():
                store.db.execute('INSERT INTO versions(entity,available_at,hash) VALUES(?,?,?)',(v['entity'],v['available_at'],v['hash']))
    receipt={'status':'imported','sha256':key,'ev_rows':len(ev),'weather_versions':len(prepared),'source':data.get('source'),'source_captured_at':data.get('source_captured_at'),'no_external_runtime_database':True}
    with store.db:store.db.execute('INSERT OR IGNORE INTO standalone_imports VALUES(?,?)',(key,pack(receipt)))
    return receipt

def ev_rows(store,now):
    schema(store.db);end=now.isoformat();start=(now-timedelta(days=60)).isoformat()
    rows=[dict(zip(('at','power_w','energy_total_kwh','soc'),r))for r in store.db.execute('SELECT *FROM standalone_ev_history WHERE at>=? AND at<=? ORDER BY at',(start,end))]
    cutoff=rows[-1]['at']if rows else start
    # Imported historical prefix, then own minute observations. Avoid interleaving
    # two collectors or creating a fake inactive edge across the handover gap.
    for at,blob in store.db.execute('SELECT at,payload FROM soc_observations WHERE at>? AND at<=? ORDER BY at',(cutoff,end)):
        row=unpack(blob);observed=row.get('at',at)
        if instant(observed)>now:continue
        rows.append({'at':observed,'power_w':row.get('ev_w'),'energy_total_kwh':row.get('ev_counter'),'soc':row.get('ev_soc')})
    return rows
