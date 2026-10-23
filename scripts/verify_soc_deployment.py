"""Post-update verification on RPi; private logs and evidence remain on RPi."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--recovery', required=True)
    p.add_argument('--version', default='0.6.2')
    a = p.parse_args()
    root = Path(a.recovery)
    if not str(root).startswith('/share/hec-recovery/'):
        raise ValueError('Expected RPi recovery directory')
    sys.path.insert(0, '/addons/energy_priority_shadow')
    from energy.store import unpack
    from energy.soc_evidence import verify
    from energy.soc_planner import POLICY
    headers = {'Authorization': 'Bearer '+os.environ['SUPERVISOR_TOKEN']}

    def get(path):
        req = urllib.request.Request('http://supervisor'+path, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.read()

    apps = {}
    for slug in ['local_energy_priority_shadow', '6696af1a_energy_coordinator']:
        d = json.loads(get('/addons/'+slug+'/info'))['data']
        apps[slug] = {k: d.get(k) for k in ['version', 'state', 'boot', 'options']}
    shadow, main = apps.values()
    assert shadow['version'] == a.version and shadow['state'] == 'started'
    assert shadow['options'].get('mode') == 'observe_only'
    assert main['version'] == '0.5.3' and main['state'] == 'started'
    logs = get('/addons/local_energy_priority_shadow/logs').decode(errors='replace')
    (root/'addon-logs-after.txt').write_text(logs)
    records = []
    for line in logs.splitlines():
        try:
            records.append(json.loads(line[line.index('{'):]))
        except (ValueError, TypeError):
            pass
    first = max((i for i, x in enumerate(records) if x.get('version') == a.version), default=-1)
    assert first >= 0
    failures = [x for x in records[first:] if x.get('priority_collection') == 'failed']
    collections = [x for x in records[first:] if x.get('priority_collection') == 'ok']
    assert collections and not failures
    states = json.loads(get('/core/api/states'))
    monitor = next(s for s in states if s['entity_id'] == 'sensor.nocni_stinovy_soc_optimalizace')
    m = monitor['attributes']
    (root/'monitor-after.json').write_text(json.dumps(monitor, ensure_ascii=False, indent=2))
    assert m.get('status') == 'conditional_shadow_plan'
    assert m.get('software_version') == a.version
    assert m.get('mode') == 'observe_only' and m.get('device_actions') == 0 and m.get('live_ready') is False
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(m['issued_at'])).total_seconds()
    assert 0 <= age < 1200
    ui = json.loads((root/'ui-result.json').read_text())
    with urllib.request.urlopen('http://homeassistant:8123'+ui['resource'], timeout=20) as response:
        assert response.status == 200
        assert hashlib.sha256(response.read()).hexdigest() == ui['card_sha256']
    configs = {'/config/automations.yaml': '1f39eac7dd4662f91bb9c414db438f52e325a22258f0b2d6bade4c17e06a1dbc',
               '/config/night_charge_shadow.yaml': '75e3770e683c9bb93966c03e7776a2021482bea318640ce8233ccf6be9ae8cf2'}
    for path, expected in configs.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
    db = sqlite3.connect('file:/share/home-energy-priority-shadow/evidence.sqlite?mode=ro', uri=True)
    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    db.execute('ATTACH DATABASE ? AS prior', ('file:'+str(root/'evidence-before.sqlite')+'?mode=ro',))
    tables = ['soc_decisions', 'soc_observations', 'soc_model_versions', 'soc_reviews',
              'priority_sessions', 'priority_events', 'priority_summaries', 'priority_samples',
              'priority_commands', 'night_sessions', 'night_samples', 'night_summaries']
    preserved = {}
    for table in tables:
        if not db.execute("SELECT 1 FROM prior.sqlite_master WHERE name=? AND type='table'", (table,)).fetchone():
            continue
        removed = db.execute(f'SELECT COUNT(*) FROM (SELECT * FROM prior.{table} EXCEPT SELECT * FROM main.{table})').fetchone()[0]
        assert removed == 0, table
        preserved[table] = True
    v2 = legacy = current_policy = 0
    for key, blob in db.execute('SELECT hash,payload FROM soc_decisions'):
        d = unpack(blob)
        v = verify(d)
        if v['status'] == 'legacy_unversioned_hash':
            legacy += 1
            continue
        assert v['verified'] and key == d['decision_hash']
        v2 += 1
        current_policy += d.get('policy') == POLICY
    assert v2 > 0 and current_policy > 0
    db.close()
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'version': shadow['version'],
              'main_version': main['version'], 'mode': 'observe_only', 'device_actions': 0,
              'healthy_collections': len(collections), 'collection_failures': len(failures),
              'current_decision_status': m['status'], 'current_decision_fresh': True,
              'new_canonical_decisions_verified': v2, 'legacy_decisions_preserved': legacy,
              'current_policy_decisions_verified': current_policy,
              'frozen_tables_preserved': preserved, 'sqlite_quick_check': 'ok',
              'card_http_and_hash_verified': True, 'dashboard_views_unchanged': ui['all_dashboard_views_unchanged'],
              'automation_configs_unchanged': True, 'live_ready': False}
    (root/'deployment-verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ['checked_at', 'frozen_tables_preserved']}))


if __name__ == '__main__':
    main()
