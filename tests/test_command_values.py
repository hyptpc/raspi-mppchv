import asyncio
from queue import Queue
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

import main
from modules import hardware_manager


class EndOfTasks(Exception):
    pass


class CommandValueTests(unittest.TestCase):
    def setUp(self):
        self.communicator = Mock(spec=['ser', 'monitor', 'set_voltage', 'set_current',
                                       'enable_ocp', 'send_raw_command'], ser=True)
        self.communicator.monitor.return_value = {'voltage': 50.0, 'is_on': True}
        self.communicator.send_raw_command.return_value = b'OK'
        self.queue = Queue()
        for patcher in (
                patch.dict(hardware_manager.DEVICE_PORTS, {1: self.communicator}, clear=True),
                patch.dict(hardware_manager.PORT_VOLTAGE_LIMITS_V, {}, clear=True),
                patch.object(main, 'command_queue', self.queue),
                patch.object(main, 'log')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def queue_command(self, command, value):
        request = main.StructuredCommand(port_id=1, command_type=command, value=value)
        return asyncio.run(main.queue_structured_command(request))

    def assert_no_hardware_calls(self):
        for method in ('monitor', 'set_voltage', 'set_current', 'enable_ocp'):
            getattr(self.communicator, method).assert_not_called()

    def test_api_rejects_nonfinite_and_negative_values_without_queuing(self):
        for command in ('SET_VOLTAGE', 'SET_CURRENT', 'ENABLE_OCP'):
            for value in (float('nan'), float('inf'), float('-inf'), -1.0):
                with self.subTest(command=command, value=value):
                    with self.assertRaises(HTTPException) as raised:
                        self.queue_command(command, value)
                    self.assertEqual(raised.exception.status_code, 422)
                    self.assertTrue(self.queue.empty())
                    self.assert_no_hardware_calls()

    def test_api_still_rejects_missing_values(self):
        for command in ('SET_VOLTAGE', 'SET_CURRENT', 'ENABLE_OCP'):
            with self.subTest(command=command):
                with self.assertRaises(HTTPException) as raised:
                    self.queue_command(command, None)
                self.assertEqual(raised.exception.status_code, 400)
                self.assertTrue(self.queue.empty())

    def test_api_accepts_valid_values_and_zero_current(self):
        for command, value in (('SET_VOLTAGE', 55.0), ('SET_CURRENT', 0.0),
                               ('SET_CURRENT', 0.1), ('ENABLE_OCP', 0.1)):
            with self.subTest(command=command, value=value):
                self.assertEqual(self.queue_command(command, value)['status'], 'success')
                task = self.queue.get_nowait()
                self.assertEqual(task['command_info']['value'], value)
        self.assert_no_hardware_calls()

    def test_api_rejects_zero_ocp_and_unsupported_disable_without_queuing(self):
        for command, value in (('ENABLE_OCP', 0.0), ('DISABLE_OCP', None)):
            with self.subTest(command=command):
                with self.assertRaises(HTTPException) as raised:
                    self.queue_command(command, value)
                self.assertEqual(raised.exception.status_code, 422)
                self.assertTrue(self.queue.empty())
                self.assert_no_hardware_calls()

    def test_worker_rejects_invalid_values_even_when_api_is_bypassed(self):
        for command in ('SET_VOLTAGE', 'SET_CURRENT', 'ENABLE_OCP'):
            for value in (float('nan'), float('inf'), float('-inf'), -1.0, None, 'invalid'):
                with self.subTest(command=command, value=value):
                    self.communicator.reset_mock()
                    queue = Mock()
                    queue.get.side_effect = [
                        {'port_id': 1, 'command_info': {'command_type': command, 'value': value}},
                        {'port_id': 1, 'command_info': {'command_type': 'RAW', 'raw_command': 'HGS'}},
                        EndOfTasks(),
                    ]
                    with patch.object(hardware_manager, 'run_adaptive_voltage_ramp', return_value=b'OK') as ramp, \
                            patch.object(hardware_manager.log_database, 'save_action_log') as action_log, \
                            patch.object(hardware_manager, 'log'):
                        with self.assertRaises(EndOfTasks):
                            hardware_manager.worker(queue)
                    self.assert_no_hardware_calls()
                    ramp.assert_not_called()
                    self.communicator.send_raw_command.assert_called_once_with('HGS')
                    self.assertEqual(action_log.call_args_list[0].args[1], f'ERROR executing {command}')
                    self.assertFalse(hardware_manager.is_system_busy)
                    self.assertEqual(queue.task_done.call_count, 2)


if __name__ == '__main__':
    unittest.main()
