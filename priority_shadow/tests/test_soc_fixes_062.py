"""End-to-end regressions for N01-N07 from the independent 0.6.1 audit."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import random
import tempfile
import unittest

from energy.core import TZ,instant
from energy import priority,night
from energy.soc_history import fit_ev,minute_hours
from energy.soc_runtime import schema,record_decision,session_plan,review
from energy.soc_planner import simulate
from energy.store import Store,pack
from test_soc_fixes import MODEL,BASE,START,END,row


def ev_rows(days=5,gap=False):
    rows=[]
    for d in range(days):
        at=START+timedelta(days=d)
        rows.append({'at':at.isoformat(),'power_w':0.,'energy_total_kwh':100*d,'soc':20.})
        for m in range(1,32):
            rows.append({'at':(at+timedelta(minutes=m)+(timedelta(hours=2) if gap else timedelta())).isoformat(),
                'power_w':12000. if m<=20 else 0.,'energy_total_kwh':100*d+min(m,20)*.4,
                'soc':20.+min(m,20)*.5})
    return rows


class SessionRecovery(unittest.TestCase):
    def make(self,path):
        s=Store(path);schema(s.db);priority.schema(s.db);night.ensure_schema(s.db)
        return s

    def test_N01_orphan_legacy_is_blocked_and_original_survives_restart(self):
        for status in ('calculation_unavailable','disabled','no_comparable_feasible_plan'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as td:
                path=Path(td)/'db';s=self.make(path)
                original=pack({'day':'2026-06-15','forecast_kwh':6,'target_soc_pct':80,'status':'captured'})
                s.db.execute('INSERT INTO priority_sessions VALUES(?,?)',('2026-06-15',original))
                record_decision(s,{'issued_at':START.isoformat(),'day':'2026-06-15','status':status,'target_soc_pct':None})
                s.close();s=self.make(path)
                result=priority.effective_session(s,'2026-06-15',START.isoformat(),{},True)
                self.assertIsNone(result['target_soc_pct']);self.assertFalse(result['soc_plan_valid'])
                self.assertEqual(priority.allocate({},START.isoformat(),result,20,'battery')['reason'],'invalid_soc_plan')
                self.assertEqual(s.db.execute('SELECT payload FROM priority_sessions').fetchone()[0],original);s.close()

    def test_N01_running_legacy_keeps_its_frozen_model(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(Path(td)/'db');frozen={'forecast_kwh':6,'target_soc_pct':80}
            s.db.execute('INSERT INTO priority_sessions VALUES(?,?)',('2026-06-15',pack(frozen)))
            s.db.execute('INSERT INTO priority_runs VALUES(?,?)',('2026-06-15',pack({'soc_plan_required':False})))
            self.assertEqual(priority.effective_session(s,'2026-06-15',START.isoformat(),{},True),frozen);s.close()

    def test_N01_valid_new_plan_can_replace_orphan_in_memory_only(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(Path(td)/'db');frozen=pack({'forecast_kwh':6,'target_soc_pct':80})
            s.db.execute('INSERT INTO priority_sessions VALUES(?,?)',('2026-06-15',frozen))
            record_decision(s,{'issued_at':START.isoformat(),'day':'2026-06-15','status':'conditional_shadow_plan',
                'target_soc_pct':30,'horizon_complete':True,'policy':'test','battery_energy_model':{'source_hash':'test'},'assumptions':{}})
            r=priority.effective_session(s,'2026-06-15',START.isoformat(),{},True)
            self.assertEqual(r['target_soc_pct'],30);self.assertTrue(r['soc_plan_valid'])
            self.assertEqual(s.db.execute('SELECT payload FROM priority_sessions').fetchone()[0],frozen);s.close()


class EVContinuity(unittest.TestCase):
    def test_N02_complete_sessions_still_fit(self):
        r=fit_ev(ev_rows());self.assertEqual(r['status'],'candidate_for_shadow')
        self.assertEqual(len(r['sessions']),5);self.assertAlmostEqual(r['ac_kwh_per_soc_pct'],.8)
        self.assertTrue(all(s['continuity_verified'] for s in r['sessions']))

    def test_N02_gap_cannot_reuse_previous_inactive_sample(self):
        r=fit_ev(ev_rows(gap=True));self.assertEqual(r['sessions'],[])
        self.assertIsNone(r['ac_kwh_per_soc_pct']);self.assertGreater(r['quality_rejections']['discontinuous_interval'],0)

    def test_N02_bad_power_cannot_seed_a_partial_active_session(self):
        rows=ev_rows();rows[0]['power_w']=None
        r=fit_ev(rows);self.assertEqual(len(r['sessions']),4);self.assertIsNone(r['ac_kwh_per_soc_pct'])

    def test_N02_gap_inside_active_session_discards_entire_session(self):
        rows=ev_rows(days=1)
        for r in rows[5:]:r['at']=(instant(r['at'])+timedelta(minutes=5)).isoformat()
        self.assertEqual(fit_ev(rows)['sessions'],[])

    def test_N02_counter_reset_invalidates_active_session(self):
        rows=ev_rows(days=1)
        for r in rows[5:]:r['energy_total_kwh']-=2
        self.assertEqual(fit_ev(rows)['sessions'],[])


class ACBalance(unittest.TestCase):
    def run_case(self,rows,inputs,target=0):
        return simulate(rows,inputs,MODEL,target,'central',START,END,1.)

    def test_N03_pv_offsets_ev_and_not_grid_import(self):
        r=self.run_case([row(house=.1,pv=2)],{**BASE,'soc':100,'battery_charge_max_dc_kw':0,'ev_need_ac_kwh':5.5})
        self.assertAlmostEqual(r['import_ac_kwh'],4.55);self.assertAlmostEqual(r['unused_pv_ac_kwh'],0)
        self.assertAlmostEqual(r['pv_to_ev_ac_kwh'],.95)

    def test_N03_short_ev_does_not_net_later_export_against_earlier_import(self):
        r=self.run_case([row(house=.1,pv=2)],{**BASE,'soc':100,'battery_charge_max_dc_kw':0,'ev_need_ac_kwh':.1})
        expected_pv=1.9*.1/11
        self.assertAlmostEqual(r['pv_to_ev_ac_kwh'],expected_pv)
        self.assertAlmostEqual(r['import_ac_kwh'],.1-expected_pv)
        self.assertAlmostEqual(r['unused_pv_ac_kwh'],.95-expected_pv)

    def test_N04_common_inverter_limit_includes_battery_discharge(self):
        for pv in (0,3,10,15):
            with self.subTest(pv=pv):
                r=self.run_case([row(END,house=15,pv=pv)],{**BASE,'soc':100,'ev_need_ac_kwh':0,'inverter_ac_limit_kw':10})
                self.assertLessEqual(r['timeline'][0]['inverter_ac_kw'],10+1e-8)
                self.assertGreaterEqual(r['import_ac_kwh'],2.5-1e-8)
                if pv==10:self.assertEqual(r['discharge_ac_kwh'],0)

    def test_N03_N04_random_segment_and_energy_balance(self):
        rng=random.Random(622)
        for _ in range(500):
            eta=.966;model={**MODEL,'solar_ac_dc_efficiency':eta,'ac_discharge_efficiency':.977}
            i={**BASE,'soc':rng.uniform(15,100),'ev_need_ac_kwh':rng.uniform(0,8),
               'priority':rng.choice(['ev','battery']),'battery_charge_max_dc_kw':rng.uniform(0,7),
               'battery_discharge_max_dc_kw':rng.uniform(0,7),'inverter_ac_limit_kw':rng.uniform(1,10)}
            at=rng.choice([START,END]);house=rng.uniform(0,15);pv=rng.uniform(0,15)
            r=simulate([row(at,house=house,pv=pv)],i,model,95,'central',START,END,1.)
            t=r['timeline'][0]
            self.assertLessEqual(t['inverter_ac_kw'],i['inverter_ac_limit_kw']+1e-7)
            self.assertAlmostEqual(t['pv_ac_kwh']+t['import_ac_kwh']+t['discharge_ac_kwh'],
                t['house_ac_kwh']+t['ev_ac_kwh']+t['charge_grid_ac_kwh']+t['pv_to_battery_ac_kwh']+t['unused_pv_ac_kwh'])
            for s in t['charge_segments']:
                self.assertAlmostEqual(s['ev_grid_ac_kw']+s['pv_to_ev_ac_kw'],s['ev_ac_kw'])
                self.assertLessEqual(s['battery_total_dc_kw'],i['battery_charge_max_dc_kw']+1e-7)
                self.assertLessEqual(s['battery_pv_dc_kw']*eta+s['pv_to_ev_ac_kw'],max(0,min(pv,i['inverter_ac_limit_kw'])-house)+1e-7)


def observations(day,limit=9900):
    begin=datetime.fromisoformat(day+'T00:00:00').replace(tzinfo=TZ).astimezone(timezone.utc)
    end=datetime.fromisoformat(day+'T00:00:00').replace(tzinfo=TZ)+timedelta(days=1)
    count=int((end.astimezone(timezone.utc)-begin).total_seconds()/60)
    return [{'at':(begin+timedelta(minutes=m)).isoformat(),'house_w':400.,'ev_w':0.,
        'pv_counter':max(0.,min(12.,(m-360)/60)),'inverter_w':1000.,'export_limit_w':limit}
        for m in range(count+1)]


class ReviewValidity(unittest.TestCase):
    def make(self,td,day='2026-10-24'):
        s=Store(Path(td)/'db');schema(s.db);obs=observations(day)
        s.db.executemany('INSERT INTO soc_observations VALUES(?,?,?)',[(x['at'],day,pack(x)) for x in obs]);s.db.commit()
        return s

    def proposal(self,s,day='2026-10-24',hour_end=27,complete=True,issued=None):
        begin=datetime.fromisoformat(day+'T00:00:00').replace(tzinfo=TZ).astimezone(timezone.utc)
        periods=[{'start':(begin+timedelta(hours=h)).timestamp(),'end':(begin+timedelta(hours=h+1)).timestamp(),
            'house_kw':.4,'raw_pv_kw':1. if 6<=h<18 else 0.,'pv_ac_kw':.966 if 6<=h<18 else 0.} for h in range(3,hour_end)]
        return record_decision(s,{'day':day,'issued_at':issued or (begin+timedelta(hours=2,minutes=55)).isoformat(),
            'status':'conditional_shadow_plan','target_soc_pct':80,'horizon_complete':complete,'forecast_periods':periods})

    def test_N05_incomplete_plan_never_creates_a_daily_error(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(td);p=self.proposal(s,hour_end=17,complete=False)
            self.assertIsNone(session_plan(s,p['day'],(instant(p['issued_at'])+timedelta(minutes=5)).isoformat()))
            self.assertEqual(review(s,{'days':[{'day':p['day'],'pv_kwh':12}]},'2026-10-25T08:00:00+00:00'),[]);s.close()

    def test_N05_valid_common_intervals_have_zero_error(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(td);p=self.proposal(s)
            r=review(s,{'days':[{'day':p['day'],'pv_kwh':12}]},'2026-10-25T08:00:00+00:00')[0]
            self.assertEqual(r['constraint_status'],'clear_in_covered_daylight')
            self.assertAlmostEqual(r['pv_error_ac_proxy_kwh'],0)
            self.assertAlmostEqual(r['comparison_forecast_ac_kwh'],r['comparison_actual_ac_proxy_kwh']);s.close()

    def test_N05_tampered_latest_decision_cannot_create_review(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(td);p=self.proposal(s);p['target_soc_pct']=95
            s.db.execute('UPDATE soc_decisions SET payload=?',(pack(p),));s.db.commit()
            self.assertEqual(review(s,{'days':[{'day':p['day'],'pv_kwh':12}]},'2026-10-25T08:00:00+00:00'),[]);s.close()

    def test_N05_newer_invalid_decision_revokes_the_review_as_well(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(td);p=self.proposal(s)
            record_decision(s,{'day':p['day'],'issued_at':(instant(p['issued_at'])+timedelta(minutes=3)).isoformat(),
                              'status':'calculation_unavailable','target_soc_pct':None})
            self.assertEqual(review(s,{'days':[{'day':p['day'],'pv_kwh':12}]},'2026-10-25T08:00:00+00:00'),[]);s.close()

    def test_N06_autumn_first_0255_is_not_a_pre_window_review(self):
        with tempfile.TemporaryDirectory() as td:
            day='2026-10-25';s=self.make(td,day);self.proposal(s,day,issued='2026-10-25T00:56:00+00:00')
            self.assertEqual(review(s,{'days':[{'day':day,'pv_kwh':12}]},'2026-10-26T08:00:00+00:00'),[]);s.close()

    def test_N06_autumn_second_0255_is_accepted_and_evidence_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            day='2026-10-25';s=self.make(td,day);p=self.proposal(s,day,hour_end=28,issued='2026-10-25T01:55:00+00:00')
            reports=review(s,{'days':[{'day':day,'pv_kwh':12}]},'2026-10-26T08:00:00+00:00')
            self.assertEqual(len(reports),1);self.assertEqual(reports[0]['decision_hash'],p['decision_hash'])
            prior=s.db.execute('SELECT payload FROM soc_reviews').fetchone()[0]
            review(s,{'days':[{'day':day,'pv_kwh':99}]},'2026-10-26T08:10:00+00:00')
            self.assertEqual(prior,s.db.execute('SELECT payload FROM soc_reviews').fetchone()[0]);s.close()

    def test_N07_unknown_constraint_does_not_validate_daily_error(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.make(td);self.proposal(s);s.db.execute('DELETE FROM soc_observations')
            obs=observations('2026-10-24',None)
            s.db.executemany('INSERT INTO soc_observations VALUES(?,?,?)',[(x['at'],'2026-10-24',pack(x)) for x in obs]);s.db.commit()
            r=review(s,{'days':[{'day':'2026-10-24','pv_kwh':12}]},'2026-10-25T08:00:00+00:00')[0]
            self.assertEqual(r['constraint_status'],'unknown_coverage');self.assertIsNone(r['pv_error_ac_proxy_kwh']);s.close()


class IndependentQuality(unittest.TestCase):
    def test_N07_house_survives_each_unrelated_pv_input_failure(self):
        rows=observations('2026-10-24')[:61]
        for key in ('pv_counter','inverter_w','export_limit_w'):
            with self.subTest(key=key):
                house,pv=minute_hours([{**r,key:None} for r in rows])
                self.assertEqual(len(house),1);self.assertAlmostEqual(house[0]['house_without_ev_kwh'],.4)
                if key!='pv_counter':self.assertIsNone(pv[0]['constrained'])
                else:self.assertEqual(pv,[])

    def test_N07_pv_survives_house_failure_but_unknown_constraint_is_not_clear(self):
        rows=observations('2026-10-24')[360:421]
        house,pv=minute_hours([{**r,'house_w':None,'export_limit_w':None} for r in rows])
        self.assertEqual(house,[]);self.assertEqual(len(pv),1);self.assertIsNone(pv[0]['constrained'])
        self.assertAlmostEqual(pv[0]['actual_ac_proxy_kwh'],.966)

    def test_N07_a_single_unknown_constraint_interval_prevents_clear_label(self):
        rows=observations('2026-10-24')[:61];rows[10]['export_limit_w']=None
        house,pv=minute_hours(rows);self.assertEqual(len(house),1);self.assertIsNone(pv[0]['constrained'])
        self.assertLess(pv[0]['constraint_coverage_seconds'],pv[0]['coverage_seconds'])


if __name__=='__main__':unittest.main()
