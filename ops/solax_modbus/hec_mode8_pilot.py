"""Candidate HA-side one-shot Mode 8 qualification service for SolaX 2026.11.04.

Not installed automatically. No automatic renewal, arbitrary register writes,
or normal operation. Requires private, short-lived, operator-approved arming.
"""
import asyncio
from datetime import datetime, timezone
import json
import math
import os
import time
from importlib.metadata import version
from pathlib import Path
import uuid

MAPPING = 'mode8-a6-wait-timeout-a7-next-motion-v00100-candidate-v3'
ARM_FILE = Path('/config/.hec-mode8-pilot-approval.json')
PHASES = tuple('sensor.solax_inverter_solax_grid_current_l'+str(i) for i in (1,2,3))
MODE = 'sensor.solax_inverter_solax_remotecontrol_readback_mode'
REMOTE = 'sensor.solax_modbus_power_control'
REPEAT = 'sensor.solax_remotecontrol_autorepeat_remaining'
POWER = 'sensor.solax_battery_power_charge'
PV = 'sensor.solax_pv_power_total'
EV = 'sensor.solax_api_charge_power_total'
EV_MODE = 'select.solax_api_charger_use_mode'
EV_STATUS = 'sensor.solax_api_charging_status'
EV_CABLE = 'binary_sensor.tesla_model_y_juniper_nabijeci_kabel'
SOC = 'sensor.solax_battery_capacity'
HEALTH = 'sensor.solax_inverter_communication_health'
RUN = 'sensor.solax_run_mode'
WORK = 'select.solax_charger_use_mode'
PARALLEL = 'select.solax_parallel_setting'
BREAKER = 'number.solax_main_breaker_current_limit'
FIRMWARE = 'sensor.solax_inverter_solax_software_version'
HARDWARE = 'sensor.solax_inverter_solax_hardware_version'
QUALIFICATION_FIRMWARE = 'DSP 1.62 ARM 1.60-1.09'
PROTOCOL = 'sensor.solax_inverter_solax_modbus_protocol_version'
QUALIFICATION_PROTOCOL = 100
# A documented candidate is not proof for this firmware. Do not arm real HA service
# until the manufacturer-confirmed mapping/recovery and separate hardware review.
HARDWARE_DISPATCH_QUALIFIED = False
PILOT_PV_LIMIT_W = 15000  # fixed candidate; no PV curtailment intended

def utcnow():
    return datetime.now(timezone.utc)

def timestamp(value):
    out=datetime.fromisoformat(value)
    if out.tzinfo is None:raise ValueError('timezone required')
    return out

def validate_request(request, approved, now):
    fields={'request_id','hub_name','mapping','charge_dc_w','wait_timeout_s','expires_at','operator_confirmed','ev_disconnected_confirmed'}
    if set(approved)!=fields or set(request)!=fields|{'send_before'}:
        raise ValueError('wrong request fields')
    if any(request[k]!=approved[k] for k in fields):
        raise ValueError('request does not match local approval')
    if approved['operator_confirmed'] is not True or approved['ev_disconnected_confirmed'] is not True or approved['mapping']!=MAPPING:
        raise ValueError('mapping review and local operator confirmation required')
    if str(uuid.UUID(approved['request_id']))!=approved['request_id']:
        raise ValueError('invalid request id')
    if not isinstance(approved['hub_name'],str) or not approved['hub_name']:
        raise ValueError('invalid hub')
    if type(approved['charge_dc_w']) is not int or approved['charge_dc_w'] not in (100,200,300):
        raise ValueError('invalid pilot power')
    if type(approved['wait_timeout_s']) is not int or approved['wait_timeout_s']!=10:
        raise ValueError('invalid pilot wait timeout')
    remaining=(timestamp(request['send_before'])-now).total_seconds()
    approval_remaining=(timestamp(approved['expires_at'])-now).total_seconds()
    if not 0<remaining<=5 or not remaining<=approval_remaining<=60:
        raise ValueError('expired or overlong request')
    return remaining

