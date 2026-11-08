"""Keep WAL lifetime stable and checkpoint away from short writer scopes.

FULL remains enabled. PASSIVE checkpoints never wait for readers or writers.
This removes automatic checkpoint/last-close work from managed worker commits;
it does not promise that physical fsync can never stall.
"""
import sqlite3,threading,time
from pathlib import Path
from .sqlite_writes import gate_for
class Checkpointer:
    def __init__(self,path):
        self.path=Path(path);self.gate=gate_for(path);self.stop=threading.Event();self.ready=threading.Event();self.lock=threading.Lock()
        self.health={'status':'starting'};self.thread=threading.Thread(target=self.run,name='sqlite-checkpoint',daemon=True)
    def snapshot(self):
        with self.lock:return dict(self.health)
    def start(self):
        self.thread.start()
        if not self.ready.wait(5)or self.snapshot().get('status')=='failed':raise RuntimeError('CHECKPOINT_KEEPER_NOT_READY')
        return self
    def run(self):
        db=None
        try:
            db=sqlite3.connect(self.path,timeout=0);db.execute('PRAGMA synchronous=FULL');db.execute('PRAGMA wal_autocheckpoint=0')
            if db.execute('PRAGMA journal_mode').fetchone()[0]!='wal':raise RuntimeError('CHECKPOINT_REQUIRES_WAL')
            self.gate.managed=True
            with self.lock:self.health={'status':'ok','checkpoint_count':0,'wal_bytes':0,'mode':'PASSIVE','synchronous':'FULL'}
            self.ready.set();last=0.
            while not self.stop.wait(1):
                try:
                    wal=Path(str(self.path)+'-wal');size=wal.stat().st_size if wal.exists()else 0
                    now=time.monotonic()
                    if now-last<30 or size<4*1024*1024 and now-last<300:
                        with self.lock:self.health['wal_bytes']=size
                        continue
                    started=time.monotonic();busy,log,done=db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone();last=now
                    with self.lock:self.health.update(status='degraded'if size>256*1024*1024 and done<log else'ok',wal_bytes=size,checkpoint_count=self.health.get('checkpoint_count',0)+1,last_checkpoint_s=time.monotonic()-started,busy=busy,log_frames=log,checkpointed_frames=done)
                except Exception as error:
                    with self.lock:self.health.update(status='degraded',error_code=type(error).__name__)
        except Exception as error:
            with self.lock:self.health={'status':'failed','error_code':type(error).__name__}
            self.ready.set()
        finally:
            self.gate.managed=False
            if db:db.close()
    def close(self):
        self.stop.set();self.thread.join(timeout=5)
        return not self.thread.is_alive()
