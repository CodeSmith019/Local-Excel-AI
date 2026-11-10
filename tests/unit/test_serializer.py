"""Unit tests for sheet serialization to LLM prompt format."""

from backend.excel.serializer import snapshot_to_prompt
from backend.schemas.sheet import SheetSnapshot


def test_snapshot_to_prompt_golden_small() -> None:
    snapshot = SheetSnapshot(
        workbook="test.xlsx",
        sheet="Mini",
        used_range="A1:B3",
        header_row=1,
        columns=["A", "B"],
        headers=["Name", "Age"],
        values=[
            ["Name", "Age"],
            ["Alice", 30],
            ["Bob", 25],
        ],
        formulas=[
            [None, None],
            [None, None],
            [None, None],
        ],
        selection=None,
    )

    expected = (
        'Sheet "Mini" | used range A1:B3 | header row 1 | data rows 2-3 | selection: none\n'
        "Columns: A=Name, B=Age\n"
        "Row | A | B\n"
        "1 | Name | Age\n"
        "2 | Alice | 30\n"
        "3 | Bob | 25"
    )
    result = snapshot_to_prompt(snapshot)
    assert result == expected


def test_snapshot_to_prompt_quoting_rules() -> None:
    snapshot = SheetSnapshot(
        workbook="test.xlsx",
        sheet="Quotes",
        used_range="A1:D2",
        header_row=1,
        columns=["A", "B", "C", "D"],
        headers=["Col1", "Col2", "Col3", "Col4"],
        values=[
            ["Col1", "Col2", "Col3", "Col4"],
            ["  leading", "trailing  ", "middle  space", "pipe|char"],
        ],
        formulas=[
            [None, None, None, None],
            [None, None, None, None],
        ],
        selection="A2:B2",
    )

    result = snapshot_to_prompt(snapshot)
    assert '2 | "  leading" | "trailing  " | "middle  space" | "pipe|char"' in result
    assert "selection: A2:B2" in result


def test_snapshot_to_prompt_empty_and_formulas() -> None:
    snapshot = SheetSnapshot(
        workbook="test.xlsx",
        sheet="Formulas",
        used_range="A1:C2",
        header_row=1,
        columns=["A", "B", "C"],
        headers=["Qty", "Price", "Total"],
        values=[
            ["Qty", "Price", ""],
            [10, None, 100],
        ],
        formulas=[
            [None, None, None],
            [None, None, "=A2*B2"],
        ],
    )

    result = snapshot_to_prompt(snapshot)
    assert "1 | Qty | Price | (empty)" in result
    assert "2 | 10 | (empty) | {=A2*B2}" in result


def test_snapshot_to_prompt_truncation() -> None:
    long_text = "This is a very long text string that definitely exceeds forty characters in total length."
    snapshot = SheetSnapshot(
        workbook="test.xlsx",
        sheet="Long",
        used_range="A1:A2",
        header_row=1,
        columns=["A"],
        headers=["Description"],
        values=[
            ["Description"],
            [long_text],
        ],
        formulas=[
            [None],
            [None],
        ],
    )

    result = snapshot_to_prompt(snapshot)
    # 40 chars total: 37 chars + "..."
    truncated = long_text[:37] + "..."
    assert f"2 | {truncated}" in result


def test_snapshot_to_prompt_max_rows_pagination() -> None:
    values = [["Index"]] + [[i] for i in range(1, 11)]
    formulas = [[None]] * 11
    snapshot = SheetSnapshot(
        workbook="test.xlsx",
        sheet="Numbers",
        used_range="A1:A11",
        header_row=1,
        columns=["A"],
        headers=["Index"],
        values=values,
        formulas=formulas,
    )

    result = snapshot_to_prompt(snapshot, max_rows=3)
    assert "1 | Index" in result
    assert "2 | 1" in result
    assert "3 | 2" in result
    assert "4 | 3" in result
    assert "5 | 4" not in result
    assert "(... 7 more rows not shown)" in result

