"""B02: odmítnutý čas nesmí otrávit referenci ani obejít dvě nové platné sady."""
import tempfile,copy,unittest
from pathlib import Path
from energy import ram_control as c
from energy.store import Store,pack,unpack
from test_ram_control import data,result,stamp
class ClockRecoveryTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'e.sqlite');self.step(0);self.step(5)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def step(self,s,states=None):return c.observe(self.store,data(stamp(s))if states is None else states,result(stamp(s)))
 def test_future_rejected_frame_does_not_change_reference_and_recovers(self):
  v=self.step(10,data(stamp(310)));self.assertEqual(v['session']['target_ac_w'],0);self.assertTrue(v['recent_samples'][0]['input_errors']);self.assertEqual(v['session']['accepted_solax_reports'][c.SOLAX_KEYS[0]],stamp(5))
  self.assertEqual(self.step(15)['session']['target_ac_w'],0);v=self.step(20);self.assertEqual(v['session']['target_ac_w'],500);self.assertEqual(v['session']['good_frames'],2)
 def test_incoherent_rejected_frame_does_not_advance_reference(self):
  states=data(stamp(10));next(x for x in states if x['entity_id']==c.RUN_MODE)['last_reported']=stamp(50)
  v=self.step(10,states);self.assertEqual(v['session']['accepted_solax_reports'][c.SOLAX_KEYS[0]],stamp(5));self.assertEqual(v['session']['target_ac_w'],0)
  self.assertEqual(self.step(15)['session']['target_ac_w'],0);self.assertEqual(self.step(20)['session']['target_ac_w'],500)
 def test_old_version_poisoned_reference_is_reset_safely(self):
  row=self.store.db.execute('SELECT day,payload FROM ram_control_sessions').fetchone();run=unpack(row[1]);run['accepted_solax_reports']={k:stamp(310)for k in c.SOLAX_KEYS}
  with self.store.db:self.store.db.execute('UPDATE ram_control_sessions SET payload=?WHERE day=?',(pack(run),row[0]))
  v=self.step(10);self.assertEqual(v['session']['target_ac_w'],0);self.assertEqual(v['session']['good_frames'],1);self.assertEqual(self.step(15)['session']['target_ac_w'],500)
  self.assertTrue(any(unpack(p)['kind']=='frame_reference_reset'for p, in self.store.db.execute('SELECT payload FROM ram_control_events')))
 def test_backwards_clock_restarts_confirmation_without_increasing(self):
  v=self.step(4);self.assertEqual(v['session']['target_ac_w'],0);self.assertEqual(v['session']['good_frames'],0)
  self.assertEqual(self.step(5)['session']['target_ac_w'],0)
  self.assertEqual(self.step(9)['session']['target_ac_w'],0)
  self.assertEqual(self.step(14)['session']['target_ac_w'],500)
 def test_invalid_reference_does_not_bypass_invalid_current_data(self):
  row=self.store.db.execute('SELECT day,payload FROM ram_control_sessions').fetchone();run=unpack(row[1]);run['accepted_solax_reports']={k:stamp(310)for k in c.SOLAX_KEYS}
  with self.store.db:self.store.db.execute('UPDATE ram_control_sessions SET payload=?WHERE day=?',(pack(run),row[0]))
  states=data(stamp(10));next(x for x in states if x['entity_id']==c.REMOTE_MODE)['state']='unknown';v=self.step(10,states);self.assertEqual(v['session']['target_ac_w'],0);self.assertEqual(v['session']['good_frames'],0)
  self.assertEqual(self.step(15)['session']['target_ac_w'],0);self.assertEqual(self.step(20)['session']['target_ac_w'],500)
