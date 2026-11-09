"""Historical EV-transition attribution; never a live control allowance.

A cross-source transition cannot prove a short house pulse. Such intervals are
reported as unresolved, not zero-load measurements or verified safety margins.
Only settled endpoint changes enter the learned reserve; independent house
steps outside EV transitions keep their original magnitude.
"""
from bisect import bisect_left,bisect_right
from .core import instant

SETTLE_S=15

def steps(frames):
    times=[instant(f['at']).timestamp()for f in frames]
    result=[[],[],[]];unresolved=[0]*3;adjusted=[0]*3;pending=[0]*3
    for phase in range(3):
        changes=[]
        for n in range(1,len(frames)):
            a,b=frames[n-1],frames[n]
            if frames[n].get('segment')!=frames[n-1].get('segment') or not 0<times[n]-times[n-1]<=30:continue
            ea,eb=a['ev'][phase],b['ev'][phase]
            if abs(eb-ea)>max(100.,.03*max(ea,eb)):
                changes.append(times[n])
        clusters=[]
        for t in changes:
            if clusters and t-clusters[-1][1]<=2*SETTLE_S:clusters[-1][1]=t
            else:clusters.append([t,t])
        starts=[a for a,b in clusters];ends=[b for a,b in clusters]
        for n in range(1,len(frames)):
            if frames[n].get('segment')!=frames[n-1].get('segment') or not 0<times[n]-times[n-1]<=30:continue
            before,after=frames[n-1]['values'][phase],frames[n]['values'][phase]
            raw=max(0.,after[0]/after[1]-before[0]/before[1])
            lo=bisect_left(ends,times[n-1]-SETTLE_S)
            if lo<len(clusters)and starts[lo]<=times[n]+SETTLE_S:
                first,last=clusters[lo];a=bisect_right(times,first-SETTLE_S)-1;b=bisect_left(times,last+SETTLE_S)
                if a<0 or b>=len(frames):pending[phase]+=1;continue
                if any(frames[k].get('segment')!=frames[k-1].get('segment') or not 0<times[k]-times[k-1]<=30 for k in range(a+1,b+1)):
                    unresolved[phase]+=1;continue
                x,y=frames[a]['values'][phase],frames[b]['values'][phase]
                raw=max(0.,y[0]/y[1]-x[0]/x[1]);adjusted[phase]+=1
                # No claim that a real short pulse inside the transition was absent.
                unresolved[phase]+=1
            result[phase].append(raw)
    return result,{'policy':'wallbox-transition-settlement-v1','settlement_s':SETTLE_S,
                   'adjusted_step_pairs':adjusted,'unresolved_transition_pairs':unresolved,
                   'pending_step_pairs':pending,'unknown_pulses_not_proven_absent':True}
