import unittest
from unittest.mock import patch

import serial

from modules.hamahoto_module import SerialCommunicator


class SerialTransportTests(unittest.TestCase):
    def setUp(self):
        self.communicator = SerialCommunicator('/dev/mockHV', is_test_mode=True)

    def test_command_checksum_is_two_uppercase_hex_digits(self):
        cases = [(b'HOF', b'E2'), (b'HCM0', b'0D'),
                 (b'\x00', b'05'), (b'\xff', b'04')]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(self.communicator._calculate_checksum(command), expected)

    def test_off_command_packet(self):
        self.assertEqual(self.communicator._format_command(b'HOF'), b'\x02HOF\x03E2\r')

    def test_cr_terminated_response_leaves_next_frame_unread(self):
        # HOF and HGS responses captured from the real device; loopback is memory only.
        response = b'\x02hof\x0342\r'
        next_response = b'\x02hgs0010\x0308\r'
        with serial.serial_for_url('loop://', timeout=0.05) as transport:
            self.communicator.ser = transport
            self.communicator.is_test_mode = False
            write = transport.write

            def device_reply(packet):
                self.assertEqual(packet.upper(), b'\x02HOF\x03E2\r')
                write(response + next_response)
                return len(packet)

            with patch.object(transport, 'write', side_effect=device_reply), \
                    patch('modules.hamahoto_module.time.sleep'):
                actual = self.communicator._send_and_receive(b'HOF')
            self.assertEqual(actual, response)
            self.assertEqual(transport.read_until(b'\r'), next_response)


if __name__ == '__main__':
    unittest.main()
