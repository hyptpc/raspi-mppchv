import unittest
from unittest.mock import Mock, patch

from modules import hardware_manager
from modules.kikusui_module import KikusuiCommunicator


class KikusuiStatusTests(unittest.TestCase):
    def setUp(self):
        logger = patch('modules.kikusui_module.log')
        logger.start()
        self.addCleanup(logger.stop)
        self.communicator = KikusuiCommunicator('mock', True)
        self.communicator.is_test_mode = False
        self.communicator.instrument = Mock()
        self.responses = {
            'MEASure:VOLTage?': '50.0', 'MEASure:CURRent?': '0.001',
            'OUTPut:STATe?': '1', 'STATus:OPERation:CONDition?': '0',
            'STATus:QUEStionable:CONDition?': '0',
        }
        self.communicator.instrument.query.side_effect = self.responses.__getitem__

    def test_pmx_register_bits_and_unrelated_faults(self):
        for operation, questionable, cc, ocp in (
                (1024, 2, True, True), (16, 16, False, False),
                (768, 1, False, False), (1792, 18, True, True)):
            with self.subTest(operation=operation, questionable=questionable):
                self.responses['STATus:OPERation:CONDition?'] = str(operation)
                self.responses['STATus:QUEStionable:CONDition?'] = str(questionable)
                result = self.communicator.monitor()
                self.assertNotIn('error', result)
                self.assertEqual(result['status_info'], {'is_cc_mode': cc, 'has_ocp_tripped': ocp})
        self.communicator.instrument.write.assert_not_called()

    def test_repeated_monitoring_preserves_active_ocp_and_does_not_read_events(self):
        self.responses['STATus:QUEStionable:CONDition?'] = '2'
        for _ in range(3):
            self.assertTrue(self.communicator.monitor()['status_info']['has_ocp_tripped'])
        self.responses['STATus:QUEStionable:CONDition?'] = '0'
        self.assertFalse(self.communicator.monitor()['status_info']['has_ocp_tripped'])
        queries = [call.args[0] for call in self.communicator.instrument.query.call_args_list]
        self.assertNotIn('STATus:QUEStionable:EVENt?', queries)
        self.communicator.instrument.write.assert_not_called()

    def test_malformed_status_is_an_error_instead_of_off_or_ok(self):
        invalid = {
            'OUTPut:STATe?': ('', '2', '-1', 'ON', 'garbled'),
            'STATus:OPERation:CONDition?': ('', '-1', '65536', 'nan'),
            'STATus:QUEStionable:CONDition?': ('', '-1', '65536', 'garbled'),
        }
        for query, values in invalid.items():
            for value in values:
                with self.subTest(query=query, value=value):
                    with patch.dict(self.responses, {query: value}):
                        result = self.communicator.monitor()
                    self.assertIn('error', result)
                    self.assertNotIn('is_on', result)
                    self.assertNotIn('status_info', result)
        self.communicator.instrument.write.assert_not_called()

    def test_safety_checks_do_not_treat_unknown_values_as_on(self):
        for state in (None, '0', '1', 0, 1, [], {}):
            for reading in ({'is_on': state}, {'status_flags': {'is_hv_on': state}}):
                with self.subTest(reading=reading):
                    self.assertIsNone(hardware_manager.parse_output_on(reading))
                    with patch.object(hardware_manager, 'REQUIRE_ON_FOR_VOLTAGE_INCREASE', True):
                        allowed, _ = hardware_manager.check_set_voltage_safety(
                            {**reading, 'voltage': 20.0}, 30.0)
                    self.assertFalse(allowed)
