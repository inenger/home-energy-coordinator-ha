"""EV meter accounting, with interval pricing and explicit source/coverage limitations."""
from __future__ import annotations
from collections import defaultdict
from .core import instant, TZ
from .pricing import split, totals, valid


def analyze(rows, now, tariff_book=None):
    rows=sorted((r for r in rows if instant(r['at'])<=now),key=lambda r:instant(r['at']))
    if not rows: return {'status':'collecting','sessions':[],'month':{},'months':[]}
    increments=[]
    for a,b in zip(rows,rows[1:]):
        for x in split(a,b,book=tariff_book,max_kw=25):
            x.update(soc=b.get('soc'));increments.append(x)
    groups=defaultdict(list)
    for x in increments: groups[x['month']].append(x)
    sessions=[];current=[]
    for x in increments:
        if x['energy_kwh']<=0: continue
        if current and ((x['start']-current[-1]['at']).total_seconds()>600 or x['long_gap']):
            sessions.append(current);current=[]
        current.append(x)
        if x['long_gap']: sessions.append(current);current=[]
    if current: sessions.append(current)
    finished=[]
    for xs in sessions:
        result=totals(xs)
        finished.append({'start':xs[0]['start'].isoformat(),'end':xs[-1]['at'].isoformat(),
            'start_month':xs[0]['start'].astimezone(TZ).strftime('%Y-%m'),
            'energy_kwh':result.pop('home_charge_kwh'),**result,
            'soc_start':xs[0].get('soc'),'soc_end':xs[-1].get('soc'),
            'status':'incomplete_gap' if any(x['long_gap'] for x in xs) else
                'open_or_recent' if (now-xs[-1]['at']).total_seconds()<600 else 'observed_session'})
    months=[{'month':m,**totals(xs),'sessions':sum(s['start_month']==m for s in finished)} for m,xs in sorted(groups.items())]
    key=now.astimezone(TZ).strftime('%Y-%m')
    month=next((m for m in months if m['month']==key),{'month':key,**totals([]),'sessions':0})
    driving={'distance_km':None,'vehicle_energy_kwh':None,'kwh_per_100km':None}
    mr=[r for r in rows if instant(r['at']).astimezone(TZ).strftime('%Y-%m')==key]
    if len(mr)>1:
        a,b=mr[0],mr[-1]
        for field,out,limit in [('odometer_km','distance_km',10000),('vehicle_energy_total_kwh','vehicle_energy_kwh',5000)]:
            if valid(a.get(field)) and valid(b.get(field)) and 0<=b[field]-a[field]<limit:
                driving[out]=round(b[field]-a[field],3)
        if (driving['distance_km'] or 0)>=10 and driving['vehicle_energy_kwh'] is not None:
            driving['kwh_per_100km']=round(driving['vehicle_energy_kwh']/driving['distance_km']*100,2)
    month={**month,**driving,'observed_from':mr[0]['at'] if mr else None,'observed_until':mr[-1]['at'] if mr else None,
        'month_complete':False,'vehicle_energy_definition_verified':False}
    return {'status':'ok','month':month,'months':months[-12:],'sessions':finished[-30:],
        'cost_definition':'Meter delta split across archived tariff/calendar boundaries; tariff equivalent, not a grid-source invoice.',
        'allocation_uncertainty':'Energy inside a meter interval is allocated by duration; long gaps are unpriced.'}
