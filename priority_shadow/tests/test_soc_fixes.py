"""Regressions for each independent 0.6.0 audit finding."""
import copy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
from energy import priority,night
from energy.core import TZ,instant,digest
from energy.soc_calibration import validate_household,pre_window,season
from energy.soc_energy import Battery
from energy.soc_evidence import seal,verify
from energy.soc_history import minute_hours,covered_forecast
from energy.soc_planner import simulate,slots,plan
from energy.soc_runtime import schema,session_plan,record_decision,PlannerService,view,inputs
from energy.store import Store,pack,unpack
from test_soc_planner import fixture
from test_priority import inputs as phase_states
from test_night import archive

MODEL={'discharge_curve':[[0,-1.5],[15,0],[100,8.5]],
       'charge_curve':[[0,-1.5/.9],[15,0],[100,8.5/.9]],
       'dc_cycle_efficiency':.9,'dc_cycle_low':.9,'grid_efficiency':.9,
       'grid_efficiency_range':[.9,.9],'ac_discharge_efficiency':1.,'solar_ac_dc_efficiency':1.,
       'source_hash':'independent-analytic-fixture'}
START=instant('2026-06-15T03:00:00+02:00');END=START+timedelta(hours=2)
BASE={'soc':15.,'reserve_soc':15.,'battery_charge_max_dc_kw':7.,'battery_discharge_max_dc_kw':7.,
      'phase_voltages':[230.]*3,'priority':'battery','ev_need_ac_kwh':4.,'ev_max_ac_kw':11.}


def row(at=START,house=2.,pv=0.,hours=.5):
    return {'start':at.timestamp(),'end':at.timestamp()+hours*3600,'hours':hours,
            'house_kw':house,'house_low_kw':house,'house_high_kw':house,
            'pv_ac_kw':pv,'pv_low_kw':pv,'pv_high_kw':pv,'price':3.}


