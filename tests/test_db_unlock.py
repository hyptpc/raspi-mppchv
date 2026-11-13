from contextlib import closing, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from modules import db_unlock
from modules.db_runs import database_paths


class DatabaseUnlockTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = database_paths(self.root, 'run001')
        for path in self.paths.values():
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('create table records (value text)')
                connection.execute("insert into records values ('original')")
                connection.commit()
        self.path = self.paths['measurements']
        self.config = self.root / 'config.yaml'
        self.config.write_text(yaml.safe_dump({'databases': {
            'db_directory': str(self.root), 'db_suffix': 'run001'}}))

    def test_available_database_keeps_records_and_journal_mode(self):
        self.assertEqual(db_unlock.recover_database(self.path), 'delete')
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('select * from records').fetchall(), [('original',)])
            self.assertEqual(connection.execute('pragma journal_mode').fetchone()[0], 'delete')

    def test_active_writer_is_not_interrupted_and_retry_succeeds(self):
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("insert into records values ('pending')")
            with self.assertRaises(sqlite3.OperationalError):
                db_unlock.recover_database(self.path, timeout_seconds=.02)
            self.assertTrue(writer.in_transaction)
            writer.commit()
            self.assertEqual(db_unlock.recover_database(self.path), 'delete')
            self.assertEqual(writer.execute('select count(*) from records').fetchone()[0], 2)

    def test_wal_reader_blocks_checkpoint_without_losing_committed_data(self):
        with closing(sqlite3.connect(self.path)) as writer, closing(sqlite3.connect(self.path)) as reader:
            writer.execute('pragma journal_mode=WAL')
            writer.execute('pragma wal_autocheckpoint=0')
            reader.execute('begin')
            reader.execute('select * from records').fetchall()
            writer.execute("insert into records values ('committed')")
            writer.commit()
            wal = Path(str(self.path) + '-wal')
            with self.assertRaisesRegex(sqlite3.OperationalError, 'checkpoint busy'):
                db_unlock.recover_database(self.path, timeout_seconds=.02)
            self.assertTrue(reader.in_transaction)
            self.assertGreater(wal.stat().st_size, 0)
            reader.rollback()
            self.assertEqual(db_unlock.recover_database(self.path), 'wal')
            self.assertEqual(wal.stat().st_size, 0)
            self.assertEqual(writer.execute('select count(*) from records').fetchone()[0], 2)

    def test_absent_database_is_not_created(self):
        path = self.root / 'missing.db'
        with self.assertRaises(sqlite3.OperationalError):
            db_unlock.recover_database(path)
        self.assertFalse(path.exists())

    def test_interrupted_transaction_is_recovered_by_sqlite(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executemany('insert into records values (?)', [('x' * 1024,)] * 64)
            connection.commit()
        subprocess.run([sys.executable, '-c', '''
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute('pragma cache_size=1')
connection.execute('begin immediate')
connection.execute("update records set value = 'interrupted'")
os._exit(0)
''', str(self.path)], check=True)
        self.assertTrue(Path(str(self.path) + '-journal').exists())
        self.assertEqual(db_unlock.recover_database(self.path), 'delete')
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('pragma quick_check').fetchone()[0], 'ok')
            self.assertEqual(connection.execute('select count(*) from records').fetchone()[0], 65)
            self.assertEqual(connection.execute("select count(*) from records where value='interrupted'").fetchone()[0], 0)

    def test_cli_uses_configured_pair_without_hardware(self):
        with patch('serial.Serial', side_effect=AssertionError('hardware')), \
                patch('pyvisa.ResourceManager', side_effect=AssertionError('hardware')), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(db_unlock.main(['--config', str(self.config)]), 0)
        for path in self.paths.values():
            self.assertIn(str(path), output.getvalue())

    def test_busy_cli_reports_file_users_without_killing_processes(self):
        with patch.object(db_unlock, 'recover_database', side_effect=sqlite3.OperationalError('locked')), \
                patch.object(db_unlock.shutil, 'which', return_value='/usr/bin/fuser'), \
                patch.object(db_unlock.subprocess, 'run') as run, redirect_stderr(io.StringIO()):
            self.assertEqual(db_unlock.main(['--config', str(self.config)]), 1)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['/usr/bin/fuser', '-v', str(path)] for path in self.paths.values()])

    def test_shell_wrapper_works_from_another_directory(self):
        script = Path('db_unlock.sh').resolve()
        result = subprocess.run([str(script), '--config', str(self.config)], cwd=self.root,
                                env={**os.environ, 'HV_PYTHON': sys.executable},
                                capture_output=True, text=True, check=True)
        for path in self.paths.values():
            self.assertIn(str(path), result.stdout)


if __name__ == '__main__':
    unittest.main()
