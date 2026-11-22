"""PEAK-02 regression: phase freshness independent from 8s high-water."""
import unittest
from energy.phase_peaks import PhasePeakWindow
from energy import night
from test_ram_control import data, stamp
from test_control_journal import patch_value
from energy.isolated_control import MemoryControl
from test_ram_control import result


class FreshnessTests(unittest.TestCase):
    def sample(self, sec, l2=16.0):
        rows = data(stamp(sec))
        patch_value(rows, night.IDS['grid_l2_a'], l2)
        return rows

    def test_two_missing_seconds_grace_three_seconds_blocks(self):
        w = PhasePeakWindow()
        fresh = self.sample(0)
        w.observe(fresh,stamp(0),0)
        for second in (1,2):
            w.observe(fresh,stamp(second),second)
            p=w.snapshot(float(second))
            self.assertEqual(p['status'],'ok')
            self.assertEqual(p['phase_quality']['L2']['quality'],'held_fresh_prior')
            self.assertAlmostEqual(p['last_report_age_s']['L2'],float(second))
        at=3.1
        p=w.snapshot(at)
        self.assertEqual(p['status'],'unverified')
        self.assertEqual(p['phase_quality']['L2']['quality'],'stale')
        self.assertIn('L2',p['unverified_phases'])
        self.assertEqual(p['maxima']['L2']['a'],16.0)  # highwater still retained
        w.observe(self.sample(4),stamp(4),4)
        self.assertEqual(w.snapshot(4)['status'],'ok')
        self.assertEqual(w.snapshot(4)['phase_quality']['L2']['quality'],'fresh')

    def test_only_one_phase_missing_then_recovery(self):
        w=PhasePeakWindow()
        w.observe(self.sample(0),stamp(0),0)
        l2=night.IDS['grid_l2_a']
        for sec in (1,2,3,4):
            x=self.sample(sec)
            x=[r for r in x if r['entity_id']!=l2]
            w.observe(x,stamp(sec),sec)
        p=w.snapshot(4.0)
        self.assertEqual(p['phase_quality']['L1']['quality'],'fresh')
        self.assertEqual(p['phase_quality']['L2']['quality'],'stale')
        self.assertEqual(p['phase_quality']['L3']['quality'],'fresh')
        self.assertEqual(p['unverified_phases'],['L2'])
        self.assertEqual(p['maxima']['L2']['a'],16.0)
        w.observe(self.sample(5,20.3),stamp(5),5)
        p=w.snapshot(5.0)
        self.assertEqual(p['status'],'ok')
        self.assertEqual(p['maxima']['L2']['a'],20.3)
        self.assertEqual(p['max_report_gap_s']['L2'],5.0)
        self.assertEqual(p['missed_reports_inferred']['L2'],4)

    def test_physical_age_already_older_than_threshold_fails_even_when_new(self):
        w=PhasePeakWindow()
        x=self.sample(0)
        for s in x:
            if s['entity_id']==night.IDS['grid_l2_a']:
                s['last_reported']=stamp(-3)
        w.observe(x,stamp(0),0)
        p=w.snapshot(0.01)
        self.assertEqual(p['status'],'unverified')
        self.assertEqual(p['phase_quality']['L2']['quality'],'stale')
        self.assertGreater(p['last_report_age_s']['L2'],3.0)

    def test_source_duplicate_does_not_refresh_last_report_age(self):
        w=PhasePeakWindow()
        x=self.sample(0)
        w.observe(x,stamp(0),0)
        for i in (1,2,3):
            w.observe(x,stamp(i),float(i))
        p=w.snapshot(3.1)
        self.assertEqual(p['status'],'unverified')
        self.assertEqual(p['phase_report_counts']['L2'],1)
        self.assertEqual(p['phase_quality']['L2']['last_collector_status'],'duplicate_report')

    def test_daytime_2point5_second_collection_no_false_report_misses(self):
        w=PhasePeakWindow()
        for i in (0,2.5,5.0,7.5):
            # fixture stamp uses whole seconds; manually create ISO with milliseconds
            from datetime import timedelta
            from energy.core import instant
            source=(instant(stamp(0))+timedelta(seconds=i)).isoformat()
            x=self.sample(0)
            for row in x:row['last_reported']=source
            w.observe(x,source,i,expected_period_s=2.5)
        p=w.snapshot(7.5)
        self.assertEqual(p['status'],'ok')
        self.assertEqual(p['missed_reports_inferred'],{'L1':0,'L2':0,'L3':0})
        self.assertEqual(p['max_report_gap_s'],{'L1':2.5,'L2':2.5,'L3':2.5})

    def test_ram_guard_uses_freshness_not_old_8s_maximum(self):
        w=PhasePeakWindow()
        ram=MemoryControl()
        try:
            for i in (0,5):
                x=self.sample(i)
                w.observe(x,stamp(i),float(i))
                x[0]['collection_phase_peaks']=w.snapshot(float(i))
                current,j=ram.step(x,result(stamp(i)),stamp(i))
            x=self.sample(10)
            # At 10 secs, phases L1/L3 freshly reported but L2 not.
            missing=night.IDS['grid_l2_a']
            w.observe([r for r in x if r['entity_id']!=missing],stamp(10),10.)
            x[0]['collection_phase_peaks']=w.snapshot(10.)
            current,j=ram.step(x,result(stamp(10)),stamp(10))
            self.assertEqual(j['session']['target_ac_w'],0)
            self.assertIn('fast_phase_peak_window_unverified',j['recent_samples'][0]['input_errors'])
            self.assertEqual(j['device_actions'],0)
        finally:
            ram.close()


if __name__=='__main__':
    unittest.main()
