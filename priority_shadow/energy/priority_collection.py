"""Síťový sběr mimo řídicí smyčku. Cache nikdy nemění původní HA reporty."""
import copy,threading,time

class SnapshotCollector:
 def __init__(self,client,period=5,max_age=7.5):
  self.client=client;self.period=period;self.max_age=max_age;self.condition=threading.Condition();self.stop=threading.Event();self.states=None;self.received=None;self.error=None;self.duration=None;self.thread=None
 def run(self):
  while not self.stop.is_set():
   start=time.monotonic()
   try:
    states=self.client.priority_states()
    with self.condition:self.states=states;self.received=time.monotonic();self.error=None;self.duration=self.received-start;self.condition.notify_all()
   except Exception as e:
    with self.condition:self.states=None;self.error=type(e).__name__;self.duration=time.monotonic()-start;self.condition.notify_all()
   self.stop.wait(max(.1,self.period-(time.monotonic()-start)))
 def start(self):
  self.thread=threading.Thread(target=self.run,name='priority-inputs',daemon=True);self.thread.start();return self
 def priority_states(self):
  with self.condition:
   if self.received is None and self.error is None:self.condition.wait_for(lambda:self.received is not None or self.error is not None,timeout=1)
   if self.error:raise RuntimeError('COLLECTION_WORKER_FAILED:'+self.error)
   if self.received is None or time.monotonic()-self.received>self.max_age:raise RuntimeError('COLLECTION_SNAPSHOT_EXPIRED')
   return copy.deepcopy(self.states)
 def snapshot(self):
  with self.condition:return {'snapshot_age_s':time.monotonic()-self.received if self.received is not None else None,'request_duration_s':self.duration,'error_code':self.error,'max_snapshot_age_s':self.max_age,'poll_interval_s':self.period}
 def close(self):
  self.stop.set()
  if self.thread:self.thread.join(timeout=1)
