"""Reserve a fresh measurement/action-log pair without overwriting files."""
from datetime import datetime
import os
from pathlib import Path
import re
from uuid import uuid4


def create_fresh_database_pair(directory: str, suffix: str = "") -> str:
    if not suffix:
        suffix = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', suffix):
        raise ValueError('Database name must start with a letter/digit and contain only letters, digits, _, -, or .')
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for name in ('measurements', 'action_log'):
            path = root / f'{name}_{suffix}.db'
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created.append(path)
            os.close(descriptor)
    except Exception:
        # Remove only the empty reservations created by this call.
        for path in created:
            path.unlink()
        raise
    return suffix
