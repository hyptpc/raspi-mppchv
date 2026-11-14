from datetime import datetime
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules import db_measurements as database
from modules import hardware_manager
from modules.kikusui_module import KikusuiCommunicator


class KikusuiCurrentTests(unittest.TestCase):
    def setUp(self):
        self.communicator = KikusuiCommunicator('mock', is_test_mode=True)
        self.communicator.is_test_mode = False
        self.communicator.instrument = Mock()
        self.responses = {
            'MEASure:VOLTage?': '50.0',
            'MEASure:CURRent?': '0.012345',
            'OUTPut:STATe?': '1',
            'STATus:OPERation:CONDition?': '1024',
            'STATus:QUEStionable:CONDition?': '2',
        }
        self.communicator.instrument.query.side_effect = self.responses.__getitem__

    def test_current_is_converted_to_milliamps_before_rounding(self):
        for amps, milliamps in [('0', 0.0), ('0.012345', 12.345),
                                ('1.234567E-5', 0.012), ('1.5', 1500.0),
                                ('-0.000001', -0.001)]:
            with self.subTest(amps=amps):
                self.responses['MEASure:CURRent?'] = amps
                result = self.communicator.monitor()
                self.assertNotIn('error', result)
                self.assertEqual(result['current'], milliamps)
                self.assertIn(f'C:{amps}', result['raw_response'])
                self.assertEqual(result['voltage'], 50.0)
                self.assertTrue(result['is_on'])
                self.assertTrue(result['status_info']['has_ocp_tripped'])
                self.assertTrue(result['status_info']['is_cc_mode'])

    def test_current_query_failure_is_not_reported_as_zero(self):
        self.responses['MEASure:CURRent?'] = 'ERROR:VISA_QUERY_FAILED'
        result = self.communicator.monitor()
        self.assertIn('error', result)
        self.assertNotIn('current', result)

    def test_nonfinite_readings_are_monitor_errors(self):
        for query in ('MEASure:VOLTage?', 'MEASure:CURRent?'):
            for value in ('nan', 'inf', '-inf'):
                with self.subTest(query=query, value=value):
                    old = self.responses[query]
                    self.responses[query] = value
                    result = self.communicator.monitor()
                    self.responses[query] = old
                    self.assertIn('error', result)
                    self.assertNotIn('voltage', result)
                    self.assertNotIn('current', result)

    def test_current_and_ocp_settings_still_use_amps(self):
        self.communicator.set_current(0.012)
        self.communicator.instrument.write.assert_called_with('SOURce:CURRent 0.012')
        self.responses['CURRent:PROTection:LEVel?'] = '0.025'
        self.assertEqual(self.communicator.enable_ocp(0.025), b'OK')
        self.communicator.instrument.write.assert_called_with(
            'CURRent:PROTection:LEVel 0.025')

    def test_new_rows_and_data_api_use_milliamps_without_rewriting_history(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        database.Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sessions() as session:
            historical = database.Measurement(port_id=0, current=0.012345)
            session.add(historical)
            session.commit()
            historical_id = historical.id
        with patch.object(database, 'SessionLocal', sessions), \
                patch.dict(hardware_manager.DEVICE_MAPPINGS, {}, clear=True):
            hardware_manager.monitor_primary_then_save_combined(0, self.communicator)
            rows = database.get_data_from_db_since(datetime.min)
        self.assertEqual([row['current'] for row in rows], [0.012345, 12.345])
        with sessions() as session:
            self.assertEqual(session.get(database.Measurement, historical_id).current, 0.012345)


if __name__ == '__main__':
    unittest.main()
