"""MODBUS-02 vendor-neutral interval monitor regression, no HA imports."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MONITOR = ROOT / 'ops' / 'solax_modbus' / 'poll_interval_monitor.py'


def module():
    spec = importlib.util.spec_from_file_location('poll_monitor_test', MONITOR)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PollGroupTimingTests(unittest.TestCase):
    def test_merged_slow_groups_and_p95_p99(self):
        mon = module().PollIntervalMonitor()
        for i in range(70):
            mon.record(1, 1.45 if i % 4 == 0 else .63, True)
        for i in range(20):
            mon.record(5, 2.5 if i % 3 == 0 else .85, True)
        stats = mon.snapshot({'scan_interval_fast':1,'scan_interval_medium':5,
                              'scan_interval':5},now=50)
        self.assertEqual(set(stats),{'1.0','5.0'})
        a,b=stats['1.0'],stats['5.0']
        self.assertEqual(a['configured_groups'],['FAST'])
        self.assertEqual(b['configured_groups'],['MEDIUM','DEFAULT'])
        self.assertEqual(a['window_count'],64)
        self.assertEqual(a['total_cycles'],70)
        self.assertEqual(a['total_overruns'],18)
        self.assertEqual(a['p95_ms'],1450)
        self.assertEqual(a['p99_ms'],1450)
        self.assertEqual(b['total_overruns'],0)

    def test_rolling_window_and_30s_snapshot(self):
        mon = module().PollIntervalMonitor()
        mon.record(1, .6, True)
        a = mon.snapshot({'scan_interval_fast':1},now=0)
        mon.record(1,1.8,False)
        self.assertEqual(mon.snapshot({},now=10),a)
        b=mon.snapshot({'scan_interval_fast':1},now=31)
        self.assertEqual(b['1.0']['total_overruns'],1)
        self.assertEqual(b['1.0']['window_success_pct'],50.0)
        self.assertEqual(b['1.0']['p99_ms'],1800)

    def test_invalid_samples_do_not_pollute(self):
        mon=module().PollIntervalMonitor()
        for interval,elapsed in [(0,1),(-1,1),(1,-1),(1,float('inf')),
                                 ('garbage',1),(1,121)]:
            mon.record(interval,elapsed,False)
        self.assertEqual(mon.snapshot({},now=0),{})


if __name__=='__main__':
    unittest.main()
