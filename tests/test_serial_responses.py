import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules import db_measurements as database, hardware_manager
from modules.hamahoto_module import SerialCommunicator


def frame(body):
    checksum = f'{(sum(body) + 5) & 0xFF:02X}'.encode('ascii')
    return b'\x02' + body + b'\x03' + checksum + b'\r'


class SerialResponseTests(unittest.TestCase):
    def setUp(self):
        self.communicator = SerialCommunicator('/dev/mockHV', is_test_mode=True)
        self.communicator.is_test_mode = False
        self.communicator.ser = Mock(is_open=True)
        sleep_patch = patch('modules.hamahoto_module.time.sleep')
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def exchange(self, command, response):
        self.communicator.ser.read_until.return_value = response
        return self.communicator._send_and_receive(command)

    def test_captured_device_responses_are_accepted(self):
        cases = [
            (b'HOF', b'\x02hof\x0342\r'),
            (b'HCM0', b'\x02hcm\x033D\r'),
            (b'HGS', b'\x02hgs0010\x0308\r'),
            (b'HRT', b'\x02hrt0000000000000000001E0014\x03EE\r'),
            (b'HPO', b'\x02hpo00100000023100000692\x0324\r'),
        ]
        for command, response in cases:
            with self.subTest(command=command):
                self.assertEqual(self.exchange(command, response), response)

    def test_invalid_frames_are_errors(self):
        valid = frame(b'hgs0010')
        cases = {
            'timeout': b'',
            'missing_cr': valid[:-1],
            'missing_stx': valid[1:],
            'wrong_etx': valid[:-4] + b'!' + valid[-3:],
            'wrong_checksum': valid[:-3] + b'00\r',
            'invalid_checksum_hex': valid[:-3] + b'GG\r',
            'signed_checksum': valid[:-3] + b'+8\r',
            'wrong_command': frame(b'hgc0010'),
            'short_payload': frame(b'hgs010'),
            'long_payload': frame(b'hgs00010'),
            'invalid_payload_hex': frame(b'hgs00G0'),
            'signed_payload': frame(b'hgs+010'),
            'non_ascii': frame(b'hgs\xff010'),
            'extra_frame': valid + valid,
        }
        for reason, response in cases.items():
            with self.subTest(reason=reason):
                self.assertTrue(self.exchange(b'HGS', response).startswith(b'ERROR:'))

    def test_device_error_is_not_a_success_response(self):
        result = self.exchange(b'HOF', frame(b'hxx1'))
        self.assertTrue(result.startswith(b'ERROR:DEVICE_ERROR'))
        self.assertIn(b'hxx1', result)

    def test_write_acknowledgement_cannot_have_a_payload(self):
        self.assertTrue(self.exchange(b'HOF', frame(b'hof0000')).startswith(b'ERROR:'))

    def test_monitor_rejects_corrupt_data_instead_of_reporting_measurements(self):
        self.communicator.ser.read_until.return_value = (
            b'\x02hpo00100000023100000692\x0300\r'
        )
        result = self.communicator.monitor()
        self.assertIn('error', result)
        self.assertNotIn('voltage', result)
        self.assertNotIn('status_flags', result)

    def test_monitor_checks_reserved_hex_and_full_payload_length(self):
        for body in (b'hpo0010ZZZZ023100000692',
                     b'hpo001000000231000006920',
                     b'hpo0010000002310000069'):
            with self.subTest(body=body):
                self.communicator.ser.read_until.return_value = frame(body)
                self.assertIn('error', self.communicator.monitor())

    def test_monitor_still_decodes_valid_measurements(self):
        self.communicator.ser.read_until.return_value = (
            b'\x02hpo00100000023100000692\x0324\r'
        )
        result = self.communicator.monitor()
        self.assertNotIn('error', result)
        self.assertEqual(result['voltage'], 1.017)
        self.assertFalse(result['status_flags']['is_hv_on'])
        self.assertFalse(result['status_flags']['is_temp_correction_enabled'])

    def test_enabled_correction_triggers_off_and_returns_error(self):
        self.communicator.ser.read_until.side_effect = [
            frame(b'hpo004100002C310000B7D7'), frame(b'hof'),
        ]
        result = self.communicator.monitor()
        self.assertIn('unexpectedly enabled', result['error'])
        self.assertTrue(result['status_flags']['is_temp_correction_enabled'])
        self.assertNotIn('voltage', result)
        self.assertEqual([args[0][1:-4] for args, _ in self.communicator.ser.write.call_args_list],
                         [b'HPO', b'HOF'])

    def test_correction_trip_reports_off_failures(self):
        for off_result in (b'ERROR:SERIAL_COMM_FAILED', b''):
            with self.subTest(off_result=off_result):
                self.communicator.ser.read_until.return_value = frame(b'hpo004100002C310000B7D7')
                with patch.object(self.communicator, 'turn_off', return_value=off_result) as off:
                    result = self.communicator.monitor()
                off.assert_called_once()
                self.assertIn('OFF command failed', result['error'])

    def test_correction_trip_handles_off_exception(self):
        self.communicator.ser.read_until.return_value = frame(b'hpo004100002C310000B7D7')
        with patch.object(self.communicator, 'turn_off', side_effect=RuntimeError('disconnected')):
            result = self.communicator.monitor()
        self.assertIn('OFF command failed', result['error'])
        self.assertIn('disconnected', result['raw_response'])

    def test_disabled_correction_does_not_send_off(self):
        self.communicator.ser.read_until.return_value = frame(b'hpo000100002C310000B7D7')
        with patch.object(self.communicator, 'turn_off') as off:
            self.assertNotIn('error', self.communicator.monitor())
        off.assert_not_called()

    def test_correction_trip_is_saved_as_error_with_original_status(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        database.Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        self.communicator.ser.read_until.side_effect = [
            frame(b'hpo004100002C310000B7D7'), frame(b'hof'),
        ]
        with patch.object(database, 'SessionLocal', sessions):
            hardware_manager.monitor_primary_then_save_combined(1, self.communicator)
        with sessions() as session:
            row = session.query(database.Measurement).one()
            self.assertIsNone(row.voltage)
            self.assertIsNone(row.is_hv_on)
            self.assertTrue(row.is_temp_correction_enabled)
            self.assertIn('ERROR:TEMP_CORRECTION_ENABLED', row.raw_response)


if __name__ == '__main__':
    unittest.main()
