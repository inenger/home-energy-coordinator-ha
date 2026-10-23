"""RPi-only adapters for measured history; no network, secrets or device writes.

The one-time import consumes the explicitly audited analysis already on the
same RPi. Subsequent updates use this observer's own minute snapshots. Input
digests and acquisition times remain in the model provenance.
"""
import argparse
import bisect
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median
from .core import TZ, instant, digest
from .pricing import valid
from .soc_calibration import season, quantile


def read_gzip(path):
    with gzip.open(path,'rt') as f:return json.load(f)


def atomic_gzip(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.next')
    with gzip.open(temp,'wt') as f:json.dump(data,f,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    temp.chmod(0o600);temp.replace(path)


def _series(data,name):
    for result in data[name]['results']:
        for series in result.get('series',[]):
            yield series,[dict(zip(series['columns'],v)) for v in series['values']]


def import_analysis(root):
    root=Path(root);history=read_gzip(root/'history.json.gz')
    audit=json.loads((root/'audit.json').read_text())
    battery=json.loads((root/'battery_deep.json').read_text())
    power={};pv={};temperature={};limits=[];ev={}
    for s,rows in _series(history,'power_hourly'):
        power[s['tags']['entity_id']]={instant(r['time']).timestamp():r for r in rows}
    for s,rows in _series(history,'pv_counter'):pv={instant(r['time']).timestamp():r for r in rows}
    for s,rows in _series(history,'temp_hourly'):temperature={instant(r['time']).timestamp():r for r in rows}
    for s,rows in _series(history,'limits'):limits=[(instant(r['time']).timestamp(),r['value']) for r in rows]
    for s,rows in _series(history,'ev_counter'):ev={instant(r['time']).timestamp():r['last'] for r in rows}
    limit_times=[t for t,v in limits]
    def constraint(t):
        i=bisect.bisect_right(limit_times,t)-1
        if i<0:return None
        values=[limits[i][1]]+[limits[j][1] for j in range(i+1,bisect.bisect_left(limit_times,t+3600))]
        peak=power.get('solax_inverter_power',{}).get(t,{}).get('max')
        if peak is None:return None
        return any(v<=10 for v in values) or peak>=9800
    # Recorded counter increments are assigned to the hour containing their
    # final report. Quiet hours carry the known counter, not a fresh heartbeat.
    ev_delta={};prior=None
    for t,v in sorted(ev.items()):
        if prior is not None:
            delta=v-prior
            ev_delta[t]=delta if 0<=delta<=12.5 else None
        prior=v
    house=[];first_ev=min(ev) if ev else None
    for t,r in sorted(power.get('solax_house_load',{}).items()):
        if r['n']<30 or first_ev is None or t<=first_ev:continue
        delta=ev_delta.get(t,0.)
        if delta is None:continue
        value=r['mean']/1000-delta
        if value<-.15 or value>25:continue
        dt=datetime.fromtimestamp(t,timezone.utc);local=dt.astimezone(TZ)
        house.append({'at':dt.isoformat(),'available_at':datetime.fromtimestamp(t+3600,timezone.utc).isoformat(),
                      'day':local.date().isoformat(),'season':season(dt),'weekend':local.weekday()>=5,
                      'house_without_ev_kwh':max(0.,value),'temperature_c':temperature.get(t,{}).get('mean'),
                      'quality':'observed','method':'hourly_power_mean_minus_wallbox_counter_delta',
                      'source_samples':r['n'],'ev_counter_quiet_hours_held':True})
    pairs=[]
    for f in history['forecasts']:
        for row in f['hourly']:
            dt=instant(row['period_start']);t=dt.timestamp();available=instant(f['available_at'])
            a,b=pv.get(t-3600),pv.get(t);limited=constraint(t)
            if not a or not b or limited is None or available>dt:continue
            if datetime.fromtimestamp(t-3600,TZ).date()!=dt.astimezone(TZ).date():continue
            actual=b['last']-a['last'];house_row=power.get('solax_house_load',{}).get(t,{})
            if not 0<=actual<=12 or house_row.get('n',0)<30:continue
            pairs.append({'target':dt.isoformat(),'day':dt.astimezone(TZ).date().isoformat(),
                          'available_at':datetime.fromtimestamp(t+3600,timezone.utc).isoformat(),
                          'forecast_available_at':f['available_at'],'forecast_ac_kwh':row['pv_estimate'],
                          'actual_ac_proxy_kwh':actual*.966,'constrained':limited,
                          'boundary':'native_dc_counter_times_0.966_ac_proxy','source':'audited_influx_history'})
    # July is the fitting period; October remains a separate validation period.
    source=battery['2026-07'];curve=source['curve'];eta=source['roundtrip']['ratio_of_sums']
    if not valid(eta) or not .7<=eta<=1:raise ValueError('No suitable DC cycle evidence')
    debt=curve['charge_11_30']['median']-curve['charge_15_30']['median']
    discharge=[[0,-debt*eta*15/4],[11,-debt*eta],[15,0.]];charge=[[0,-debt*15/4],[11,-debt],[15,0.]]
    for soc in [30,50,70,90,95,100]:
        discharge.append([soc,curve[f'discharge_15_{soc}']['median']])
        charge.append([soc,curve[f'charge_15_{soc}']['median']])
    model={'discharge_curve':discharge,'charge_curve':charge,'dc_cycle_efficiency':eta,
           'dc_cycle_low':source['roundtrip']['distribution']['p10'],
           'ac_discharge_efficiency':.977,'solar_ac_dc_efficiency':.966,
           'fit_period':'2026-07','reference_reserve_soc':15,
           'reference_reserve_is_approved_policy':False,'catalogue_capacity_not_used':True,
           'capacity_and_soh_not_identified':True,'input_soc_uncertainty':True,
           'grid_efficiency':.9,'grid_efficiency_range':[.85,.95],
           'grid_efficiency_source':'unverified_legacy_assumption_sensitivity_only',
           'curve_sample_counts':{k:v['n'] for k,v in curve.items()},
           'validation_holdout':{'period':'2026-09-28_to_2026-10-23','curve_errors_kwh':{
               k:battery['recent']['curve'][k]['median']-v['median'] for k,v in curve.items()
               if k in battery['recent']['curve']},'not_a_savings_test':True}}
    model['source_hash']=digest({'model':model,'input_sha256':audit['raw_inputs']})
    return {'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),
            'house_hours':house,'pv_pairs':pairs,'battery_model':model,
            'source':{'kind':'audited_RPi_history','source_dir':str(root),
                      'input_sha256':audit['raw_inputs'],'private_data_stay_on_RPi':True,
                      'historical_validation_is_replay_not_issued_decisions':True}}


def fit_ev(rows):
    """AC delivered per SOC point; candidate only, with complete observed sessions."""
    sessions=[];start=None;last=None;prior=None;rejected=defaultdict(int)
    for r in rows:
        if (not all(valid(r.get(k)) for k in ('power_w','energy_total_kwh','soc'))
                or not 0<=r['power_w']<=25000 or r['energy_total_kwh']<0 or not 0<=r['soc']<=100):
            start=last=prior=None;rejected['invalid_sample']+=1;continue
        if prior and not 0<(instant(r['at'])-instant(prior['at'])).total_seconds()<=90:
            start=last=prior=None;rejected['discontinuous_interval']+=1
        if prior and r['energy_total_kwh']<prior['energy_total_kwh']:
            start=last=prior=None;rejected['counter_reset']+=1
        active=r['power_w']>500
        if active:
            # A complete session needs an observed inactive -> active edge.
            # Never restart an already active session across a gap or bad row.
            if start is None and prior and prior['power_w']<=500:start=prior
            if start is not None:last=r
        elif start and last and (instant(r['at'])-instant(last['at'])).total_seconds()>=600:
            ds=r['soc']-start['soc'];energy=r['energy_total_kwh']-start['energy_total_kwh']
            if ds>=5 and .2<=energy/ds<=1.5 and energy>=2:
                sessions.append({'start':start['at'],'end':r['at'],'soc_delta':ds,'ac_kwh':energy,'ratio':energy/ds,
                                 'continuity_verified':True,'maximum_interval_seconds':90})
            start=last=None
        prior=r
    values=[r['ratio'] for r in sessions[-30:]]
    enough=len(values)>=5 and len({r['start'][:10] for r in sessions[-30:]})>=3
    stable=enough and quantile(values,.9)/quantile(values,.1)<1.3
    return {'status':'candidate_for_shadow' if stable else 'insufficient_consistent_sessions',
            'ac_kwh_per_soc_pct':median(values) if stable else None,
            'low':quantile(values,.1),'high':quantile(values,.9),'sessions':sessions[-30:],
            'approval_for_control':False,'energy_boundary':'wallbox_ac',
            'calibration_policy':'ev-contiguous-sessions-v2','quality_rejections':dict(rejected),
            'source_hash':digest(sessions[-30:]),
            'note':'Vehicle SOC estimator and reporting delay remain measurement uncertainties.'}


def minute_hours(rows):
    """Integrate only valid adjacent minute samples; aggregate flags, never gaps."""
    bins=defaultdict(lambda:defaultdict(float));coverage=defaultdict(list)
    for a,b in zip(rows,rows[1:]):
        ta=instant(a['at']).timestamp();tb=instant(b['at']).timestamp();dt=tb-ta
        if not 0<dt<=90:continue
        house_good=all(valid(r.get(k)) for r in (a,b) for k in ('house_w','ev_w'))
        house_good=house_good and all(r['house_w']>=0 and 0<=r['ev_w']<=r['house_w']+500 for r in (a,b))
        counter_good=all(valid(r.get('pv_counter')) and r['pv_counter']>=0 for r in (a,b))
        constraint_good=all(valid(r.get(k)) for r in (a,b) for k in ('inverter_w','export_limit_w'))
        constraint_good=constraint_good and all(r['export_limit_w']>=0 for r in (a,b))
        same=datetime.fromtimestamp(ta,TZ).date()==datetime.fromtimestamp(tb,TZ).date()
        delta=b['pv_counter']-a['pv_counter'] if same and counter_good else None
        pv_good=delta is not None and 0<=delta<=12*dt/3600+.15
        while ta<tb:
            hour=int(ta//3600)*3600;stop=min(tb,hour+3600);seconds=stop-ta;v=bins[hour]
            if house_good:
                v['seconds']+=seconds;v['house_j']+=max(0,a['house_w']-a['ev_w'])*seconds
            if all(valid(r.get('outdoor_c')) for r in (a,b)):
                v['temp_j']+=a['outdoor_c']*seconds;v['temp_s']+=seconds
            if pv_good:
                v['pv_dc']+=delta*seconds/dt;v['pv_seconds']+=seconds
                if coverage[hour] and abs(coverage[hour][-1][1]-ta)<1e-6:coverage[hour][-1][1]=stop
                else:coverage[hour].append([ta,stop])
                if constraint_good:
                    v['constraint_seconds']+=seconds
                    if a['export_limit_w']<=10 or b['export_limit_w']<=10 or max(a['inverter_w'],b['inverter_w'])>=9800:v['limited']=1
            ta=stop
    house=[];actual=[]
    for t,r in sorted(bins.items()):
        dt=datetime.fromtimestamp(t,timezone.utc);local=dt.astimezone(TZ)
        if r['seconds']>=3240:
            house.append({'at':dt.isoformat(),'available_at':datetime.fromtimestamp(t+3600,timezone.utc).isoformat(),
                          'day':local.date().isoformat(),'season':season(dt),'weekend':local.weekday()>=5,
                          'house_without_ev_kwh':r['house_j']/r['seconds']/1000,
                          'temperature_c':r['temp_j']/r['temp_s'] if r['temp_s']>=3240 else None,
                          'quality':'observed','method':'covered_minute_power_integral_minus_ev_once',
                          'quality_schema':'independent-quality-masks-v1'})
        if r['pv_seconds']>=3240:
            actual.append({'target':dt.isoformat(),'available_at':datetime.fromtimestamp(t+3600,timezone.utc).isoformat(),
                           'actual_ac_proxy_kwh':r['pv_dc']*.966,
                           'constrained':True if r['limited'] else False if r['constraint_seconds']>=r['pv_seconds']-1e-6 else None,
                           'constraint_coverage_seconds':r['constraint_seconds'],
                           'quality_schema':'independent-quality-masks-v1',
                           'coverage_seconds':r['pv_seconds'],'coverage_intervals':coverage[t],
                           'coverage_schema':'common-intervals-v2'})
    return house,actual


def covered_forecast(actual,solar):
    """Integrate a forecast only over exactly the observed counter intervals."""
    intervals=actual.get('coverage_intervals')
    if actual.get('coverage_schema')!='common-intervals-v2' or not intervals:return None
    total=seconds=0.;used=[]
    for start,end in intervals:
        cuts=sorted({start,end}|{v[k] for v in solar for k in ('start','end') if start<v[k]<end})
        for a,b in zip(cuts,cuts[1:]):
            matches=[v for v in solar if v['start']<=a and v['end']>=b]
            if not matches:return None
            available=max(instant(v['available_at']) for v in matches)
            latest=[v for v in matches if instant(v['available_at'])==available]
            if len({v['kw'] for v in latest})!=1:return None
            chosen=latest[0];total+=chosen['kw']*(b-a)/3600;seconds+=b-a;used.append(chosen)
    if abs(seconds-actual.get('coverage_seconds',0))>1e-5:return None
    return {'forecast_ac_kwh':total,'forecast_available_at':max(v['available_at'] for v in used),
            'forecast_source_hashes':sorted({v['source_hash'] for v in used})}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--analysis-dir',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();data=import_analysis(args.analysis_dir);atomic_gzip(args.output,data)
    print(json.dumps({'history_import':'ok','house_hours':len(data['house_hours']),'pv_pairs':len(data['pv_pairs']),
                      'output_sha256':hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
                      'device_actions':0}))


if __name__=='__main__':main()
