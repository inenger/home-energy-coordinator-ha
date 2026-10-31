"""Pomalé přepočty mimo rychlou smyčku. Vlastní SQLite spojení a HTTP klient."""
import copy,threading,time
from .store import Store
from . import night,priority,priority_audit,soc_runtime
from .collector import ReadOnlyHA

class Maintenance:
    def __init__(self,path,options,backup,period_s=60,work=None):
        self.path=path;self.options=options;self.backup=backup;self.period=period_s;self.work=work
        self.lock=threading.Lock();self.wake=threading.Event();self.stop=threading.Event()
        self.pending=None;self.output={};self.next_backup=0;self.next_audit=0;self.audit_error=None
        self.thread=threading.Thread(target=self.run,name='priority-maintenance',daemon=True)
        self.thread.start()
    def submit(self,states,at):
        with self.lock:self.pending=(copy.deepcopy(states),at)
        self.wake.set()
    def snapshot(self):
        with self.lock:return copy.deepcopy(self.output)
    def compute(self,states,at):
        planner=getattr(self,'planner',None)
        if planner is None:self.planner=soc_runtime.PlannerService(self.options);self.client=ReadOnlyHA();planner=self.planner
        store=Store(self.path)
        try:
            night.ensure_schema(store.db);priority.schema(store.db)
            errors=[]
            for day in priority.closed_days(store,at):
                try:priority.finish(store,day)
                except Exception as error:errors.append({'day':day,'error_code':type(error).__name__})
            optimizer=planner.observe(store,states,at,self.client)
            if time.monotonic()>=self.next_audit:
                try:priority_audit.update_day_audit(store,self.client,at);self.audit_error=None
                except Exception as error:self.audit_error=type(error).__name__
                self.next_audit=time.monotonic()+600
            audit=priority_audit.day_summary(store,at,self.audit_error)
            try:optimizer['review_history']=soc_runtime.review(store,audit,at)
            except Exception as error:optimizer['review_error_code']=type(error).__name__
            return {'at':at,'soc_optimizer':optimizer,'fve_soc_audit':audit,'summary_errors':errors}
        finally:store.close()
    def run(self):
        next_run=0
        while not self.stop.is_set():
            self.wake.wait(.5);self.wake.clear()
            if self.stop.is_set():break
            if time.monotonic()<next_run:continue
            with self.lock:pending=self.pending
            if not pending:continue
            states,at=pending
            try:
                out=self.work(states,at) if self.work else self.compute(states,at)
                with self.lock:self.output=out
            except Exception as error:
                with self.lock:self.output={**self.output,'maintenance_error':type(error).__name__,'maintenance_error_at':at}
            next_run=time.monotonic()+self.period
            if not self.work and time.monotonic()>=self.next_backup:
                try:self.backup();self.next_backup=time.monotonic()+3600
                except Exception:self.next_backup=time.monotonic()+600
    def close(self):
        self.stop.set();self.wake.set();self.thread.join(timeout=25)
        return not self.thread.is_alive()
