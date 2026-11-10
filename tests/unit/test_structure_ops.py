"""Unit tests for Tier 2 structural spreadsheet operations with FakeAdapter."""

from pathlib import Path

import pytest

from backend.excel.adapter import TargetError
from backend.excel.fake_adapter import FakeAdapter
from backend.ops.registry import REGISTRY, execute
from backend.ops.structure_ops import FORMULA_MOVE_WARNING
from backend.schemas.intent import (
    Condition,
    DeleteColumnParams,
    FillBlanksParams,
    FilterRowsParams,
    HighlightCellsParams,
    InsertColumnParams,
    MoveColumnParams,
    RemoveDuplicatesParams,
    RenameColumnParams,
    SortRowsParams,
)

EMPLOYEES_PATH = Path("tests/fixtures/employees.xlsx")
SALES_PATH = Path("tests/fixtures/sales.xlsx")


@pytest.fixture
def employees_adapter() -> FakeAdapter:
    """FakeAdapter preloaded with employees.xlsx."""
    return FakeAdapter(file_path=EMPLOYEES_PATH)


@pytest.fixture
def sales_adapter() -> FakeAdapter:
    """FakeAdapter preloaded with sales.xlsx."""
    return FakeAdapter(file_path=SALES_PATH)


# ---------------------------------------------------------------------------
# 1. Sort Rows Tests
# ---------------------------------------------------------------------------


def test_sort_rows_numeric_descending(employees_adapter: FakeAdapter) -> None:
    """Sort by Salary highest first."""
    snapshot = employees_adapter.read_snapshot()
    params = SortRowsParams(by_column="Salary", descending=True)
    patch = execute("sort_rows", snapshot, params)

    assert patch.op == "sort_rows"
    assert len(patch.cells) > 0
    assert "Sorted rows by Salary (descending)" in patch.summary

    # Apply patch to fake adapter and verify top salary is 83000 (Li Wei)
    employees_adapter.apply_patch(patch)
    updated = employees_adapter.read_snapshot()
    # Row 2 is first data row; Salary is column F (col index 5)
    salaries = [row[5] for row in updated.values[1:]]
    assert salaries == sorted(salaries, reverse=True)
    assert salaries[0] == 83000


def test_sort_rows_multi_level(employees_adapter: FakeAdapter) -> None:
    """Sort by City then Full Name."""
    snapshot = employees_adapter.read_snapshot()
    params = SortRowsParams(by_column="City", descending=False, then_by="Full Name", then_descending=False)
    patch = execute("sort_rows", snapshot, params)

    assert patch.op == "sort_rows"
    assert len(patch.cells) > 0
    assert "Sorted rows by City, then by Full Name" in patch.summary


def test_sort_rows_date(employees_adapter: FakeAdapter) -> None:
    """Sort by Join Date ascending."""
    snapshot = employees_adapter.read_snapshot()
    params = SortRowsParams(by_column="Join Date", descending=False)
    patch = execute("sort_rows", snapshot, params)

    assert patch.op == "sort_rows"
    assert len(patch.cells) > 0
    employees_adapter.apply_patch(patch)
    updated = employees_adapter.read_snapshot()
    dates = [str(row[6])[:10] for row in updated.values[1:]]
    assert dates == sorted(dates)


def test_sort_rows_idempotent(employees_adapter: FakeAdapter) -> None:
    """Sorting an already sorted table produces no cell changes (finish_nothing)."""
    snapshot = employees_adapter.read_snapshot()
    # Sort by Emp ID ascending (it is already sorted 101..110)
    params = SortRowsParams(by_column="Emp ID", descending=False)
    patch = execute("sort_rows", snapshot, params)

    assert patch.op == "sort_rows"
    assert len(patch.cells) == 0


# ---------------------------------------------------------------------------
# 2. Filter Rows Tests & All Operators
# ---------------------------------------------------------------------------


