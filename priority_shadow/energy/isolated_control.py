"""Řídicí stav v soukromé RAM; disk, analytika a monitoring v jiných procesech.

Nejde o hard real-time záruku Linuxu ani o fyzický akční adaptér.
Paměťové SQLite zachovává otestovanou stavovou logiku; neotevírá diskový soubor.
"""
import copy,multiprocessing as mp,pickle,queue,sqlite3,time,uuid,threading,os
from datetime import datetime,timezone
from . import ram_control as control,control_journal as legacy,priority,night
from .core import TZ,VERSION,instant
from .store import Store,unpack
from .sqlite_writes import details

TABLES={
 'ram_control_sessions':('day','payload'),
 'ram_control_events':('id','day','at','payload'),
 'ram_control_samples':('at','day','payload'),
 'control_sessions':('day','payload'),
 'control_events':('id','day','at','payload'),
 'control_samples':('at','day','payload'),
}
MAX_BATCH_BYTES=512*1024
QUEUE_BATCHES=64

def utcnow():return datetime.now(timezone.utc).isoformat()

def latest(channel,value):
    """Nahraditelná odpověď obslužného procesu; řídicí vlákno tuto IPC cestu nevolá."""
    try:channel.put_nowait(value);return True
    except queue.Full:
        try:channel.get_nowait()
        except queue.Empty:pass
        try:channel.put_nowait(value);return True
        except queue.Full:return False

def drain(channel,default=None):
    for _ in range(8):
        try:default=channel.get_nowait()
        except queue.Empty:break
    return default

def seed_from(store):
    """Omezený startovní stav. Žádné přehrávání historie jako nových vzorků."""
    control.schema(store.db);legacy.schema(store.db)
    out={}
    for name in TABLES:
        if name.endswith('sessions'):
            rows=[]
            for i,row in enumerate(store.db.execute('SELECT * FROM '+name+' ORDER BY day DESC')):
                if i<14 or not unpack(row[-1]).get('closed_at'):rows.append(row)
                if len(rows)>64:raise ValueError('TOO_MANY_UNRESOLVED_CONTROL_SESSIONS')
        elif name.endswith('events'):
            rows=list(store.db.execute('SELECT * FROM '+name+' ORDER BY id DESC LIMIT 24'))
        else:rows=list(store.db.execute('SELECT * FROM '+name+' ORDER BY at DESC LIMIT 2'))
        out[name]=rows
    if len(pickle.dumps(out))>4*1024*1024:raise ValueError('CONTROL_BOOTSTRAP_TOO_LARGE')
    return out

