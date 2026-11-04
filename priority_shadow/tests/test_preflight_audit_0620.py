"""Synthetic reproduction of persisted manual-submode preflight blocking."""
import unittest
from energy.isolated_control import MemoryControl
from energy import control_journal as legacy
from test_ram_control import data,result,stamp
from test_control_journal import patch_value

class PreflightAuditTests(unittest.TestCase):
 def test_stored_force_charge_allows_takeover_with_fresh_backup_work_mode(self):
  memory=MemoryControl()
  try:
   for second in [0,5,10]:
    states=data(stamp(second))
    patch_value(states,legacy.MODE,'Back Up Mode')
    patch_value(states,legacy.FORCE,'Force Charge')
    current,journal=memory.step(states,result(stamp(second)),stamp(second))
    self.assertGreater(current['selected']['battery_ac_w'],0)
    self.assertFalse(journal['recent_samples'][0]['input_errors'])
   self.assertIsNotNone(journal['session'].get('started_at'))
   self.assertTrue(journal['session']['owned'])
   self.assertGreater(journal['session']['target_ac_w'],0)
  finally:memory.close()
