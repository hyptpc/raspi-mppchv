from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch

import pyvisa
import yaml

from modules import db_logs, db_measurements, hardware_manager
from modules.kikusui_module import KikusuiCommunicator


class KikusuiStartupTests(unittest.TestCase):
    def instrument(self, on):
        instrument = Mock()
        responses = {
            '*IDN?': 'KIKUSUI,PMX110-0.6A,TEST,1.0',
            'MEASure:VOLTage?': '56.0' if on else '0.0',
            'MEASure:CURRent?': '0.0005' if on else '0.0',
            'OUTPut:STATe?': str(int(on)),
            'STATus:OPERation:CONDition?': '0',
            'STATus:QUEStionable:EVENt?': '16',
        }
        instrument.query.side_effect = responses.__getitem__
        return instrument

    def test_connect_and_monitor_preserve_existing_on_and_off_outputs(self):
        for on in (True, False):
            with self.subTest(on=on):
                instrument = self.instrument(on)
                manager = Mock()
                manager.open_resource.return_value = instrument
                with patch('pyvisa.ResourceManager', return_value=manager):
                    communicator = KikusuiCommunicator('TCPIP0::test::inst0::INSTR', False)
                instrument.query.assert_called_once_with('*IDN?')
                instrument.write.assert_not_called()
                result = communicator.monitor()
                self.assertEqual(result['is_on'], on)
                self.assertEqual(result['voltage'], 56.0 if on else 0.0)
                self.assertEqual(result['current'], .5 if on else 0.0)
                self.assertTrue(result['status_info']['has_ocp_tripped'])
                instrument.write.assert_not_called()

    def test_repeated_reconnection_never_sends_control_or_clear_commands(self):
        instrument = self.instrument(True)
        manager = Mock()
        manager.open_resource.return_value = instrument
        with patch('pyvisa.ResourceManager', return_value=manager):
            for _ in range(3):
                communicator = KikusuiCommunicator('TCPIP0::test::inst0::INSTR', False)
                self.assertTrue(communicator.monitor()['is_on'])
        self.assertEqual(instrument.query.call_args_list.count(call('*IDN?')), 3)
        instrument.write.assert_not_called()

    def test_application_startup_and_connection_failure_do_not_change_outputs(self):
        for failure in (False, True):
            with self.subTest(failure=failure), TemporaryDirectory() as directory, ExitStack() as stack:
                instruments = [self.instrument(True), self.instrument(False)]
                if failure:
                    instruments[0].query.side_effect = pyvisa.errors.VisaIOError(-1073807339)
                manager = Mock()
                manager.open_resource.side_effect = instruments
                config_path = Path(directory) / 'config.yaml'
                config_path.write_text(yaml.safe_dump({
                    'test_mode': {'enabled': False},
                    'devices': [{'id': i, 'type': 'kikusui_visa', 'connection': f'test{i}'} for i in range(2)],
                    'databases': {'db_directory': directory, 'db_suffix': 'restart'},
                }))
                stack.enter_context(patch.object(sys, 'argv', ['main.py', '--config', str(config_path)]))
                stack.enter_context(patch('pyvisa.ResourceManager', return_value=manager))
                stack.enter_context(patch('serial.Serial', side_effect=AssertionError('serial access')))
                server = stack.enter_context(patch('uvicorn.run'))
                stack.enter_context(redirect_stdout(io.StringIO()))
                for name in ('DEVICE_PORTS', 'DEVICE_MAPPINGS', 'PORT_VOLTAGE_LIMITS_V'):
                    stack.enter_context(patch.dict(getattr(hardware_manager, name), {}, clear=True))
                stack.enter_context(patch.object(hardware_manager, 'IS_TEST_MODE', False))
                for module in (db_measurements, db_logs):
                    for name in ('engine', 'SessionLocal'):
                        stack.enter_context(patch.object(module, name, None))
                try:
                    if failure:
                        with self.assertRaises(SystemExit) as raised:
                            runpy.run_path('main.py', run_name='__main__')
                        self.assertEqual(raised.exception.code, 1)
                        server.assert_not_called()
                    else:
                        runpy.run_path('main.py', run_name='__main__')
                        server.assert_called_once()
                    for instrument in instruments:
                        instrument.query.assert_called_once_with('*IDN?')
                        instrument.write.assert_not_called()
                finally:
                    for module in (db_measurements, db_logs):
                        if module.engine is not None:
                            module.engine.dispose()


if __name__ == '__main__':
    unittest.main()
