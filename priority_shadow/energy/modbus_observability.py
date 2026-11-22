"""Read-only rolling SolaX communication diagnostics; no polling or writes.

One snapshot per existing HA collector request; groups are reported by
*actual interval*, so medium+default both 5 s may share a physical group.
"""
import math
from .core import instant

HEALTH_ENTITY = 'sensor.solax_inverter_communication_health'

class ModbusHealthMonitor:
    def __init__(self):
        self.last = None
        self.last_counter = None
        self.last_mono = None
        self.reset_count = 0
        self.latest_delta = None

    def observe(self, states, at, mono):
        state = next((s for s in states if s.get('entity_id') == HEALTH_ENTITY), None)
        if not state or state.get('snapshot_error'):
            self.last = {'status': 'unavailable', 'reason': 'missing_health_entity'}
            return
        attrs = state.get('attributes') or {}
        val = state.get('state')
        try:
            timestamp = instant(state.get('last_reported'))
            age = (instant(at)-timestamp).total_seconds()
        except (ValueError, TypeError, AttributeError):
            age = None
        if age is None or age < 0 or age > 15:
            self.last = {'status': 'unavailable', 'reason': 'stale_health_report',
                         'last_report_age_s':round(age,2) if age is not None else None}
            return
        counter = attrs.get('overrun_count')
        if not isinstance(counter,(int,float)) or not math.isfinite(counter) or counter < 0:
            counter = None
        delta = None
        rate = None
        if counter is not None and self.last_counter is not None and self.last_mono is not None:
            if counter < self.last_counter:
                self.reset_count += 1
            else:
                delta = int(counter - self.last_counter)
                elapsed = mono-self.last_mono
                if elapsed > 0:
                    rate = round(delta*60/elapsed,2)
        if counter is not None:
            self.last_counter = counter
            self.last_mono = mono
        groups = attrs.get('poll_interval_diagnostics')
        if not isinstance(groups, dict):
            groups = None
        self.last = {
            'status': 'ok' if val == 'Healthy' else 'degraded',
            'communication_health': val,
            'last_report_age_s': round(age,2),
            'success_rate_pct': attrs.get('success_rate'),
            'avg_poll_duration_ms': attrs.get('average_poll_duration_ms'),
            'max_poll_duration_ms': attrs.get('max_poll_duration_ms'),
            'overrun_count_total': counter,
            'overrun_delta_latest': delta,
            'overrun_rate_per_minute_latest': rate,
            'diagnostic_counter_resets': self.reset_count,
            'quarantined_registers': attrs.get('quarantined_registers'),
            'group_latency_stats': groups,
            'group_latency_source': ('solax_modbus_interval_bucket_30s' if groups is not None else 'not_in_upstream_diagnostics'),
        }

    def snapshot(self):
        return dict(self.last) if self.last is not None else {'status':'not_yet_collected'}
