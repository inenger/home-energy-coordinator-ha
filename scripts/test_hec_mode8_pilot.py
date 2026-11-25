"""Synthetic HA-side service contract; never imports HA or contacts a device."""
import asyncio
from datetime import datetime,timezone,timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock,Mock,patch

path=Path(__file__).resolve().parents[1]/'ops/solax_modbus/hec_mode8_pilot.py'
spec=importlib.util.spec_from_file_location('pilot_candidate',path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PilotServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        a=self.approved=dict(request_id=str(uuid.uuid4()),hub_name='test',mapping=m.MAPPING,
                             charge_dc_w=300,wait_timeout_s=10,operator_confirmed=True,ev_disconnected_confirmed=True,
                             expires_at=(self.now+timedelta(seconds=30)).isoformat())
        self.req={**a,'send_before':(self.now+timedelta(seconds=5)).isoformat()}
        self.states={}
        def add(eid,value,unit=None):
            self.states[eid]=SimpleNamespace(state=str(value),attributes={'unit_of_measurement':unit},
                                              last_reported=self.now)
        for e in m.PHASES:add(e,10,'A')
        for eid,v,u in [(m.BREAKER,25,'A'),(m.SOC,40,'%'),(m.POWER,0,'W'),(m.PV,0,'W'),
                        (m.EV,0,'W'),(m.REPEAT,0,'s')]:add(eid,v,u)
        for eid,v in [(m.MODE,'Disabled'),(m.REMOTE,'Disabled'),(m.HEALTH,'Healthy'),
                      (m.RUN,'Normal Mode'),(m.WORK,'Back Up Mode'),(m.PARALLEL,'Free'),(m.FIRMWARE,m.QUALIFICATION_FIRMWARE),(m.PROTOCOL,100),(m.HARDWARE,'Gen4'),(m.EV_MODE,'Stop'),(m.EV_STATUS,'Available'),(m.EV_CABLE,'off')]:add(eid,v)
        self.client=SimpleNamespace(write_registers=AsyncMock())
        self.transport=SimpleNamespace(_request_lock=asyncio.Lock(),_unit=Mock(return_value=self.client),
                                       is_connected=Mock(return_value=True),backoff_remaining=0)
        self.input_mode=0;self.holding_mode=0;self.run_mode=2;self.battery_power=0;self.work_mode=2;self.protocol=100
        async def input_read(unit,address,count):
            if address==0x09:
                v=[0]*20;v[0]=self.run_mode;v[0x14-9]=2360;v[0x16-9]=self.battery_power;v[0x1c-9]=40
            else:v=[self.input_mode]
            return SimpleNamespace(isError=lambda:False,registers=v)
        async def holding_read(unit,address,count):
            return SimpleNamespace(isError=lambda:False,registers=[self.protocol if address==0x82 else self.work_mode if address==0x1f else self.holding_mode])
        self.hub=SimpleNamespace(_poll_data_lock=asyncio.Lock(),_lock=asyncio.Lock(),_stopping=False,
                  data={'_repeatUntil':{}},_modbus_addr=1,
                  async_read_input_registers=AsyncMock(side_effect=input_read),
                  async_read_holding_registers=AsyncMock(side_effect=holding_read),
                  _core_recovery_transport=Mock(return_value=self.transport),
                  _encode_multi_write_payload=Mock(return_value=[8,1,15000,0,0xfed4,0xffff,10,0xa0]))
        self.consume=AsyncMock()
        self.current=self.now
        async def mock_frame(unit,values,guard):
            guard()
            await unit.write_registers(0xA0,values)
        self.frame_patch=patch.object(m,'single_frame_write',side_effect=mock_frame)
        self.frame=self.frame_patch.start()
        self.addCleanup(self.frame_patch.stop)
    async def advance(self,delay):
        self.current+=timedelta(seconds=delay)
        for s in self.states.values():
            if s is not None and s.last_reported>=self.now:s.last_reported=self.current
    async def execute(self,clock=None,pause=None):
        return await m.one_shot(self.hub,self.req,self.approved,self.states.get,self.consume,clock or (lambda:self.current),pause or self.advance)
    async def test_one_complete_candidate_and_no_repeat(self):
        r=await self.execute()
        self.hub._encode_multi_write_payload.assert_called_once_with(
            [('_uint16',8),('_uint16',1),('_uint32',15000),('_int32',-300),('_uint16',10),('_uint16',160)])
        self.client.write_registers.assert_awaited_once_with(0xa0,[8,1,15000,0,65236,65535,10,160])
        self.consume.assert_awaited_once()
        self.assertEqual(r['status'],'modbus_call_returned')
        self.assertFalse(r['physical_response_verified'])
    async def test_reject_big_endian_word_order_before_dispatch(self):
        self.hub._encode_multi_write_payload.return_value=[8,1,0,15000,65535,65236,10,160]
        with self.assertRaisesRegex(ValueError,'wire words'):
            await self.execute()
        self.consume.assert_not_awaited()
        self.client.write_registers.assert_not_awaited()
    def test_documented_candidate_words_and_hardware_lock(self):
        self.assertIs(m.HARDWARE_DISPATCH_QUALIFIED,False)
        for w in (100,200,300):
            words=m.expected_words(w)
            self.assertEqual(words[2:4],[15000,0])
            self.assertEqual((words[5]<<16|words[4])-2**32,-w)
            self.assertEqual(words[6:],[10,160])
    async def test_reject_partial_phase_or_high_current_or_stale(self):
        e=m.PHASES[1];old=self.states[e]
        for s in (None,SimpleNamespace(state='18.1',attributes={'unit_of_measurement':'A'},last_reported=self.now),
                  SimpleNamespace(state='1',attributes={'unit_of_measurement':'A'},last_reported=self.now-timedelta(seconds=4))):
            with self.subTest(s=s):
                self.states[e]=s
                with self.assertRaises(ValueError):await self.execute()
        self.states[e]=old
        self.client.write_registers.assert_not_awaited();self.consume.assert_not_awaited()
    async def test_expired_after_lock_never_writes(self):
        async def expire(_):self.current=self.now+timedelta(seconds=6)
        with self.assertRaises(ValueError):await self.execute(pause=expire)
        self.consume.assert_not_awaited();self.client.write_registers.assert_not_awaited()
    async def test_foreign_owner_and_repeat_block(self):
        self.hub.data['_repeatUntil']={'mode8':1}
        with self.assertRaises(ValueError):await self.execute()
        self.hub.data['_repeatUntil']={}
        self.input_mode=6
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
    async def test_holding_readback_or_firmware_mismatch_blocks(self):
        self.holding_mode=8
        with self.assertRaises(ValueError):await self.execute()
        self.holding_mode=0
        self.states[m.FIRMWARE].state='different'
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
    async def test_protocol_mismatch_blocks_at_ha_and_physical_read(self):
        self.states[m.PROTOCOL].state='102'
        with self.assertRaisesRegex(ValueError,'Modbus document version'):
            await self.execute()
        self.states[m.PROTOCOL].state='100'
        self.protocol=102
        with self.assertRaisesRegex(ValueError,'physical Modbus protocol'):
            await self.execute()
        self.client.write_registers.assert_not_awaited()
        self.consume.assert_not_awaited()
    async def test_duplicate_frames_do_not_authorize(self):
        async def no_new(_):self.current+=timedelta(seconds=1)
        with self.assertRaises(ValueError):await self.execute(pause=no_new)
        self.client.write_registers.assert_not_awaited()
    async def test_stable_ha_states_never_replace_physical_read(self):
        self.run_mode=3
        with self.assertRaises(ValueError):await self.execute()
        self.run_mode=2;self.battery_power=65535-400
        with self.assertRaises(ValueError):await self.execute()
        self.battery_power=0;self.work_mode=3
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
    async def test_transport_error_never_retries(self):
        self.client.write_registers.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):await self.execute()
        self.client.write_registers.assert_awaited_once();self.consume.assert_awaited_once()
    async def test_mismatched_approval_never_writes(self):
        self.req['charge_dc_w']=200
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
    async def test_invalid_pv_or_ev_blocks(self):
        for eid, value in ((m.PV,'1000.1'),(m.EV,'100.1')):
            self.states[eid].state=value
            with self.assertRaises(ValueError):await self.execute()
            self.states[eid].state='0'
        self.client.write_registers.assert_not_awaited()
    async def test_pv_at_new_limit_allows_only_synthetic_single_shot(self):
        self.states[m.PV].state='1000'
        await self.execute()
        self.client.write_registers.assert_awaited_once()
        self.assertIs(m.HARDWARE_DISPATCH_QUALIFIED,False)
    async def test_invalid_pv_even_below_limit_blocks(self):
        for value in ('-1','nan','inf','unknown'):
            self.states[m.PV].state=value
            with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
    async def test_stale_pv_blocks(self):
        self.states[m.PV].last_reported=self.now-timedelta(seconds=4)
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
    async def test_final_guard_rechecks_after_transport_queue(self):
        async def delayed_frame(unit,values,guard):
            self.current+=timedelta(seconds=6)
            guard()
            await unit.write_registers(0xA0,values)
        self.frame.side_effect=delayed_frame
        with self.assertRaisesRegex(ValueError,'expired'):
            await self.execute()
        self.consume.assert_awaited_once()
        self.client.write_registers.assert_not_awaited()
    async def test_disconnected_blocks_without_reconnect(self):
        self.transport.is_connected.return_value=False
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
class StopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.used=dict(request_id=str(uuid.uuid4()),hub_name='test',mapping=m.MAPPING,
                       charge_dc_w=100,wait_timeout_s=10,operator_confirmed=True,
                       ev_disconnected_confirmed=True,expires_at=(self.now+timedelta(seconds=20)).isoformat())
        self.req=dict(request_id=self.used['request_id'],hub_name='test',operator_confirmed=True,
                      send_before=(self.now+timedelta(seconds=5)).isoformat())
        self.current=self.now
        self.active=dict(protocol=100,vpp_mode=8,words=m.expected_words(100),work_mode=2,battery_w_raw_signed=-100)
        self.disabled=dict(protocol=100,vpp_mode=0,words=[0]*8,work_mode=2,battery_w_raw_signed=0)
        self.client=Mock()
        self.transport=SimpleNamespace(_request_lock=asyncio.Lock(),_unit=Mock(return_value=self.client),
                                        is_connected=Mock(return_value=True),backoff_remaining=0)
        self.hub=SimpleNamespace(_poll_data_lock=asyncio.Lock(),_lock=asyncio.Lock(),_stopping=False,
                                 data={'_repeatUntil':{}},_modbus_addr=1,_core_recovery_transport=Mock(return_value=self.transport))
        self.states={e:SimpleNamespace(state=v) for e,v in ((m.FIRMWARE,m.QUALIFICATION_FIRMWARE),(m.HARDWARE,'Gen4'),(m.PROTOCOL,'100'))}
        self.read=AsyncMock(side_effect=[self.active,self.disabled])
        self.log=AsyncMock()
        self.send=AsyncMock(side_effect=lambda u,v,g,**kw:g())
        for n,v in [('recovery_readback',self.read),('single_frame_write',self.send)]:
            patcher=patch.object(m,n,v);patcher.start();self.addCleanup(patcher.stop)
    async def execute(self):
        return await m.stop_pilot(self.hub,self.req,self.used,self.states.get,self.log,lambda:self.current)
    async def test_owned_disable_verified(self):
        r=await self.execute()
        self.assertEqual(r['status'],'disabled_verified')
        self.assertTrue(r['ack'])
        self.assertTrue(r['physical_response_verified'])
        self.assertEqual(self.send.call_count,1)
        self.assertEqual(self.send.call_args.args[1],[0])
        self.assertEqual(self.send.call_args.kwargs,{'disable':True})
        self.assertEqual([x.args[0] for x in self.log.call_args_list],['before_stop','disable_requested','disable_ack','stop_result'])
    async def test_already_disabled_no_write(self):
        self.read.side_effect=[self.disabled]
        self.assertEqual((await self.execute())['status'],'already_disabled')
        self.send.assert_not_called()
    async def test_ack_alone_not_success(self):
        self.read.side_effect=[self.active,self.active]
        r=await self.execute()
        self.assertEqual(r['status'],'recovery_unverified')
        self.assertTrue(r['ack'])
        self.assertFalse(r['physical_response_verified'])
    async def test_lost_ack_readback_verified_without_resending(self):
        self.send.side_effect=TimeoutError
        r=await self.execute()
        self.assertFalse(r['ack'])
        self.assertTrue(r['physical_response_verified'])
        self.send.assert_awaited_once()
    async def test_outer_deadline_after_dispatch_still_reads_back(self):
        self.req['send_before']=(self.now+timedelta(seconds=.05)).isoformat()
        async def slow(*args,**kwargs):await asyncio.sleep(.2)
        self.send.side_effect=slow
        r=await self.execute()
        self.assertFalse(r['ack'])
        self.assertTrue(r['physical_response_verified'])
        self.send.assert_awaited_once()
    async def test_readback_failure_not_verified(self):
        self.read.side_effect=[self.active,OSError('read failed')]
        r=await self.execute()
        self.assertEqual(r['status'],'recovery_unverified')
        self.assertEqual(r['readback_error'],'OSError')
        self.send.assert_awaited_once()
    async def test_foreign_or_mode6_rejected(self):
        for bad in ({'vpp_mode':6},{'words':m.expected_words(200)},{'protocol':102},{'work_mode':1}):
            self.read.side_effect=[{**self.active,**bad}]
            with self.assertRaisesRegex(ValueError,'does not match'):
                await self.execute()
        self.send.assert_not_called()
    async def test_mode6_requires_explicit_operator_recovery(self):
        mode6={**self.active,'vpp_mode':6,'words':[6,10,160]}
        self.read.side_effect=[mode6]
        with self.assertRaisesRegex(ValueError,'does not match'):await self.execute()
        self.send.assert_not_called()
        self.req['mode6_recovery_confirmed']=True
        self.read.side_effect=[mode6,self.disabled]
        r=await self.execute()
        self.assertEqual(r['status'],'disabled_verified')
        self.assertEqual(r['recovery_scope'],'operator_confirmed_mode6_recovery')
        self.send.assert_awaited_once()
        self.assertEqual(self.send.call_args.args[1],[0])
        self.assertEqual(self.send.call_args.kwargs,{'disable':True})
    async def test_mode6_confirmation_cannot_override_other_mode_or_invalid_readback(self):
        self.req['mode6_recovery_confirmed']=True
        for bad in ({'vpp_mode':7,'words':[7,10,160]},
                    {'vpp_mode':6,'words':[8,10,160]},
                    {'vpp_mode':6,'words':[6,10,999]},
                    {'vpp_mode':6,'words':[6]},
                    {'vpp_mode':6,'words':[6,10,160],'protocol':102},
                    {'vpp_mode':6,'words':[6,10,160],'work_mode':1}):
            self.read.side_effect=[{**self.active,**bad}]
            with self.assertRaises(ValueError):await self.execute()
        self.send.assert_not_called()
    async def test_mode6_still_requires_recent_matching_approval(self):
        self.req['mode6_recovery_confirmed']=True
        self.used['expires_at']=(self.now-timedelta(seconds=121)).isoformat()
        with self.assertRaisesRegex(ValueError,'expired'):await self.execute()
        self.send.assert_not_called()
    async def test_mode6_lost_ack_never_repeats(self):
        self.req['mode6_recovery_confirmed']=True
        self.read.side_effect=[{**self.active,'vpp_mode':6,'words':[6,10,161]},self.disabled]
        self.send.side_effect=TimeoutError
        r=await self.execute()
        self.assertFalse(r['ack'])
        self.assertTrue(r['physical_response_verified'])
        self.send.assert_awaited_once()
    async def test_mode6_ack_without_exit_is_not_success(self):
        self.req['mode6_recovery_confirmed']=True
        mode6={**self.active,'vpp_mode':6,'words':[6,10,160]}
        self.read.side_effect=[mode6,mode6]
        r=await self.execute()
        self.assertEqual(r['status'],'recovery_unverified')
        self.send.assert_awaited_once()
    async def test_no_ownership_or_stale_deadline(self):
        self.req['request_id']=str(uuid.uuid4())
        with self.assertRaises(ValueError):await self.execute()
        self.req['request_id']=self.used['request_id']
        self.current+=timedelta(seconds=6)
        with self.assertRaises(ValueError):await self.execute()
        self.read.assert_not_awaited()
        self.send.assert_not_called()
    async def test_competing_repeat_blocks(self):
        self.hub.data['_repeatUntil']={'other':1}
        with self.assertRaises(ValueError):await self.execute()
        self.send.assert_not_called()
    async def test_log_failure_prevents_write(self):
        self.log.side_effect=[None,OSError('disk')]
        with self.assertRaises(OSError):await self.execute()
        self.send.assert_not_called()
    def test_journal_single_use_private(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'private'/'test.jsonl'
            m.create_stop_journal(p)
            m.append_stop_journal(p,'before_stop',{'test':True})
            self.assertEqual(json.loads(p.read_text())['kind'],'before_stop')
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):m.create_stop_journal(p)

class ReadbackTests(unittest.IsolatedAsyncioTestCase):
    async def check(self,mode,words,mode_after=None):
        def reply(v):return SimpleNamespace(isError=lambda:False,registers=v)
        hub=SimpleNamespace(_modbus_addr=1,
            async_read_holding_registers=AsyncMock(side_effect=[reply([100]),reply(words),reply([2])]),
            async_read_input_registers=AsyncMock(side_effect=[reply([mode]),reply([0]),reply([mode if mode_after is None else mode_after])]))
        r=await m.recovery_readback(hub)
        self.assertEqual(hub.async_read_holding_registers.call_args_list[1].kwargs['count'],len(words))
        return r
    async def test_documented_read_lengths(self):
        for mode,words in ((0,[0]),(6,[6,10,160]),(8,m.expected_words(100))):
            r=await self.check(mode,words)
            self.assertEqual(r['words'],words)
    async def test_incoherent_readback_rejected(self):
        for mode,words,after in ((6,[8,10,160],6),(6,[6,10,160],0)):
            with self.assertRaisesRegex(ValueError,'transitioning'):await self.check(mode,words,after)

if __name__=='__main__':unittest.main()
