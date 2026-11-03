# Historical coupled-loop regression baseline; current runtime proof: verify_control_isolation_0620.py
"""Syntetické důkazy SQLite koordinace, bez HA a soukromých dat."""
import json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
repo=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from test_sqlite_writes_0619 import SQLiteWritesTests
from energy.sqlite_writes import Gate
case=SQLiteWritesTests();baseline=None
with patch.object(Gate,'acquire',return_value=None),patch.object(Gate,'release',return_value=None):
 try:case.test_main_control_keeps_local_background_writer_out_of_decision_scope()
 except AssertionError as error:baseline=type(error).__name__
assert baseline,'Disabling coordination must reproduce contention/ordering failure'
tests=unittest.defaultTestLoader.loadTestsFromTestCase(SQLiteWritesTests)
result=unittest.TextTestRunner(verbosity=2).run(tests)
assert result.wasSuccessful()
out={'guard_disabled_baseline':'failed_as_expected','coordinated_contracts':result.testsRun,'all_passed':True,'real_sqlite_and_threads':True,'external_busy_still_fails_safe':True,'compression_outside_writer':True,'native_error_details_retained':True,'private_inputs':False}
target=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/sqlite-0619'));target.mkdir(exist_ok=True,parents=True)
(target/'sqlite-probes.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
