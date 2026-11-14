from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import Mock, patch

import pyvisa

from modules import hardware_manager
from modules.kikusui_module import KikusuiCommunicator


class EndOfTasks(Exception):
    pass


class KikusuiResetTests(unittest.TestCase):
    def setUp(self):
        with redirect_stdout(io.StringIO()):
            self.communicator = KikusuiCommunicator('mock', True)
        self.communicator.is_test_mode = False
        self.instrument = Mock()
        self.communicator.instrument = self.instrument

    def test_reset_clears_only_alarm_and_preserves_on_off_and_settings(self):
        for on in (True, False):
            with self.subTest(on=on):
                state = {'on': on, 'voltage': 56.0, 'current_limit': .02,
                         'ovp': 60.0, 'ocp': .03, 'ocp_enabled': True, 'alarm': not on}
                expected = {**state, 'alarm': False}

                def write(command):
                    self.assertEqual(command, 'OUTPut:PROTection:CLEar')
                    state['alarm'] = False

                self.instrument.reset_mock()
                self.instrument.write.side_effect = write
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(self.communicator.reset_device(), b'OK')
                self.instrument.write.assert_called_once_with('OUTPut:PROTection:CLEar')
                self.instrument.query.assert_not_called()
                self.assertEqual(state, expected)

    def test_failed_alarm_clear_never_falls_back_to_full_reset(self):
        self.instrument.write.side_effect = pyvisa.errors.VisaIOError(-1073807339)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.communicator.reset_device(), b'ERROR:VISA_WRITE_FAILED')
        self.instrument.write.assert_called_once_with('OUTPut:PROTection:CLEar')
        self.instrument.query.assert_not_called()

    def test_worker_reset_and_clear_trip_share_the_nondestructive_command(self):
        for command in ('RESET', 'CLEAR_TRIP'):
            with self.subTest(command=command):
                self.instrument.reset_mock()
                queue = Mock()
                queue.get.side_effect = [
                    {'port_id': 0, 'command_info': {'command_type': command}}, EndOfTasks()]
                with patch.dict(hardware_manager.DEVICE_PORTS, {0: self.communicator}, clear=True), \
                        patch.object(hardware_manager.log_database, 'save_action_log') as action, \
                        redirect_stdout(io.StringIO()):
                    with self.assertRaises(EndOfTasks):
                        hardware_manager.worker(queue)
                self.instrument.write.assert_called_once_with('OUTPut:PROTection:CLEar')
                self.assertEqual(action.call_args.args[1:], (command, b'OK'))
                queue.task_done.assert_called_once()

    def test_mock_reset_preserves_running_voltage_and_protection_settings(self):
        with redirect_stdout(io.StringIO()):
            communicator = KikusuiCommunicator('mock', True)
            communicator.turn_on()
            communicator.set_voltage(40.0)
            communicator.set_current(.02)
            communicator.enable_ocp(.03)
            self.assertEqual(communicator.reset_device(), b'OK_TRIP_CLEAR')
            reading = communicator.monitor()
        self.assertTrue(reading['is_on'])
        self.assertEqual(reading['voltage'], 40.0)
        self.assertEqual(communicator._mock_current_limit_a, .02)
        self.assertTrue(communicator._mock_ocp_enabled)
        self.assertEqual(communicator._mock_ocp_level_a, .03)


if __name__ == '__main__':
    unittest.main()
