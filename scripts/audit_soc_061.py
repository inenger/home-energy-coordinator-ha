"""Independent read-only 0.6.1 audit probes. Run on RPi; no live writes.

Only aggregate/synthetic findings leave stdout. Full evidence stays in the
chosen RPi audit directory. Mutable Stores below are temporary audit fixtures.
"""
import argparse
from collections import Counter
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--source', default='/addons/energy_priority_shadow')
    cli.add_argument('--output-dir', required=True)
    a = cli.parse_args()
    sys.path.insert(0, a.source)
    from energy.core import instant, TZ
    from energy import priority, night
    from energy.soc_evidence import seal, verify
    from energy.soc_energy import Battery
    from energy.soc_history import fit_ev, minute_hours, covered_forecast, read_gzip
    from energy.soc_calibration import pre_window
    from energy.soc_runtime import schema, record_decision, session_plan, review
    from energy.soc_planner import simulate, slots
    from energy.store import Store, pack, unpack

    root = Path(a.output_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    full, findings = {}, {}
    start = instant('2026-06-15T03:00:00+02:00')
    end = start+timedelta(hours=2)
    model = {'discharge_curve': [[0,-1.5],[15,0],[100,8.5]],
             'charge_curve': [[0,-1.5/.9],[15,0],[100,8.5/.9]],
             'dc_cycle_efficiency': .9, 'dc_cycle_low': .9,
             'grid_efficiency': .9, 'grid_efficiency_range': [.9,.9],
             'ac_discharge_efficiency': 1., 'solar_ac_dc_efficiency': 1.,
             'source_hash': 'independent-audit-061-linear'}
    inp = {'soc': 15., 'reserve_soc': 15., 'battery_charge_max_dc_kw': 7.,
           'battery_discharge_max_dc_kw': 7., 'phase_voltages': [230.]*3,
           'priority': 'battery', 'ev_need_ac_kwh': 4., 'ev_max_ac_kw': 11.}

    def row(at=start, house=2., pv=0., hours=.5):
        return {'start': at.timestamp(), 'end': at.timestamp()+hours*3600, 'hours': hours,
                'house_kw': house, 'house_low_kw': house, 'house_high_kw': house,
                'pv_ac_kw': pv, 'pv_low_kw': pv, 'pv_high_kw': pv, 'price': 3.}

    # The F04 fix only applies saved sessions that already have planning_source.
    # A crash after persisting an older session but before its first run is a
    # distinct migration boundary: no running legacy model exists to preserve.
    with tempfile.TemporaryDirectory(dir=root) as td:
        store = Store(Path(td)/'strict.sqlite')
        priority.schema(store.db)
        night.ensure_schema(store.db)
        schema(store.db)
        frozen = {'day': '2026-06-15', 'status': 'captured', 'forecast_kwh': 6.,
                  'target_soc_pct': 80., 'captured_at': start.isoformat()}
        store.db.execute('INSERT INTO priority_sessions VALUES(?,?)', ('2026-06-15', pack(frozen)))
        record_decision(store, {'day': '2026-06-15', 'issued_at': start.isoformat(),
                        'status': 'calculation_unavailable', 'target_soc_pct': None})
        effective = priority.effective_session(store, '2026-06-15', start.isoformat(), {}, True)
        findings['strict_legacy_session_without_run'] = {
            'strict_requested': True, 'prior_run_exists': False,
            'latest_proposal_status': 'calculation_unavailable',
            'returned_target_soc_pct': effective.get('target_soc_pct'),
            'soc_plan_valid': effective.get('soc_plan_valid'),
            'bypasses_strict_revocation': effective.get('target_soc_pct') == 80.}
        full['strict_legacy_session_without_run'] = effective
        store.close()

    # Energy accounting is separate from conservative phase protection.
    # With a full battery, unused PV should offset simultaneous EV demand.
    case = {**inp, 'soc': 100., 'battery_charge_max_dc_kw': 0., 'ev_need_ac_kwh': 5.5}
    r = simulate([row(house=.1, pv=2.)], case, model, 0, 'central', start, end, 1.)
    t = r['timeline'][0]
    true_net = max(0., t['house_ac_kwh']+t['ev_ac_kwh']-t['pv_ac_kwh'])
    findings['simultaneous_ev_import_and_pv_spill'] = {
        'model_import_ac_kwh': r['import_ac_kwh'], 'net_meter_import_ac_kwh': true_net,
        'model_spill_ac_kwh': r['unused_pv_ac_kwh'],
        'excess_import_ac_kwh': r['import_ac_kwh']-true_net}
    full['simultaneous_ev_import_and_pv_spill'] = r

    # Gap check resets start, then immediately reuses the sample before the gap.
    ev = []
    for i in range(5):
        day = start+timedelta(days=i)
        ev.append({'at': day.isoformat(), 'power_w': 0., 'energy_total_kwh': 0., 'soc': 20.})
        for m in range(21):
            active = m <= 10
            ev.append({'at': (day+timedelta(hours=2, minutes=m)).isoformat(),
                       'power_w': 12000. if active else 0.,
                       'energy_total_kwh': 6.+min(m,10)*.2,
                       'soc': 28.+min(m,10)*.2})
    fit = fit_ev(ev)
    findings['ev_fit_accepts_unobserved_gap'] = {
        'status': fit['status'], 'accepted_sessions': len(fit['sessions']),
        'ac_kwh_per_soc_pct': fit['ac_kwh_per_soc_pct'],
        'unobserved_initial_gap_seconds': 7200,
        'sessions_including_gap': sum((instant(s['end'])-instant(s['start'])).total_seconds()>7200 for s in fit['sessions'])}
    full['ev_fit_accepts_unobserved_gap'] = fit

    # The explicit inverter cap currently clips PV alone, not combined output.
    class House:
        def predict(self, *_):
            return {'central_kw': 15., 'low_kw': 15., 'high_kw': 15., 'samples': 24}
    daytime = end+timedelta(hours=7)
    solar = [{'start': daytime.timestamp(), 'end': daytime.timestamp()+1800,
              'kw': 10., 'low_kw': 10., 'high_kw': 10.,
              'available_at': start.isoformat(), 'source_hash': 'synthetic-pv'}]
    tariff = [{'start': daytime.timestamp(), 'end': daytime.timestamp()+1800,
               'price': 3., 'available_at': start.timestamp()}]
    capped = {**inp, 'soc': 100., 'ev_need_ac_kwh': 0., 'inverter_ac_limit_kw': 10.}
    rows, _, _ = slots(daytime, capped, House(), {}, solar, tariff, daytime+timedelta(minutes=30))
    r = simulate(rows, capped, model, 0, 'central', start, end, 1.)
    combined = (r['timeline'][0]['pv_ac_kwh']+r['discharge_ac_kwh'])/.5
    findings['combined_inverter_ac_limit'] = {'explicit_limit_kw': 10.,
        'modeled_combined_ac_output_kw': combined, 'exceeds_explicit_limit': combined>10.+1e-8}
    full['combined_inverter_ac_limit'] = r

    # Verify the autumn review SQL, not just the corrected pre_window helper.
    day = '2026-10-25'
    local03 = datetime.fromisoformat(day+'T03:00:00').replace(tzinfo=TZ)
    used = (local03-timedelta(minutes=5)).astimezone(timezone.utc)
    required = pre_window(day)
    findings['autumn_review_cutoff'] = {'used_cutoff_utc': used.isoformat(),
        'required_cutoff_utc': required.isoformat(),
        'extra_minutes': (required-used).total_seconds()/60}
    with tempfile.TemporaryDirectory(dir=root) as td:
        store = Store(Path(td)/'review.sqlite')
        schema(store.db)
        issue = used+timedelta(minutes=1)
        p = {'issued_at': issue.isoformat(), 'day': day, 'status': 'conditional_shadow_plan',
             'target_soc_pct': 80, 'forecast_periods': []}
        record_decision(store, p)
        midnight = datetime.fromisoformat(day+'T00:00:00').replace(tzinfo=TZ).astimezone(timezone.utc)
        observations = [{'at': (midnight+timedelta(minutes=m)).isoformat(),
            'house_w': 400., 'ev_w': 0., 'pv_counter': m/60,
            'inverter_w': 1000., 'export_limit_w': 9900.} for m in range(25*60+1)]
        with store.db:
            store.db.executemany('INSERT INTO soc_observations VALUES(?,?,?)',
                [(x['at'], day, pack(x)) for x in observations])
        reports = review(store, {'days': [{'day': day, 'pv_kwh': 25.}]},
                         '2026-10-26T08:00:00+00:00')
        findings['autumn_review_cutoff']['review_created_for_64_min_old_plan'] = bool(reports)
        full['autumn_review_cutoff'] = reports
        store.close()

    # A regular day: incomplete night preview is rejected by session_plan but
    # review still compares its truncated forecast with a whole-day counter.
    day = '2026-10-24'
    midnight = datetime.fromisoformat(day+'T00:00:00').replace(tzinfo=TZ).astimezone(timezone.utc)
    with tempfile.TemporaryDirectory(dir=root) as td:
        store = Store(Path(td)/'partial-review.sqlite')
        schema(store.db)
        periods = [{'start': (midnight+timedelta(hours=h)).timestamp(),
                    'end': (midnight+timedelta(hours=h+1)).timestamp(),
                    'house_kw': .4, 'raw_pv_kw': 1. if h>=6 else 0.,
                    'pv_ac_kw': .966 if h>=6 else 0.} for h in range(3,17)]
        issued = midnight+timedelta(hours=2,minutes=55)
        record_decision(store, {'issued_at': issued.isoformat(), 'day': day,
            'status': 'conditional_shadow_plan', 'target_soc_pct': 80,
            'horizon_complete': False, 'night_plan_eligible': False,
            'forecast_periods': periods})
        rejected = session_plan(store,day,(issued+timedelta(minutes=5)).isoformat()) is None
        obs = [{'at': (midnight+timedelta(minutes=m)).isoformat(),
            'house_w': 400., 'ev_w': 0., 'pv_counter': max(0.,min(12.,(m-360)/60)),
            'inverter_w': 1000., 'export_limit_w': 9900.} for m in range(1441)]
        with store.db:
            store.db.executemany('INSERT INTO soc_observations VALUES(?,?,?)',
                                 [(x['at'],day,pack(x)) for x in obs])
        reports = review(store,{'days':[{'day':day,'pv_kwh':12.}]},'2026-10-25T08:00:00+00:00')
        findings['incomplete_plan_daily_error'] = {
            'night_session_correctly_rejected': rejected, 'review_created':bool(reports),
            'reported_pv_error_ac_proxy_kwh': reports[0]['pv_error_ac_proxy_kwh'] if reports else None,
            'actual_error_on_common_forecast_intervals_kwh':0.}
        full['incomplete_plan_daily_error'] = reports
        store.close()

    # Separately measured load should not disappear with unrelated PV metadata.
    obs = [{'at': (start+timedelta(minutes=m)).isoformat(), 'house_w': 400., 'ev_w': 0.,
            'pv_counter': m/60, 'inverter_w': 1000., 'export_limit_w': 9900.} for m in range(61)]
    good_house, _ = minute_hours(obs)
    no_limit = [{**x, 'export_limit_w': None} for x in obs]
    missing_house, _ = minute_hours(no_limit)
    findings['house_quality_coupled_to_pv_metadata'] = {'complete_load_hours': len(good_house),
        'load_hours_when_only_pv_limit_missing': len(missing_house)}

    # Independent checkpoints for old findings, without release test fixtures.
    r = simulate([row()], inp, model, 95, 'central', start, end, 1.)
    port = simulate([row(house=.1,pv=.5)], {**inp,'battery_charge_max_dc_kw':2.,'ev_need_ac_kwh':0.}, model, 95, 'central', start,end,1.)
    no_charge = simulate([row(end,house=1.)], {**inp,'soc':80.,'battery_charge_max_dc_kw':0.,'ev_need_ac_kwh':0.}, model,0,'central',start,end,1.)
    _, actual = minute_hours(obs[:55])
    match = covered_forecast(actual[0], [{'start':start.timestamp(),'end':start.timestamp()+3600,
         'kw':.966,'available_at':(start-timedelta(hours=1)).isoformat(),'source_hash':'common-mask'}])
    from energy.soc_runtime import view
    profile = view({'day':'2026-06-15','timeline':r['timeline']})['profile']
    findings['old_findings_independent_recheck'] = {
        'no_subminimum_ev_segments': all(s['ev_ac_kw']==0 or s['ev_ac_kw']>=4.14-1e-8 for s in r['timeline'][0]['charge_segments']),
        'shared_dc_cap_respected': all(s['battery_total_dc_kw']<=2.+1e-8 for s in port['timeline'][0]['charge_segments']),
        'independent_discharge_limit': abs(no_charge['discharge_ac_kwh']-.5)<1e-8,
        'partial_pv_matching_correct': abs(match['forecast_ac_kwh']-actual[0]['actual_ac_proxy_kwh'])<1e-8,
        'canonical_hash_correct': verify(seal({'a':1}))['verified'],
        'soc_profile_initial_and_end_correct': instant(profile[0]['at'])==start and instant(profile[-1]['at'])==start+timedelta(minutes=30)}

    # Inspect real candidate sessions without returning their private samples.
    from energy.soc_runtime import _external_context
    _, calibrated = _external_context(datetime.now(timezone.utc))
    db = sqlite3.connect('file:/share/home-energy-coordinator/evidence.sqlite?mode=ro', uri=True)
    real_gap_sessions = 0
    private_gap_details = []
    for session in calibrated.get('sessions', []):
        times = [instant(r[0]) for r in db.execute('SELECT at FROM ev_obs WHERE at>=? AND at<=? ORDER BY at', (session['start'],session['end']))]
        maximum = max(((b-a).total_seconds() for a,b in zip(times,times[1:])),default=0)
        private_gap_details.append({'start':session['start'],'end':session['end'],'maximum_gap_s':maximum})
        real_gap_sessions += maximum>90
    db.close()
    full['real_ev_calibration_gap_details'] = private_gap_details
    findings['real_ev_calibration_gaps'] = {'sessions':len(calibrated.get('sessions',[])),
                                          'sessions_with_gaps_over_90s':real_gap_sessions}
    full['findings'] = findings
    (root/'probes-full.json').write_text(json.dumps(full,ensure_ascii=False,indent=2))
    (root/'probes-summary.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2))
    print(json.dumps(findings,ensure_ascii=False))


if __name__ == '__main__':
    main()
