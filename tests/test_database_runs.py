from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from modules import db_logs, db_measurements
from modules.db_runs import create_fresh_database_pair


class DatabaseRunTests(unittest.TestCase):
    def test_named_pair_reserves_both_files(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(create_fresh_database_pair(directory, 'run001'), 'run001')
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                             ['action_log_run001.db', 'measurements_run001.db'])

    def test_existing_either_file_is_preserved_and_partial_reservation_removed(self):
        for kind in ('measurements', 'action_log'):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                existing = Path(directory) / f'{kind}_run001.db'
                existing.write_bytes(b'original')
                with self.assertRaises(FileExistsError):
                    create_fresh_database_pair(directory, 'run001')
                self.assertEqual(existing.read_bytes(), b'original')
                self.assertEqual(list(Path(directory).iterdir()), [existing])

    def test_auto_names_are_distinct(self):
        with TemporaryDirectory() as directory:
            first = create_fresh_database_pair(directory)
            second = create_fresh_database_pair(directory)
            self.assertNotEqual(first, second)
            self.assertEqual(len(list(Path(directory).glob('*.db'))), 4)

    def test_invalid_names_cannot_escape_directory(self):
        with TemporaryDirectory() as directory:
            for suffix in ('../escape', '/absolute', 'a/b', '..', 'name with space'):
                with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                    create_fresh_database_pair(directory, suffix)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_concurrent_creation_has_only_one_winner(self):
        with TemporaryDirectory() as directory:
            def create():
                try:
                    return create_fresh_database_pair(directory, 'same')
                except FileExistsError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(lambda _: create(), range(2))).count('same'), 1)
            self.assertEqual(len(list(Path(directory).glob('*.db'))), 2)

    def run_init_only(self, directory, new_name, fresh=True, configured_suffix='old'):
        config = Path(directory) / 'config.yaml'
        config.write_text(yaml.safe_dump({'test_mode': {'enabled': False},
            'devices': [{'id': 1, 'type': 'serial_hv', 'connection': '/dev/forbidden'}],
            'databases': {'db_directory': directory, 'db_suffix': configured_suffix}}))
        argv = ['main.py', '--config', str(config)]
        if fresh:
            argv.append('--new-db')
            if new_name is not None:
                argv.append(new_name)
        argv.append('--init-db-only')
        with patch.object(sys, 'argv', argv), \
                patch('serial.Serial', side_effect=AssertionError('hardware access')) as serial, \
                patch('pyvisa.ResourceManager', side_effect=AssertionError('VISA access')) as visa, \
                patch('uvicorn.run') as server, \
                patch.object(db_measurements, 'engine', None), patch.object(db_measurements, 'SessionLocal', None), \
                patch.object(db_measurements, 'DATABASE_URL', ''), \
                patch.object(db_logs, 'engine', None), patch.object(db_logs, 'SessionLocal', None):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path('main.py', run_name='__main__')
            serial.assert_not_called()
            visa.assert_not_called()
            server.assert_not_called()
            return raised.exception.code

    def test_init_only_creates_schemas_without_hardware_or_server(self):
        with TemporaryDirectory() as directory:
            old = Path(directory) / 'measurements_old.db'
            old.write_bytes(b'original')
            self.assertEqual(self.run_init_only(directory, 'run001'), 0)
            self.assertEqual(old.read_bytes(), b'original')
            for kind, table in (('measurements', 'measurements'), ('action_log', 'action_logs')):
                with sqlite3.connect(Path(directory) / f'{kind}_run001.db') as connection:
                    self.assertIsNotNone(connection.execute(
                        'select name from sqlite_master where type=? and name=?', ('table', table)).fetchone())

    def test_cli_refuses_existing_named_pair_before_hardware_access(self):
        with TemporaryDirectory() as directory:
            existing = Path(directory) / 'action_log_run001.db'
            existing.write_bytes(b'original')
            self.assertEqual(self.run_init_only(directory, 'run001'), 1)
            self.assertEqual(existing.read_bytes(), b'original')

    def test_cli_auto_name_creates_a_fresh_pair(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(self.run_init_only(directory, None), 0)
            self.assertEqual(len(list(Path(directory).glob('measurements_*.db'))), 1)
            self.assertEqual(len(list(Path(directory).glob('action_log_*.db'))), 1)

    def test_configured_suffix_resumes_existing_rows(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(self.run_init_only(directory, 'run001'), 0)
            path = Path(directory) / 'measurements_run001.db'
            with sqlite3.connect(path) as connection:
                connection.execute('insert into measurements (current) values (?)', (0.123,))
            self.assertEqual(self.run_init_only(directory, None, fresh=False, configured_suffix='run001'), 0)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute('select current from measurements').fetchone()[0], 0.123)


if __name__ == '__main__':
    unittest.main()
