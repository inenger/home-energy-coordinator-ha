"""Synthetic replay contract through RAM, SQLite, archive and independent energy."""
import sys,unittest,tempfile,json,gzip,contextlib,io,sqlite3,hashlib
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_archived_night import replay
from energy import priority,ram_control as c
from energy.store import Store,pack,unpack
from test_ram_control import data,result
from test_night import state
class ArchivedReplayTests(unittest.TestCase):
 def test_provenance_causality_readonly_input_and_energy(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);path=root/'source.sqlite';s=Store(path)
   s.db.execute('CREATE TABLE IF NOT EXISTS priority_samples(at TEXT PRIMARY KEY,day TEXT,payload BLOB)')
   start=datetime.fromisoformat('2026-01-15T03:59:40+00:00');history=[]
   for sec in range(0,21,5):
    at=(start+timedelta(seconds=sec)).isoformat();states=data(at);r=result(at);r['session']={**r['session'],'model_available_at':(start-timedelta(seconds=1)).isoformat()}
    c.observe(s,states,r)
    if sec<20:
     points=priority.checked_points(states,at)
     with s.db:s.db.execute('INSERT INTO priority_samples VALUES(?,?,?)',(at,'2026-01-15',pack({'at':at,'inputs':points,'session':r['session']})))
    if sec==0:
     history=[[{**row,'last_changed':row['last_updated']}]for row in states]
   s.close();before=hashlib.sha256(path.read_bytes()).hexdigest()
   with gzip.open(root/'history.gz','wt')as f:json.dump(history,f)
   with contextlib.redirect_stdout(io.StringIO()):out=replay(path,root/'history.gz','2026-01-15',root/'out')
   self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
   with self.assertRaises(FileExistsError):replay(path,root/'history.gz','2026-01-15',root/'out')
   bad=root/'future.sqlite';bad.write_bytes(path.read_bytes());db=sqlite3.connect(bad)
   at,payload=db.execute('SELECT at,payload FROM priority_samples ORDER BY at LIMIT 1').fetchone();row=unpack(payload)
   row['session']['model_available_at']=(start+timedelta(seconds=1)).isoformat()
   with db:db.execute('UPDATE priority_samples SET payload=? WHERE at=?',(pack(row),at))
   db.close()
   with self.assertRaises(AssertionError):replay(bad,root/'history.gz','2026-01-15',root/'rejected-future')
   self.assertEqual(out['strict_capture']['model']['battery_kwh_ac'],0)
   for name in ['captured_owner_assumed','report_time_owner_assumed']:
    archive=json.loads((root/'out'/(name+'-archive.json')).read_text());run=archive['session'];samples=archive['samples']
    self.assertGreater(run['shadow_model']['battery_kwh_ac'],0)
    self.assertTrue(run['provenance']['owner_report_freshness_assumed'])
    energy=0
    for a,b in zip(samples,samples[1:]+[{'at':run['closed_at']}]):
     if a['ram_target_ac_w']>0:
      finish=min(datetime.fromisoformat(b['at']),datetime.fromisoformat(a['intent_expires_at']))
      energy+=a['ram_target_ac_w']*max(0,(finish-datetime.fromisoformat(a['at'])).total_seconds())/3600000
    self.assertAlmostEqual(energy,run['shadow_model']['battery_kwh_ac'])
    self.assertTrue(all(e['device_actions']==e['persistent_writes']==0 for e in archive['events']))
   self.assertFalse(json.loads((root/'out/captured_owner_assumed-archive.json').read_text())['provenance']['report_delivery_at_last_reported_assumed'])
   self.assertTrue(json.loads((root/'out/report_time_owner_assumed-archive.json').read_text())['provenance']['report_delivery_at_last_reported_assumed'])
if __name__=='__main__':unittest.main()
