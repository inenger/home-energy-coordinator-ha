"""Teplotní katalog musí beze ztráty přežít omezení atributů recorderu."""
import json,unittest,copy,contextlib,io
from unittest.mock import patch
from energy import publish_status as pub
from energy.monitor_payload import unpacked,encoded
class MonitorBudgetTests(unittest.TestCase):
 def test_full_large_temperature_catalog_roundtrips_below_budget(self):
  attrs={'friendly_name':'Teploty','sensors':[{'entity_id':'sensor.synthetic_temperature_'+str(i),'label':'Syntetické teplotní čidlo '+str(i),'value':20+i/10,'unit':'°C','quality':'valid','role':None,'zone':None,'area_name':None}for i in range(300)]}
  original=copy.deepcopy(attrs);request=pub.request('sensor.energie_v4_teploty_pocet',{'state':300,'attributes':attrs},'http://synthetic','synthetic');sent=json.loads(request.data)
  self.assertLessEqual(len(encoded(sent['attributes'])),14000);self.assertEqual(unpacked(sent['attributes']),attrs);self.assertEqual(attrs,original);self.assertEqual(sent['state'],300)
 def test_full_publisher_uses_bounded_transport_and_keeps_every_sensor(self):
  points=[{'entity_id':'sensor.synthetic_'+str(i),'quantity':'temperature','label':'Syntetické čidlo '+str(i),'value':22,'unit':'°C','quality':'valid'}for i in range(200)];sent=[]
  class Response:
   status=201
   def __enter__(self):return self
   def __exit__(self,*args):return False
  class Opener:
   def open(self,request,**kwargs):sent.append((request.full_url,json.loads(request.data)));return Response()
  payloads={'status.json':{'last_observed_at':'2026-01-15T02:00:00+00:00'},'analytics.json':{'environment':{'points':points}}}
  with patch.object(pub,'settings',return_value=({'ha_base_url':'http://synthetic'},{})),patch.object(pub,'read_token',return_value='synthetic'),patch.object(pub,'_load',side_effect=lambda name:payloads.get(name,{})),patch.object(pub.urllib.request,'build_opener',return_value=Opener()),contextlib.redirect_stdout(io.StringIO()):pub.main()
  records=[p for url,p in sent if url.endswith('/sensor.energie_v4_teploty_pocet')];self.assertEqual(len(records),1);record=records[0];self.assertEqual(record['state'],200);self.assertEqual(len(unpacked(record['attributes'])['sensors']),200)
  self.assertTrue(all(len(encoded(p['attributes']))<=14000 for _,p in sent));self.assertTrue(all('/api/states/'in url for url,_ in sent));self.assertTrue(all(unpacked(p['attributes'])['device_actions']==0 for _,p in sent))
 def test_tampering_is_detected_and_physical_entities_still_rejected(self):
  attrs={'sensors':['teplota '*10000]};sent=json.loads(pub.request('sensor.energie_v4_teploty_pocet',{'state':1,'attributes':attrs},'http://synthetic','synthetic').data)['attributes'];sent['packed_attributes']['sha256']='0'*64
  self.assertRaises(ValueError,unpacked,sent);self.assertRaises(ValueError,pub.request,'number.solax_battery_charge_max_current',{'state':0},'http://synthetic','synthetic')
