"""Unit tests for Tier 1 operation registry and execution with FakeAdapter."""

from pathlib import Path

import pytest

from backend.excel.adapter import OpError, TargetError
from backend.excel.fake_adapter import FakeAdapter
from backend.ops.registry import execute, implemented_ops
from backend.schemas.intent import (
    AddPrefixSuffixParams,
    ChangeCaseParams,
    ConvertCaseStyleParams,
    FindReplaceParams,
    RemoveCharactersParams,
    Target,
    TrimWhitespaceParams,
)


@pytest.fixture
def employees_snapshot():
    """Load employees.xlsx snapshot using FakeAdapter."""
    fixture_path = Path("tests/fixtures/employees.xlsx")
    assert fixture_path.exists(), "employees.xlsx fixture missing"
    adapter = FakeAdapter(file_path=fixture_path)
    return adapter.read_snapshot()


def test_implemented_ops_count_and_tier() -> None:
    """Verify registry lists the six Tier 1 operations."""
    tier1_ops = [spec for spec in implemented_ops() if spec.tier == 1]
    assert len(tier1_ops) == 6
    expected_names = {
        "change_case",
        "convert_case_style",
        "trim_whitespace",
        "find_replace",
        "add_prefix_suffix",
        "remove_characters",
    }
    assert {spec.name for spec in tier1_ops} == expected_names
    for spec in tier1_ops:
        assert spec.tier == 1
        assert spec.title
        assert spec.description
        assert len(spec.examples) > 0


def test_convert_headers_to_camel_case(employees_snapshot) -> None:
    """Test converting all headers to camelCase."""
    params = ConvertCaseStyleParams(
        target=Target(kind="headers"),
        style="camel",
    )
    patch = execute("convert_case_style", employees_snapshot, params)

    assert patch.op == "convert_case_style"
    assert patch.sheet == "Employees"
    assert len(patch.cells) == 10
    assert patch.summary == "Converted 10 headers to camelCase"

    # Check expected transformed headers
    changes = {c.address: c.after for c in patch.cells}
    assert changes["A1"] == "empId"
    assert changes["B1"] == "fullName"
    assert changes["C1"] == "department"
    assert changes["D1"] == "email"
    assert changes["E1"] == "phone"
    assert changes["F1"] == "salary"
    assert changes["G1"] == "joinDate"
    assert changes["H1"] == "city"
    assert changes["I1"] == "status"
    assert changes["J1"] == "rating"

    # Ensure no data rows were touched
    for c in patch.cells:
        assert c.address.endswith("1")


def test_trim_whitespace_full_name(employees_snapshot) -> None:
    """Test trim whitespace on Full Name column changes exactly B2, B4, and B11."""
    params = TrimWhitespaceParams(
        target=Target(kind="columns", columns=["Full Name"]),
    )
    patch = execute("trim_whitespace", employees_snapshot, params)

    assert patch.op == "trim_whitespace"
    assert len(patch.cells) == 3

    changed_addrs = [c.address for c in patch.cells]
    assert changed_addrs == ["B2", "B4", "B11"]

    assert patch.cells[0].before == "  john smith "
    assert patch.cells[0].after == "john smith"

    assert patch.cells[1].before == "carlos  mendez"
    assert patch.cells[1].after == "carlos mendez"

    assert patch.cells[2].before == "Sara  Lee "
    assert patch.cells[2].after == "Sara Lee"


def test_change_case_upper(employees_snapshot) -> None:
    """Test change case to upper on Department column.

    Note: C9 is 'HR', which is already uppercase, so only 9 cells change.
    """
    params = ChangeCaseParams(
        target=Target(kind="columns", columns=["Department"]),
        mode="upper",
    )
    patch = execute("change_case", employees_snapshot, params)

    assert patch.op == "change_case"
    assert len(patch.cells) == 9
    changed_addresses = {change.address for change in patch.cells}
    assert "C9" not in changed_addresses  # 'HR' already uppercase
    for change in patch.cells:
        assert change.address.startswith("C")
        assert change.after == change.before.upper()


def test_change_case_title(employees_snapshot) -> None:
    """Test change case to title on Full Name."""
    params = ChangeCaseParams(
        target=Target(kind="columns", columns=["Full Name"]),
        mode="title",
    )
    patch = execute("change_case", employees_snapshot, params)

    # In employees fixture:
    # B3: "PRIYA SHARMA" -> "Priya Sharma"
    # B6: "li wei" -> "Li Wei"
    # B8: "priya sharma" -> "Priya Sharma"
    # B10: "raj patel" -> "Raj Patel"
    changes = {c.address: c.after for c in patch.cells}
    assert "B3" in changes and changes["B3"] == "Priya Sharma"
    assert "B6" in changes and changes["B6"] == "Li Wei"
    assert "B8" in changes and changes["B8"] == "Priya Sharma"
    assert "B10" in changes and changes["B10"] == "Raj Patel"


