"""Unit tests for pure Tier 1 text operations."""

from datetime import date, datetime

import pytest

from backend.ops.text_ops import (
    add_prefix_suffix,
    find_replace,
    remove_characters,
    to_camel,
    to_kebab,
    to_lower,
    to_pascal,
    to_sentence,
    to_snake,
    to_title,
    to_upper,
    trim_whitespace,
)

# ---------------------------------------------------------------------------
# Case style tests (at least 8 cases per style)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("Full Name", "fullName"),
        ("emp_id", "empId"),
        ("  join   date ", "joinDate"),
        ("HTTPServer", "httpServer"),
        ("already camelCase", "alreadyCamelCase"),
        ("Order-ID", "orderId"),
        ("Address 2", "address2"),
        ("", ""),
        ("simple", "simple"),
        ("first_name_2", "firstName2"),
    ],
)
def test_to_camel(input_val: str, expected: str) -> None:
    assert to_camel(input_val) == expected


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("Full Name", "full_name"),
        ("fullName", "full_name"),
        ("emp_id", "emp_id"),
        ("  join   date ", "join_date"),
        ("HTTPServer", "http_server"),
        ("already camelCase", "already_camel_case"),
        ("Order-ID", "order_id"),
        ("Address 2", "address_2"),
        ("", ""),
        ("Address2", "address_2"),
    ],
)
def test_to_snake(input_val: str, expected: str) -> None:
    assert to_snake(input_val) == expected


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("Full Name", "FullName"),
        ("fullName", "FullName"),
        ("emp_id", "EmpId"),
        ("  join   date ", "JoinDate"),
        ("HTTPServer", "HttpServer"),
        ("already camelCase", "AlreadyCamelCase"),
        ("Order-ID", "OrderId"),
        ("Address 2", "Address2"),
        ("", ""),
        ("address_2", "Address2"),
    ],
)
def test_to_pascal(input_val: str, expected: str) -> None:
    assert to_pascal(input_val) == expected


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("Full Name", "full-name"),
        ("fullName", "full-name"),
        ("emp_id", "emp-id"),
        ("  join   date ", "join-date"),
        ("HTTPServer", "http-server"),
        ("already camelCase", "already-camel-case"),
        ("Order-ID", "order-id"),
        ("Address 2", "address-2"),
        ("", ""),
        ("Address2", "address-2"),
    ],
)
def test_to_kebab(input_val: str, expected: str) -> None:
    assert to_kebab(input_val) == expected


def test_case_styles_non_string_passthrough() -> None:
    today = date(2021, 3, 4)
    now = datetime(2021, 3, 4, 12, 0, 0)
    for fn in (to_camel, to_snake, to_pascal, to_kebab, to_upper, to_lower, to_title, to_sentence):
        assert fn(101) == 101
        assert fn(4.2) == 4.2
        assert fn(None) is None
        assert fn(today) == today
        assert fn(now) == now
        assert fn(True) is True


# ---------------------------------------------------------------------------
# Basic Case (upper, lower, title, sentence)
# ---------------------------------------------------------------------------


def test_to_upper() -> None:
    assert to_upper("sales") == "SALES"
    assert to_upper("Sales Dept") == "SALES DEPT"
    assert to_upper("") == ""


def test_to_lower() -> None:
    assert to_lower("SALES") == "sales"
    assert to_lower("Sales Dept") == "sales dept"
    assert to_lower("") == ""


def test_to_title() -> None:
    assert to_title("priya sharma") == "Priya Sharma"
    assert to_title("PRIYA SHARMA") == "Priya Sharma"
    assert to_title("  john smith ") == "  John Smith "
    assert to_title("li wei") == "Li Wei"


def test_to_sentence() -> None:
    assert to_sentence("urgent delivery") == "Urgent delivery"
    assert to_sentence("PRIYA SHARMA") == "Priya sharma"
    assert to_sentence("bulk order. urgent delivery.") == "Bulk order. Urgent delivery."
    assert to_sentence("  spaces before") == "  Spaces before"
    assert to_sentence("") == ""
    assert to_sentence("   ") == "   "


# ---------------------------------------------------------------------------
# Trim Whitespace
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("  john smith ", "john smith"),
        ("carlos  mendez", "carlos mendez"),
        ("Sara  Lee ", "Sara Lee"),
        ("\tjoin\t\tdate\t", "join date"),
        ("\u00a0hello\u00a0\u00a0world\u00a0", "hello world"),
        ("\t  mixed\u00a0 \tspaces  ", "mixed spaces"),
        ("   ", ""),
        ("", ""),
    ],
)
def test_trim_whitespace(input_val: str, expected: str) -> None:
    assert trim_whitespace(input_val) == expected


