"""Undo snapshot storage operations backed by SQLite."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.excel.values import from_jsonable, to_jsonable
from backend.schemas.sheet import RegionState
from backend.storage.db import get_connection

MAX_UNDO_SNAPSHOTS = 50


def save_snapshot(
    thread_id: str | None,
    state: RegionState,
    summary: str,
    db_path: Path | str | None = None,
) -> int:
    """Save a region snapshot to the undo store and prune old snapshots.

    Keeps only the newest 50 snapshots. Returns the newly inserted snapshot ID.
    """
    conn = get_connection(db_path)
    try:
        now_iso = datetime.now(UTC).isoformat()
        state_dict = to_jsonable(state.model_dump())
        state_json = json.dumps(state_dict)

        cursor = conn.execute(
            """
            INSERT INTO undo_snapshots (created_at, thread_id, sheet, region, state_json, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_iso, thread_id, state.sheet, state.region, state_json, summary),
        )
        snapshot_id = cursor.lastrowid or 0

        # Prune older snapshots beyond MAX_UNDO_SNAPSHOTS
        conn.execute(
            f"""
            DELETE FROM undo_snapshots
            WHERE id NOT IN (
                SELECT id FROM undo_snapshots ORDER BY id DESC LIMIT {MAX_UNDO_SNAPSHOTS}
            )
            """
        )
        conn.commit()
        return snapshot_id
    finally:
        conn.close()


def pop_latest(db_path: Path | str | None = None) -> tuple[RegionState, str] | None:
    """Pop and return the most recent undo snapshot (state, summary), removing it from the store.

    Returns None if no snapshots exist.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT id, state_json, summary
            FROM undo_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if not row:
            return None

        row_id, state_json, summary = row
        conn.execute("DELETE FROM undo_snapshots WHERE id = ?", (row_id,))
        conn.commit()

        raw_dict = json.loads(state_json)
        state_dict = from_jsonable(raw_dict)
        state = RegionState.model_validate(state_dict)
        return state, summary
    finally:
        conn.close()


def list_recent(
    n: int = 10, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """List the most recent n undo snapshots with id, created_at, and summary."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT id, created_at, summary
            FROM undo_snapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (n,),
        )
        rows = cursor.fetchall()
        return [
            {"id": row[0], "created_at": row[1], "summary": row[2]}
            for row in rows
        ]
    finally:
        conn.close()
