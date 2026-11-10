"""Unit tests for FakeAdapter in-memory workbook simulation."""

from pathlib import Path

from backend.excel.fake_adapter import FakeAdapter
from backend.schemas.patch import CellChange, FormatChange, Patch


def test_fake_adapter_basic_crud() -> None:
    rows = [
        ["Name", "Score"],
        ["Alice", 90],
        ["Bob", 85],
    ]
    adapter = FakeAdapter(sheet_name="Scores", rows=rows)

    # 1. Describe
    desc = adapter.describe()
    assert desc["connected"] is True
    assert desc["sheet"] == "Scores"

    # 2. Read snapshot
    snap = adapter.read_snapshot()
    assert snap.sheet == "Scores"
    assert snap.used_range == "A1:B3"
    assert snap.columns == ["A", "B"]
    assert snap.headers == ["Name", "Score"]
    assert snap.values == rows

    # 3. Read region
    region = adapter.read_region("A2:B3")
    assert region.region == "A2:B3"
    assert region.values == [["Alice", 90], ["Bob", 85]]

    # 4. Apply patch
    patch = Patch(
        op="test_op",
        sheet="Scores",
        cells=[
            CellChange(address="A2", before="Alice", after="ALICE"),
            CellChange(address="B2", before=90, after=None, after_formula="=100-10"),
        ],
        formats=[
            FormatChange(address="A2", fill_hex="#00FF00"),
        ],
        summary="Test change",
    )
    adapter.apply_patch(patch)
    assert len(adapter.applied_patches) == 1

    # 5. Read back values
    vals = adapter.read_values("A2:B2")
    assert vals == [["ALICE", "=100-10"]]

    # 6. Restore region round-trip
    adapter.restore_region(region)
    vals_restored = adapter.read_values("A2:B3")
    assert vals_restored == [["Alice", 90], ["Bob", 85]]


def test_fake_adapter_from_fixture_file() -> None:
    fixture_path = Path("tests/fixtures/employees.xlsx")
    assert fixture_path.exists()

    adapter = FakeAdapter(file_path=fixture_path)
    desc = adapter.describe()
    assert desc["connected"] is True
    assert desc["sheet"] == "Employees"

    snapshot = adapter.read_snapshot()
    assert snapshot.used_range == "A1:J11"
    assert "Emp ID" in snapshot.headers
    assert "Salary" in snapshot.headers
    assert len(snapshot.values) == 11

