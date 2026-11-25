"""Read-only HA preflight. Never authorizes or dispatches an inverter command."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'priority_shadow')]
from energy.live_control import PilotHA
from ops.solax_modbus.hec_mode8_pilot import check_states, PHASES

def report(first, second, now):
    blockers = []
    for label, snapshot in (('first', first), ('second', second)):
        states = {k: SimpleNamespace(state=v['state'], attributes=v['attributes'],
                  last_reported=datetime.fromisoformat(v['last_reported']))
                  for k, v in snapshot.items()}
        try:
            check_states(states.get, now)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            blockers.append(label + ': ' + str(error))
    fresh = all(datetime.fromisoformat(second[e]['last_reported']) >
                datetime.fromisoformat(first[e]['last_reported']) for e in PHASES)
    if not fresh:
        blockers.append('no two distinct phase frames')
    return {'at':now.isoformat(), 'ha_checks_ok':not blockers, 'blockers':blockers,
            'new_phase_frame':fresh, 'entity_count':len(second),
            'physical_control_ready':False, 'device_actions':0,
            'unverified':['native expiry','local recovery under active VPP',
                          'transport retry/cancellation','operator presence','physical preflight']}

def main():
    client = PilotHA()
    first = client.snapshot()
    time.sleep(1.1)
    second = client.snapshot()
    result = report(first, second, datetime.now(timezone.utc))
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['ha_checks_ok'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
