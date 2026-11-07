"""Durable FIFO analytics, isolated from control and evidence acknowledgements.

Retries retain the original observation time and inputs; they are never replaced
with current data. Completed immutable evidence is not rewritten.
"""
import copy,threading,time
from .store import Store,unpack
from .sqlite_writes import details,WriterTimeout,schema_ready

def schema(db):
    if schema_ready(db,('control_analytics_pending',)):return
    db.execute('''CREATE TABLE IF NOT EXISTS control_analytics_pending(
        id INTEGER PRIMARY KEY,runtime TEXT NOT NULL,seq INTEGER NOT NULL,
        at TEXT NOT NULL,payload BLOB NOT NULL,UNIQUE(runtime,seq))''')

def retryable(error):
    import sqlite3
    return isinstance(error,WriterTimeout) or (isinstance(error,sqlite3.OperationalError)
        and getattr(error,'sqlite_errorcode',0)&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED))

class Analytics:
    def __init__(self,path,maintenance,work=None):
        self.path=path;self.maintenance=maintenance;self.work=work
        self.stop=threading.Event();self.wake=threading.Event();self.lock=threading.Lock()
        self.output={'analysis':{},'health':{'status':'starting'}};self.thread=None
        self.failures=0;self.retries=0;self.last_failure=None
    def start(self):
        self.thread=threading.Thread(target=self.run,name='durable-analytics',daemon=True)
        self.thread.start();return self
    def snapshot(self):
        with self.lock:return copy.deepcopy(self.output)
    def compute(self,store,item):
        from . import night,priority,priority_observer as observer,priority_audit
        from .collector import atomic_json
        night.ensure_schema(store.db);priority.schema(store.db)
        states=item['states'];at=item['at']
        observer.archive_forecasts(store,states,at)
        analysis=observer.observe_priority(store,states,at,finish_closed=False)
        slow=self.maintenance.snapshot()
        analysis.update(soc_optimizer=slow.get('soc_optimizer',{}),
            fve_soc_audit=slow.get('fve_soc_audit',{}),
            maintenance={k:v for k,v in slow.items()if k not in ('soc_optimizer','fve_soc_audit')})
        priority_audit.journal(store,analysis)
        analysis['command_audit']=priority_audit.command_summary(store,at)
        atomic_json(self.path.parent/'priority-live.json',item['result'])
        return analysis
    def tick(self):
        """One original FIFO item; short writer waits yield to committed evidence."""
        store=None;item=None
        try:
            store=Store(self.path,timeout=.25);schema(store.db)
            row=store.db.execute('SELECT id,payload FROM control_analytics_pending ORDER BY id LIMIT 1').fetchone()
            count=store.db.execute('SELECT count(*) FROM control_analytics_pending').fetchone()[0]
            if not row:
                with self.lock:self.output['health']={**self.output['health'],'status':'ok','pending_items':0}
                return False
            # A nonempty job writes: yield before computation if a writer is already busy.
            with store.db:pass
            key,payload=row;item=unpack(payload)
            analysis=self.work(store,item)if self.work else self.compute(store,item)
            with store.db:store.db.execute('DELETE FROM control_analytics_pending WHERE id=?',(key,))
            remaining=store.db.execute('SELECT count(*) FROM control_analytics_pending').fetchone()[0]
            # Never finish a day while earlier observations are still queued.
            if not remaining:self.maintenance.submit(item['states'],item['at'])
            self.failures=0
            with self.lock:self.output={'analysis':analysis,'health':{'status':'ok','pending_items':remaining,
                'last_processed_at':item['at'],'retry_count':self.retries,'last_failure':self.last_failure}}
            return True
        except Exception as error:
            self.failures+=1;self.retries+=1
            self.last_failure={'error_code':type(error).__name__,'storage_error':details(error),
                'observation_at':item['at']if item else None,'retryable':retryable(error)}
            with self.lock:self.output['health']={'status':'retrying'if retryable(error)else'degraded',
                'stage':'analytics_or_live_snapshot','pending_items':None,'retry_count':self.retries,
                'last_failure':self.last_failure,'retry_delay_s':min(5.,.25*2**min(self.failures,5))}
            return False
        finally:
            if store:store.close()
    def run(self):
        while not self.stop.is_set():
            if self.tick():continue
            # A new evidence batch cannot bypass backoff during a persistent fault.
            if self.failures:self.stop.wait(min(5.,.25*2**min(self.failures,5)))
            else:self.wake.wait(.25);self.wake.clear()
    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join(timeout=2)
        return not self.thread or not self.thread.is_alive()
