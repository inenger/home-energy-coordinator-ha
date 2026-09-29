"""Hourly forecast/reality pairs with chronological holdout, not in-sample success."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median, mean
import math
from .core import instant, TZ
from .weather import lead_bucket
from .pricing import valid


def _season(dt):
    m=dt.astimezone(TZ).month
    return 'winter' if m in (12,1,2) else 'spring' if m in (3,4,5) else 'summer' if m in (6,7,8) else 'autumn'


def actual_hourly(rows,now):
    bins=defaultdict(lambda:{'energy':0.,'seconds':0.})
    rows=sorted((r for r in rows if instant(r['at'])<=now),key=lambda r:instant(r['at']))
    for a,b in zip(rows,rows[1:]):
        ta=instant(a['at']);tb=instant(b['at']);seconds=(tb-ta).total_seconds()
        ea,eb=a.get('energy_today_kwh'),b.get('energy_today_kwh')
        if not valid(ea) or not valid(eb) or not 0<seconds<=90: continue
        if ta.astimezone(TZ).date()!=tb.astimezone(TZ).date() or not 0<=eb-ea<=20*seconds/3600+.15: continue
        if a.get('limited') is True or b.get('limited') is True: continue
        start=ta.timestamp();end=tb.timestamp()
        while start<end:
            hour=math.floor(start/3600)*3600;stop=min(end,hour+3600)
            bins[hour]['energy']+=(eb-ea)*(stop-start)/seconds
            bins[hour]['seconds']+=stop-start;start=stop
    return {h:v['energy'] for h,v in bins.items() if v['seconds']>=3240 and h+3600<=now.timestamp()}


def calibrate(forecasts,pv_rows,now):
    actual=actual_hourly(pv_rows,now);chosen={}
    for version in forecasts:
        try: available=instant(version['available_at']).timestamp()
        except (KeyError,TypeError,ValueError): continue
        for row in version.get('payload',{}).get('detailedHourly',[]):
            try: target=instant(row['period_start']).timestamp();raw=row['pv_estimate']
            except (KeyError,TypeError,ValueError): continue
            bucket=lead_bucket((target-available)/3600)
            if not bucket or target not in actual or not valid(raw) or raw<.05: continue
            key=(target,bucket)
            if key in chosen and chosen[key]['available_ts']>=available: continue
            dt=datetime.fromtimestamp(target,timezone.utc)
            chosen[key]={'target':dt.isoformat(),'day':dt.astimezone(TZ).date().isoformat(),
                'season':_season(dt),'bucket':bucket,'available_ts':available,
                'raw_kwh':raw,'actual_kwh':actual[target],'p10':row.get('pv_estimate10'),'p90':row.get('pv_estimate90')}
    groups=defaultdict(list)
    for p in chosen.values(): groups[p['season']+'|'+p['bucket']].append(p)
    models={};recent=[]
    for key,pairs in groups.items():
        days=sorted({p['day'] for p in pairs});model=None
        if len(days)>=8:
            boundary=days[-3];train=[p for p in pairs if p['day']<boundary];test=[p for p in pairs if p['day']>=boundary]
            daily=defaultdict(list)
            for p in train: daily[p['day']].append(p['actual_kwh']/p['raw_kwh'])
            factor=max(.5,min(1.6,median(median(rs) for rs in daily.values())))
            raw_mae=mean(abs(p['actual_kwh']-p['raw_kwh']) for p in test)
            corr_mae=mean(abs(p['actual_kwh']-p['raw_kwh']*factor) for p in test)
            accepted=raw_mae>0 and corr_mae<=raw_mae*.97
            bounded=[p for p in test if valid(p['p10']) and valid(p['p90'])]
            model={'factor':round(factor if accepted else 1.,4),'candidate_factor':round(factor,4),
                'accepted_for_shadow':accepted,'samples':len(pairs),'train_days':len(daily),'test_days':3,
                'validation':'chronological_holdout','train_before':boundary,'test_hours':len(test),
                'mae_raw_kwh':round(raw_mae,4),'mae_corrected_kwh':round(corr_mae,4),
                'improvement_pct':round((raw_mae-corr_mae)/raw_mae*100,2) if raw_mae else 0,
                'p10_p90_coverage':sum(min(p['p10'],p['p90'])<=p['actual_kwh']<=max(p['p10'],p['p90']) for p in bounded)/len(bounded) if bounded else None,
                'curtailment_verified':False}
            models[key]=model
        for p in pairs:
            tested=model is not None and p['day']>=model['train_before']
            recent.append({'target':p['target'],'bucket':p['bucket'],'raw_kwh':p['raw_kwh'],'actual_kwh':p['actual_kwh'],
                'corrected_kwh':p['raw_kwh']*model['candidate_factor'] if tested else None,
                'evaluation':'holdout_replay' if tested else 'not_scored',
                'available_at':datetime.fromtimestamp(p['available_ts'],timezone.utc).isoformat()})
    return {'status':'ok' if models else 'collecting','models':models,'fallback_factor':1.0,
        'paired_forecasts':len(chosen),'observed_hours':len(actual),
        'recent_pairs':sorted(recent,key=lambda p:(p['target'],p['bucket']))[-200:],
        'note':'Hourly kWh, acquisition-to-period-start lead; eight distinct days required. Holdout replay is not a historical issued forecast. Curtailment reference remains unverified.'}


def corrected_upcoming(latest_payloads,calibration,now):
    out={}
    for name,p in latest_payloads.items():
        available_text=p.get('_available_at');parts=[];raw_total=0.;total=0.
        try: available=instant(available_text).timestamp()
        except (TypeError,ValueError,AttributeError): available=None
        for row in p.get('detailedHourly',[]):
            try: dt=instant(row['period_start']);raw=row['pv_estimate']
            except (KeyError,TypeError,ValueError): continue
            if dt<now or not valid(raw): continue
            bucket=lead_bucket((dt.timestamp()-available)/3600) if available is not None else None
            model=calibration.get('models',{}).get(_season(dt)+'|'+str(bucket),{})
            factor=model.get('factor',1.);raw_total+=raw;total+=raw*factor
            parts.append({'start':dt.isoformat(),'raw_kwh':raw,'corrected_kwh':raw*factor,'factor':factor,'lead_bucket':bucket})
        out[name]={'raw_kwh':round(raw_total,4),'corrected_kwh':round(total,4),'periods':len(parts),
            'forecast_available_at':available_text,'hourly':parts,'correction_mode':'shadow_only'}
    return out
