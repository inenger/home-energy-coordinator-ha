"""Standalone local companion: priority evidence only, never operational control."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,signal,threading,time,sqlite3
from .collector import ReadOnlyHA,DATA,atomic_json
from .core import VERSION,TZ,digest,forecast_payloads
from .store import Store,pack
from . import night,priority,priority_audit,soc_runtime
from .publish_status import publish_priority
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


def main():
    os.umask(0o077);DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    optionfile=Path('/data/options.json');opts=json.loads(optionfile.read_text()) if optionfile.exists() else {}
    if opts.get('mode','observe_only')!='observe_only':raise ValueError('Only observe_only is supported')
    cfg={'ha_base_url':'http://supervisor/core','token_file':None}
    client=ReadOnlyHA(cfg['ha_base_url'])
    planner=soc_runtime.PlannerService(opts)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:STOP.set())
    print(json.dumps({'version':VERSION,'component':'local_priority_shadow','mode':'observe_only','device_actions':0}),flush=True)
    next_backup=0;next_day_audit=0;day_audit_error=None
    while not STOP.is_set():
        started=time.monotonic();now=datetime.now(timezone.utc)
        try:
            used=sum(p.stat().st_size for p in DATA.glob('evidence.sqlite*'))
            if used>int(opts.get('storage_limit_mb',2048))*1024*1024:raise RuntimeError('STORAGE_BUDGET_EXCEEDED_NO_DELETE')
            states=client.priority_states();at=datetime.now(timezone.utc).isoformat();local=datetime.now(TZ)
            store=Store(DATA/'evidence.sqlite')
            try:
                night.ensure_schema(store.db);priority.schema(store.db)
                archive_forecasts(store,states,at)
                optimizer=planner.observe(store,states,at,client)
                if night.window(at):night.record(store,states,at)
                for day in priority.closed_days(store,at):priority.finish(store,day)
                result=priority.observe(store,states,at,require_soc_plan=True)
                result['soc_optimizer']=optimizer
                priority_audit.journal(store,result)
                if time.monotonic()>=next_day_audit:
                    try:
                        priority_audit.update_day_audit(store,client,at);day_audit_error=None
                        next_day_audit=time.monotonic()+600
                    except Exception as e:
                        day_audit_error=type(e).__name__;next_day_audit=time.monotonic()+600
                result['command_audit']=priority_audit.command_summary(store,at)
                result['fve_soc_audit']=priority_audit.day_summary(store,at,day_audit_error)
                try:result['soc_optimizer']['review_history']=soc_runtime.review(store,result['fve_soc_audit'],at)
                except Exception as e:result['soc_optimizer']['review_error_code']=type(e).__name__
            finally:store.close()
            atomic_json(DATA/'priority-live.json',result)
            publish_priority(result,cfg)
            print(json.dumps({'priority_collection':'ok','at':at,'active':result['active'],'priority':result['priority'],
                              'reason':result['selected']['reason'],'soc_planner':optimizer.get('status'),
                              'soc_target_pct':optimizer.get('target_soc_pct'),'device_actions':0}),flush=True)
            if time.monotonic()>=next_backup:
                backup();next_backup=time.monotonic()+3600
        except Exception as e:
            print(json.dumps({'priority_collection':'failed','error_code':type(e).__name__,'device_actions':0}),flush=True)
        STOP.wait(max(1,(15 if night.window(now.isoformat()) else 60)-(time.monotonic()-started)))
    try:backup()
    except Exception:pass
    print(json.dumps({'priority_runtime':'stopped','device_actions':0}),flush=True)

if __name__=='__main__':main()