class MemoryControl:
    """Jediný vlastník řídicího stavu. Žádný disk, síť ani sdílený writer gate."""
    def __init__(self,seed=None):
        self.db=sqlite3.connect(':memory:')
        control.schema(self.db);legacy.schema(self.db)
        for name,rows in (seed or {}).items():
            if name not in TABLES:raise ValueError('Unexpected bootstrap table')
            self.db.executemany('INSERT INTO '+name+' VALUES('+','.join('?'for _ in TABLES[name])+')',rows)
        self.db.commit()
        self.events={n:self.db.execute('SELECT coalesce(max(id),0) FROM '+n).fetchone()[0]for n in TABLES if n.endswith('events')}
        self.samples={n:self.db.execute('SELECT coalesce(max(rowid),0) FROM '+n).fetchone()[0]for n in TABLES if n.endswith('samples')}
        self.sessions={n:dict(self.db.execute('SELECT day,payload FROM '+n))for n in TABLES if n.endswith('sessions')}
        self.restart=bool(seed)
        times=[v for name in self.sessions for payload in self.sessions[name].values()
               for run in [unpack(payload)]for v in (run.get('last_processed_at'),run.get('closed_at'))if v]
        self.watermark=max(times,key=instant)if times else None
    def step(self,states,analysis,at):
        if self.restart:
            # Při restartu nelze dokázat poslední neuložený stav. Nikdy nepokračovat
            # ve staré lease; obnova opět vyžaduje dvě nové platné sady.
            from .store import pack
            for day,p in list(self.db.execute('SELECT day,payload FROM ram_control_sessions')):
                run=unpack(p)
                if not run.get('closed_at'):
                    run.setdefault('evidence_integrity',{'status':'unknown','reason':'runtime_restart_unflushed_state_unknown'})
                    with self.db:self.db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(run),day))
            control.record_failure(self,at,'runtime_restart_unflushed_state_unknown')
            self.restart=False
        points=priority.checked_points(states,at)
        session=(analysis or {}).get('session')
        if not session or session.get('day')!=instant(at).astimezone(TZ).date().isoformat():
            session={'allocation_policy':'instant-max-fill-v1'}
        if any(session.get(k)and instant(session[k])>instant(at)for k in ('model_available_at','soc_plan_issued_at')):
            session={'allocation_policy':'instant-max-fill-v1'}
        current={'at':at,'session':session,'priority':priority.LABELS.get(priority.value(points,'priority')),
                 'actual':{k:priority.value(points,k)for k in ('battery_a','battery_v','battery_soc','ev_w')},
                 'collection_snapshot':{**(states[0].get('collection_snapshot',{})if states else {}),'read_at':at}}
        if self.watermark and instant(at)<instant(self.watermark):
            journal=control.record_failure(self,at,'clock_rollback')
            journal.update(status='waiting_clock_recovery',resume_after=self.watermark)
            current['selected']={'reason':'clock_rollback','battery_ac_w':0,'ev_ac_w':None,'grid_model_w':None,'phase':[]}
            return current,journal
        journal=control.observe(self,states,current)
        self.watermark=at
        sample=next(iter(journal.get('recent_samples',[])),{})
        run=journal.get('session')or {}
        allocation=priority.allocate(points,at,session,(run.get('shadow_model')or{}).get('soc_pct'),current['priority'])
        current['selected']=allocation
        return current,journal
    def failure(self,at,error):
        self.restart=False
        return control.record_failure(self,at,type(error).__name__,diagnostics=details(error))
    def annotate_loss(self,loss):
        from .store import pack
        for day,payload in list(self.db.execute('SELECT day,payload FROM ram_control_sessions')):
            if not loss.get('days',{}).get(day):continue
            run=unpack(payload)
            # Uzavřený snapshot je neměnný i v RAM; pozdější ztráta je
            # samostatný trvalý doklad v control_evidence_batches.payload.
            if run.get('closed_at'):continue
            run['evidence_integrity']={'status':'incomplete','reason':'bounded_volatile_queue_overflow',
                'lost_batches':loss['days'][day],'runtime_loss_first_at':loss.get('first_at'),
                'runtime_loss_last_at':loss.get('last_at')}
            with self.db:self.db.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(run),day))
    def retry_sessions(self):
        self.sessions={name:{}for name in self.sessions}
    def delta(self):
        out={}
        for name in TABLES:
            if name in self.events:
                out[name]=list(self.db.execute('SELECT * FROM '+name+' WHERE id>? ORDER BY id',(self.events[name],)))
                if out[name]:self.events[name]=out[name][-1][0]
            elif name in self.samples:
                rows=list(self.db.execute('SELECT rowid,* FROM '+name+' WHERE rowid>? ORDER BY rowid',(self.samples[name],)))
                out[name]=[r[1:]for r in rows]
                if rows:self.samples[name]=rows[-1][0]
            else:
                current=dict(self.db.execute('SELECT day,payload FROM '+name))
                out[name]=[(d,p)for d,p in current.items()if self.sessions[name].get(d)!=p]
                self.sessions[name]=current
        # Oříznutí se týká jen dočasné RAM, nikdy původní evidence na disku.
        with self.db:
            for name in self.events:self.db.execute('DELETE FROM '+name+' WHERE id NOT IN (SELECT id FROM '+name+' ORDER BY id DESC LIMIT 24)')
            for name in self.samples:self.db.execute('DELETE FROM '+name+' WHERE rowid NOT IN (SELECT rowid FROM '+name+' ORDER BY rowid DESC LIMIT 2)')
            for name in self.sessions:
                for day,payload in list(self.db.execute('SELECT day,payload FROM '+name+' ORDER BY day DESC'))[14:]:
                    if unpack(payload).get('closed_at'):self.db.execute('DELETE FROM '+name+' WHERE day=?',(day,))
        return out
    def close(self):self.db.close()

