import itertools
import unittest
from unittest.mock import Mock, call, patch

from modules import hardware_manager


class EndOfTasks(Exception):
    pass


def reading(voltage=2.0, is_on=True):
    return {'voltage': voltage, 'is_on': is_on}


class VoltageRampTests(unittest.TestCase):
    def setUp(self):
        self.communicator = Mock(ser=True)
        self.communicator.set_voltage.return_value = b'OK'
        patches = [
            patch.object(hardware_manager.database, 'save_monitor_data'),
            patch.object(hardware_manager, 'log'),
            patch.dict(hardware_manager.DEVICE_MAPPINGS, {}, clear=True),
            patch.object(hardware_manager, 'RAMP_VOLTAGE_DEFAULT_CYCLE_S', 0.1),
            patch.object(hardware_manager, 'RAMP_VOLTAGE_CYCLE_EWMA_ALPHA', 1.0),
            patch.object(hardware_manager, 'RAMP_VOLTAGE_MAX_STEP_V', 0.5),
            patch.object(hardware_manager, 'RAMP_PAD_STEP_TO_TARGET_RATE', False),
            patch.object(hardware_manager.time, 'perf_counter', side_effect=itertools.count(0, 0.1)),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def ramp(self, monitors, target=3.0):
        self.communicator.monitor.side_effect = monitors
        return hardware_manager.run_adaptive_voltage_ramp(1, self.communicator, target, 5.0)

    def test_successful_ramp_writes_each_step(self):
        result = self.ramp([reading(), reading(2.5), reading(3.0)])
        self.assertEqual(result, b'OK')
        self.assertEqual(self.communicator.set_voltage.call_args_list, [call(2.5), call(3.0)])

    def test_failed_or_empty_write_stops_before_monitoring_or_next_write(self):
        for response in (b'ERROR:SERIAL_COMM_FAILED', b''):
            with self.subTest(response=response):
                self.communicator.reset_mock()
                self.communicator.set_voltage.return_value = response
                result = self.ramp([reading(), reading(2.5), reading(3.0)])
                self.assertTrue(result.startswith(b'ERROR:'))
                self.communicator.set_voltage.assert_called_once_with(2.5)
                self.assertEqual(self.communicator.monitor.call_count, 1)

    def test_monitor_errors_stop_ramp_even_after_final_write(self):
        for monitors, write_count in (
                ([{'error': 'timeout'}], 0),
                ([reading(), {'error': 'timeout'}], 1),
                ([reading(), reading(2.5), {'error': 'timeout'}], 2)):
            with self.subTest(write_count=write_count):
                self.communicator.reset_mock()
                result = self.ramp(monitors)
                self.assertEqual(result, b'ERROR:MONITOR_FAILED')
                self.assertEqual(self.communicator.set_voltage.call_count, write_count)

    def test_missing_voltage_stops_ramp(self):
        for monitors, write_count in (([{'is_on': True}], 0),
                                      ([reading(), {'is_on': True}], 1)):
            with self.subTest(write_count=write_count):
                self.communicator.reset_mock()
                self.assertEqual(self.ramp(monitors), b'ERROR:NO_VOLTAGE')
                self.assertEqual(self.communicator.set_voltage.call_count, write_count)

    def test_ramp_up_requires_output_on_at_start_and_after_each_step(self):
        off_states = [reading(is_on=False), {'voltage': 2.0},
                      {'voltage': 2.0, 'status_flags': {'is_hv_on': False}}]
        for state in off_states:
            for monitors, write_count in (([state], 0), ([reading(), state], 1)):
                with self.subTest(state=state, write_count=write_count):
                    self.communicator.reset_mock()
                    result = self.ramp(monitors)
                    self.assertEqual(result, b'ERROR:OUTPUT_NOT_ON')
                    self.assertEqual(self.communicator.set_voltage.call_count, write_count)

    def test_serial_output_on_flags_allow_ramp_up(self):
        monitors = [{'voltage': voltage, 'status_flags': {'is_hv_on': True}}
                    for voltage in (2.0, 2.5, 3.0)]
        self.assertEqual(self.ramp(monitors), b'OK')

    def test_ramp_down_is_allowed_with_output_off(self):
        self.assertEqual(self.ramp([reading(2.0, False), reading(1.5, False),
                                    reading(1.0, False)], target=1.0), b'OK')
        self.assertEqual(self.communicator.set_voltage.call_args_list, [call(1.5), call(1.0)])

    def test_noop_still_reports_monitor_failure(self):
        result = self.ramp([reading(), {'error': 'timeout'}], target=2.0)
        self.assertEqual(result, b'ERROR:MONITOR_FAILED')
        self.communicator.set_voltage.assert_not_called()

    def test_write_exception_stops_before_next_step(self):
        self.communicator.set_voltage.side_effect = RuntimeError('write failed')
        with self.assertRaisesRegex(RuntimeError, 'write failed'):
            self.ramp([reading()])
        self.communicator.set_voltage.assert_called_once_with(2.5)

    def test_nonfinite_monitoring_stops_before_another_write(self):
        for value in (float('nan'), float('inf'), float('-inf'), 'invalid'):
            for monitors, count in (([reading(value)], 0), ([reading(), reading(value)], 1)):
                with self.subTest(value=value, count=count):
                    self.communicator.reset_mock()
                    self.assertEqual(self.ramp(monitors), b'ERROR:INVALID_VOLTAGE')
                    self.assertEqual(self.communicator.set_voltage.call_count, count)

    def test_invalid_rates_and_targets_do_not_access_hardware(self):
        for rate in (0, -1, float('nan'), float('inf')):
            self.assertEqual(hardware_manager.run_adaptive_voltage_ramp(
                1, self.communicator, 3.0, rate), b'ERROR:INVALID_RAMP_RATE')
        for target in (-1, float('nan'), float('inf')):
            self.assertEqual(hardware_manager.run_adaptive_voltage_ramp(
                1, self.communicator, target, 5.0), b'ERROR:INVALID_TARGET_VOLTAGE')
        self.communicator.monitor.assert_not_called()
        self.communicator.set_voltage.assert_not_called()

    def test_disabling_on_requirement_does_not_accept_monitor_errors(self):
        with patch.object(hardware_manager, 'REQUIRE_ON_FOR_VOLTAGE_INCREASE', False):
            for sample in ({'error': 'timeout'}, reading(float('nan')), {'is_on': True}):
                self.assertFalse(hardware_manager.check_set_voltage_safety(sample, 3.0)[0])

    def test_worker_does_not_log_failed_ramp_as_complete(self):
        for result in (b'ERROR:MONITOR_FAILED', b'OK'):
            with self.subTest(result=result):
                self.communicator.monitor.side_effect = None
                self.communicator.monitor.return_value = reading()
                queue = Mock()
                queue.get.side_effect = [
                    {'port_id': 1, 'command_info': {'command_type': 'SET_VOLTAGE', 'value': 3.0}},
                    EndOfTasks(),
                ]
                with patch.dict(hardware_manager.DEVICE_PORTS, {1: self.communicator}, clear=True), \
                        patch.dict(hardware_manager.PORT_VOLTAGE_LIMITS_V, {}, clear=True), \
                        patch.object(hardware_manager, 'run_adaptive_voltage_ramp', return_value=result), \
                        patch.object(hardware_manager, 'log') as log, \
                        patch.object(hardware_manager.log_database, 'save_action_log') as action_log:
                    with self.assertRaises(EndOfTasks):
                        hardware_manager.worker(queue)
                complete = [args for args, _ in log.call_args_list if 'complete' in args[1]]
                self.assertEqual(bool(complete), result == b'OK')
                self.assertEqual(action_log.call_args.args[2], result)
                self.assertFalse(hardware_manager.is_system_busy)
                queue.task_done.assert_called_once()


if __name__ == '__main__':
    unittest.main()
