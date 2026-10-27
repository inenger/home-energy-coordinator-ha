import unittest
from test_phase_064 import samples
from energy.phase_budget import estimate,checked,limits
class EnvelopeRegressions(unittest.TestCase):
 def synthetic(self,large=False):
  rows=samples()
  for j,row in enumerate(rows):
   base=(6200 if j%2 else 100) if large else (2530 if j%10==0 else 230)
   inv=0 if large else (201 if j%10==0 else 0)
   for i in (1,2,3):
    p=row['inputs'];g=inv-base-3680
    for k,v in {f'grid_l{i}_w':g,f'inverter_l{i}_w':inv,f'grid_l{i}_a':abs(g)/(230*.99)}.items():p[k]['value']=v
  return rows
 def test_pf_filter_cannot_hide_house_steps(self):
  rows=self.synthetic();budget=estimate(rows,rows[-1]['at'])
  self.assertGreaterEqual(min(budget['reserve_a']),10)
  self.assertEqual(budget['step_samples'],[99]*3)
 def test_impossible_observed_budget_never_falls_back(self):
  rows=self.synthetic(True);budget=estimate(rows,rows[-1]['at'])
  self.assertEqual(budget['status'],'observed_steps_exceed_budget')
  self.assertTrue(budget['blocking'])
  with self.assertRaises(ValueError):checked(budget)
  with self.assertRaises(ValueError):limits([230]*3,budget)