def persist_batch(store,batch):
    """Idempotentní FIFO flush. Potvrzení až po commit, bez přepisů immutable řádků."""
    db=store.db;control.schema(db);legacy.schema(db)
    db.executescript('CREATE TABLE IF NOT EXISTS control_evidence_batches(runtime TEXT,seq INTEGER,at TEXT,payload BLOB,PRIMARY KEY(runtime,seq));')
    from .ancillary_analytics import schema as analytics_schema
    analytics_schema(db)
    key=(batch['runtime'],batch['seq'])
    if db.execute('SELECT 1 FROM control_evidence_batches WHERE runtime=? AND seq=?',key).fetchone():return
    from .store import pack
    analytic_payload=pack({k:batch[k]for k in ('at','states','result')}) if 'states'in batch and 'result'in batch else None
    with db:
        for name,rows in batch['rows'].items():
            if name not in TABLES:raise ValueError('Unexpected evidence table')
            for row in rows:
                if name.endswith('sessions'):
                    previous=db.execute('SELECT payload FROM '+name+' WHERE day=?',(row[0],)).fetchone()
                    if previous and unpack(previous[0]).get('closed_at') and previous[0]!=row[-1]:
                        raise ValueError('CLOSED_CONTROL_SESSION_CONFLICT')
                    db.execute('INSERT OR REPLACE INTO '+name+' VALUES(?,?)',row)
                else:
                    previous=db.execute('SELECT * FROM '+name+' WHERE '+TABLES[name][0]+'=?',(row[0],)).fetchone()
                    if previous is not None:
                        if tuple(previous)!=tuple(row):raise ValueError('IMMUTABLE_CONTROL_EVIDENCE_CONFLICT')
                    else:db.execute('INSERT INTO '+name+' VALUES('+','.join('?'for _ in row)+')',row)
        db.execute('INSERT INTO control_evidence_batches VALUES(?,?,?,?)',(*key,batch['at'],pack(batch['loss'])))
        if analytic_payload is not None:
            db.execute('INSERT INTO control_analytics_pending(runtime,seq,at,payload) VALUES(?,?,?,?)',(*key,batch['at'],analytic_payload))

