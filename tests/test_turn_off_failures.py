import unittest
from unittest.mock import Mock, patch

from modules import hardware_manager


class EndOfTasks(Exception):
    pass


class TurnOffFailureTests(unittest.TestCase):
    def run_off(self, monitor_error=None, ramp_error=None, ramp_result=b'OK',
                off_error=None, off_result=b'OK_OFF', save_error=None,
                monitor_result=None):
        events = []
        communicator = Mock(ser=True)

        def monitor():
            events.append('monitor')
            if monitor_error:
                raise monitor_error
            return {'voltage': 50.0} if monitor_result is None else monitor_result

        def ramp(*args):
            events.append('ramp')
            if ramp_error:
                raise ramp_error
            return ramp_result

        def off():
            events.append('off')
            self.assertTrue(hardware_manager.get_port_lock(1).locked())
            if off_error:
                raise off_error
            return off_result

        def save(*args):
            events.append('save')
            if save_error:
                raise save_error
            return {'voltage': 0.0, 'is_on': False}

        def next_command(command):
            self.assertFalse(hardware_manager.is_system_busy)
            self.assertFalse(hardware_manager.get_port_lock(1).locked())
            events.append('next')
            return b'OK'

        communicator.monitor.side_effect = monitor
        communicator.turn_off.side_effect = off
        communicator.send_raw_command.side_effect = next_command
        queue = Mock()
        queue.get.side_effect = [
            {'port_id': 1, 'command_info': {'command_type': 'TURN_OFF'}},
            {'port_id': 1, 'command_info': {'command_type': 'RAW', 'raw_command': 'HGS'}},
            EndOfTasks(),
        ]
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: communicator}, clear=True), \
                patch.object(hardware_manager, 'is_system_busy', False), \
                patch.object(hardware_manager, 'run_adaptive_voltage_ramp', side_effect=ramp), \
                patch.object(hardware_manager, 'monitor_primary_then_save_combined', side_effect=save), \
                patch.object(hardware_manager.log_database, 'save_action_log') as action_log, \
                patch.object(hardware_manager, 'log') as app_log:
            with self.assertRaises(EndOfTasks):
                hardware_manager.worker(queue)
            self.assertFalse(hardware_manager.is_system_busy)
        self.assertEqual(queue.task_done.call_count, 2)
        self.assertEqual(events[-1], 'next')
        communicator.turn_off.assert_called_once()
        return events, action_log, app_log

    def test_normal_shutdown_ramps_before_off(self):
        events, action_log, _ = self.run_off()
        self.assertEqual(events, ['monitor', 'ramp', 'off', 'save', 'next'])
        self.assertEqual(action_log.call_args_list[0].args[2], b'OK_OFF')

    def test_ramp_exception_still_sends_off_and_records_failure(self):
        events, action_log, _ = self.run_off(ramp_error=RuntimeError('ramp failed'))
        self.assertEqual(events, ['monitor', 'ramp', 'off', 'save', 'next'])
        result = action_log.call_args_list[0].args[2]
        self.assertIn(b'ERROR:RAMP_DOWN_FAILED', result)
        self.assertIn(b'ramp failed', result)
        self.assertIn(b'OK_OFF', result)

    def test_initial_monitor_exception_still_sends_off(self):
        events, _, _ = self.run_off(monitor_error=RuntimeError('monitor failed'))
        self.assertEqual(events, ['monitor', 'off', 'save', 'next'])

    def test_monitor_error_response_skips_ramp_and_sends_off(self):
        events, _, _ = self.run_off(monitor_result={'error': 'No response'})
        self.assertEqual(events, ['monitor', 'off', 'save', 'next'])

    def test_voltage_below_ramp_floor_sends_off_without_voltage_writes(self):
        events, _, _ = self.run_off(monitor_result={'voltage': 1.0})
        self.assertEqual(events, ['monitor', 'off', 'save', 'next'])

    def test_ramp_error_response_still_sends_off_and_records_failure(self):
        _, action_log, _ = self.run_off(ramp_result=b'ERROR:MONITOR_FAILED')
        self.assertIn(b'ERROR:MONITOR_FAILED', action_log.call_args_list[0].args[2])

    def test_off_exception_does_not_stop_worker(self):
        events, action_log, _ = self.run_off(
            ramp_error=RuntimeError('ramp failed'), off_error=RuntimeError('OFF failed'))
        self.assertEqual(events, ['monitor', 'ramp', 'off', 'next'])
        self.assertEqual(action_log.call_args_list[0].args[1], 'ERROR executing TURN_OFF')
        self.assertIn(b'OFF failed', action_log.call_args_list[0].args[2])

    def test_off_error_response_is_reported(self):
        _, action_log, app_log = self.run_off(off_result=b'ERROR:SERIAL_COMM_FAILED')
        self.assertIn(b'ERROR:SERIAL_COMM_FAILED', action_log.call_args_list[0].args[2])
        self.assertTrue(any(args[0] == 'ERROR' and 'OFF' in args[1]
                            for args, _ in app_log.call_args_list))

    def test_post_off_save_failure_does_not_repeat_off_or_stop_worker(self):
        events, _, _ = self.run_off(save_error=RuntimeError('database unavailable'))
        self.assertEqual(events, ['monitor', 'ramp', 'off', 'save', 'next'])


if __name__ == '__main__':
    unittest.main()
