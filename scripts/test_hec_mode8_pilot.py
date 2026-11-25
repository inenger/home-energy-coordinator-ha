"""Synthetic HA-side service contract; never imports HA or contacts a device."""
import asyncio
from datetime import datetime,timezone,timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock,Mock

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
    async def test_disconnected_blocks_without_reconnect(self):
        self.transport.is_connected.return_value=False
        with self.assertRaises(ValueError):await self.execute()
        self.client.write_registers.assert_not_awaited()
if __name__=='__main__':unittest.main()
