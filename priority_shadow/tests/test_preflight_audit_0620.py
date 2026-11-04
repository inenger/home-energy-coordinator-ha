"""Synthetic reproduction of persisted manual-submode preflight blocking."""
import unittest
from energy.isolated_control import MemoryControl
from energy import control_journal as legacy
from test_ram_control import data,result,stamp
from test_control_journal import patch_value

class PreflightAuditTests(unittest.TestCase):
 def test_stored_force_charge_blocks_even_with_backup_work_mode(self):
  memory=MemoryControl()
  try:
   for second in [0,5,10]:
    states=data(stamp(second))
    patch_value(states,legacy.MODE,'Back Up Mode')
    patch_value(states,legacy.FORCE,'Force Charge')
    current,journal=memory.step(states,result(stamp(second)),stamp(second))
    self.assertGreater(current['selected']['battery_ac_w'],0)
    self.assertEqual(journal['session']['target_ac_w'],0)
    self.assertFalse(journal['session']['owned'])
    self.assertEqual(journal['recent_samples'][0]['input_errors'],['unowned_manual_charge_or_discharge'])
   self.assertIsNone(journal['session'].get('started_at'))
  finally:memory.close()
