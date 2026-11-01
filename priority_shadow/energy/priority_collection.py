"""Síťový sběr mimo smyčku; nepřevzatá chyba přežije úspěch i restart."""
import copy,json,threading,time
from datetime import datetime,timezone
from pathlib import Path
from .collector import atomic_json
from . import night

class CollectionFailure(RuntimeError):
    def __init__(self, failure):
        self.generation=failure['generation']
        self.failure_at=failure['first_at']
        super().__init__('COLLECTION_WORKER_FAILED:'+failure['error_code'])

class SnapshotCollector:
    def __init__(self,client,period=5,max_age=7.5,failure_path=None,night_period=None):
        self.client=client;self.period=period;self.max_age=max_age;self.night_period=night_period
        self.sequence=0;self.receipt=None
        self.condition=threading.Condition();self.stop=threading.Event()
        self.states=None;self.received=None;self.error=None;self.duration=None;self.thread=None
        self.failure_path=Path(failure_path) if failure_path else None
        self.pending_failure=None;self.generation=0;self.persistence_error=None
        if self.failure_path and self.failure_path.exists():
            saved=json.loads(self.failure_path.read_text())
            self.generation=saved['generation']
            self.pending_failure=saved.get('pending')
            if not isinstance(self.generation,int) or self.generation<0:raise ValueError('Invalid collection failure generation')
            if self.pending_failure:
                datetime.fromisoformat(self.pending_failure['first_at'])
                if self.pending_failure['generation']!=self.generation:raise ValueError('Invalid pending collection generation')

    def persist(self,pending):
        if self.failure_path:
            atomic_json(self.failure_path,{'generation':self.generation,'pending':pending})

    def failed(self,error):
        # Nejstarší nezpracovaný výpadek zůstává zachovaný. Novější generaci
        # nesmí potvrdit konzument, který viděl jen starší generaci.
        with self.condition:
            self.generation+=1
            self.pending_failure={'generation':self.generation,
                'first_at':(self.pending_failure or {}).get('first_at') or datetime.now(timezone.utc).isoformat(),
                'error_code':type(error).__name__}
            self.states=None;self.error=type(error).__name__
            try:self.persist(self.pending_failure);self.persistence_error=None
            except Exception as problem:self.persistence_error=type(problem).__name__
            self.condition.notify_all()

    def acknowledge_failure(self,generation):
        """Až po trvalém stopu a enqueue. Souběžná novější chyba zůstane čekat."""
        with self.condition:
            if not self.pending_failure or self.pending_failure['generation']!=generation:return False
            self.persist(None)
            self.pending_failure=None;self.persistence_error=None
            return True

    def effective_period(self,at=None):
        return self.night_period if self.night_period is not None and night.window(at or datetime.now(timezone.utc).isoformat()) else self.period

    def run(self):
        while not self.stop.is_set():
            start=time.monotonic();started_at=datetime.now(timezone.utc).isoformat();period=self.effective_period(started_at)
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
            self.stop.wait(max(.1,period-(time.monotonic()-start)))

    def start(self):
        self.thread=threading.Thread(target=self.run,name='priority-inputs',daemon=True)
        self.thread.start();return self

    def priority_states(self):
        with self.condition:
            if self.received is None and self.error is None and self.pending_failure is None:
                self.condition.wait_for(lambda:self.received is not None or self.error is not None or self.pending_failure is not None,timeout=1)
            if self.pending_failure:raise CollectionFailure(dict(self.pending_failure))
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
                'failure_generation':self.generation,'failure_persistence_error':self.persistence_error}

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=1)
