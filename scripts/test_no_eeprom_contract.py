"""Narrow source regression for reviewed actuator boundaries; no network/device I/O."""
import ast
from collections import Counter
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PILOT = 'ops/solax_modbus/hec_mode8_pilot.py'
CLIENT = 'priority_shadow/energy/live_control.py'
# New routes require explicit review of exact target, persistence and wire tests.
ALLOWED = Counter({
    (PILOT, 'WriteMultipleRegistersPDU(160, values)'): 1,
    (PILOT, 'base.send_and_receive(unit_id, pdu)'): 1,
    (CLIENT, '/api/services/solax_modbus/hec_mode8_pilot?return_response'): 1,
    ('priority_shadow/energy/weather.py', '/api/services/weather/get_forecasts?return_response'): 1,
    ('energy_coordinator/energy/weather.py', '/api/services/weather/get_forecasts?return_response'): 1,
})
WRITE_NAMES = {'write_register', 'write_registers', 'write_single_register',
               'write_multiple_registers', 'async_write_register', 'async_write_registers',
               'async_write_registers_multi', 'WriteSingleRegisterPDU',
               'WriteMultipleRegistersPDU', 'send_and_receive', 'call_service',
               'async_call_service'}

def inventory(path, source):
    found = Counter()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'attr', getattr(node.func, 'id', None))
            if name in WRITE_NAMES:
                found[path, ast.unparse(node)] += 1
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if '/api/services/' in node.value or node.value in {
                    'number.set_value', 'select.select_option', 'modbus.write_register'}:
                found[path, node.value] += 1
    return found

class NoEEPROMContract(unittest.TestCase):
    def test_reviewed_routes_only(self):
        actual = Counter()
        for folder in ('priority_shadow/energy', 'energy_coordinator/energy', 'ops/solax_modbus'):
            for p in (ROOT/folder).rglob('*.py'):
                actual.update(inventory(p.relative_to(ROOT).as_posix(), p.read_text()))
        self.assertEqual(actual, ALLOWED)
    def test_unqualified_pilot_locked(self):
        tree = ast.parse((ROOT/PILOT).read_text())
        values = [x.value for x in tree.body if isinstance(x, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'HARDWARE_DISPATCH_QUALIFIED'
                          for t in x.targets)]
        self.assertEqual(len(values), 1)
        self.assertIsInstance(values[0], ast.Constant)
        self.assertIs(values[0].value, False)
    def test_counterexamples_detected(self):
        for path, src in (
            (PILOT, 'pdu=WriteMultipleRegistersPDU(0x24,values)'),
            (PILOT, 'await hub.async_write_registers_multi(unit,0x25,[0])'),
            (CLIENT, 'url="/api/services/number/set_value"'),
            (CLIENT, 'url="/api/services/modbus/write_register"'),
            (CLIENT, 'service="select.select_option"'),
            (CLIENT, 'await unit.write_registers(0x668,[1600])'),
            (CLIENT, 'await unit.write_registers(0x628,[1000])'),
        ):
            with self.subTest(src=src):
                self.assertTrue(inventory(path, src) - ALLOWED)

if __name__ == '__main__':
    unittest.main()
