"""Pure functions for Tier 1 text operations on single cell values."""

import math
import re
from datetime import date, datetime
from typing import Literal

from backend.schemas.sheet import CellValue


def _format_number_text(val: float) -> str:
    """Format number to text, omitting .0 for whole numbers."""
    if isinstance(val, float):
        if math.isnan(val):
            return "NaN"
        if val.is_integer():
            return str(int(val))
        return str(val)
    return str(val)


def split_words(text: str) -> list[str]:
    """Split text into words handling delimiters, camelCase, acronyms, and digits."""
    if not text:
        return []
    # Step 1: Split acronyms preceding titlecase/lowercase: e.g. "HTTPServer" -> "HTTP Server"
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    # Step 2: Split lowercase/digits preceding uppercase: e.g. "camelCase" -> "camel Case"
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    # Step 3: Split letters followed by digits: e.g. "Address2" -> "Address 2"
    s = re.sub(r"([a-zA-Z])([0-9])", r"\1 \2", s)
    # Step 4: Split digits followed by letters: e.g. "2ndAddress" -> "2 ndAddress"
    s = re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", s)
    # Step 5: Replace all delimiters [ _\-.] and non-alphanumeric chars with spaces
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)
    return [w for w in s.split() if w]


def to_upper(val: CellValue) -> CellValue:
    """Convert string to uppercase. Non-string values are returned unchanged."""
    if not isinstance(val, str):
        return val
    return val.upper()


def to_lower(val: CellValue) -> CellValue:
    """Convert string to lowercase. Non-string values are returned unchanged."""
    if not isinstance(val, str):
        return val
    return val.lower()


def to_title(val: CellValue) -> CellValue:
    """Convert string to title case (PROPER). Non-string values are returned unchanged."""
    if not isinstance(val, str):
        return val
    return val.title()


def to_sentence(val: CellValue) -> CellValue:
    """Convert string to sentence case. Non-string values are returned unchanged."""
    if not isinstance(val, str):
        return val
    if not val.strip():
        return val

    # Split into sentence segments preserving delimiters like '. ', '! ', '? '
    parts = re.split(r"([.!?]+\s+)", val)
    result: list[str] = []
    for part in parts:
        if re.match(r"^[.!?]+\s+$", part):
            result.append(part)
        else:
            match = re.search(r"[a-zA-Z]", part)
            if match:
                idx = match.start()
                cased = part[:idx] + part[idx].upper() + part[idx + 1:].lower()
                result.append(cased)
            else:
                result.append(part)
    return "".join(result)


def to_camel(val: CellValue) -> CellValue:
    """Convert string to camelCase (e.g. 'Full Name' -> 'fullName')."""
    if not isinstance(val, str):
        return val
    words = split_words(val)
    if not words:
        return ""
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])


def to_snake(val: CellValue) -> CellValue:
    """Convert string to snake_case (e.g. 'Full Name' -> 'full_name')."""
    if not isinstance(val, str):
        return val
    words = split_words(val)
    if not words:
        return ""
    return "_".join(w.lower() for w in words)


def to_pascal(val: CellValue) -> CellValue:
    """Convert string to PascalCase (e.g. 'Full Name' -> 'FullName')."""
    if not isinstance(val, str):
        return val
    words = split_words(val)
    if not words:
        return ""
    return "".join(w.capitalize() for w in words)


def to_kebab(val: CellValue) -> CellValue:
    """Convert string to kebab-case (e.g. 'Full Name' -> 'full-name')."""
    if not isinstance(val, str):
        return val
    words = split_words(val)
    if not words:
        return ""
    return "-".join(w.lower() for w in words)


def trim_whitespace(val: CellValue) -> CellValue:
    """Strip leading/trailing spaces and collapse internal runs of spaces/tabs/NBSP."""
    if not isinstance(val, str):
        return val
    stripped = val.strip(" \t\n\r\u00a0")
    return re.sub(r"[ \t\u00a0]+", " ", stripped)


def find_replace(
    val: CellValue,
    find: str,
    replace: str,
    match_case: bool = False,
    whole_cell: bool = False,
) -> CellValue:
    """Find and replace text or number substrings/whole cells."""
    if val is None or isinstance(val, (datetime, date, bool)):
        return val

    if isinstance(val, (int, float)):
        if isinstance(val, float) and math.isnan(val):
            return val
        text = _format_number_text(val)
    elif isinstance(val, str):
        text = val
    else:
        return val

    if not find:
        return val

    if whole_cell:
        matches = (text == find) if match_case else (text.lower() == find.lower())
        if matches:
            return replace
        return val

    if match_case:
        if find in text:
            return text.replace(find, replace)
        return val

    pattern = re.escape(find)
    new_text, count = re.subn(pattern, replace, text, flags=re.IGNORECASE)
    if count > 0:
        return new_text
    return val


def add_prefix_suffix(
    val: CellValue,
    prefix: str = "",
    suffix: str = "",
) -> CellValue:
    """Add prefix and/or suffix to text or number values."""
    if val is None or isinstance(val, (datetime, date, bool)):
        return val

    if isinstance(val, (int, float)):
        if isinstance(val, float) and math.isnan(val):
            return val
        text = _format_number_text(val)
    elif isinstance(val, str):
        text = val
    else:
        return val

    if not prefix and not suffix:
        return val

    return f"{prefix}{text}{suffix}"


def remove_characters(
    val: CellValue,
    remove: Literal["special", "digits", "letters", "non_digits", "custom"],
    custom_chars: str = "",
) -> CellValue:
    """Remove specified category of characters from text. Non-strings return unchanged."""
    if not isinstance(val, str):
        return val

    if remove == "special":
        # Keep letters, digits, and whitespace; remove symbols, punctuation, and '_'
        return "".join(c for c in val if c.isalnum() or c.isspace())

    if remove == "digits":
        return "".join(c for c in val if not c.isdigit())

    if remove == "letters":
        return "".join(c for c in val if not c.isalpha())

    if remove == "non_digits":
        # Keeps only 0-9
        return "".join(c for c in val if c.isdigit())

    if remove == "custom":
        remove_set = set(custom_chars)
        return "".join(c for c in val if c not in remove_set)

    return val