def test_filter_rows_delete_matching_status_inactive(employees_adapter: FakeAdapter) -> None:
    """Delete rows where Status equals Inactive (10 -> 7 rows)."""
    snapshot = employees_adapter.read_snapshot()
    params = FilterRowsParams(
        condition=Condition(column="Status", operator="equals", value="Inactive"),
        action="delete_matching",
    )
    patch = execute("filter_rows", snapshot, params)

    assert patch.op == "filter_rows"
    assert "(10 -> 7 rows)" in patch.summary
    assert "Deleted 3 rows" in patch.summary

    # Vacated rows 9, 10, 11 (rows 10, 11 in Excel) must be cleared (after=None)
    cleared_addrs = {c.address for c in patch.cells if c.after is None}
    assert any("9" in addr or "10" in addr or "11" in addr for addr in cleared_addrs)

    employees_adapter.apply_patch(patch)
    updated = employees_adapter.read_snapshot()
    statuses = [row[8] for row in updated.values[1:8]]
    assert all(s == "Active" for s in statuses)


def test_filter_rows_keep_matching(employees_adapter: FakeAdapter) -> None:
    """Keep only Engineering employees."""
    snapshot = employees_adapter.read_snapshot()
    params = FilterRowsParams(
        condition=Condition(column="Department", operator="equals", value="Engineering"),
        action="keep_matching",
    )
    patch = execute("filter_rows", snapshot, params)

    assert "(10 -> 3 rows)" in patch.summary
    assert "Kept 3 rows" in patch.summary


@pytest.mark.parametrize(
    ("operator", "value", "expected_matches"),
    [
        ("equals", "Sales", 2),
        ("not_equals", "Sales", 8),
        ("contains", "Engin", 3),
        ("not_contains", "Sales", 8),
        ("starts_with", "Mark", 2),
        ("ends_with", "ing", 5),  # Marketing (2) + Engineering (3)
    ],
)
def test_filter_operators_text(
    employees_adapter: FakeAdapter, operator: str, value: str, expected_matches: int
) -> None:
    snapshot = employees_adapter.read_snapshot()
    params = FilterRowsParams(
        condition=Condition(column="Department", operator=operator, value=value),
        action="keep_matching",
    )
    patch = execute("filter_rows", snapshot, params)
    assert f"Kept {expected_matches} rows" in patch.summary


@pytest.mark.parametrize(
    ("operator", "value", "expected_matches"),
    [
        ("greater_than", 60000, 5),
        ("less_than", 50000, 2),
        ("greater_or_equal", 78000, 3),  # 78000 (2x), 83000 (1x)
        ("less_or_equal", 52000, 3),
    ],
)
def test_filter_operators_numeric(
    employees_adapter: FakeAdapter, operator: str, value: float, expected_matches: int
) -> None:
    snapshot = employees_adapter.read_snapshot()
    params = FilterRowsParams(
        condition=Condition(column="Salary", operator=operator, value=value),
        action="keep_matching",
    )
    patch = execute("filter_rows", snapshot, params)
    assert f"Kept {expected_matches} rows" in patch.summary


def test_filter_operators_date(employees_adapter: FakeAdapter) -> None:
    """Filter using date comparisons."""
    snapshot = employees_adapter.read_snapshot()
    params = FilterRowsParams(
        condition=Condition(column="Join Date", operator="greater_than", value="2022-01-01"),
        action="keep_matching",
    )
    patch = execute("filter_rows", snapshot, params)
    # Join dates > 2022-01-01: Carlos Mendez (2022-01-10), Aisha Khan (2023-05-22), Sara Lee (2024-06-03) -> 3
    assert "Kept 3 rows" in patch.summary


