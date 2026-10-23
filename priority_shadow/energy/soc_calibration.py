"""Causal rolling calibration of forecast and non-EV household demand.

Only completed observed periods are training evidence. Candidates must improve
a chronological holdout; absent evidence remains explicit. Models never change
equipment policy, reserve, priorities or contractual tariffs.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone, time
from math import exp
from statistics import mean, median
from .core import TZ, instant, digest
from .pricing import valid


def quantile(values, q):
    values = sorted(v for v in values if valid(v))
    if not values:
        return None
    p = (len(values)-1)*q; i = int(p)
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(p-i)


def season(at):
    m=at.astimezone(TZ).month
    return 'winter' if m in (12,1,2) else 'spring' if m in (3,4,5) else 'summer' if m in (6,7,8) else 'autumn'


def lead(hours):
    return '0-6' if 0<=hours<6 else '6-24' if 6<=hours<24 else '24-48' if 24<=hours<48 else 'other'


def pv_key(row):
    at=instant(row['target']);ahead=(at-instant(row['forecast_available_at'])).total_seconds()/3600
    return season(at),at.astimezone(TZ).hour//4,lead(ahead)


def fit_pv(pairs, now):
    today=now.astimezone(TZ).date().isoformat();groups=defaultdict(list)
    for row in pairs:
        if (row.get('source')=='own_minute_snapshots_and_prior_decision_archive'
                and row.get('coverage_schema')!='common-intervals-v2'):continue
        try:
            target=instant(row['target']);available=instant(row['available_at'])
            forecast_at=instant(row['forecast_available_at'])
        except (ValueError,KeyError,TypeError):continue
        if (row.get('constrained') is not False or available>now or forecast_at>target
                or target.astimezone(TZ).date().isoformat()>=today
                or not valid(row.get('forecast_ac_kwh')) or row['forecast_ac_kwh']<.2
                or not valid(row.get('actual_ac_proxy_kwh')) or row['actual_ac_proxy_kwh']<0):continue
        s,h,l=pv_key(row)
        for key in (f'{s}|{h}|{l}',f'{s}|*|{l}',f'{s}|*|*'):groups[key].append(row)
    models={}
    for key,rows in groups.items():
        days=sorted({r['day'] for r in rows})[-90:]
        if len(days)<28:continue
        test_count=max(7,min(14,len(days)//5));boundary=days[-test_count]
        training=[r for r in rows if days[0]<=r['day']<boundary]
        testing=[r for r in rows if r['day']>=boundary]
        if len({r['day'] for r in training})<14 or len(testing)<10:continue
        raw_total=sum(r['forecast_ac_kwh'] for r in training)
        factor=sum(r['actual_ac_proxy_kwh'] for r in training)/raw_total
        if not .3<=factor<=1.5:continue
        raw=mean(abs(r['actual_ac_proxy_kwh']-r['forecast_ac_kwh']) for r in testing)
        corrected=mean(abs(r['actual_ac_proxy_kwh']-r['forecast_ac_kwh']*factor) for r in testing)
        accepted=raw>0 and corrected<=raw*.97
        used=factor if accepted else 1.
        daily=defaultdict(lambda:[0.,0.])
        for r in training:
            daily[r['day']][0]+=r['actual_ac_proxy_kwh'];daily[r['day']][1]+=r['forecast_ac_kwh']*used
        ratios=[a/b for a,b in daily.values() if b>.5]
        models[key]={'factor':used,'candidate_factor':factor,'accepted':accepted,
                     'train_days':len(daily),'test_days':test_count,'test_hours':len(testing),
                     'train_before':boundary,'raw_mae_kwh':raw,'corrected_mae_kwh':corrected,
                     'low_multiplier':quantile(ratios,.1),'high_multiplier':quantile(ratios,.9),
                     'boundary':'dc_counter_times_observed_ac_dc_proxy',
                     'validation':'chronological_holdout_replay','automatic_control_change':False}
    return models


def correction(models, target, available):
    s=season(target);h=target.astimezone(TZ).hour//4;l=lead((target-available).total_seconds()/3600)
    for key in (f'{s}|{h}|{l}',f'{s}|*|{l}',f'{s}|*|*'):
        if key in models:return key,models[key]
    return None,{'factor':1.,'accepted':False,'reason':'insufficient_chronological_validation',
                 'low_multiplier':None,'high_multiplier':None}


class Household:
    def __init__(self, hours, now):
        self.hours=[];self.by_hour=defaultdict(list);self.recency={};today=now.astimezone(TZ).date()
        for row in hours:
            try:at=instant(row['at']);available=instant(row['available_at'])
            except (KeyError,TypeError,ValueError):continue
            if available>now or at.astimezone(TZ).date()>=today:continue
            if not valid(row.get('house_without_ev_kwh')) or not 0<=row['house_without_ev_kwh']<=25:continue
            if row.get('quality')!='observed':continue
            self.hours.append(row)
            self.by_hour[at.astimezone(TZ).hour].append(row)
            self.recency[row['at']]=min(8,max(0,(now-available).total_seconds()/86400)/90)
        self.last_day=max((r['at'][:10] for r in self.hours),default=None)
        self.source_hash=digest(self.hours)
        self.now=now

    def predict(self,target,temperature=None):
        local=target.astimezone(TZ);s=season(target);weekend=local.weekday()>=5
        rows=self.by_hour[local.hour]
        stages=[('season_daytype',[r for r in rows if r['season']==s and r['weekend']==weekend]),
                ('season',[r for r in rows if r['season']==s]),('hour_all_seasons',rows)]
        for grouping,rows in stages:
            if len({r['day'] for r in rows})<5:continue
            def distance(r):
                t=r.get('temperature_c')
                return (abs(t-temperature) if valid(t) and valid(temperature) else 4)+self.recency[r['at']]
            selected=sorted(rows,key=distance)[:24]
            values=[r['house_without_ev_kwh'] for r in selected]
            return {'central_kw':median(values),'low_kw':quantile(values,.15),
                    'high_kw':quantile(values,.85),'samples':len(selected),
                    'days':len({r['day'] for r in selected}),'group':grouping,
                    'temperature_used':valid(temperature),'includes_heat_and_immersion':True,
                    'source':'historical_house_minus_ev','oldest_day':min(r['day'] for r in selected),
                    'newest_day':max(r['day'] for r in selected)}
        return None


def pre_window(day):
    """Five real minutes before 03:00, including the repeated autumn hour."""
    return datetime.combine(datetime.fromisoformat(day).date(),time(3),TZ).astimezone(timezone.utc)-timedelta(minutes=5)


def archived_weather(versions,decision_at):
    usable=[]
    for version in versions:
        try:available=instant(version['available_at'])
        except (KeyError,ValueError,TypeError):continue
        payload=version.get('payload') or {}
        if (0<=(decision_at-available).total_seconds()<8*3600
                and payload.get('units',{}).get('temperature_unit')=='°C'):
            usable.append(version)
    if not usable:return None
    return max(usable,key=lambda v:instant(v['available_at']))


def forecast_temperature(rows,target):
    matches=[]
    for row in rows:
        try:distance=abs((instant(row['datetime'])-target).total_seconds())
        except (KeyError,ValueError,TypeError):continue
        if distance<=3600 and valid(row.get('temperature')):matches.append((distance,row['temperature']))
    return min(matches,key=lambda x:x[0])[1] if matches else None


def validate_household(hours, now, weather_versions=()):
    """Chronological holdout using only weather known before each night's window."""
    complete=sorted({r['day'] for r in hours if r.get('quality')=='observed'
                     and instant(r['available_at'])<=now and r['day']<now.astimezone(TZ).date().isoformat()})
    if len(complete)<28:return {'status':'insufficient_holdout','use_temperature':False}
    boundary=complete[-7];training=[r for r in hours if r['day']<boundary]
    model=Household(training,instant(boundary+'T00:00:00+00:00'));raw=[];candidate=[];sources={};missing=0
    for day in complete[-7:]:
        version=archived_weather(weather_versions,pre_window(day))
        if version:sources[day]=version
    for r in hours:
        if r['day']<boundary or r.get('quality')!='observed' or instant(r['available_at'])>now:continue
        if r['day'] not in complete[-7:]:continue
        version=sources.get(r['day']);at=instant(r['at'])
        if at<pre_window(r['day']):continue
        temperature=forecast_temperature((version or {}).get('payload',{}).get('forecast',[]),at)
        if temperature is None:missing+=1;continue
        a=model.predict(at,None);b=model.predict(at,temperature)
        if a and b:
            raw.append(abs(a['central_kw']-r['house_without_ev_kwh']))
            candidate.append(abs(b['central_kw']-r['house_without_ev_kwh']))
    accepted=len(raw)>=72 and mean(raw)>0 and mean(candidate)<=mean(raw)*.97
    return {'status':'accepted_for_shadow' if accepted else 'insufficient_asof_weather' if len(raw)<72 else 'temperature_candidate_not_better',
            'use_temperature':accepted,'train_before':boundary,'test_days':7,'test_hours':len(raw),
            'reference_mae_kw':mean(raw) if raw else None,'candidate_mae_kw':mean(candidate) if candidate else None,
            'validation':'chronological_holdout_causal_weather','feature_source':'archived_weather_asof_02:55',
            'test_window':'after_pre_window_decision_to_midnight',
            'missing_weather_hours':missing,'weather_sources':{day:{'available_at':v['available_at'],
                 'hash':v.get('hash') or digest(v['payload'])} for day,v in sources.items()},
            'automatic_control_change':False}
