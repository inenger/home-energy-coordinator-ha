import copy
from datetime import datetime,timedelta,timezone
import tempfile
from pathlib import Path
import random
import unittest
from energy.core import TZ,instant,digest
from energy.soc_energy import Battery,coordinate_remaining,advance_coordinate
from energy.soc_calibration import fit_pv,Household,validate_household
from energy.soc_planner import plan,solar_periods,prices,simulate,window
from energy.soc_runtime import schema,session_plan,view,observation,inputs
from energy.soc_history import minute_hours
from energy.store import Store,pack
from energy.soc_evidence import seal

MODEL={'discharge_curve':[[0,-1.3],[11,-.35],[15,0],[30,1.1],[50,3.3],[70,5.55],[90,7.65],[95,8.3],[100,8.8]],
       'charge_curve':[[0,-1.5],[11,-.4],[15,0],[30,1.9],[50,4.5],[70,7],[90,9.25],[95,9.35],[100,9.35]],
       'dc_cycle_efficiency':.886,'dc_cycle_low':.85,'grid_efficiency':.9,
       'grid_efficiency_range':[.85,.95],'ac_discharge_efficiency':.977,'solar_ac_dc_efficiency':.966,
       'source_hash':'measured-fixture','fit_period':'2026-07'}


class FixedHouse:
    last_day='2026-10-21'
    def __init__(self,power=.4):self.power=power
    def predict(self,target,temp=None):
        return {'central_kw':self.power,'low_kw':self.power,'high_kw':self.power,'samples':30}


def fixture(pv=50,house=.4,soc=20,season='summer',ev=0):
    day='2026-07-15' if season=='summer' else '2026-01-15'
    now=instant(day+'T02:55:00'+('+02:00' if season=='summer' else '+01:00'))
    versions={'solar':[],'tariff':[]};tariff={'today':[],'tomorrow':[],'today_valid':True,'tomorrow_valid':True}
    for offset in (0,1):
        start=datetime.combine(now.astimezone(TZ).date()+timedelta(days=offset),datetime.min.time(),TZ)
        hourly=[]
        for h in range(24):
            at=start+timedelta(hours=h)
            # Summer starts producing at 05; winter at 09. Total is pv kWh.
            begin=5 if season=='summer' else 9;end=19 if season=='summer' else 15
            kwh=pv/(end-begin) if begin<=h<end else 0
            hourly.append({'period_start':at.isoformat(),'pv_estimate':kwh,'pv_estimate10':kwh,'pv_estimate90':kwh})
            tariff['today' if offset==0 else 'tomorrow'].append({'start':at.isoformat(),'end':(at+timedelta(hours=1)).isoformat(),'price':1 if h in (3,4) else 5})
        versions['solar'].append({'available_at':now.isoformat(),'payload':{'state':str(pv),'unit_of_measurement':'kWh','dataCorrect':True,'detailedHourly':hourly}})
    versions['tariff']=[{'available_at':now.isoformat(),'payload':tariff}]
    inp={'soc':soc,'reserve_soc':15,'reserve_soc_approved':None,'battery_charge_max_dc_kw':7,'battery_discharge_max_dc_kw':7,
         'phase_voltages':[230,230,230],'ev_need_ac_kwh':ev,'ev_max_ac_kw':11,
         'priority':'ev','outdoor_c':20 if season=='summer' else -5,'use_temperature':False}
    return now,inp,{'battery_model':copy.deepcopy(MODEL),'source':{'kind':'test'}},versions,FixedHouse(house)


class EnergyTests(unittest.TestCase):
    def test_curve_is_not_a_linear_capacity(self):
        b=Battery(MODEL)
        self.assertAlmostEqual(b.available(30),1.1)
        self.assertAlmostEqual(b.available(70),5.55)
        self.assertGreater(b.dc_to_target(15,95),b.dc_to_target(15,70))

    def test_energy_conserved_for_random_charge_discharge(self):
        rng=random.Random(45)
        for envelope in (False,True):
            b=Battery(MODEL,envelope)
            for _ in range(200):
                soc=rng.uniform(11,99);e=rng.uniform(0,10)
                new,accepted,loss=b.charge_dc(soc,e)
                self.assertLessEqual(b.available(new)-b.available(soc),accepted+1e-9)
                self.assertAlmostEqual(accepted,b.available(new)-b.available(soc)+loss,places=8)
                after,out=b.discharge_dc(new,100,15)
                self.assertGreaterEqual(after,min(15,soc)-1e-9)
                self.assertLessEqual(out,max(0,b.available(soc))+accepted+1e-8)

    def test_flat_empirical_charge_curve_cannot_create_energy(self):
        b=Battery(MODEL,True);new,accepted,loss=b.charge_dc(95,0)
        self.assertAlmostEqual(new,95);self.assertEqual(accepted,0)
        self.assertGreater(b.dc_to_target(95,100),0)

    def test_coordinate_replay_caps_at_target(self):
        b=Battery(MODEL);s=b.snapshot();need=coordinate_remaining(s,20,30)
        self.assertAlmostEqual(advance_coordinate(s,20,need/.9,30),30)
        self.assertAlmostEqual(advance_coordinate(s,20,100,30),30)

    def test_reject_non_monotone(self):
        m=copy.deepcopy(MODEL);m['discharge_curve'][3][1]=0
        with self.assertRaises(ValueError):Battery(m)


