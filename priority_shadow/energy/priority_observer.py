"""Standalone local companion: priority evidence only, never operational control."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,signal,threading,time,sqlite3
from .collector import ReadOnlyHA,DATA,atomic_json
from .core import VERSION,TZ,digest,forecast_payloads,instant
from .store import Store,pack
from . import night,priority,priority_audit,soc_runtime
from . import ram_control as control_journal
from .priority_maintenance import Maintenance
from . import journal_transport,monitor_payload
from .storage import sqlite_bytes
from .sqlite_writes import details as storage_details
import traceback
from .priority_publication import MonitorPublisher
from .priority_collection import SnapshotCollector,CollectionFailure
STOP=threading.Event()
PORTABLE=Path('/share/home-energy-priority-shadow')


def archive_forecasts(store,states,at):
    with store.db:
        for entity,payload in forecast_payloads(states):
            if entity not in (night.IDS['forecast_today'],priority.EXTRA['forecast_tomorrow'],soc_runtime.IDS['forecast_day3'],soc_runtime.IDS['tariff']):continue
            key=digest({'entity':entity,'payload':payload})
            store.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',(key,'solcast',pack(payload)))
            last=store.db.execute('SELECT hash FROM versions WHERE entity=? ORDER BY id DESC LIMIT 1',(entity,)).fetchone()
            if not last or last[0]!=key:store.db.execute('INSERT INTO versions(entity,available_at,hash) VALUES(?,?,?)',(entity,at,key))


def backup():
    PORTABLE.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=PORTABLE/'evidence.next.sqlite'
    source=sqlite3.connect(f'file:{DATA}/evidence.sqlite?mode=ro',uri=True)
    dest=sqlite3.connect(target)
    try:source.backup(dest)
    finally:dest.close();source.close()
    target.chmod(0o600);target.replace(PORTABLE/'evidence.sqlite')


def observe_priority(store,states,at,finish_closed=True):
    """Vadný souhrn jedné noci nesmí zastavit aktuální alokaci ani další noc."""
    if night.window(at):night.record(store,states,at)
    errors=[]
    for day in priority.closed_days(store,at) if finish_closed else ():
        try:priority.finish(store,day)
        except Exception as error:
            errors.append({'day':day,'error_code':type(error).__name__})
    result=priority.observe(store,states,at,require_soc_plan=True,allocation_policy='instant-max-fill-v1')
    result['collection_health']={'status':'degraded' if errors else 'ok','checked_at':at,
        'last_successful_collection_at':at,'summary_errors':errors}
    return result


def collection_reason(error):
    import re
    message=str(error)
    if isinstance(error,RuntimeError):
        match=re.match(r'^(COLLECTION_SNAPSHOT_EXPIRED|COLLECTION_WORKER_FAILED|COLLECTION_THREAD_STALLED|COLLECTION_THREAD_EXITED)(?::([A-Za-z_][A-Za-z_0-9]{0,63}))?$',message)
        if match:return match.group(1)+((':'+match.group(2))if match.group(2)else '')
    return None


def failure_result(at,error,last_success):
    """Nové hlášení chyby nesmí vydávat staré výkony za čerstvé měření."""
    result={'at':last_success,'version':VERSION,'mode':'observe_only','device_actions':0,
        'selected':{'reason':'collection_failed','ev_ac_w':None,'battery_ac_w':None,'grid_model_w':None},
        'collection_health':{'status':'failed','checked_at':at,'last_successful_collection_at':last_success,
                             'error_code':type(error).__name__,'reason_code':collection_reason(error),'summary_errors':[],
                              'error_location':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}for f in traceback.extract_tb(error.__traceback__)[-6:]],
                              'error_file':Path(error.filename).name if isinstance(error,OSError)and error.filename else None}}
    detail=storage_details(error)
    if detail:result['collection_health']['storage_error']=detail
    return result



def next_wait(at,work_s,journal=None):
    """Další krok před lease deadline; původní HA reporty ani TTL se nemění."""
    delay=max(1.,(5 if night.window(at) else 60)-work_s)
    run=(journal or {}).get('session') or {}
    if (run.get('target_ac_w') or 0)>0:
        expiry=(run.get('last_intent') or {}).get('expires_at')
        if expiry:
            remaining=(instant(expiry)-instant(at)).total_seconds()
            # Rezerva pro převzetí čerstvé cache. Při skutečné ztrátě dat
            # řídicí vrstva stále zastaví přesně na původní deadline.
            delay=min(delay,max(.25,remaining-max(1.,work_s+.25)))
    return delay



def observe_control(store,states,result,at,client=None):
    # Počkat na místní writer před získáním snímku a času rozhodnutí.
    # Cache read je bez síťového HTTP; zámek se nedrží během analytiky.
    with store.db:
        if client is not None:
            states=client.priority_states();at=datetime.now(timezone.utc).isoformat()
        points=priority.checked_points(states,at)
        current={'at':at,'session':result.get('session'),
            'priority':priority.LABELS.get(priority.value(points,'priority')),
            'actual':{k:priority.value(points,k)for k in ('battery_a','battery_v','battery_soc','ev_w')},
            'collection_snapshot':{**(states[0].get('collection_snapshot',{})if states else {}),'read_at':at}}
        return control_journal.observe(store,states,current)



def main():
    from .isolated_control import EvidenceBridge,MonitorBridge,run_loop
    os.umask(0o077);DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    from .native_backup import restore as restore_native_backup, finish as finish_native_backup
    restored = restore_native_backup(root=DATA.parent, database=DATA/'evidence.sqlite')
    if restored['status'] == 'restored_native_snapshot':
        print(json.dumps({'native_backup_restore': restored}), flush=True)
        finish_native_backup(root=DATA.parent)
    optionfile=Path('/data/options.json')
    opts=json.loads(optionfile.read_text()) if optionfile.exists()else {}
    if opts.get('mode','observe_only')!='observe_only':raise ValueError('Only observe_only is supported')
    # Privileged, operator-requested, one-shot SQLite migration executes while
    # all evidence writers are STOPPED. A failure must not produce a partial swap.
    from .offline_compaction import run as run_offline_compaction
    try:
        migration=run_offline_compaction(DATA/'evidence.sqlite')
        if migration.get('status')!='no_request':
            print(json.dumps({'offline_db_compaction':migration},ensure_ascii=False),flush=True)
    except Exception as error:
        print(json.dumps({'offline_db_compaction':'failed',
                          'error_code':type(error).__name__},ensure_ascii=False),flush=True)
        # Fail closed instead of quietly continuing after a failed cutover.
        # Original SQLite backup lives on /share; a manual recovery is needed.
        raise

    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:STOP.set())
    # Spawn procesy nemají zděděná SQLite spojení ani zámky vláken.
    evidence=EvidenceBridge(DATA/'evidence.sqlite',opts).start()
    monitor=MonitorBridge({'ha_base_url':'http://supervisor/core','token_file':None}).start()
    client=SnapshotCollector(ReadOnlyHA('http://supervisor/core'),period=2.5,night_period=1.,
                             failure_path=DATA/'collection-failure.json',defer_failure_persistence=True).start()
    try:run_loop(client,evidence,monitor,STOP)
    finally:
        client.close();evidence.close();monitor.close()

if __name__=='__main__':main()
