"""Bounded, seasonal candidate models. No actuator or policy-setting access.

An observation-only baseline profile excludes measured EV/heat-pump/immersion
loads. Recent data get larger weights. Chronological holdout tests compare the
candidate with an unweighted historical profile. Neither model is activated.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
from statistics import mean, median
from .core import TZ, instant, digest
from .store import unpack

def valid_value(sample, key):
    x = sample.get('signals', {}).get(key, {})
    v = x.get('value')
    return v if x.get('quality') == 'valid' and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

def residual_w(sample):
    health=sample.get('signals',{}).get('communication_health',{})
    if health.get('quality')!='valid' or health.get('value')!='Healthy': return None
    values=[valid_value(sample,k) for k in ('house_power','ev_power','heat_pump_power','immersion_power')]
    if any(v is None or v<0 for v in values): return None
    reported=sample.get('signals',{}).get('house_power',{}).get('last_reported')
    try:
        age=(instant(sample['observed_at'])-instant(reported)).total_seconds()
        if age < -10 or age > 300: return None
    except (ValueError, TypeError, AttributeError): return None
    value=values[0]-sum(values[1:])
    return max(0.0,value) if value>=-100 else None

def make_hourly_points(samples, now, history_days=45):
    cutoff=(now.astimezone(TZ).date()-timedelta(days=history_days)).isoformat()
    today=now.astimezone(TZ).date().isoformat()
    bins=defaultdict(lambda:[0.0,0.0,None,None,None]); previous=None
    for sample in samples:
        at=instant(sample['observed_at'])
        if previous is not None:
            old,old_at=previous; seconds=(at-old_at).total_seconds(); v=residual_w(old)
            workday=old.get('signals',{}).get('workday',{}).get('value')
            if 0<seconds<=90 and v is not None and residual_w(sample) is not None and workday in ('on','off'):
                a=old_at.timestamp(); end=at.timestamp()
                while a<end:
                    slot=math.floor(a/3600)*3600; b=min(end,slot+3600); local=datetime.fromtimestamp(a,TZ); date=local.date().isoformat()
                    if cutoff<=date<today and old.get('local_date')==date:
                        record=bins[slot]; record[0]+=v*(b-a); record[1]+=b-a; record[2:]=[date,old['season'],workday=='on']
                    a=b
        previous=(sample,at)
    points=[]; coverage=defaultdict(float)
    for slot,(energy,seconds,date,season,workday) in sorted(bins.items()):
        coverage[date]+=seconds
        if seconds>=3240:
            points.append({'date':date,'season':season,'workday':workday,'hour':datetime.fromtimestamp(slot,TZ).hour,'start_ts':slot,'watts':energy/seconds,'coverage_seconds':seconds})
    good_days=set()
    for date,seconds in coverage.items():
        start=datetime.fromisoformat(date).replace(tzinfo=TZ)
        actual_day_seconds=(start+timedelta(days=1)).timestamp()-start.timestamp()
        if seconds/actual_day_seconds>=.90: good_days.add(date)
    return [p for p in points if p['date'] in good_days],sorted(good_days)

def profile_key(point):
    return f"{point['season']}|{'workday' if point['workday'] else 'offday'}|{point['hour']:02d}"

def train_candidate(points, now, cfg):
    today=now.astimezone(TZ).date().isoformat()
    points=[p for p in points if p['date']<today and math.isfinite(p['watts']) and p['watts']>=0]
    days=sorted({p['date'] for p in points})
    result={'schema_version':1,'mode':'candidate_only','control_writes':0,'calculated_at':now.isoformat(),'complete_days':len(days),'minimum_complete_days':cfg['min_complete_days'],'status':'collecting','applied_to_control':False,'models':{},'validation':None,'warning_cs':'Odhad zbytkové spotřeby, nikoli souhlas s provozním řízením nebo důkaz úspory.'}
    if len(days)<cfg['min_complete_days']:
        result['reason']='NOT_ENOUGH_COMPLETE_DAYS'; return result
    split=days[-cfg['holdout_days']]; train=[p for p in points if p['date']<split]; test=[p for p in points if p['date']>=split]
    grouped=defaultdict(list)
    for p in train: grouped[profile_key(p)].append(p)
    models={}; latest=instant(days[-1]+'T00:00:00+00:00')
    for key,items in grouped.items():
        if len({p['date'] for p in items})<3: continue
        values=[p['watts'] for p in items]; reference=mean(values)
        weights=[2**(-((latest-instant(p['date']+'T00:00:00+00:00')).days)/cfg['half_life_days']) for p in items]
        weighted=sum(v*w for v,w in zip(values,weights))/sum(weights); delta=reference*cfg['max_correction_fraction']
        candidate=max(reference-delta,min(reference+delta,weighted))
        models[key]={'reference_w':round(reference,4),'candidate_w':round(candidate,4),'training_days':len({p['date'] for p in items}),'latest_training_day':max(p['date'] for p in items)}
    valid=[p for p in test if profile_key(p) in models]
    if len(valid)<24:
        result.update(status='insufficient_validation',reason='NO_SUFFICIENT_MATCHING_SEASON_AND_HOURS'); return result
    old_mae=mean(abs(p['watts']-models[profile_key(p)]['reference_w']) for p in valid)
    new_mae=mean(abs(p['watts']-models[profile_key(p)]['candidate_w']) for p in valid)
    improvement=(old_mae-new_mae)/old_mae if old_mae>0 else 0.0
    accepted=improvement>=cfg['minimum_improvement_fraction']
    result.update(status='candidate_improves_holdout' if accepted else 'candidate_not_better',reason='REVIEW_REQUIRED_NO_AUTOMATIC_CONTROL_CHANGE',models=models,training_end=split,validation={'reference_mae_w':round(old_mae,4),'candidate_mae_w':round(new_mae,4),'relative_improvement':round(improvement,5),'test_hours':len(valid),'test_days':len({p['date'] for p in valid}),'note':'Rolling monitoring holdout, not an independent certification dataset.'})
    trends={}
    for season in sorted({p['season'] for p in points}):
        daily=defaultdict(list)
        for p in points:
            if p['season']==season: daily[p['date']].append(p['watts'])
        rows=[(datetime.fromisoformat(d).toordinal(),mean(v)) for d,v in sorted(daily.items())]
        slopes=[(b[1]-a[1])/(b[0]-a[0]) for i,a in enumerate(rows) for b in rows[i+1:] if b[0]>a[0]]
        trends[season]={'watts_per_day':round(median(slopes),3) if slopes else None,'days':len(rows),'note':'Descriptive only; occupancy/weather changes may confound trend.'}
    result['observed_trends']=trends
    result['model_hash']=digest({'models':models,'validation':result['validation'],'training_end':split})
    return result

def calibrate(store,cfg,now=None):
    now=now or datetime.now(timezone.utc)
    if not cfg['enabled']: return {'status':'disabled','applied_to_control':False,'mode':'candidate_only'}
    cutoff=(now.astimezone(TZ).date()-timedelta(days=cfg['history_days'])).isoformat()
    rows=store.db.execute('SELECT payload FROM samples WHERE day>=? ORDER BY available_at',(cutoff,))
    points,days=make_hourly_points((unpack(row[0]) for row in rows),now,cfg['history_days'])
    result=train_candidate(points,now,cfg)
    result['last_complete_day']=days[-1] if days else None
    result['source']='house_power - ev_power - heat_pump_power - immersion_power'
    result['not_implemented']=['battery_capacity_fit','battery_efficiency_fit','pv_forecast_bias_fit','thermal_model_fit','autonomous_control']
    return result