def candidate_payload(charge_dc_w):
    """Complete, typed FC16 block A0..A7; candidate protocol, not HW proof."""
    if type(charge_dc_w) is not int or charge_dc_w not in (100,200,300):
        raise ValueError('invalid pilot power')
    return [('_uint16',8),('_uint16',1),('_uint32',PILOT_PV_LIMIT_W),
            ('_int32',-charge_dc_w),('_uint16',10),('_uint16',0xA0)]

def expected_words(charge_dc_w):
    """Independent V001.00 LSW-first encoding contract, not device qualification."""
    candidate_payload(charge_dc_w)
    unsigned = (-charge_dc_w) & 0xffffffff
    return [8,1,PILOT_PV_LIMIT_W & 0xffff,PILOT_PV_LIMIT_W >> 16,
            unsigned & 0xffff,unsigned >> 16,10,0xA0]

def check_states(get_state, now):
    def state(eid, max_age=None):
        s=get_state(eid)
        if s is None or s.state in ('unknown','unavailable',''):
            raise ValueError('missing state: '+eid)
        if max_age is not None:
            t=getattr(s,'last_reported',None)
            if t is None or not 0<=(now-t).total_seconds()<=max_age:
                raise ValueError('stale state: '+eid)
        return s
    def number(eid,unit,lo,hi,max_age=None):
        s=state(eid,max_age)
        if s.attributes.get('unit_of_measurement')!=unit:
            raise ValueError('wrong unit: '+eid)
        v=float(s.state)
        if not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError('unsafe value: '+eid)
        return v
    for eid in PHASES:number(eid,'A',-18,18,3)
    phase_times=tuple(state(eid,3).last_reported for eid in PHASES)
    if (max(phase_times)-min(phase_times)).total_seconds()>2:raise ValueError('incoherent phase reports')
    if state(FIRMWARE).state!=QUALIFICATION_FIRMWARE or state(HARDWARE).state!='Gen4':
        raise ValueError('different firmware or hardware; mapping review required')
    if state(PROTOCOL).state!=str(QUALIFICATION_PROTOCOL):
        raise ValueError('different or unverified Modbus document version')
    number(BREAKER,'A',25,25)
    # These stable HA states are cross-checks only; read inverter registers live below.
    number(SOC,'%',15,90)
    number(POWER,'W',-100,100)
    number(PV,'W',0,1000,3)
    # EV physically unplugged is an explicit operator condition. Stale wallbox idle
    # values are only a cross-check, not proof of unplugging.
    number(EV,'W',0,100)
    if state(EV_MODE).state!='Stop' or state(EV_STATUS).state!='Available' or state(EV_CABLE).state!='off':
        raise ValueError('EV not confirmed idle/disconnected')
    number(REPEAT,'s',0,0)
    if state(HEALTH,15).state!='Healthy':raise ValueError('Modbus not healthy')
    if state(RUN).state!='Normal Mode':raise ValueError('inverter not normal')
    if state(WORK).state!='Back Up Mode':raise ValueError('unexpected work mode')
    if state(PARALLEL).state!='Free':raise ValueError('parallel operation not qualified')
    if state(REMOTE).state!='Disabled' or state(MODE).state!='Disabled':
        raise ValueError('another VPP owner or unverified mode')
    return phase_times

