import json, tempfile, unittest, uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import Mock
from energy.live_control import MAPPING, preview, request_for, pilot
from energy.isolated_control import MemoryControl
from test_ram_control import data, stamp, result

class LivePilotTests(unittest.TestCase):
    def approval(self,now):
        return dict(request_id=str(uuid.uuid4()),hub_name='test',mapping=MAPPING,charge_dc_w=300,
                    duration_s=10,ev_disconnected_confirmed=True,expires_at=(now+timedelta(seconds=50)).isoformat(),operator_confirmed=True)
    def test_default_and_live_test_never_write(self):
        ram=MemoryControl()
        try:
            for t in (0,5,10):
                _,j=ram.step(data(stamp(t)),result(stamp(t)),stamp(t))
            for mode in ('observe_only','live_test'):
                p=preview(j,stamp(10),mode)
                self.assertFalse(p['automatic_actuation']);self.assertIsNone(p['wire_command'])
                self.assertEqual(p['device_actions'],0)
                self.assertIsNotNone(p['requested_ac_w'])
            self.assertIsNone(preview(j,stamp(30),'live_test')['requested_ac_w'])
            j['recent_samples'][0]['phase_peak_window']=None
            self.assertIsNone(preview(j,stamp(10),'live_test')['requested_ac_w'])
        finally:ram.close()
    def test_reject_unreviewed_and_unbounded(self):
        now=datetime.now(timezone.utc)
        a=self.approval(now)
        self.assertEqual(request_for(a,now)['charge_dc_w'],300)
        for bad in ({'mapping':'unknown'},{'charge_dc_w':5000},{'charge_dc_w':True},{'duration_s':60},
                    {'operator_confirmed':False},{'ev_disconnected_confirmed':False},{'expires_at':now.isoformat()},{'register':160}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):request_for({**a,**bad},now)
    def test_one_shot_uncertain_no_retry_or_replay(self):
        now=datetime.now(timezone.utc);client=Mock();client.snapshot.return_value={}
        client.send.side_effect=TimeoutError
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'approval';a.write_text(json.dumps(self.approval(now)));a.chmod(0o600)
            with self.assertRaises(ValueError):pilot({'mode':'observe_only'},a,root/'audit',client,lambda:now,lambda _:None)
            client.send.assert_not_called()
            path=pilot({'mode':'live_test'},a,root/'audit',client,lambda:now,lambda _:None)
            self.assertEqual(client.send.call_count,1)
            records=[json.loads(x) for x in path.read_text().splitlines()]
            self.assertIn('dispatch_uncertain',[x['kind'] for x in records])
            self.assertEqual(records[-1]['kind'],'operator_review_required')
            with self.assertRaises(FileExistsError):pilot({'mode':'live_test'},a,root/'audit',client,lambda:now,lambda _:None)
            self.assertEqual(client.send.call_count,1)
    def test_before_snapshot_failure_does_not_write(self):
        now=datetime.now(timezone.utc);client=Mock();client.snapshot.side_effect=OSError
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'approval';a.write_text(json.dumps(self.approval(now)));a.chmod(0o600)
            with self.assertRaises(OSError):pilot({'mode':'live_test'},a,root/'audit',client,lambda:now,lambda _:None)
            client.send.assert_not_called()
