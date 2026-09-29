import json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from energy.appliances import discover, positive_delta, summarize
from energy.evmodel import analyze as ev_analyze
from energy.batterymodel import analyze as battery_analyze, SPEC
from energy.pvmodel import calibrate as pv_calibrate, corrected_upcoming
from energy.updater import _version
from energy.webui import PAGE
from energy.publish_status import _safe_state

class ApplianceTests(unittest.TestCase):
    def state(self,eid,state,unit,name):
        return {"entity_id":eid,"state":str(state),"attributes":{"unit_of_measurement":unit,"friendly_name":name}}
    def test_discover_known_plug(self):
        states=[
          self.state("sensor.shellyplus1pm_x_switch_0_power",120,"W","Myčka switch_0 power"),
          self.state("sensor.shellyplus1pm_x_switch_0_energy",12.5,"kWh","Myčka switch_0 energy")]
        d=discover(states)
        self.assertEqual(len(d),1);x=next(iter(d.values()))
        self.assertEqual(x["kind"],"dishwasher");self.assertEqual(x["power_value"],120);self.assertEqual(x["energy_value"],12.5)
    def test_ignore_three_phase_meter(self):
        states=[self.state("sensor.shellypro3em_x_total_active_power",100,"W","TČ")]
        self.assertEqual(discover(states),{})
    def test_energy_delta_physical_limit(self):
        self.assertAlmostEqual(positive_delta(10,10.1,60),.1)
        self.assertIsNone(positive_delta(10,20,60))
    def test_cycle_summary(self):
        now=datetime(2026,9,28,12,tzinfo=timezone.utc);rows=[];e=10
        for minute in range(90):
            p=0 if minute<5 or minute>=70 else 1000
            if p:e+=p/1000/60
            rows.append({"at":(now-timedelta(minutes=90-minute)).isoformat(),"appliance_id":"dish","label":"Myčka","kind":"dishwasher","power_w":p,"energy_kwh":e,"buy_price":3.0})
        s=summarize({"dish":rows},now)["dish"]
        self.assertGreaterEqual(s["cycles_30d"],1);self.assertGreater(s["avg_cycle_kwh"],.5)

class EVTests(unittest.TestCase):
    def test_tariff_weighting(self):
        start=datetime(2026,9,1,tzinfo=timezone.utc);rows=[];e=100
        for i,price in enumerate((2.0,2.0,5.0,5.0)):
            if i:e+=1
            rows.append({"at":(start+timedelta(minutes=15*i)).isoformat(),"power_w":12000,"energy_total_kwh":e,
                         "soc":50+i,"buy_price":price,"odometer_km":1000,"vehicle_energy_total_kwh":300})
        x=ev_analyze(rows,start+timedelta(hours=1))["month"]
        self.assertAlmostEqual(x["home_charge_kwh"],3)
        self.assertAlmostEqual(x["tariff_equivalent_cost_czk"],9)  # Prior price applies forward.
        self.assertAlmostEqual(x["weighted_price_czk_kwh"],3)

class BatteryTests(unittest.TestCase):
    def test_known_spec(self):
        self.assertEqual(SPEC["usable_kwh"],10.4);self.assertEqual(SPEC["nominal_kwh"],11.5)
        self.assertEqual(SPEC["roundtrip_efficiency"],.95)
    def test_capacity_estimate(self):
        start=datetime(2026,9,1,8,tzinfo=timezone.utc);rows=[]
        # Three independent charge episodes, each roughly 10.4 kWh / 100% SOC.
        for day in range(3):
            base=start+timedelta(days=day)
            rows += [
             {"at":base.isoformat(),"soc":20,"input_today_kwh":0,"output_today_kwh":0,"temp_c":25},
             {"at":(base+timedelta(hours=2)).isoformat(),"soc":70,"input_today_kwh":5.2,"output_today_kwh":0,"temp_c":25}]
        x=battery_analyze(rows,start+timedelta(days=4))
        self.assertAlmostEqual(x["effective_capacity_kwh"],10.4,places=1)
        self.assertIsNone(x["soh_pct"])  # Unverified SOC/energy basis does not prove SoH.

class PVTests(unittest.TestCase):
    def test_collecting_without_history(self):
        x=pv_calibrate([],[],datetime(2026,9,28,tzinfo=timezone.utc))
        self.assertEqual(x["status"],"collecting");self.assertEqual(x["fallback_factor"],1)
    def test_bias_correction(self):
        now=datetime(2026,9,28,12,tzinfo=timezone.utc);pv=[];fc=[]
        for d in range(8):
            day=(datetime(2026,9,1,tzinfo=timezone.utc)+timedelta(days=d))
            # Sparse endpoints must not be treated as complete hourly measurements.
            pv += [{"at":day.isoformat(),"energy_today_kwh":0},
                   {"at":(day+timedelta(hours=21)).isoformat(),"energy_today_kwh":8}]
            target=day.date().isoformat()
            payload={"estimate":10.0,"estimate10":7.0,"estimate90":12.0,
                     "detailedHourly":[{"period_start":day.isoformat(),"pv_estimate":0}]}
            fc.append({"available_at":(day-timedelta(hours=12)).isoformat(),"payload":payload})
        x=pv_calibrate(fc,pv,now)
        self.assertEqual(x["status"],"collecting");self.assertEqual(x["fallback_factor"],1)

class PublishRegressionTests(unittest.TestCase):
    def test_none_becomes_unknown(self):
        self.assertEqual(_safe_state(None),"unknown")
    def test_nonfinite_becomes_unknown(self):
        self.assertEqual(_safe_state(float("nan")),"unknown")
        self.assertEqual(_safe_state(float("inf")),"unknown")
    def test_normal_value_preserved(self):
        self.assertEqual(_safe_state(12.3),12.3)

class UpdateAndUITests(unittest.TestCase):
    def test_semver(self):self.assertGreater(_version("0.3.0"),_version("0.2.9"))
    def test_ui_local_only(self):
        self.assertIn("Spotřebiče",PAGE);self.assertNotIn("https://",PAGE);self.assertNotIn("http://",PAGE)

if __name__=="__main__":unittest.main()