def test_trim_whitespace_non_strings() -> None:
    assert trim_whitespace(101) == 101
    assert trim_whitespace(52000.0) == 52000.0
    assert trim_whitespace(None) is None
    d = date(2021, 3, 4)
    assert trim_whitespace(d) == d


# ---------------------------------------------------------------------------
# Find & Replace
# ---------------------------------------------------------------------------


def test_find_replace_case_insensitive_default() -> None:
    assert find_replace("Inactive", "inactive", "Former") == "Former"
    assert find_replace("Active and Inactive", "inactive", "Former") == "Active and Former"
    assert find_replace("New York", "new york", "NYC") == "NYC"


def test_find_replace_match_case() -> None:
    assert find_replace("Inactive", "inactive", "Former", match_case=True) == "Inactive"
    assert find_replace("inactive", "inactive", "Former", match_case=True) == "Former"


def test_find_replace_whole_cell() -> None:
    assert find_replace("New York City", "New York", "NYC", whole_cell=True) == "New York City"
    assert find_replace("New York", "New York", "NYC", whole_cell=True) == "NYC"
    assert find_replace("new york", "New York", "NYC", match_case=True, whole_cell=True) == "new york"
    assert find_replace("new york", "New York", "NYC", match_case=False, whole_cell=True) == "NYC"


def test_find_replace_numbers() -> None:
    # Numbers format without .0 and return text when replaced
    assert find_replace(101, "10", "99") == "991"
    assert find_replace(101.0, "101", "202") == "202"
    assert find_replace(4.2, "4", "5") == "5.2"
    # Unmatched numbers return original number unchanged (avoiding false CellChanges)
    assert find_replace(101, "foo", "bar") == 101
    assert find_replace(4.2, "9", "8") == 4.2


def test_find_replace_non_strings() -> None:
    assert find_replace(None, "a", "b") is None
    d = date(2021, 3, 4)
    assert find_replace(d, "2021", "2022") == d
    assert find_replace(True, "True", "False") is True
    assert find_replace("Same", "", "New") == "Same"


# ---------------------------------------------------------------------------
# Add Prefix / Suffix
# ---------------------------------------------------------------------------


def test_add_prefix_suffix_strings() -> None:
    assert add_prefix_suffix("New York", suffix=" (HQ)") == "New York (HQ)"
    assert add_prefix_suffix("101", prefix="EMP-") == "EMP-101"
    assert add_prefix_suffix("Item", prefix="[", suffix="]") == "[Item]"
    assert add_prefix_suffix("Noop") == "Noop"


def test_add_prefix_suffix_numbers() -> None:
    assert add_prefix_suffix(101, prefix="EMP-") == "EMP-101"
    assert add_prefix_suffix(52000.0, prefix="$") == "$52000"
    assert add_prefix_suffix(4.2, suffix="/5.0") == "4.2/5.0"


def test_add_prefix_suffix_non_strings() -> None:
    assert add_prefix_suffix(None, prefix="EMP-") is None
    d = date(2021, 3, 4)
    assert add_prefix_suffix(d, prefix="Date: ") == d
    assert add_prefix_suffix(True, prefix="is_") is True


# ---------------------------------------------------------------------------
# Remove Characters
# ---------------------------------------------------------------------------


def test_remove_characters_special() -> None:
    # "special" = anything that is not a letter, digit or space
    assert remove_characters("(555) 123-4567", "special") == "555 1234567"
    assert remove_characters("hello_world#1!", "special") == "helloworld1"
    assert remove_characters("carlos  mendez", "special") == "carlos  mendez"


def test_remove_characters_digits() -> None:
    assert remove_characters("Emp 101", "digits") == "Emp "
    assert remove_characters("Order-1234", "digits") == "Order-"


def test_remove_characters_letters() -> None:
    assert remove_characters("SO-1001", "letters") == "-1001"
    assert remove_characters("abc 123", "letters") == " 123"


def test_remove_characters_non_digits() -> None:
    # "non_digits" keeps only 0-9
    assert remove_characters("(555) 123-4567", "non_digits") == "5551234567"
    assert remove_characters("+1 555 444 5555", "non_digits") == "15554445555"
    assert remove_characters("555.987.6543", "non_digits") == "5559876543"


def test_remove_characters_custom() -> None:
    assert (
        remove_characters("carlos.mendez@acme.com", "custom", custom_chars="@.")
        == "carlosmendezacmecom"
    )
    assert remove_characters("foo-bar_baz", "custom", custom_chars="-_") == "foobarbaz"


def test_remove_characters_non_strings() -> None:
    assert remove_characters(101, "digits") == 101
    assert remove_characters(None, "special") is None
    d = date(2021, 3, 4)
    assert remove_characters(d, "non_digits") == d
