from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import serial
import yaml

import main
from modules import db_logs, db_measurements, hardware_manager
from modules.hamahoto_module import SerialCommunicator


OLD_PARAMETERS = b'0000000000000000001E0014'
SAFE_PARAMETERS = b'00000000000000002C31B7D7'


def frame(body):
    return b'\x02' + body + b'\x03' + f'{(sum(body) + 5) & 255:02X}'.encode() + b'\r'


class SimulatedSerial:
    """Memory-only device for checking actual frames, state changes and readback."""
    def __init__(self, parameters=OLD_PARAMETERS):
        self.parameters = parameters
        self.status = 0x41
        self.is_open = True
        self.commands = []
        self.faults = {}
        self.stuck_hv = False
        self.stuck_correction = False
        self.ignore_write = False
        self.output_on_after_write = False

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def flush(self):
        pass

    def write(self, packet):
        command = packet[1:-4]
        self.commands.append(command)
        assert packet == frame(command), 'Incorrect outgoing frame'
        fault = self.faults.get(command[:3])
        if isinstance(fault, Exception):
            raise fault
        if fault is not None:
            self.reply = fault
        elif command == b'HOF':
            if not self.stuck_hv:
                self.status &= ~1
            self.reply = frame(b'hof')
        elif command == b'HCM0':
            if not self.stuck_correction:
                self.status &= ~(1 << 6)
            self.reply = frame(b'hcm')
        elif command == b'HGS':
            self.reply = frame(b'hgs' + f'{self.status:04X}'.encode())
        elif command == b'HRT':
            self.reply = frame(b'hrt' + self.parameters)
        elif command.startswith(b'HST'):
            assert self.status & 0x41 == 0, 'Persistent write before OFF verification'
            if not self.ignore_write:
                self.parameters = command[3:]
            if self.output_on_after_write:
                self.status |= 1
            self.reply = frame(b'hst')
        else:
            raise AssertionError(f'Unexpected command: {command!r}')
        return len(packet)

    def read_until(self, delimiter):
        assert delimiter == b'\r'
        return self.reply


class SerialStartupTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('modules.hamahoto_module.time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def initialize(self, transport):
        with patch('modules.hamahoto_module.serial.Serial', return_value=transport):
            communicator = SerialCommunicator('/dev/simulated', is_test_mode=False)
        return communicator.initialize_safe_state()

    def test_startup_verifies_off_before_writing_and_reads_back_parameters(self):
        transport = SimulatedSerial()
        self.assertEqual(self.initialize(transport), b'OK_SAFE_INITIALIZED')
        self.assertEqual(transport.parameters, SAFE_PARAMETERS)
        self.assertEqual(transport.status & 0x41, 0)
        self.assertEqual(transport.commands, [
            b'HOF', b'HCM0', b'HGS', b'HRT', b'HST' + SAFE_PARAMETERS, b'HRT', b'HGS',
        ])
        # No voltage-application or hardware-reset commands are used.
        self.assertFalse(any(command[:3] in (b'HON', b'HBV', b'HRE')
                             for command in transport.commands))

    def test_matching_parameters_skip_persistent_write(self):
        transport = SimulatedSerial(SAFE_PARAMETERS)
        self.assertEqual(self.initialize(transport), b'OK_SAFE_INITIALIZED')
        self.assertEqual(transport.commands, [b'HOF', b'HCM0', b'HGS', b'HRT', b'HGS'])

    def test_nonzero_coefficients_are_cleared(self):
        transport = SimulatedSerial(b'FC1803E8043004302C31B7D7')
        self.assertEqual(self.initialize(transport), b'OK_SAFE_INITIALIZED')
        self.assertEqual(transport.parameters, SAFE_PARAMETERS)
        self.assertEqual(sum(command.startswith(b'HST') for command in transport.commands), 1)

    def test_unconfirmed_output_or_correction_prevents_persistent_write(self):
        for stuck_attribute in ('stuck_hv', 'stuck_correction'):
            with self.subTest(stuck_attribute=stuck_attribute):
                transport = SimulatedSerial()
                setattr(transport, stuck_attribute, True)
                self.assertTrue(self.initialize(transport).startswith(b'ERROR:'))
                self.assertEqual(transport.commands, [b'HOF', b'HCM0', b'HGS', b'HOF'])

    def test_readback_mismatch_fails_and_attempts_off(self):
        transport = SimulatedSerial()
        transport.ignore_write = True
        result = self.initialize(transport)
        self.assertIn(b'readback mismatch', result)
        self.assertEqual(transport.commands[-1], b'HOF')

    def test_final_status_is_verified_after_persistent_write(self):
        transport = SimulatedSerial()
        transport.output_on_after_write = True
        self.assertTrue(self.initialize(transport).startswith(b'ERROR:'))
        self.assertEqual(transport.commands[-2:], [b'HGS', b'HOF'])
        self.assertEqual(transport.status & 1, 0)

    def test_each_command_failure_aborts_and_attempts_off(self):
        for failed_command in (b'HOF', b'HCM', b'HGS', b'HRT', b'HST'):
            with self.subTest(failed_command=failed_command):
                transport = SimulatedSerial()
                transport.faults[failed_command] = frame(b'hxx0004')
                self.assertTrue(self.initialize(transport).startswith(b'ERROR:'))
                self.assertEqual(transport.commands[-1], b'HOF')

    def test_corrupt_parameter_response_is_not_used_for_writing(self):
        transport = SimulatedSerial()
        transport.faults[b'HRT'] = frame(b'hrt' + b'G' * 24)
        self.assertTrue(self.initialize(transport).startswith(b'ERROR:'))
        self.assertFalse(any(command.startswith(b'HST') for command in transport.commands))

    def test_serial_exception_and_failed_fallback_off_do_not_escape(self):
        transport = SimulatedSerial()
        transport.faults[b'HOF'] = serial.SerialException('disconnected')
        self.assertTrue(self.initialize(transport).startswith(b'ERROR:'))
        self.assertEqual(transport.commands, [b'HOF', b'HOF'])

    def test_mock_startup_never_opens_a_serial_port(self):
        with patch('modules.hamahoto_module.serial.Serial', side_effect=AssertionError('hardware access')):
            communicator = SerialCommunicator('/dev/mockHV', is_test_mode=True)
            self.assertEqual(communicator.initialize_safe_state(), b'OK_SAFE_INITIALIZED_MOCK')

    def test_all_serial_devices_are_checked_even_when_one_fails(self):
        first = Mock(spec=SerialCommunicator)
        second = Mock(spec=SerialCommunicator)
        first.initialize_safe_state.return_value = b'ERROR:failed'
        second.initialize_safe_state.return_value = b'OK_SAFE_INITIALIZED'
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: first, 2: second}, clear=True):
            self.assertFalse(main._initialize_serial_devices())
        first.initialize_safe_state.assert_called_once()
        second.initialize_safe_state.assert_called_once()

    def test_main_only_starts_server_after_successful_serial_verification(self):
        for stuck in (False, True):
            with self.subTest(stuck=stuck), TemporaryDirectory() as directory:
                transport = SimulatedSerial()
                transport.stuck_hv = stuck
                config_path = Path(directory) / 'config.yaml'
                config_path.write_text(yaml.safe_dump({
                    'devices': [{'id': 1, 'type': 'serial_hv', 'connection': '/dev/simulated'}],
                    'test_mode': {'enabled': False},
                }))
                with patch.object(sys, 'argv', ['main.py', '--config', str(config_path)]), \
                        patch('modules.hamahoto_module.serial.Serial', return_value=transport), \
                        patch.dict(hardware_manager.DEVICE_PORTS, {}, clear=True), \
                        patch.dict(hardware_manager.PORT_VOLTAGE_LIMITS_V, {}, clear=True), \
                        patch.object(hardware_manager, 'DEVICE_MAPPINGS', {}), \
                        patch.object(hardware_manager, 'IS_TEST_MODE', True), \
                        patch.object(db_measurements, 'init_database_connection'), \
                        patch.object(db_measurements, 'init_db'), \
                        patch.object(db_logs, 'init_database_connection'), \
                        patch.object(db_logs, 'init_db'), \
                        patch('uvicorn.run') as server:
                    if stuck:
                        with self.assertRaises(SystemExit) as raised:
                            runpy.run_path('main.py', run_name='__main__')
                        self.assertEqual(raised.exception.code, 1)
                        server.assert_not_called()
                    else:
                        runpy.run_path('main.py', run_name='__main__')
                        server.assert_called_once()
                        self.assertEqual(transport.status & 0x41, 0)


