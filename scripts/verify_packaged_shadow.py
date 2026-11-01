"""Test z rozložení skutečných Docker COPY, bez přístupu ke zdrojům mimo balík."""
import os,shlex,shutil,subprocess,sys,tempfile
from pathlib import Path
source=Path(__file__).resolve().parents[1]/'priority_shadow'
with tempfile.TemporaryDirectory()as directory:
 app=Path(directory)/'app';app.mkdir()
 for line in (source/'Dockerfile').read_text().splitlines():
  if not line.startswith('COPY '):continue
  parts=shlex.split(line);assert len(parts)==3 and parts[2].startswith('/app/'),line
  src=(source/parts[1]).resolve();assert src.is_relative_to(source),line
  dst=app/parts[2].removeprefix('/app/')
  if src.is_dir():shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  else:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 env={k:v for k,v in os.environ.items()if k!='PYTHONPATH'}
 subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_archived_replay.py','-q'],cwd=app,env=env,check=True)
print('PASS: replay import and provenance contract in Docker COPY layout')
