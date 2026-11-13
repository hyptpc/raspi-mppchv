from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from modules import db_sync
from modules.db_runs import database_paths


class DatabaseSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source with space'
        self.destination = self.root / 'copies'
        self.config = self.root / 'config.yaml'
        self.make_pair('run001')
        self.write_config()

    def make_pair(self, suffix):
        paths = database_paths(self.source, suffix)
        self.source.mkdir(exist_ok=True)
        for name, path in paths.items():
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('create table records (value text)')
                connection.execute('insert into records values (?)', (name + ':' + suffix,))
                connection.commit()
        return paths

    def write_config(self, suffix='run001', destination=None, interval=5):
        self.config.write_text(yaml.safe_dump({
            'databases': {'db_directory': str(self.source), 'db_suffix': suffix},
            'database_sync': {'destination_directory': str(destination or self.destination),
                              'interval_seconds': interval},
            'test_mode': {'enabled': False},
            'devices': [{'id': 1, 'type': 'serial_hv', 'connection': '/dev/forbidden'}],
        }))

    def rows(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute('select value from records').fetchall()

    def test_pair_uses_same_suffix_and_keeps_sources(self):
        copied = db_sync.sync_database_pair(self.source, 'run001', self.destination)
        for name, source in database_paths(self.source, 'run001').items():
            self.assertTrue(source.exists())
            self.assertEqual(copied[name].name, source.name)
            self.assertEqual(self.rows(source), self.rows(copied[name]))

    def test_live_wal_snapshot_includes_only_committed_rows(self):
        source = database_paths(self.source, 'run001')['measurements']
        with closing(sqlite3.connect(source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute("insert into records values ('committed')")
            writer.commit()
            writer.execute("insert into records values ('uncommitted')")
            copied = db_sync.sync_database_pair(self.source, 'run001', self.destination)
            values = self.rows(copied['measurements'])
            self.assertIn(('committed',), values)
            self.assertNotIn(('uncommitted',), values)
            self.assertTrue(writer.in_transaction)
            with closing(sqlite3.connect(copied['measurements'])) as snapshot:
                self.assertEqual(snapshot.execute('PRAGMA journal_mode').fetchone()[0], 'delete')

    def test_repeated_sync_updates_snapshots_and_keeps_unrelated_files(self):
        copied = db_sync.sync_database_pair(self.source, 'run001', self.destination)
        marker = self.destination / 'keep.txt'
        marker.write_text('keep')
        with closing(sqlite3.connect(database_paths(self.source, 'run001')['measurements'])) as connection:
            connection.execute("insert into records values ('new')")
            connection.commit()
        db_sync.sync_database_pair(self.source, 'run001', self.destination)
        self.assertIn(('new',), self.rows(copied['measurements']))
        self.assertEqual(marker.read_text(), 'keep')
        self.assertEqual(list(self.destination.glob('.db-sync-*')), [])

    def test_missing_source_never_creates_an_empty_database_or_destination(self):
        missing = self.root / 'missing'
        with self.assertRaises(FileNotFoundError):
            db_sync.sync_database_pair(missing, 'run001', self.destination)
        self.assertFalse(missing.exists())
        self.assertFalse(self.destination.exists())

    def test_same_destination_or_symlink_is_rejected(self):
        for destination in (self.source, self.root / 'linked'):
            if destination != self.source:
                destination.symlink_to(self.source, target_is_directory=True)
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                db_sync.sync_database_pair(self.source, 'run001', destination)

    def test_second_backup_failure_does_not_publish_first_backup(self):
        copied = db_sync.sync_database_pair(self.source, 'run001', self.destination)
        old = {name: path.read_bytes() for name, path in copied.items()}
        sources = database_paths(self.source, 'run001')
        with closing(sqlite3.connect(sources['measurements'])) as connection:
            connection.execute("insert into records values ('new')")
            connection.commit()
        sources['action_log'].write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            db_sync.sync_database_pair(self.source, 'run001', self.destination)
        for name, path in copied.items():
            self.assertEqual(path.read_bytes(), old[name])
        self.assertEqual(list(self.destination.glob('.db-sync-*')), [])

    def test_timeout_preserves_existing_snapshots(self):
        copied = db_sync.sync_database_pair(self.source, 'run001', self.destination)
        old = {name: path.read_bytes() for name, path in copied.items()}
        with self.assertRaises(TimeoutError):
            db_sync.sync_database_pair(self.source, 'run001', self.destination, timeout_seconds=1e-12)
        for name, path in copied.items():
            self.assertEqual(path.read_bytes(), old[name])

    def test_cli_config_and_overrides_do_not_connect_to_hardware(self):
        self.make_pair('run002')
        destination = self.root / 'override'
        with patch('serial.Serial', side_effect=AssertionError('hardware')) as serial, \
                patch('pyvisa.ResourceManager', side_effect=AssertionError('hardware')) as visa, \
                redirect_stdout(io.StringIO()):
            result = db_sync.main(['--config', str(self.config), '--suffix', 'run002',
                                   '--destination', str(destination), '--once'])
        self.assertEqual(result, 0)
        self.assertTrue((destination / 'measurements_run002.db').exists())
        self.assertTrue((destination / 'action_log_run002.db').exists())
        self.assertFalse(self.destination.exists())
        serial.assert_not_called()
        visa.assert_not_called()

    def test_dry_run_does_not_open_databases_or_create_directories(self):
        self.write_config(suffix='not-created')
        output = io.StringIO()
        with patch.object(db_sync.sqlite3, 'connect', side_effect=AssertionError('DB opened')), redirect_stdout(output):
            self.assertEqual(db_sync.main(['--config', str(self.config), '--dry-run']), 0)
        plan = json.loads(output.getvalue())
        self.assertTrue(plan['source']['measurements'].endswith('measurements_not-created.db'))
        self.assertFalse(self.destination.exists())

    def test_unconfigured_destination_fails_without_changes(self):
        self.config.write_text('databases:\n  db_directory: data\n')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(db_sync.main(['--config', str(self.config)]), 1)
        self.assertFalse(self.destination.exists())

    def test_shell_wrapper_works_from_another_working_directory(self):
        script = Path('sync_db.sh').resolve()
        result = subprocess.run([str(script), '--config', str(self.config), '--dry-run'],
                                cwd=self.root, env={**os.environ, 'HV_PYTHON': sys.executable},
                                capture_output=True, text=True, check=True)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['source']['action_log'], str(self.source / 'action_log_run001.db'))
        self.assertFalse(self.destination.exists())

    def test_watch_reloads_suffix_and_interval_from_config(self):
        self.make_pair('run002')
        sleeps = []

        def next_cycle(interval):
            sleeps.append(interval)
            if len(sleeps) == 1:
                self.write_config(suffix='run002', interval=7)
            else:
                raise KeyboardInterrupt()

        with patch.object(db_sync.time, 'sleep', side_effect=next_cycle), redirect_stdout(io.StringIO()):
            self.assertEqual(db_sync.main(['--config', str(self.config), '--watch']), 0)
        self.assertEqual(sleeps, [5.0, 7.0])
        for suffix in ('run001', 'run002'):
            self.assertTrue((self.destination / f'measurements_{suffix}.db').exists())
            self.assertTrue((self.destination / f'action_log_{suffix}.db').exists())

    def test_watch_recovers_from_temporary_copy_failure(self):
        backup = db_sync.sync_database_pair
        attempts = []

        def retry(*args):
            attempts.append(args)
            if len(attempts) == 1:
                raise OSError('temporarily unavailable')
            return backup(*args)

        pauses = []

        def next_cycle(interval):
            pauses.append(interval)
            if len(pauses) == 2:
                raise KeyboardInterrupt()

        with patch.object(db_sync, 'sync_database_pair', side_effect=retry), \
                patch.object(db_sync.time, 'sleep', side_effect=next_cycle), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(db_sync.main(['--config', str(self.config), '--watch']), 0)
        self.assertEqual(len(attempts), 2)
        self.assertTrue((self.destination / 'measurements_run001.db').exists())


if __name__ == '__main__':
    unittest.main()
