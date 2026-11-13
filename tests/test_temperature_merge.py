import copy
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules import db_measurements as database
from modules import hardware_manager
from modules.hamahoto_module import SerialCommunicator


class EndOfTasks(Exception):
    pass


class TemperatureMergeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        self.sensor = SerialCommunicator('/dev/mockHV', is_test_mode=True)
        self.sensor.monitor = Mock()
        for target, value in [('DEVICE_PORTS', {4: self.sensor}),
                              ('DEVICE_MAPPINGS', {0: 4})]:
            patcher = patch.dict(getattr(hardware_manager, target), value, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(database, 'SessionLocal', self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare_data(self, ocp, cc):
        primary = {'is_on': True, 'voltage': 50.0, 'current': 0.01,
                   'status_info': {'has_ocp_tripped': ocp, 'is_cc_mode': cc},
                   'raw_response': 'primary'}
        temperature = {
            'temperature': 24.5, 'status_raw': 8, 'raw_response': 'sensor',
            'status_flags': {
                'is_hv_on': False,
                'is_overcurrent_protection_active': not ocp,
                'is_current_out_of_spec': not cc,
                'is_temp_sensor_connected': True,
                'is_temp_in_range': True,
                'is_temp_correction_enabled': False,
            },
        }
        self.sensor.monitor.return_value = temperature
        return primary, temperature

    def assert_saved_status(self, ocp, cc):
        with self.sessions() as session:
            row = session.query(database.Measurement).order_by(
                database.Measurement.id.desc()).first()
            self.assertEqual(row.is_overcurrent_protection_active, ocp)
            self.assertEqual(row.is_current_out_of_spec, cc)
            self.assertTrue(row.is_hv_on)
            self.assertEqual(row.voltage, 50.0)
            self.assertEqual(row.temperature, 24.5)
            self.assertTrue(row.is_temp_sensor_connected)
            self.assertFalse(row.is_temp_correction_enabled)

    def test_ramp_monitor_save_preserves_kikusui_protection_status(self):
        for ocp, cc in [(True, True), (True, False), (False, True), (False, False)]:
            with self.subTest(ocp=ocp, cc=cc):
                primary, temperature = self.prepare_data(ocp, cc)
                originals = copy.deepcopy((primary, temperature))
                communicator = Mock(monitor=Mock(return_value=primary))
                hardware_manager.monitor_primary_then_save_combined(0, communicator)
                self.assert_saved_status(ocp, cc)
                self.assertEqual((primary, temperature), originals)

    def test_worker_monitor_save_preserves_kikusui_protection_status(self):
        for ocp, cc in [(True, True), (True, False), (False, True), (False, False)]:
            with self.subTest(ocp=ocp, cc=cc):
                primary, _ = self.prepare_data(ocp, cc)
                communicator = Mock(ser=True, monitor=Mock(return_value=primary))
                queue = Mock()
                queue.get.side_effect = [
                    {'port_id': 0, 'command_info': {'command_type': 'MONITOR'}},
                    EndOfTasks(),
                ]
                with patch.dict(hardware_manager.DEVICE_PORTS, {0: communicator}):
                    with self.assertRaises(EndOfTasks):
                        hardware_manager.worker(queue)
                queue.task_done.assert_called_once()
                self.assert_saved_status(ocp, cc)

    def test_merge_preserves_primary_serial_flags_and_does_not_mutate_inputs(self):
        _, temperature = self.prepare_data(False, False)
        primary = {'status_flags': {'is_hv_on': True,
                                   'is_overcurrent_protection_active': False,
                                   'is_current_out_of_spec': False,
                                   'is_temp_in_range': False}}
        original = copy.deepcopy(primary)
        merged = hardware_manager._combine_primary_with_temp(0, primary)
        self.assertTrue(merged['status_flags']['is_hv_on'])
        self.assertFalse(merged['status_flags']['is_overcurrent_protection_active'])
        self.assertFalse(merged['status_flags']['is_current_out_of_spec'])
        self.assertTrue(merged['status_flags']['is_temp_in_range'])
        self.assertEqual(primary, original)
        self.assertIsNot(merged['status_flags'], primary['status_flags'])
        self.assertIsNot(merged['status_flags'], temperature['status_flags'])

    def test_temperature_failure_preserves_primary_data(self):
        primary, _ = self.prepare_data(True, True)
        self.sensor.monitor.return_value = {'error': 'sensor unavailable'}
        merged = hardware_manager._combine_primary_with_temp(0, primary)
        self.assertEqual(merged, primary)
        self.assertIsNot(merged, primary)

    def test_unmapped_primary_does_not_query_sensor(self):
        primary, _ = self.prepare_data(True, True)
        self.assertEqual(hardware_manager._combine_primary_with_temp(1, primary), primary)
        self.sensor.monitor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
