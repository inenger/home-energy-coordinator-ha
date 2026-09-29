"""Catalogue inputs and provisional energy/SOC evidence; not a degradation test."""
from statistics import median
from .core import instant, TZ
from .pricing import valid

SPEC={'model':'SolaX T-BAT H 11.5 (2× T58)','nominal_kwh':11.5,'usable_kwh':10.4,
      'roundtrip_efficiency':0.95,'dod':0.90,'cycle_life_reference':6000,
      'source_note':'SolaX T-BAT SYS-HV-5.8 technical data; not a measured system efficiency.'}


def analyze(rows,now):
    rows=sorted((r for r in rows if instant(r['at'])<=now),key=lambda r:instant(r['at']))
    candidates=[];start=None;prev=None;throughput=0.
    for r in rows:
        at=instant(r['at'])
        fields=('soc','input_today_kwh','output_today_kwh')
        if not all(valid(r.get(k)) for k in fields): start=None;prev=r;continue
        if prev and all(valid(prev.get(k)) for k in fields):
            same=at.astimezone(TZ).date()==instant(prev['at']).astimezone(TZ).date()
            elapsed=(at-instant(prev['at'])).total_seconds()
            ds=r['soc']-prev['soc'];di=r['input_today_kwh']-prev['input_today_kwh'];do=r['output_today_kwh']-prev['output_today_kwh']
            if same and 0<elapsed<=3*3600 and di>=0 and do>=0:
                # Explicitly observation-based; cumulative meters can bridge a sparse interval.
                if di<=10*elapsed/3600+.15 and do<=10*elapsed/3600+.15: throughput+=di+do
            else: start=None
        if start is None: start=r;prev=r;continue
        a=instant(start['at'])
        if at.astimezone(TZ).date()!=a.astimezone(TZ).date() or not 0<(at-a).total_seconds()<=12*3600:
            start=r;prev=r;continue
        ds=r['soc']-start['soc'];din=r['input_today_kwh']-start['input_today_kwh'];dout=r['output_today_kwh']-start['output_today_kwh']
        if din<0 or dout<0: start=r;prev=r;continue
        if abs(ds)>=15:
            energy=din if ds>0 and din>.3 and dout<=.15*din else dout if ds<0 and dout>.3 and din<=.15*dout else None
            if energy is not None:
                cap=energy/(abs(ds)/100)
                if 7<=cap<=13.5:
                    candidates.append({'start':start['at'],'end':r['at'],'direction':'charge' if ds>0 else 'discharge',
                        'soc_delta_pct':round(ds,1),'energy_kwh':round(energy,3),'capacity_estimate_kwh':round(cap,3)})
            start=r
        prev=r
    caps=[r['capacity_estimate_kwh'] for r in candidates[-30:]];effective=median(caps) if len(caps)>=3 else None
    return {'status':'ok' if rows else 'collecting','spec':SPEC,
        'effective_capacity_kwh':round(effective,3) if effective is not None else None,
        'observed_energy_per_soc100_kwh':round(effective,3) if effective is not None else None,
        'soh_pct':None,'soc_basis_verified':False,'energy_boundary_verified':False,
        'capacity_evidence_count':len(caps),'capacity_evidence':candidates[-10:],
        'observed_throughput_kwh':round(throughput,3),
        'equivalent_full_cycles_observed':round(throughput/(2*SPEC['usable_kwh']),3),
        'note':'Provisional energy/SOC ratio; no measured degradation, reserve changes or test cycles.'}
