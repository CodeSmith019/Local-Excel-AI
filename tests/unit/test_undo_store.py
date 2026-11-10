"""Unit tests for SQLite-based undo snapshot storage."""

from pathlib import Path

from backend.schemas.sheet import RegionState
from backend.storage.undo import list_recent, pop_latest, save_snapshot


def test_save_and_pop_snapshot(tmp_path: Path) -> None:
    db_file = tmp_path / "test_undo.sqlite"

    state = RegionState(
        sheet="Employees",
        region="B2:B3",
        values=[["Alice"], ["Bob"]],
        formulas=[[None], [None]],
        fills=[[None], ["#FFFF00"]],
    )

    snap_id = save_snapshot(
        thread_id="t1",
        state=state,
        summary="Test change on B2:B3",
        db_path=db_file,
    )
    assert snap_id > 0

    recent = list_recent(10, db_path=db_file)
    assert len(recent) == 1
    assert recent[0]["id"] == snap_id
    assert recent[0]["summary"] == "Test change on B2:B3"

    # Pop latest
    popped = pop_latest(db_path=db_file)
    assert popped is not None
    restored_state, summary = popped
    assert summary == "Test change on B2:B3"
    assert restored_state.sheet == "Employees"
    assert restored_state.region == "B2:B3"
    assert restored_state.values == [["Alice"], ["Bob"]]
    assert restored_state.fills == [[None], ["#FFFF00"]]

    # Store should now be empty
    assert pop_latest(db_path=db_file) is None
    assert len(list_recent(10, db_path=db_file)) == 0


def test_undo_pruning_limit_50(tmp_path: Path) -> None:
    db_file = tmp_path / "test_prune.sqlite"

    for i in range(1, 56):
        state = RegionState(
            sheet="S1",
            region="A1",
            values=[[i]],
            formulas=[[None]],
            fills=[[None]],
        )
        save_snapshot(
            thread_id=f"t{i}",
            state=state,
            summary=f"Snapshot {i}",
            db_path=db_file,
        )

    # After saving 55 snapshots, only 50 should remain (snapshots 6 to 55)
    recent = list_recent(100, db_path=db_file)
    assert len(recent) == 50

    # The most recent should be 55
    popped = pop_latest(db_path=db_file)
    assert popped is not None
    state, summary = popped
    assert summary == "Snapshot 55"
    assert state.values == [[55]]

