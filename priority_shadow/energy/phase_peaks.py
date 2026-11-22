"""PEAK-02: bounded high-water PLUS independent per-phase freshness evidence.

This is a read-only HA report monitor, not a hard-real-time protection device.
Timestamps are from HA last_reported; repeating a value is not a new reading.
"""
import math
from .core import instant
from . import night

BREAKER_A = 25.0
LOOKBACK_S = 8.0
MAX_REPORT_AGE_S = 3.5
FRESHNESS_LIMIT_S = 3.0
PHASES = (1, 2, 3)


class PhasePeakWindow:
    def __init__(self):
        self.reset()

    def reset(self):
        self.frames = []
        self.last_report = {}
        self.latest = {}
        self.collector_count = 0

    def _prune(self, now):
        self.frames = [(at, r) for at, r in self.frames if 0 <= now-at <= LOOKBACK_S]
        if len(self.frames) > 32:
            self.frames = self.frames[-32:]

    def observe(self, states, at, mono, expected_period_s=1.0):
        """Exactly one copy per collected HA snapshot; no disk or device I/O."""
        by = {s.get('entity_id'): s for s in states}
        frame = {}
        self.collector_count += 1
        expected = max(.5, min(5.0, float(expected_period_s)))
        for i in PHASES:
            eid = night.IDS[f'grid_l{i}_a']
            state = by.get(eid)
            if not state or state.get('snapshot_error'):
                code = 'missing_or_snapshot_error'
            elif (state.get('attributes') or {}).get('unit_of_measurement') != 'A':
                code = 'wrong_unit'
            else:
                p = night.point(state, at)
                v = p['value']
                age = p.get('age_seconds')
                if p['quality'] != 'valid':
                    code = p['quality']
                elif not isinstance(age, (float, int)) or not 0 <= age <= MAX_REPORT_AGE_S:
                    code = 'stale_or_future_report'
                elif not isinstance(v, (float, int)) or not math.isfinite(v) or abs(v) > 100:
                    code = 'out_of_range'
                else:
                    source_at = p.get('last_reported')
                    try:
                        source_dt = instant(source_at)
                    except (ValueError, TypeError, AttributeError):
                        code = 'invalid_report_time'
                    else:
                        if i in self.last_report and source_dt <= self.last_report[i]:
                            code = 'duplicate_report'
                        else:
                            previous = self.last_report.get(i)
                            delta = (source_dt-previous).total_seconds() if previous else None
                            # Inferred skipped update opportunities, NOT proven device drops.
                            misses = max(0, int(math.floor(delta / expected + .25))-1) if delta is not None else 0
                            misses = min(misses, 60)
                            report = {'a': round(abs(v), 4), 'at': source_at,
                                      'entity_id': eid}
                            frame[i] = {'report': report, 'gap_s': round(delta, 3) if delta is not None else None,
                                        'inferred_missed_reports': misses}
                            self.latest[i] = {'report': report,
                                              'observed_mono': mono,
                                              'source_age_at_collection_s': float(age)}
                            self.last_report[i] = source_dt
                            code = 'new_valid_report'
            # Most recent collector-level status can be degraded; a previously
            # *fresh* valid report may be held briefly, never > 3 s.
            self.latest.setdefault(i, {}).update(last_collector_status=code,
                                                   last_collector_mono=mono)
        self.frames.append((mono, frame))
        self._prune(mono)

    def snapshot(self, now):
        self._prune(now)
        maxima = {}
        counts = {f'L{i}': 0 for i in PHASES}
        gaps = {f'L{i}': 0.0 for i in PHASES}
        misses = {f'L{i}': 0 for i in PHASES}
        for _, reports in self.frames:
            for i, r in reports.items():
                phase = f'L{i}'
                counts[phase] += 1
                x = r['report']
                if phase not in maxima or x['a'] > maxima[phase]['a']:
                    maxima[phase] = dict(x)
                if r['gap_s'] is not None:
                    gaps[phase] = max(gaps[phase], r['gap_s'])
                misses[phase] += r['inferred_missed_reports']
        ages = {}
        qualities = {}
        missing = []
        for i in PHASES:
            key = f'L{i}'
            last = self.latest.get(i, {})
            valid = last.get('report')
            if valid:
                age = max(0, now-last['observed_mono']) + last['source_age_at_collection_s']
                ages[key] = round(age, 3)
            else:
                age = None
                ages[key] = None
            status = last.get('last_collector_status', 'missing')
            if age is None:
                quality = 'missing'
            elif age > FRESHNESS_LIMIT_S:
                quality = 'stale'
            elif status == 'new_valid_report':
                quality = 'fresh'
            else:
                quality = 'held_fresh_prior'
            qualities[key] = {
                'quality': quality,
                'last_reported': valid['at'] if valid else None,
                'last_report_age_s': ages[key],
                'last_collector_status': status,
            }
            if quality in ('stale', 'missing'):
                missing.append(key)
        return {
            'status': 'unverified' if missing else 'ok',
            'breaker_a': BREAKER_A,
            'lookback_s': LOOKBACK_S,
            'freshness_limit_s': FRESHNESS_LIMIT_S,
            'collector_frames': len(self.frames),
            'phase_report_counts': counts,
            'maxima': maxima,
            'phase_quality': qualities,
            'last_report_age_s': ages,
            'max_report_gap_s': gaps,
            'missed_reports_inferred': misses,
            'unverified_phases': missing,
            'over_limit_phases': [i for i, x in maxima.items() if x['a'] > BREAKER_A],
            'basis': 'HA_last_reported_not_hardware_protection'
        }