def read_approval(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('approval file must be private')
    return json.loads(path.read_text())

def registers(response, count):
    if response is None or response.isError():raise ValueError('Modbus read failed')
    values=list(response.registers)
    if len(values)!=count or any(type(x) is not int or not 0<=x<=65535 for x in values):
        raise ValueError('invalid register response')
    return values

def signed16(value):return value-65536 if value>=32768 else value

async def physical_preflight(hub):
    # Stable HA states can be hours old despite healthy polling. Never fake
    # freshness; read the pinned Gen4 register mapping from the actual hub.
    unit=hub._modbus_addr
    if registers(await hub.async_read_holding_registers(unit=unit,address=0x82,count=1),1)!=[QUALIFICATION_PROTOCOL]:
        raise ValueError('physical Modbus protocol version mismatch')
    response=await hub.async_read_input_registers(unit=unit,address=0x09,count=20)
    v=registers(response,20)
    if v[0]!=2 or not 1000<=signed16(v[0x14-0x09])<=5000 or abs(signed16(v[0x16-0x09]))>100 or not 15<=v[0x1C-0x09]<=90:
        raise ValueError('physical inverter or battery state not eligible')
    if registers(await hub.async_read_holding_registers(unit=unit,address=0x1F,count=1),1)!=[2]:
        raise ValueError('physical work mode is not Back Up Mode')
    if registers(await hub.async_read_input_registers(unit=unit,address=0x100,count=1),1)!=[0]:
        raise ValueError('physical VPP mode is not confirmed disabled')
    if registers(await hub.async_read_holding_registers(unit=unit,address=0x1A0,count=1),1)!=[0]:
        raise ValueError('physical Mode8 readback not confirmed disabled')

async def single_frame_write(unit, values, guard, *, disable=False):
    """Pinned shared TCP transport; one FC16, no retry/reconnect or policy mutation.

    Private upstream APIs are deliberately version-gated. Unknown transports fail
    closed. Keep the Core pacer and smart transport lock, but bypass the smart
    retry loop for this one PDU. The caller supplies the final pre-send guard.
    A failed/cancelled response is still an unknown physical outcome.
    """
    from modbus_connection.tmodbus import ModbusConnection, TmodbusUnit
    from tmodbus.transport import AsyncSmartTransport, AsyncTcpTransport
    from tmodbus.pdu import WriteMultipleRegistersPDU

    if (version('modbus-connection'), version('tmodbus')) != ('4.12.8', '1.1.0'):
        raise ValueError('unreviewed Modbus dependency versions')
    if type(unit) is not TmodbusUnit or type(unit._conn) is not ModbusConnection:
        raise ValueError('unreviewed Core Modbus unit')
    if (disable and values != [0]) or (not disable and values not in [expected_words(w) for w in (100,200,300)]):
        raise ValueError('unexpected pilot payload')
    conn=unit._conn
    unit_id=unit._unit_id
    if type(unit_id) is not int or not 1<=unit_id<=247:
        raise ValueError('invalid unicast unit')
    pdu=WriteMultipleRegistersPDU(0xA0,values)
    async with conn._pacer.paced(unit_id):
        if conn._closed or not conn.connected:
            raise ValueError('Core connection unavailable')
        client=unit._client
        smart=client.transport
        if (type(smart) is not AsyncSmartTransport or smart.auto_reconnect
                or type(smart.base_transport) is not AsyncTcpTransport):
            raise ValueError('unreviewed Core TCP transport')
        async with smart._communication_lock:
            if smart._last_request_finished_at is not None:
                gap=smart.wait_between_requests-(time.monotonic()-smart._last_request_finished_at)
                if gap>0:await asyncio.sleep(gap)
            base=smart.base_transport
            if (conn._closed or not conn.connected or unit._client is not client
                    or smart._must_reconnect or not base.is_open()):
                raise ValueError('Core TCP connection changed or unavailable')
            # All pacing waits and locks are complete. No retry loop, reconnect
            # or scheduling point between the guard and TCP protocol send.
            guard()
            try:
                count=await base.send_and_receive(unit_id,pdu)
                if count!=len(values):
                    raise ValueError('unexpected FC16 response count')
            finally:
                smart._last_request_finished_at=time.monotonic()


async def one_shot(hub, request, approved, get_state, consume, clock=utcnow, pause=asyncio.sleep):
    """Shared hub locks, one version-pinned TCP frame, no automatic retry.
    Physical expiry and recovery remain HW qualification items.
    """
    remaining=validate_request(request,approved,clock())
    first=check_states(get_state,clock())
    async with asyncio.timeout(remaining):
        # A second genuinely new phase frame is required; no polling while holding the hub lock.
        while True:
            await pause(.25)
            validate_request(request,approved,clock())
            second=check_states(get_state,clock())
            if all(b>a for a,b in zip(first,second)):break
        async with hub._poll_data_lock:
            if getattr(hub,'_stopping',True):raise ValueError('hub stopping')
            repeat=hub.data.get('_repeatUntil')
            if not isinstance(repeat,dict) or any(x!=0 for x in repeat.values()):
                raise ValueError('repeat or post-action pending')
            await physical_preflight(hub)
            # No parallel TCP client, no ordinary write queue, no wrapper that retries writes.
            transport=hub._core_recovery_transport()
            if transport is None:raise ValueError('Core transport not available')
            values=hub._encode_multi_write_payload(candidate_payload(request['charge_dc_w']))
            if values!=expected_words(request['charge_dc_w']):
                raise ValueError('wire words differ from documented LSW-first candidate')
            async with hub._lock:
                async with transport._request_lock:
                    if not transport.is_connected() or transport.backoff_remaining:
                        raise ValueError('transport disconnected or in backoff')
                    if any(x!=0 for x in hub.data.get('_repeatUntil',{'missing':1}).values()):
                        raise ValueError('repeat state changed')
                    validate_request(request,approved,clock())
                    check_states(get_state,clock())
                    await consume()
                    validate_request(request,approved,clock())
                    check_states(get_state,clock())
                    if getattr(hub,'_stopping',True):raise ValueError('hub stopping')
                    # A response failure is ambiguous; never try the write again.
                    client=transport._unit(hub._modbus_addr)
                    def final_guard():
                        validate_request(request,approved,clock())
                        check_states(get_state,clock())
                        if (getattr(hub,'_stopping',True) or not transport.is_connected()
                                or transport.backoff_remaining
                                or any(x!=0 for x in hub.data.get('_repeatUntil',{'missing':1}).values())):
                            raise ValueError('hub stopped, disconnected or repeat state changed')
                    await single_frame_write(client,values,final_guard)
    return {'request_id':request['request_id'],'status':'modbus_call_returned',
            'address':0xA0,'register_count':8,'requested_dc_w':request['charge_dc_w'],
            'automatic_retry':False,'physical_response_verified':False}

def validate_stop(request, used, now):
    fields={'request_id','hub_name','send_before','operator_confirmed'}
    if set(request) not in (fields,fields|{'mode6_recovery_confirmed'}):
        raise ValueError('wrong stop fields')
    if 'mode6_recovery_confirmed' in request and request['mode6_recovery_confirmed'] is not True:
        raise ValueError('explicit Mode6 recovery confirmation required')
    if (request['operator_confirmed'] is not True
            or request['request_id']!=used['request_id']
            or request['hub_name']!=used['hub_name']
            or used['mapping']!=MAPPING
            or used['operator_confirmed'] is not True
            or used['ev_disconnected_confirmed'] is not True
            or str(uuid.UUID(request['request_id']))!=request['request_id']):
        raise ValueError('stop requires matching consumed pilot approval')
    expected_words(used['charge_dc_w'])
    expiry=timestamp(used['expires_at'])
    remaining=(timestamp(request['send_before'])-now).total_seconds()
    # Bound ownership to the immediate supervised pilot session. No takeover
    # of a later command, including a different user's identical setpoint.
    if not -60<=(now-expiry).total_seconds()<=120 or not 0<remaining<=5:
        raise ValueError('expired stop/session')
    return remaining

async def recovery_readback(hub):
    unit=hub._modbus_addr
    protocol=registers(await hub.async_read_holding_registers(unit=unit,address=0x82,count=1),1)[0]
    mode=registers(await hub.async_read_input_registers(unit=unit,address=0x100,count=1),1)[0]
    # V001.00 defines different lengths: disabled=1, Mode6=3, Mode8=8.
    # Never compare stale Mode8 target words after a transition to Mode6.
    length={0:1,6:3,8:8}.get(mode,1)
    words=registers(await hub.async_read_holding_registers(unit=unit,address=0x1A0,count=length),length)
    work=registers(await hub.async_read_holding_registers(unit=unit,address=0x1F,count=1),1)[0]
    power=signed16(registers(await hub.async_read_input_registers(unit=unit,address=0x16,count=1),1)[0])
    mode_after=registers(await hub.async_read_input_registers(unit=unit,address=0x100,count=1),1)[0]
    if mode!=words[0] or mode!=mode_after:
        raise ValueError('inconsistent or transitioning VPP readback')
    return {'protocol':protocol,'vpp_mode':mode,'words':words,'work_mode':work,'battery_w_raw_signed':power}

def recovery_disabled(x):
    return x['protocol']==QUALIFICATION_PROTOCOL and x['vpp_mode']==0 and x['words'][0]==0 and x['work_mode']==2

async def stop_pilot(hub, request, used, get_state, log, clock=utcnow):
    """Explicit manual recovery only. Verify ownership, one disable, direct readback.

    No startup hook, auto-stop, reconnect-write, fallback address or retry.
    A stop ACK is not proof that VPP has exited. No claim of independent recovery.
    """
    remaining=validate_stop(request,used,clock())
    def guard():
        validate_stop(request,used,clock())
        repeat=hub.data.get('_repeatUntil')
        if getattr(hub,'_stopping',True) or not isinstance(repeat,dict) or any(x!=0 for x in repeat.values()):
            raise ValueError('hub stopping or competing repeat')
        for eid,value in ((FIRMWARE,QUALIFICATION_FIRMWARE),(HARDWARE,'Gen4'),(PROTOCOL,'100')):
            state=get_state(eid)
            if state is None or state.state!=value:raise ValueError('stop mapping mismatch')
    outcome={'request_id':request['request_id'],'automatic_retry':False,'physical_response_verified':False}
    attempted=False
    try:
        async with asyncio.timeout(remaining):
            async with hub._poll_data_lock:
                guard()
                before=await recovery_readback(hub)
                await log('before_stop',readback=before)
                if recovery_disabled(before):
                    result={**outcome,'status':'already_disabled','physical_response_verified':True,'readback':before}
                    await log('stop_result',**result)
                    return result
                if before['protocol']!=QUALIFICATION_PROTOCOL or before['work_mode']!=2:
                    raise ValueError('active mode does not match qualified installation; no stop write')
                if before['vpp_mode']==8 and before['words']==expected_words(used['charge_dc_w']):
                    scope='matching_mode8'
                elif (before['vpp_mode']==6 and len(before['words'])==3
                      and before['words'][0]==6 and before['words'][2] in (0xA0,0xA1)
                      and request.get('mode6_recovery_confirmed') is True):
                    # Mode6 does not carry the original pilot's power or ID.
                    # This is explicit operator-authorized recovery, NOT proven ownership.
                    scope='operator_confirmed_mode6_recovery'
                else:
                    raise ValueError('active mode does not match owned pilot or confirmed Mode6; no stop write')
                outcome['recovery_scope']=scope
                transport=hub._core_recovery_transport()
                if transport is None:raise ValueError('Core transport unavailable')
                async with hub._lock:
                    async with transport._request_lock:
                        def final_guard():
                            guard()
                            if not transport.is_connected() or transport.backoff_remaining:
                                raise ValueError('transport unavailable')
                        final_guard()
                        # The service's exclusive journal is durable before any write.
                        await log('disable_requested',address=0xA0,words=[0],recovery_scope=scope)
                        attempted=True
                        try:
                            await single_frame_write(transport._unit(hub._modbus_addr),[0],final_guard,disable=True)
                        except Exception as error:
                            await log('disable_uncertain',error_code=type(error).__name__)
                            outcome['ack']=False
                        else:
                            await log('disable_ack')
                            outcome['ack']=True
    except TimeoutError:
        if not attempted:raise
        outcome['ack']=False
        await log('disable_uncertain',error_code='TimeoutError')
    # Separate bounded read-only verification, never another write.
    try:
        async with asyncio.timeout(5):
            async with hub._poll_data_lock:
                after=await recovery_readback(hub)
        outcome['readback']=after
        outcome['physical_response_verified']=recovery_disabled(after)
    except Exception as error:
        outcome['readback_error']=type(error).__name__
    outcome['status']='disabled_verified' if outcome['physical_response_verified'] else 'recovery_unverified'
    await log('stop_result',**outcome)
    return outcome

def create_stop_journal(path):
    # Exclusive durable record: no repeat of a stop with the same pilot ID.
    path.parent.mkdir(mode=0o700,exist_ok=True)
    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077:
        raise ValueError('stop journal directory must be private')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    os.close(fd)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def append_stop_journal(path, kind, fields):
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
    with os.fdopen(fd,'a',encoding='utf-8') as f:
        f.write(json.dumps({'kind':kind,'at':utcnow().isoformat(),**fields})+'\n')
        f.flush();os.fsync(f.fileno())

def register(hass, domain):
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError
    lock=asyncio.Lock()
    async def service(call):
        if not HARDWARE_DISPATCH_QUALIFIED:
            raise HomeAssistantError('Hardware dispatch locked: firmware-specific confirmation and recovery review pending')
        request=dict(call.data)
        async with lock:
            try:
                approved=await hass.async_add_executor_job(read_approval,ARM_FILE)
                validate_request(request,approved,utcnow())
                rec=hass.data[domain].get(approved['hub_name'])
                hub=rec.get('hub') if isinstance(rec,dict) else None
                if hub is None:raise ValueError('approved hub not found')
                def consume_file():
                    # Atomic single-use local authorization; no regeneration on error.
                    if read_approval(ARM_FILE)!=approved:raise ValueError('approval changed')
                    used=ARM_FILE.with_name(ARM_FILE.name+'.used-'+request['request_id'])
                    if used.exists():raise ValueError('request already consumed')
                    ARM_FILE.rename(used)
                async def consume():
                    await hass.async_add_executor_job(consume_file)
                return await one_shot(hub,request,approved,hass.states.get,consume)
            except Exception as error:
                raise HomeAssistantError('HEC pilot rejected or dispatch uncertain; inspect readback, do not retry: '+type(error).__name__) from error
    async def stop_service(call):
        if not HARDWARE_DISPATCH_QUALIFIED:
            raise HomeAssistantError('Hardware dispatch locked: recovery review pending')
        request=dict(call.data)
        async with lock:
            try:
                rid=str(uuid.UUID(request['request_id']))
                if rid!=request['request_id']:raise ValueError('invalid request id')
                used_path=ARM_FILE.with_name(ARM_FILE.name+'.used-'+rid)
                used=await hass.async_add_executor_job(read_approval,used_path)
                validate_stop(request,used,utcnow())
                rec=hass.data[domain].get(used['hub_name'])
                hub=rec.get('hub') if isinstance(rec,dict) else None
                if hub is None:raise ValueError('approved hub not found')
                path=ARM_FILE.parent/'.hec-mode8-stop-audit'/(rid+'.jsonl')
                await hass.async_add_executor_job(create_stop_journal,path)
                async def log(kind,**fields):
                    await hass.async_add_executor_job(append_stop_journal,path,kind,fields)
                await log('operator_stop_requested',request=request)
                try:
                    return await stop_pilot(hub,request,used,hass.states.get,log)
                except (Exception,asyncio.CancelledError) as error:
                    await log('stop_unverified',error_code=type(error).__name__)
                    raise
            except Exception as error:
                raise HomeAssistantError('HEC stop rejected or unverified; inspect readback, do not retry: '+type(error).__name__) from error
    hass.services.async_register(domain,'hec_mode8_pilot',service,supports_response=SupportsResponse.ONLY)
    hass.services.async_register(domain,'hec_mode8_stop',stop_service,supports_response=SupportsResponse.ONLY)
