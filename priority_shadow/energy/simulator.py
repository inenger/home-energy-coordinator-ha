"""Pure AC/DC ledger for OFFLINE tests. Not a household digital twin yet.

Grid currents use fixed voltage, unity power factor and balanced simulated
battery/EV. This is an explicitly simplified test model, NEVER a breaker guard.
Heating stays inside the common non-EV base load in this version.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import math

def finite_nonnegative(value):
    if not math.isfinite(value) or value < 0:
        raise ValueError('Expected finite nonnegative value')

@dataclass(frozen=True)
class Model:
    battery_capacity_kwh: float
    battery_reserve_kwh: float
    ev_capacity_kwh: float
    charge_efficiency: float
    discharge_efficiency: float
    ev_efficiency: float
    battery_charge_limit_kw: float = 5
    battery_discharge_limit_kw: float = 5
    ev_limit_kw: float = 11.04
    ev_min_kw: float = 4.14
    phase_limit_a: float = 25
    voltage_v: float = 230
    export_limit_kw: float = 10

    def __post_init__(self):
        for value in self.__dict__.values(): finite_nonnegative(value)
        if not (0 < self.battery_capacity_kwh and 0 < self.ev_capacity_kwh and 0 < self.voltage_v):
            raise ValueError('Capacities and voltage must be positive')
        if self.battery_reserve_kwh > self.battery_capacity_kwh:
            raise ValueError('Reserve exceeds capacity')
        if not all(0 < v <= 1 for v in (self.charge_efficiency,self.discharge_efficiency,self.ev_efficiency)):
            raise ValueError('Invalid efficiency')
        if self.ev_min_kw > self.ev_limit_kw:
            raise ValueError('EV minimum exceeds maximum')

@dataclass(frozen=True)
class State:
    battery_kwh: float
    ev_kwh: float

def residual_non_ev(house_kw, measured_ev_kw):
    finite_nonnegative(house_kw); finite_nonnegative(measured_ev_kw)
    if measured_ev_kw > house_kw + .05:
        raise ValueError('EV exceeds house power: alignment/mapping needs review')
    return max(0, house_kw-measured_ev_kw)

def step(state, model, *, hours, base_phase_kw, pv_ac_phase_kw,
         requested_battery_kw=0., requested_ev_kw=0., ev_connected=True,
         buy_price=0., sell_price=0., priority=('ev','battery')):
    if len(base_phase_kw)!=3 or len(pv_ac_phase_kw)!=3 or set(priority)!={'ev','battery'} or len(priority)!=2:
        raise ValueError('Three phases and exactly two priorities required')
    for v in (*base_phase_kw,*pv_ac_phase_kw,state.battery_kwh,state.ev_kwh): finite_nonnegative(v)
    if not math.isfinite(hours) or not 0<hours<=1:
        raise ValueError('Step must be between 0 and 1 hour')
    if not all(math.isfinite(v) for v in (requested_battery_kw,requested_ev_kw,buy_price,sell_price)):
        raise ValueError('Invalid action or price')
    if requested_ev_kw<0: raise ValueError('V2H is not supported')
    if not 0<=state.battery_kwh<=model.battery_capacity_kwh or not 0<=state.ev_kwh<=model.ev_capacity_kwh:
        raise ValueError('Invalid starting energy')
    net=[a-b for a,b in zip(base_phase_kw,pv_ac_phase_kw)]
    phase_cap=model.phase_limit_a*model.voltage_v/1000
    flags=[]
    if any(n>phase_cap for n in net): flags.append('BASE_LOAD_ALREADY_EXCEEDS_IMPORT_LIMIT')
    charge=min(max(requested_battery_kw,0), model.battery_charge_limit_kw,
               (model.battery_capacity_kwh-state.battery_kwh)/model.charge_efficiency/hours)
    discharge=min(max(-requested_battery_kw,0), model.battery_discharge_limit_kw,
                  max(0,state.battery_kwh-model.battery_reserve_kwh)*model.discharge_efficiency/hours)
    ev=min(requested_ev_kw,model.ev_limit_kw,(model.ev_capacity_kwh-state.ev_kwh)/model.ev_efficiency/hours) if ev_connected else 0
    if requested_ev_kw and not ev_connected: flags.append('EV_DISCONNECTED')
    requests={'battery':charge,'ev':ev}; allocation={}
    for device in priority:
        headroom=max(0,min(phase_cap-n for n in net)*3)
        actual=min(requests[device],headroom)
        if device=='ev' and 0<actual<model.ev_min_kw:
            actual=0; flags.append('EV_BELOW_MINIMUM_POWER')
        allocation[device]=actual
        net=[n+actual/3 for n in net]
        if actual+1e-9<requests[device]: flags.append(device.upper()+'_POWER_LIMITED')
    charge,ev=allocation['battery'],allocation['ev']
    discharge=min(discharge,max(0,sum(net)+model.export_limit_kw))
    discharge=min(discharge,max(0,min(n+phase_cap for n in net)*3))
    net=[n-discharge/3 for n in net]
    curtail=0.
    for i,n in enumerate(net):
        if n < -phase_cap:
            cut=min(pv_ac_phase_kw[i],-phase_cap-n)
            net[i]+=cut; curtail+=cut
    excess=max(0,-sum(net)-model.export_limit_kw)
    pv_remaining=sum(pv_ac_phase_kw)-curtail
    cut=min(excess,max(0,pv_remaining))
    if cut:
        negative=sum(max(-n,0) for n in net)
        net=[n+cut*max(-n,0)/negative for n in net]; curtail+=cut
    new=State(state.battery_kwh+charge*hours*model.charge_efficiency-discharge*hours/model.discharge_efficiency,
              state.ev_kwh+ev*hours*model.ev_efficiency)
    imports=max(sum(net),0)*hours; exports=max(-sum(net),0)*hours
    balance=sum(base_phase_kw)+charge+ev-(sum(pv_ac_phase_kw)-curtail)-discharge-sum(net)
    return new,{'hours':hours,'battery_ac_charge_kw':charge,'battery_ac_discharge_kw':discharge,
                'ev_ac_kw':ev,'grid_import_kwh':imports,'grid_export_kwh':exports,
                'phase_import_a':[max(n,0)*1000/model.voltage_v for n in net],
                'curtailment_kwh':curtail*hours,'energy_balance_error_kw':balance,
                'battery_loss_kwh':charge*hours*(1-model.charge_efficiency)+discharge*hours*(1/model.discharge_efficiency-1),
                'ev_loss_kwh':ev*hours*(1-model.ev_efficiency),
                'electricity_cost_czk':imports*buy_price-exports*sell_price,'flags':flags}

def trip(state,kwh):
    finite_nonnegative(kwh)
    return replace(state,ev_kwh=max(0,state.ev_kwh-kwh)),max(0,kwh-state.ev_kwh)

def compare_terminal(first,second,tolerance=.001):
    equal=(abs(first.battery_kwh-second.battery_kwh)<=tolerance and abs(first.ev_kwh-second.ev_kwh)<=tolerance)
    return {'terminal_comparable':equal,'battery_difference_kwh':second.battery_kwh-first.battery_kwh,
            'ev_difference_kwh':second.ev_kwh-first.ev_kwh}

def demo():
    model=Model(10,2,60,.95,.95,.9)
    initial=State(5,20)
    outputs={}
    for name,charge_hours in [('synthetic_evening_baseline',(18,19)),('synthetic_cheap_window',(3,4))]:
        state=initial; cost=0.; ledgers=[]
        for h in range(24):
            state,row=step(state,model,hours=1,base_phase_kw=(.3,.3,.3),pv_ac_phase_kw=(0,0,0),
                           requested_ev_kw=4.14 if h in charge_hours else 0,buy_price=1.8 if h in (3,4) else 4.7)
            cost+=row['electricity_cost_czk']; ledgers.append({'hour':h,**row})
        outputs[name]={'cost_czk':round(cost,4),'terminal':state.__dict__,'steps':ledgers}
    terminals=[State(**v['terminal']) for v in outputs.values()]
    return {'kind':'SYNTHETIC_SOFTWARE_TEST_NOT_HOUSEHOLD_RESULT','real_household_savings_czk':None,
            'comparison':compare_terminal(*terminals),'runs':outputs}