def evidence_worker(path,options,inbox,output,bootstrap,stopping):
    """Disk a analytika mají vlastní proces, spojení i chybovou větev."""
    from . import priority_observer as observer,journal_transport
    from .priority_maintenance import Maintenance
    os.nice(10)
    path=__import__('pathlib').Path(path);maintenance=None;publisher=None;analytics=None
    pending=None;ack=0;ack_generation=None;analysis={};transport={};booted=False
    last_response={'ack':0,'storage_health':{'status':'starting'}}
    def emit(value):
        nonlocal last_response
        last_response=value
        latest(output,value)
    try:
        while not stopping.is_set():
            try:
                if not booted:
                    store=Store(path)
                    try:seed=seed_from(store)
                    finally:store.close()
                    bootstrap.put(seed)
                    maintenance=Maintenance(path,options,observer.backup)
                    publisher=journal_transport.Publisher(path).start()
                    from .ancillary_analytics import Analytics
                    analytics=Analytics(path,maintenance).start();booted=True
                if pending is None:
                    try:pending=inbox.get(timeout=.25)
                    except queue.Empty:
                        auxiliary=analytics.snapshot()
                        emit({**last_response,'analysis':auxiliary.get('analysis',analysis),
                              'analytics_health':auxiliary.get('health',{'status':'starting'})});continue
                from .storage import sqlite_bytes
                used=sqlite_bytes(path.parent,required=True)
                if used>int(options.get('storage_limit_mb',2048))*1024*1024:
                    raise RuntimeError('STORAGE_BUDGET_EXCEEDED_NO_DELETE')
                store=Store(path,timeout=.25)
                try:
                    persist_batch(store,pending)
                    # Potvrzení výpadku kolektoru až po commitu a trvalém outboxu.
                    transport=journal_transport.enqueue(store,pending['result'].get('control_journal',{}))
                    ack=pending['seq'];ack_generation=pending.get('failure_generation')or ack_generation
                finally:store.close()
                auxiliary=analytics.snapshot();analysis=auxiliary.get('analysis',analysis)
                emit({'ack':ack,'ack_generation':ack_generation,'analysis':analysis,
                      'analytics_health':auxiliary.get('health',{'status':'starting'}),
                      'transport':transport,'storage_health':{'status':'ok','checked_at':utcnow()}})
                pending=None
                analytics.wake.set()

            except Exception as error:
                emit({'ack':ack,'ack_generation':ack_generation,'analysis':analysis,
                    'transport':transport,'storage_health':{'status':'degraded','checked_at':utcnow(),
                    'stage':'bootstrap_or_evidence','error_code':type(error).__name__,'storage_error':details(error)}})
                stopping.wait(.5)
    finally:
        if booted:
            try:observer.backup()
            except Exception:pass
        if analytics:analytics.close()
        if publisher:publisher.close()
        if maintenance:maintenance.close()

def monitor_worker(cfg,inbox,output,stopping):
    """Příprava/komprese i HTTP monitorů jsou mimo řídicí proces."""
    from .priority_publication import MonitorPublisher
    os.nice(5)
    from .monitor_overflow import OverflowArchive
    archive=OverflowArchive(cfg)
    monitoring=MonitorPublisher(cfg,overflow=archive.capture).start();preparation_error=None
    def health():
        value={**monitoring.snapshot(),**archive.health()}
        if preparation_error:
            return {**value,'status':'degraded','error_code':preparation_error,'stage':'monitor_preparation'}
        return value
    try:
        while not stopping.is_set():
            try:result=inbox.get(timeout=.25)
            except queue.Empty:
                latest(output,health());continue
            result=drain(inbox,result)
            try:
                archive.begin()
                monitoring.submit(result,failure=result.get('collection_health',{}).get('status')=='failed')
                preparation_error=None
                latest(output,health())
            except Exception as error:
                preparation_error=type(error).__name__
                latest(output,health())
    finally:monitoring.close()

