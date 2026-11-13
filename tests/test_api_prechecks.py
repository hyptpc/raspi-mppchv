import asyncio
from queue import Queue
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

import main
from modules import hardware_manager


class EndOfTasks(Exception):
    pass


class ApiPrecheckTests(unittest.TestCase):
    def setUp(self):
        self.communicator = Mock(ser=True)
        self.communicator.monitor.return_value = {'voltage': 50.0, 'is_on': True}
        self.queue = Queue()
        patches = [
            patch.dict(hardware_manager.DEVICE_PORTS, {1: self.communicator}, clear=True),
            patch.dict(hardware_manager.PORT_VOLTAGE_LIMITS_V, {1: 60.0}, clear=True),
            patch.object(main, 'command_queue', self.queue),
            patch.object(main, 'log'),
            patch.object(hardware_manager, 'REQUIRE_ON_FOR_VOLTAGE_INCREASE', True),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def queue_voltage(self, value=55.0, port_id=1):
        command = main.StructuredCommand(port_id=port_id, command_type='SET_VOLTAGE', value=value)
        return asyncio.run(main.queue_structured_command(command))

    def run_queued_task(self):
        queue = Mock()
        queue.get.side_effect = [self.queue.get_nowait(), EndOfTasks()]
        with patch.object(hardware_manager, 'run_adaptive_voltage_ramp', return_value=b'OK') as ramp, \
                patch.object(hardware_manager.log_database, 'save_action_log') as action_log, \
                patch.object(hardware_manager, 'log'):
            with self.assertRaises(EndOfTasks):
                hardware_manager.worker(queue)
        queue.task_done.assert_called_once()
        self.assertFalse(hardware_manager.is_system_busy)
        return ramp, action_log

    def test_api_queues_without_hardware_io_or_port_lock(self):
        self.communicator.monitor.side_effect = AssertionError('API must not access hardware')
        with patch.object(hardware_manager, 'get_port_lock',
                          side_effect=AssertionError('API must not wait for ramp lock')) as get_lock:
            self.assertEqual(self.queue_voltage()['status'], 'success')
        get_lock.assert_not_called()
        self.communicator.monitor.assert_not_called()
        self.assertEqual(self.queue.get_nowait()['command_info']['value'], 55.0)

    def test_api_still_rejects_configured_voltage_limit_without_io(self):
        with self.assertRaises(HTTPException) as raised:
            self.queue_voltage(value=61.0)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertTrue(self.queue.empty())
        self.communicator.monitor.assert_not_called()

    def test_api_still_rejects_unconfigured_port(self):
        with self.assertRaises(HTTPException) as raised:
            self.queue_voltage(port_id=9)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(self.queue.empty())

    def test_api_still_rejects_uninitialized_communicator(self):
        self.communicator = Mock(spec=['ser'], ser=None)
        with patch.dict(hardware_manager.DEVICE_PORTS, {1: self.communicator}):
            with self.assertRaises(HTTPException) as raised:
                self.queue_voltage()
        self.assertEqual(raised.exception.status_code, 422)
        self.assertTrue(self.queue.empty())

    def test_worker_rechecks_output_state_changed_since_enqueue(self):
        self.queue_voltage()
        self.communicator.monitor.assert_not_called()
        self.communicator.monitor.return_value = {'voltage': 50.0, 'is_on': False}
        ramp, action_log = self.run_queued_task()
        self.communicator.monitor.assert_called_once()
        ramp.assert_not_called()
        self.assertIn(b'Output is OFF', action_log.call_args.args[2])

    def test_worker_rechecks_voltage_limit_changed_since_enqueue(self):
        self.queue_voltage()
        hardware_manager.PORT_VOLTAGE_LIMITS_V[1] = 54.0
        ramp, action_log = self.run_queued_task()
        self.communicator.monitor.assert_not_called()
        ramp.assert_not_called()
        self.assertIn(b'exceeds configured limit', action_log.call_args.args[2])

    def test_worker_checks_live_state_under_port_lock_before_ramping(self):
        self.queue_voltage()

        def live_monitor():
            self.assertTrue(hardware_manager.get_port_lock(1).locked())
            return {'voltage': 50.0, 'is_on': True}

        self.communicator.monitor.side_effect = live_monitor
        ramp, _ = self.run_queued_task()
        self.communicator.monitor.assert_called_once()
        ramp.assert_called_once_with(1, self.communicator, 55.0,
                                     hardware_manager.RAMP_VOLTAGE_TARGET_V_PER_S)


if __name__ == '__main__':
    unittest.main()
