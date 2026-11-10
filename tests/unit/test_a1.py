"""Unit tests for Excel A1 notation helpers."""

import pytest

from backend.excel.a1 import (
    bounding_range,
    col_to_index,
    index_to_col,
    iter_range,
    make_range,
    parse_cell,
    parse_range,
)


def test_col_to_index() -> None:
    assert col_to_index("A") == 1
    assert col_to_index("B") == 2
    assert col_to_index("Z") == 26
    assert col_to_index("AA") == 27
    assert col_to_index("AB") == 28
    assert col_to_index("$B") == 2
    assert col_to_index("  $c  ") == 3

    with pytest.raises(ValueError):
        col_to_index("")
    with pytest.raises(ValueError):
        col_to_index("123")
    with pytest.raises(ValueError):
        col_to_index("A1")


def test_index_to_col() -> None:
    assert index_to_col(1) == "A"
    assert index_to_col(2) == "B"
    assert index_to_col(26) == "Z"
    assert index_to_col(27) == "AA"
    assert index_to_col(28) == "AB"

    with pytest.raises(ValueError):
        index_to_col(0)
    with pytest.raises(ValueError):
        index_to_col(-5)


def test_parse_cell() -> None:
    assert parse_cell("A1") == (1, 1)
    assert parse_cell("$B$3") == (3, 2)
    assert parse_cell("b3") == (3, 2)
    assert parse_cell("AB28") == (28, 28)

    with pytest.raises(ValueError):
        parse_cell("A0")
    with pytest.raises(ValueError):
        parse_cell("123")
    with pytest.raises(ValueError):
        parse_cell("AAA")
    with pytest.raises(ValueError):
        parse_cell("A1:B2")


def test_parse_range() -> None:
    assert parse_range("A1:J11") == (1, 1, 11, 10)
    assert parse_range("$A$1:$J$11") == (1, 1, 11, 10)
    assert parse_range("J11:A1") == (1, 1, 11, 10)
    # Single cell is a 1x1 range
    assert parse_range("B3") == (3, 2, 3, 2)
    assert parse_range("$B$3") == (3, 2, 3, 2)

    with pytest.raises(ValueError):
        parse_range("A1:B2:C3")
    with pytest.raises(ValueError):
        parse_range("invalid")


def test_make_range() -> None:
    assert make_range(1, 1, 11, 10) == "A1:J11"
    assert make_range(11, 10, 1, 1) == "A1:J11"
    assert make_range(3, 2, 3, 2) == "B3"

    with pytest.raises(ValueError):
        make_range(0, 1, 2, 2)


def test_iter_range() -> None:
    assert iter_range("A1:B2") == ["A1", "B1", "A2", "B2"]
    assert iter_range("B3") == ["B3"]
    assert iter_range("C1:C3") == ["C1", "C2", "C3"]
    assert iter_range("A1:C1") == ["A1", "B1", "C1"]


def test_bounding_range() -> None:
    assert bounding_range(["A1", "C4", "B2"]) == "A1:C4"
    assert bounding_range(["B3"]) == "B3"
    assert bounding_range(["$B$3", "$C$4"]) == "B3:C4"

    with pytest.raises(ValueError):
        bounding_range([])

