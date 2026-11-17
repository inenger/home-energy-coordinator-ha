"""WIN-01 v0.6.35: energy-driven SOC intent, never live actuation.

Synthetic fixtures only; private as-of replay is performed on RPi separately.
"""
import unittest
from datetime import datetime,timedelta,timezone

from energy.winter_soc import evaluate, POLICY
from energy.soc_planner import plan
from energy.soc_evidence import verify
from energy.soc_runtime import view
from test_soc_planner import fixture


class EnergyBalanceIntent(unittest.TestCase):
    def test_mild_november_5c_low_pv_severe_shortfall_full(self):
        now,inputs,history,versions,household=fixture(season='winter',pv=3.1642,house=1.4,ev=31.7)
        inputs.update(outdoor_c=4.9,heat_pump_w=366,priority='ev')
        d=plan(now,inputs,history,{},household,versions)
        self.assertEqual(d['winter_demand']['policy'],POLICY)
        self.assertEqual(d['winter_demand']['status'],'severe_energy_deficit')
        self.assertFalse(d['winter_demand']['cold_condition_met'])
        self.assertEqual(d['target_soc_pct'],100)
        self.assertEqual(d['desired_target_soc_pct'],100)
        self.assertIsNone(d['physical_charge_target_soc_pct'])
        self.assertEqual(d['decision_reason'],'severe_energy_deficit')
        self.assertLess(d['attainable_soc_05_pct'],100)
        self.assertEqual(d['device_actions'],0)
        self.assertFalse(d['live_ready'])
        self.assertTrue(verify(d)['verified'])
        visible=view(d)
        self.assertEqual(visible['desired_target_soc_pct'],100)
        self.assertEqual(visible['economic_target_soc_pct'],d['economic_target_soc_pct'])

    def fixture(self,*,central=10,stress=12,capacity=8,temp=5,
                complete=True,low_pv=0,central_pv=0):
        start=datetime(2026,11,17,4,tzinfo=timezone.utc)
        end=start+timedelta(hours=22)
        model={'discharge_curve':[[0,0],[20,2],[100,2+capacity]],
               'dc_cycle_efficiency':.9}
        hours=22
        row={'start':start.timestamp(),'end':end.timestamp() if complete else (end-timedelta(hours=1)).timestamp(),
             'hours':hours if complete else hours-1,
             'house_kw':(central+central_pv)/hours,'house_high_kw':(stress+low_pv)/hours,
             'pv_ac_kw':central_pv/hours,'pv_low_kw':low_pv/hours,
             'temperature_c':temp}
        return [row], {'outdoor_c':temp,'reserve_soc':20,'heat_pump_w':400},model,start,end

    def calc(self,**kwargs):
        rows,inp,model,start,end=self.fixture(**kwargs)
        return evaluate(rows,inp,model,start,end)

    def test_warm_moderate_shortfall_remains_economic(self):
        r=self.calc(central=7.9,stress=15,capacity=8,temp=5)
        self.assertEqual(r['status'],'ordinary_economic_plan')
        self.assertIsNone(r['desired_target_soc_pct'])

    def test_warm_large_central_but_low_stress_does_not_force(self):
        # Inconsistent or narrow envelope: conservative second check fails.
        r=self.calc(central=9,stress=9.2,capacity=8,temp=5)
        self.assertEqual(r['status'],'ordinary_economic_plan')
        self.assertIsNone(r['desired_target_soc_pct'])

    def test_warm_strong_shortfall_triggers_without_frost(self):
        r=self.calc(central=10,stress=12,capacity=8,temp=8)
        self.assertEqual(r['status'],'severe_energy_deficit')
        self.assertEqual(r['desired_target_soc_pct'],100)

    def test_chill_threshold_is_lower_without_energy_only_trigger(self):
        r=self.calc(central=5.0,stress=7,capacity=8,temp=-1)
        self.assertEqual(r['status'],'cold_deficit')
        self.assertEqual(r['desired_target_soc_pct'],100)

    def test_incomplete_forecast_must_never_force(self):
        r=self.calc(central=25,stress=35,capacity=8,temp=-6,complete=False)
        self.assertEqual(r['status'],'insufficient_energy_forecast')
        self.assertIsNone(r['desired_target_soc_pct'])
        self.assertFalse(r['horizon_complete'])

    def test_missing_temperature_with_strong_energy_shortfall(self):
        rows,inp,model,start,end=self.fixture(central=10,stress=12,capacity=8,temp=None)
        inp['outdoor_c']=None
        r=evaluate(rows,inp,model,start,end)
        self.assertEqual(r['temperature_source'],'no_cold_evidence')
        self.assertEqual(r['status'],'severe_energy_deficit')
        self.assertEqual(r['desired_target_soc_pct'],100)

    def test_missing_temperature_with_sufficient_energy_no_override(self):
        rows,inp,model,start,end=self.fixture(central=1,stress=3,capacity=8,temp=None)
        inp['outdoor_c']=None
        r=evaluate(rows,inp,model,start,end)
        self.assertEqual(r['status'],'no_temperature_asof')
        self.assertIsNone(r['desired_target_soc_pct'])

    def test_battery_reference_missing_must_not_trigger(self):
        rows,inp,model,start,end=self.fixture(central=20,stress=30)
        inp['reserve_soc']=None
        r=evaluate(rows,inp,model,start,end)
        self.assertEqual(r['status'],'missing_battery_energy_reference')
        self.assertIsNone(r['desired_target_soc_pct'])

if __name__=='__main__':
    unittest.main()
