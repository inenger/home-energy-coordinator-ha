"""Read-only measurements and strictly allowlisted weather/metadata queries; no device actions."""
from __future__ import annotations
import argparse
import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone
import urllib.request
import urllib.error
from .core import build_sample, digest, evaluate, forecast_payloads, canonical, VERSION
from .store import Store
from .appliances import discover as discover_appliances
from .analytics import record as record_analytics
from . import telemetry, weather

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('ENERGY_DATA_DIR', '/data/evidence'))

def utcnow():
    return datetime.now(timezone.utc).isoformat()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('REDIRECT_REJECTED')

class ReadOnlyHA:
    """Read-only application interface, not an OS-level credential sandbox."""
    def __init__(self, base='http://supervisor/core', token_file=None):
        from urllib.parse import urlsplit
        parts = urlsplit(base)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.query or parts.fragment or (parts.path not in ('', '/') and not (parts.hostname == 'supervisor' and parts.path == '/core')):
            raise ValueError('Invalid Home Assistant origin')
        self.base, self.token_file = base.rstrip('/'), Path(token_file) if token_file else None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, path):
        if path != '/api/states':
            raise ValueError('Only /api/states is permitted')
        token = read_token(self.token_file)
        req = urllib.request.Request(self.base+path, headers={'Authorization': 'Bearer '+token}, method='GET')
        with self.opener.open(req, timeout=15) as response:
            raw = response.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:
            raise ValueError('Response too large')
        data = json.loads(raw)
        if not isinstance(data, list) or any(not isinstance(x, dict) or 'entity_id' not in x for x in data):
            raise ValueError('Invalid states response')
        return data

    def _query(self, path, payload, text=False):
        req=urllib.request.Request(self.base+path,data=json.dumps(payload).encode(),method='POST',
            headers={'Authorization':'Bearer '+read_token(self.token_file),'Content-Type':'application/json'})
        with self.opener.open(req,timeout=12) as response: raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: raise ValueError('Query response too large')
        return raw.decode() if text else json.loads(raw)

    def weather_forecast(self, entity, kind):
        path,payload=weather.request_parts(entity,kind)
        return self._query(path,payload)

    def entity_metadata(self, ids):
        if len(ids)>1500 or any(not telemetry.ENTITY_ID.fullmatch(e) for e in ids):
            raise ValueError('Invalid metadata IDs')
        template="{% set ids = "+json.dumps(ids)+" %}{% set ns=namespace(rows=[]) %}{% for e in ids %}{% set ns.rows=ns.rows+[dict(entity_id=e,device_id=device_id(e),area_id=area_id(e),area_name=area_name(e))] %}{% endfor %}{{ ns.rows | to_json }}"
        rows=json.loads(self._query('/api/template',{'template':template},text=True))
        return {row['entity_id']:{k:row.get(k) for k in ('device_id','area_id','area_name')} for row in rows if row.get('entity_id') in ids}


def read_token(token_file=None):
    if token_file is None:
        token = os.environ.get('SUPERVISOR_TOKEN', '').strip()
    else:
        path = Path(token_file)
        if path.stat().st_mode & 0o077:
            raise ValueError('Token file must not be group/world accessible')
        token = path.read_text().strip()
    if not token or any(c in token for c in ('\n', '\r')):
        raise ValueError('Missing or invalid authentication')
    return token

def settings():
    cfg = json.loads((ROOT/'config/settings.example.json').read_text())
    op = Path(os.environ.get('ENERGY_OPTIONS_FILE', '/data/options.json'))
    options = json.loads(op.read_text()) if op.exists() else {}
    if options.get('mode', 'observe_only') != 'observe_only':
        raise ValueError('This release only supports observe_only')
    cfg['interval_seconds'] = int(options.get('interval_seconds', 60))
    if not 60 <= cfg['interval_seconds'] <= 300:
        raise ValueError('Interval must be 60..300 seconds')
    cfg['storage_limit_bytes'] = int(options.get('storage_limit_mb', 2048))*1024*1024
    cfg['minimum_free_bytes'] = int(options.get('minimum_free_mb', 1024))*1024*1024
    cfg['calibration']['enabled'] = options.get('self_calibration', True) is True
    cfg['analytics_enabled'] = options.get('analytics_enabled', True) is True
    cfg['github_auto_update'] = options.get('github_auto_update', False) is True
    cfg['github_token'] = options.get('github_token') or None
    cfg['weather_enabled']=options.get('weather_enabled',True) is True
    cfg['weather_interval_seconds']=max(1800,int(options.get('weather_interval_seconds',3600)))
    cfg['weather_types']=['hourly','daily']
    cfg['weather_reference']=options.get('weather_reference','sensor.current_outdoor_temperature_bt1_30002')
    if not isinstance(cfg['weather_reference'],str) or not telemetry.ENTITY_ID.fullmatch(cfg['weather_reference']) or not cfg['weather_reference'].startswith('sensor.'):
        raise ValueError('Invalid weather reference entity')
    cfg['ha_base_url'] = 'http://supervisor/core'
    cfg['token_file'] = None
    catalog = json.loads((ROOT/'config/entities.json').read_text())
    return cfg, catalog

