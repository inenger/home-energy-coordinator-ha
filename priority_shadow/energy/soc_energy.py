"""Conserved DC discharge-energy state and explicit SOC calibration envelopes.

SOC is an observation coordinate, not a linear capacity measurement. The
central model assigns round-trip DC losses to charging; discharge removes
available DC energy directly. The envelope additionally prices the directional
SOC ambiguity. Neither model is a measured AC charging efficiency.
"""
from bisect import bisect_right
from .pricing import valid


def interpolate(points, x):
    if not valid(x) or len(points) < 2:
        raise ValueError('Invalid interpolation')
    i = min(len(points)-2, max(0, bisect_right([p[0] for p in points], x)-1))
    a, b = points[i:i+2]
    return a[1] + (x-a[0])/(b[0]-a[0])*(b[1]-a[1])


class Battery:
    def __init__(self, model, envelope=False, dc_efficiency=None):
        self.model = model
        self.energy = [tuple(p) for p in model['discharge_curve']]
        self.eta_dc = dc_efficiency or model['dc_cycle_efficiency']
        if not .5 <= self.eta_dc <= 1:
            raise ValueError('Invalid DC efficiency')
        if (len(self.energy) < 3 or any(not valid(x) or not valid(y) for x,y in self.energy)
                or any(b[0] <= a[0] or b[1] <= a[1] for a,b in zip(self.energy,self.energy[1:]))):
            raise ValueError('Energy/SOC curve must be strictly increasing')
        empirical = model.get('charge_curve') or []
        # Incremental construction guarantees d(available energy) <= eta*d(input)
        # on every segment, including where the empirical charge curve is flat.
        self.charge = [(self.energy[0][0], self.energy[0][1]/self.eta_dc)]
        for a,b in zip(self.energy,self.energy[1:]):
            required = (b[1]-a[1])/self.eta_dc
            if envelope and empirical:
                required = max(required, interpolate(empirical,b[0])-interpolate(empirical,a[0]))
            self.charge.append((b[0], self.charge[-1][1]+required))
        self.envelope = envelope

    def available(self, soc):
        return interpolate(self.energy, soc)

    def soc(self, available):
        return interpolate([(e,s) for s,e in self.energy], available)

    def dc_to_target(self, soc, target):
        return max(0., interpolate(self.charge,target)-interpolate(self.charge,soc))

    def charge_dc(self, soc, incoming, target=100):
        incoming = max(0., incoming)
        accepted = min(incoming, self.dc_to_target(soc,target))
        coordinate = interpolate(self.charge,soc)+accepted
        new = min(target, interpolate([(c,s) for s,c in self.charge],coordinate))
        stored = self.available(new)-self.available(soc)
        return new, accepted, max(0., accepted-stored)

    def discharge_dc(self, soc, requested, reserve_soc):
        available = max(0., self.available(soc)-self.available(reserve_soc))
        delivered = min(max(0.,requested), available)
        return self.soc(self.available(soc)-delivered), delivered

    def snapshot(self):
        return {'kind':'directional_soc_envelope' if self.envelope else 'dc_cycle_energy_model',
                'discharge_curve':[list(p) for p in self.energy],
                'charge_coordinate':[list(p) for p in self.charge],
                'dc_cycle_efficiency':self.eta_dc,
                'grid_charge_efficiency':self.model.get('grid_efficiency',.9),
                'grid_charge_efficiency_status':'unverified_legacy_assumption',
                'ac_discharge_efficiency':self.model.get('ac_discharge_efficiency',.977),
                'source_hash':self.model.get('source_hash'),
                'not_nameplate_capacity_or_soh':True}


def coordinate_remaining(snapshot, soc, target):
    return max(0.,interpolate(snapshot['charge_coordinate'],target)-interpolate(snapshot['charge_coordinate'],soc))


def advance_coordinate(snapshot, soc, ac_kwh, target):
    coordinate = snapshot['charge_coordinate']
    value = interpolate(coordinate,soc)+max(0.,ac_kwh)*snapshot['grid_charge_efficiency']
    return min(target,interpolate([(c,s) for s,c in coordinate],value))
