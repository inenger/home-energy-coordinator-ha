"""Pinned real Core dependency stack, isolated 127.0.0.1 only. No HA/device access."""
import asyncio
import importlib.util
from pathlib import Path
import struct
import time
import unittest
from unittest.mock import patch

from modbus_connection import ModbusTcpParams
from modbus_connection.tmodbus import ModbusConnection
from tmodbus.exceptions import ServerDeviceBusyError

spec=importlib.util.spec_from_file_location('pilot',Path(__file__).resolve().parents[1]/'ops/solax_modbus/hec_mode8_pilot.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TransportLoopback(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.frames=[]
        self.responses=[]
        self.writers=set()
        async def handler(reader,writer):
            self.writers.add(writer)
            try:
                while True:
                    h=await reader.readexactly(7)
                    tx,proto,length,unit=struct.unpack('>HHHB',h)
                    pdu=await reader.readexactly(length-1)
                    self.frames.append((unit,pdu,time.monotonic()))
                    action=self.responses.pop(0) if self.responses else 'ack'
                    if action=='lost':continue
                    if action=='disconnect':break
                    if action=='busy':response=bytes([0x90,6])
                    elif pdu[0]==3:response=bytes([3,2,0,42])
                    elif pdu[0]==16:response=pdu[:5]
                    else:raise AssertionError('unexpected test function')
                    writer.write(struct.pack('>HHHB',tx,0,len(response)+1,unit)+response)
                    await writer.drain()
            except (asyncio.IncompleteReadError,ConnectionError):pass
            finally:
                self.writers.discard(writer)
                writer.close()
                await writer.wait_closed()
        self.server=await asyncio.start_server(handler,'127.0.0.1',0)
        self.conn=ModbusConnection(ModbusTcpParams(host='127.0.0.1',port=self.server.sockets[0].getsockname()[1]),timeout=.20,message_spacing=.02)
        await self.conn.connect()
        self.unit=self.conn.for_unit(1)
        self.words=m.expected_words(100)
    async def asyncTearDown(self):
        await self.conn.close()
        for writer in list(self.writers):
            writer.close()
            await writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()
    async def send(self,guard=lambda:None):
        await m.single_frame_write(self.unit,self.words,guard)
    def assert_one(self):
        self.assertEqual(len(self.frames),1)
        unit,pdu,_=self.frames[0]
        self.assertEqual(unit,1)
        self.assertEqual(pdu,struct.pack('>BHHB8H',16,0xA0,8,16,*self.words))
    async def test_ack_and_exact_payload(self):
        await self.send()
        self.assert_one()
    async def test_busy_no_retry_and_normal_policy_unchanged(self):
        self.responses=['busy']
        smart=self.unit._client.transport
        policy=smart.response_retry_strategy
        with self.assertRaises(ServerDeviceBusyError):await self.send()
        await asyncio.sleep(.15)
        self.assert_one()
        self.assertIs(smart.response_retry_strategy,policy)
        self.responses=['busy','ack']
        await self.unit.write_registers(1,[123])
        self.assertEqual(len(self.frames),3)
    async def test_lost_reply_no_retry(self):
        self.responses=['lost']
        with self.assertRaises(TimeoutError):await self.send()
        await asyncio.sleep(.25)
        self.assert_one()
        self.assertEqual(await self.unit.read_holding_registers(1,1),[42])
    async def test_cancel_no_late_write(self):
        self.responses=['lost']
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(.08):await self.send()
        await asyncio.sleep(.25)
        self.assert_one()
        self.assertEqual(await self.unit.read_holding_registers(1,1),[42])
    async def test_deadline_after_pacer_queue(self):
        expires=time.monotonic()+.03
        def guard():
            if time.monotonic()>=expires:raise ValueError('expired')
        async with self.conn._pacer.paced(2):
            task=asyncio.create_task(self.send(guard))
            await asyncio.sleep(.06)
        with self.assertRaisesRegex(ValueError,'expired'):await task
        self.assertEqual(self.frames,[])
    async def test_connection_closed_no_reconnect(self):
        await self.conn.disconnect()
        with self.assertRaisesRegex(ValueError,'unavailable'):await self.send()
        self.assertFalse(self.conn.connected)
        self.assertEqual(self.frames,[])
    async def test_version_and_payload_fail_closed(self):
        with patch.object(m,'version',return_value='0.0'):
            with self.assertRaisesRegex(ValueError,'unreviewed'):await self.send()
        with self.assertRaisesRegex(ValueError,'payload'):
            await m.single_frame_write(self.unit,[0],lambda:None)
        self.assertEqual(self.frames,[])
    async def test_disable_exact_frame(self):
        await m.single_frame_write(self.unit,[0],lambda:None,disable=True)
        self.assertEqual(len(self.frames),1)
        self.assertEqual(self.frames[0][:2],(1,struct.pack('>BHHBH',16,0xA0,1,2,0)))
    async def test_disable_busy_no_retry(self):
        self.responses=['busy']
        with self.assertRaises(ServerDeviceBusyError):
            await m.single_frame_write(self.unit,[0],lambda:None,disable=True)
        await asyncio.sleep(.15)
        self.assertEqual(len(self.frames),1)
    async def test_disable_payload_not_arbitrary(self):
        with self.assertRaises(ValueError):
            await m.single_frame_write(self.unit,self.words,lambda:None,disable=True)
        self.assertEqual(self.frames,[])
    async def test_other_unit_serialized_and_gap_preserved(self):
        other=self.conn.for_unit(2)
        await asyncio.gather(self.send(),other.read_holding_registers(1,1))
        self.assertEqual(len(self.frames),2)
        self.assertEqual({x[0] for x in self.frames},{1,2})
        self.assertGreaterEqual(self.frames[1][2]-self.frames[0][2],.018)
    async def test_disconnect_after_send_no_reconnect(self):
        self.responses=['disconnect']
        with self.assertRaises(Exception):await self.send()
        await asyncio.sleep(.25)
        self.assert_one()

if __name__=='__main__':unittest.main(verbosity=2)
