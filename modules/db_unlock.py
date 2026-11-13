"""Check SQLite locks and request recovery without deleting database files."""
import argparse
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import yaml

from modules.db_runs import database_paths


def recover_database(path, timeout_seconds=5.0):
    """Wait for a write lock; checkpoint WAL only when SQLite permits it."""
    path = Path(path).expanduser().resolve()
    # mode=rw permits SQLite recovery but never creates an absent database.
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True,
                                 timeout=timeout_seconds)) as connection:
        connection.execute('BEGIN EXCLUSIVE')
        connection.rollback()
        mode = connection.execute('PRAGMA journal_mode').fetchone()[0]
        if mode == 'wal':
            busy, _, _ = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if busy:
                raise sqlite3.OperationalError('WAL checkpoint busy; close the process using the database and retry')
    return mode


def show_users(path):
    executable = shutil.which('fuser')
    if executable:
        files = [str(p) for p in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')) if p.exists()]
        if files:
            print('Processes using these files (not necessarily lock owners):', file=sys.stderr, flush=True)
            try:
                subprocess.run([executable, '-v', *files], check=False, timeout=5)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f'Process lookup failed: {error}', file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check configured SQLite locks and request safe recovery')
    parser.add_argument('--config', default='config/config.yaml')
    args = parser.parse_args(argv)
    try:
        config = yaml.safe_load(Path(args.config).read_text()) or {}
        databases = config.get('databases') or {}
        paths = database_paths(databases.get('db_directory', 'data'), databases.get('db_suffix', ''))
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as error:
        print(f'Database configuration error: {error}', file=sys.stderr)
        return 1
    failed = False
    for path in paths.values():
        try:
            mode = recover_database(path)
            print(f'OK: {path}: write lock available (journal_mode={mode})')
        except (OSError, sqlite3.Error) as error:
            failed = True
            print(f'BUSY/ERROR: {path}: {error}', file=sys.stderr, flush=True)
            show_users(path)
    if failed:
        print('If another process holds the lock, close it and retry. No processes were stopped or database files deleted.',
              file=sys.stderr)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