def test_filter_operators_blank(employees_adapter: FakeAdapter) -> None:
    """Filter rows where City is blank / not blank."""
    snapshot = employees_adapter.read_snapshot()
    # is_blank on City (Carlos Mendez and Tom O'Brien have None)
    params_blank = FilterRowsParams(
        condition=Condition(column="City", operator="is_blank"),
        action="keep_matching",
    )
    patch_blank = execute("filter_rows", snapshot, params_blank)
    assert "Kept 2 rows" in patch_blank.summary

    params_not_blank = FilterRowsParams(
        condition=Condition(column="City", operator="is_not_blank"),
        action="keep_matching",
    )
    patch_not_blank = execute("filter_rows", snapshot, params_not_blank)
    assert "Kept 8 rows" in patch_not_blank.summary


# ---------------------------------------------------------------------------
# 3. Remove Duplicates Tests
# ---------------------------------------------------------------------------


def test_remove_duplicates_keep_first(employees_adapter: FakeAdapter) -> None:
    """Dedupe on Email keeping first: keeps Emp ID 102, removes 107."""
    snapshot = employees_adapter.read_snapshot()
    params = RemoveDuplicatesParams(columns=["Email"], keep="first")
    patch = execute("remove_duplicates", snapshot, params)

    assert "(10 -> 9 rows)" in patch.summary
    assert "Removed 1 duplicate row(s)" in patch.summary

    employees_adapter.apply_patch(patch)
    updated = employees_adapter.read_snapshot()
    emp_ids = [row[0] for row in updated.values[1:10]]
    assert 102 in emp_ids
    assert 107 not in emp_ids


def test_remove_duplicates_keep_last(employees_adapter: FakeAdapter) -> None:
    """Dedupe on Email keeping last: keeps Emp ID 107, removes 102."""
    snapshot = employees_adapter.read_snapshot()
    params = RemoveDuplicatesParams(columns=["Email"], keep="last")
    patch = execute("remove_duplicates", snapshot, params)

    assert "(10 -> 9 rows)" in patch.summary
    employees_adapter.apply_patch(patch)
    updated = employees_adapter.read_snapshot()
    emp_ids = [row[0] for row in updated.values[1:10]]
    assert 107 in emp_ids
    assert 102 not in emp_ids


def test_remove_duplicates_whole_rows(employees_adapter: FakeAdapter) -> None:
    """Dedupe comparing whole rows when columns is empty list."""
    snapshot = employees_adapter.read_snapshot()
    params = RemoveDuplicatesParams(columns=[], keep="first")
    patch = execute("remove_duplicates", snapshot, params)

    # In employees.xlsx, Emp 102 and 107 differ by ID, so all rows are unique
    assert len(patch.cells) == 0
    assert "No duplicate rows found" in patch.summary


# ---------------------------------------------------------------------------
# 4. Column Operations Tests (Insert, Delete, Rename, Move)
# ---------------------------------------------------------------------------


def test_insert_column_end(employees_adapter: FakeAdapter) -> None:
    """Insert column at end with fill value."""
    snapshot = employees_adapter.read_snapshot()
    params = InsertColumnParams(header="Notes", position="end", fill_value="N/A")
    patch = execute("insert_column", snapshot, params)

    assert patch.op == "insert_column"
    # Column K is 11th column
    assert any(c.address == "K1" and c.after == "Notes" for c in patch.cells)
    assert any(c.address == "K2" and c.after == "N/A" for c in patch.cells)


def test_insert_column_after(employees_adapter: FakeAdapter) -> None:
    """Insert column called Bonus after Salary."""
    snapshot = employees_adapter.read_snapshot()
    params = InsertColumnParams(
        header="Bonus",
        position="after",
        reference_column="Salary",
        fill_value="1000",
    )
    patch = execute("insert_column", snapshot, params)

    # Salary is F (6), so new column is G (7)
    assert any(c.address == "G1" and c.after == "Bonus" for c in patch.cells)
    assert any(c.address == "G2" and c.after == "1000" for c in patch.cells)
    # Former G (Join Date) shifts to H
    assert any(c.address == "H1" and c.after == "Join Date" for c in patch.cells)


