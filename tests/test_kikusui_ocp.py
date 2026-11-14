import unittest
from unittest.mock import Mock, call, patch

import pyvisa

from modules.kikusui_module import KikusuiCommunicator


class KikusuiOcpTests(unittest.TestCase):
    def setUp(self):
        logger = patch('modules.kikusui_module.log')
        logger.start()
        self.addCleanup(logger.stop)
        self.communicator = KikusuiCommunicator('mock', True)
        self.communicator.is_test_mode = False
        self.instrument = Mock()
        self.communicator.instrument = self.instrument

    def test_sets_only_the_pmx_threshold_and_verifies_readback(self):
        self.instrument.query.return_value = '1.234E-2'
        self.assertEqual(self.communicator.enable_ocp(.01234), b'OK')
        self.assertEqual(self.instrument.mock_calls, [
            call.write('CURRent:PROTection:LEVel 0.01234'),
            call.query('CURRent:PROTection:LEVel?')])

    def test_rejected_or_rounded_setting_is_not_reported_as_success(self):
        for reply in ('0.1', '0.012', '0', '-1', 'nan', 'inf', '', 'garbled'):
            with self.subTest(reply=reply):
                self.instrument.reset_mock()
                self.instrument.query.return_value = reply
                self.assertTrue(self.communicator.enable_ocp(.01234).startswith(b'ERROR:'))
                self.instrument.write.assert_called_once_with('CURRent:PROTection:LEVel 0.01234')
                self.instrument.query.assert_called_once_with('CURRent:PROTection:LEVel?')

    def test_write_failure_does_not_query_or_send_more_settings(self):
        self.instrument.write.side_effect = pyvisa.errors.VisaIOError(-1073807339)
        self.assertTrue(self.communicator.enable_ocp(.1).startswith(b'ERROR:'))
        self.instrument.write.assert_called_once()
        self.instrument.query.assert_not_called()

    def test_readback_timeout_is_an_error_without_retrying_or_resetting(self):
        self.instrument.query.side_effect = pyvisa.errors.VisaIOError(-1073807339)
        self.assertTrue(self.communicator.enable_ocp(.1).startswith(b'ERROR:'))
        self.instrument.write.assert_called_once_with('CURRent:PROTection:LEVel 0.1')
        self.instrument.query.assert_called_once_with('CURRent:PROTection:LEVel?')

    def test_invalid_levels_never_access_hardware(self):
        for value in (0, -1, float('nan'), float('inf'), None, 'invalid'):
            with self.subTest(value=value):
                self.assertTrue(self.communicator.enable_ocp(value).startswith(b'ERROR:'))
        self.instrument.write.assert_not_called()
        self.instrument.query.assert_not_called()

    def test_disable_is_rejected_in_real_and_mock_modes_without_io(self):
        for mode in (False, True):
            with self.subTest(mode=mode):
                self.communicator.is_test_mode = mode
                self.communicator._mock_ocp_level_a = .1
                self.assertTrue(self.communicator.disable_ocp().startswith(b'ERROR:COMMAND_NOT_SUPPORTED'))
                self.assertEqual(self.communicator._mock_ocp_level_a, .1)
                self.assertTrue(self.communicator._mock_ocp_enabled)
        self.instrument.write.assert_not_called()
        self.instrument.query.assert_not_called()
