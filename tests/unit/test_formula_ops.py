"""Unit tests for Tier 3 formula operations."""

from pathlib import Path

import pytest

from backend.excel.fake_adapter import FakeAdapter
from backend.ops.formula_ops import (
    handle_add_formula_column,
    handle_add_summary_formula,
    shift_relative_refs,
    static_check,
)
from backend.schemas.intent import AddFormulaColumnParams, AddSummaryFormulaParams

SALES_PATH = Path("tests/fixtures/sales.xlsx")


@pytest.fixture
def sales_adapter() -> FakeAdapter:
    """FakeAdapter preloaded with sales.xlsx."""
    return FakeAdapter(file_path=SALES_PATH)


# ---------------------------------------------------------------------------
# 1. shift_relative_refs tests
# ---------------------------------------------------------------------------


def test_shift_relative_refs_basic_arithmetic() -> None:
    """Relative references shift row numbers."""
    assert shift_relative_refs("=D2*E2", 9) == "=D11*E11"
    assert shift_relative_refs("=D2*E2", 0) == "=D2*E2"


def test_shift_relative_refs_anchors() -> None:
    """Fully anchored $A$2 and row-anchored A$2 remain unchanged; col-anchored $A2 shifts."""
    assert shift_relative_refs("=$A$2", 5) == "=$A$2"
    assert shift_relative_refs("=A$2", 5) == "=A$2"
    assert shift_relative_refs("=$A2", 5) == "=$A7"
    assert shift_relative_refs("=D2*E$2 + $A$2", 3) == "=D5*E$2 + $A$2"


def test_shift_relative_refs_ranges() -> None:
    """Ranges with relative endpoints shift both endpoints."""
    assert shift_relative_refs("=SUM(D2:D11)", 5) == "=SUM(D7:D16)"
    assert shift_relative_refs("=SUM(D$2:D$11)", 5) == "=SUM(D$2:D$11)"


def test_shift_relative_refs_multi_letter_columns() -> None:
    """Multi-letter columns (e.g. AA, XFD) shift rows properly."""
    assert shift_relative_refs("=AA2+AB2", 3) == "=AA5+AB5"
    assert shift_relative_refs("=$AA2+AA$2", 4) == "=$AA6+AA$2"


def test_shift_relative_refs_strings_untouched() -> None:
    """References inside string literals remain untouched."""
    formula = '="Total for D2 is: " & D2'
    assert shift_relative_refs(formula, 3) == '="Total for D2 is: " & D5'
    formula_quotes = '="D2" & D2 & " D2 "'
    assert shift_relative_refs(formula_quotes, 2) == '="D2" & D4 & " D2 "'


def test_shift_relative_refs_function_names_untouched() -> None:
    """Function names with numbers (e.g. LOG10) are not treated as cell references."""
    assert shift_relative_refs("=LOG10(A2)", 2) == "=LOG10(A4)"


# ---------------------------------------------------------------------------
# 2. static_check tests
# ---------------------------------------------------------------------------


def test_static_check_valid_formulas(sales_adapter: FakeAdapter) -> None:
    """Valid formulas pass static check."""
    snapshot = sales_adapter.read_snapshot()

    # Arithmetic
    assert static_check("=D2*E2", snapshot, target_col="K", row_wise=True) == []

    # IF condition
    assert (
        static_check(
            '=IF(H2="Yes","Done","Pending")',
            snapshot,
            target_col="K",
            row_wise=True,
        )
        == []
    )

    # Text manipulation
    assert (
        static_check(
            '=LEFT(TRIM(B2),FIND(" ",TRIM(B2))-1)',
            snapshot,
            target_col="K",
            row_wise=True,
        )
        == []
    )

    # Summary formulas (row_wise=False allows multi-row references)
    assert static_check("=SUM(D2:D11)", snapshot, target_col=None, row_wise=False) == []
    assert (
        static_check(
            '=COUNTIF(H2:H11,"Yes")',
            snapshot,
            target_col=None,
            row_wise=False,
        )
        == []
    )
    assert (
        static_check(
            '=SUMIF(B2:B11,"North",D2:D11)',
            snapshot,
            target_col=None,
            row_wise=False,
        )
        == []
    )


def test_static_check_must_start_with_equal(sales_adapter: FakeAdapter) -> None:
    """Formula must start with '='."""
    snapshot = sales_adapter.read_snapshot()
    errors = static_check("D2*E2", snapshot, target_col="K", row_wise=True)
    assert any("must start with '='" in e for e in errors)


def test_static_check_length_limit(sales_adapter: FakeAdapter) -> None:
    """Formula length must be less than 500 characters."""
    snapshot = sales_adapter.read_snapshot()
    long_formula = "=D2" + "+D2" * 200
    errors = static_check(long_formula, snapshot, target_col="K", row_wise=True)
    assert any("less than 500" in e for e in errors)


