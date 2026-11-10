"""SQLite database connection and schema initialization."""

import sqlite3
from pathlib import Path

from backend.config import get_settings


def get_db_path(custom_path: Path | str | None = None) -> Path:
    """Resolve database path, defaulting to settings.data_dir / 'app.sqlite'."""
    if custom_path is not None:
        return Path(custom_path)
    return get_settings().data_dir / "app.sqlite"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a SQLite connection and ensure schema tables exist."""
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Initialize undo_snapshots table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS undo_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            thread_id TEXT,
            sheet TEXT NOT NULL,
            region TEXT NOT NULL,
            state_json TEXT NOT NULL,
            summary TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn
