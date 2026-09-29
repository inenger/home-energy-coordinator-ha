"""Shadow EV scenarios must remain conditional, time-correct and read-only."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from energy import shadow
from energy.store import Store, pack
from energy.pricing import TariffBook

UTC = timezone.utc
NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)  # Tuesday 14:00 Prague


def sample(now=NOW, connected='on', soc=50, target=60):
    def signal(v):
        return {'quality': 'valid', 'value': v, 'last_reported': now.isoformat()}
    return {'observed_at': now.isoformat(), 'signals': {
        'ev_connected': signal(connected), 'ev_soc': signal(soc),
        'ev_target_soc': signal(target), 'house_power': signal(1500),
        'ev_power': signal(0)}}


def forecast(available=NOW-timedelta(minutes=10), sunny=True):
    rows = [{'start': (NOW+timedelta(hours=h)).isoformat(),
             'corrected_kwh': 10 if sunny and h == 1 else 0}
            for h in range(24)]
    return {'upcoming': {'today': {'forecast_available_at': available.isoformat(),
                                   'hourly': rows[:12]},
                         'tomorrow': {'forecast_available_at': available.isoformat(),
                                      'hourly': rows[12:]}}}


def tariff():
    rows = [{'start': (NOW+timedelta(hours=h)).isoformat(),
             'end': (NOW+timedelta(hours=h+1)).isoformat(),
             'price': 1 if h >= 13 else 4} for h in range(24)]
    return TariffBook([{'available_at': (NOW-timedelta(hours=1)).isoformat(),
                        'payload': {'today': rows}}])


CFG = {'shadow_ev': {'ac_kwh_per_soc_pct': .8, 'charge_power_kw': 8,
                     'ready_by_local': '07:00'}}


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'evidence.sqlite')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def put(self, row):
        self.store.db.execute('INSERT INTO samples(available_at,day,season,payload) VALUES(?,?,?,?)',
                              (row['observed_at'], '2026-09-29', 'autumn', pack(row)))
        self.store.db.commit()

    def run_candidate(self, pv=None, book=None, cfg=CFG):
        with patch.object(shadow, '_hourly_house_profile', return_value={
                (True, h): .5 for h in range(24)}):
            return shadow._candidate(self.store, NOW, cfg, pv or forecast(), book or tariff())

    def test_weekday_sun_can_win_over_cheap_night(self):
        self.put(sample())
        plan = self.run_candidate()
        self.assertEqual(plan['status'], 'scenario')
        self.assertEqual(plan['mode'], 'observe_only')
        self.assertEqual(plan['actions_executed'], 0)
        self.assertNotIn('savings_czk', plan)
        self.assertAlmostEqual(sum(r['planned_ev_kw']/4 for r in plan['slots']), 8)
        self.assertEqual(sum(r['planned_ev_kw'] for r in plan['slots'] if r['at'].startswith('2026-09-29T13:')), 32)

    def test_cheap_night_without_sun(self):
        self.put(sample())
        plan = self.run_candidate(pv=forecast(sunny=False))
        self.assertEqual(plan['status'], 'scenario')
        active = [r for r in plan['slots'] if r['planned_ev_kw'] > 0]
        self.assertTrue(all(r['buy_price'] == 1 for r in active))

    def test_negative_tariff_can_beat_solar(self):
        self.put(sample())
        rows = [{'start': (NOW+timedelta(hours=h)).isoformat(),
                 'end': (NOW+timedelta(hours=h+1)).isoformat(),
                 'price': -1 if h >= 13 else 4} for h in range(24)]
        book = TariffBook([{'available_at': (NOW-timedelta(hours=1)).isoformat(),
                            'payload': {'today': rows}}])
        plan = self.run_candidate(book=book)
        active = [r for r in plan['slots'] if r['planned_ev_kw'] > 0]
        self.assertTrue(all(r['buy_price'] == -1 for r in active))

    def test_future_forecast_is_not_backfilled(self):
        self.put(sample())
        plan = self.run_candidate(pv=forecast(available=NOW+timedelta(minutes=1)))
        self.assertEqual(plan['status'], 'missing_forecast_profile_or_tariff')

    def test_missing_approval_and_disconnected_car(self):
        self.put(sample())
        self.assertEqual(self.run_candidate(cfg={})['status'], 'needs_configuration')
        self.store.db.execute('DELETE FROM samples')
        self.store.db.commit()
        self.put(sample(connected='off'))
        self.assertEqual(self.run_candidate()['status'], 'car_not_confirmed_connected')

    def test_stale_soc_and_target_met_do_not_make_scenario(self):
        old = sample()
        old['signals']['ev_soc']['last_reported'] = (NOW-timedelta(hours=1)).isoformat()
        self.put(old)
        self.assertEqual(self.run_candidate()['status'], 'missing_soc_or_target')
        self.store.db.execute('DELETE FROM samples')
        self.store.db.commit()
        self.put(sample(soc=60, target=60))
        self.assertEqual(self.run_candidate()['status'], 'target_met')

    def test_next_complete_hour_after_partial_hour(self):
        now = NOW+timedelta(minutes=15)
        self.put(sample(now=now))
        with patch.object(shadow, '_hourly_house_profile', return_value={(True, h): .5 for h in range(24)}):
            plan = shadow._candidate(self.store, now, CFG, forecast(), tariff())
        self.assertEqual(plan['status'], 'scenario')
        self.assertEqual(plan['slots'][0]['at'], (NOW+timedelta(hours=1)).isoformat())

    def test_existing_plan_is_immutable_during_same_hour(self):
        self.put(sample())
        with patch.object(shadow, '_hourly_house_profile', return_value={(True, h): .5 for h in range(24)}):
            a = shadow.build(self.store, NOW, CFG, forecast(), tariff())
            b = shadow.build(self.store, NOW+timedelta(minutes=15), CFG, forecast(), tariff())
        self.assertEqual(a['candidate'], b['candidate'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM shadow_plans').fetchone()[0], 1)

    def test_dst_gap_is_not_a_deadline(self):
        spring = datetime(2026, 3, 28, 20, tzinfo=UTC)
        self.assertEqual(shadow._deadline(spring, '02:30').date().isoformat(), '2026-03-30')

    def test_weekly_review_is_frozen_and_never_claims_savings(self):
        shadow.ensure_schema(self.store.db)
        issued = datetime(2026, 9, 23, 10, tzinfo=UTC)
        slots = [{'at': (issued+timedelta(minutes=15*i)).isoformat(),
                  'planned_house_kw': 2} for i in range(12)]
        plan = {'issued_at': issued.isoformat(), 'slots': slots}
        self.store.db.execute('INSERT INTO shadow_plans VALUES(?,?)', (issued.isoformat(), pack(plan)))
        self.store.db.commit()
        actual = [{'at': row['at'], 'house_kw': 1.5} for row in slots]
        with patch.object(shadow, '_actual', return_value=actual) as measured:
            review = shadow._weekly_review(self.store, NOW)
            self.assertEqual(review['status'], 'descriptive')
            self.assertEqual(review['mean_absolute_house_difference_kw'], .5)
            self.assertIsNone(review['savings_czk'])
            self.assertEqual(shadow._weekly_review(self.store, NOW), review)
            measured.assert_called_once()


if __name__ == '__main__':
    unittest.main()
