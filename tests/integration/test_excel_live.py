"""Integration tests with a live Microsoft Excel instance."""

from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest

from backend.excel.com_thread import com_thread
from backend.excel.xlwings_adapter import XlwingsAdapter
from backend.ops.formula_ops import handle_add_formula_column, validate_formula_op
from backend.schemas.intent import AddFormulaColumnParams
from backend.schemas.patch import CellChange, FormatChange, Patch


@pytest.fixture
def live_adapter() -> Generator[XlwingsAdapter, None, None]:
    fixture_path = Path("tests/fixtures/employees.xlsx").resolve()
    adapter = XlwingsAdapter(book_path=fixture_path)
    try:
        yield adapter
    finally:
        adapter.close()


@pytest.mark.excel
def test_live_excel_round_trip(live_adapter: XlwingsAdapter) -> None:
    # 1. Describe
    desc = live_adapter.describe()
    assert desc["connected"] is True
    assert desc["sheet"] == "Employees"

    # 2. Read snapshot
    snapshot = live_adapter.read_snapshot()
    assert snapshot.used_range == "A1:J11"
    assert snapshot.headers[0] == "Emp ID"
    assert snapshot.headers[1] == "Full Name"
    # Row 2 (index 1 in values) col B is "  john smith "
    assert "john smith" in str(snapshot.values[1][1])

    # 3. Read region before change
    orig_region = live_adapter.read_region("B2:B3")
    val_b2_orig = orig_region.values[0][0]
    val_b3_orig = orig_region.values[1][0]

    # 4. Apply patch
    patch = Patch(
        op="change_case",
        sheet=snapshot.sheet,
        cells=[
            CellChange(address="B2", before=val_b2_orig, after="UPPER JOHN"),
            CellChange(address="B3", before=val_b3_orig, after="UPPER PRIYA"),
        ],
        formats=[
            FormatChange(address="B2", fill_hex="#FFFF00"),
        ],
        summary="Uppercase test",
    )
    live_adapter.apply_patch(patch)

    # 5. Read back modified values and check
    mod_values = live_adapter.read_values("B2:B3")
    assert mod_values[0][0] == "UPPER JOHN"
    assert mod_values[1][0] == "UPPER PRIYA"

    # 6. Restore original region
    live_adapter.restore_region(orig_region)

    # 7. Verify restored values
    restored_values = live_adapter.read_values("B2:B3")
    assert restored_values[0][0] == val_b2_orig
    assert restored_values[1][0] == val_b3_orig


@pytest.fixture
async def sales_live_adapter() -> AsyncGenerator[XlwingsAdapter, None]:
    fixture_path = Path("tests/fixtures/sales.xlsx").resolve()
    adapter = await com_thread.run(XlwingsAdapter, book_path=fixture_path)
    try:
        yield adapter
    finally:
        await com_thread.run(adapter.close)


@pytest.mark.excel
@pytest.mark.asyncio
async def test_live_excel_formula_trial_run_div_zero_and_success(
    sales_live_adapter: XlwingsAdapter,
) -> None:
    snapshot = await com_thread.run(sales_live_adapter.read_snapshot)

    # 1. Trial run of =D2/0 is detected as #DIV/0! and sheet is restored exactly
    orig_region = await com_thread.run(sales_live_adapter.read_region, "K1:K11")
    params_div0 = AddFormulaColumnParams(new_header="DivZero", formula="=D2/0")
    patch_div0 = handle_add_formula_column(snapshot, params_div0)

    errors, _ = await validate_formula_op(
        snapshot, params_div0, patch_div0, sales_live_adapter
    )
    assert any("#DIV/0!" in e for e in errors)

    # Verify sheet is restored exactly as before
    restored_region = await com_thread.run(sales_live_adapter.read_region, "K1:K11")
    assert restored_region.values == orig_region.values
    assert restored_region.formulas == orig_region.formulas

    # 2. A valid formula yields correct preview_values
    params_valid = AddFormulaColumnParams(new_header="Total", formula="=D2*E2")
    patch_valid = handle_add_formula_column(snapshot, params_valid)

    val_errors, updated_patch = await validate_formula_op(
        snapshot, params_valid, patch_valid, sales_live_adapter
    )
    assert val_errors == []
    # K2 preview_value is 2 * 850 = 1700
    assert updated_patch.preview_values["K2"] in (1700, 1700.0)
    # K3 preview_value is 15 * 12.5 = 187.5
    assert updated_patch.preview_values["K3"] == 187.5

