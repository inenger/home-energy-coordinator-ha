"""Empirical shadow power budget; never a breaker protection or actuator approval."""
import math
from datetime import timedelta
from .core import instant, digest
from .pricing import valid
from .store import unpack

POLICY = 'phase-budget-v1-observed-night-envelope'


def fallback():
    return {'policy': POLICY, 'status': 'insufficient_history', 'breaker_a': 25.,
            'reserve_a': [3.]*3, 'power_factor': [.9]*3, 'house_phase_shares': [1/3]*3,
            'source': 'explicit_legacy_fallback', 'control_verified': False}


def checked(context):
    c = context or fallback()
    if c.get('status')=='observed_steps_exceed_budget':raise ValueError('OBSERVED_PHASE_BUDGET_BLOCKED')
    for key in ('reserve_a', 'power_factor', 'house_phase_shares'):
        values = c.get(key)
        if not isinstance(values, list) or len(values) != 3 or not all(valid(v) for v in values):
            raise ValueError('INVALID_PHASE_BUDGET')
    if c.get('breaker_a') != 25 or any(not 0 <= v < 25 for v in c['reserve_a']):
        raise ValueError('INVALID_PHASE_RESERVE')
    if any(not .5 <= v <= 1 for v in c['power_factor']):
        raise ValueError('INVALID_PHASE_POWER_FACTOR')
    if any(not 0 <= v <= 1 for v in c['house_phase_shares']) or abs(sum(c['house_phase_shares'])-1)>1e-6:
        raise ValueError('INVALID_PHASE_SHARES')
    return c


def limits(volts, context=None):
    c = checked(context)
    return [(25-r)*u*pf for u,r,pf in zip(volts,c['reserve_a'],c['power_factor'])]


def estimate(samples, at):
    """Use only earlier night samples, no future-night information in a decision.

    Reserve = largest observed positive base-load current step + 0.1 A rounding.
    PF = minimum consistent P/(U*I) at >=5 A. Neither bounds unseen transients.
    """
    now=instant(at); cutoff=now-timedelta(days=7)
    ratios=[[],[],[]]; steps=[[],[],[]]; energy=[0.,0.,0.]; evidence=[]; previous=None
    for row in sorted(samples,key=lambda r:r['at']):
        t=instant(row['at'])
        if not cutoff<=t<=now:continue
        p=row.get('inputs',row.get('points',{}))
        def num(k):
            x=p.get(k,{})
            return x.get('value') if x.get('quality')=='valid' and valid(x.get('value')) and valid(x.get('age_seconds')) and 0<=x['age_seconds']<90 else None
        values=[]
        for i in (1,2,3):
            u,g,inv,ev,a=[num(k) for k in (f'grid_voltage_l{i}_v',f'grid_l{i}_w',f'inverter_l{i}_w',f'ev_l{i}_w',f'grid_l{i}_a')]
            if any(v is None for v in (u,g,inv,ev,a)) or not 180<u<260 or ev<0 or not 0<=abs(a)<=100:
                break
            base=inv-g-ev
            if base < -100:break
            ratio=abs(g)/(u*abs(a)) if abs(a)>=5 else None
            if ratio is not None and (abs(inv)>200 or not .5<=ratio<=1.05):ratio=None
            values.append((max(0.,base),u,ratio))
        if len(values)!=3:previous=None;continue
        for i,(base,u,pf) in enumerate(values):
            if pf is not None:ratios[i].append(min(1.,pf))
        if previous and 0<(t-previous[0]).total_seconds()<=30:
            dt=(t-previous[0]).total_seconds()
            for i,(base,u,pf) in enumerate(values):
                energy[i]+=previous[1][i][0]*dt
                steps[i].append(max(0.,base/u-previous[1][i][0]/previous[1][i][1]))
        evidence.append({'at':row['at'],'values':values})
        previous=(t,values)
    if min(map(len,ratios))<30 or min(map(len,steps))<60 or sum(energy)<=0:
        return {**fallback(),'available_at':at,'loaded_samples':[len(x) for x in ratios],
                'step_samples':[len(x) for x in steps],'source_hash':digest(evidence)}
    pf=[min(x) for x in ratios]
    reserve=[math.ceil((max(s)/f+.1)*10)/10 for s,f in zip(steps,pf)]
    if any(r>=25 for r in reserve):
        return {**fallback(),'status':'observed_steps_exceed_budget','reserve_a':reserve,'available_at':at,'source_hash':digest(evidence),'blocking':True}
    return checked({'policy':POLICY,'status':'empirical_shadow_candidate','breaker_a':25.,
        'reserve_a':reserve,'power_factor':pf,'house_phase_shares':[v/sum(energy) for v in energy],
        'available_at':at,'source_start':evidence[0]['at'],'source_end':evidence[-1]['at'],
        'source_hash':digest(evidence),'loaded_samples':[len(x) for x in ratios],
        'step_samples':[len(x) for x in steps], 'control_verified':False,
        'source':'prior_night_measured_envelope',
        'limitations':['sampling_can_miss_peaks','actuator_latency_unverified','future_phase_distribution_uncertain']})


def from_db(db, at):
    cutoff=(instant(at)-timedelta(days=7)).isoformat()
    rows=db.execute('SELECT payload FROM priority_samples WHERE at>=? AND at<=? ORDER BY at',(cutoff,at))
    return estimate((unpack(r[0]) for r in rows),at)
