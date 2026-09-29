"""Regression coverage for telemetry, forecast provenance, time boundaries and integration."""
import contextlib, io, json, tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from energy import telemetry, weather, pricing, pvmodel, appliances, portable
from energy.core import build_sample, digest
from energy.store import Store
from energy.collector import ReadOnlyHA, settings
from energy.analytics import record as record_analytics, build
from energy.evmodel import analyze as ev_analyze
from energy.webui import PAGE
UTC=timezone.utc
NOW=datetime(2026,9,29,12,tzinfo=UTC)

def state(eid='sensor.room',value='22',unit='°C',cls='temperature',**attrs):
    return {'entity_id':eid,'state':value,'last_reported':NOW.isoformat(),'last_updated':NOW.isoformat(),
        'attributes':{'unit_of_measurement':unit,'device_class':cls,'friendly_name':'Čidlo',**attrs}}

def book(rows,at='2026-09-01T00:00:00+00:00'):
    return pricing.TariffBook([{'available_at':at,'payload':{'today':rows}}])

class TelemetryTests(unittest.TestCase):
    def test_all_environmental_classes(self):
        ss=[state('sensor.c'+str(i),'1',None,c) for i,c in enumerate(telemetry.CLASSES)]
        self.assertEqual(len(telemetry.discover(ss,NOW.isoformat())['points']),len(telemetry.CLASSES))
    def test_unavailable_retained(self):
        p=telemetry.discover([state(value='unavailable')],NOW.isoformat())['points']['sensor.room']
        self.assertIsNone(p['value']);self.assertEqual(p['quality'],'unavailable')
    def test_humidity_not_phone_battery(self):
        ss=[state('sensor.humidity','50','%','humidity'),state('sensor.phone','50','%','battery')]
        self.assertEqual(set(telemetry.discover(ss,NOW.isoformat())['points']),{'sensor.humidity'})
    def test_sensitive_domains_excluded_even_explicit(self):
        ss=[state('device_tracker.phone','home'),state('camera.door','idle'),state('lock.door','locked')]
        p=telemetry.discover(ss,NOW.isoformat(),{'include':[s['entity_id'] for s in ss]})
        self.assertEqual(p['points'],{})
    def test_allowlisted_attributes_no_secrets(self):
        p=telemetry.discover([state(latitude=1,token='SECRET',url='http://secret',nested={'password':'x'})],NOW.isoformat())
        self.assertNotIn('SECRET',json.dumps(p));self.assertNotIn('latitude',json.dumps(p))
    def test_nan_stays_missing(self):
        p=telemetry.discover([state(value='NaN')],NOW.isoformat())['points']['sensor.room']
        self.assertIsNone(p['value']);self.assertEqual(p['quality'],'invalid_number')
    def test_temperature_unit_conversion(self):
        p=telemetry.discover([state(value='68',unit='°F')],NOW.isoformat())['points']['sensor.room']
        self.assertEqual(p['value'],20);self.assertEqual(p['unit'],'°C')
    def test_unknown_temperature_unit(self):
        p=telemetry.discover([state(unit='x')],NOW.isoformat())['points']['sensor.room']
        self.assertEqual(p['quality'],'unit_mismatch')
    def test_equipment_not_room_implicitly(self):
        p=telemetry.discover([state('sensor.cpu_temperature')],NOW.isoformat())['points']['sensor.cpu_temperature']
        self.assertEqual(p['role'],'unclassified');self.assertFalse(p['role_verified'])
    def test_weather_not_measurement(self):
        p=telemetry.discover([state('weather.home','rainy',None,None,temperature=10,temperature_unit='°C')],NOW.isoformat())
        self.assertEqual(p['points']['weather.home']['source_kind'],'provider_current_not_local_observation')
    def test_solar_geometry_kept_not_coordinates(self):
        p=telemetry.discover([state('sun.sun','above_horizon',None,None,azimuth=125,elevation=30,latitude=49)],NOW.isoformat())
        self.assertEqual(p['points']['sun.sun']['attributes']['elevation'],30);self.assertNotIn('latitude',json.dumps(p))
    def test_calendar_tariff_season_distinct(self):
        p=telemetry.discover([],NOW.isoformat())['calendar']
        self.assertEqual(p['season'],'autumn');self.assertEqual(p['tariff_season'],'summer');self.assertIsNone(p['workday'])
    def test_self_published_not_reingested(self):
        self.assertEqual(telemetry.discover([state('sensor.energie_v4_x')],NOW.isoformat())['points'],{})
    def test_configured_security_relay_is_excluded(self):
        p=Path(__file__).resolve().parents[1]/'config/telemetry.json'
        policy=json.loads(p.read_text())
        self.assertEqual(telemetry.discover([state('switch.nibe_relay_relay','on',None,None)],NOW.isoformat(),policy)['points'],{})
    def test_actual_sensor_reports_deduplicated(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite')
            for t in (NOW,NOW+timedelta(minutes=1)): telemetry.record(st,telemetry.discover([state()],t.isoformat()))
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM temperature_observations').fetchone()[0],1)
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM environment_samples').fetchone()[0],2);st.close()
    def test_role_changes_versioned(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');telemetry.record(st,telemetry.discover([state()],NOW.isoformat()))
            telemetry.record(st,telemetry.discover([state()],(NOW+timedelta(minutes=1)).isoformat(),{'mappings':{'sensor.room':{'role':'room','zone':'Office'}}}))
            self.assertEqual(st.db.execute('SELECT COUNT(*) FROM telemetry_mappings').fetchone()[0],2);st.close()

class WeatherTests(unittest.TestCase):
    def forecasts(self,kind='hourly',available=None):
        return [{'available_at':(available or NOW-timedelta(hours=24)).isoformat(),
            'payload':{'entity_id':'weather.home','forecast_type':kind,'units':{'temperature_unit':'°C'},
                'forecast':[{'datetime':(NOW-timedelta(hours=1)).isoformat(),'temperature':10}]}}]
    def observations(self):
        t=(NOW-timedelta(hours=1)).isoformat();return [{'reported_at':t,'first_seen':t,'value_c':12}]
    def test_explicit_local_pair(self):
        r=weather.comparison(self.forecasts(),self.observations(),'sensor.outdoor',NOW)
        self.assertEqual(r['metrics'][0]['mae_c'],2)
    def test_daily_not_compared_to_point(self):
        self.assertEqual(weather.comparison(self.forecasts('daily'),self.observations(),'sensor.outdoor',NOW)['metrics'],[])
    def test_forecast_after_target_excluded(self):
        self.assertEqual(weather.comparison(self.forecasts(available=NOW),self.observations(),'sensor.outdoor',NOW)['pairs'],[])
    def test_old_sensor_not_fresh(self):
        obs=self.observations();obs[0]['first_seen']=(NOW+timedelta(days=1)).isoformat()
        self.assertEqual(weather.comparison(self.forecasts(),obs,'sensor.outdoor',NOW)['pairs'],[])
    def test_weather_call_rejects_device(self): self.assertRaises(ValueError,weather.request_parts,'switch.heater','hourly')
    def test_clean_response_preserves_units(self):
        x=weather.clean_response({'service_response':{'weather.home':{'forecast':[{'datetime':NOW.isoformat(),'temperature':4,'token':'SECRET'}]}}},'weather.home','hourly',{'temperature_unit':'°C'})
        self.assertEqual(x['units']['temperature_unit'],'°C');self.assertNotIn('SECRET',json.dumps(x))
    def test_api_call_only_weather(self):
        ha=ReadOnlyHA();ha._query=MagicMock(return_value={});ha.weather_forecast('weather.home','hourly')
        self.assertEqual(ha._query.call_args.args[0],'/api/services/weather/get_forecasts?return_response')
    def test_metadata_ids_validated(self):
        ha=ReadOnlyHA();self.assertRaises(ValueError,ha.entity_metadata,['sensor.x %}{% set x=1 %}'])
    def test_unsupported_weather_types_not_called(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');client=MagicMock()
            weather.poll(st,client,[state('weather.home','sunny',None,None,supported_features=1)],{'weather_types':['hourly']},NOW)
            client.weather_forecast.assert_not_called();st.close()

class PricingTests(unittest.TestCase):
    def test_crossing_tariff_boundary(self):
        prices=book([{'start':'2026-09-29T10:00:00+02:00','end':'2026-09-29T11:00:00+02:00','price':3.5284},
            {'start':'2026-09-29T11:00:00+02:00','end':'2026-09-29T12:00:00+02:00','price':1.8078}])
        xs=pricing.split({'at':'2026-09-29T10:55:00+02:00','energy_total_kwh':10},
            {'at':'2026-09-29T11:05:00+02:00','energy_total_kwh':11},book=prices)
        self.assertAlmostEqual(sum(x['energy_kwh'] for x in xs),1)
        self.assertAlmostEqual(sum(x['cost_czk'] for x in xs),2.6681)
    def test_cost_missing_not_zero(self):
        xs=pricing.split({'at':NOW.isoformat(),'energy_total_kwh':1},{'at':(NOW+timedelta(minutes=1)).isoformat(),'energy_total_kwh':1.1},book=book([]))
        self.assertAlmostEqual(pricing.totals(xs)['unpriced_kwh'],.1);self.assertIsNone(pricing.totals(xs)['tariff_equivalent_cost_czk'])
    def test_future_tariff_not_used(self):
        b=book([{'start':NOW.isoformat(),'end':(NOW+timedelta(hours=1)).isoformat(),'price':1}],at=(NOW+timedelta(days=1)).isoformat())
        self.assertIsNone(b.price(NOW.timestamp()))
    def test_midnight_month_split(self):
        xs=pricing.split({'at':'2026-09-30T23:55:00+02:00','energy_total_kwh':1},{'at':'2026-10-01T00:05:00+02:00','energy_total_kwh':2})
        self.assertEqual([x['month'] for x in xs],['2026-09','2026-10']);self.assertAlmostEqual(xs[0]['energy_kwh'],.5)
    def test_dst_repeated_hour_distinct(self):
        xs=pricing.split({'at':'2026-10-25T02:50:00+02:00','energy_total_kwh':1},{'at':'2026-10-25T02:10:00+01:00','energy_total_kwh':2})
        self.assertEqual(len(xs),2);self.assertEqual(sum(x['seconds'] for x in xs),1200)
    def test_long_gap_keeps_known_energy(self):
        xs=pricing.split({'at':NOW.isoformat(),'energy_total_kwh':1,'buy_price':2},{'at':(NOW+timedelta(hours=5)).isoformat(),'energy_total_kwh':10,'buy_price':2})
        self.assertEqual(pricing.totals(xs)['home_charge_kwh'],9);self.assertEqual(pricing.totals(xs)['unpriced_kwh'],9)
    def test_reset_not_new_energy(self):
        self.assertEqual(pricing.split({'at':NOW.isoformat(),'energy_total_kwh':20},{'at':(NOW+timedelta(minutes=1)).isoformat(),'energy_total_kwh':0}),[])
    def test_dst_day_seconds(self):
        self.assertEqual(pricing.day_seconds('2026-03-29'),82800);self.assertEqual(pricing.day_seconds('2026-10-25'),90000)
    def test_conflicting_tariffs_not_silently_chosen(self):
        row={'start':NOW.isoformat(),'end':(NOW+timedelta(hours=1)).isoformat(),'price':1}
        b=book([row,{**row,'price':2}]);self.assertIsNone(b.price(NOW.timestamp()))

class ApplianceTests(unittest.TestCase):
    def test_laptop_not_washer(self): self.assertEqual(appliances._kind('Pracovna NTB - zásuvka'),'laptop')
    def test_czech_washer(self): self.assertEqual(appliances._kind('Pračka switch_0 power'),'washer')
    def test_workroom_not_washer(self): self.assertEqual(appliances._kind('Pracovna server'),'generic')
    def test_short_history_not_divided_by_30(self):
        rows=[{'at':(NOW-timedelta(minutes=i)).isoformat(),'label':'Myčka','kind':'dishwasher','energy_kwh':10,'power_w':0,'buy_price':2} for i in (1,0)]
        r=appliances.summarize({'dish':rows},NOW)['dish']
        self.assertIsNone(r['cycles_per_day_30d']);self.assertIsNone(r['trend_7d_vs_prev7_pct']);self.assertEqual(r['complete_days_30d'],0)
    def test_interrupted_cycle_not_completed(self):
        rows=[{'at':(NOW+timedelta(minutes=m)).isoformat(),'power_w':p,'energy_kwh':i,'buy_price':2} for i,(m,p) in enumerate([(0,0),(1,1000),(20,1000),(21,0),(40,0)])]
        self.assertEqual(appliances._sessions(rows,'dishwasher'),[])

class PVTests(unittest.TestCase):
    def data(self):
        rows=[];forecasts=[];base=datetime(2026,9,1,10,tzinfo=UTC)
        for d in range(10):
            at=base+timedelta(days=d)
            for i in range(61): rows.append({'at':(at+timedelta(minutes=i)).isoformat(),'energy_today_kwh':i/60*.8})
            forecasts.append({'available_at':(at-timedelta(hours=12)).isoformat(),'payload':{'detailedHourly':[{'period_start':at.isoformat(),'pv_estimate':1,'pv_estimate10':.5,'pv_estimate90':1.1}]}})
        return forecasts,rows
    def test_time_holdout(self):
        f,r=self.data();model=pvmodel.calibrate(f,r,NOW)['models']['autumn|6-24h']
        self.assertEqual(model['train_days'],7);self.assertEqual(model['test_days'],3);self.assertAlmostEqual(model['factor'],.8)
    def test_sparse_coverage_rejected(self):
        f,r=self.data();r=r[::60];self.assertEqual(pvmodel.calibrate(f,r,NOW)['models'],{})
    def test_past_not_rewritten_by_future_forecast(self):
        f,r=self.data();a=pvmodel.calibrate(f,r,NOW)
        f.append({'available_at':(NOW+timedelta(days=10)).isoformat(),'payload':f[0]['payload']})
        self.assertEqual(a,pvmodel.calibrate(f,r,NOW))
    def test_lead_uses_forecast_acquisition_not_now(self):
        target=NOW+timedelta(hours=1)
        p={'_available_at':(target-timedelta(hours=30)).isoformat(),'detailedHourly':[{'period_start':target.isoformat(),'pv_estimate':1}]}
        x=pvmodel.corrected_upcoming({'tomorrow':p},{'models':{'autumn|24-48h':{'factor':.8}}},NOW)
        self.assertAlmostEqual(x['tomorrow']['corrected_kwh'],.8)
    def test_limited_production_excluded(self):
        f,r=self.data()
        for row in r: row['limited']=True
        self.assertEqual(pvmodel.calibrate(f,r,NOW)['models'],{})

class PortableMigrationTests(unittest.TestCase):
    def test_consistent_backup_and_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/"source.sqlite";shared=root/"shared";target=root/"target.sqlite"
            import sqlite3
            db=sqlite3.connect(src);db.execute("CREATE TABLE x(v INTEGER)");db.execute("INSERT INTO x VALUES(42)");db.commit();db.close()
            with patch.object(portable,"PORTABLE_DIR",shared),patch.object(portable,"PORTABLE_DB",shared/"evidence.sqlite"),patch.object(portable,"PORTABLE_META",shared/"evidence.json"):
                meta=portable.backup(src,"0.4.1");self.assertEqual(meta["status"],"ready")
                result=portable.restore_if_empty(target);self.assertEqual(result["status"],"restored")
                db=sqlite3.connect(target);self.assertEqual(db.execute("SELECT v FROM x").fetchone()[0],42);db.close()
    def test_existing_database_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);target=root/"target.sqlite";target.write_bytes(b"x")
            with patch.object(portable,"PORTABLE_DB",root/"missing.sqlite"):
                self.assertEqual(portable.restore_if_empty(target)["status"],"existing_database_kept")

class IntegrationTests(unittest.TestCase):
    def test_empty_database_build(self):
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'x.sqlite');a=build(s,NOW)
            self.assertEqual(a['environment']['status'],'collecting');self.assertEqual(a['weather']['status'],'collecting_pairs');s.close()
    def test_additive_migration_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'x.sqlite');at=NOW.isoformat();sample=build_sample([],{},at,at,'hash')
            s.record(sample,{},[],{});telemetry.record(s,telemetry.discover([state()],at));record_analytics(s,sample)
            result=s.export('2026-09-29');self.assertEqual(len(result['samples']),1);self.assertEqual(len(result['environment_samples']),1)
            self.assertEqual(s.db.execute('PRAGMA integrity_check').fetchone()[0],'ok');s.close()
    def test_settings_still_observe_only(self):
        with patch.dict('os.environ',{'ENERGY_OPTIONS_FILE':'/not_exists'}):
            c,_=settings();self.assertEqual(c['mode'],'observe_only');self.assertTrue(c['weather_enabled'])
    def test_ui_escape_helper_and_null_gaps(self):
        self.assertIn('const esc=',PAGE);self.assertIn('prev=null;continue',PAGE)
        self.assertIn("timeZone:'Europe/Prague'",PAGE)
        self.assertNotIn('http://',PAGE);self.assertNotIn('https://',PAGE)
    def test_prague_timezone_reference_offsets(self):
        from zoneinfo import ZoneInfo
        z=ZoneInfo('Europe/Prague')
        self.assertEqual(datetime(2026,9,29,1,tzinfo=UTC).astimezone(z).hour,3)
        self.assertEqual(datetime(2026,12,29,1,tzinfo=UTC).astimezone(z).hour,2)
    def test_no_actuation_output(self):
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)/'x.sqlite');self.assertEqual(build(s,NOW)['quality']['control_actions'],0);s.close()
    def test_cold_start_collect_and_analytics(self):
        from energy import collector
        cfg,catalog=settings();at=datetime.now(UTC).isoformat();ss=[]
        for spec in catalog.values():
            ss.append({'entity_id':spec['entity_id'],'state':'0' if spec['unit'] else 'off',
                'last_reported':at,'attributes':{'unit_of_measurement':spec['unit']}})
        ss.append({'entity_id':'weather.home','state':'cloudy','attributes':{'supported_features':3,'temperature_unit':'°C'}})
        forecast={'service_response':{'weather.home':{'forecast':[{'datetime':at,'temperature':10}]}}}
        with tempfile.TemporaryDirectory() as td,patch.object(collector,'DATA',Path(td)),patch.object(collector,'storage_check'),patch.object(ReadOnlyHA,'get',return_value=ss),patch.object(ReadOnlyHA,'entity_metadata',return_value={}),patch.object(ReadOnlyHA,'weather_forecast',return_value=forecast),contextlib.redirect_stdout(io.StringIO()):
            collector.collect();s=Store(Path(td)/'evidence.sqlite');a=build(s,datetime.now(UTC));s.close()
            self.assertGreater(a['environment']['quality']['count'],0);self.assertEqual(a['weather']['forecast_versions'],2)
    def test_publisher_creates_all_unknown_entities(self):
        from energy import publish_status as pub
        class Response:
            status=201
            def __enter__(self): return self
            def __exit__(self,*args): pass
        mock=MagicMock();mock.open.return_value=Response()
        with patch.object(pub,'_load',return_value={}),patch.object(pub,'read_token',return_value='dummy'),patch.object(pub.urllib.request,'build_opener',return_value=mock),contextlib.redirect_stdout(io.StringIO()): pub.main()
        self.assertEqual(mock.open.call_count,23)
        for call in mock.open.call_args_list:
            body=json.loads(call.args[0].data);self.assertIsNotNone(body['state'])
    def test_bootstrap_changes_working_directory(self):
        from energy import bootstrap
        with patch.object(bootstrap.subprocess,'Popen') as m:
            bootstrap.run_child({'path':'/tmp/candidate'});self.assertEqual(m.call_args.kwargs['cwd'],'/tmp/candidate')

if __name__=='__main__': unittest.main()
