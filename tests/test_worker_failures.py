import unittest
from unittest.mock import Mock, call, patch

from modules import hardware_manager


class EndOfTasks(Exception):
    """Stop the worker after all test tasks have been consumed."""


class WorkerFailureTests(unittest.TestCase):
    def check_worker_continues(self, first_command, communicator):
        next_command = {'command_type': 'RAW', 'raw_command': 'HOF'}
        queue = Mock()
        queue.get.side_effect = [
            {'port_id': 1, 'command_info': first_command},
            {'port_id': 1, 'command_info': next_command},
            EndOfTasks(),
        ]
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: communicator}, clear=True), \
                patch.object(hardware_manager, 'is_system_busy', False), \
                patch.object(hardware_manager.log_database, 'save_action_log',
                             side_effect=RuntimeError('database unavailable')), \
                patch.object(hardware_manager, 'log') as log:
            with self.assertRaises(EndOfTasks):
                hardware_manager.worker(queue)
            self.assertFalse(hardware_manager.is_system_busy)
        self.assertEqual(queue.task_done.call_count, 2)
        self.assertIn(call('HOF'), communicator.send_raw_command.call_args_list)
        self.assertTrue(any('database unavailable' in args[1]
                            for args, _ in log.call_args_list if args[0] == 'ERROR'))

    def test_communication_failure_and_error_log_failure_do_not_stop_worker(self):
        communicator = Mock(ser=True)
        communicator.send_raw_command.side_effect = [
            RuntimeError('communication failed'), b'\x02hof\x0342\r',
        ]
        self.check_worker_continues(
            {'command_type': 'RAW', 'raw_command': 'HGS'}, communicator,
        )
        self.assertEqual(communicator.send_raw_command.call_count, 2)

    def test_successful_command_with_log_failure_does_not_stop_worker(self):
        communicator = Mock(ser=True)
        communicator.send_raw_command.return_value = b'\x02hof\x0342\r'
        self.check_worker_continues(
            {'command_type': 'RAW', 'raw_command': 'HOF'}, communicator,
        )
        self.assertEqual(communicator.send_raw_command.call_count, 2)

    def test_blocking_command_failure_clears_busy_state_despite_log_failure(self):
        communicator = Mock(ser=True)
        communicator.monitor.side_effect = RuntimeError('monitor failed')
        communicator.send_raw_command.return_value = b'\x02hof\x0342\r'
        self.check_worker_continues({'command_type': 'TURN_OFF'}, communicator)


if __name__ == '__main__':
    unittest.main()
