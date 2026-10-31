"""Oddělený monitoring: nejvýše jedna čekající zpráva na monitorovací entitu.

SQLite deník má vlastní trvalý transport. Tato fronta drží poslední stav
monitorů; starší čekající stav nahrazuje novější bez blokování rychlého sběru.
"""
from collections import OrderedDict
from datetime import datetime,timezone
import threading,time
import urllib.request
from . import publish_status
from .collector import NoRedirect,read_token

class MonitorPublisher:
    def __init__(self,cfg,send=None):
        self.cfg=cfg;self.send=send;self.condition=threading.Condition()
        self.pending=OrderedDict();self.stopping=False;self.thread=None
        self.health={'status':'starting','pending_entities':0,'published_packets':0}
        self.failed=False;self.errors={}

    def submit(self,result,failure=False):
        # Příprava je čistá a kontroluje byte budget ještě v cestě fail-closed.
        packets=publish_status.prepare_priority(result,failure)
        with self.condition:
            urgent=failure and not self.failed;self.failed=failure
            for eid,payload in packets:self.pending[eid]=payload
            if urgent:
                order=[eid for eid,_ in packets]
                self.pending=OrderedDict([(eid,self.pending[eid])for eid in order]+[(e,p)for e,p in self.pending.items()if e not in order])
            self.health['pending_entities']=len(self.pending);self.condition.notify()
        return self.snapshot()

    def snapshot(self):
        with self.condition:return dict(self.health)

    def publish(self,eid,payload):
        if self.send is not None:return self.send(eid,payload)
        if not hasattr(self,'opener'):
            self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=publish_status.request(eid,payload,self.cfg['ha_base_url'],read_token())
        with self.opener.open(request,timeout=5)as response:
            if response.status not in (200,201):raise RuntimeError('Priority monitoring publication failed')

    def tick(self):
        with self.condition:
            if not self.pending or self.stopping:return False
            eid,payload=self.pending.popitem(last=False)
            self.health['pending_entities']=len(self.pending)
        started=time.monotonic();at=datetime.now(timezone.utc).isoformat()
        try:
            self.publish(eid,payload)
            with self.condition:
                self.errors.pop(eid,None)
                self.health.update(status='degraded' if self.errors else 'ok',error_code=next(iter(self.errors.values()),None),failed_entities=dict(self.errors),last_published_at=at,
                    last_publish_duration_s=time.monotonic()-started,
                    published_packets=self.health['published_packets']+1)
        except Exception as error:
            with self.condition:
                # Novější čekající zpráva má přednost i při opakování chyby.
                if eid not in self.pending:self.pending[eid]=payload
                self.errors[eid]=type(error).__name__
                self.health.update(status='degraded',error_code=type(error).__name__,failed_entities=dict(self.errors),
                    last_failure_at=at,last_publish_duration_s=time.monotonic()-started)
            return False
        finally:
            with self.condition:self.health['pending_entities']=len(self.pending)
        return True

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.stopping or bool(self.pending))
                if self.stopping:return
            if not self.tick():
                with self.condition:self.condition.wait_for(lambda:self.stopping,timeout=1)

    def start(self):
        self.thread=threading.Thread(target=self.run,name='priority-monitoring',daemon=True)
        self.thread.start();return self

    def close(self):
        with self.condition:self.stopping=True;self.condition.notify_all()
        if self.thread:self.thread.join(timeout=7)
        return not self.thread or not self.thread.is_alive()
