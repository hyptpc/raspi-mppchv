import unittest
from unittest.mock import Mock, patch

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


if __name__ == '__main__':
    unittest.main()
