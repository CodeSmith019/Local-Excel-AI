"""Utilities for formatting and JSON serialization of Excel cell values."""

import math
from datetime import date, datetime
from typing import Any

from backend.schemas.sheet import CellValue


def display_value(v: CellValue) -> str:
    """Format cell value for display and model prompts.

    - None -> ""
    - dates/datetimes -> YYYY-MM-DD
    - bools -> TRUE / FALSE
    - whole floats without .0 (e.g. 52000.0 -> "52000", 4.2 -> "4.2")
    - strings -> unchanged
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    return str(v)


def to_jsonable(obj: Any) -> Any:
    """Recursively encode structures, turning datetimes into {'$date': iso}."""
    if isinstance(obj, datetime):
        return {"$date": obj.isoformat()}
    if isinstance(obj, date):
        dt = datetime(obj.year, obj.month, obj.day)
        return {"$date": dt.isoformat()}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(item) for item in obj]
    return obj


def from_jsonable(obj: Any) -> Any:
    """Recursively decode structures, turning {'$date': iso} back into datetime."""
    if isinstance(obj, dict):
        if len(obj) == 1 and "$date" in obj and isinstance(obj["$date"], str):
            return datetime.fromisoformat(obj["$date"])
        return {k: from_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [from_jsonable(item) for item in obj]
    return obj