def test_find_replace_inactive_to_former(employees_snapshot) -> None:
    """Test find & replace on Status column replacing Inactive with Former."""
    params = FindReplaceParams(
        target=Target(kind="columns", columns=["Status"]),
        find="Inactive",
        replace="Former",
    )
    patch = execute("find_replace", employees_snapshot, params)

    assert patch.op == "find_replace"
    # Row 4 (carlos mendez), Row 7 (tom obrien), Row 11 (sara lee) have Status 'Inactive'
    assert len(patch.cells) == 3
    assert [c.address for c in patch.cells] == ["I4", "I7", "I11"]
    for c in patch.cells:
        assert c.before == "Inactive"
        assert c.after == "Former"


def test_add_prefix_suffix_emp_id(employees_snapshot) -> None:
    """Test adding prefix EMP- to numbers in Emp ID column."""
    params = AddPrefixSuffixParams(
        target=Target(kind="columns", columns=["Emp ID"]),
        prefix="EMP-",
    )
    patch = execute("add_prefix_suffix", employees_snapshot, params)

    assert patch.op == "add_prefix_suffix"
    assert len(patch.cells) == 10
    for idx, c in enumerate(patch.cells):
        expected_emp = 101 + idx
        assert c.address == f"A{idx + 2}"
        assert c.before == expected_emp
        assert c.after == f"EMP-{expected_emp}"


def test_remove_characters_non_digits(employees_snapshot) -> None:
    """Test removing non-digits from Phone column.

    Note: E6 is '5556667777', which already contains only digits, so 9 cells change.
    """
    params = RemoveCharactersParams(
        target=Target(kind="columns", columns=["Phone"]),
        remove="non_digits",
    )
    patch = execute("remove_characters", employees_snapshot, params)

    assert patch.op == "remove_characters"
    assert len(patch.cells) == 9
    changed_addresses = {c.address for c in patch.cells}
    assert "E6" not in changed_addresses  # already only digits
    changes = {c.address: c.after for c in patch.cells}
    assert changes["E2"] == "5551234567"
    assert changes["E3"] == "5559876543"
    assert changes["E5"] == "15554445555"


def test_execute_with_dict_params(employees_snapshot) -> None:
    """Test execute dispatcher automatically validates dict params."""
    params_dict = {
        "target": {"kind": "headers"},
        "style": "snake",
    }
    patch = execute("convert_case_style", employees_snapshot, params_dict)
    assert patch.op == "convert_case_style"
    changes = {c.address: c.after for c in patch.cells}
    assert changes["A1"] == "emp_id"
    assert changes["B1"] == "full_name"


def test_execute_error_conditions(employees_snapshot) -> None:
    """Test OpError and TargetError raised appropriately."""
    # 1. Unknown op
    with pytest.raises(OpError, match="Unknown operation 'non_existent_op'"):
        execute("non_existent_op", employees_snapshot, {})

    # 2. Wrong params type
    with pytest.raises(OpError, match="Params for 'trim_whitespace' must be TrimWhitespaceParams"):
        execute(
            "trim_whitespace",
            employees_snapshot,
            ChangeCaseParams(target=Target(kind="headers"), mode="upper"),
        )

    # 3. Invalid dict params
    with pytest.raises(OpError, match="Invalid parameters for 'change_case'"):
        execute("change_case", employees_snapshot, {"target": {"kind": "headers"}, "mode": "invalid_mode"})

    # 4. TargetError for nonexistent column
    with pytest.raises(TargetError, match="Column 'NonExistent' not found"):
        execute(
            "trim_whitespace",
            employees_snapshot,
            TrimWhitespaceParams(target=Target(kind="columns", columns=["NonExistent"])),
        )


def test_no_changes_produces_empty_patch_cells(employees_snapshot) -> None:
    """Test that if an op produces no changes, patch.cells is empty."""
    # Trim on Rating column (which has numbers 4.2, 4.8, etc.)
    params = TrimWhitespaceParams(
        target=Target(kind="columns", columns=["Rating"]),
    )
    patch = execute("trim_whitespace", employees_snapshot, params)
    assert len(patch.cells) == 0
