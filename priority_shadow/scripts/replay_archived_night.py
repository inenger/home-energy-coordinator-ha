"""Offline conditional replay. Private inputs stay on the host; no HA calls."""
import argparse,bisect,collections,copy,gzip,json,sqlite3,sys
from datetime import timedelta,datetime,timezone
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from energy import priority,ram_control as c,priority_observer
from energy.core import instant,digest,VERSION
from energy.store import unpack,pack

def replay(database,history,day,out):
 out.mkdir(parents=True,exist_ok=False)
 db=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
 old=unpack(db.execute('SELECT payload FROM ram_control_sessions WHERE day=?',(day,)).fetchone()[0])
 frames=[];sessions={}
 for payload, in db.execute('SELECT payload FROM priority_samples WHERE day=? ORDER BY at',(day,)):
  x=unpack(payload);session=sessions.setdefault(digest(x['session']),x['session'])
  assert instant(session['model_available_at'])<=instant(x['at'])
  points={k:{z:p.get(z)for z in ('entity_id','value','unit','last_reported','last_updated')}for k,p in x['inputs'].items()}
  frames.append((instant(x['at']),points,session))
 failures=[unpack(p)for p, in db.execute('SELECT payload FROM ram_control_events WHERE day=? ORDER BY id',(day,))if unpack(p)['kind']=='collection_failure']
 db.close();times=[x[0]for x in frames];end=instant(old['window_end'])
 hist=json.load(gzip.open(history,'rt'));base={}
 for rows in hist:
  for row in rows:
   base.setdefault(row['entity_id'],[]).append((instant(row.get('last_updated')or row['last_changed']),row))
 for rows in base.values():rows.sort(key=lambda x:x[0])
 base_times={k:[x[0]for x in rows]for k,rows in base.items()}
 reports={}
 for captured,points,session in frames:
  for p in points.values():
   if p['entity_id']and p['value']is not None and p['last_reported']:
    at=instant(p['last_reported']);assert at<=captured
    reports.setdefault(p['entity_id'],{})[at]=p
 reports={k:sorted(v.items())for k,v in reports.items()}
 report_times={k:[x[0]for x in rows]for k,rows in reports.items()}
 results={}
 for scenario in ('strict_capture','captured_owner_assumed','report_time_owner_assumed'):
  d=sqlite3.connect(out/(scenario+'.sqlite'));store=SimpleNamespace(db=d)
  at=times[0];failure_index=0;waits=[];assumptions=0
  while True:
   index=bisect.bisect_right(times,at)-1
   _,captured_points,session=frames[index]
   states={}
   for eid,rows in base.items():
    i=bisect.bisect_right(base_times[eid],at)-1
    if i>=0:
     row=copy.deepcopy(rows[i][1]);row.update(last_updated=(row.get('last_updated')or row['last_changed']),last_reported=None,report_source='historical_recorder_NO_report_time')
     states[eid]=row
   chosen=captured_points.values()
   if scenario=='report_time_owner_assumed':
    chosen=[]
    for eid,rows in reports.items():
     i=bisect.bisect_right(report_times[eid],at)-1
     if i>=0:chosen.append(rows[i][1])
   for p in chosen:
    eid=p['entity_id']
    if not eid:continue
    if p['value']is None or not p['last_reported']:
     states.pop(eid,None);continue
    assert instant(p['last_reported'])<=at
    row=states.setdefault(eid,{'entity_id':eid,'attributes':{}});row['attributes']=dict(row.get('attributes',{}))
    if p['unit']is not None:row['attributes']['unit_of_measurement']=p['unit']
    row.update(state=str(p['value']),last_updated=p['last_updated'],last_reported=p['last_reported'],report_source='original_report_timestamp')
   if scenario!='strict_capture':
    cohort=states.get(c.RUN_MODE,{}).get('last_reported')
    for eid in (c.REMOTE_MODE,c.READBACKS[0]):
     if eid in states and cohort:
      states[eid].update(last_reported=cohort,report_source='ASSUMED_owner_heartbeat_from_run_mode');assumptions+=1
   states=list(states.values())
   while failure_index<len(failures)and instant(failures[failure_index]['at'])<=at:
    fail=failures[failure_index];c.record_failure(store,fail['at'],fail['reason']);failure_index+=1
   outage=any(instant(f['at'])<=at<times[bisect.bisect_right(times,instant(f['at']))]for f in failures)
   stamp=at.isoformat()
   if not outage:
    points=priority.checked_points(states,stamp)
    journal=c.observe(store,states,{'at':stamp,'session':session,'priority':priority.LABELS.get(priority.value(points,'priority'))})
   else:journal=c.view(store,stamp,states)
   if at>=end:break
   delay=priority_observer.next_wait(stamp,0.,journal);waits.append(delay)
   next_at=min(at+timedelta(seconds=delay),end)
   pending=[instant(f['at'])for f in failures[failure_index:]if at<instant(f['at'])<next_at]
   if pending:next_at=min(pending)
   assert next_at>at;at=next_at
  run=c.view(store,stamp,states)['session'];assert run['closed_at']
  provenance={'kind':'retrospective_held_recorder_states','scenario':scenario,'software_version':VERSION,
   'source_runtime_version':old['software_version'],'reconstructed_at':datetime.now(timezone.utc).isoformat(),
   'historical_last_reported_available':'original_priority_samples_except_owner_heartbeat',
   'owner_report_freshness_assumed':scenario!='strict_capture',
   'report_delivery_at_last_reported_assumed':scenario=='report_time_owner_assumed',
   'original_capture_availability_only':scenario!='report_time_owner_assumed',
   'scheduler':'production_next_wait_zero_work_duration','collection_failure_preserved':True,
   'live_heartbeat_verified':False,'physical_control_ready':False,
   'limitations':[
    'Zpětný model 0.6.17; původní živý deník zůstává samostatně zachovaný.',
    'Přesný čas převzetí reportů workerem ani délku práce v nových krocích nelze zpětně doložit. Smyčka používá next_wait a nulovou délku práce.',
    'Strict kontrola nepředpokládá čerstvost vzdáleného vlastníka. Obě podmíněné varianty ji předpokládají podle původního run-mode reportu.',
    'Captured varianta zpřístupní snímek až při původním zachycení. Report-time varianta předpokládá dostupnost už při uloženém last_reported; jde o příznivý předpoklad, nikoli doložené doručení.',
    'Původní report timestampy a hodnoty rychlých senzorů se nepřepisují. Model a prognóza pocházejí pouze z předchozího zachyceného rozhodnutí.',
    'Původní chyba sběru a interval do zachycené obnovy se zachovávají. Výsledek je AC/SOC model, nikoli skutečně nabitá energie; žádné fyzické povely.']}
  run['provenance']=provenance
  run['ideal_allocation_model']={'unavailable':True,'reason':'not_computed_for_this_adaptive_replay'}
  provenance['limitations'].append('Ideální alokace se v této rekonstrukci nepočítá. Chybějící výsledek se nepřebírá z původního živého běhu.')
  with d:d.execute('UPDATE ram_control_sessions SET payload=? WHERE day=?',(pack(run),day))
  events=[dict(unpack(p),id=i,provenance_kind=provenance['kind'])for i,p in d.execute('SELECT id,payload FROM ram_control_events ORDER BY id')]
  samples=[dict(unpack(p),provenance_kind=provenance['kind'])for p, in d.execute('SELECT payload FROM ram_control_samples ORDER BY at')]
  archive={'session':run,'events':events,'samples':samples,'provenance':provenance,'model_result':run.get('shadow_model')}
  (out/(scenario+'-archive.json')).write_text(json.dumps(archive,ensure_ascii=False))
  assert all(x['device_actions']==x['persistent_writes']==0 for x in events+samples)
  assert d.execute('PRAGMA quick_check').fetchone()[0]=='ok';d.close()
  results[scenario]={'samples':len(samples),'events':len(events),'stop_reasons':dict(collections.Counter(e['reason']for e in events if e['kind']=='would_stop_charge')),
   'model':run.get('shadow_model'),'restoration':run.get('restoration_status'),'sub5s_waits':sum(w<5 for w in waits),
   'minimum_wait_s':min(waits),'invalid_samples':sum(bool(s['input_errors'])for s in samples),'owner_heartbeat_assumptions':assumptions}
  print(scenario,json.dumps(results[scenario]),flush=True)
  del archive,events,samples
 (out/'results.json').write_text(json.dumps(results,indent=2))
 return results

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('database',type=Path);p.add_argument('history',type=Path);p.add_argument('day');p.add_argument('out',type=Path)
 a=p.parse_args();replay(a.database,a.history,a.day,a.out)
