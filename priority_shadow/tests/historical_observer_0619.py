"""Standalone local companion: priority evidence only, never operational control."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,signal,threading,time,sqlite3
from energy.collector import ReadOnlyHA,DATA,atomic_json
from energy.core import VERSION,TZ,digest,forecast_payloads,instant
from energy.store import Store,pack
from energy import night,priority,priority_audit,soc_runtime
from energy import ram_control as control_journal
from energy.priority_maintenance import Maintenance
from energy import journal_transport,monitor_payload
from energy.storage import sqlite_bytes
from energy.sqlite_writes import details as storage_details
import traceback
from energy.priority_publication import MonitorPublisher
from energy.priority_collection import SnapshotCollector,CollectionFailure
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


def failure_result(at,error,last_success):
    """Nové hlášení chyby nesmí vydávat staré výkony za čerstvé měření."""
    result={'at':last_success,'version':VERSION,'mode':'observe_only','device_actions':0,
        'selected':{'reason':'collection_failed','ev_ac_w':None,'battery_ac_w':None,'grid_model_w':None},
        'collection_health':{'status':'failed','checked_at':at,'last_successful_collection_at':last_success,
                             'error_code':type(error).__name__,'summary_errors':[],
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
    os.umask(0o077);DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    optionfile=Path('/data/options.json');opts=json.loads(optionfile.read_text()) if optionfile.exists() else {}
    if opts.get('mode','observe_only')!='observe_only':raise ValueError('Only observe_only is supported')
    cfg={'ha_base_url':'http://supervisor/core','token_file':None}
    client=SnapshotCollector(ReadOnlyHA(cfg['ha_base_url']),period=2.5,night_period=1.,failure_path=DATA/'collection-failure.json').start()
    maintenance=Maintenance(DATA/'evidence.sqlite',opts,backup)
    journal_publisher=journal_transport.Publisher(DATA/'evidence.sqlite').start()
    monitoring=MonitorPublisher(cfg).start()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:STOP.set())
    print(json.dumps({'version':VERSION,'component':'local_priority_shadow','mode':'observe_only','device_actions':0}),flush=True)
    last_success=None;failure_pending=None;last_priority_result=None;analysis_budget_s=1.
    try:
        previous=json.loads((DATA/'priority-live.json').read_text())
        last_success=previous.get('at')
        if previous.get('collection_health',{}).get('status')=='failed':failure_pending=previous.get('unpersisted_failure_at') or previous['collection_health'].get('checked_at')
    except (OSError,ValueError,TypeError):pass
    while not STOP.is_set():
        started=time.monotonic();now=datetime.now(timezone.utc);loop_journal=None
        try:
            used=sqlite_bytes(DATA,required=last_success is not None)
            if used>int(opts.get('storage_limit_mb',2048))*1024*1024:raise RuntimeError('STORAGE_BUDGET_EXCEEDED_NO_DELETE')
            input_started=time.monotonic();states=client.priority_states();input_read_s=time.monotonic()-input_started;db_started=time.monotonic();at=datetime.now(timezone.utc).isoformat();local=datetime.now(TZ)
            store=Store(DATA/'evidence.sqlite',timeout=.25)
            try:
                night.ensure_schema(store.db);priority.schema(store.db)
                # RAM má přednost před analytikou. Zmrazený model/prognóza se
                # přebírá jen ze stejného dne a již dokončeného výpočtu.
                cached=last_priority_result if ((last_priority_result or {}).get('session')or{}).get('day')==local.date().isoformat() else None
                early=None
                if cached:
                    if failure_pending:
                        control_journal.record_failure(store,failure_pending,'collection_failure_pending');failure_pending=None
                    early=observe_control(store,states,cached,at,client=client)
                run=(early or {}).get('session')or {}
                expiry=(run.get('last_intent')or {}).get('expires_at')
                headroom=(instant(expiry)-instant((early or {}).get('observed_at')or at)).total_seconds()if expiry and run.get('target_ac_w',0)>0 else None
                # Krátký platný lease se nesmí spotřebovat pomalou analytikou.
                # Při odkladu zůstává poslední analytický čas pravdivě původní.
                deferred=headroom is not None and headroom<=analysis_budget_s
                slow=maintenance.snapshot()
                if not deferred:
                    analysis_start=time.monotonic()
                    archive_forecasts(store,states,at)
                    maintenance.submit(states,at)
                    result=observe_priority(store,states,at,finish_closed=False)
                    analysis_budget_s=max(1.,time.monotonic()-analysis_start+.5)
                else:
                    result=dict(cached)
                optimizer=slow.get('soc_optimizer',{})
                result['collection_snapshot']={**(states[0].get('collection_snapshot',{})if states else {}),'read_at':at}
                result['soc_optimizer']=optimizer
                result['maintenance']={k:v for k,v in slow.items() if k not in ('soc_optimizer','fve_soc_audit')}
                result['collection_health']=dict(result['collection_health'])
                result['collection_health']['summary_errors']=slow.get('summary_errors',[])
                if slow.get('maintenance_error') or slow.get('summary_errors'):result['collection_health']['status']='degraded'
                if early is None:
                    # První model se vytvořil až v tomto kroku: před prvním
                    # návrhem znovu převzít cache a použít aktuální čas.
                    if failure_pending:
                        control_journal.record_failure(store,failure_pending,'collection_failure_pending');failure_pending=None
                    early=observe_control(store,states,result,at,client=client)
                result['control_journal']=early
                result['analytics_scheduling']={'deferred_for_control_deadline':deferred,'work_budget_s':analysis_budget_s}
                result['control_journal']['transport']=journal_transport.enqueue(store,result['control_journal'])
                if result['control_journal']['transport'].get('status')=='degraded':
                    result['collection_health']['status']='degraded'
                    result['collection_health']['journal_transport_error']=result['control_journal']['transport'].get('error_code')
                if not deferred:
                    priority_audit.journal(store,result)
                    result['command_audit']=priority_audit.command_summary(store,at)
                    last_priority_result=dict(result)
                result['fve_soc_audit']=slow.get('fve_soc_audit',{})
            finally:store.close()
            loop_journal=result['control_journal']
            result['monitor_publication']=monitoring.snapshot()
            if result['monitor_publication'].get('status')=='degraded':
                result['collection_health'].update(status='degraded',monitor_publication_error=result['monitor_publication'].get('error_code'))
            result['fast_loop']={'target_interval_s':5 if night.window(at) else 60,'last_work_duration_s':time.monotonic()-started,'physical_control_ready':False,'monitoring_http_in_control_thread':False,'collection_http_in_control_thread':False,'collection_worker':client.snapshot(),'input_read_s':input_read_s,'database_processing_s':time.monotonic()-db_started}
            monitoring.submit(result)
            result['fast_loop']['last_work_duration_s']=time.monotonic()-started
            atomic_json(DATA/'priority-live.json',result)
            last_success=at
            print(json.dumps({'priority_collection':'ok','at':at,'active':result['active'],'priority':result['priority'],
                              'reason':result['selected']['reason'],'collection_health':result['collection_health'],'soc_planner':optimizer.get('status'),
                              'soc_target_pct':optimizer.get('target_soc_pct'),'fast_work_duration_s':time.monotonic()-started,'monitor_publication':monitoring.snapshot(),'device_actions':0}),flush=True)
        except Exception as e:
            failed=failure_result(datetime.now(timezone.utc).isoformat(),e,last_success)
            failure_at=e.failure_at if isinstance(e,CollectionFailure) else failed['collection_health']['checked_at']
            # Jiná chyba (např. stat/storage budget) nesmí zakrýt starší
            # dosud nepřevzatý výpadek síťového workeru.
            pending_collection=client.snapshot().get('pending_failure')
            pending_at=pending_collection['first_at'] if pending_collection else None
            failure_pending=min(filter(None,[failure_pending,failure_at,pending_at]),key=instant)
            if pending_collection:failed['collection_health']['pending_collection_failure']=pending_collection
            try:
                journal_store=Store(DATA/'evidence.sqlite',timeout=.25)
                try:
                    if isinstance(e,monitor_payload.PayloadOverflow):monitor_payload.record_overflow(journal_store,e,datetime.now(timezone.utc).isoformat())
                    failed['control_journal']=control_journal.record_failure(journal_store,failure_pending,type(e).__name__,diagnostics=storage_details(e))
                    failed['control_journal']['transport']=journal_transport.enqueue(journal_store,failed['control_journal'])
                    if pending_collection:client.acknowledge_failure(pending_collection['generation'])
                    elif isinstance(e,CollectionFailure):client.acknowledge_failure(e.generation)
                    failure_pending=None
                finally:journal_store.close()
            except Exception as journal_error:
                failed['control_journal']={'status':'error','error_code':type(journal_error).__name__,'storage_error':storage_details(journal_error),'device_actions':0}
            loop_journal=failed.get('control_journal')
            if failure_pending:failed['unpersisted_failure_at']=failure_pending
            print(json.dumps({'priority_collection':'failed',**failed['collection_health'],'device_actions':0}),flush=True)
            try:
                atomic_json(DATA/'priority-live.json',failed)
                monitoring.submit(failed,failure=True)
            except Exception as monitor_error:
                print(json.dumps({'priority_failure_publication':'failed','error_code':type(monitor_error).__name__}),flush=True)
        STOP.wait(next_wait(datetime.now(timezone.utc).isoformat(),time.monotonic()-started,loop_journal))
    client.close();publisher_closed=journal_publisher.close();monitoring_closed=monitoring.close()
    if maintenance.close() and publisher_closed and monitoring_closed:
        try:backup()
        except Exception:pass
    print(json.dumps({'priority_runtime':'stopped','device_actions':0}),flush=True)

# Explicit historical regression baseline; never the addon entrypoint.
