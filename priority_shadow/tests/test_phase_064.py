import copy
from datetime import timedelta
import unittest
from energy.core import instant
from energy.phase_budget import estimate, fallback, checked
from energy.soc_planner import plan, _night_room
from energy.soc_runtime import view
from energy.soc_evidence import verify
from energy import priority
from test_soc_planner import fixture
from test_priority import inputs, points, AT


def samples():
    result=[];start=instant(AT)
    for j in range(100):
        p={}
        for i in (1,2,3):
            base=230+(23 if j%2 else 0)
            for key,value in {f'grid_voltage_l{i}_v':230,f'grid_l{i}_w':-3680-base,
                              f'inverter_l{i}_w':0,f'ev_l{i}_w':3680,
                              f'grid_l{i}_a':(3680+base)/230/.99}.items():
                p[key]={'value':value,'quality':'valid','age_seconds':1}
        result.append({'at':(start+timedelta(seconds=15*j)).isoformat(),'inputs':p})
    return result


class PhaseBudget(unittest.TestCase):
    def test_empirical_budget_and_asof_no_future_leak(self):
        rows=samples();at=rows[-1]['at'];c=estimate(rows,at)
        self.assertEqual(c['status'],'empirical_shadow_candidate')
        self.assertEqual(c['reserve_a'],[.3]*3)
        self.assertTrue(all(abs(p-.99)<1e-8 for p in c['power_factor']))
        future=copy.deepcopy(rows[-1]);future['at']=(instant(at)+timedelta(seconds=15)).isoformat()
        future['inputs']['grid_l1_a']['value']=99
        self.assertEqual(estimate(rows+[future],at),c)
        self.assertFalse(c['control_verified'])

    def test_sparse_or_stale_history_is_explicit_fallback(self):
        rows=samples()
        self.assertEqual(estimate(rows[:20],rows[-1]['at'])['source'],'explicit_legacy_fallback')
        for r in rows:r['inputs']['grid_l1_a']['age_seconds']=100
        self.assertEqual(estimate(rows,rows[-1]['at'])['status'],'insufficient_history')

    def test_inconsistent_current_is_not_used_as_unity_pf(self):
        rows=samples()
        for r in rows:r['inputs']['grid_l1_a']['value']=5
        self.assertEqual(estimate(rows,rows[-1]['at'])['status'],'insufficient_history')

    def test_invalid_budget_fails_explicitly(self):
        for key,value in [('reserve_a',[-1,0,0]),('power_factor',[1.1,1,1]),('house_phase_shares',[1,1,1])]:
            with self.assertRaises(ValueError):checked({**fallback(),key:value})

    def test_weakest_phase_limits_balanced_charging(self):
        c={**fallback(),'reserve_a':[.5]*3,'power_factor':[1.]*3, 'house_phase_shares':[.8,.1,.1]}
        self.assertAlmostEqual(_night_room({'phase_voltages':[230]*3,'power_budget':c},3),3*(24.5*.230-2.4))

    def test_allocator_fills_room_without_reducing_ev(self):
        c={**fallback(),'reserve_a':[.5]*3,'power_factor':[1.]*3}
        pp=points(inputs());session={'forecast_kwh':12,'target_soc_pct':90,'power_budget':c}
        old=priority.allocate(pp,AT,{**session,'power_budget':fallback()},20,'ev')
        new=priority.allocate(pp,AT,session,20,'ev')
        self.assertEqual(new['ev_ac_w'],11000)
        self.assertGreater(new['battery_ac_w'],old['battery_ac_w']+2000)
        self.assertTrue(all(p['planned_model_a']<=24.5 for p in new['phase']))
        budget=3*min(p['budget_w'] for p in new['phase'])
        self.assertLess(budget-new['ev_ac_w']-new['battery_ac_w'],100.01)
        self.assertFalse(new['live_ready']);self.assertEqual(new['device_actions'],0)

    def test_target_shortfall_retained_not_false_success(self):
        now,i,h,v,house=fixture(pv=0,house=1,soc=20,season='winter',ev=0)
        i['battery_charge_max_dc_kw']=.1
        p=plan(now,i,h,{},house,v)
        high=next(c for c in p['candidates'] if c['target_soc_pct']==95)
        self.assertTrue(high['service_feasible_all_scenarios'])
        self.assertFalse(high['feasible_all_scenarios'])
        self.assertIn('max_regret_czk',high)
        self.assertGreater(high['scenarios']['central']['target_shortfall_soc_pct'],50)
        self.assertEqual(view(p)['attainable_soc_05'],p['attainable_soc_05'])
        self.assertTrue(verify(p)['verified'])

    def test_budget_and_own_priority_outcome_survive_view(self):
        now,i,h,v,house=fixture(pv=6,house=.7,soc=11,season='winter',ev=45)
        i['power_budget']={**fallback(),'reserve_a':[.5]*3,'power_factor':[.99]*3}
        p=plan(now,i,h,{},house,v);out=view(p)
        self.assertEqual(out['power_budget'],i['power_budget'])
        self.assertIn('attainable_soc_05',out['priority_alternatives']['battery'])
        for s in p['selected']['scenarios'].values():self.assertGreaterEqual(s['soc_at_05'],i['reserve_soc']-.5)
        self.assertTrue(verify(p)['verified'])

    def test_solar_surplus_still_skips_unnecessary_grid_charge(self):
        now,i,h,v,house=fixture(pv=50,house=.25,soc=20)
        i['power_budget']={**fallback(),'reserve_a':[.2]*3,'power_factor':[1.]*3}
        p=plan(now,i,h,{},house,v)
        self.assertEqual(p['target_soc_pct'],0);self.assertEqual(p['night_charge_ac_kwh'],0)

    def test_empirical_replay_requires_fresh_current_and_lowers_pf(self):
        pp=points(inputs()); c={**fallback(),'status':'empirical_shadow_candidate','reserve_a':[.5]*3,'power_factor':[1.]*3}
        session={'forecast_kwh':12,'target_soc_pct':90,'power_budget':c}
        for i in (1,2,3):
            u=pp.get(f'grid_voltage_l{i}_v',{}).get('value') or pp[f'voltage_l{i}_v']['value']
            pp[f'grid_l{i}_a']={'value':abs(pp[f'grid_l{i}_w']['value'])/u/.95,'quality':'valid','age_seconds':1}
        new=priority.allocate(pp,AT,session,20,'ev')
        self.assertTrue(all(p['power_factor']<=.95+1e-8 for p in new['phase']))
        pp['grid_l1_a']['age_seconds']=100
        self.assertEqual(priority.allocate(pp,AT,session,20,'ev')['reason'],'invalid_phase_input')
