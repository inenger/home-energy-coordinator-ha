"""Read-only SolaX Modbus per-*interval* poll duration instrumentation.

Independent of Home Assistant runtime; one bounded rolling sample window.
MEDIUM and DEFAULT intentionally merge if both are configured at 5 seconds:
the vendor hub schedules by numeric period, not symbolic scan-group name.
"""
from collections import deque
from math import ceil, isfinite
import time


class PollIntervalMonitor:
    def __init__(self, history=64, refresh_seconds=30.0):
        self.groups = {}
        self.history = history
        self.refresh_seconds = refresh_seconds
        self.last_summary = {}
        self.last_summary_at = float('-inf')

    def record(self, interval_s, elapsed_s, successful):
        try:
            period = float(interval_s)
            elapsed = float(elapsed_s)
        except (ValueError, TypeError):
            return
        if not (isfinite(period) and isfinite(elapsed) and 0 < period < 3600 and 0 <= elapsed < 120):
            return
        key = round(period, 3)
        bucket = self.groups.setdefault(key, {
            'durations_ms': deque(maxlen=self.history),
            'outcomes': deque(maxlen=self.history),
            'total_cycles': 0,
            'total_overruns': 0,
        })
        bucket['durations_ms'].append(round(elapsed * 1000))
        bucket['outcomes'].append(bool(successful))
        bucket['total_cycles'] += 1
        if elapsed >= period:
            bucket['total_overruns'] += 1

    def snapshot(self, config, now=None):
        """Refresh only every 30 s to avoid extra attributes churn in Recorder."""
        if now is None:
            now = time.monotonic()
        if now-self.last_summary_at < self.refresh_seconds:
            return self.last_summary
        names = {}
        for label, option in [('FAST','scan_interval_fast'),
                              ('MEDIUM','scan_interval_medium'),
                              ('DEFAULT','scan_interval')]:
            try:
                period = round(float(config.get(option, 5.0)), 3)
            except (ValueError, TypeError):
                continue
            names.setdefault(period, []).append(label)
        result = {}
        for interval_s, bucket in sorted(self.groups.items()):
            nums = sorted(bucket['durations_ms'])
            n = len(nums)
            if not n:
                continue
            def percentile(p):
                return nums[max(0,ceil(n*p)-1)]
            result[str(interval_s)] = {
                'interval_s': interval_s,
                'configured_groups': names.get(interval_s, []),
                'window_count': n,
                'mean_ms': round(sum(nums)/n),
                'p95_ms': percentile(.95),
                'p99_ms': percentile(.99),
                'max_ms': nums[-1],
                'window_success_pct': round(sum(bucket['outcomes'])*100/n, 1),
                'total_cycles': bucket['total_cycles'],
                'total_overruns': bucket['total_overruns'],
                'overrun_rate_window_pct': round(sum(v>=interval_s*1000 for v in nums)*100/n, 1),
            }
        self.last_summary = result
        self.last_summary_at = now
        return result
