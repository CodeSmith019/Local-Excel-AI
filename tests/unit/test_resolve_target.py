"""Unit tests for resolve_target functionality."""

import pytest

from backend.excel.adapter import TargetError
from backend.excel.serializer import resolve_target
from backend.schemas.intent import Target
from backend.schemas.sheet import SheetSnapshot


@pytest.fixture
def sample_snapshot() -> SheetSnapshot:
    return SheetSnapshot(
        workbook="employees.xlsx",
        sheet="Employees",
        used_range="A1:C4",
        header_row=1,
        columns=["A", "B", "C"],
        headers=["Emp ID", "Full Name", "Department"],
        values=[
            ["Emp ID", "Full Name", "Department"],
            [101, "Alice", "Sales"],
            [102, "Bob", "Engineering"],
            [103, "Charlie", "Marketing"],
        ],
        formulas=[
            [None, None, None],
            [None, None, None],
            [None, None, None],
            [None, None, None],
        ],
        selection="B2:B3",
    )


def test_resolve_target_columns_by_name(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="columns", columns=["Full Name"])
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["B2", "B3", "B4"]


def test_resolve_target_columns_by_letter(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="columns", columns=["b"])
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["B2", "B3", "B4"]


def test_resolve_target_columns_case_and_trim(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="columns", columns=["  department  "])
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["C2", "C3", "C4"]


def test_resolve_target_headers_all(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="headers")
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["A1", "B1", "C1"]


def test_resolve_target_headers_subset(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="headers", columns=["Emp ID", "C"])
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["A1", "C1"]


def test_resolve_target_range(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="range", range="A2:B3")
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["A2", "B2", "A3", "B3"]


def test_resolve_target_selection(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="selection")
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["B2", "B3"]


def test_resolve_target_selection_none() -> None:
    snapshot = SheetSnapshot(
        workbook="test.xlsx",
        sheet="S1",
        used_range="A1:A2",
        header_row=1,
        columns=["A"],
        headers=["X"],
        values=[["X"], [1]],
        formulas=[[None], [None]],
        selection=None,
    )
    target = Target(kind="selection")
    with pytest.raises(TargetError, match="No cells are currently selected"):
        resolve_target(snapshot, target)


def test_resolve_target_columns_camel_case_to_spaced(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="columns", columns=["fullName", "emp_id"])
    addresses = resolve_target(sample_snapshot, target)
    assert addresses == ["B2", "A2", "B3", "A3", "B4", "A4"]


def test_resolve_target_unknown_column(sample_snapshot: SheetSnapshot) -> None:
    target = Target(kind="columns", columns=["NonExistent"])
    with pytest.raises(TargetError) as exc_info:
        resolve_target(sample_snapshot, target)
    err = str(exc_info.value)
    assert "NonExistent" in err
    assert "'Emp ID'" in err
    assert "'Full Name'" in err
    assert "'Department'" in err