class PlannerTests(unittest.TestCase):
    def run_plan(self,**kwargs):
        now,inp,h,v,house=fixture(**kwargs)
        return plan(now,inp,h,{},house,v)

    def test_sunny_summer_skips_grid_charge(self):
        r=self.run_plan(pv=50,house=.25,soc=20)
        self.assertEqual(r['status'],'conditional_shadow_plan')
        self.assertEqual(r['target_soc_pct'],0)
        self.assertEqual(r['device_actions'],0);self.assertFalse(r['live_ready'])
        self.assertIsNone(r['assumptions']['reserve_soc_approved'])

    def test_cold_low_solar_selects_high_soc_without_offgrid_requirement(self):
        r=self.run_plan(pv=6,house=1.5,soc=20,season='winter')
        self.assertGreaterEqual(r['target_soc_pct'],90)
        self.assertGreater(r['selected']['scenarios']['central']['import_ac_kwh'],10)

    def test_start_below_reference_must_restore_reserve(self):
        r=self.run_plan(pv=50,house=.25,soc=11)
        self.assertGreater(r['target_soc_pct'],0)
        self.assertGreaterEqual(r['soc_at_05_estimate'],15)

    def test_ev_need_is_fulfilled_for_comparable_candidates(self):
        r=self.run_plan(pv=6,house=.7,soc=20,season='winter',ev=12)
        self.assertEqual(r['status'],'conditional_shadow_plan')
        for x in r['selected']['scenarios'].values():self.assertLessEqual(x['unserved_ev_ac_kwh'],.05)

    def test_impossible_ev_demand_not_claimed_saving(self):
        r=self.run_plan(ev=80)
        self.assertEqual(r['status'],'partial_shadow_plan')
        self.assertGreater(r['ev_deficit_ac_kwh']['central'],0)
        self.assertFalse(r['demand_fully_met'])

    def test_missing_ev_calibration_is_not_zero(self):
        now,i,h,v,house=fixture();i['ev_need_ac_kwh']=None
        r=plan(now,i,h,{},house,v)
        self.assertIn('ev_need_ac_kwh',r['missing_inputs']);self.assertIsNone(r['target_soc_pct'])

    def test_missing_hour_in_tariff_blocks_instead_of_zero(self):
        now,i,h,v,house=fixture();v['tariff'][0]['payload']['today'].pop(9)
        r=plan(now,i,h,{},house,v)
        self.assertEqual(r['status'],'waiting_for_inputs');self.assertIsNone(r['target_soc_pct'])

    def test_future_forecast_and_future_tariff_rejected(self):
        now,i,h,v,house=fixture()
        for p in v['solar']:p['available_at']=(now+timedelta(minutes=1)).isoformat()
        self.assertEqual(solar_periods(v['solar'],now),[])
        v['tariff'][0]['available_at']=(now+timedelta(seconds=1)).isoformat()
        self.assertEqual(prices(v['tariff'],now),[])

    def test_half_hour_kw_energy_units_checked(self):
        now,i,h,v,house=fixture(pv=24)
        p=v['solar'][0]['payload'];hourly=p.pop('detailedHourly');p['detailedForecast']=[]
        for r in hourly:
            for minute in (0,30):p['detailedForecast'].append({**r,'period_start':(instant(r['period_start'])+timedelta(minutes=minute)).isoformat()})
        rows=solar_periods([v['solar'][0]],now)
        self.assertEqual(len(rows),48);self.assertAlmostEqual(sum(r['kw']*.5 for r in rows),24)
        p['state']='48';self.assertEqual(solar_periods([v['solar'][0]],now),[])

    def test_negative_prices_are_valid_and_conserved(self):
        now,i,h,v,house=fixture(pv=0,house=.5)
        for p in v['tariff'][0]['payload']['today']:
            if instant(p['start']).astimezone(TZ).hour in (3,4):p['price']=-1
        r=plan(now,i,h,{},house,v)
        self.assertEqual(r['status'],'conditional_shadow_plan')
        c=r['selected']['scenarios']['central'];self.assertGreater(c['grid_charge_ac_kwh'],0)

    def test_terminal_inventory_credit_is_common_and_explicit(self):
        r=self.run_plan();self.assertEqual(r['terminal_price_czk_kwh'],1)
        for candidate in r['candidates']:
            x=candidate['scenarios']['central']
            self.assertAlmostEqual(x['inventory_adjusted_cost_czk'],x['import_cost_czk']-x['terminal_inventory_credit_czk'])

    def test_dst_window_is_two_real_hours_after_transition(self):
        for text in ['2026-03-29T01:55:00+01:00','2026-10-25T02:55:00+02:00']:
            day,start,end,horizon=window(instant(text))
            self.assertEqual((end-start).total_seconds(),7200)
            self.assertEqual(start.astimezone(TZ).hour,3)

    def test_compact_view_omits_private_raw_history_and_full_timeline(self):
        r=self.run_plan();v=view(r)
        self.assertNotIn('input_snapshot',v);self.assertNotIn('timeline',v)
        self.assertLess(len(__import__('json').dumps(v)),20000)

    def test_session_uses_only_prior_same_day_recent_decision(self):
        r=self.run_plan();at=r['issued_at']
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'s.sqlite');schema(st.db)
            with st.db:st.db.execute('INSERT INTO soc_decisions VALUES(?,?,?,?)',(at,r['day'],r['decision_hash'],pack(r)))
            self.assertEqual(session_plan(st,r['day'],(instant(at)+timedelta(minutes=5)).isoformat())['target_soc_pct'],0)
            self.assertIsNone(session_plan(st,r['day'],(instant(at)-timedelta(seconds=1)).isoformat()))
            self.assertIsNone(session_plan(st,'2026-07-16',at));st.close()