def test_static_check_unbalanced_quotes(sales_adapter: FakeAdapter) -> None:
    """Unbalanced double quotes trigger validation error."""
    snapshot = sales_adapter.read_snapshot()
    formula = '=IF(H2="Yes, "Done", "Pending")'
    errors = static_check(formula, snapshot, target_col="K", row_wise=True)
    assert any("unbalanced double quotes" in e for e in errors)


def test_static_check_unbalanced_parentheses(sales_adapter: FakeAdapter) -> None:
    """Unbalanced parentheses trigger validation error."""
    snapshot = sales_adapter.read_snapshot()
    errors_open = static_check("=SUM(D2:D11", snapshot, target_col=None, row_wise=False)
    assert any("unbalanced parentheses" in e for e in errors_open)

    errors_close = static_check("=SUM(D2:D11))", snapshot, target_col=None, row_wise=False)
    assert any("unbalanced parentheses" in e for e in errors_close)


def test_static_check_unknown_function(sales_adapter: FakeAdapter) -> None:
    """Disallowed function names trigger validation error."""
    snapshot = sales_adapter.read_snapshot()
    errors = static_check("=FOOBAR(D2)", snapshot, target_col="K", row_wise=True)
    assert any("Function 'FOOBAR' is not allowed" in e for e in errors)

    errors2 = static_check("=D2*XYZ(E2)", snapshot, target_col="K", row_wise=True)
    assert any("Function 'XYZ' is not allowed" in e for e in errors2)


def test_static_check_out_of_range_reference(sales_adapter: FakeAdapter) -> None:
    """References outside used range (A1:J11) trigger error."""
    snapshot = sales_adapter.read_snapshot()
    # Column X is outside table A-J
    errors_col = static_check("=D2*X2", snapshot, target_col="K", row_wise=True)
    assert any("Column 'X' is outside" in e for e in errors_col)

    # Row 99 is outside used range
    errors_row = static_check("=D99", snapshot, target_col="K", row_wise=False)
    assert any("Row 99" in e for e in errors_row)


def test_static_check_row_wise_relative_row(sales_adapter: FakeAdapter) -> None:
    """Row-wise formula must reference relative row 2 (or absolute rows)."""
    snapshot = sales_adapter.read_snapshot()
    errors = static_check("=D3*E3", snapshot, target_col="K", row_wise=True)
    assert any("must reference row 2" in e for e in errors)

    # Absolute row D$1 is permitted
    assert static_check("=D2*D$1", snapshot, target_col="K", row_wise=True) == []


def test_static_check_circular_reference(sales_adapter: FakeAdapter) -> None:
    """Formula cannot reference the target column."""
    snapshot = sales_adapter.read_snapshot()
    errors = static_check("=K2*2", snapshot, target_col="K", row_wise=True)
    assert any("circular reference" in e for e in errors)


# ---------------------------------------------------------------------------
# 3. Handler tests on sales fixture
# ---------------------------------------------------------------------------


def test_add_formula_column_handler(sales_adapter: FakeAdapter) -> None:
    """Total column creates header in K1 and shifted formulas in K2..K11."""
    snapshot = sales_adapter.read_snapshot()
    params = AddFormulaColumnParams(new_header="Total", formula="=D2*E2")
    patch = handle_add_formula_column(snapshot, params)

    assert patch.op == "add_formula_column"
    assert len(patch.cells) == 11  # 1 header + 10 data rows

    # K1 header
    assert patch.cells[0].address == "K1"
    assert patch.cells[0].after == "Total"
    assert patch.cells[0].after_formula is None

    # K2 first data row
    assert patch.cells[1].address == "K2"
    assert patch.cells[1].after_formula == "=D2*E2"

    # K11 last data row
    assert patch.cells[10].address == "K11"
    assert patch.cells[10].after_formula == "=D11*E11"


def test_add_summary_formula_handler(sales_adapter: FakeAdapter) -> None:
    """Summary formula places formula two rows below last row with optional label."""
    snapshot = sales_adapter.read_snapshot()
    params = AddSummaryFormulaParams(formula="=SUM(D2:D11)", label="Total Qty")
    patch = handle_add_summary_formula(snapshot, params)

    assert patch.op == "add_summary_formula"
    assert len(patch.cells) == 2  # label + formula

    # Label in C13 (left of D13)
    assert patch.cells[0].address == "C13"
    assert patch.cells[0].after == "Total Qty"
    assert patch.cells[0].after_formula is None

    # Formula in D13 (column D, row 11 + 2 = 13)
    assert patch.cells[1].address == "D13"
    assert patch.cells[1].after_formula == "=SUM(D2:D11)"