def test_insert_column_before(employees_adapter: FakeAdapter) -> None:
    """Insert column before Full Name."""
    snapshot = employees_adapter.read_snapshot()
    params = InsertColumnParams(
        header="Title",
        position="before",
        reference_column="Full Name",
    )
    patch = execute("insert_column", snapshot, params)

    # Full Name is B (2), so Title is inserted at B, Full Name moves to C
    assert any(c.address == "B1" and c.after == "Title" for c in patch.cells)
    assert any(c.address == "C1" and c.after == "Full Name" for c in patch.cells)


def test_delete_column(employees_adapter: FakeAdapter) -> None:
    """Delete the Rating column (J)."""
    snapshot = employees_adapter.read_snapshot()
    params = DeleteColumnParams(column="Rating")
    patch = execute("delete_column", snapshot, params)

    assert patch.op == "delete_column"
    assert "Deleted column 'Rating' (J)" in patch.summary
    # Column J must be cleared
    assert any(c.address == "J1" and c.after is None for c in patch.cells)
    assert any(c.address == "J2" and c.after is None for c in patch.cells)


def test_rename_column(employees_adapter: FakeAdapter) -> None:
    """Rename Emp ID to Employee ID."""
    snapshot = employees_adapter.read_snapshot()
    params = RenameColumnParams(column="Emp ID", new_header="Employee ID")
    patch = execute("rename_column", snapshot, params)

    assert patch.op == "rename_column"
    assert len(patch.cells) == 1
    assert patch.cells[0].address == "A1"
    assert patch.cells[0].before == "Emp ID"
    assert patch.cells[0].after == "Employee ID"


def test_move_column_before_after_start_end(employees_adapter: FakeAdapter) -> None:
    """Test move column before, after, start, and end."""
    snapshot = employees_adapter.read_snapshot()

    # Move Email (D) before Full Name (B)
    patch_before = execute(
        "move_column",
        snapshot,
        MoveColumnParams(column="Email", position="before", reference_column="Full Name"),
    )
    assert any(c.address == "B1" and c.after == "Email" for c in patch_before.cells)

    # Move Email (D) after Full Name (B) -> becomes C
    patch_after = execute(
        "move_column",
        snapshot,
        MoveColumnParams(column="Email", position="after", reference_column="Full Name"),
    )
    assert any(c.address == "C1" and c.after == "Email" for c in patch_after.cells)

    # Move City (H) to start -> becomes A
    patch_start = execute(
        "move_column",
        snapshot,
        MoveColumnParams(column="City", position="start"),
    )
    assert any(c.address == "A1" and c.after == "City" for c in patch_start.cells)

    # Move Emp ID (A) to end -> becomes J
    patch_end = execute(
        "move_column",
        snapshot,
        MoveColumnParams(column="Emp ID", position="end"),
    )
    assert any(c.address == "J1" and c.after == "Emp ID" for c in patch_end.cells)


# ---------------------------------------------------------------------------
# 5. Fill Blanks Tests
# ---------------------------------------------------------------------------


def test_fill_blanks_value(employees_adapter: FakeAdapter) -> None:
    """Fill empty City cells with Unknown."""
    snapshot = employees_adapter.read_snapshot()
    params = FillBlanksParams(column="City", mode="value", value="Unknown")
    patch = execute("fill_blanks", snapshot, params)

    assert patch.op == "fill_blanks"
    assert "Filled 2 blank cell(s) in City with 'Unknown'" in patch.summary
    addrs = {c.address: c.after for c in patch.cells}
    # Row 4 (Carlos Mendez) and Row 7 (Tom O'Brien) have None in City
    assert addrs.get("H4") == "Unknown"
    assert addrs.get("H7") == "Unknown"


