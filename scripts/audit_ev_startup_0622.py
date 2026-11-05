"""Reprodukuje známý EV startup stop0.6.22. Úspěch potvrzuje vadu, ne opravu."""
import sys,tempfile,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'priority_shadow'),str(ROOT/'priority_shadow/tests')]
from energy import isolated_control as iso,night,priority,journal_transport as transport,publish_status
from energy.store import Store,unpack
from test_control_isolation_0620 import Clock,Stop,Client,Evidence,Monitor
from test_control_journal import patch_value

def main():
 mapping={**night.IDS,**priority.EXTRA}
 clock=Clock();client=Client(clock);read=client.priority_states;evidence=Evidence();monitor=Monitor()
 def states():
  rows=read();ev=[1000.,0.,0.]if clock.sec==10 else[0.,0.,0.]
  patch_value(rows,mapping['ev_w'],sum(ev))
  for i,(base,load)in enumerate(zip([400.,800.,200.],ev),1):
   patch_value(rows,mapping[f'ev_l{i}_w'],load)
   patch_value(rows,mapping[f'grid_l{i}_w'],-base-load)
   patch_value(rows,mapping[f'grid_l{i}_a'],(base+load)/230)
   patch_value(rows,mapping[f'inverter_l{i}_w'],0)
   patch_value(rows,mapping[f'grid_voltage_l{i}_v'],230)
  return rows
 client.priority_states=states
 iso.run_loop(client,evidence,monitor,Stop(clock),clock.now,lambda:clock.sec)
 assert all(x['collection_health']['status']!='failed'for x in monitor.results),'Invalid synthetic input fixture'
 runs=[x['control_journal']['session']for x in monitor.results]
 assert runs[1]['target_ac_w']>0
 blocked=monitor.results[2]['control_journal']['recent_samples'][0]
 assert blocked['ram_target_ac_w']==0 and 'requires_ev_control_not_implemented'in blocked['input_errors']
 assert runs[4]['target_ac_w']>0
 with tempfile.TemporaryDirectory()as folder:
  store=Store(Path(folder)/'synthetic.sqlite')
  try:
   for seq,(rows,states,value,generation)in enumerate(evidence.rows,1):
    iso.persist_batch(store,{'runtime':'synthetic-startup','seq':seq,'at':value['at'],'rows':rows,'loss':{}})
    transport.enqueue(store,value['control_journal'])
   events=[unpack(p)for p, in store.db.execute('SELECT payload FROM ram_control_events')]
   stops=[e for e in events if e['kind']=='would_stop_charge']
   assert len(stops)==1 and stops[0]['reason']=='requires_ev_control_not_implemented'
   assert store.db.execute('SELECT count(*)FROM journal_transport_outbox').fetchone()[0]>0
   assert publish_status.prepare_priority(monitor.results[-1])
   assert all(e['device_actions']==0 for e in events)
  finally:store.close()
 print(json.dumps({'defect_reproduced':True,'path':'production run_loop -> RAM stop -> SQLite -> outbox -> monitor preparation','measured_startup_ev_w':1000,'all_phase_loads_fit':True,'power_resumes_after_two_new_frames':True,'physical_actions':0}))
if __name__=='__main__':main()
