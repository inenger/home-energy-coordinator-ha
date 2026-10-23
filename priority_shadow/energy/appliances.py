"""Smart-plug discovery and interpretable appliance-cycle analytics."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta
import math
import re
from .core import instant, TZ

CYCLIC = {
    "dishwasher": {"start_w": 8.0, "idle_w": 3.0, "idle_minutes": 8, "min_minutes": 10},
    "washer": {"start_w": 5.0, "idle_w": 2.0, "idle_minutes": 8, "min_minutes": 8},
    "3d_printer": {"start_w": 15.0, "idle_w": 5.0, "idle_minutes": 10, "min_minutes": 10},
}

def _kind(text: str) -> str:
    import unicodedata
    t=''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c))
    if re.search(r"\b(ntb|notebook|laptop)\b",t): return "laptop"
    if re.search(r"\b(myck\w*|dishwasher)\b",t): return "dishwasher"
    if re.search(r"\b(prack\w*|washer|washing)\b",t): return "washer"
    if "3d" in t and ("tisk" in t or "print" in t): return "3d_printer"
    if "lednic" in t: return "fridge"
    if "router" in t: return "router"
    if re.search(r"\btv\b",t): return "tv"
    if "cerpad" in t: return "pump"
    return "generic"


def _eligible(entity_id: str) -> bool:
    x = entity_id.lower()
    return (
        "shellyplug" in x or "shellyplusplugs" in x or "shellyplus1pm" in x
        or x.startswith("sensor.lednice_") or x.startswith("sensor.tv_")
    ) and "shellypro3em" not in x

def _stem(entity_id: str):
    for suffix in ("_switch_0_power", "_switch_0_energy", "_power", "_energy"):
        if entity_id.endswith(suffix):
            base = entity_id[:-len(suffix)]
            role = "power" if suffix.endswith("power") else "energy"
            return base, role
    return None, None

def discover(states, overrides=None):
    overrides=overrides or {}
    """Return stable plug-level measurements without reading device registry."""
    groups = defaultdict(dict)
    for state in states:
        eid = state.get("entity_id", "")
        if not eid.startswith("sensor.") or not _eligible(eid):
            continue
        base, role = _stem(eid)
        if not base:
            continue
        unit = state.get("attributes", {}).get("unit_of_measurement")
        if role == "power" and unit not in ("W", "kW"): continue
        if role == "energy" and unit not in ("kWh", "Wh"): continue
        groups[base][role] = state
    result = {}
    for base, pair in sorted(groups.items()):
        if "power" not in pair and "energy" not in pair:
            continue
        names = [str(x.get("attributes", {}).get("friendly_name", "")) for x in pair.values()]
        label = next((n for n in names if n and not n.lower().startswith('shelly')),names[0] if names else base.split('.',1)[-1])
        label = re.sub(r"(?i)\s+(power|výkon|energie|energy)$", "", label)
        label = re.sub(r"(?i)\s+switch_0$", "", label).strip(" -")
        item = {"id": base.split(".",1)[-1], "label": label, "kind": _kind(label+" "+base)}
        for role, state in pair.items():
            raw = str(state.get("state", ""))
            try:
                value = float(raw)
                if not math.isfinite(value): raise ValueError
                unit = state.get("attributes", {}).get("unit_of_measurement")
                if role == "power" and unit == "kW": value *= 1000
                if role == "energy" and unit == "Wh": value /= 1000
                item[role+"_value"] = value
                item[role+"_entity"] = state["entity_id"]
                item[role+"_quality"] = "valid"
            except (ValueError, TypeError):
                item[role+"_value"] = None
                item[role+"_entity"] = state["entity_id"]
                item[role+"_quality"] = "invalid"
        override=overrides.get(item['id'],{})
        for key in ('label','kind'):
            if key in override: item[key]=str(override[key])[:160]
        item['mapping_source']='user_override' if override else 'name_candidate'
        result[item["id"]] = item
    return result

def positive_delta(previous,current,elapsed_seconds,max_kw=30.0):
    from .pricing import valid
    if not valid(previous) or not valid(current) or not 0<elapsed_seconds<=31*86400: return None
    delta=current-previous
    return delta if 0<=delta<=max_kw*elapsed_seconds/3600+.05 else None


def _sessions(rows,kind,book=None):
    from .pricing import split,totals,valid
    cfg=CYCLIC.get(kind)
    if not cfg: return []
    output=[];active=None;idle=None;previous=None
    for r in rows:
        at=instant(r['at']);power=r.get('power_w')
        gap=previous is not None and (at-instant(previous['at'])).total_seconds()>180
        reset=previous is not None and valid(r.get('energy_kwh')) and valid(previous.get('energy_kwh')) and r['energy_kwh']<previous['energy_kwh']
        if not valid(power) or gap or reset:
            active=None;idle=None;previous=r;continue
        if active is None:
            if power>=cfg['start_w'] and previous is not None and valid(previous.get('power_w')) and previous['power_w']<=cfg['idle_w']:
                active={'start':instant(previous['at']),'peak':power,'increments':[]}
        if active:
            active['peak']=max(active['peak'],power)
            if previous: active['increments'].extend(split(previous,r,energy_key='energy_kwh',book=book))
            if power<=cfg['idle_w']:
                idle=idle or at
                if (at-idle).total_seconds()>=cfg['idle_minutes']*60:
                    duration=(idle-active['start']).total_seconds()/60
                    if duration>=cfg['min_minutes']:
                        xs=[x for x in active['increments'] if x['start']<idle];t=totals(xs)
                        output.append({'start':active['start'].isoformat(),'end':idle.isoformat(),
                            'duration_min':round(duration,1),'energy_kwh':t.pop('home_charge_kwh'),**t,
                            'peak_w':round(active['peak'],1),'classification':'heuristic_completed_cycle'})
                    active=None;idle=None
            else: idle=None
        previous=r
    return output


def summarize(rows_by_appliance,now,tariff_book=None,overrides=None):
    from .pricing import split,totals,day_seconds
    overrides=overrides or {};today=now.astimezone(TZ).date();out={}
    for aid,rows in rows_by_appliance.items():
        rows=sorted((r for r in rows if instant(r['at'])<=now),key=lambda r:instant(r['at']))
        if not rows: continue
        label=rows[-1]['label'];kind=overrides.get(aid,{}).get('kind',_kind(label+' '+aid))
        dayparts=defaultdict(list)
        for a,b in zip(rows,rows[1:]):
            for x in split(a,b,energy_key='energy_kwh',book=tariff_book): dayparts[x['day']].append(x)
        daily={d:totals(xs) for d,xs in dayparts.items()}
        def days_ago(lo,hi):
            return [d for d in daily if today-timedelta(days=hi)<=datetime.fromisoformat(d).date()<=today-timedelta(days=lo)]
        recent=days_ago(0,29);week=days_ago(0,6)
        def energy(ds): return sum(daily[d]['home_charge_kwh'] for d in ds)
        complete=[d for d,v in daily.items() if d<today.isoformat() and v['covered_seconds']>=.9*day_seconds(d)]
        w1=days_ago(1,7);w0=days_ago(8,14);trend=None
        if len(w1)==len(w0)==7 and set(w1+w0)<=set(complete) and energy(w0)>0:
            trend=(energy(w1)/energy(w0)-1)*100
        cycles=_sessions(rows,kind,tariff_book)
        cyc=[s for s in cycles if instant(s['start']).astimezone(TZ).date().isoformat() in recent]
        complete30=[d for d in complete if d in recent]
        completecycles=[s for s in cyc if instant(s['start']).astimezone(TZ).date().isoformat() in complete30 and instant(s['end']).astimezone(TZ).date().isoformat() in complete30]
        priced=sum(daily[d]['priced_kwh'] for d in recent)
        cost=sum(daily[d]['tariff_equivalent_cost_czk'] or 0 for d in recent)
        out[aid]={'id':aid,'label':label,'kind':kind,'energy_7d_kwh':round(energy(week),4),'energy_30d_kwh':round(energy(recent),4),
            'tariff_equivalent_cost_30d_czk':round(cost,3) if priced else None,
            'unpriced_30d_kwh':round(sum(daily[d]['unpriced_kwh'] for d in recent),4),
            'trend_7d_vs_prev7_pct':round(trend,2) if trend is not None else None,
            'cycles_30d':len(cyc),'cycles_per_day_30d':round(len(completecycles)/len(complete30),3) if complete30 else None,
            'complete_days_30d':len(complete30),'observed_days_30d':len(recent),
            'avg_cycle_kwh':round(sum(s['energy_kwh'] for s in cyc)/len(cyc),4) if cyc else None,
            'last_power_w':rows[-1].get('power_w'),'sessions':cyc[-20:],
            'daily':[{'date':d,**v,'energy_kwh':v['home_charge_kwh']} for d,v in sorted(daily.items())],
            'note':'Cycles are heuristic; incomplete/gapped cycles and unobserved days are not counted as zero.'}
    return out
