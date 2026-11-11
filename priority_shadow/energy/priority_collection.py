"""Síťový sběr mimo smyčku; nepřevzatá chyba přežije úspěch i restart."""
import copy,json,threading,time
from datetime import datetime,timezone
from pathlib import Path
from .collector import atomic_json
from . import night

class CollectionFailure(RuntimeError):
    def __init__(self, failure):
        self.generation=failure['generation']
        self.failure_at=failure.get('control_first_at',failure['first_at'])
        super().__init__('COLLECTION_WORKER_FAILED:'+failure['error_code'])

class SnapshotCollector:
    def __init__(self,client,period=5,max_age=7.5,failure_path=None,night_period=None,defer_failure_persistence=False):
        self.client=client;self.period=period;self.max_age=max_age;self.night_period=night_period
        self.sequence=0;self.receipt=None
        self.persistence_lock=threading.Lock();self.ack_wake=threading.Event();self.ack_requested=None;self.ack_thread=None
        self.condition=threading.Condition();self.stop=threading.Event()
        self.states=None;self.received=None;self.error=None;self.duration=None;self.thread=None
        self.request_started=None;self.thread_failed=False;self.watcher=None
        self.restart_attempts=[];self.restart_count=0;self.restart_limit=3;self.restart_window=300.
        self.thread_problem=None
        self.failure_path=Path(failure_path) if failure_path else None
        self.pending_failure=None;self.generation=0;self.persistence_error=None
        self.consumed_generation=0
        self.defer_failure_persistence=defer_failure_persistence;self.failure_dirty=False
        if self.failure_path and self.failure_path.exists():
            saved=json.loads(self.failure_path.read_text())
            self.generation=saved['generation']
            self.pending_failure=saved.get('pending')
            if not isinstance(self.generation,int) or self.generation<0:raise ValueError('Invalid collection failure generation')
            if self.pending_failure:
                datetime.fromisoformat(self.pending_failure['first_at'])
                if self.pending_failure['generation']!=self.generation:raise ValueError('Invalid pending collection generation')

    def persist(self,pending,generation=None):
        if self.failure_path:
            atomic_json(self.failure_path,{'generation':self.generation if generation is None else generation,'pending':pending})

    def failed(self,error):
        # Krátký zámek chrání cache. Diskové fsync nikdy neběží pod ním.
        with self.condition:
            previous=self.pending_failure or {}
            control_first=previous.get('control_first_at',previous.get('first_at')) if previous.get('generation',0)>self.consumed_generation else None
            self.generation+=1
            generation=self.generation
            self.pending_failure={'generation':generation,
                'first_at':(self.pending_failure or {}).get('first_at') or datetime.now(timezone.utc).isoformat(),
                'error_code':type(error).__name__,
                'control_first_at':control_first or datetime.now(timezone.utc).isoformat()}
            self.states=None;self.error=type(error).__name__
            self.condition.notify_all()
        if self.defer_failure_persistence:
            with self.condition:self.failure_dirty=True
            self.ack_wake.set()
            return
        self.persist_failure()

    def persist_failure(self):
        """Jen pomocné vlákno smí v produkci čekat na disk."""
        with self.persistence_lock:
            with self.condition:pending=copy.deepcopy(self.pending_failure);generation=self.generation
            try:
                self.persist(pending,generation=generation)
                problem=None
            except Exception as error:problem=type(error).__name__
            with self.condition:
                if self.generation==generation:self.persistence_error=problem

    def consume_failure(self,generation):
        """Stop už byl proveden v RAM; trvalé potvrzení evidence je nezávislé.

        Jen přesná generace smí uvolnit novou cache. Po restartu začíná
        consumed_generation od nuly: neuložená chyba se znovu bezpečně převezme.
        """
        with self.condition:
            if not self.pending_failure or self.pending_failure['generation']!=generation:return False
            self.consumed_generation=generation
            return True

    def acknowledge_failure(self,generation):
        """Až po trvalém stopu/outboxu. Persistence neblokuje přístup ke cache."""
        with self.persistence_lock:
            with self.condition:
                if not self.pending_failure or self.pending_failure['generation']!=generation:return False
            self.persist(None,generation=generation)
            with self.condition:
                if not self.pending_failure or self.pending_failure['generation']!=generation:return False
                self.pending_failure=None;self.persistence_error=None
                return True

    def request_acknowledge_failure(self,generation):
        """Řídicí proces jen předá generaci; nesahá na disk a nečeká na fsync."""
        with self.condition:
            if not self.pending_failure or self.pending_failure['generation']!=generation:return
            self.ack_requested=generation
        self.ack_wake.set()

    def run_acknowledgements(self):
        while not self.stop.is_set():
            self.ack_wake.wait(.25);self.ack_wake.clear()
            with self.condition:
                generation=self.ack_requested;self.ack_requested=None
                dirty=self.failure_dirty;self.failure_dirty=False
            if dirty:self.persist_failure()
            if generation is None:continue
            try:self.acknowledge_failure(generation)
            except Exception as error:
                with self.condition:self.persistence_error=type(error).__name__

    def effective_period(self,at=None):
        return self.night_period if self.night_period is not None and night.window(at or datetime.now(timezone.utc).isoformat()) else self.period

    def run(self):
        while not self.stop.is_set():
            start=time.monotonic();started_at=datetime.now(timezone.utc).isoformat();period=self.effective_period(started_at)
            with self.condition:self.request_started=start
            try:
                states=self.client.priority_states()
                with self.condition:
                    self.states=states;self.received=time.monotonic();self.error=None
                    self.duration=self.received-start;self.sequence+=1
                    self.receipt={'sequence':self.sequence,'request_started_at':started_at,
                        'received_at':datetime.now(timezone.utc).isoformat(),'request_duration_s':self.duration,
                        'poll_interval_s':period}
                    self.condition.notify_all()
            except Exception as error:
                self.failed(error)
                with self.condition:self.duration=time.monotonic()-start
            with self.condition:self.request_started=None
            self.stop.wait(max(.1,period-(time.monotonic()-start)))

    def watch(self):
        while not self.stop.wait(.25):
            now=time.monotonic()
            with self.condition:
                dead=self.thread is not None and not self.thread.is_alive()
                blocked=(self.request_started is not None and now-self.request_started>max(2*self.max_age,15.))
                if blocked:
                    self.thread_problem='COLLECTION_THREAD_STALLED'
                elif dead:
                    self.thread_problem='COLLECTION_THREAD_EXITED'
                else:
                    self.thread_problem=None
                    self.thread_failed=False
                problem=self.thread_problem
                first=problem is not None and not self.thread_failed
                if first:self.thread_failed=True
            if first:self.failed(RuntimeError(problem))
            if dead and not self.stop.is_set():
                self.restart_attempts=[t for t in self.restart_attempts if now-t<self.restart_window]
                if len(self.restart_attempts)<self.restart_limit:
                    self.restart_attempts.append(now);self.restart_count+=1
                    with self.condition:
                        self.thread_failed=False
                        self.request_started=None
                    self.thread=threading.Thread(target=self.run,name='priority-inputs',daemon=True)
                    self.thread.start()
                # If exhausted, keep the failure latched. Never reanimate stale data.

    def start(self):
        self.ack_thread=threading.Thread(target=self.run_acknowledgements,name='collection-failure-ack',daemon=True)
        self.ack_thread.start()
        self.thread=threading.Thread(target=self.run,name='priority-inputs',daemon=True)
        self.thread.start()
        self.watcher=threading.Thread(target=self.watch,name='priority-inputs-watchdog',daemon=True)
        self.watcher.start();return self

    def priority_states(self):
        with self.condition:
            if self.received is None and self.error is None and self.pending_failure is None:
                self.condition.wait_for(lambda:self.received is not None or self.error is not None or self.pending_failure is not None,timeout=1)
            if self.pending_failure and self.pending_failure['generation']>self.consumed_generation:
                raise CollectionFailure(dict(self.pending_failure))
            if self.thread_problem:raise RuntimeError(self.thread_problem)
            if self.error:raise RuntimeError('COLLECTION_WORKER_FAILED:'+self.error)
            if self.received is None or time.monotonic()-self.received>self.max_age:raise RuntimeError('COLLECTION_SNAPSHOT_EXPIRED')
            states=copy.deepcopy(self.states)
            if states and self.receipt:
                # Atomicky se stejnou sadou; pozdější snapshot() už může patřit
                # jinému requestu. Jde o čas získání HA stavu, nikoli heartbeat.
                states[0]['collection_snapshot']=dict(self.receipt)
            return states

    def snapshot(self):
        with self.condition:
            return {'snapshot_age_s':time.monotonic()-self.received if self.received is not None else None,
                'request_duration_s':self.duration,'error_code':self.error,'max_snapshot_age_s':self.max_age,
                'poll_interval_s':self.effective_period(),'base_poll_interval_s':self.period,'night_poll_interval_s':self.night_period,'pending_failure':copy.deepcopy(self.pending_failure),
                'failure_generation':self.generation,'control_consumed_generation':self.consumed_generation,'failure_persistence_error':self.persistence_error,
                 'thread_alive':bool(self.thread and self.thread.is_alive()),'thread_problem':self.thread_problem,
                 'thread_restart_count':self.restart_count,'thread_restart_limit':self.restart_limit,
                 'thread_restart_budget_exhausted':len(self.restart_attempts)>=self.restart_limit,
                 'request_in_progress_s':time.monotonic()-self.request_started if self.request_started is not None else None}

    def close(self):
        self.stop.set();self.ack_wake.set()
        if self.thread:self.thread.join(timeout=1)
        if self.watcher:self.watcher.join(timeout=1)
        if self.ack_thread:self.ack_thread.join(timeout=1)
