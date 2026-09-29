import unittest, tempfile, os, json
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone, timedelta
from energy.collector import settings, read_token, ReadOnlyHA
from energy.calibration import train_candidate,residual_w,make_hourly_points
from energy.core import season_context

CFG={'enabled':True,'mode':'candidate_only','min_complete_days':14,'history_days':45,'holdout_days':4,'half_life_days':14,'minimum_improvement_fraction':.03,'max_correction_fraction':.15}

def make_points(days=24, trend=15):
    out=[]
    for d in range(days):
        dt=datetime(2026,9,1,tzinfo=timezone.utc)+timedelta(days=d)
        for h in range(24):
            out.append({'date':dt.date().isoformat(),'season':'autumn','workday':dt.weekday()<5,
                        'hour':h,'watts':300+trend*d+h,'start_ts':dt.timestamp()+h*3600,'coverage_seconds':3600})
    return out

def sample(at,house=1000,ev=400,hp=100,immersion=0):
    vals={'house_power':house,'ev_power':ev,'heat_pump_power':hp,'immersion_power':immersion}
    signals={k:{'quality':'valid','value':v,'last_reported':at} for k,v in vals.items()}
    signals.update(communication_health={'quality':'valid','value':'Healthy'},workday={'quality':'valid','value':'on'})
    return {'observed_at':at,**season_context(at),'signals':signals}

class CalibrationTests(unittest.TestCase):
    def test_insufficient_data(self):
        r=train_candidate(make_points(3),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertEqual(r['status'],'collecting');self.assertEqual(r['models'],{})
    def test_recent_trend_improves(self):
        r=train_candidate(make_points(),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertEqual(r['status'],'candidate_improves_holdout');self.assertGreater(r['validation']['relative_improvement'],0)
    def test_stable_data_no_fake_improvement(self):
        r=train_candidate(make_points(trend=0),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertEqual(r['status'],'candidate_not_better')
    def test_change_bounded(self):
        r=train_candidate(make_points(),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        for m in r['models'].values():self.assertLessEqual(abs(m['candidate_w']-m['reference_w']),m['reference_w']*.15+.001)
    def test_seasons_separate(self):
        p=make_points();p[0]['season']='summer'
        r=train_candidate(p,datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertFalse(any(k.startswith('summer') for k in r['models']))
    def test_no_control(self):
        r=train_candidate(make_points(),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertFalse(r['applied_to_control']);self.assertEqual(r['control_writes'],0)
    def test_holdout_not_training(self):
        r=train_candidate(make_points(),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertTrue(all(m['latest_training_day']<r['training_end'] for m in r['models'].values()))
    def test_future_excluded(self):
        p=make_points();extra=dict(p[-1]);extra.update(date='2026-10-01',watts=9999999)
        a=train_candidate(p,datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        b=train_candidate(p+[extra],datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertEqual(a['model_hash'],b['model_hash'])
    def test_outcome_not_probability(self):
        r=train_candidate(make_points(),datetime(2026,9,28,tzinfo=timezone.utc),CFG)
        self.assertNotIn('probability',r);self.assertNotIn('savings_czk',r)
    def test_correct_residual(self):self.assertEqual(residual_w(sample('2026-09-28T12:00:00+00:00')),500)
    def test_missing_not_zero(self):
        x=sample('2026-09-28T12:00:00+00:00');x['signals'].pop('ev_power')
        self.assertIsNone(residual_w(x))
    def test_big_negative_rejected(self):self.assertIsNone(residual_w(sample('2026-09-28T12:00:00+00:00',house=100)))
    def test_stale_rejected(self):
        x=sample('2026-09-28T12:00:00+00:00');x['signals']['house_power']['last_reported']='2026-09-28T11:00:00+00:00'
        self.assertIsNone(residual_w(x))
    def test_partial_day_rejected(self):
        start=datetime(2026,9,25,12,tzinfo=timezone.utc)
        seq=[sample((start+timedelta(minutes=i)).isoformat()) for i in range(61)]
        points,days=make_hourly_points(seq,datetime(2026,9,28,tzinfo=timezone.utc))
        self.assertEqual(points,[]);self.assertEqual(days,[])
    def test_long_gap_rejected(self):
        seq=[sample('2026-09-25T12:00:00+00:00'),sample('2026-09-25T14:00:00+00:00')]
        self.assertEqual(make_hourly_points(seq,datetime(2026,9,28,tzinfo=timezone.utc)),([],[]))
    def test_complete_day(self):
        start=datetime(2026,9,24,22,tzinfo=timezone.utc)
        seq=[sample((start+timedelta(minutes=i)).isoformat()) for i in range(1441)]
        points,days=make_hourly_points(seq,datetime(2026,9,28,tzinfo=timezone.utc))
        self.assertEqual(days,['2026-09-25']);self.assertEqual(len(points),24)

class AppTests(unittest.TestCase):
    def test_native_proxy(self):self.assertEqual(ReadOnlyHA().base,'http://supervisor/core')
    def test_native_environment_token(self):
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'test_token'}):self.assertEqual(read_token(),'test_token')
    def test_missing_native_token(self):
        with patch.dict(os.environ,{},clear=True):self.assertRaises(ValueError,read_token)
    def test_newline_token_rejected(self):
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'abc\r\ndef'}):self.assertRaises(ValueError,read_token)
    def test_settings_not_dev(self):
        with patch.dict(os.environ,{'ENERGY_OPTIONS_FILE':'/not/exists'}):
            cfg,_=settings();self.assertEqual(cfg['ha_base_url'],'http://supervisor/core');self.assertIsNone(cfg['token_file'])
    def test_actual_control_mode_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'options.json';path.write_text('{"mode":"auto"}')
            with patch.dict(os.environ,{'ENERGY_OPTIONS_FILE':str(path)}):self.assertRaises(ValueError,settings)
    def test_noncore_proxy_rejected(self):self.assertRaises(ValueError,ReadOnlyHA,'http://supervisor/addons',None)
    def test_settings_can_disable_calibration(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'options.json';path.write_text('{"self_calibration":false}')
            with patch.dict(os.environ,{'ENERGY_OPTIONS_FILE':str(path)}):self.assertFalse(settings()[0]['calibration']['enabled'])

if __name__=='__main__':unittest.main()
