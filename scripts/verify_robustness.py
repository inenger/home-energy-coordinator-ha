"""Opakovatelná brána obnovy současné produkční cesty. Žádný HA klient."""
import argparse,json,os,platform,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'priority_shadow'),str(ROOT/'priority_shadow/tests'),str(ROOT/'scripts/robustness')]
MODULES=('test_recovery_0622','test_contracts','test_night_fixes_0623')
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--repetitions',type=int,default=3);args=parser.parse_args()
 if not 1<=args.repetitions<=10:parser.error('repetitions must be 1..10')
 # Historické audity se sem nezapočítávají jako důkaz současného řízení.
 os.environ['SUPERVISOR_TOKEN']='synthetic-no-credential'
 outcomes=[]
 for iteration in range(1,args.repetitions+1):
  print('Robustness iteration',iteration,flush=True)
  suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name)for name in MODULES)
  result=unittest.TextTestRunner(verbosity=2,failfast=True).run(suite)
  strict=result.wasSuccessful() and result.testsRun>=26 and not result.skipped and not result.expectedFailures
  outcomes.append({'iteration':iteration,'tests':result.testsRun,'passed':strict,'skipped':len(result.skipped),'expected_failures':len(result.expectedFailures)})
  if not strict:
   print(json.dumps({'python':platform.python_version(),'iterations':outcomes,'failed':True}));return 1
 print(json.dumps({'python':platform.python_version(),'iterations':outcomes,'synthetic_only':True,'physical_readiness_proven':False}))
 return 0
if __name__=='__main__':raise SystemExit(main())
