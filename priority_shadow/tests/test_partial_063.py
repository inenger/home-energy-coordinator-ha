import copy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from energy.soc_planner import plan
from energy.soc_runtime import view, schema, session_plan
from energy.soc_evidence import seal, verify
from energy.store import Store, pack
from energy import priority
from test_soc_planner import fixture


class PartialDemand(unittest.TestCase):
    def calculate(self, priority_name='ev', **changes):
        now, inputs, history, versions, house = fixture(ev=45, soc=11, pv=6, house=.7, season='winter')
        inputs.update(priority=priority_name, **changes)
        return now, plan(now, inputs, history, {}, house, versions)

    def test_unreachable_desired_soc_does_not_block_battery(self):
        _, result = self.calculate()
        self.assertEqual(result['status'], 'partial_shadow_plan')
        self.assertGreater(result['target_soc_pct'], 0)
        self.assertFalse(result['demand_fully_met'])
        self.assertGreater(result['ev_deficit_ac_kwh']['central'], 0)
        self.assertEqual(result['device_actions'], 0)
        self.assertFalse(result['live_ready'])

    def test_ev_priority_minimizes_worst_deficit_among_battery_feasible_targets(self):
        _, result = self.calculate()
        candidates = [c for c in result['candidates'] if all(v['battery_feasible'] for v in c['scenarios'].values())]
        deficit = lambda c: max(v['unserved_ev_ac_kwh'] for v in c['scenarios'].values())
        self.assertLessEqual(max(result['ev_deficit_ac_kwh'].values()), min(map(deficit, candidates)) + .05 + 1e-8)

    def test_battery_priority_preserves_more_energy_without_claiming_equal_service(self):
        _, ev = self.calculate('ev')
        _, battery = self.calculate('battery')
        self.assertGreaterEqual(battery['target_soc_pct'], ev['target_soc_pct'])
        self.assertEqual(battery['allocation_policy'], 'battery_regret_then_ev_deficit')
        self.assertEqual(battery['economic_comparison'], 'unequal_ev_service_no_savings_claim')
        for scenario in battery['selected']['scenarios'].values():
            self.assertAlmostEqual(scenario['house_battery_adjusted_cost_czk'],
                scenario['import_cost_czk'] - scenario['terminal_inventory_credit_czk'] - scenario['ev_import_cost_czk'])

    def test_desired_soc_never_invents_departure_or_minimum(self):
        _, result = self.calculate()
        self.assertEqual(result['ev_requirement']['desired_ac_kwh'], 45)
        self.assertIsNone(result['ev_requirement']['minimum_ac_kwh'])
        self.assertIsNone(result['ev_requirement']['departure_at'])

    def test_partial_cannot_bypass_battery_reserve(self):
        _, result = self.calculate(battery_charge_max_dc_kw=0)
        self.assertEqual(result['status'], 'no_comparable_feasible_plan')
        self.assertIn('input_snapshot', result)
        self.assertIn('forecast_periods', result)
        self.assertTrue(verify(result)['verified'])

    def test_missing_input_is_archived_and_not_replaced_with_zero(self):
        now, inputs, history, versions, house = fixture()
        inputs['ev_need_ac_kwh'] = None
        result = plan(now, inputs, history, {}, house, versions)
        self.assertIsNone(result['input_snapshot']['ev_need_ac_kwh'])
        self.assertEqual(result['forecast_versions'], versions)
        inputs['soc'] = 99
        self.assertNotEqual(result['input_snapshot']['soc'], 99)
        self.assertTrue(verify(result)['verified'])

    def test_partial_persists_through_view_and_session_then_revokes(self):
        now, result = self.calculate()
        compact = view(result)
        self.assertEqual(compact['ev_deficit_ac_kwh'], result['ev_deficit_ac_kwh'])
        self.assertFalse(compact['demand_fully_met'])
        self.assertNotIn('input_snapshot', compact)
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td)/'s.sqlite')
            schema(store.db)
            def save(r):
                with store.db:
                    store.db.execute('INSERT INTO soc_decisions VALUES(?,?,?,?)', (r['issued_at'],r['day'],r['decision_hash'],pack(r)))
            save(result)
            self.assertEqual(session_plan(store,result['day'],now.isoformat())['status'],'partial_shadow_plan')
            self.assertIsNone(session_plan(store,result['day'],(now+timedelta(minutes=31)).isoformat()))
            invalid = seal({**result,'issued_at':(now+timedelta(seconds=1)).isoformat(),'status':'waiting_for_inputs'})
            save(invalid)
            self.assertIsNone(session_plan(store,result['day'],(now+timedelta(seconds=2)).isoformat()))
            store.close()

    def test_missing_forecast_and_invalid_plan_have_distinct_context(self):
        self.assertEqual(priority.comparison_context({'forecast_kwh':12,'target_soc_pct':None}),'invalid_soc_plan')
        self.assertEqual(priority.comparison_context({'target_soc_pct':None}),'missing_forecast')
        self.assertEqual(priority.comparison_context({'forecast_kwh':12,'target_soc_pct':30,'soc_plan_status':'partial_shadow_plan'}),'partial_ev_service')

    def test_each_power_replay_uses_its_own_priority_target(self):
        from test_priority import inputs
        at='2026-10-23T01:01:00+00:00'
        points=priority.checked_points(inputs(at),at)
        session={'forecast_kwh':12,'target_soc_pct':30,'soc_plan_valid':True,
            'priority_alternatives':{'ev':{'status':'partial_shadow_plan','target_soc_pct':15,'horizon_complete':True},
                                     'battery':{'status':'partial_shadow_plan','target_soc_pct':90,'horizon_complete':True}}}
        self.assertEqual(priority.allocate(points,at,session,50,'ev')['target_soc_pct'],15)
        self.assertEqual(priority.allocate(points,at,session,50,'battery')['target_soc_pct'],90)
        session['priority_alternatives']['battery']['horizon_complete']=False
        self.assertEqual(priority.allocate(points,at,session,50,'battery')['reason'],'invalid_soc_plan')

    def test_historical_unknown_model_does_not_publish_zero_or_false_forecast_error(self):
        from energy.publish_status import priority_history_view
        source={'day':'2026-10-24','comparison_context':'missing_forecast',
                'session':{'forecast_kwh':12,'target_soc_pct':None},
                'models':{'ev':priority.empty_model(11)}}
        out=priority_history_view([source])[0]
        self.assertEqual(out['comparison_context'],'invalid_soc_plan')
        self.assertIsNone(out['models']['ev']['battery_kwh_ac'])
        self.assertIsNone(out['models']['ev']['soc_pct'])
        self.assertEqual(source['models']['ev']['battery_kwh_ac'],0)

    def test_operational_status_is_not_charger_mode(self):
        from test_priority import inputs
        states = inputs('2026-10-23T01:01:00+00:00')
        states.append({'entity_id':'sensor.solax_run_mode','state':'Normal Mode','attributes':{},'last_reported':'2026-10-23T01:01:00+00:00','last_updated':'2026-10-23T01:01:00+00:00'})
        points = priority.checked_points(states,'2026-10-23T01:01:00+00:00')
        self.assertEqual(priority.value(points,'inverter_run_mode'),'Normal Mode')
        self.assertNotEqual(priority.EXTRA['inverter_run_mode'],__import__('energy.night',fromlist=['IDS']).IDS['inverter_mode'])
