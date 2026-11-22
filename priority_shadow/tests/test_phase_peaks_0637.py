"""PEAK-01: collector 1s frames -> 5s RAM controller, all synthetic."""
import copy
import unittest

from energy import night
from energy.phase_peaks import BREAKER_A, PhasePeakWindow
from energy.priority_collection import SnapshotCollector
from energy.isolated_control import MemoryControl
from test_ram_control import data, result, stamp
from test_control_journal import patch_value


class PeakWindowTests(unittest.TestCase):
    def states(self, second, l2=None):
        states=data(stamp(second))
        if l2 is not None:
            patch_value(states,night.IDS['grid_l2_a'],l2)
        return states

    def test_1_second_spike_between_control_ticks_is_preserved(self):
        collector=PhasePeakWindow()
        for sec in range(6):
            collector.observe(self.states(sec,20.3 if sec==2 else 16),stamp(sec),sec)
        peak=collector.snapshot(5)
        self.assertEqual(peak['status'],'ok')
        self.assertEqual(peak['maxima']['L2']['a'],20.3)
        self.assertEqual(peak['maxima']['L2']['at'],stamp(2))
        self.assertEqual(peak['phase_report_counts']['L2'],6)
        self.assertEqual(peak['over_limit_phases'],[])
        self.assertEqual(BREAKER_A,25.0)
        self.assertEqual(collector.snapshot(14)['status'],'unverified')

    def test_duplicate_last_reported_cannot_invent_new_samples(self):
        window=PhasePeakWindow()
        same=self.states(0)
        for sec in range(5):
            window.observe(same,stamp(sec),sec)
        snap=window.snapshot(4)
        self.assertEqual(snap['phase_report_counts'],{'L1':1,'L2':1,'L3':1})
        self.assertEqual(snap['collector_frames'],5)

    def test_unavailable_invalid_age_wrong_unit_and_missed_phase_fail_closed(self):
        window=PhasePeakWindow()
        states=self.states(0)
        l2=next(s for s in states if s['entity_id']==night.IDS['grid_l2_a'])
        l2['attributes']['unit_of_measurement']='W'
        window.observe(states,stamp(0),0)
        self.assertEqual(window.snapshot(0)['unverified_phases'],['L2'])
        states=self.states(1)
        next(s for s in states if s['entity_id']==night.IDS['grid_l2_a'])['state']='unavailable'
        window.observe(states,stamp(1),1)
        self.assertEqual(window.snapshot(1)['status'],'unverified')
        states=self.states(2)
        next(s for s in states if s['entity_id']==night.IDS['grid_l2_a'])['last_reported']=stamp(-6)
        window.observe(states,stamp(2),2)
        self.assertEqual(window.snapshot(2)['status'],'unverified')
        window.observe(self.states(3),stamp(3),3)
        self.assertEqual(window.snapshot(3)['status'],'ok')
        window.reset()
        self.assertEqual(window.snapshot(3)['status'],'unverified')

    def test_collector_handoff_uses_atomic_cache_and_does_not_modify_states(self):
        collector=SnapshotCollector(None)
        states=self.states(0)
        before=copy.deepcopy(states)
        collector.phase_peaks.observe(states,stamp(0),0)
        # Fake monotonic to avoid artificial staleness.
        with unittest.mock.patch('energy.priority_collection.time.monotonic',return_value=0.2):
            with collector.condition:
                collector.states=states
                collector.received=0
                collector.receipt={'sequence':1,'received_at':stamp(0)}
            handoff=collector.priority_states()
        self.assertEqual(states,before)
        self.assertEqual(handoff[0]['collection_phase_peaks']['status'],'ok')
        self.assertEqual(handoff[0]['collection_snapshot']['sequence'],1)
        collector.failed(RuntimeError('synthetic'))
        self.assertEqual(collector.phase_peaks.snapshot(.2)['status'],'unverified')

    def test_end_to_end_highwater_and_over_25a_virtual_stop(self):
        window=PhasePeakWindow()
        memory=MemoryControl()
        try:
            def step(t,spike=None):
                # Collector observes all 1s frames while RAM executes at t=0,5,10,15.
                for sec in range(max(0,t-4),t+1):
                    window.observe(self.states(sec,spike if sec==t-2 else None),stamp(sec),float(sec))
                states=self.states(t)
                states[0]['collection_phase_peaks']=window.snapshot(float(t))
                current,journal=memory.step(states,result(stamp(t)),stamp(t))
                return current,journal
            _,first=step(0)
            _,second=step(5)
            self.assertGreater(second['session']['target_ac_w'],0)
            _,normal=step(10,20.3)
            sample=normal['recent_samples'][0]
            self.assertEqual(sample['phase_peak_window']['maxima']['L2']['a'],20.3)
            self.assertEqual(normal['session']['statistics']['measured_phase_max_a']['L2'],20.3)
            self.assertNotIn('observed_phase_current_above_25a',sample['input_errors'])
            _,blocked=step(15,25.4)
            self.assertEqual(blocked['session']['target_ac_w'],0)
            self.assertIn('observed_phase_current_above_25a',blocked['recent_samples'][0]['input_errors'])
            self.assertEqual(blocked['session']['statistics']['measured_phase_max_a']['L2'],25.4)
            self.assertGreaterEqual(blocked['session']['statistics']['collector_peak_exceedance_intervals'],1)
            self.assertEqual(blocked['device_actions'],0)
            self.assertEqual(blocked['persistent_writes'],0)
        finally:
            memory.close()


if __name__=='__main__':
    unittest.main()