class CalibrationTests(unittest.TestCase):
    def test_forecast_fitting_has_chronological_holdout(self):
        pairs=[]
        for d in range(50):
            at=instant('2026-07-01T12:00:00+02:00')+timedelta(days=d)
            pairs.append({'target':at.isoformat(),'day':at.date().isoformat(),
                'available_at':(at+timedelta(hours=1)).isoformat(),
                'forecast_available_at':(at-timedelta(hours=9)).isoformat(),
                'forecast_ac_kwh':2,'actual_ac_proxy_kwh':1.6,'constrained':False})
        models=fit_pv(pairs,instant('2026-08-25T00:00:00+02:00'))
        self.assertTrue(models)
        for m in models.values():
            self.assertTrue(m['accepted']);self.assertAlmostEqual(m['factor'],.8)
            self.assertGreaterEqual(m['test_days'],7);self.assertLess(m['train_before'],'2026-08-20')
        # All contaminated data and outcomes not yet available are unusable.
        self.assertEqual(fit_pv([{**r,'constrained':True} for r in pairs],instant('2026-08-25T00:00:00+02:00')), {})
        self.assertEqual(fit_pv(pairs,instant('2026-07-10T00:00:00+02:00')), {})

    def test_household_excludes_ev_and_today_outcomes(self):
        rows=[]
        for d in range(40):
            at=instant('2026-06-01T08:00:00+02:00')+timedelta(days=d)
            rows.append({'at':at.isoformat(),'available_at':(at+timedelta(hours=1)).isoformat(),
                'day':at.astimezone(TZ).date().isoformat(),'season':'summer','weekend':False,
                'house_without_ev_kwh':.4,'temperature_c':20,'quality':'observed'})
        now=instant('2026-07-15T02:55:00+02:00');model=Household(rows,now)
        self.assertAlmostEqual(model.predict(now.replace(hour=8),20)['central_kw'],.4)

    def test_minute_integrator_never_bridges_gaps_or_adds_ev_twice(self):
        start=instant('2026-10-20T08:00:00+02:00');rows=[]
        for i in range(61):rows.append({'at':(start+timedelta(minutes=i)).isoformat(),
            'house_w':11400,'ev_w':11000,'pv_counter':i*.01,'inverter_w':1000,'export_limit_w':9900,'outdoor_c':10})
        h,p=minute_hours(rows);self.assertAlmostEqual(h[0]['house_without_ev_kwh'],.4)
        self.assertAlmostEqual(p[0]['actual_ac_proxy_kwh'],.6*.966)
        self.assertEqual(minute_hours(rows[:20]+rows[40:])[0],[])
        rows[10]['export_limit_w']=0;self.assertTrue(minute_hours(rows)[1][0]['constrained'])