def storage_check(cfg):
    data = DATA
    data.mkdir(mode=0o700,exist_ok=True)
    used=sum(p.stat().st_size for p in data.glob('evidence.sqlite*') if p.is_file())
    if used >= cfg['storage_limit_bytes']:
        raise RuntimeError('STORAGE_BUDGET_EXCEEDED_NO_DATA_DELETED')
    if shutil.disk_usage(data).free < cfg['minimum_free_bytes']:
        raise RuntimeError('LOW_DISK_NO_DATA_DELETED')

def atomic_json(path, payload):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    temp.chmod(0o600)
    temp.replace(path)

def collect():
    os.umask(0o077)
    cfg, catalog = settings()
    storage_check(cfg)
    with (DATA/'collect.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        store = Store(DATA/'evidence.sqlite')
        started = utcnow()
        try:
            client=ReadOnlyHA(cfg['ha_base_url'],cfg['token_file'])
            states=client.get('/api/states')
            received=utcnow()
            policy=json.loads((ROOT/'config/telemetry.json').read_text())
            custom=DATA/'telemetry-overrides.json'
            if custom.exists():
                extra=json.loads(custom.read_text())
                for key in ('mappings','appliances'): policy[key].update(extra.get(key,{}))
                for key in ('include','exclude'): policy[key]=extra.get(key,policy[key])
            context=telemetry.discover(states,received,policy)
            metafile=DATA/'entity-metadata.json';metadata={}
            if metafile.exists():
                try: metadata=json.loads(metafile.read_text())
                except (ValueError,OSError): pass
            # Backoff also on failure: no expensive metadata retry every minute.
            attempt=DATA/'metadata-attempt.json';due=True
            try: due=datetime.now().timestamp()-attempt.stat().st_mtime>21600
            except OSError: pass
            if due:
                try:
                    metadata=client.entity_metadata(list(context['points']))
                    atomic_json(metafile,metadata)
                    atomic_json(attempt,{'at':received,'status':'ok'})
                except Exception as error: atomic_json(attempt,{'at':received,'error_code':type(error).__name__})
            context=telemetry.discover(states,received,policy,metadata)
            safe_cfg={k:v for k,v in cfg.items() if k not in ('ha_base_url','token_file','github_token')}
            source_hashes={p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'energy').glob('*.py'))}
            manifest={'settings':safe_cfg,'catalog':catalog,'software_version':VERSION,'source_hashes':source_hashes,'telemetry_policy':policy}
            sample=build_sample(states,catalog,received,started,digest(manifest))
            sample['appliances']=discover_appliances(states,policy.get('appliances',{}))
            decision=evaluate(sample,cfg)
            store.record(sample,decision,list(forecast_payloads(states)),manifest)
            telemetry.record(store,context)
            try: weather.poll(store,client,states,cfg,datetime.now(timezone.utc))
            except Exception as error: store.failure(utcnow(),'WEATHER_'+type(error).__name__)
            if cfg.get('analytics_enabled', True):
                record_analytics(store,sample)
            summary=store.summary()
            summary['telemetry_quality']=context['quality']
            atomic_json(DATA/'status.json',summary)
            print(json.dumps({'collection':'ok','samples':summary['samples'],'forecast_versions':summary['forecast_versions'],'quality':summary['quality'],'observed_at':received},ensure_ascii=False))
        except Exception as error:
            code='HTTP_'+str(error.code) if isinstance(error,urllib.error.HTTPError) else type(error).__name__
            store.failure(utcnow(),code)
            atomic_json(DATA/'status.json',{'mode':'observe_only','collection':'failed','error_code':code,'at':utcnow()})
            print(json.dumps({'collection':'failed','error_code':code}))
            raise SystemExit(1) from None
        finally:
            store.close()

def main():
    parser=argparse.ArgumentParser(description='Read-only energy evidence and offline test runner')
    sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('collect'); sub.add_parser('status'); sub.add_parser('demo')
    ex=sub.add_parser('export'); ex.add_argument('--date',required=True)
    args=parser.parse_args()
    if args.cmd=='collect':
        collect(); return
    if args.cmd=='demo':
        from .simulator import demo
        print(json.dumps(demo(),ensure_ascii=False,indent=2)); return
    os.umask(0o077)
    store=Store(DATA/'evidence.sqlite')
    try:
        if args.cmd=='status':
            print(json.dumps(store.summary(),ensure_ascii=False,indent=2))
        else:
            from datetime import date
            day=date.fromisoformat(args.date).isoformat()
            report=store.export(day)
            dest=DATA/f'ai_bundle_{day}.json.gz'
            with gzip.open(dest,'wt',encoding='utf-8') as f: json.dump(report,f,ensure_ascii=False,allow_nan=False)
            print(json.dumps({'file':str(dest),'sha256':__import__('hashlib').sha256(dest.read_bytes()).hexdigest(),'samples':len(report['samples']),'uploaded':False}))
    finally:
        store.close()
