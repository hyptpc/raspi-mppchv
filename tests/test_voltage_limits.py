import asyncio
from queue import Queue
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

import main
from modules import hardware_manager
from modules.hamahoto_module import SerialCommunicator
from modules.kikusui_module import KikusuiCommunicator


class EndOfTasks(Exception):
    pass


class VoltageLimitTests(unittest.TestCase):
    def setUp(self):
        self.serial = SerialCommunicator('/dev/mockHV', True)
        self.kikusui = KikusuiCommunicator('mock', True)
        for patcher in (patch.dict(hardware_manager.DEVICE_PORTS, {1: self.serial, 2: self.kikusui}, clear=True),
                        patch.dict(hardware_manager.PORT_VOLTAGE_LIMITS_V, {}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_serial_rejects_out_of_range_values_before_sending(self):
        with patch.object(self.serial, '_send_and_receive') as send:
            for value in (0, 19.999, 90.001, float('nan'), float('inf'), -1):
                with self.subTest(value=value):
                    self.assertTrue(self.serial.set_voltage(value).startswith(b'ERROR:'))
            send.assert_not_called()

    def test_serial_boundary_encoding_stays_within_physical_range(self):
        for value in (20.0, 20.5, 90.0):
            with self.subTest(value=value), patch.object(self.serial, '_send_and_receive', return_value=b'OK') as send:
                self.assertEqual(self.serial.set_voltage(value), b'OK')
                command = send.call_args.args[0]
                actual = int(command[3:], 16) * self.serial.CONV_FACTOR_VOLT
                self.assertGreaterEqual(actual, 20.0)
                self.assertLessEqual(actual, 90.0)
                self.assertEqual(command, command.upper())

    def test_api_rejects_invalid_serial_voltage_without_queuing(self):
        queue = Queue()
        with patch.object(main, 'command_queue', queue):
            for value in (0.0, 19.9, 90.1):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(main.queue_structured_command(main.StructuredCommand(
                        port_id=1, command_type='SET_VOLTAGE', value=value)))
                self.assertEqual(raised.exception.status_code, 422)
                self.assertTrue(queue.empty())

    def test_kikusui_allows_zero_and_configured_limits_are_strict(self):
        self.assertTrue(hardware_manager.check_max_voltage_allowed(2, 0.0)[0])
        hardware_manager.PORT_VOLTAGE_LIMITS_V[1] = 58.5
        self.assertTrue(hardware_manager.check_max_voltage_allowed(1, 58.5)[0])
        self.assertFalse(hardware_manager.check_max_voltage_allowed(1, 58.5001)[0])
        hardware_manager.PORT_VOLTAGE_LIMITS_V[1] = float('nan')
        self.assertFalse(hardware_manager.check_max_voltage_allowed(1, 55.0)[0])

    def run_worker(self, port_id, command, value=None):
        queue = Mock()
        queue.get.side_effect = [{'port_id': port_id, 'command_info': {'command_type': command, 'value': value}}, EndOfTasks()]
        with patch.object(hardware_manager, 'run_adaptive_voltage_ramp', return_value=b'OK') as ramp, \
                patch.object(hardware_manager, 'monitor_primary_then_save_combined'), \
                patch.object(hardware_manager.log_database, 'save_action_log') as action:
            with self.assertRaises(EndOfTasks):
                hardware_manager.worker(queue)
        return ramp, action

    def test_worker_rejects_invalid_serial_voltage_before_monitoring(self):
        with patch.object(self.serial, 'monitor') as monitor:
            ramp, _ = self.run_worker(1, 'SET_VOLTAGE', 10.0)
        monitor.assert_not_called()
        ramp.assert_not_called()

    def test_turn_on_respects_limit_below_start_voltage(self):
        hardware_manager.PORT_VOLTAGE_LIMITS_V[1] = 20.0
        with patch.object(self.serial, 'turn_on') as on:
            _, action = self.run_worker(1, 'TURN_ON')
        on.assert_not_called()
        self.assertTrue(action.call_args.args[2].startswith(b'ERROR:TURN_ON'))

    def test_shutdown_floor_is_selected_for_each_device(self):
        for port, communicator, floor in ((1, self.serial, 20.5), (2, self.kikusui, 0.0)):
            with self.subTest(port=port), patch.object(communicator, 'monitor', return_value={'voltage': 50.0}), \
                    patch.object(communicator, 'turn_off', return_value=b'OK_OFF'):
                ramp, _ = self.run_worker(port, 'TURN_OFF')
            self.assertEqual(ramp.call_args.args[2], floor)


if __name__ == '__main__':
    unittest.main()
