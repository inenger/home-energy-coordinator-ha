"""Native Home Assistant app process; persistent /data, internal Supervisor API.

The HTTP interface is read-only and available via authenticated HA Ingress.
No host ports, actuator endpoint, scheduling service or external AI dependency.
"""
from __future__ import annotations
from datetime import datetime, timezone, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, os, signal, threading, time, urllib.parse
from .collector import DATA, collect, settings, atomic_json
from .store import Store
from .calibration import calibrate
from .publish_status import main as publish
from .core import VERSION
from . import telemetry
from .store import pack
from .analytics import build as build_analytics
from .webui import PAGE
from .updater import apply as apply_update, status_file as update_status_file
from .portable import backup as portable_backup, restore_if_empty as portable_restore

STOP=threading.Event()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,payload,code=200):
        body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.client_address[0] not in ('172.30.32.2','127.0.0.1','::1'):
            self.send_json({'error':'INGRESS_ONLY'},403);return
        path=urllib.parse.urlsplit(self.path)
        if path.path=='/health':
            self.send_json({'version':VERSION,'mode':'observe_only','device_actions':0});return
        try:
            if path.path in ('/status.json','/calibration.json','/analytics.json','/update.json'):
                file=DATA/path.path.lstrip('/')
                self.send_json(json.loads(file.read_text()) if file.exists() else {'status':'waiting'});return
            if path.path=='/export':
                requested=urllib.parse.parse_qs(path.query).get('date',[''])[0]
                day=date.fromisoformat(requested).isoformat()
                store=Store(DATA/'evidence.sqlite')
                try:payload=store.export(day)
                finally:store.close()
                self.send_json(payload);return
            if path.path!='/':
                self.send_json({'error':'NOT_FOUND'},404);return
            body=PAGE.encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        except (ValueError,OSError):self.send_json({'error':'DATA_NOT_AVAILABLE'},400)
        except Exception:self.send_json({'error':'INTERNAL_ERROR'},500)

def calibration_once(cfg):
    if not (DATA/'evidence.sqlite').exists():return
    store=Store(DATA/'evidence.sqlite')
    try:
        result=calibrate(store,cfg['calibration'])
        if 'calculated_at' in result:store.record_calibration(result)
    finally:store.close()
    atomic_json(DATA/'calibration.json',result)

def analytics_once(cfg=None):
    if not (DATA/'evidence.sqlite').exists():return
    store=Store(DATA/'evidence.sqlite')
    try:
        result=build_analytics(store,cfg=cfg)
        with store.db:
            snapshot={'at':result['calculated_at'],'version':VERSION,'pv':result['pv'],
                      'weather_metrics':result['weather']['metrics'],'device_actions':0}
            store.db.execute('INSERT OR IGNORE INTO analytics_versions VALUES(?,?)',(result['calculated_at'],pack(snapshot)))
    finally:store.close()
    atomic_json(DATA/'analytics.json',result)

def main():
    os.umask(0o077)
    DATA.mkdir(mode=0o700,parents=True,exist_ok=True)
    try: print(json.dumps({'portable_restore':portable_restore(DATA/'evidence.sqlite')}),flush=True)
    except Exception as e: print(json.dumps({'portable_restore':'failed','error_code':type(e).__name__}),flush=True)
    cfg,_=settings()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:STOP.set())
    try:os.nice(10)
    except OSError:pass
    server=ThreadingHTTPServer(('0.0.0.0',8099),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    print(json.dumps({'version':VERSION,'runtime':'home_assistant_app','mode':'observe_only','device_actions':0}),flush=True)
    next_cal=0.0
    next_analytics=0.0
    next_update=0.0
    next_portable=0.0
    try:
        while not STOP.is_set():
            started=time.monotonic()
            try:collect()
            except (Exception,SystemExit) as e:
                print(json.dumps({'cycle':'failed','error_code':type(e).__name__}),flush=True)
                try:atomic_json(DATA/'status.json',{'collection':'failed','error_code':type(e).__name__})
                except OSError:pass
            if time.monotonic()>=next_analytics:
                try:
                    if cfg.get('analytics_enabled',True): analytics_once(cfg)
                except Exception as e:print(json.dumps({'analytics':'failed','error_code':type(e).__name__}),flush=True)
                next_analytics=time.monotonic()+900
            if time.monotonic()>=next_cal:
                try:calibration_once(cfg)
                except Exception as e:print(json.dumps({'calibration':'failed','error_code':type(e).__name__}),flush=True)
                next_cal=time.monotonic()+86400
            if time.monotonic()>=next_portable:
                try: print(json.dumps({'portable_backup':portable_backup(DATA/'evidence.sqlite',VERSION)}),flush=True)
                except Exception as e: print(json.dumps({'portable_backup':'failed','error_code':type(e).__name__}),flush=True)
                next_portable=time.monotonic()+21600
            if time.monotonic()>=next_update:
                try:
                    if cfg.get('github_auto_update'):
                        if cfg.get('github_token'):
                            update_status_file(apply_update(cfg['github_token']))
                        else:
                            update_status_file({'status':'token_required','installed':VERSION})
                    else:
                        update_status_file({'status':'disabled','installed':VERSION})
                except Exception as e:
                    update_status_file({'status':'update_failed','installed':VERSION,'error_code':type(e).__name__})
                next_update=time.monotonic()+21600
            try:publish()
            except Exception as e:print(json.dumps({'publication':'failed','error_code':type(e).__name__}),flush=True)
            STOP.wait(max(1,cfg['interval_seconds']-(time.monotonic()-started)))
    finally:
        server.shutdown();server.server_close()
        print(json.dumps({'runtime':'stopped','device_actions':0}),flush=True)

if __name__=='__main__':main()
