"""Cooperative SQLite writers. No network or physical device access."""
import sqlite3,threading,time,weakref
from pathlib import Path

class WriterTimeout(RuntimeError):
    """A local writer did not yield within the connection's bounded wait."""

class Gate:
    def __init__(self):
        self.condition=threading.Condition();self.owner=None;self.depth=0;self.fast_waiters=0;self.owner_thread=None;self.acquired_at=None;self.operation=None;self.operation_at=None;self.last_scope=None;self.managed=False
    def diagnostic(self):
        with self.condition:
            return {'owner_thread':self.owner_thread,
                    'held_seconds':max(0.,time.monotonic()-self.acquired_at)if self.acquired_at is not None else None,
                    'fast_waiters':self.fast_waiters,'operation':self.operation,'operation_seconds':max(0.,time.monotonic()-self.operation_at)if self.operation_at is not None else None,'last_scope':self.last_scope}
    def phase(self,name):
        with self.condition:
            if self.owner==threading.get_ident():self.operation=name;self.operation_at=time.monotonic()
    def acquire(self,fast,timeout):
        ident=threading.get_ident()
        with self.condition:
            if self.owner==ident:self.depth+=1;return
            if fast:self.fast_waiters+=1;self.condition.notify_all()
            try:
                if not self.condition.wait_for(lambda:self.owner is None and (fast or self.fast_waiters==0),timeout):
                    error=WriterTimeout('Local SQLite writer wait exceeded')
                    error.writer_diagnostic={**self.diagnostic(),'wait_timeout_s':timeout}
                    raise error
                self.owner=ident;self.depth=1;self.owner_thread=threading.current_thread().name;self.acquired_at=time.monotonic();self.operation="python_scope";self.operation_at=self.acquired_at
            finally:
                if fast:self.fast_waiters-=1
                self.condition.notify_all()
    def release(self):
        with self.condition:
            if self.owner!=threading.get_ident():raise RuntimeError('SQLite writer owner mismatch')
            self.depth-=1
            if not self.depth:
                self.last_scope={'owner_thread':self.owner_thread,'seconds':time.monotonic()-self.acquired_at,'last_operation':self.operation}
                self.owner=None;self.owner_thread=None;self.acquired_at=None;self.operation=None;self.operation_at=None;self.condition.notify_all()

_registry=weakref.WeakValueDictionary()
_registry_lock=threading.Lock()
def gate_for(path):
    key=str(Path(path).resolve())
    with _registry_lock:
        gate=_registry.get(key)
        if gate is None:gate=Gate();_registry[key]=gate
        return gate

class Connection(sqlite3.Connection):
    """Serialize write scopes/schema; ordinary SELECTs remain concurrent."""
    def configure(self,path,timeout):
        self._gate=gate_for(path);self._wait=timeout;self._fast=timeout<=.25
        self._owned=False;self._contexts=0
        # These affect/query this newly opened connection, without a DB write.
        try:
            super().execute('PRAGMA synchronous=FULL')
            self.journal_mode=super().execute('PRAGMA journal_mode').fetchone()[0]
            if self._gate.managed:super().execute('PRAGMA wal_autocheckpoint=0')
        except sqlite3.Error as error:self._annotate(error,'configure');raise
    def _acquire(self):
        if not self._owned:self._gate.acquire(self._fast,self._wait);self._owned=True
    def _annotate(self,error,operation):
        if isinstance(error,sqlite3.Error):
            error.writer_diagnostic={**self._gate.diagnostic(),'operation':operation,
                                     'connection_in_transaction':self.in_transaction}
    def _release_idle(self):
        if self._owned and not self._contexts and not self.in_transaction:
            self._owned=False;self._gate.release()
    def __enter__(self):
        self._acquire();self._contexts+=1
        return self
    def __exit__(self,*args):
        self._gate.phase('rollback'if args and args[0]else'commit')
        try:return super().__exit__(*args)
        finally:self._contexts-=1;self._release_idle()
    def execute(self,sql,parameters=()):
        token=sql.lstrip().split(None,1)[0].upper()if sql.strip()else ''
        writing=token not in ('SELECT','EXPLAIN')
        if writing:self._acquire()
        if self._owned:self._gate.phase(token)
        try:return super().execute(sql,parameters)
        except sqlite3.Error as error:self._annotate(error,token);raise
        finally:
            if self._owned:self._gate.phase('python_scope')
            if writing:self._release_idle()
    def executemany(self,sql,parameters):
        self._acquire()
        self._gate.phase('executemany')
        try:return super().executemany(sql,parameters)
        except sqlite3.Error as error:self._annotate(error,'executemany');raise
        finally:self._release_idle()
    def executescript(self,sql):
        self._acquire()
        self._gate.phase('executescript')
        try:return super().executescript(sql)
        except sqlite3.Error as error:self._annotate(error,'executescript');raise
        finally:self._release_idle()
    def commit(self):
        self._gate.phase('commit')
        try:return super().commit()
        finally:self._release_idle()
    def rollback(self):
        self._gate.phase('rollback')
        try:return super().rollback()
        finally:self._release_idle()
    def close(self):
        if hasattr(self,'_gate'):self._gate.phase('close')
        try:return super().close()
        finally:
            if self._owned:self._owned=False;self._gate.release()

def details(error):
    if isinstance(error,WriterTimeout):
        return {'source':'local_writer','sqlite_errorcode':None,'sqlite_errorname':None,'message':str(error),'writer_diagnostic':getattr(error,'writer_diagnostic',None)}
    if isinstance(error,sqlite3.Error):
        return {'source':'sqlite','sqlite_errorcode':getattr(error,'sqlite_errorcode',None),
                'sqlite_errorname':getattr(error,'sqlite_errorname',None),'message':str(error)[:512],
                'writer_diagnostic':getattr(error,'writer_diagnostic',None)}
    return None

def schema_ready(db,names):
    names=tuple(names)
    return db.execute('SELECT count(*) FROM sqlite_master WHERE name IN('+','.join('?'for _ in names)+')',names).fetchone()[0]==len(names)
