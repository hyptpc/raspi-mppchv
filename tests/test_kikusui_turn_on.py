import asyncio
from contextlib import redirect_stdout
import io
from queue import Queue
import unittest
from unittest.mock import Mock, patch

import pyvisa

import main
from modules import hardware_manager
from modules.kikusui_module import KikusuiCommunicator


class EndOfTasks(Exception):
    pass


class KikusuiTurnOnTests(unittest.TestCase):
    def setUp(self):
        with redirect_stdout(io.StringIO()):
            self.communicator = KikusuiCommunicator('mock', True)
        self.communicator.is_test_mode = False
        self.state = {'setpoint': 85.0, 'on': False}
        self.events = []
        self.instrument = Mock()
        self.communicator.instrument = self.instrument

        def query(command):
            self.assertTrue(hardware_manager.get_port_lock(0).locked())
            self.events.append(('query', command))
            if command == 'OUTPut:STATe?':
                return str(int(self.state['on']))
            if command == 'SOURce:VOLTage?':
                return str(self.state['setpoint'])
            if command == 'MEASure:VOLTage?':
                return str(self.state['setpoint'] if self.state['on'] else 0.0)
            raise AssertionError(f'Unexpected query: {command}')

        def write(command):
            self.assertTrue(hardware_manager.get_port_lock(0).locked())
            self.events.append(('write', command))
            if command == 'SOURce:VOLTage 0.000':
                self.state['setpoint'] = 0.0
            elif command == 'OUTPut:STATe ON':
                self.state['on'] = True
            else:
                raise AssertionError(f'Unexpected write: {command}')

        self.instrument.query.side_effect = query
        self.instrument.write.side_effect = write
        for patcher in (patch.dict(hardware_manager.DEVICE_PORTS, {0: self.communicator}, clear=True),
                        patch.dict(hardware_manager.PORT_VOLTAGE_LIMITS_V, {0: 5.0}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_on(self, task=None):
        queue = Mock()
        queue.get.side_effect = [task or {'port_id': 0, 'command_info': {'command_type': 'TURN_ON'}}, EndOfTasks()]
        with patch.object(hardware_manager.log_database, 'save_action_log') as action, \
                patch.object(hardware_manager, 'log'), redirect_stdout(io.StringIO()):
            with self.assertRaises(EndOfTasks):
                hardware_manager.worker(queue)
        queue.task_done.assert_called_once()
        return action.call_args.args[2]

    def test_high_retained_setting_is_zeroed_and_verified_before_on(self):
        self.assertEqual(self.run_on(), b'OK')
        self.assertEqual(self.events, [
            ('query', 'OUTPut:STATe?'), ('write', 'SOURce:VOLTage 0.000'),
            ('query', 'SOURce:VOLTage?'), ('write', 'OUTPut:STATe ON'),
        ])
        self.assertEqual(self.state, {'setpoint': 0.0, 'on': True})

    def test_zero_start_is_used_with_zero_limit_and_without_configured_limit(self):
        for limit in (0.0, None):
            with self.subTest(limit=limit):
                self.instrument.reset_mock()
                self.state.update(setpoint=85.0, on=False)
                hardware_manager.PORT_VOLTAGE_LIMITS_V.clear()
                if limit is not None:
                    hardware_manager.PORT_VOLTAGE_LIMITS_V[0] = limit
                self.assertEqual(self.run_on(), b'OK')
                self.assertEqual(self.state, {'setpoint': 0.0, 'on': True})

    def test_invalid_zero_readback_never_enables_output(self):
        responses = (b'', b'ERROR:VISA_QUERY_FAILED', b'nan', b'inf', b'-1', b'bad', b'1,2', b'\xff')
        for response in responses:
            with self.subTest(response=response), patch.object(self.communicator, '_query',
                    side_effect=[b'0', response]):
                self.instrument.reset_mock()
                self.assertTrue(self.run_on().startswith(b'ERROR:TURN_ON'))
                self.instrument.write.assert_called_once_with('SOURce:VOLTage 0.000')
                self.assertEqual(self.state, {'setpoint': 0.0, 'on': False})

    def test_already_on_supply_keeps_its_voltage_without_writes(self):
        self.state['on'] = True
        self.assertEqual(self.run_on(), b'OK_ALREADY_ON')
        self.instrument.query.assert_called_once_with('OUTPut:STATe?')
        self.instrument.write.assert_not_called()
        self.assertEqual(self.state, {'setpoint': 85.0, 'on': True})

    def test_setting_changed_while_queued_is_still_zeroed_before_on(self):
        self.state['setpoint'] = 2.0
        queue = Queue()
        with patch.object(main, 'command_queue', queue), redirect_stdout(io.StringIO()):
            asyncio.run(main.queue_structured_command(main.StructuredCommand(port_id=0, command_type='TURN_ON')))
        self.instrument.query.assert_not_called()
        self.state['setpoint'] = 85.0
        self.assertEqual(self.run_on(queue.get_nowait()), b'OK')
        self.assertEqual(self.state, {'setpoint': 0.0, 'on': True})

    def test_query_timeout_prevents_on_without_reset_or_voltage_changes(self):
        self.instrument.query.side_effect = pyvisa.errors.VisaIOError(-1073807339)
        self.assertTrue(self.run_on().startswith(b'ERROR:TURN_ON'))
        self.instrument.write.assert_not_called()
        self.assertEqual(self.state, {'setpoint': 85.0, 'on': False})

    def test_failed_zero_write_prevents_on(self):
        self.instrument.write.side_effect = pyvisa.errors.VisaIOError(-1073807339)
        self.assertTrue(self.run_on().startswith(b'ERROR:TURN_ON'))
        self.instrument.write.assert_called_once_with('SOURce:VOLTage 0.000')
        self.assertEqual(self.state, {'setpoint': 85.0, 'on': False})

    def test_ignored_zero_write_does_not_enable_retained_voltage(self):
        self.instrument.write.side_effect = None
        self.assertEqual(self.run_on(), b'ERROR:TURN_ON:ZERO_VOLTAGE_READBACK_MISMATCH')
        self.instrument.write.assert_called_once_with('SOURce:VOLTage 0.000')
        self.assertEqual(self.state, {'setpoint': 85.0, 'on': False})

    def test_invalid_configured_limit_rejects_before_any_device_io(self):
        for limit in (-1, float('nan'), float('inf')):
            with self.subTest(limit=limit):
                hardware_manager.PORT_VOLTAGE_LIMITS_V[0] = limit
                self.assertTrue(self.run_on().startswith(b'ERROR:TURN_ON'))
                self.instrument.query.assert_not_called()
                self.instrument.write.assert_not_called()

    def test_mock_starts_at_zero_and_repeated_on_keeps_running_voltage(self):
        with redirect_stdout(io.StringIO()):
            communicator = KikusuiCommunicator('mock', True)
            communicator.set_voltage(85.0)
            self.assertEqual(communicator.monitor()['voltage'], 0.0)
        self.assertEqual(communicator.get_voltage_setpoint(), 85.0)
        self.assertFalse(communicator._mock_is_on)
        with redirect_stdout(io.StringIO()):
            communicator.turn_on()
            self.assertEqual(communicator.monitor()['voltage'], 0.0)
            communicator.set_voltage(40.0)
            self.assertEqual(communicator.turn_on(), b'OK_ALREADY_ON')
            self.assertEqual(communicator.monitor()['voltage'], 40.0)


if __name__ == '__main__':
    unittest.main()