class EvidenceBridge:
    def __init__(self,path,options,capacity=QUEUE_BATCHES):
        from .process_supervision import WorkerGuard
        self.ctx=mp.get_context('spawn');self.path=str(path);self.options=options;self.capacity=capacity
        self.inbox=self.ctx.Queue(capacity);self.output=self.ctx.Queue(2);self.bootstrap=self.ctx.Queue(1);self.stop=self.ctx.Event()
        self.process=self.new_process()
        self.runtime=uuid.uuid4().hex;self.seq=0;self.ack=0;self.last={};self.last_accepted=0;self.inflight={}
        self.reader_stop=threading.Event();self.reader_lock=threading.Lock();self.seed_value=None;self.reader=None
        self.seed_consumed=False;self.epoch=0;self.last_reply=time.monotonic()
        self.replay={};self.sent=set();self.retired_readers=[];self.retired_feeders=[];self.guard=WorkerGuard(self)
        self.loss={'batches':0,'events':0,'samples':0,'first_at':None,'last_at':None,'days':{}}
    def new_process(self):
        return self.ctx.Process(target=evidence_worker,args=(self.path,self.options,self.inbox,self.output,self.bootstrap,self.stop),daemon=True)
    def start_reader(self):
        self.reader=threading.Thread(target=self.read_responses,args=(self.bootstrap,self.output,self.epoch),name='evidence-ipc-reader',daemon=True)
        self.reader.start()
    def start(self):
        self.process.start();self.last_reply=time.monotonic();self.start_reader();self.guard.start();return self
    def read_responses(self,bootstrap,output,epoch):
        seeded=False
        while not self.reader_stop.is_set() and epoch==self.epoch:
            try:
                if not seeded:
                    try:
                        seed=bootstrap.get(timeout=.05)
                        with self.reader_lock:
                            if epoch!=self.epoch:return
                            if not self.seed_consumed:self.seed_value=seed
                            self.last_reply=time.monotonic()
                        seeded=True
                    except queue.Empty:pass
                try:value=output.get(timeout=.05)
                except queue.Empty:continue
                with self.reader_lock:
                    if epoch!=self.epoch:return
                    self.last_reply=time.monotonic();self.last=value
                    self.ack=max(self.ack,value.get('ack',0))
                    self.replay={s:b for s,b in self.replay.items()if s>self.ack}
                    self.sent.intersection_update(self.replay)
            except (EOFError,OSError,ValueError):return
    def seed(self):
        with self.reader_lock:
            value=self.seed_value;self.seed_value=None
            if value is not None:self.seed_consumed=True
            return value
    def worker_problem(self,now,timeout):
        if self.process.pid is not None and not self.process.is_alive():return 'EVIDENCE_PROCESS_EXITED'
        if now-self.last_reply>timeout:return 'EVIDENCE_PROCESS_UNRESPONSIVE'
    def flush_pending(self):
        # Celé IPC předání běží v pomocném vlákně, včetně feeder serializace.
        with self.reader_lock:
            for seq,batch in self.replay.items():
                if seq in self.sent:continue
                try:self.inbox.put_nowait(batch)
                except queue.Full:break
                self.sent.add(seq)
    def restart_worker(self):
        from .process_supervision import retire,reader_budget,retire_reader
        reader_budget(self)
        old=self.process;channels=(self.inbox,self.output,self.bootstrap)
        # Nová generace nemůže sdílet poškozený multiprocessing pipe/semafor.
        with self.reader_lock:self.epoch+=1
        retire(old,channels)
        retire_reader(self,channels)
        if self.guard.stop.is_set():return
        inbox=self.ctx.Queue(self.capacity);output=self.ctx.Queue(2);bootstrap=self.ctx.Queue(1);stop=self.ctx.Event()
        with self.reader_lock:
            self.inbox=inbox;self.output=output;self.bootstrap=bootstrap;self.stop=stop
            self.sent.clear();self.last_reply=time.monotonic()
            self.last={**self.last,'storage_health':{'status':'starting','error_code':'EVIDENCE_PROCESS_RECOVERING'}}
        self.process=self.new_process();self.process.start();self.start_reader()
    def snapshot(self):
        with self.reader_lock:
            last=self.last;self.ack=max(self.ack,last.get('ack',0))
            self.replay={s:b for s,b in self.replay.items()if s>self.ack}
            self.inflight={seq:at for seq,at in self.inflight.items()if seq>self.ack}
            oldest=min(self.inflight.values(),default=None)
        status=dict(last.get('storage_health',{'status':'starting'}))
        problem=self.worker_problem(time.monotonic(),self.guard.timeout)
        if problem:status={'status':'degraded','error_code':problem}
        if oldest and (instant(utcnow())-instant(oldest)).total_seconds()>15:
            status={**status,'status':'degraded','error_code':status.get('error_code')or 'EVIDENCE_LAG'}
        if self.loss['batches']:status={**status,'status':'degraded','integrity':'volatile_evidence_loss'}
        supervision=self.guard.snapshot()
        if supervision['supervision_error']or supervision['restart_budget_exhausted']:
            status={**status,'status':'degraded','error_code':'EVIDENCE_SUPERVISION_FAILED'}
        return {**status,'runtime':self.runtime,'submitted_seq':self.seq,'committed_seq':self.ack,
                'pending_or_lost_batches':self.seq-self.ack,'capacity_batches':self.capacity,
                'max_batch_bytes':MAX_BATCH_BYTES,'loss':copy.deepcopy(self.loss),'supervision':supervision,
                'ack_generation':last.get('ack_generation'),'analysis':last.get('analysis',{}),
                'transport':last.get('transport',{}),'analytics_health':last.get('analytics_health',{})}
    def submit(self,rows,states,result,failure_generation=None):
        self.seq+=1;at=result['at']
        batch={'runtime':self.runtime,'seq':self.seq,'at':at,'rows':rows,'states':states,
               'result':result,'loss':copy.deepcopy(self.loss),'failure_generation':failure_generation}
        accepted=False
        if len(pickle.dumps(batch,protocol=pickle.HIGHEST_PROTOCOL))<=MAX_BATCH_BYTES:
            with self.reader_lock:
                if len(self.replay)<self.capacity:
                    self.replay[self.seq]=batch;accepted=True
                    self.last_accepted=self.seq;self.inflight[self.seq]=at
        if not accepted:
            self.loss['batches']+=1
            day=instant(at).astimezone(TZ).date().isoformat()
            self.loss['days'][day]=self.loss['days'].get(day,0)+1
            self.loss['events']+=sum(len(v)for k,v in rows.items()if k.endswith('events'))
            self.loss['samples']+=sum(len(v)for k,v in rows.items()if k.endswith('samples'))
            self.loss['first_at']=self.loss['first_at']or at;self.loss['last_at']=at
        return accepted
    def close(self,timeout=12):
        self.guard.closing=True
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline and self.process.is_alive():
            if self.snapshot()['committed_seq']>=self.last_accepted:break
            time.sleep(.05)
        self.guard.close();self.stop.set();self.process.join(timeout=12)
        alive=self.process.is_alive()
        if alive:self.process.terminate();self.process.join(timeout=2)
        self.reader_stop.set()
        if self.reader:self.reader.join(timeout=.2)
        for q in (self.inbox,self.output,self.bootstrap):q.cancel_join_thread();q.close()
        return not alive

