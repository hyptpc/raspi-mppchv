"""Optional, standalone SQLite snapshots; never connects to HV hardware."""
import argparse
from contextlib import closing
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import sys
from tempfile import TemporaryDirectory
import time

import yaml

from modules.db_runs import database_paths


def sync_database_pair(directory, suffix, destination, timeout_seconds=30.0):
    """Back up both live databases before publishing either destination file."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('Snapshot timeout must be finite and positive')
    sources = database_paths(directory, suffix)
    destination = Path(destination).expanduser()
    targets = {name: destination / source.name for name, source in sources.items()}
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f'Source database does not exist: {source}')
        target = targets[name]
        if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
            raise ValueError(f'Source and destination must differ: {source}')

    destination.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('SQLite snapshot timed out')

    # Staging on the destination filesystem permits an atomic replacement per file.
    with TemporaryDirectory(prefix='.db-sync-', dir=destination) as staging:
        staged = {}
        for name, source in sources.items():
            snapshot_path = Path(staging) / source.name
            snapshot_path.touch(mode=0o600, exist_ok=False)
            # mode=ro prevents an absent/misspelled source from creating an empty DB.
            with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True,
                                         timeout=min(timeout_seconds, 5.0))) as origin, \
                    closing(sqlite3.connect(snapshot_path)) as snapshot:
                origin.backup(snapshot, pages=256, progress=progress, sleep=.05)
                if snapshot.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise sqlite3.DatabaseError(f'Snapshot integrity check failed: {source}')
                # Publish a self-contained file without requiring WAL sidecars.
                snapshot.execute('PRAGMA journal_mode=DELETE')
                snapshot.commit()
            snapshot_path.chmod(stat.S_IMODE(source.stat().st_mode))
            staged[name] = snapshot_path
        for name, snapshot_path in staged.items():
            os.replace(snapshot_path, targets[name])
    return targets


def main(argv=None):
    parser = argparse.ArgumentParser(description='Copy a configured SQLite DB pair as consistent snapshots')
    parser.add_argument('--config', default='config/config.yaml')
    parser.add_argument('--destination', help='Override database_sync.destination_directory')
    parser.add_argument('--suffix', help='Override databases.db_suffix, e.g. a run selected with --new-db')
    parser.add_argument('--once', action='store_true', help='Copy once instead of repeating')
    parser.add_argument('--interval', type=float, help='Override database_sync.interval_seconds')
    parser.add_argument('--dry-run', action='store_true', help='Show paths without opening or copying databases')
    args = parser.parse_args(argv)
    if args.interval is not None and (not math.isfinite(args.interval) or args.interval <= 0):
        parser.error('--interval must be finite and positive')
    interval = args.interval or 5.0

    try:
        while True:
            try:
                config = yaml.safe_load(Path(args.config).read_text()) or {}
                db_config = config.get('databases') or {}
                sync_config = config.get('database_sync') or {}
                directory = db_config.get('db_directory', 'data')
                suffix = args.suffix if args.suffix is not None else db_config.get('db_suffix', '')
                destination = args.destination if args.destination is not None else sync_config.get('destination_directory')
                if not destination or not str(destination).strip():
                    raise ValueError('Set database_sync.destination_directory or pass --destination')
                interval = args.interval if args.interval is not None else float(sync_config.get('interval_seconds', 5.0))
                if not math.isfinite(interval) or interval <= 0:
                    raise ValueError('Sync interval must be finite and positive')
                sources = database_paths(directory, suffix)
                targets = {name: Path(destination).expanduser() / source.name for name, source in sources.items()}
                if args.dry_run:
                    print(json.dumps({'source': {k: str(v) for k, v in sources.items()},
                                      'destination': {k: str(v) for k, v in targets.items()},
                                      'interval_seconds': interval}, indent=2))
                    return 0
            except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as error:
                print(f'Database sync configuration error: {error}', file=sys.stderr, flush=True)
                return 1
            try:
                copied = sync_database_pair(directory, suffix, destination)
                print(json.dumps({'time': datetime.now().isoformat(),
                                  'copied': {k: str(v) for k, v in copied.items()}}, ensure_ascii=False), flush=True)
            except (OSError, ValueError, sqlite3.Error) as error:
                print(f'Database sync failed: {error}', file=sys.stderr, flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
