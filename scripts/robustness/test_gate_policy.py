"""Brána nesmí vydat skipped/expectedFailure za důkaz opravy."""
import contextlib,io,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import verify_robustness as gate
class GatePolicy(unittest.TestCase):
 def invoke(self,kind):
  class Case(unittest.TestCase):
   def runTest(self):
    if kind=='skip':self.skipTest('synthetic disabled regression')
    if kind=='expected':self.fail('synthetic known defect')
  if kind=='expected':Case.runTest=unittest.expectedFailure(Case.runTest)
  suite=unittest.TestSuite(Case()for _ in range(26))if kind!='empty'else unittest.TestSuite()
  with patch.object(gate,'MODULES',('synthetic',)),patch.object(gate.unittest.defaultTestLoader,'loadTestsFromName',return_value=suite),patch.object(sys,'argv',['verify_robustness','--repetitions','1']),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
   return gate.main()
 def test_completed_contracts_are_accepted(self):self.assertEqual(self.invoke('pass'),0)
 def test_disabled_contracts_are_rejected(self):self.assertEqual(self.invoke('skip'),1)
 def test_known_defects_are_rejected(self):self.assertEqual(self.invoke('expected'),1)
 def test_empty_suite_is_rejected(self):self.assertEqual(self.invoke('empty'),1)
if __name__=='__main__':unittest.main()
