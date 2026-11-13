import asyncio
from queue import Queue
import unittest
from unittest.mock import Mock, call, patch

from fastapi import HTTPException

import main
from modules import hardware_manager
from modules.hamahoto_module import SerialCommunicator
from modules.kikusui_module import KikusuiCommunicator


class EndOfTasks(Exception):
    pass


class RawCommandTests(unittest.TestCase):
    def setUp(self):
        self.serial = SerialCommunicator('/dev/mockHV', is_test_mode=True)
        self.kikusui = KikusuiCommunicator('mock', is_test_mode=True)
        self.kikusui.instrument = Mock()
        self.kikusui.instrument.query.return_value = '50.0\n'

    def test_serial_rejects_control_commands_and_injection_in_real_and_mock_modes(self):
        commands = ['HON', 'HRE', 'HCM1', 'HCM0', 'HBV2C31',
                    'HST00000000000000002C31B7D7', 'hRe', 'HPO;HON',
                    'HPO\rHON', 'HPO\nHRE', 'HPO\x00', 'unknown', '']
        with patch.object(self.serial, '_send_and_receive') as send:
            for mode in (False, True):
                self.serial.is_test_mode = mode
                for command in commands:
                    with self.subTest(mode=mode, command=command):
                        self.assertTrue(self.serial.send_raw_command(command).startswith(b'ERROR:'))
            send.assert_not_called()

    def test_serial_allows_queries_and_off_with_normalization(self):
        self.serial.is_test_mode = False
        with patch.object(self.serial, '_send_and_receive', return_value=b'reply') as send:
            for command in ('HRT', 'HPO', 'HGS', 'HGV', 'HGC', 'HGT', 'HOF'):
                with self.subTest(command=command):
                    self.assertEqual(self.serial.send_raw_command(f' {command.lower()} '), b'reply')
                    send.assert_called_with(command.encode('ascii'))

    def test_serial_numeric_queries_validate_fixed_hex_payloads(self):
        self.serial.is_test_mode = False
        self.serial.ser = Mock(is_open=True)
        for command in ('HGV', 'HGC', 'HGT'):
            for payload, valid in ((b'0014', True), (b'014', False), (b'GGGG', False)):
                with self.subTest(command=command, payload=payload):
                    body = command.lower().encode() + payload
                    response = b'\x02' + body + b'\x03' + f'{(sum(body) + 5) & 255:02X}'.encode() + b'\r'
                    self.serial.ser.read_until.return_value = response
                    with patch('modules.hamahoto_module.time.sleep'):
                        result = self.serial.send_raw_command(command)
                    if valid:
                        self.assertEqual(result, response)
                    else:
                        self.assertTrue(result.startswith(b'ERROR:'))

    def test_kikusui_rejects_writes_unknown_queries_and_compound_commands(self):
        commands = ['OUTP ON', 'OUTP OFF', '*RST', '*CLS', 'VOLT 50',
                    'MEAS:VOLT?;OUTP ON', 'MEAS:VOLT?\n*RST', '*IDN?;*RST',
                    'MEAS:UNKNOWN?', 'HPO', '']
        for mode in (False, True):
            self.kikusui.is_test_mode = mode
            for command in commands:
                with self.subTest(mode=mode, command=command):
                    self.assertTrue(self.kikusui.send_raw_command(command).startswith(b'ERROR:'))
        self.kikusui.instrument.write.assert_not_called()
        self.kikusui.instrument.query.assert_not_called()

    def test_kikusui_reads_each_query_response_instead_of_leaving_it_unread(self):
        self.kikusui.is_test_mode = False
        self.kikusui.instrument.query.side_effect = ['50.0\n', '0.012\n', '1\n']
        self.assertEqual(self.kikusui.send_raw_command(' meas:volt? '), b'50.0')
        self.assertEqual(self.kikusui.send_raw_command('MEASure:CURRent?'), b'0.012')
        self.assertEqual(self.kikusui.send_raw_command('OUTP:STAT?'), b'1')
        self.assertEqual(self.kikusui.instrument.query.call_args_list,
                         [call('MEASure:VOLTage?'), call('MEASure:CURRent?'), call('OUTPut:STATe?')])
        self.kikusui.instrument.write.assert_not_called()

    def test_api_rejects_disallowed_commands_without_queuing_or_hardware_io(self):
        queue = Queue()
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: self.serial, 2: self.kikusui}, clear=True), \
                patch.object(main, 'command_queue', queue), \
                patch.object(self.serial, '_send_and_receive') as send:
            for port, command in [(1, 'HRE'), (1, 'HCM1'), (1, 'MEAS:VOLT?'),
                                  (2, '*RST'), (2, 'OUTP ON'), (2, 'HOF')]:
                with self.subTest(port=port, command=command):
                    request = main.RawCommand(port_id=port, command=command)
                    with self.assertRaises(HTTPException) as raised:
                        asyncio.run(main.queue_raw_command(request))
                    self.assertEqual(raised.exception.status_code, 422)
                    self.assertTrue(queue.empty())
            send.assert_not_called()
        self.kikusui.instrument.query.assert_not_called()
        self.kikusui.instrument.write.assert_not_called()

    def test_api_only_queues_approved_commands(self):
        queue = Queue()
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: self.serial, 2: self.kikusui}, clear=True), \
                patch.object(main, 'command_queue', queue), patch.object(main, 'log'):
            for port, command in [(1, 'HOF'), (1, 'HRT'), (2, 'MEAS:VOLT?')]:
                request = main.RawCommand(port_id=port, command=command)
                self.assertEqual(asyncio.run(main.queue_raw_command(request))['status'], 'success')
                self.assertEqual(queue.get_nowait()['command_info']['raw_command'], command)

    def test_worker_cannot_bypass_restrictions_and_processes_next_command(self):
        for communicator, forbidden, query in ((self.serial, 'HRE', 'HOF'),
                                               (self.kikusui, '*RST', 'MEAS:VOLT?')):
            with self.subTest(forbidden=forbidden):
                communicator.is_test_mode = False
                queue = Mock()
                queue.get.side_effect = [
                    {'port_id': 1, 'command_info': {'command_type': 'RAW', 'raw_command': forbidden}},
                    {'port_id': 1, 'command_info': {'command_type': 'RAW', 'raw_command': query}},
                    EndOfTasks(),
                ]
                with patch.dict(hardware_manager.DEVICE_PORTS, {1: communicator}, clear=True), \
                        patch.object(self.serial, '_send_and_receive', return_value=b'reply') as send, \
                        patch.object(hardware_manager.log_database, 'save_action_log') as action_log, \
                        patch.object(hardware_manager, 'log'):
                    with self.assertRaises(EndOfTasks):
                        hardware_manager.worker(queue)
                self.assertTrue(action_log.call_args_list[0].args[2].startswith(b'ERROR:'))
                self.assertFalse(action_log.call_args_list[1].args[2].startswith(b'ERROR:'))
                self.assertEqual(queue.task_done.call_count, 2)
                if communicator is self.serial:
                    send.assert_called_once_with(b'HOF')
                else:
                    self.kikusui.instrument.query.assert_called_once_with('MEASure:VOLTage?')
                    self.kikusui.instrument.write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
