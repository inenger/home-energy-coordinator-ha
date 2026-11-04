"""Dohled mimo řídicí vlákno; omezené obnovení pomocného procesu."""
import threading,time

class WorkerGuard:
    def __init__(self,owner,timeout=30.,limit=3):
        self.owner=owner;self.timeout=timeout;self.limit=limit
        self.stop=threading.Event();self.closing=False;self.thread=None
        self.restarts=0;self.reason=None;self.error=None;self.exhausted=False
    def start(self):
        self.thread=threading.Thread(target=self.run,name='auxiliary-supervisor',daemon=True)
        self.thread.start();return self
    def tick(self):
        self.owner.flush_pending()
        if self.closing:return
        problem=self.owner.worker_problem(time.monotonic(),self.timeout)
        if not problem:return
        self.reason=problem
        if self.restarts>=self.limit:self.exhausted=True;return
        self.restarts+=1
        try:self.owner.restart_worker();self.error=None
        except Exception as error:self.error=type(error).__name__
    def run(self):
        while not self.stop.wait(.05):
            try:self.tick()
            except Exception as error:self.error=type(error).__name__
    def snapshot(self):
        return {'restart_count':self.restarts,'restart_limit':self.limit,
                'last_restart_reason':self.reason,'supervision_error':self.error,
                'restart_budget_exhausted':self.exhausted}
    def close(self):
        self.closing=True;self.stop.set()
        if self.thread:self.thread.join(timeout=5)

def retire(process,channels):
    """Volá pouze pomocné vlákno nebo shutdown, nikdy řídicí krok."""
    if process.pid is not None:
        if process.is_alive():process.terminate()
        process.join(timeout=2)
        if process.is_alive():raise RuntimeError('AUXILIARY_PROCESS_WOULD_NOT_EXIT')
    for channel in channels:
        channel.cancel_join_thread();channel.close()
