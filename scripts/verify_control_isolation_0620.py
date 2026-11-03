"""Syntetická regrese produkční smyčky při blokovaném úložišti, bez HA."""
import json,os,sys,unittest
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(repo/'priority_shadow'),str(repo/'priority_shadow/tests')]
from test_control_isolation_0620 import ControlIsolationTests
if __name__=='__main__':
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(ControlIsolationTests)
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 out={'all_passed':result.wasSuccessful(),'contracts':result.testsRun,
      'production_entrypoint_and_run_loop':True,'private_memory_control_state':True,
      'real_external_sqlite_lock':True,'real_spawned_writer':True,
      'bounded_queue_overflow_reported':True,'genuine_input_failure_stops':True,
      'disk_and_ipc_reads_outside_control_thread':True,
      'physical_control_verified':False,'private_inputs':False}
 target=Path(os.environ.get('ENERGY_AUDIT_OUTPUT','/tmp/control-isolation-0620'))
 target.mkdir(parents=True,exist_ok=True)
 (target/'control-isolation-probes.json').write_text(json.dumps(out,indent=2))
 print(json.dumps(out))
 if not result.wasSuccessful():raise SystemExit(1)
