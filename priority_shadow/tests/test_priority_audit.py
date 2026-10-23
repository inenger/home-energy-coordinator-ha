import unittest,tempfile
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from energy import priority_audit as a
from energy.store import Store

DAY='2026-10-21';AT='2026-10-22T10:00:00+00:00'

def series(entity,unit,points):
    out=[]
    for hour,value in points:
        t=datetime.fromisoformat(DAY+'T00:00:00+02:00')+timedelta(hours=hour)
        out.append({'entity_id':entity,'attributes':{'unit_of_measurement':unit},'last_changed':t.isoformat(),'state':str(value)})
    return out


def histories():
    data=[]
    for key in ('export_kwh','import_kwh','pv_kwh','battery_in_kwh'):
        data.append(series(a.HISTORY_IDS[key],'kWh',[(0,50),(.02,0),(3,1),(5,3),(17,7),(23.9,10)]))
    data.append(series(a.HISTORY_IDS['soc'],'%',[(0,20),(5,70),(12,100),(17,80),(23.9,30)]))
    data.append(series(a.HISTORY_IDS['forecast'],'kWh',[(0,8),(12,100)]))
    return data


def result(at,active=True,w=1000,reason='ev_first'):
    return {'at':at,'active':active,'priority':'ev','actual':{'battery_v':250},'selected':{
       'reason':reason,'ev_ac_w':w,'battery_ac_w':1000,'target_soc_pct':80,'forbid_discharge':True,
       'phase':[{'voltage_v':230} for _ in range(3)]}}


class AuditTests(unittest.TestCase):
    def test_daily_final_not_max_and_forecast_is_not_retroactively_known(self):
        r=a.evaluate_day(DAY,histories(),AT)
        self.assertEqual(r['export_kwh'],10)
        self.assertEqual(r['pv_kwh'],10)
        self.assertIsNone(r['forecast_frozen_kwh'])
        self.assertIsNone(r['forecast_error_kwh'])
        self.assertEqual(r['assessment'],'observations_only')
        self.assertEqual(r['soc_05'],70);self.assertEqual(r['soc_end'],30)
        self.assertEqual(r['night_charge_dc_kwh'],2)
        self.assertEqual(r['evening_import_kwh'],3)

    def test_small_midnight_carry_is_not_mistaken_for_reset(self):
        start=datetime.fromisoformat(DAY+'T00:00:00+02:00')
        rows=[(start,.07),(start+timedelta(minutes=1),0),(start+timedelta(hours=23),.47)]
        self.assertEqual(a.daily_counter(rows,start)[0],.47)

    def test_no_reset_or_later_reset_is_missing_not_zero(self):
        start=datetime.fromisoformat(DAY+'T00:00:00+02:00')
        self.assertIsNone(a.daily_counter([(start,10),(start+timedelta(hours=23),20)],start)[0])
        self.assertIsNone(a.daily_counter([(start,0),(start+timedelta(hours=2),10),(start+timedelta(hours=3),0)],start)[0])

    def test_forecast_comparison_uses_frozen_session_and_unknown_unit_rejected(self):
        h=histories();r=a.evaluate_day(DAY,h,AT,{'forecast_kwh':8,'target_soc_pct':80,'captured_at':DAY+'T03:00:00+02:00','status':'captured','forecast_archived_available_at':DAY+'T02:59:00+02:00'})
        self.assertIsNone(r['forecast_error_kwh']);self.assertEqual(r['raw_forecast_difference_kwh'],2);self.assertFalse(r['measurement_boundary_verified'])
        h[0][0]['attributes']['unit_of_measurement']='Wh'
        self.assertIsNone(a.evaluate_day(DAY,h,AT)['export_kwh'])
        self.assertRaises(ValueError,a.evaluate_day,DAY,h,DAY+'T12:00:00+02:00')

    def test_later_forecast_archive_cannot_validate_an_earlier_target(self):
        session={'forecast_kwh':8,'target_soc_pct':80,'captured_at':DAY+'T03:00:00+02:00','status':'captured','forecast_archived_available_at':DAY+'T09:00:00+02:00'}
        r=a.evaluate_day(DAY,histories(),AT,session)
        self.assertIsNone(r['forecast_error_kwh']);self.assertFalse(r['linked_shadow_night'])
        self.assertEqual(r['assessment'],'incomplete_measurements')

    def test_history_day_has_correct_dst_duration_and_exact_entity_allowlist(self):
        path=a.history_path('2026-10-25');start=datetime.fromisoformat(urlparse(path).path.rsplit('/',1)[-1]);q=parse_qs(urlparse(path).query)
        end=datetime.fromisoformat(q['end_time'][0])
        self.assertEqual((end-start).total_seconds(),25*3600)
        self.assertEqual(set(q['filter_entity_id'][0].split(',')),set(a.HISTORY_IDS.values()))
        self.assertRaises(ValueError,a.history_path,'2026-10-21/../../services')

    def test_journal_is_persistent_deduplicated_and_bounded_only_in_display(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'audit.sqlite';store=Store(path)
            self.assertEqual(a.command_summary(store,AT)['rows'],[])
            a.journal(store,result(AT,False));self.assertEqual(a.command_summary(store,AT)['rows'],[])
            for i in range(25):
                at=(datetime.fromisoformat(AT)+timedelta(seconds=15*i)).isoformat()
                r=result(at,w=1000+i*100);a.journal(store,r);a.journal(store,r)
            store.close();store=Store(path)
            report=a.command_summary(store,at)
            self.assertEqual(report['total_records'],25);self.assertEqual(len(report['rows']),20)
            self.assertEqual(report['rows'][0]['ev_ac_w'],3400)
            a.journal(store,result(at,w=3400));self.assertEqual(a.command_summary(store,at)['total_records'],25)
            self.assertTrue(all(r['device_actions']==0 for r in report['rows']))
            store.close()

    def test_export_at_high_soc_is_only_a_short_interval_observation(self):
        h=histories();h[0]=series(a.HISTORY_IDS['export_kwh'],'kWh',[(0,0),(12,0),(12.1,1),(23,5)])
        r=a.evaluate_day(DAY,h,AT)
        self.assertEqual(r['export_kwh'],5);self.assertEqual(r['export_at_high_soc_kwh'],1)
        self.assertEqual(r['export_paired_kwh'],1)
        self.assertEqual(r['assessment'],'observations_only')

if __name__=='__main__':unittest.main()
