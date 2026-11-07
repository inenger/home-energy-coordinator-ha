"""Keep SQLite WAL filenames alive during native tar, without a transaction.

A separate short-lived hook child survives evidence-worker reconnects. Lease,
readiness and flock files are excluded by the existing .native-backup-* rule.
It never writes application rows, sends HTTP, or signals a PID.
"""
from contextlib import contextmanager,closing
import fcntl,json,os,sqlite3,sys,time,uuid
from pathlib import Path
LEASE='.native-backup-holder.json'
READY='.native-backup-holder-ready.json'
LOCK='.native-backup-holder.lock'
MAX_HOLD_SECONDS=1800
_children={}

def read(path):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return None

def atomic(path,value):
    pending=path.with_suffix('.tmp')
    pending.write_text(json.dumps(value));os.chmod(pending,0o600);os.replace(pending,path)

def active(root):
    with (root/LOCK).open('a')as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        return False

def stop(root,timeout=10):
    root=Path(root)
    if not root.exists():
        reap(root,time.monotonic()+timeout);return
    (root/LEASE).unlink(missing_ok=True)
    deadline=time.monotonic()+timeout
    while active(root):
        if time.monotonic()>=deadline:raise TimeoutError('NATIVE_BACKUP_HOLDER_STOP_TIMEOUT')
        time.sleep(.05)
    (root/READY).unlink(missing_ok=True)
    reap(root,deadline)

def reap(root,deadline):
    pid=_children.pop(str(root.resolve()),None)
    if pid is None:return
    while True:
        try:done,_=os.waitpid(pid,os.WNOHANG)
        except ChildProcessError:return
        if done:return
        if time.monotonic()>=deadline:raise TimeoutError('NATIVE_BACKUP_HOLDER_REAP_TIMEOUT')
        time.sleep(.05)

def start(root,database,timeout=10,hold_seconds=MAX_HOLD_SECONDS):
    root=Path(root);database=Path(database)
    if not 0<hold_seconds<=MAX_HOLD_SECONDS:raise ValueError('NATIVE_BACKUP_INVALID_HOLDER_DURATION')
    if active(root):raise RuntimeError('NATIVE_BACKUP_ALREADY_ACTIVE')
    (root/READY).unlink(missing_ok=True)
    token=uuid.uuid4().hex
    atomic(root/LEASE,{'token':token,'database':str(database.resolve()),'hold_seconds':hold_seconds})
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])+os.pathsep+os.environ.get('PYTHONPATH','')}
    env.pop('SUPERVISOR_TOKEN',None)
    pid=None
    try:
        # posix_spawn avoids forking a multithreaded evidence/test process and
        # intentionally allows the pre-hook parent to exit before the holder.
        with open(os.devnull,'r+b')as null:
            pid=os.posix_spawn(sys.executable,[sys.executable,'-m','energy.native_backup_holder',str(root.resolve()),token],env,
                file_actions=[(os.POSIX_SPAWN_DUP2,null.fileno(),fd)for fd in (0,1,2)],setsid=True)
        _children[str(root.resolve())]=pid
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            ready=read(root/READY)
            if ready and ready.get('token')==token:
                if ready.get('status')!='ready':raise RuntimeError('NATIVE_BACKUP_HOLDER_FAILED:'+ready.get('error','unknown'))
                if not active(root):raise RuntimeError('NATIVE_BACKUP_HOLDER_EXITED')
                return {'token':token,'pid':pid}
            done,_=os.waitpid(pid,os.WNOHANG)
            if done:
                _children.pop(str(root.resolve()),None)
                raise RuntimeError('NATIVE_BACKUP_HOLDER_EXITED')
            time.sleep(.05)
        raise TimeoutError('NATIVE_BACKUP_HOLDER_READY_TIMEOUT')
    except BaseException:
        stop(root)
        raise

def run(root,token):
    root=Path(root)
    with (root/LOCK).open('a')as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        lease=read(root/LEASE)
        if not lease or lease.get('token')!=token:return
        try:
            with closing(sqlite3.connect(Path(lease['database']).as_uri()+'?mode=rw',uri=True,timeout=.25))as db:
                # Exhaust the cursor; no read/write transaction remains held.
                db.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
                assert not db.in_transaction
                duration=lease['hold_seconds']
                if not 0<duration<=MAX_HOLD_SECONDS:raise ValueError('NATIVE_BACKUP_INVALID_HOLDER_DURATION')
                deadline=time.monotonic()+duration
                atomic(root/READY,{'token':token,'status':'ready'})
                while time.monotonic()<deadline:
                    current=read(root/LEASE)
                    if not current or current.get('token')!=token:break
                    time.sleep(.1)
        except BaseException as error:
            atomic(root/READY,{'token':token,'status':'failed','error':type(error).__name__})
            raise
        finally:
            ready=read(root/READY)
            if ready and ready.get('token')==token and ready.get('status')=='ready':
                (root/READY).unlink(missing_ok=True)

if __name__=='__main__':
    os.umask(0o077)
    run(Path(sys.argv[1]),sys.argv[2])