def test_fill_blanks_down(employees_adapter: FakeAdapter) -> None:
    """Fill blanks down in City (forward fill)."""
    snapshot = employees_adapter.read_snapshot()
    params = FillBlanksParams(column="City", mode="down")
    patch = execute("fill_blanks", snapshot, params)

    assert "Filled 2 blank cell(s) down in City" in patch.summary
    addrs = {c.address: c.after for c in patch.cells}
    # H4 fills from H3 (Pune), H7 fills from H6 (Seattle)
    assert addrs.get("H4") == "Pune"
    assert addrs.get("H7") == "Seattle"


def test_fill_blanks_up(employees_adapter: FakeAdapter) -> None:
    """Fill blanks up in City (backward fill)."""
    snapshot = employees_adapter.read_snapshot()
    params = FillBlanksParams(column="City", mode="up")
    patch = execute("fill_blanks", snapshot, params)

    assert "Filled 2 blank cell(s) up in City" in patch.summary
    addrs = {c.address: c.after for c in patch.cells}
    # H4 fills from H5 (Chicago), H7 fills from H8 (Pune)
    assert addrs.get("H4") == "Chicago"
    assert addrs.get("H7") == "Pune"


# ---------------------------------------------------------------------------
# 6. Highlight Cells Tests
# ---------------------------------------------------------------------------


def test_highlight_cells_single_column(employees_adapter: FakeAdapter) -> None:
    """Highlight salaries above 60000 in green."""
    snapshot = employees_adapter.read_snapshot()
    params = HighlightCellsParams(
        condition=Condition(column="Salary", operator="greater_than", value=60000),
        color="green",
        whole_row=False,
    )
    patch = execute("highlight_cells", snapshot, params)

    assert patch.op == "highlight_cells"
    assert len(patch.formats) == 5
    assert all(fmt.fill_hex == "#C6EFCE" for fmt in patch.formats)
    # Target column is F
    assert all(fmt.address.startswith("F") for fmt in patch.formats)


def test_highlight_cells_whole_row(employees_adapter: FakeAdapter) -> None:
    """Highlight Inactive rows in red."""
    snapshot = employees_adapter.read_snapshot()
    params = HighlightCellsParams(
        condition=Condition(column="Status", operator="equals", value="Inactive"),
        color="red",
        whole_row=True,
    )
    patch = execute("highlight_cells", snapshot, params)

    # 3 inactive rows * 10 columns = 30 format changes
    assert len(patch.formats) == 30
    assert all(fmt.fill_hex == "#FFC7CE" for fmt in patch.formats)


@pytest.mark.parametrize(
    ("color_name", "expected_hex"),
    [
        ("yellow", "#FFF2CC"),
        ("green", "#C6EFCE"),
        ("red", "#FFC7CE"),
        ("orange", "#F8CBAD"),
        ("blue", "#DDEBF7"),
        ("none", None),
    ],
)
def test_highlight_color_palette(
    employees_adapter: FakeAdapter, color_name: str, expected_hex: str | None
) -> None:
    """Verify all 6 colors in palette."""
    snapshot = employees_adapter.read_snapshot()
    params = HighlightCellsParams(
        condition=Condition(column="Status", operator="equals", value="Inactive"),
        color=color_name,
    )
    patch = execute("highlight_cells", snapshot, params)
    assert all(fmt.fill_hex == expected_hex for fmt in patch.formats)


def test_highlight_cells_multiple_conditions_whole_row(employees_adapter: FakeAdapter) -> None:
    """Highlight rows matching multiple criteria: Engineering AND Salary > 80000."""
    snapshot = employees_adapter.read_snapshot()
    params = HighlightCellsParams(
        conditions=[
            Condition(column="Department", operator="equals", value="Engineering"),
            Condition(column="Salary", operator="greater_than", value="80000"),
        ],
        color="yellow",
        whole_row=True,
    )
    patch = execute("highlight_cells", snapshot, params)

    # Only 1 employee (Li Wei: Engineering, 83000) matches both conditions -> 10 cells in row 6
    assert patch.op == "highlight_cells"
    assert len(patch.formats) == 10
    assert all(fmt.fill_hex == "#FFF2CC" for fmt in patch.formats)
    assert all(fmt.address.endswith("6") for fmt in patch.formats)
    assert "Engineering" in patch.summary and "Salary" in patch.summary