class PowerRegressions(unittest.TestCase):
    def run_case(self,rows=None,inputs=None,target=95):
        return simulate(rows or [row()],inputs or BASE,MODEL,target,'central',START,END,1.)

    def test_F02_no_subminimum_ev_alongside_maximum_battery(self):
        r=self.run_case();segments=r['timeline'][0]['charge_segments']
        self.assertEqual(r['timeline'][0]['ev_ac_kwh'],0)
        for s in segments:self.assertTrue(s['ev_ac_kw']==0 or s['ev_ac_kw']>=4.14-1e-8)

    def test_F02_planner_and_replay_use_same_instantaneous_allocation(self):
        def point(value):return {'value':value,'quality':'valid','age_seconds':1}
        pp={k:point(v) for k,v in {'battery_v':7000/30,'battery_limit_a':30,'ev_w':11000}.items()}
        for phase in (1,2,3):
            pp.update({f'grid_l{phase}_w':point(-13000/3),f'inverter_l{phase}_w':point(0),
                       f'voltage_l{phase}_v':point(230),f'ev_l{phase}_w':point(11000/3)})
        allocated=priority.allocate(pp,START.isoformat(),{'forecast_kwh':6,'target_soc_pct':95,
                   'battery_energy_model':Battery(MODEL).snapshot()},15,'battery')
        s=self.run_case()['timeline'][0]['charge_segments'][0]
        self.assertAlmostEqual(s['ev_ac_kw']*1000,allocated['ev_ac_w'])
        self.assertAlmostEqual(s['battery_grid_dc_kw']/.9*1000,allocated['battery_ac_w'])

    def test_F02_short_ev_completion_is_a_real_segment_and_frees_room(self):
        r=self.run_case(inputs={**BASE,'priority':'ev','ev_need_ac_kwh':.1})
        segments=r['timeline'][0]['charge_segments']
        self.assertAlmostEqual(r['timeline'][0]['ev_ac_kwh'],.1)
        self.assertAlmostEqual(sum(s['hours'] for s in segments),.5)
        self.assertEqual(segments[0]['ev_ac_kw'],11)
        self.assertEqual(segments[-1]['ev_ac_kw'],0)
        self.assertGreater(segments[-1]['battery_grid_dc_kw'],segments[0]['battery_grid_dc_kw'])

    def test_F02_ev_max_below_minimum_is_not_treated_as_delivered(self):
        r=self.run_case(inputs={**BASE,'ev_max_ac_kw':3,'ev_need_ac_kwh':.1})
        self.assertEqual(r['timeline'][0]['ev_ac_kwh'],0)
        self.assertAlmostEqual(r['unserved_ev_ac_kwh'],.1)

    def test_F03_all_sources_share_charge_port_capacity(self):
        i={**BASE,'battery_charge_max_dc_kw':2,'ev_need_ac_kwh':0}
        r=self.run_case([row(START+timedelta(hours=1.5),house=.1,pv=.5)],i)
        self.assertLessEqual((r['grid_charge_ac_kwh']*.9+r['pv_to_battery_ac_equivalent_kwh'])/.5,2+1e-9)
        self.assertTrue(all(s['battery_total_dc_kw']<=2+1e-9 for s in r['timeline'][0]['charge_segments']))

    def test_F03_random_physical_and_energy_constraints(self):
        rng=random.Random(179)
        for _ in range(300):
            i={**BASE,'soc':rng.uniform(15,90),'battery_charge_max_dc_kw':rng.uniform(0,9),
               'battery_discharge_max_dc_kw':rng.uniform(0,9),'priority':rng.choice(['ev','battery']),
               'ev_need_ac_kwh':rng.uniform(0,12)}
            r=self.run_case([row(house=rng.uniform(.1,5),pv=rng.uniform(0,4))],i)
            t=r['timeline'][0]
            for s in t['charge_segments']:
                self.assertLessEqual(s['battery_total_dc_kw'],i['battery_charge_max_dc_kw']+1e-7)
                self.assertLessEqual(s['battery_grid_dc_kw']/.9+s['ev_ac_kw'],s['room_ac_kw']+1e-7)
                self.assertTrue(s['ev_ac_kw']==0 or s['ev_ac_kw']>=4.14-1e-7)
            self.assertAlmostEqual(t['pv_ac_kwh']+t['import_ac_kwh']+t['discharge_ac_kwh'],
                t['house_ac_kwh']+t['ev_ac_kwh']+t['charge_grid_ac_kwh']+t['pv_to_battery_ac_kwh']+t['unused_pv_ac_kwh'])
            self.assertLessEqual(r['grid_charge_ac_kwh']*.9+r['pv_to_battery_ac_equivalent_kwh'],i['battery_charge_max_dc_kw']*.5+1e-7)

    def test_F05_zero_charge_limit_does_not_block_discharge(self):
        r=self.run_case([row(END,house=1)],{**BASE,'soc':80,'battery_charge_max_dc_kw':0,'ev_need_ac_kwh':0},0)
        self.assertAlmostEqual(r['discharge_ac_kwh'],.5)
        self.assertAlmostEqual(r['import_ac_kwh'],0)

    def test_F05_zero_discharge_limit_is_respected_independently(self):
        r=self.run_case([row(END,house=1)],{**BASE,'soc':80,'battery_discharge_max_dc_kw':0,'ev_need_ac_kwh':0},0)
        self.assertEqual(r['discharge_ac_kwh'],0);self.assertAlmostEqual(r['import_ac_kwh'],.5)

    def test_missing_directional_limit_blocks_instead_of_using_charge_limit(self):
        now,i,h,v,house=fixture();del i['battery_discharge_max_dc_kw']
        self.assertIn('battery_discharge_max_dc_kw',plan(now,i,h,{},house,v)['missing_inputs'])

    def test_late_window_cannot_claim_unreachable_target(self):
        now,i,h,v,house=fixture(season='winter',pv=0,house=1)
        now=now+timedelta(hours=1,minutes=5);i['battery_charge_max_dc_kw']=.1
        r=plan(now,i,h,{},house,v)
        for c in r.get('candidates',[]):
            if c['target_soc_pct']>=50:self.assertFalse(c['feasible_all_scenarios'])

    def test_cover_requires_real_hour_even_with_quarter_hour_slots(self):
        i={**BASE,'ev_need_ac_kwh':0};rows=[row(END+timedelta(minutes=15*j),house=1,pv=2,hours=.25) for j in range(4)]
        self.assertIsNone(self.run_case(rows[:2],i,0)['first_sustained_pv_cover_at'])
        self.assertEqual(instant(self.run_case(rows,i,0)['first_sustained_pv_cover_at']),END)


