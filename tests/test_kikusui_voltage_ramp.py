import unittest
from unittest.mock import Mock, patch

import main
from modules import hardware_manager as hw
from modules.kikusui_module import KikusuiCommunicator


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []
        self.on_sleep = None
        self.early_returns = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.on_sleep:
            self.on_sleep()
        self.now += seconds / 2 if self.early_returns else seconds
        if self.early_returns:
            self.early_returns -= 1


class Supply(KikusuiCommunicator):
    def __init__(self, clock, initial=0.0):
        self.clock = clock
        self.setting = initial
        self.on = True
        self.writes = []
        self.measured_override = None
        self.monitor_delay = 0.0
        self.write_delay = 0.0
        self.read_delay = 0.0
        self.write_result = b'OK'
        self.readback_error = None
        self.bad_readback = None
        self.monitor_error = False
        self.output_error = False

    def monitor(self):
        self.clock.now += self.monitor_delay
        if self.monitor_error and self.writes:
            return {'error': 'monitor failed'}
        voltage = self.setting if self.measured_override is None else self.measured_override
        return {'voltage': voltage, 'is_on': self.on}

    def get_voltage_setpoint(self):
        self.clock.now += self.read_delay
        if self.writes and self.readback_error:
            raise self.readback_error
        if self.writes and self.bad_readback is not None:
            return self.bad_readback
        return self.setting

    def get_output_state(self):
        if self.output_error:
            raise ValueError('bad output state')
        return self.on

    def set_voltage(self, voltage):
        self.writes.append((self.clock.now, voltage))
        self.clock.now += self.write_delay
        self.setting = voltage
        return self.write_result


class KikusuiVoltageRampTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.supply = Supply(self.clock)
        for patcher in (
            patch.object(hw.time, 'monotonic', self.clock.monotonic),
            patch.object(hw.time, 'sleep', self.clock.sleep),
            patch.object(hw.database, 'save_monitor_data'),
            patch.object(hw, 'log'),
            patch.dict(hw.DEVICE_MAPPINGS, {}, clear=True),
            patch.dict(hw.DEVICE_PORTS, {}, clear=True),
            patch.dict(hw.PORT_VOLTAGE_LIMITS_V, {}, clear=True),
            patch.object(hw, 'RAMP_VOLTAGE_MAX_STEP_V', 2.5),
            patch.object(hw, 'RAMP_PAD_STEP_TO_TARGET_RATE', False),
            patch.object(hw, 'KIKUSUI_RAMP_UP_MAX_V_PER_S', 2.0),
            patch.object(hw, 'KIKUSUI_RAMP_DOWN_MAX_V_PER_S', 4.0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ramp(self, target, requested_rate=5.0):
        return hw.run_adaptive_voltage_ramp(0, self.supply, target, requested_rate)

    def assert_rate_bound(self, initial, rate, start=0.0):
        previous_time, previous_value = start, initial
        for timestamp, value in self.supply.writes:
            self.assertGreaterEqual(timestamp - previous_time + 1e-8,
                                    abs(value - previous_value) / rate)
            previous_time, previous_value = timestamp, value

    def test_fast_link_needs_at_least_30_seconds_to_reach_60_volts(self):
        self.assertEqual(self.ramp(60.0), b'OK')
        self.assertEqual(len(self.supply.writes), 120)
        self.assertAlmostEqual(self.supply.writes[0][0], .25)
        self.assertAlmostEqual(self.supply.writes[-1][0], 30.0)
        self.assertEqual(self.supply.setting, 60.0)
        self.assert_rate_bound(0.0, 2.0)

    def test_downward_ramp_needs_at_least_15_seconds(self):
        self.supply.setting = 60.0
        self.assertEqual(self.ramp(0.0), b'OK')
        self.assertEqual(len(self.supply.writes), 60)
        self.assertAlmostEqual(self.supply.writes[-1][0], 15.0)
        self.assert_rate_bound(60.0, 4.0)

    def test_slow_link_cannot_enlarge_steps_or_catch_up_in_a_burst(self):
        self.supply.monitor_delay = .7
        self.supply.write_delay = .03
        self.supply.read_delay = .02
        self.assertEqual(self.ramp(3.0), b'OK')
        values = [0.0] + [value for _, value in self.supply.writes]
        self.assertTrue(all(b - a <= .5 + 1e-8 for a, b in zip(values, values[1:])))
        self.assert_rate_bound(0.0, 2.0)

    def test_monitoring_stall_does_not_increase_following_steps(self):
        original = self.supply.monitor
        def monitor():
            result = original()
            if len(self.supply.writes) == 1:
                self.clock.now += 5.0
            return result
        self.supply.monitor = monitor
        self.assertEqual(self.ramp(2.0), b'OK')
        self.assertEqual([value for _, value in self.supply.writes], [.5, 1., 1.5, 2.])
        self.assert_rate_bound(0.0, 2.0)

    def test_stale_measurement_cannot_reset_the_retained_setting(self):
        self.supply.setting = 20.0
        self.supply.measured_override = 0.0
        self.assertEqual(self.ramp(21.0), b'OK')
        self.assertEqual([value for _, value in self.supply.writes], [20.5, 21.0])
        self.assert_rate_bound(20.0, 2.0)

    def test_wait_is_rechecked_if_sleep_returns_early(self):
        self.clock.early_returns = 2
        self.assertEqual(self.ramp(.5), b'OK')
        self.assertEqual(len(self.clock.sleeps), 3)
        self.assert_rate_bound(0.0, 2.0)

    def test_output_off_during_wait_prevents_the_next_increase(self):
        self.clock.on_sleep = lambda: setattr(self.supply, 'on', False)
        self.assertEqual(self.ramp(1.0), b'ERROR:OUTPUT_NOT_ON')
        self.assertEqual(self.supply.writes, [])

    def test_unknown_output_state_prevents_the_next_increase(self):
        self.supply.output_error = True
        self.assertEqual(self.ramp(1.0), b'ERROR:OUTPUT_STATE_UNKNOWN')
        self.assertEqual(self.supply.writes, [])

    def test_readback_mismatch_or_failure_stops_after_one_write(self):
        for bad in (0.0, .499, float('nan'), float('inf')):
            with self.subTest(bad=bad):
                self.supply = Supply(self.clock)
                self.supply.bad_readback = bad
                self.assertEqual(self.ramp(1.0), b'ERROR:SETPOINT_READBACK_MISMATCH')
                self.assertEqual(len(self.supply.writes), 1)
        self.supply = Supply(self.clock)
        self.supply.readback_error = ValueError('timeout')
        self.assertEqual(self.ramp(1.0), b'ERROR:SETPOINT_READ_FAILED')
        self.assertEqual(len(self.supply.writes), 1)

    def test_write_and_monitor_failures_stop_following_steps(self):
        self.supply.write_result = b'ERROR:WRITE_FAILED'
        self.assertEqual(self.ramp(1.0), b'ERROR:WRITE_FAILED')
        self.assertEqual(len(self.supply.writes), 1)
        self.supply = Supply(self.clock)
        self.supply.monitor_error = True
        self.assertEqual(self.ramp(1.0), b'ERROR:MONITOR_FAILED')
        self.assertEqual(len(self.supply.writes), 1)

    def test_lower_requested_rate_and_smaller_step_limit_are_respected(self):
        with patch.object(hw, 'RAMP_VOLTAGE_MAX_STEP_V', .1):
            self.assertEqual(self.ramp(1.0, requested_rate=.5), b'OK')
        self.assert_rate_bound(0.0, .5)
        self.assertGreaterEqual(self.supply.writes[-1][0], 2.0 - 1e-8)

    def test_target_limit_and_invalid_config_prevent_writes(self):
        with patch.dict(hw.PORT_VOLTAGE_LIMITS_V, {0: .5}):
            self.assertTrue(self.ramp(1.0).startswith(b'ERROR:'))
        self.assertEqual(self.supply.writes, [])
        for value in (0, -1, float('nan'), float('inf')):
            with patch.object(hw, 'KIKUSUI_RAMP_UP_MAX_V_PER_S', value):
                self.assertEqual(self.ramp(1.0), b'ERROR:INVALID_KIKUSUI_RAMP_RATE')
        self.assertEqual(self.supply.writes, [])

    def test_noop_uses_retained_setpoint_and_never_writes(self):
        self.supply.setting = 20.0
        self.supply.measured_override = 0.0
        self.assertEqual(self.ramp(20.0), b'OK_NOOP')
        self.assertEqual(self.supply.writes, [])

    def test_fractional_start_and_final_partial_step_obey_the_rate(self):
        self.supply.setting = 20.0006
        self.assertEqual(self.ramp(21.123), b'OK')
        self.assert_rate_bound(20.0006, 2.0)
        self.assertLessEqual(self.supply.setting, 21.123)

    def test_adapter_output_query_rejects_malformed_responses(self):
        with patch('modules.kikusui_module.log'):
            communicator = KikusuiCommunicator('mock', True)
        for response, expected in ((b'0', False), (b'1', True)):
            with patch.object(communicator, '_query', return_value=response):
                self.assertIs(communicator.get_output_state(), expected)
        for response in (b'', b'2', b'ON', b'ERROR:QUERY_FAILED'):
            with patch.object(communicator, '_query', return_value=response):
                with self.assertRaises(ValueError):
                    communicator.get_output_state()

    def test_config_rejects_nonpositive_or_nonfinite_kikusui_rates(self):
        saved = {name: value for name, value in vars(hw).items()
                 if name.startswith(('RAMP_', 'KIKUSUI_RAMP_', 'VOLTAGE_EQ_', 'REQUIRE_ON_'))}
        for key in ('kikusui_ramp_up_max_v_per_s', 'kikusui_ramp_down_max_v_per_s'):
            for value in (0, -1, float('nan'), float('inf')):
                with patch.multiple(hw, **saved):
                    with self.assertRaises(ValueError):
                        main._apply_hardware_manager_settings({key: value})
