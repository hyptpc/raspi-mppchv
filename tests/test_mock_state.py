import unittest
from unittest.mock import patch

from modules.hamahoto_module import SerialCommunicator
from modules.kikusui_module import KikusuiCommunicator


class MockStateTests(unittest.TestCase):
    def test_serial_output_and_voltage_are_deterministic(self):
        communicator = SerialCommunicator('/dev/mockHV', True)
        self.assertFalse(communicator.monitor()['status_flags']['is_hv_on'])
        communicator.turn_on()
        communicator.set_voltage(40.0)
        first = communicator.monitor()
        self.assertTrue(first['status_flags']['is_hv_on'])
        self.assertAlmostEqual(first['voltage'], 40.0, delta=0.002)
        self.assertEqual(communicator.monitor(), first)
        communicator.send_raw_command('HOF')
        self.assertEqual(communicator.monitor()['voltage'], 0.0)
        self.assertFalse(communicator.monitor()['status_flags']['is_hv_on'])

    def test_serial_reset_and_runtime_interlock_use_simulated_state(self):
        communicator = SerialCommunicator('/dev/mockHV', True)
        communicator.turn_on()
        communicator._mock_correction = True
        self.assertIn('error', communicator.monitor())
        self.assertFalse(communicator._mock_hv_on)
        communicator.reset_device()
        result = communicator.monitor()
        self.assertNotIn('error', result)
        self.assertFalse(result['status_flags']['is_temp_correction_enabled'])
        self.assertFalse(result['status_flags']['is_hv_on'])

    def test_kikusui_output_voltage_and_raw_queries_share_state(self):
        communicator = KikusuiCommunicator('mock', True)
        self.assertFalse(communicator.monitor()['is_on'])
        communicator.turn_on()
        communicator.set_voltage(40.0)
        self.assertEqual(communicator.monitor()['voltage'], 40.0)
        self.assertEqual(communicator.send_raw_command('MEAS:VOLT?'), b'40.0')
        self.assertEqual(communicator.send_raw_command('OUTP?'), b'1')
        communicator.turn_off()
        self.assertEqual(communicator.monitor()['voltage'], 0.0)
        self.assertEqual(communicator.send_raw_command('OUTP?'), b'0')
        communicator.reset_device()
        self.assertFalse(communicator.monitor()['is_on'])

    def test_kikusui_current_unit_and_settings_are_reproducible(self):
        communicator = KikusuiCommunicator('mock', True)
        communicator.turn_on()
        communicator.set_current(0.02)
        communicator.enable_ocp(0.03)
        communicator._mock_current_a = 0.012
        self.assertEqual(communicator.monitor()['current'], 12.0)
        self.assertEqual(communicator._mock_current_limit_a, 0.02)
        self.assertEqual(communicator._mock_ocp_level_a, 0.03)
        communicator.disable_ocp()
        self.assertFalse(communicator._mock_ocp_enabled)

    def test_mock_commands_never_open_hardware(self):
        with patch('serial.Serial', side_effect=AssertionError('serial hardware')), \
                patch('pyvisa.ResourceManager', side_effect=AssertionError('VISA hardware')):
            for communicator in (SerialCommunicator('/dev/mockHV', True), KikusuiCommunicator('mock', True)):
                communicator.turn_on()
                communicator.set_voltage(25.0)
                self.assertNotIn('error', communicator.monitor())
                communicator.turn_off()
                communicator.reset_device()


if __name__ == '__main__':
    unittest.main()
