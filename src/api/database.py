"""Short, consistent read snapshots. Never creates a DB or changes journal mode."""
from contextlib import contextmanager
import sqlite3
from pathlib import Path

READ_TIMEOUT_SECONDS = 0.25


@contextmanager
def read_snapshot(path: Path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True,
                                 timeout=READ_TIMEOUT_SECONDS)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        yield connection
    finally:
        # Roll back the read transaction before releasing its connection/locks.
        connection.close()
