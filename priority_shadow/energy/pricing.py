"""Conserved meter deltas split at tariff/time/calendar boundaries, with quality flags."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from bisect import bisect_right
import math
from .core import instant, TZ


def valid(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


class TariffBook:
    def __init__(self, versions=()):
        self.by_hour=defaultdict(list);boundaries=set()
        for version in versions:
            try: available=instant(version['available_at']).timestamp()
            except (KeyError,TypeError,ValueError): continue
            p=version.get('payload') or {}
            for row in (p.get('today') or [])+(p.get('tomorrow') or []):
                try:
                    start=instant(row['start']).timestamp();end=instant(row['end']).timestamp();price=row['price']
                    if not valid(price) or not 0<end-start<=86400: continue
                except (KeyError,TypeError,ValueError): continue
                entry=(available,start,end,price);boundaries.update((start,end,available))
                for hour in range(math.floor(start/3600),math.ceil(end/3600)): self.by_hour[hour].append(entry)
        for entries in self.by_hour.values(): entries.sort()
        self.boundaries=sorted(boundaries)

    def price(self, at):
        matches=[r for r in self.by_hour.get(math.floor(at/3600),()) if r[0]<=at and r[1]<=at<r[2]]
        if not matches: return None
        newest=max(r[0] for r in matches);prices={r[3] for r in matches if r[0]==newest}
        return prices.pop() if len(prices)==1 else None

    def cuts(self, start, end):
        return self.boundaries[bisect_right(self.boundaries,start):bisect_right(self.boundaries,end)]


def split(previous, current, energy_key='energy_total_kwh', book=None, max_kw=30., max_price_gap=900):
    """Time allocation is an estimate inside a meter interval, not a new measurement."""
    try: a=instant(previous['at']).timestamp();b=instant(current['at']).timestamp()
    except (KeyError,TypeError,ValueError): return []
    e0,e1=previous.get(energy_key),current.get(energy_key)
    if not valid(e0) or not valid(e1) or not 0<b-a<=31*86400: return []
    delta=e1-e0
    if delta<0 or delta>max_kw*(b-a)/3600+.05: return []
    cuts={a,b};cuts.update(x*3600 for x in range(math.floor(a/3600)+1,math.ceil(b/3600)))
    if book: cuts.update(book.cuts(a,b))
    cuts=sorted(x for x in cuts if a<=x<=b);result=[];remaining=delta
    for i,(start,end) in enumerate(zip(cuts,cuts[1:])):
        energy=remaining if i==len(cuts)-2 else delta*(end-start)/(b-a);remaining-=energy
        price=None;method='unpriced'
        if b-a<=max_price_gap:
            if book is not None:
                price=book.price(start);method='archived_tariff_asof' if price is not None else 'missing_tariff'
            elif math.floor(start/3600)==math.floor(a/3600) and valid(previous.get('buy_price')):
                price=previous['buy_price'];method='previous_observation_same_hour'
        local=datetime.fromtimestamp(start,TZ)
        result.append({'at':datetime.fromtimestamp(end,timezone.utc),'start':datetime.fromtimestamp(start,timezone.utc),
            'day':local.date().isoformat(),'month':local.strftime('%Y-%m'),'energy_kwh':energy,
            'priced_kwh':energy if price is not None else 0.,'cost_czk':energy*price if price is not None else None,
            'price':price,'seconds':end-start,'covered_seconds':end-start if b-a<=90 else 0.,
            'price_source':method,'allocation':'uniform_between_meter_readings','long_gap':b-a>max_price_gap})
    return result


def totals(increments):
    energy=sum(x['energy_kwh'] for x in increments);priced=sum(x['priced_kwh'] for x in increments)
    cost=sum(x['cost_czk'] for x in increments if x['cost_czk'] is not None)
    covered=sum(x['covered_seconds'] for x in increments)
    return {'home_charge_kwh':round(energy,6),'priced_kwh':round(priced,6),'unpriced_kwh':round(max(0,energy-priced),6),
        'tariff_equivalent_cost_czk':round(cost,4) if priced or energy==0 and covered else None,
        'weighted_price_czk_kwh':round(cost/priced,6) if priced else None,'covered_seconds':round(covered,1),
        'coverage_status':'partial_observation','allocation_method':'uniform_between_meter_readings'}


def day_seconds(day):
    dt=datetime.fromisoformat(day).replace(tzinfo=TZ)
    return (dt+timedelta(days=1)).timestamp()-dt.timestamp()
