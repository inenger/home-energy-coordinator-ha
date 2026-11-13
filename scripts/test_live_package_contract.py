#!/usr/bin/env python3
"""stdlib-only regression for physical HA package; requires real HA config check too."""
from pathlib import Path
import math,re,unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'ha_packages/night_live_coordinator.yaml').read_text()

def reserve(pv):
    if pv is None or pv<=15:return 100
    if pv>=50:return 25
    return math.ceil(100-(pv-15)*75/35)

class LiveHAContract(unittest.TestCase):
    def test_forecast_policy_edges(self):
        for pv,want in [(None,100),(0,100),(15,100),(25,79),(35,58),(50,25),(60,25)]:
            self.assertEqual(reserve(pv),want)
        self.assertTrue(all(25<=reserve(x)<=100 for x in range(-5,90)))

    def test_persistent_ownership_and_recovery(self):
        for name in ('hec_live_owned','hec_live_reserve_before','hec_live_ev_before',
                     'hec_live_reserve_target','hec_live_ev_target',
                     'number.solax_backup_discharge_min_soc',
                     'number.solax_api_max_charge_current_setting',
                     'hec_live_claim_20261113','hec_live_phase_limit_20261113',
                     'hec_live_restore_20261113','input_boolean.turn_on',
                     'input_boolean.turn_off','3 <= now().hour < 5',
                     'last_soc','old_soc','last_ev','old_ev'):
            self.assertIn(name,SOURCE)
        self.assertEqual(SOURCE.count('    mode: single'),3)

    def test_devices_are_whitelisted(self):
        # No inverter mode switching or hidden DC-force charging in live package.
        self.assertEqual(SOURCE.count('action: number.set_value'),5)
        self.assertEqual(SOURCE.count('action: select.select_option'),1)
        self.assertIn('option: Stop',SOURCE)
        self.assertNotIn('target: {entity_id: select.solax_charger_use_mode}',SOURCE)
        self.assertNotIn('select.solax_manual_mode_select',SOURCE)
        self.assertNotIn('number.solax_battery_charge_max_current',SOURCE)
        self.assertIn('24.5',SOURCE)

    def test_unique_automations_and_time_boundaries(self):
        ids=re.findall(r'^  - id: ([a-z0-9_]+)$',SOURCE,re.M)
        self.assertEqual(len(ids),3)
        self.assertEqual(len(set(ids)),3)
        self.assertIn('at: "02:59:40"',SOURCE)
        self.assertIn('at: "05:00:00"',SOURCE)
        self.assertIn('seconds: "/30"',SOURCE)
        self.assertIn('      - delay: "00:00:05"',SOURCE)

if __name__=='__main__':
    unittest.main()