class EndOfTasks(Exception):
    pass


class SerialResetTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('modules.hamahoto_module.time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.transport = SimulatedSerial(SAFE_PARAMETERS)
        self.communicator = SerialCommunicator('/dev/mockHV', is_test_mode=True)
        self.communicator.is_test_mode = False
        self.communicator.ser = self.transport

    def test_reset_leaves_output_and_correction_off_without_hardware_reset(self):
        self.assertEqual(self.communicator.reset_device(), b'OK_SAFE_INITIALIZED')
        self.assertEqual(self.transport.status & 0x41, 0)
        self.assertEqual(self.transport.commands, [b'HOF', b'HCM0', b'HGS', b'HRT', b'HGS'])

    def test_reset_restores_safe_parameters_only_when_needed(self):
        self.transport.parameters = OLD_PARAMETERS
        self.assertEqual(self.communicator.reset_device(), b'OK_SAFE_INITIALIZED')
        self.assertEqual(self.transport.parameters, SAFE_PARAMETERS)
        self.assertEqual(self.transport.commands, [
            b'HOF', b'HCM0', b'HGS', b'HRT', b'HST' + SAFE_PARAMETERS, b'HRT', b'HGS',
        ])

    def test_failed_reset_attempts_off_and_returns_error(self):
        self.transport.stuck_correction = True
        self.assertTrue(self.communicator.reset_device().startswith(b'ERROR:'))
        self.assertEqual(self.transport.commands, [b'HOF', b'HCM0', b'HGS', b'HOF'])

    def test_worker_records_reset_failure_and_processes_next_command(self):
        self.transport.stuck_correction = True
        queue = Mock()
        queue.get.side_effect = [
            {'port_id': 1, 'command_info': {'command_type': 'RESET'}},
            {'port_id': 1, 'command_info': {'command_type': 'RAW', 'raw_command': 'HOF'}},
            EndOfTasks(),
        ]
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: self.communicator}, clear=True), \
                patch.object(db_logs, 'save_action_log') as action_log:
            with self.assertRaises(EndOfTasks):
                hardware_manager.worker(queue)
        first, second = action_log.call_args_list
        self.assertEqual(first.args[1], 'RESET')
        self.assertTrue(first.args[2].startswith(b'ERROR:'))
        self.assertEqual(second.args[1], 'RAW: HOF')
        self.assertEqual(queue.task_done.call_count, 2)
        self.assertNotIn(b'HRE', self.transport.commands)

    def test_mock_reset_does_not_access_serial_hardware(self):
        communicator = SerialCommunicator('/dev/mockHV', is_test_mode=True)
        with patch('modules.hamahoto_module.serial.Serial', side_effect=AssertionError('hardware access')):
            self.assertEqual(communicator.reset_device(), b'OK_SAFE_INITIALIZED_MOCK')


if __name__ == '__main__':
    unittest.main()
