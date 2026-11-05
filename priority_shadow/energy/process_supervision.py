"""Bounded rolling recovery outside the control thread; cumulative history retained."""
import threading,time

class WorkerGuard:
    def __init__(self,owner,timeout=30.,limit=3,window=300.,clock=time.monotonic):
        self.owner=owner;self.timeout=timeout;self.limit=limit;self.window=window;self.clock=clock
        self.stop=threading.Event();self.closing=False;self.thread=None
        self.restarts=0;self.reason=None;self.error=None;self.exhausted=False
        self.attempts=[];self.cooldown_until=None;self.problem=None
    def start(self):
        self.thread=threading.Thread(target=self.run,name='auxiliary-supervisor',daemon=True)
        self.thread.start();return self
    def tick(self):
        if self.stop.is_set():return
        self.owner.flush_pending()
        if self.closing or self.stop.is_set():return
        now=self.clock();self.attempts=[t for t in self.attempts if now-t<self.window]
        problem=self.owner.worker_problem(now,self.timeout);self.problem=problem
        if not problem:
            self.exhausted=False;self.error=None;self.cooldown_until=None
            return
        self.reason=problem
        if len(self.attempts)>=self.limit:
            self.exhausted=True;self.cooldown_until=self.attempts[0]+self.window;return
        self.exhausted=False;self.cooldown_until=None
        self.attempts.append(now);self.restarts+=1
        try:self.owner.restart_worker();self.error=None;self.problem=None
        except Exception as error:self.error=type(error).__name__+': '+str(error)[:128]
    def run(self):
        while not self.stop.wait(.05):
            try:self.tick()
            except Exception as error:self.error=type(error).__name__
    def snapshot(self):
        return {'restart_count':self.restarts,'restart_limit':self.limit,
                'restart_window_s':self.window,'attempts_in_window':len(self.attempts),
                'cooldown_remaining_s':max(0.,(self.cooldown_until or self.clock())-self.clock()),
                'current_worker_problem':self.problem,'last_restart_reason':self.reason,'supervision_error':self.error,
                'restart_budget_exhausted':self.exhausted,
                'retired_reader_count':len(getattr(self.owner,'retired_readers',())),
                'retired_feeder_count':len(getattr(self.owner,'retired_feeders',()))}
    def close(self):
        self.closing=True;self.stop.set()
        if self.thread:self.thread.join(timeout=5)
        return not self.thread or not self.thread.is_alive()

def reader_budget(owner):
    owner.retired_feeders=[t for t in getattr(owner,'retired_feeders',())if t.is_alive()]
    if len(owner.retired_feeders)>=3:raise RuntimeError('AUXILIARY_RETIRED_FEEDER_LIMIT')
    owner.retired_readers=[t for t in owner.retired_readers if t.is_alive()]
    if len(owner.retired_readers)>=3:raise RuntimeError('AUXILIARY_RETIRED_READER_LIMIT')

def retire_reader(owner,channels=()):
    for channel in channels:
        feeder=getattr(channel,'_thread',None)
        if feeder:
            feeder.join(timeout=.05)
            if feeder.is_alive():owner.retired_feeders.append(feeder)
    reader=owner.reader
    if reader:
        reader.join(timeout=.2)
        if reader.is_alive():owner.retired_readers.append(reader)

def retire(process,channels):
    """Only supervision/shutdown may wait; no late spawn after shutdown."""
    if process.pid is not None:
        if process.is_alive():process.terminate()
        process.join(timeout=2)
        if process.is_alive():raise RuntimeError('AUXILIARY_PROCESS_WOULD_NOT_EXIT')
    for channel in channels:
        channel.cancel_join_thread();channel.close()
