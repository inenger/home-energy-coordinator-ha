"""PID1 bootstrap for atomic code-only updates with rollback."""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path

DATA=Path("/data/evidence")
RUNTIME=DATA/"runtime"
STOP=False

def _sig(*_):
    global STOP
    STOP=True

def active():
    p=RUNTIME/"active.json"
    if not p.exists():return None
    try:
        x=json.loads(p.read_text())
        from .core import VERSION
        def version(v): return tuple(int(n) for n in str(v).split('.'))
        if version(x['version'])<=version(VERSION): return None
        path=Path(x["path"]).resolve()
        if RUNTIME.resolve() not in path.parents or not (path/"energy/runtime.py").exists():return None
        return x
    except Exception:return None

def run_child(selection):
    env=os.environ.copy()
    if selection:
        env["PYTHONPATH"]=str(Path(selection["path"]).resolve())+os.pathsep+"/app"
    else:
        env["PYTHONPATH"]="/app"
    cwd=str(Path(selection["path"]).resolve()) if selection else "/app"
    return subprocess.Popen([sys.executable,"-m","energy.runtime"],env=env,cwd=cwd)

def rollback(selection,reason):
    if not selection:return
    previous=selection.get("previous")
    failed=RUNTIME/f"failed-{int(time.time())}.json"
    failed.parent.mkdir(parents=True,exist_ok=True)
    failed.write_text(json.dumps({"selection":selection,"reason":reason},ensure_ascii=False))
    activefile=RUNTIME/"active.json"
    if previous and Path(previous).exists():
        activefile.write_text(json.dumps({"path":previous,"version":selection.get("previous_version"),"previous":None},ensure_ascii=False))
    else:
        activefile.unlink(missing_ok=True)

def main():
    global STOP
    DATA.mkdir(parents=True,exist_ok=True);RUNTIME.mkdir(parents=True,exist_ok=True)
    for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,_sig)
    while not STOP:
        sel=active();started=time.monotonic();child=run_child(sel)
        while child.poll() is None and not STOP:
            if (RUNTIME/"restart").exists():
                (RUNTIME/"restart").unlink(missing_ok=True)
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                break
            time.sleep(1)
        if STOP:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill()
            return 0
        runtime=time.monotonic()-started
        code=child.returncode
        if code not in (0,None) and sel and runtime<60:
            rollback(sel,f"runtime exited {code} after {runtime:.1f}s")
        time.sleep(2)
    return 0

if __name__=="__main__":raise SystemExit(main())
