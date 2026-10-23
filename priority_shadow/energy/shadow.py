"""Read-only EV scheduling scenarios, issued with their forecast provenance.

The projection is deliberately limited to house load and EV charging. It does
not model battery dispatch, export revenue, or an actionable phase-current cap.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from statistics import median
import math
import re

from .core import TZ, instant
from .pricing import valid
from .store import pack, unpack


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS shadow_plans(
        issued_at TEXT PRIMARY KEY, payload BLOB NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS shadow_reviews(
        week_start TEXT PRIMARY KEY, payload BLOB NOT NULL)''')


def _value(sample, key, now):
    signal = sample.get('signals', {}).get(key, {})
    if signal.get('quality') != 'valid':
        return None
    try:
        age = (now - instant(signal['last_reported'])).total_seconds()
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return signal.get('value') if -30 <= age <= 1800 else None


def _hourly_house_profile(store, now):
    """Covered, observed house power excluding EV, grouped by local hour/day type."""
    cutoff = (now.astimezone(TZ).date() - timedelta(days=21)).isoformat()
    rows = store.db.execute('SELECT payload FROM samples WHERE day>=? AND available_at<=? ORDER BY available_at',
                            (cutoff, now.isoformat()))
    bins = defaultdict(lambda: [0., 0., None])
    previous = None
    for (blob,) in rows:
        sample = unpack(blob)
        at = instant(sample['observed_at'])
        if previous:
            old, old_at = previous
            seconds = (at - old_at).total_seconds()
            house = _value(old, 'house_power', old_at)
            ev = _value(old, 'ev_power', old_at)
            workday_signal = old.get('signals', {}).get('workday', {})
            workday = workday_signal.get('value') if workday_signal.get('quality') == 'valid' else None
            if (0 < seconds <= 90 and valid(house) and valid(ev) and
                    house >= 0 and 0 <= ev <= house + 100 and workday in ('on', 'off')):
                start, end = old_at.timestamp(), at.timestamp()
                while start < end:
                    hour = math.floor(start / 3600) * 3600
                    stop = min(end, hour + 3600)
                    local = datetime.fromtimestamp(start, TZ)
                    if local.date() < now.astimezone(TZ).date():
                        row = bins[hour]
                        row[0] += max(0., house - ev) * (stop - start)
                        row[1] += stop - start
                        row[2] = workday == 'on'
                    start = stop
        previous = (sample, at)
    groups = defaultdict(list)
    for hour, (energy, covered, workday) in bins.items():
        if covered < 3240:
            continue
        local = datetime.fromtimestamp(hour, TZ)
        groups[(workday, local.hour)].append((local.date(), energy / covered / 1000))
    profile = {}
    for (workday, hour), values in groups.items():
        if len({day for day, _ in values}) >= 2:
            profile[(workday, hour)] = round(median(v for _, v in values), 4)
    return profile


def _deadline(now, hhmm):
    if not isinstance(hhmm, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hhmm):
        return None
    hour, minute = map(int, hhmm.split(':'))
    local = now.astimezone(TZ)
    for days in (0, 1, 2):
        day = local.date() + timedelta(days=days)
        candidate = datetime.combine(day, time(hour, minute), TZ)
        # A wall-clock time in the spring DST gap is not a real deadline.
        if candidate.astimezone(timezone.utc).astimezone(TZ).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if candidate > now and candidate - now <= timedelta(hours=30):
            return candidate
    return None


def _actual(store, now, hours=48):
    cutoff = (now - timedelta(hours=hours)).isoformat()
    rows = store.db.execute('SELECT payload FROM samples WHERE available_at>=? AND available_at<=? ORDER BY available_at',
                            (cutoff, now.isoformat()))
    bins = defaultdict(lambda: [0., 0., 0.])
    previous = None
    for (blob,) in rows:
        sample = unpack(blob)
        at = instant(sample['observed_at'])
        if previous:
            old, old_at = previous
            duration = (at - old_at).total_seconds()
            house, ev = _value(old, 'house_power', old_at), _value(old, 'ev_power', old_at)
            if 0 < duration <= 90 and valid(house) and valid(ev) and house >= 0 and ev >= 0:
                a, end = old_at.timestamp(), at.timestamp()
                while a < end:
                    slot = math.floor(a / 900) * 900
                    stop = min(end, slot + 900)
                    entry = bins[slot]
                    entry[0] += house * (stop - a)
                    entry[1] += ev * (stop - a)
                    entry[2] += stop - a
                    a = stop
        previous = (sample, at)
    return [{'at': datetime.fromtimestamp(slot, timezone.utc).isoformat(),
             'house_kw': round(house / coverage / 1000, 3),
             'ev_kw': round(ev / coverage / 1000, 3)}
            for slot, (house, ev, coverage) in sorted(bins.items()) if coverage >= 675]


def _latest(store):
    ensure_schema(store.db)
    row = store.db.execute('SELECT payload FROM shadow_plans ORDER BY issued_at DESC LIMIT 1').fetchone()
    return unpack(row[0]) if row else None


def _weekly_review(store, now):
    """Once per completed local week, compare archived suggestions with readings.

    Difference is descriptive, never a counterfactual saving or a model score:
    the suggestion was not applied and the car's future presence was unknown.
    """
    local = now.astimezone(TZ)
    week_end = datetime.combine(local.date()-timedelta(days=local.weekday()), time(), TZ)
    week_start = week_end-timedelta(days=7)
    key = week_start.date().isoformat()
    row = store.db.execute('SELECT payload FROM shadow_reviews WHERE week_start=?', (key,)).fetchone()
    if row:
        return unpack(row[0])
    start_utc, end_utc = week_start.astimezone(timezone.utc), week_end.astimezone(timezone.utc)
    # One frozen suggestion per day prevents overlapping replans from being
    # counted repeatedly in a weekly comparison.
    by_day = {}
    for (blob,) in store.db.execute('SELECT payload FROM shadow_plans WHERE issued_at>=? AND issued_at<? ORDER BY issued_at',
                                    (start_utc.isoformat(), end_utc.isoformat())):
        plan = unpack(blob)
        by_day[instant(plan['issued_at']).astimezone(TZ).date().isoformat()] = plan
    pairs = []
    if by_day:
        observed = {r['at']: r for r in _actual(store, end_utc, hours=169)}
        for plan in by_day.values():
            for slot in plan['slots']:
                if not start_utc <= instant(slot['at']) < end_utc:
                    continue
                actual = observed.get(slot['at'])
                if actual:
                    pairs.append((slot, actual))
    review = {'week_start': key, 'week_end': week_end.date().isoformat(),
              'created_at': now.isoformat(), 'scenarios': len(by_day), 'covered_slots': len(pairs),
              'mode': 'observe_only', 'savings_czk': None,
              'status': 'descriptive' if len(pairs) >= 12 else 'insufficient_overlap',
              'mean_absolute_house_difference_kw': round(sum(abs(s['planned_house_kw']-a['house_kw']) for s,a in pairs)/len(pairs), 3) if len(pairs) >= 12 else None,
              'note': 'Odchylka nevykonaného návrhu od reality; neprokazuje možnou úsporu ani přesnost předpovědi.'}
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO shadow_reviews VALUES(?,?)', (key, pack(review)))
    return review


def _candidate(store, now, cfg, pv, tariff):
    parameters = cfg.get('shadow_ev', {})
    ratio = parameters.get('ac_kwh_per_soc_pct')
    power = parameters.get('charge_power_kw')
    ready = parameters.get('ready_by_local')
    if not valid(ratio) or not .25 <= ratio <= 1.5 or not valid(power) or not 1 <= power <= 11.04 or not ready:
        return {'status': 'needs_configuration', 'missing': ['shadow_ev.ac_kwh_per_soc_pct',
                'shadow_ev.charge_power_kw', 'shadow_ev.ready_by_local'], 'note': 'Parametry auta nejsou ověřené.'}
    deadline = _deadline(now, ready)
    if deadline is None:
        return {'status': 'invalid_deadline', 'note': 'Čas odjezdu není v nadcházejících 30 hodinách.'}
    row = store.db.execute('SELECT payload FROM samples WHERE available_at<=? ORDER BY available_at DESC LIMIT 1',
                           (now.isoformat(),)).fetchone()
    if not row:
        return {'status': 'collecting'}
    sample = unpack(row[0])
    if (now - instant(sample['observed_at'])).total_seconds() > 300:
        return {'status': 'stale_measurements'}
    connected = _value(sample, 'ev_connected', now)
    if connected != 'on':
        return {'status': 'car_not_confirmed_connected' if connected == 'off' else 'stale_connection'}
    soc = _value(sample, 'ev_soc', now)
    target = _value(sample, 'ev_target_soc', now)
    if not all(valid(x) for x in (soc, target)) or not 0 <= soc <= 100 or not 0 <= target <= 100:
        return {'status': 'missing_soc_or_target'}
    need = (target - soc) * ratio
    if need <= 0:
        return {'status': 'target_met', 'soc': soc, 'target_soc': target}
    profile = _hourly_house_profile(store, now)
    if not profile:
        return {'status': 'collecting_house_profile', 'note': 'Chybí pokryté historické hodiny domu bez auta.'}
    forecast = {}
    origins = set()
    for day in ('today', 'tomorrow'):
        part = pv.get('upcoming', {}).get(day, {})
        try:
            available = instant(part['forecast_available_at'])
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if available > now:
            continue
        for h in part.get('hourly', []):
            try:
                start = instant(h['start'])
                value = h['corrected_kwh']
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if valid(value) and value >= 0:
                forecast[int(start.timestamp() // 3600)] = value
                origins.add(part['forecast_available_at'])
    # Solcast's hourly row for an already-started hour is omitted by the
    # forecast adapter. Start at the next complete forecast hour.
    first = math.ceil(now.timestamp() / 3600) * 3600
    slots = []
    for ts in range(first, int(deadline.timestamp()), 900):
        dt = datetime.fromtimestamp(ts, timezone.utc)
        local = dt.astimezone(TZ)
        base = profile.get((local.weekday() < 5, local.hour))
        pv_kwh = forecast.get(ts // 3600)
        price = tariff.price(ts)
        if base is None or pv_kwh is None or price is None:
            return {'status': 'missing_forecast_profile_or_tariff',
                    'note': 'Pro celé dostupné období nejsou známé profil domu, FVE a cena.'}
        surplus = max(0., pv_kwh / 4 - base / 4)
        slots.append({'at': dt.isoformat(), 'base_kw': base, 'pv_kwh': pv_kwh / 4,
                      'buy_price': price, 'surplus_kwh': surplus, 'planned_ev_kwh': 0.})
    if need > len(slots) * power / 4 + 1e-6 or not slots:
        return {'status': 'insufficient_window', 'needed_ac_kwh': round(need, 3)}
    remaining = need
    # Sort the PV-covered and purchased portions separately. In particular,
    # negative purchase prices can beat an assumed zero-price PV portion.
    # Export opportunity and battery dispatch are unknown; no savings claim.
    segments = []
    for slot in slots:
        solar = min(power / 4, slot['surplus_kwh'])
        segments.append((0., slot['at'], slot, solar))
        segments.append((slot['buy_price'], slot['at'], slot, power / 4 - solar))
    for _, _, slot, available in sorted(segments, key=lambda row: (row[0], row[1])):
        amount = min(remaining, available)
        slot['planned_ev_kwh'] += amount
        remaining -= amount
        if remaining < 1e-8:
            break
    if remaining > 1e-6:
        return {'status': 'insufficient_window'}
    return {'status': 'scenario', 'issued_at': now.isoformat(), 'ready_by': deadline.isoformat(),
            'soc': soc, 'target_soc': target, 'needed_ac_kwh': round(need, 3),
            'forecast_available_at': sorted(origins), 'scope': 'EV and estimated house load only',
            'assumption': 'Car remains connected until ready_by; weekday is a proxy for future Workday; battery dispatch and export revenue unknown',
            'mode': 'observe_only', 'actions_executed': 0,
            'slots': [{'at': s['at'], 'base_kw': s['base_kw'],
                       'planned_house_kw': round(s['base_kw'] + s['planned_ev_kwh'] * 4, 3),
                       'planned_ev_kw': round(s['planned_ev_kwh'] * 4, 3),
                       'pv_forecast_kw': round(s['pv_kwh'] * 4, 3),
                       'buy_price': s['buy_price']} for s in slots]}


def build(store, now, cfg, pv, tariff):
    """Create at most one immutable scenario per hour; show real observations alongside it."""
    previous = _latest(store)
    reuse = previous is not None and (
        int(instant(previous['issued_at']).timestamp() // 3600) == int(now.timestamp() // 3600)
    )
    if reuse:
        row = store.db.execute('SELECT payload FROM samples WHERE available_at<=? ORDER BY available_at DESC LIMIT 1',
                               (now.isoformat(),)).fetchone()
        sample = unpack(row[0]) if row else {}
        connection = _value(sample, 'ev_connected', now)
        soc = _value(sample, 'ev_soc', now)
        target = _value(sample, 'ev_target_soc', now)
        reuse = (connection == 'on' and valid(soc) and valid(target) and soc < target
                 and target == previous['target_soc'])
    current = _candidate(store, now, cfg, pv, tariff) if not reuse else previous
    if current['status'] == 'scenario' and current is not previous:
        with store.db:
            store.db.execute('INSERT OR IGNORE INTO shadow_plans VALUES(?,?)', (current['issued_at'], pack(current)))
    return {'status': current['status'], 'candidate': current, 'actual': _actual(store, now),
            'weekly_review': _weekly_review(store, now),
            'note': 'Stínový scénář. Křivka není změřená úspora; budoucí připojení auta ani výkon baterie nejsou zaručené.'}
