import unittest
from unittest.mock import patch

from modules.hamahoto_module import SerialCommunicator


class SerialTurnOnTests(unittest.TestCase):
    def setUp(self):
        self.communicator = SerialCommunicator('/dev/mockHV', True)

    def test_on_rechecks_and_overwrites_stale_temporary_setpoint_before_hon(self):
        self.communicator.set_voltage(55.0)
        self.communicator._mock_hv_on = True
        with patch.object(self.communicator, '_send_and_receive', wraps=self.communicator._send_and_receive) as send:
            self.assertFalse(self.communicator.turn_on().startswith(b'ERROR'))
        commands = [args[0] for args, _ in send.call_args_list]
        self.assertEqual(commands, [b'HOF', b'HCM0', b'HGS', b'HRT', b'HGS', b'HBV2C31', b'HGS', b'HON', b'HGS'])
        reading = self.communicator.monitor()
        self.assertTrue(reading['status_flags']['is_hv_on'])
        self.assertFalse(reading['status_flags']['is_temp_correction_enabled'])
        self.assertAlmostEqual(reading['voltage'], 20.5, delta=0.002)

    def test_repeated_on_restarts_at_low_voltage(self):
        self.communicator.turn_on()
        self.communicator.set_voltage(55.0)
        self.communicator.turn_on()
        self.assertAlmostEqual(self.communicator.monitor()['voltage'], 20.5, delta=0.002)

    def test_setpoint_failure_prevents_hon_and_attempts_off(self):
        with patch.object(self.communicator, 'set_voltage', return_value=b'ERROR:write failed'), \
                patch.object(self.communicator, '_send_and_receive', wraps=self.communicator._send_and_receive) as send:
            self.assertTrue(self.communicator.turn_on().startswith(b'ERROR'))
        commands = [args[0] for args, _ in send.call_args_list]
        self.assertNotIn(b'HON', commands)
        self.assertEqual(commands[-1], b'HOF')

    def test_initialization_failure_prevents_hon(self):
        with patch.object(self.communicator, 'initialize_safe_state', return_value=b'ERROR:bad parameters'), \
                patch.object(self.communicator, '_send_and_receive', wraps=self.communicator._send_and_receive) as send:
            self.assertTrue(self.communicator.turn_on().startswith(b'ERROR'))
        self.assertEqual([args[0] for args, _ in send.call_args_list], [b'HOF'])

    def test_failed_post_on_status_attempts_off(self):
        original = self.communicator._send_and_receive

        def inject_correction(command):
            response = original(command)
            if command == b'HON':
                self.communicator._mock_correction = True
            return response

        with patch.object(self.communicator, '_send_and_receive', side_effect=inject_correction):
            self.assertTrue(self.communicator.turn_on().startswith(b'ERROR'))
        self.assertFalse(self.communicator._mock_hv_on)

    def test_unconfirmed_pre_on_status_never_sends_hon(self):
        original = self.communicator._send_and_receive

        def inject_correction(command):
            response = original(command)
            if command.startswith(b'HBV'):
                self.communicator._mock_correction = True
            return response

        with patch.object(self.communicator, '_send_and_receive', side_effect=inject_correction) as send:
            self.assertTrue(self.communicator.turn_on().startswith(b'ERROR'))
        self.assertNotIn(b'HON', [args[0] for args, _ in send.call_args_list])


if __name__ == '__main__':
    unittest.main()
