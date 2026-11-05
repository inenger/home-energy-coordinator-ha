"""Deterministic synthetic child-reaping race; no production processes touched."""
import multiprocessing as mp,threading,os,sys,json
from unittest.mock import patch
from multiprocessing.connection import wait
from pathlib import Path
r=Path(__file__).resolve().parents[1];sys.path.insert(0,str(r/'priority_shadow'))
from energy.process_supervision import retire

def child():pass

def main():
 p=mp.get_context('spawn').Process(target=child);p.start();assert wait([p.sentinel],timeout=10)
 entered=threading.Event();release=threading.Event();waitpid=os.waitpid
 def held_waitpid(pid,flag):
  result=waitpid(pid,flag)
  if pid==p.pid and result[0]==pid and threading.current_thread().name=='synthetic-main-poll':
   entered.set();assert release.wait(5)
  return result
 problem=None
 with patch('os.waitpid',side_effect=held_waitpid):
  reader=threading.Thread(target=p.is_alive,name='synthetic-main-poll');reader.start();assert entered.wait(2)
  try:
   # The synthetic child is already reaped. Never send a signal to a reaped PID.
   with patch.object(p,'terminate'):
    try:retire(p,[])
    except RuntimeError as error:problem=str(error)
  finally:release.set();reader.join(2)
 assert problem=='AUXILIARY_PROCESS_WOULD_NOT_EXIT',problem
 assert p.exitcode==0;p.close()
 print(json.dumps({'race_reproduced':True,'false_retirement_error':problem,'child_exited_normally':True,'signal_sent':False,'cause':'concurrent Process.is_alive/waitpid from live snapshot and supervision'}))
if __name__=='__main__':main()
