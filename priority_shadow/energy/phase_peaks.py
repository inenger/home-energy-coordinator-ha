"""Bounded read-only high-water cache for grid phase current between control steps.

Only fresh, distinct HA last_reported observations are eligible. This is
not a subsecond meter, breaker protection, or proof of physical atomicity.
"""
from datetime import datetime, timezone
import math
from .core import instant
from . import night

BREAKER_A=25.0
LOOKBACK_S=8.0
MAX_REPORT_AGE_S=3.5
PHASES=(1,2,3)


class PhasePeakWindow:
    def __init__(self):
        self.frames=[]
        self.last_report={}
        self.poll_count=0

    def reset(self):
        self.frames=[]
        self.last_report={}
        self.poll_count=0

    def observe(self, states, at, mono):
        """Invoked only after a successful collection; no disk or device I/O."""
        by={s.get('entity_id'):s for s in states}
        report={}
        for i in PHASES:
            eid=night.IDS[f'grid_l{i}_a']
            state=by.get(eid)
            if not state or state.get('snapshot_error'):
                continue
            if state.get('attributes',{}).get('unit_of_measurement')!='A':
                continue
            p=night.point(state,at)
            if p['quality']!='valid' or p['age_seconds'] is None or not 0<=p['age_seconds']<=MAX_REPORT_AGE_S:
                continue
            amps=p['value']
            if not isinstance(amps,(int,float)) or not math.isfinite(amps) or abs(amps)>100:
                continue
            timestamp=p.get('last_reported')
            try:
                report_time=instant(timestamp)
                if i in self.last_report and report_time<=self.last_report[i]:
                    continue
            except (ValueError,TypeError,AttributeError):
                continue
            report[i]={'a':round(abs(amps),4),'at':timestamp,'entity_id':eid}
            self.last_report[i]=report_time
        self.frames.append((mono,report))
        self.poll_count+=1
        self._prune(mono)

    def _prune(self, now):
        self.frames=[(at,r)for at,r in self.frames if 0<=now-at<=LOOKBACK_S]
        # Hard bound in addition to time bound (synthetic accelerated clocks).
        if len(self.frames)>32:self.frames=self.frames[-32:]

    def snapshot(self,now):
        self._prune(now)
        maxima={}
        counts={f'L{i}':0 for i in PHASES}
        for _,readings in self.frames:
            for i,row in readings.items():
                phase=f'L{i}'
                counts[phase]+=1
                if phase not in maxima or row['a']>maxima[phase]['a']:
                    maxima[phase]=dict(row)
        missing=[f'L{i}' for i in PHASES if f'L{i}' not in maxima]
        return {'status':'unverified' if missing else 'ok',
                'breaker_a':BREAKER_A,
                'lookback_s':LOOKBACK_S,
                'collector_frames':len(self.frames),
                'phase_report_counts':counts,
                'maxima':maxima,
                'unverified_phases':missing,
                'over_limit_phases':[i for i,x in maxima.items() if x['a']>BREAKER_A],
                'basis':'distinct_fresh_HA_last_reported_not_physical_peak_protection'}