class MonitorBridge:
    def __init__(self,cfg):
        from .process_supervision import WorkerGuard
        self.ctx=mp.get_context('spawn');self.cfg=cfg
        self.inbox=self.ctx.Queue(1);self.output=self.ctx.Queue(1);self.stop=self.ctx.Event();self.last={}
        self.process=self.new_process()
        self.condition=threading.Condition();self.pending=None;self.latest_result=None
        self.stopping=False;self.sender=None;self.reader=None
        self.epoch=0;self.last_reply=time.monotonic();self.last_progress=self.last_reply;self.published=0;self.attempts=0
        self.retired_readers=[];self.retired_feeders=[];self.guard=WorkerGuard(self)
    def new_process(self):
        return self.ctx.Process(target=monitor_worker,args=(self.cfg,self.inbox,self.output,self.stop),daemon=True)
    def start_reader(self):
        self.reader=threading.Thread(target=self.read_responses,args=(self.output,self.epoch),name='monitor-ipc-reader',daemon=True)
        self.reader.start()
    def start(self):
        self.process.start();self.last_reply=time.monotonic();self.last_progress=self.last_reply
        self.sender=threading.Thread(target=self.send_pending,name='monitor-ipc-sender',daemon=True)
        self.sender.start();self.start_reader();self.guard.start();return self
    def submit(self,result):
        with self.condition:
            self.latest_result=result;self.pending=result;self.condition.notify_all()
        return True
    def send_pending(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.stopping or self.pending is not None)
                if self.stopping:return
                value=self.pending;self.pending=None
            while not self.stopping:
                with self.condition:channel=self.inbox
                try:channel.put(value,timeout=.1);break
                except queue.Full:
                    with self.condition:
                        if self.pending is not None:value=self.pending;self.pending=None
                except (OSError,ValueError):continue
    def read_responses(self,output,epoch):
        while not self.stopping and epoch==self.epoch:
            try:value=output.get(timeout=.1)
            except queue.Empty:continue
            except (EOFError,OSError,ValueError):return
            with self.condition:
                if epoch!=self.epoch:return
                self.last_reply=time.monotonic();count=value.get('published_packets',0)
                attempts=value.get('completed_attempts',0)
                if count!=self.published or attempts!=self.attempts or not value.get('pending_entities'):
                    self.last_progress=self.last_reply;self.published=count;self.attempts=attempts
                self.last=value
    def worker_problem(self,now,timeout):
        if self.process.pid is not None and not self.process.is_alive():return 'MONITOR_PROCESS_EXITED'
        if now-self.last_reply>timeout:return 'MONITOR_PROCESS_UNRESPONSIVE'
        with self.condition:
            if self.last.get('pending_entities') and now-self.last_progress>timeout:return 'MONITOR_PUBLICATION_STALLED'
    def flush_pending(self):pass
    def restart_worker(self):
        from .process_supervision import retire,reader_budget,retire_reader
        reader_budget(self)
        with self.condition:self.epoch+=1
        retire(self.process,(self.inbox,self.output))
        retire_reader(self,(self.inbox,self.output))
        if self.guard.stop.is_set():return
        inbox=self.ctx.Queue(1);output=self.ctx.Queue(1);stop=self.ctx.Event()
        with self.condition:
            self.inbox=inbox;self.output=output;self.stop=stop
            self.last={'status':'starting','error_code':'MONITOR_PROCESS_RECOVERING'}
            self.last_reply=time.monotonic();self.last_progress=self.last_reply;self.published=0;self.attempts=0
            self.pending=self.latest_result;self.condition.notify_all()
        self.process=self.new_process();self.process.start();self.start_reader()
    def snapshot(self):
        with self.condition:last=dict(self.last)
        problem=self.worker_problem(time.monotonic(),self.guard.timeout)
        if problem:last={**last,'status':'degraded','error_code':problem}
        supervision=self.guard.snapshot()
        if supervision['supervision_error']or supervision['restart_budget_exhausted']:
            last={**last,'status':'degraded','error_code':'MONITOR_SUPERVISION_FAILED'}
        return {**last,'supervision':supervision}
    def close(self):
        self.guard.close()
        with self.condition:self.stopping=True;self.condition.notify_all()
        self.stop.set();self.process.join(timeout=8)
        alive=self.process.is_alive()
        if alive:self.process.terminate();self.process.join(timeout=2)
        for t in (self.sender,self.reader):
            if t:t.join(timeout=.2)
        for q in (self.inbox,self.output):q.cancel_join_thread();q.close()
        return not alive

