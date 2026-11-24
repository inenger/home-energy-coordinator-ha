"""0.7.0 pilot: explicit one-shot test only; the nightly controller stays virtual."""
import argparse
from datetime import datetime, timezone, timedelta
import json, os, time, uuid
from pathlib import Path
import urllib.request
from .collector import NoRedirect, read_token, DATA
from .core import instant
from .ram_control import peak_window_errors, validate_intent

MAPPING = 'mode8-a6-duration-a7-next-motion-candidate-v1'
SERVICE = '/api/services/solax_modbus/hec_mode8_pilot?return_response'
READBACK = 'sensor.solax_inverter_solax_remotecontrol_readback_mode'
TARGET = 'sensor.solax_inverter_solax_remotecontrol_mode_8_battery_power_target_readback'
DURATION = 'sensor.solax_inverter_solax_remotecontrol_mode_8_timeout_readback'
NEXT_MOTION = 'sensor.solax_inverter_solax_remotecontrol_mode_8_next_motion_readback'
MEASUREMENTS = (READBACK, TARGET, DURATION, NEXT_MOTION, 'sensor.solax_battery_power_charge',
                'sensor.solax_battery_voltage_charge', 'sensor.solax_battery_current_charge',
                'sensor.solax_battery_capacity', 'sensor.solax_api_charge_power_total',
                'sensor.solax_pv_power_total', 'sensor.solax_inverter_communication_health',
                'sensor.solax_run_mode', 'select.solax_charger_use_mode',
                'sensor.solax_inverter_solax_software_version','sensor.solax_api_charging_status',
                'select.solax_api_charger_use_mode','binary_sensor.tesla_model_y_juniper_nabijeci_kabel',
                *('sensor.solax_measured_power_l'+str(i) for i in (1,2,3)),
                *('sensor.solax_inverter_solax_grid_current_l'+str(i) for i in (1,2,3)))

def preview(journal, at, mode='observe_only'):
    """Private RAM intent only, never a published HA setpoint and never a write."""
    out={'pilot_mode':mode,'status':'disabled' if mode=='observe_only' else 'operator_test_only',
         'automatic_actuation':False,'physical_control_ready':False,
         'requested_ac_w':None,'wire_command':None,'device_actions':0,
         'blocking_reasons':['mapping_review_required','hardware_timeout_unverified',
                             'ac_dc_boundary_unverified','exclusive_ownership_unverified']}
    run=(journal or {}).get('session') or {}
    candidate=run.get('last_intent')
    try:
        intent=validate_intent(candidate)
        if run.get('status')!='active' or run.get('suspended') or run.get('good_frames',0)<2:
            return out
        if not instant(intent['at'])<=instant(at)<instant(intent['expires_at']):
            return out
        sample=next(iter(journal.get('recent_samples',[])),{})
        if sample.get('at')!=at or sample.get('input_errors') or peak_window_errors(sample.get('phase_peak_window')):
            return out
        if intent['logical_battery_ac_w']!=run.get('target_ac_w'):
            return out
        out['requested_ac_w']=intent['logical_battery_ac_w']
        out['expires_at']=intent['expires_at']
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        pass
    return out

class PilotHA:
    """Fixed supervisor origin and service; no arbitrary register or service API."""
    def __init__(self):
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def _request(self,path,method='GET',body=None):
        token=read_token()
        req=urllib.request.Request('http://supervisor/core'+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
        with self.opener.open(req,timeout=8) as r:
            data=r.read(2*1024*1024+1)
        if len(data)>2*1024*1024:raise ValueError('response_too_large')
        return json.loads(data)
    def snapshot(self):
        return {eid:self._request('/api/states/'+eid) for eid in MEASUREMENTS}
    def send(self,request):
        return self._request(SERVICE,'POST',request)

def request_for(approval, now):
    """No defaults, no unbounded duration and no arbitrary register values."""
    if set(approval)!= {'request_id','hub_name','mapping','charge_dc_w','duration_s','expires_at','operator_confirmed','ev_disconnected_confirmed'}:
        raise ValueError('invalid approval fields')
    if approval['operator_confirmed'] is not True or approval['ev_disconnected_confirmed'] is not True or approval['mapping']!=MAPPING:
        raise ValueError('explicit mapping review and operator approval required')
    if str(uuid.UUID(approval['request_id']))!=approval['request_id']:
        raise ValueError('invalid request id')
    if not isinstance(approval['hub_name'],str) or not approval['hub_name']:
        raise ValueError('invalid hub')
    if type(approval['charge_dc_w']) is not int or approval['charge_dc_w'] not in (100,200,300):
        raise ValueError('pilot power outside 100/200/300W DC')
    if type(approval['duration_s']) is not int or approval['duration_s']!=10:
        raise ValueError('pilot duration must be 10s')
    expires=instant(approval['expires_at'])
    if not 0<(expires-now).total_seconds()<=60:
        raise ValueError('approval expired or too long')
    return {**approval,'send_before':min(expires,now+timedelta(seconds=5)).isoformat()}

def load_private(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:raise ValueError('approval must be private')
    return json.loads(path.read_text())

def pilot(options, approval_path, audit_dir, client, clock=lambda:datetime.now(timezone.utc), sleep=time.sleep):
    """Explicit invocation. Persist pre-send evidence; never retry uncertain requests."""
    if options.get('mode')!='live_test':raise ValueError('live_test required')
    approval=load_private(approval_path)
    request_for(approval,clock())
    audit_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=audit_dir/(approval['request_id']+'.jsonl')
    with path.open('x',encoding='utf-8') as f:
        os.fchmod(f.fileno(),0o600)
        def log(kind,**fields):
            f.write(json.dumps({'kind':kind,'at':clock().isoformat(),**fields},ensure_ascii=False)+'\n')
            f.flush();os.fsync(f.fileno())
        log('operator_approved',approval=approval)
        before=client.snapshot()
        log('before',states=before)
        request=request_for(approval,clock())
        log('dispatch_requested',request=request)
        try:
            response=client.send(request)
            log('ha_service_response',response=response)
        except Exception as error:
            log('dispatch_uncertain',error_code=type(error).__name__)
            # A failed HTTP response is not evidence of a failed device write.
            response=None
        # No re-send and no automatic disable during timeout qualification.
        # Operator remains at installation and uses independent recovery if needed.
        for _ in range(21):
            try:log('readback',states=client.snapshot())
            except Exception as error:log('readback_unavailable',error_code=type(error).__name__)
            sleep(1)
        log('operator_review_required',automatic_retry=False,physical_control_ready=False)
    return path

def main():
    parser=argparse.ArgumentParser(description='Manual supervised Mode 8 single-shot pilot; no automated renewal')
    parser.add_argument('--confirm',required=True,choices=['OPERATOR_PRESENT_MAPPING_REVIEWED_EV_DISCONNECTED'])
    args=parser.parse_args()
    options=json.loads(Path('/data/options.json').read_text())
    path=pilot(options,DATA/'live-test-approval.json',DATA/'live-test-audit',PilotHA())
    print(path)

if __name__=='__main__':main()