class WeatherRegressions(unittest.TestCase):
    def data(self,match=True):
        start=instant('2026-05-01T00:00:00+02:00');hours=[];forecasts=[]
        for d in range(80):
            day=start+timedelta(days=d);temperature=10 if d%2 else 30
            rows=[]
            for hour in range(24):
                at=day+timedelta(hours=hour)
                hours.append({'at':at.isoformat(),'available_at':(at+timedelta(hours=1)).isoformat(),
                    'day':day.date().isoformat(),'season':season(at),'weekend':day.weekday()>=5,
                    'house_without_ev_kwh':1 if temperature==10 else 3,'temperature_c':temperature,'quality':'observed'})
                rows.append({'datetime':at.isoformat(),'temperature':temperature if match else 40-temperature})
            forecasts.append({'available_at':pre_window(day.date().isoformat()).isoformat(),'hash':str(d),
                'payload':{'units':{'temperature_unit':'°C'},'forecast':rows}})
        return hours,forecasts,start+timedelta(days=81)

    def test_F01_no_weather_means_temperature_candidate_disabled(self):
        hours,weather,now=self.data()
        r=validate_household(hours,now)
        self.assertFalse(r['use_temperature']);self.assertEqual(r['test_hours'],0)

    def test_F01_predictive_archived_weather_can_pass(self):
        hours,weather,now=self.data()
        r=validate_household(hours,now,weather)
        self.assertTrue(r['use_temperature']);self.assertGreaterEqual(r['test_hours'],72)
        self.assertEqual(r['feature_source'],'archived_weather_asof_02:55')

    def test_F01_actual_future_temperature_cannot_rescue_bad_forecast(self):
        hours,weather,now=self.data(False)
        r=validate_household(hours,now,weather)
        self.assertFalse(r['use_temperature']);self.assertGreater(r['candidate_mae_kw'],r['reference_mae_kw'])
        changed=copy.deepcopy(hours)
        for x in changed:
            if x['day']>=r['train_before']:x['temperature_c']=-99999
        self.assertEqual(validate_household(changed,now,weather),r)

    def test_F01_later_forecast_versions_are_not_available(self):
        hours,weather,now=self.data()
        for x in weather:x['available_at']=(instant(x['available_at'])+timedelta(minutes=6)).isoformat()
        r=validate_household(hours,now,weather)
        self.assertFalse(r['use_temperature']);self.assertEqual(r['test_hours'],0)

    def test_F01_autumn_pre_window_uses_second_0255(self):
        before=pre_window('2026-10-25').astimezone(TZ)
        self.assertEqual(before.hour,2);self.assertEqual(before.minute,55);self.assertEqual(before.fold,1)


