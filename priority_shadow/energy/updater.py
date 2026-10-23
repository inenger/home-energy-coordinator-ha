"""Private-GitHub code updater. No update is accepted without an explicit release manifest."""
from __future__ import annotations
import base64, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, urllib.error, zipfile
from pathlib import Path
from .core import VERSION

REPO="inenger/home-energy-coordinator"
API="https://api.github.com"
DATA=Path("/data/evidence")
RUNTIME=DATA/"runtime"
ALLOWED_PREFIXES=("energy/","config/","tests/")
SEMVER=re.compile(r"^\d+\.\d+\.\d+$")

def _version(v):
    if not SEMVER.fullmatch(str(v)):raise ValueError("invalid version")
    return tuple(map(int,v.split(".")))

def _request(url,token):
    if not token:raise ValueError("github token missing")
    req=urllib.request.Request(url,headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"home-energy-coordinator"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=30) as r:
        data=r.read(12*1024*1024+1)
    if len(data)>12*1024*1024:raise ValueError("download too large")
    return data

def read_manifest(token):
    raw=_request(f"{API}/repos/{REPO}/contents/release.json?ref=main",token)
    doc=json.loads(raw)
    content=base64.b64decode(doc["content"],validate=False)
    m=json.loads(content)
    if set(("version","commit","runtime_api","files"))-set(m):raise ValueError("incomplete release manifest")
    if not SEMVER.fullmatch(str(m["version"])) or m["runtime_api"]!=1:raise ValueError("unsupported release")
    if not re.fullmatch(r"[0-9a-f]{40}",str(m["commit"])):raise ValueError("invalid commit")
    if not isinstance(m["files"],dict) or not m["files"]:raise ValueError("empty file manifest")
    return m

def check(token):
    try:m=read_manifest(token)
    except Exception as e:return {"status":"check_failed","error_code":type(e).__name__,"installed":VERSION}
    return {"status":"update_available" if _version(m["version"])>_version(VERSION) else "current",
            "installed":VERSION,"available":m["version"],"commit":m["commit"]}

def apply(token):
    manifest=read_manifest(token)
    if _version(manifest["version"])<=_version(VERSION):
        return {"status":"current","installed":VERSION,"available":manifest["version"]}
    RUNTIME.mkdir(parents=True,exist_ok=True)
    target=RUNTIME/"releases"/manifest["version"]
    if target.exists():shutil.rmtree(target)
    stage=Path(tempfile.mkdtemp(prefix="hec-update-",dir=RUNTIME))
    try:
        blob=_request(f"{API}/repos/{REPO}/zipball/{manifest['commit']}",token)
        z=zipfile.ZipFile(io.BytesIO(blob))
        members=[x for x in z.infolist() if not x.is_dir()]
        for rel,expected in manifest["files"].items():
            if not any(rel.startswith(p) for p in ALLOWED_PREFIXES) or rel.startswith("/") or ".." in Path(rel).parts:
                raise ValueError("unsafe manifest path")
            matches=[m for m in members if m.filename.split("/",1)[-1]==rel]
            if len(matches)!=1:raise ValueError("manifest file missing")
            info=matches[0]
            if info.external_attr>>16 & 0o170000 == 0o120000:raise ValueError("symlink rejected")
            data=z.read(info)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError("hash mismatch")
            dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        env=os.environ.copy();env["PYTHONPATH"]=str(stage)
        tests=stage/"tests"
        if tests.exists():
            p=subprocess.run([sys.executable,"-m","unittest","discover","-s",str(tests),"-q"],
                env=env,cwd=stage,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
            if p.returncode:raise RuntimeError("update tests failed")
        target.parent.mkdir(parents=True,exist_ok=True);stage.replace(target)
        activefile=RUNTIME/"active.json";old=None
        if activefile.exists():
            try:old=json.loads(activefile.read_text())
            except Exception:old=None
        selection={"path":str(target),"version":manifest["version"],
                   "previous":old.get("path") if old else None,
                   "previous_version":old.get("version") if old else VERSION,
                   "commit":manifest["commit"]}
        tmp=activefile.with_suffix(".tmp");tmp.write_text(json.dumps(selection));tmp.replace(activefile)
        (RUNTIME/"restart").write_text(manifest["version"])
        return {"status":"installed_pending_restart","version":manifest["version"],"commit":manifest["commit"]}
    finally:
        if stage.exists():shutil.rmtree(stage,ignore_errors=True)

def status_file(payload):
    DATA.mkdir(parents=True,exist_ok=True)
    p=DATA/"update.json";tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2));tmp.replace(p)
