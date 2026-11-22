"""MODBUS-02: pure read-only poll health and per-interval metrics tests."""
import importlib.util
from pathlib import Path
import unittest

from energy.modbus_observability import ModbusHealthMonitor, HEALTH_ENTITY
from test_ram_control import stamp


class ModbusDiagnosticsTests(unittest.TestCase):
    def health(self,at,count,groups=None):
        a={'overrun_count':count,'success_rate':100.,
           'average_poll_duration_ms':680.,'max_poll_duration_ms':1600.,
           'quarantined_registers':0}
        if groups is not None:a['poll_interval_diagnostics']=groups
        return [{'entity_id':HEALTH_ENTITY,'state':'Healthy',
                 'last_reported':stamp(at),'attributes':a}]

    def test_overrun_delta_counts_but_does_not_trigger_physical_action(self):
        diag=ModbusHealthMonitor()
        g={'1.0':{'configured_groups':['FAST'],'p95_ms':900,'p99_ms':1600,
                   'total_overruns':19,'window_count':64},
           '5.0':{'configured_groups':['MEDIUM','DEFAULT'],'p95_ms':800,
                   'total_overruns':0,'window_count':64}}
        diag.observe(self.health(0,100,g),stamp(0),0)
        self.assertEqual(diag.snapshot()['status'],'ok')
        self.assertIsNone(diag.snapshot()['overrun_delta_latest'])
        diag.observe(self.health(60,112,g),stamp(60),60)
        x=diag.snapshot()
        self.assertEqual(x['overrun_delta_latest'],12)
        self.assertEqual(x['overrun_rate_per_minute_latest'],12.)
        self.assertEqual(x['group_latency_stats']['1.0']['p99_ms'],1600)
        self.assertEqual(x['group_latency_stats']['5.0']['configured_groups'],
                         ['MEDIUM','DEFAULT'])
        self.assertEqual(x['quarantined_registers'],0)

    def test_counter_reset_does_not_create_negative_delta(self):
        d=ModbusHealthMonitor()
        d.observe(self.health(0,50),stamp(0),0)
        d.observe(self.health(10,3),stamp(10),10)
        self.assertIsNone(d.snapshot()['overrun_delta_latest'])
        self.assertEqual(d.snapshot()['diagnostic_counter_resets'],1)

    def test_missing_health_cannot_be_treated_as_zero_overruns(self):
        d=ModbusHealthMonitor()
        d.observe([],stamp(0),0)
        self.assertEqual(d.snapshot()['status'],'unavailable')
        self.assertIsNone(d.snapshot().get('overrun_count_total'))
        d.observe(self.health(10,4),stamp(10),10)
        self.assertEqual(d.snapshot()['status'],'ok')
        self.assertEqual(d.snapshot()['group_latency_source'],'not_in_upstream_diagnostics')


if __name__=='__main__':
    unittest.main()
