"""Pure functions for Excel A1 notation calculations.

All functions strip '$' and uppercase column names.
Invalid inputs raise ValueError.
"""

import re
from collections.abc import Iterable

_CELL_REGEX = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


def col_to_index(col: str) -> int:
    """Convert column letter to 1-based index (e.g. 'A' -> 1, 'Z' -> 26, 'AB' -> 28)."""
    clean = col.replace("$", "").strip().upper()
    if not clean or not clean.isalpha():
        raise ValueError(f"Invalid column name: {col!r}")

    idx = 0
    for ch in clean:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def index_to_col(idx: int) -> str:
    """Convert 1-based column index to column letter (e.g. 1 -> 'A', 28 -> 'AB')."""
    if idx < 1:
        raise ValueError(f"Column index must be >= 1, got {idx}")

    result: list[str] = []
    curr = idx
    while curr > 0:
        curr -= 1
        result.append(chr(ord("A") + (curr % 26)))
        curr //= 26
    return "".join(reversed(result))


def parse_cell(addr: str) -> tuple[int, int]:
    """Parse cell address to 1-based (row, col) (e.g. '$B$3' -> (3, 2))."""
    clean = addr.replace("$", "").strip().upper()
    match = _CELL_REGEX.match(clean)
    if not match:
        raise ValueError(f"Invalid cell address: {addr!r}")

    col_str, row_str = match.groups()
    return int(row_str), col_to_index(col_str)


def parse_range(rng: str) -> tuple[int, int, int, int]:
    """Parse range or cell address to 1-based (min_r, min_c, max_r, max_c).

    Single cells return a 1x1 range (e.g. 'B3' -> (3, 2, 3, 2)).
    'A1:J11' -> (1, 1, 11, 10).
    """
    clean = rng.replace("$", "").strip().upper()
    if ":" in clean:
        parts = clean.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid range address: {rng!r}")
        r1, c1 = parse_cell(parts[0])
        r2, c2 = parse_cell(parts[1])
        return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)

    r, c = parse_cell(clean)
    return r, c, r, c


def make_range(r1: int, c1: int, r2: int, c2: int) -> str:
    """Create an A1 range string from coordinates.

    If r1==r2 and c1==c2, returns a single cell address like 'A1'.
    Otherwise returns 'A1:J11'.
    """
    if r1 < 1 or c1 < 1 or r2 < 1 or c2 < 1:
        raise ValueError(f"Coordinates must be >= 1: ({r1}, {c1}, {r2}, {c2})")

    min_r, max_r = min(r1, r2), max(r1, r2)
    min_c, max_c = min(c1, c2), max(c1, c2)

    col1 = index_to_col(min_c)
    if min_r == max_r and min_c == max_c:
        return f"{col1}{min_r}"

    col2 = index_to_col(max_c)
    return f"{col1}{min_r}:{col2}{max_r}"


def iter_range(range_str: str) -> list[str]:
    """Iterate through all addresses in a range row by row (e.g. 'A1:B2' -> ['A1', 'B1', 'A2', 'B2'])."""
    r1, c1, r2, c2 = parse_range(range_str)
    addresses: list[str] = []
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            addresses.append(f"{index_to_col(c)}{r}")
    return addresses


def bounding_range(addresses: Iterable[str]) -> str:
    """Find the bounding A1 range covering all given addresses."""
    addr_list = list(addresses)
    if not addr_list:
        raise ValueError("No addresses provided to bounding_range")

    min_r = min_c = float("inf")
    max_r = max_c = float("-inf")

    for addr in addr_list:
        r, c = parse_cell(addr)
        min_r = min(min_r, r)
        max_r = max(max_r, r)
        min_c = min(min_c, c)
        max_c = max(max_c, c)

    return make_range(int(min_r), int(min_c), int(max_r), int(max_c))
