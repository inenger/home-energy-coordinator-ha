"""Authoritative wallbox observations; Tesla/Tessie never determines activity.

HA report freshness is not a physical heartbeat. Unknown power/status remains
unknown; a stopped power reading alone does not prove cable disconnection.
"""
from .core import instant

STATUS_ID='sensor.solax_api_charging_status'
POWER_ID='sensor.solax_api_charge_power_total'
MAX_AGE_S=15
CONNECTED={'Preparing','Charging','Finishing','Suspended EV','Suspended EVSE','RFID Activation'}

def fresh(point):
    age=point.get('age_seconds')
    return point.get('quality')in('valid','text') and isinstance(age,(int,float)) and 0<=age<MAX_AGE_S

def observation(points):
    power=points.get('ev_w',{});status=points.get('ev_state',{})
    watts=power.get('value')if fresh(power)and power.get('quality')=='valid'else None
    label=status.get('value')if fresh(status)else None
    connected=None;activity='unknown';used=[]
    if isinstance(watts,(int,float))and watts>0:
        connected='on';activity='charging';used=[power]
    elif label in CONNECTED:
        connected='on';used=[status]
        if watts==0:activity='transition'if label=='Charging'else'connected_idle'
    elif label=='Available'and watts==0:
        connected='off';activity='disconnected';used=[power,status]
    stamps=[x.get('last_reported')for x in used]
    report=min(stamps,key=instant)if stamps and all(stamps)else None
    age=max([x['age_seconds']for x in used],default=None)
    return {'connected':connected,'activity':activity,'charging':watts>0 if isinstance(watts,(int,float))and watts>=0 else None,'power_reported_at':power.get('last_reported')if fresh(power)else None,'power_w':watts,'wallbox_status':label,
            'entity_id':STATUS_ID,'power_entity_id':POWER_ID,'last_reported':report,
            'age_seconds':age,'report_source':'wallbox_observations_only',
            'tessie_role':'SOC_and_planning_supplement_only',
            'physical_heartbeat_verified':False}

def connection_point(points):
    obs=observation(points)
    return {'value':obs['connected'],'quality':'text'if obs['connected']is not None else'unknown',
            'age_seconds':obs['age_seconds'],'last_reported':obs['last_reported'],
            'entity_id':STATUS_ID,'unit':None,'report_source':obs['report_source'],
            'activity':obs['activity'],'source_details':obs}