class RuntimeTests(unittest.TestCase):
    def prepare(self,store,at,target):
        from energy import night,priority
        from test_night import archive
        from test_priority import inputs
        night.ensure_schema(store.db);priority.schema(store.db);schema(store.db)
        archive(store,'2026-10-22T22:01:00+00:00')
        night.record(store,inputs(at),at)
        r=plan(*self.plan_args())
        r.update(day='2026-10-23',issued_at=at,target_soc_pct=target);r=seal(r)
        with store.db:store.db.execute('INSERT INTO soc_decisions VALUES(?,?,?,?)',(at,r['day'],r['decision_hash'],pack(r)))

    def plan_args(self):
        now,i,h,v,house=fixture(season='winter',pv=6,house=1.5)
        return now,i,h,{},house,v

    def test_new_night_uses_empirical_plan_preserves_original_table_capture(self):
        from energy import priority
        from energy.store import unpack
        from test_priority import inputs
        at='2026-10-23T01:00:00+00:00'
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'s.sqlite');self.prepare(s,at,95)
            r=priority.observe(s,inputs(at),at)
            self.assertEqual(r['session']['target_soc_pct'],95)
            self.assertIn('battery_energy_model',r['assumptions'])
            original=unpack(s.db.execute('SELECT payload FROM night_sessions WHERE day=?',('2026-10-23',)).fetchone()[0])
            self.assertEqual(original['target_soc_pct'],80)
            self.assertNotIn('planning_source',original)
            later='2026-10-23T01:00:15+00:00';q=priority.observe(s,inputs(later),later)
            self.assertGreater(q['progress']['models']['selected']['soc_pct'],60)
            self.assertEqual(q['device_actions'],0);s.close()

    def test_legacy_run_does_not_switch_energy_models_after_restart(self):
        from energy import priority,night
        from test_night import archive
        from test_priority import inputs
        at='2026-10-23T01:00:00+00:00'
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'s.sqlite');night.ensure_schema(s.db);archive(s,'2026-10-22T22:01:00+00:00')
            night.record(s,inputs(at),at);priority.observe(s,inputs(at),at)
            later='2026-10-23T01:00:15+00:00';self.prepare(s,later,95)
            r=priority.observe(s,inputs(later),later)
            self.assertEqual(r['session']['target_soc_pct'],80)
            self.assertNotIn('battery_energy_model',r['session']);s.close()

    def test_disabled_planner_cannot_emit_actions(self):
        from energy.soc_runtime import PlannerService
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'s.sqlite')
            r=PlannerService({'planner_enabled':False}).observe(s,[],'2026-10-23T01:00:00+00:00')
            self.assertEqual(r['status'],'disabled');self.assertEqual(r['device_actions'],0);s.close()

    def test_daily_review_with_missing_daylight_does_not_validate_pv_error(self):
        from energy.soc_runtime import review
        start=instant('2026-10-23T00:00:00+02:00')
        now,i,h,v,house=fixture();r=plan(now,i,h,{},house,v)
        r.update(day='2026-10-23',issued_at='2026-10-23T00:55:00+00:00',decision_hash='pre-window')
        r['forecast_periods']=[{'start':(start+timedelta(hours=j)).timestamp(),
            'end':(start+timedelta(hours=j+1)).timestamp(),'raw_pv_kw':1 if 8<=j<20 else 0,
            'pv_ac_kw':1 if 8<=j<20 else 0,'house_kw':.4} for j in range(24)]
        r=seal(r)
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'s.sqlite');schema(s.db)
            with s.db:
                s.db.execute('INSERT INTO soc_decisions VALUES(?,?,?,?)',(r['issued_at'],r['day'],r['decision_hash'],pack(r)))
                for j in range(721):
                    at=(start+timedelta(minutes=j)).isoformat()
                    row={'at':at,'house_w':400,'ev_w':0,'pv_counter':j*.01,'inverter_w':1000,'export_limit_w':9900}
                    s.db.execute('INSERT INTO soc_observations VALUES(?,?,?)',(at,r['day'],pack(row)))
            rows=review(s,{'days':[{'day':'2026-10-23','pv_kwh':8}]},'2026-10-24T00:30:00+00:00')
            self.assertEqual(rows[0]['constraint_status'],'unknown_coverage')
            self.assertIsNone(rows[0]['pv_error_ac_proxy_kwh'])
            self.assertIsNone(rows[0]['measured_savings_czk']);self.assertFalse(rows[0]['plan_executed']);s.close()


if __name__=='__main__':unittest.main()
