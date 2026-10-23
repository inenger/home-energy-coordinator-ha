"""Verify a full SOC preview and real fitted energy curve on the RPi only.

Private inputs stay on the RPi. This reads an isolated preview and history;
it never opens a mutable production Store or invokes HA services.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--preview', required=True)
    p.add_argument('--history', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    sys.path.insert(0, a.source)
    from energy.core import instant, TZ
    from energy.soc_evidence import verify
    from energy.soc_energy import Battery
    from energy.soc_history import read_gzip
    from energy.soc_runtime import view

    preview = json.loads(Path(a.preview).read_text())
    assert verify(preview)['verified'], 'Preview canonical hash mismatch'
    issued = instant(preview['issued_at'])
    assert preview['status'] == 'conditional_shadow_plan'
    assert preview['input_snapshot']['use_temperature'] == preview['house_validation']['use_temperature']
    assert preview['house_validation']['feature_source'] == 'archived_weather_asof_02:55'
    for r in preview['forecast_periods']:
        assert instant(r['forecast_available_at']) <= issued
    timeline = preview['timeline']
    assert timeline
    profile = view(preview)['profile']
    assert profile[0]['hours'] == 0
    first = next(t for t in timeline if instant(t['start']).astimezone(TZ).date().isoformat() == preview['day'])
    assert instant(profile[0]['at']) == instant(first['start'])
    assert abs(profile[0]['soc'] - first['soc_start']) < 1e-8
    for t in timeline:
        assert instant(t['at']) == instant(t['end'])
        assert abs(t['soc'] - t['soc_end']) < 1e-8
        for s in t['charge_segments']:
            assert s['battery_total_dc_kw'] <= preview['input_snapshot']['battery_charge_max_dc_kw'] + 1e-7
            assert s['battery_grid_dc_kw'] >= 0
    history = read_gzip(a.history)
    rng = random.Random(624)
    maximum = 0.
    for envelope in [False, True]:
        b = Battery(history['battery_model'], envelope)
        for _ in range(2500):
            soc = rng.uniform(11, 99)
            before = b.available(soc)
            mid, accepted, loss = b.charge_dc(soc, rng.uniform(0, 12))
            after, taken = b.discharge_dc(mid, rng.uniform(0, 12), 15)
            residual = abs(b.available(after) - (before + accepted - loss - taken))
            maximum = max(maximum, residual)
            assert residual < 1e-8 and after >= min(soc, 15)-1e-8
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'decision_hash_verified': True, 'forecast_availability_verified': True,
              'profile_interval_ends_verified': True, 'real_battery_curve_cases': 5000,
              'maximum_balance_residual_kwh': maximum,
              'status': preview['status'], 'target_soc_pct': preview['target_soc_pct'],
              'horizon_complete': preview['horizon_complete'],
              'temperature_model_accepted': preview['house_validation']['use_temperature'],
              'device_actions': 0, 'measured_savings_czk': None}
    Path(a.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
