"""Pure normalization, provenance and fail-closed policy readiness."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

VERSION = '0.5.0'
TZ = ZoneInfo('Europe/Prague')
BAD_STATES = {'unknown', 'unavailable', 'none', ''}

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def instant(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('A timezone offset is required')
    return dt

def season_context(at):
    local = instant(at).astimezone(TZ)
    month = local.month
    season = ('winter' if month in (12, 1, 2) else 'spring' if month in (3, 4, 5)
              else 'summer' if month in (6, 7, 8) else 'autumn')
    return {'local_date': local.date().isoformat(), 'season': season,
            'tariff_season': 'winter' if month >= 10 or month <= 3 else 'summer',
            'timezone': str(TZ)}

def normalize(spec, state):
    base = {'entity_id': spec['entity_id'], 'unit': spec['unit'], 'value': None,
            'quality': 'missing', 'source_freshness': 'not_proven_by_poll'}
    if state is None:
        return base
    raw = str(state.get('state', 'unknown'))
    attrs = state.get('attributes', {})
    base.update(raw_state=raw, last_changed=state.get('last_changed'),
                last_updated=state.get('last_updated'), last_reported=state.get('last_reported'))
    if raw.lower() in BAD_STATES:
        base['quality'] = raw.lower() or 'unknown'
        return base
    if spec['unit'] is None:
        base.update(value=raw, quality='valid')
        return base
    try:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError('non-finite value')
    except (ValueError, TypeError):
        base['quality'] = 'invalid_number'
        return base
    actual = attrs.get('unit_of_measurement')
    expected = spec['unit']
    factors = {('kW', 'W'): 1000, ('Wh', 'kWh'): .001, ('MWh', 'kWh'): 1000,
               ('CZK/kWh', 'Kč/kWh'): 1}
    if actual != expected:
        if (actual, expected) not in factors:
            base.update(quality='unit_mismatch', source_unit=actual)
            return base
        value *= factors[actual, expected]
    if (spec['min'] is not None and value < spec['min']) or (spec['max'] is not None and value > spec['max']):
        base['quality'] = 'out_of_range'
        return base
    base.update(value=value, quality='valid')
    return base

def build_sample(states, catalog, observed_at, started_at, config_hash):
    instant(observed_at)
    byid = {row['entity_id']: row for row in states}
    signals = {key: normalize(spec, byid.get(spec['entity_id'])) for key, spec in catalog.items()}
    missing = [key for key, spec in catalog.items()
               if spec['required_for_quality'] and signals[key]['quality'] != 'valid']
    return {'schema_version': 1, 'software_version': VERSION, 'config_hash': config_hash,
            'observed_at': observed_at, 'request_started_at': started_at,
            **season_context(observed_at), 'signals': signals,
            'quality': {'missing_required': missing, 'valid_count': sum(s['quality'] == 'valid' for s in signals.values()),
                        'signal_count': len(signals), 'acquisition': 'REST polling; not an atomic physical measurement',
                        'minute_sampling_not_for_breaker_protection': True}}

def forecast_payloads(states):
    """Persist only explicit energy forecasts, tariff data, and source metadata."""
    byid = {s['entity_id']: s for s in states}
    polled = byid.get('sensor.solcast_pv_forecast_api_last_polled', {}).get('state')
    for eid, s in byid.items():
        a = s.get('attributes', {})
        if eid in ('sensor.cez_indi_cenik', 'sensor.current_sell_electricity_price'):
            if eid == 'sensor.cez_indi_cenik':
                allowed = ('today', 'tomorrow', 'today_date', 'tomorrow_date', 'today_valid',
                           'tomorrow_valid', 'workday_today', 'workday_tomorrow', 'timezone', 'rates', 'status')
                payload = {k: a[k] for k in allowed if k in a}
            else:
                payload = {'unit': a.get('unit_of_measurement'), 'net_formula_verified': False,
                           'prices': {k: v for k, v in a.items() if k[:4].isdigit()}}
            yield eid, payload
        elif eid in ['sensor.solcast_pv_forecast_forecast_' + name for name in
                     ('today', 'tomorrow', 'day_3', 'day_4', 'day_5', 'day_6', 'day_7')]:
            payload = {k: a[k] for k in ('estimate', 'estimate10', 'estimate90', 'detailedForecast',
                       'detailedHourly', 'dataCorrect', 'unit_of_measurement') if k in a}
            payload.update(state=s.get('state'), ha_last_polled=polled,
                           uncertainty_calibrated=False, provider_issue_time=None)
            yield eid, payload

def readiness(settings):
    return sorted(k for k, v in settings['missing_approvals'].items() if v is None or v is False)

def evaluate(sample, settings):
    """A recorded abstention is a decision; no default targets are invented."""
    reasons = []
    if sample['quality']['missing_required']:
        reasons.append('MISSING_REQUIRED_MEASUREMENTS')
    unapproved = readiness(settings)
    if unapproved:
        reasons.append('POLICY_AND_MODEL_PARAMETERS_NOT_APPROVED')
    if not settings['ev_low_pv_rule']['enabled']:
        reasons.append('EV_LOW_PV_RULE_NOT_ENABLED')
    return {'schema_version': 1, 'at': sample['observed_at'], 'mode': 'observe_only',
            'policy_version': VERSION, 'config_hash': sample['config_hash'],
            'season': sample['season'], 'tariff_season': sample['tariff_season'],
            'status': 'collecting_baseline', 'reasons': reasons, 'missing_approvals': unapproved,
            'requested_actions': [], 'executed_actions': [], 'financial_savings_czk': None,
            'note_cs': 'Sběr důkazů. Reálné porovnání čeká na schválené parametry a kalibraci modelu.'}

def interval_energy(previous, current, seconds, reset_counter=False):
    """Never infer zero consumption or a hidden reset across a gap."""
    if previous is None or current is None or seconds <= 0 or seconds > 90:
        return None
    delta = current - previous
    if not math.isfinite(delta) or delta < 0:
        return None
    return delta