def run_loop(client,evidence,monitor,stop,clock=utcnow,monotonic=time.monotonic):
    """Produkční smyčka: cache → stav v RAM → neblokující předání výsledků."""
    memory=None;last_success=None;pending_at=None;pending_generation=None
    try:
        while not stop.is_set():
            started=monotonic();at=clock();journal=None
            health=evidence.snapshot();analysis=health.pop('analysis',{})
            if analysis.get('at') and instant(analysis['at'])>instant(at):analysis={}
            if health.get('ack_generation') is not None:
                client.request_acknowledge_failure(health['ack_generation'])
            if memory is None:
                seed=evidence.seed()
                if seed is None:
                    monitor.submit({'at':at,'version':VERSION,'mode':'observe_only','device_actions':0,
                        'selected':{'reason':'waiting_control_bootstrap','battery_ac_w':None,'ev_ac_w':None,'grid_model_w':None},
                        'collection_health':{'status':'degraded','checked_at':at},'evidence_pipeline':health})
                    stop.wait(.25);continue
                memory=MemoryControl(seed)
            memory.annotate_loss(evidence.loss)
            states=[]
            try:
                states=client.priority_states()
                # Snímek a rozhodnutí mají čas až po dokončení neblokujícího čtení cache.
                at=clock();current,journal=memory.step(states,analysis,at)
                result={**analysis,**current,'version':VERSION,'mode':'observe_only','device_actions':0,
                    'active':180<=instant(at).astimezone(TZ).hour*60+instant(at).astimezone(TZ).minute<300,'control_journal':journal,
                    'analysis_at':analysis.get('at'),'collection_health':{'status':'ok','checked_at':at,
                    'last_successful_collection_at':at,'summary_errors':[]}}
                last_success=at
            except Exception as error:
                from .priority_observer import failure_result
                result=failure_result(at,error,last_success)
                pending=client.snapshot().get('pending_failure')
                failure_at=getattr(error,'failure_at',at)
                pending_at=min(filter(None,[pending_at,failure_at,(pending or {}).get('control_first_at',(pending or {}).get('first_at'))]),key=instant)
                pending_generation=(pending or {}).get('generation')
                journal=memory.failure(pending_at,error)
                consume=getattr(client,'consume_failure',None)
                if consume and pending_generation is not None:consume(pending_generation)
                pending_at=None
                result['control_journal']=journal;result['at']=at
                if pending:result['collection_health']['pending_collection_failure']=pending
            journal['transport']=health.get('transport',{})
            result['evidence_pipeline']=health
            if health.get('status')=='degraded' and result['collection_health']['status']=='ok':
                result['collection_health']['status']='degraded'
                if health.get('stage')!='analytics_or_live_snapshot':
                    result['collection_health']['journal_transport_error']=health.get('error_code')or 'EVIDENCE_STORAGE_DEGRADED'
            auxiliary=health.get('analytics_health',{})
            if auxiliary.get('status') in ('degraded','retrying'):
                result['collection_health']['analytics_error']=auxiliary
                if result['collection_health']['status']=='ok':result['collection_health']['status']='degraded'
            maintenance=analysis.get('maintenance',{})
            if maintenance.get('maintenance_error')or maintenance.get('summary_errors'):
                result['collection_health']['summary_errors']=maintenance.get('summary_errors',[])
                if result['collection_health']['status']=='ok':result['collection_health']['status']='degraded'
            result['monitor_publication']=monitor.snapshot()
            if result['monitor_publication'].get('status')=='degraded':
                result['collection_health']['monitor_publication_error']=result['monitor_publication'].get('error_code')
                if result['collection_health']['status']=='ok':result['collection_health']['status']='degraded'
            result['fast_loop']={'target_interval_s':5 if night.window(at)else 60,
                'last_work_duration_s':monotonic()-started,'physical_control_ready':False,
                'control_state_backend':'private_memory','disk_io_in_control_thread':False,
                'analytics_in_control_process':False,'monitoring_http_in_control_thread':False,
                'collection_http_in_control_thread':False,'collection_worker':client.snapshot()}
            rows=memory.delta()
            accepted=evidence.submit(rows,states,result,pending_generation)
            if accepted:pending_at=None
            else:memory.retry_sessions()
            result_for_monitor=copy.copy(result)
            result_for_monitor['evidence_pipeline']={**health,**({'status':'degraded','loss':dict(evidence.loss)}if not accepted else {})}
            monitor.submit(result_for_monitor)
            # Čekání se odvozuje od skutečného journalu, nikoli úspěchu ukládání.
            from .priority_observer import next_wait
            stop.wait(next_wait(clock(),monotonic()-started,journal))
    finally:
        if memory:memory.close()
