"""Historical 0.6.23 cold-backup counterexample, not a readiness PASS.

Synthetic run_loop -> shutdown -> durable seed -> restart. No HA client,
Supervisor call, backup request or physical action is performed.
"""
import sys,json,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'priority_shadow'),str(ROOT/'priority_shadow/tests')]
from energy import isolated_control as iso,journal_transport as transport
from energy.store import Store,unpack
from test_control_isolation_0620 import Clock,Stop,Client,Evidence,Monitor
from test_ram_control import stamp

def main():
 assert 'backup: cold' in (ROOT/'priority_shadow/config.yaml').read_text(),'This reproducer targets the historical cold-backup candidate'
 clock=Clock();evidence=Evidence();monitor=Monitor()
 iso.run_loop(Client(clock),evidence,monitor,Stop(clock,25),clock.now,lambda:clock.sec)
 assert monitor.results[-1]['control_journal']['session']['target_ac_w']>0
 with tempfile.TemporaryDirectory()as folder:
  store=Store(Path(folder)/'evidence.sqlite')
  try:
   def flush(items,offset=0):
    for seq,(rows,states,value,generation)in enumerate(items,offset+1):
     iso.persist_batch(store,{'runtime':'synthetic-backup','seq':seq,'at':value['at'],'rows':rows,'loss':{}})
     transport.enqueue(store,value['control_journal'])
   flush(evidence.rows);seed=iso.seed_from(store)
   original={table:list(store.db.execute('SELECT * FROM '+table+' ORDER BY '+key))for table,key in [('ram_control_events','id'),('ram_control_samples','at')]}
   class Restored(Evidence):
    def seed(self):return seed
   # No controller instance is alive while its entire addon is stopped.
   clock.sec=60;restored=Restored();after=Monitor()
   iso.run_loop(Client(clock),restored,after,Stop(clock,90),clock.now,lambda:clock.sec)
   flush(restored.rows,len(evidence.rows))
   for table,rows in original.items():
    key='id'if table.endswith('events')else'at'
    assert all(store.db.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(row[0],)).fetchone()==row for row in rows)
   events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
   assert any(e['kind']=='collection_failure'and e['reason']=='runtime_restart_unflushed_state_unknown'for e in events)
   assert any(e['kind']=='sampling_gap'for e in events)
   assert after.results[0]['control_journal']['session']['target_ac_w']==0
   assert after.results[1]['control_journal']['session']['target_ac_w']>0
   assert after.results[0]['control_journal']['session']['evidence_integrity']['status']=='unknown'
   assert all(e['device_actions']==0 for e in events)
  finally:store.close()
 print(json.dumps({'cold_backup_continuity_proven':False,'readiness_blocker_reproduced':True,
  'primary_controller_absent_during_whole_addon_stop':True,'last_old_sample':stamp(20),'first_restarted_sample':stamp(60),
  'sample_gap_s':40,'old_lease_not_reused':True,'recovery_requires_new_frames':True,
  'original_records_retained':True,'physical_actions':0}))
if __name__=='__main__':main()