def test_filter_rows_multiple_conditions(employees_adapter: FakeAdapter) -> None:
    """Filter rows with multiple criteria: delete matching Inactive AND Finance."""
    snapshot = employees_adapter.read_snapshot()
    params = FilterRowsParams(
        conditions=[
            Condition(column="Status", operator="equals", value="Inactive"),
            Condition(column="Department", operator="equals", value="Finance"),
        ],
        action="delete_matching",
    )
    patch = execute("filter_rows", snapshot, params)

    # 1 row deleted (Tom O'Brien: Finance + Inactive)
    assert patch.op == "filter_rows"
    assert "Deleted 1 rows" in patch.summary
    assert "Inactive" in patch.summary and "Finance" in patch.summary


def test_highlight_cells_split_condition_and_conditions(employees_adapter: FakeAdapter) -> None:
    """Verify that if LLM provides both condition and conditions, both are merged and evaluated."""
    snapshot = employees_adapter.read_snapshot()
    # Provide condition as Department=Engineering, and conditions as [Salary > 80000]
    raw = {
        "condition": {"column": "Department", "operator": "equals", "value": "Engineering"},
        "conditions": [{"column": "Salary", "operator": "greater_than", "value": "80000"}],
        "color": "yellow",
        "whole_row": True,
    }
    params = HighlightCellsParams.model_validate(raw)
    assert len(params.conditions) == 2

    patch = execute("highlight_cells", snapshot, params)
    # Only Li Wei matches both conditions -> 10 cells in row 6
    assert patch.op == "highlight_cells"
    assert len(patch.formats) == 10
    assert all(fmt.address.endswith("6") for fmt in patch.formats)


# ---------------------------------------------------------------------------
# 7. Formulas Preservation and Unknown Columns
# ---------------------------------------------------------------------------


def test_formula_preserved_with_warning() -> None:
    """Formulas move as formula text and emit proof-of-concept warning."""
    # Build a small sheet with a formula in column C
    rows = [
        ["Item", "Price", "Tax"],
        ["Widget", 100, "=B2*0.1"],
        ["Gadget", 200, "=B3*0.1"],
    ]
    adapter = FakeAdapter(rows=rows)
    snapshot = adapter.read_snapshot()

    # Sort Price descending -> Widget and Gadget will swap
    params = SortRowsParams(by_column="Price", descending=True)
    patch = execute("sort_rows", snapshot, params)

    assert FORMULA_MOVE_WARNING in patch.warnings
    # Gadget (200) is now row 2, Widget (100) is now row 3
    assert any(c.address == "C2" and c.after_formula == "=B3*0.1" for c in patch.cells)


def test_unknown_column_raises_target_error(employees_adapter: FakeAdapter) -> None:
    """Unknown column name raises TargetError listing valid headers."""
    snapshot = employees_adapter.read_snapshot()
    params = SortRowsParams(by_column="NonExistent")

    with pytest.raises(TargetError) as exc_info:
        execute("sort_rows", snapshot, params)

    assert "Valid headers are:" in str(exc_info.value)
    assert "'Salary'" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 8. Merged Cells Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merged_cells_refusal(employees_adapter: FakeAdapter) -> None:
    """Structural operations refuse when sheet has merged cells."""
    adapter = FakeAdapter(file_path=EMPLOYEES_PATH, has_merged_cells=True)
    snapshot = adapter.read_snapshot()
    assert snapshot.has_merged_cells is True

    spec = REGISTRY["sort_rows"]
    assert spec.validator is not None

    patch = execute("sort_rows", snapshot, SortRowsParams(by_column="Salary"))
    errors, _ = await spec.validator(snapshot, SortRowsParams(by_column="Salary"), patch, adapter)

    assert len(errors) == 1
    assert "merged cells" in errors[0].lower()