class EvidenceRegressions(unittest.TestCase):
    def test_F07_sealing_is_canonical_and_idempotent(self):
        r=seal({'issued_at':START.isoformat(),'x':[1,2]})
        self.assertEqual(r,seal(r));self.assertTrue(verify(r)['verified'])
        self.assertEqual(r['decision_hash'],digest({k:v for k,v in r.items() if k!='decision_hash'}))
        r['x'].append(3);self.assertFalse(verify(r)['verified'])

    def test_F07_full_runtime_metadata_is_hashed_and_legacy_left_readable(self):
        now,i,h,v,house=fixture();r=plan(now,i,h,{},house,v)
        self.assertTrue(verify(r)['verified'])
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'x.sqlite');schema(s.db)
            r['model_version_hash']='new-model';r=record_decision(s,r)
            key,blob=s.db.execute('SELECT hash,payload FROM soc_decisions').fetchone()
            self.assertEqual(key,unpack(blob)['decision_hash']);self.assertTrue(verify(unpack(blob))['verified'])
            self.assertEqual(verify({'decision_hash':'legacy'})['status'],'legacy_unversioned_hash');s.close()

    def make_store(self,path):
        s=Store(path);night.ensure_schema(s.db);priority.schema(s.db);schema(s.db)
        archive(s,'2026-06-14T22:01:00+00:00')
        return s

    def proposal(self,s,at,status='conditional_shadow_plan'):
        r={'day':'2026-06-15','issued_at':at,'status':status,'policy':'soc-energy-scenarios-v2',
           'horizon_complete':True,
           'target_soc_pct':80 if status=='conditional_shadow_plan' else None,
           'battery_energy_model':Battery(MODEL).snapshot(),'assumptions':{'reserve_soc_approved':None}}
        return record_decision(s,r)

    def test_F04_new_invalid_decision_revokes_saved_session_even_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'x.sqlite';s=self.make_store(path);at=START.isoformat()
            good=self.proposal(s,at)
            # Use a frozen session to isolate revocation from forecast acquisition.
            frozen={'day':'2026-06-15','status':'captured','forecast_kwh':6,'target_soc_pct':80,
                    'planning_source':good['policy'],'battery_energy_model':good['battery_energy_model']}
            with s.db:s.db.execute('INSERT INTO priority_sessions VALUES(?,?)',('2026-06-15',pack(frozen)))
            original=s.db.execute('SELECT payload FROM priority_sessions').fetchone()[0]
            later=(START+timedelta(minutes=10)).isoformat();self.proposal(s,later,'no_comparable_feasible_plan')
            self.assertIsNone(session_plan(s,'2026-06-15',later));s.close();s=self.make_store(path)
            for minute in [11,45]:
                time=(START+timedelta(minutes=minute)).isoformat()
                effective=priority.effective_session(s,'2026-06-15',time,{},require_soc_plan=True)
                self.assertIsNone(effective['target_soc_pct']);self.assertFalse(effective['soc_plan_valid'])
                r=priority.allocate({},time,effective,15,'battery')
                self.assertEqual(r['reason'],'invalid_soc_plan');self.assertIsNone(r['battery_ac_w'])
            self.assertEqual(original,s.db.execute('SELECT payload FROM priority_sessions').fetchone()[0]);s.close()

    def test_F04_expired_saved_target_is_not_a_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make_store(Path(td)/'x.sqlite');good=self.proposal(s,START.isoformat())
            frozen={'planning_source':good['policy'],'target_soc_pct':80,'forecast_kwh':6}
            with s.db:s.db.execute('INSERT INTO priority_sessions VALUES(?,?)',('2026-06-15',pack(frozen)))
            r=priority.effective_session(s,'2026-06-15',(START+timedelta(minutes=31)).isoformat(),{},True)
            self.assertIsNone(r['target_soc_pct']);s.close()

    def test_F04_hash_mismatch_cannot_reactivate_an_old_plan(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make_store(Path(td)/'x.sqlite');good=self.proposal(s,START.isoformat())
            later=(START+timedelta(minutes=10)).isoformat();bad=seal({**good,'issued_at':later});bad['target_soc_pct']=95
            with s.db:s.db.execute('INSERT INTO soc_decisions VALUES(?,?,?,?)',(later,'2026-06-15',bad['decision_hash'],pack(bad)))
            self.assertIsNone(session_plan(s,'2026-06-15',later));s.close()

    def test_F04_calculation_error_is_archived_and_revokes_previous_plan(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make_store(Path(td)/'x.sqlite');self.proposal(s,START.isoformat())
            p=PlannerService();later=(START+timedelta(minutes=10)).isoformat()
            with patch.object(p,'refresh',side_effect=RuntimeError('synthetic failure')):r=p.observe(s,[],later)
            self.assertEqual(r['status'],'calculation_unavailable');self.assertIsNone(session_plan(s,'2026-06-15',later))
            latest=unpack(s.db.execute('SELECT payload FROM soc_decisions ORDER BY at DESC LIMIT 1').fetchone()[0])
            self.assertTrue(verify(latest)['verified']);s.close()

    def test_partial_preview_is_not_an_executable_night_replay_plan(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make_store(Path(td)/'x.sqlite');good=self.proposal(s,START.isoformat())
            later=(START+timedelta(minutes=10)).isoformat()
            record_decision(s,{**good,'issued_at':later,'horizon_complete':False})
            self.assertIsNone(session_plan(s,'2026-06-15',later));s.close()


class CoverageAndDisplayRegressions(unittest.TestCase):
    def test_F06_partial_counter_hour_uses_same_forecast_intervals(self):
        points=[{'at':(START+timedelta(minutes=i)).isoformat(),'house_w':400,'ev_w':0,
                 'pv_counter':i/60,'inverter_w':1000,'export_limit_w':9900} for i in range(55)]
        _,actual=minute_hours(points)
        solar=[{'start':START.timestamp(),'end':START.timestamp()+3600,'kw':.966,
                'available_at':(START-timedelta(hours=1)).isoformat(),'source_hash':'pv'}]
        matched=covered_forecast(actual[0],solar)
        self.assertAlmostEqual(actual[0]['coverage_seconds'],3240)
        self.assertAlmostEqual(matched['forecast_ac_kwh'],actual[0]['actual_ac_proxy_kwh'])
        self.assertAlmostEqual(matched['forecast_ac_kwh'],.8694)
        self.assertIsNone(covered_forecast(actual[0],[]))

    def test_F06_disjoint_intervals_do_not_fill_missing_minutes(self):
        actual={'coverage_schema':'common-intervals-v2','coverage_seconds':1800,
                'coverage_intervals':[[0,900],[2700,3600]]}
        solar=[{'start':0,'end':1800,'kw':1,'available_at':'2026-01-01T00:00:00+00:00','source_hash':'a'},
               {'start':1800,'end':3600,'kw':3,'available_at':'2026-01-01T00:00:00+00:00','source_hash':'b'}]
        self.assertAlmostEqual(covered_forecast(actual,solar)['forecast_ac_kwh'],1)

    def test_F08_soc_profile_has_initial_and_true_end_time(self):
        r=simulate([row()],BASE,MODEL,95,'central',START,END,1.)
        v=view({'day':'2026-06-15','timeline':r['timeline']})
        self.assertEqual(instant(v['profile'][0]['at']),START)
        self.assertEqual(v['profile'][0]['soc'],15)
        self.assertEqual(instant(v['profile'][-1]['at']),START+timedelta(minutes=30))
        self.assertAlmostEqual(v['profile'][-1]['soc'],r['timeline'][0]['soc_end'])

    def test_F08_legacy_timestamp_is_converted_without_rewriting_evidence(self):
        old={'at':START.isoformat(),'hours':.5,'house_ac_kwh':1,'pv_ac_kwh':0,'soc':40}
        r=view({'day':'2026-06-15','timeline':[old]})
        self.assertEqual(r['profile'][0]['at'],(START+timedelta(minutes=30)).isoformat())
        self.assertEqual(old['at'],START.isoformat())


if __name__=='__main__':unittest.main()
