"""Unit tests for cell value formatting and JSON serialization."""

from datetime import date, datetime

from backend.excel.values import display_value, from_jsonable, to_jsonable


def test_display_value_none() -> None:
    assert display_value(None) == ""


def test_display_value_bool() -> None:
    assert display_value(True) == "TRUE"
    assert display_value(False) == "FALSE"


def test_display_value_numbers() -> None:
    assert display_value(52000.0) == "52000"
    assert display_value(52000) == "52000"
    assert display_value(4.2) == "4.2"
    assert display_value(0.0) == "0"
    assert display_value(0) == "0"


def test_display_value_dates() -> None:
    dt = datetime(2021, 3, 4, 14, 30)
    d = date(2021, 3, 4)
    assert display_value(dt) == "2021-03-04"
    assert display_value(d) == "2021-03-04"


def test_display_value_strings() -> None:
    assert display_value("hello") == "hello"
    assert display_value("  spaces  ") == "  spaces  "


def test_to_and_from_jsonable_primitive() -> None:
    data = {"num": 42, "text": "sample", "flag": True, "none": None}
    encoded = to_jsonable(data)
    decoded = from_jsonable(encoded)
    assert decoded == data


def test_to_and_from_jsonable_datetime() -> None:
    dt = datetime(2023, 5, 22, 12, 0, 0)
    data = {"date": dt}
    encoded = to_jsonable(data)
    assert encoded == {"date": {"$date": dt.isoformat()}}

    decoded = from_jsonable(encoded)
    assert decoded == {"date": dt}


def test_to_and_from_jsonable_nested_lists() -> None:
    dt1 = datetime(2021, 1, 1, 10, 0)
    dt2 = datetime(2022, 2, 2, 20, 0)
    grid = [
        [101, "Alice", dt1],
        [102, "Bob", dt2],
    ]
    encoded = to_jsonable(grid)
    assert encoded == [
        [101, "Alice", {"$date": dt1.isoformat()}],
        [102, "Bob", {"$date": dt2.isoformat()}],
    ]
    decoded = from_jsonable(encoded)
    assert decoded == grid

