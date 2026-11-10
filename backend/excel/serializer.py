"""Serialization of SheetSnapshot to prompt text and target resolution."""

import math
from datetime import date, datetime

from backend.excel.a1 import iter_range, parse_range
from backend.excel.adapter import TargetError
from backend.schemas.intent import Target
from backend.schemas.sheet import CellValue, SheetSnapshot


def _format_cell_prompt(val: CellValue, formula: str | None) -> str:
    """Format single cell for model prompt following section 8 rules."""
    if formula is not None and isinstance(formula, str) and formula.startswith("="):
        f_text = formula
        if len(f_text) > 40:
            f_text = f_text[:37] + "..."
        return f"{{{f_text}}}"

    if val is None or val == "":
        return "(empty)"

    if isinstance(val, (datetime, date)):
        formatted = val.strftime("%Y-%m-%d")
    elif isinstance(val, bool):
        formatted = "TRUE" if val else "FALSE"
    elif isinstance(val, float):
        if math.isnan(val):
            return "(empty)"
        if val.is_integer():
            formatted = str(int(val))
        else:
            formatted = str(val)
    elif isinstance(val, int):
        formatted = str(val)
    else:
        formatted = str(val)

    # Cut at 40 characters with ...
    if len(formatted) > 40:
        formatted = formatted[:37] + "..."

    # Quote text that has leading, trailing or repeated spaces or contains '|'
    if (
        formatted.startswith(" ")
        or formatted.endswith(" ")
        or "  " in formatted
        or "|" in formatted
    ):
        formatted = f'"{formatted}"'

    return formatted


def snapshot_to_prompt(snapshot: SheetSnapshot, max_rows: int = 50) -> str:
    """Convert SheetSnapshot to plain text representation for LLM prompts."""
    r1, _c1, r2, _c2 = parse_range(snapshot.used_range)
    total_data_rows = max(0, r2 - snapshot.header_row)

    if total_data_rows == 0:
        data_rows_str = "none"
    else:
        data_rows_str = f"{snapshot.header_row + 1}-{r2}"

    selection_str = snapshot.selection if snapshot.selection else "none"

    lines: list[str] = []
    # Line 1: Summary header
    lines.append(
        f'Sheet "{snapshot.sheet}" | used range {snapshot.used_range} | '
        f"header row {snapshot.header_row} | data rows {data_rows_str} | "
        f"selection: {selection_str}"
    )

    # Line 2: Columns mapping
    col_pairs: list[str] = []
    for col, header in zip(snapshot.columns, snapshot.headers, strict=False):
        h_text = header if header else "(empty)"
        col_pairs.append(f"{col}={h_text}")
    lines.append("Columns: " + ", ".join(col_pairs))

    # Line 3: Table column letters
    lines.append("Row | " + " | ".join(snapshot.columns))

    # Line 4: Header row values
    header_idx = snapshot.header_row - r1
    header_row_vals: list[str] = []
    if 0 <= header_idx < len(snapshot.values):
        for c_idx in range(len(snapshot.columns)):
            val = (
                snapshot.values[header_idx][c_idx]
                if c_idx < len(snapshot.values[header_idx])
                else None
            )
            form = (
                snapshot.formulas[header_idx][c_idx]
                if c_idx < len(snapshot.formulas[header_idx])
                else None
            )
            header_row_vals.append(_format_cell_prompt(val, form))
    else:
        header_row_vals = [
            _format_cell_prompt(h, None) for h in snapshot.headers
        ]

    lines.append(f"{snapshot.header_row} | " + " | ".join(header_row_vals))

    # Data rows (up to max_rows)
    data_row_start = snapshot.header_row + 1
    rows_to_render = min(total_data_rows, max_rows)

    for offset in range(rows_to_render):
        curr_row = data_row_start + offset
        row_idx = curr_row - r1
        row_vals: list[str] = []
        if 0 <= row_idx < len(snapshot.values):
            for c_idx in range(len(snapshot.columns)):
                val = (
                    snapshot.values[row_idx][c_idx]
                    if c_idx < len(snapshot.values[row_idx])
                    else None
                )
                form = (
                    snapshot.formulas[row_idx][c_idx]
                    if c_idx < len(snapshot.formulas[row_idx])
                    else None
                )
                row_vals.append(_format_cell_prompt(val, form))
        else:
            row_vals = ["(empty)" for _ in snapshot.columns]
        lines.append(f"{curr_row} | " + " | ".join(row_vals))

    # Pagination notice if more rows exist
    if total_data_rows > max_rows:
        remaining = total_data_rows - max_rows
        lines.append(f"(... {remaining} more rows not shown)")

    return "\n".join(lines)


def resolve_column_letter(snapshot: SheetSnapshot, col_spec: str) -> str:
    """Resolve a column specification (letter or header name) to column letter."""
    cleaned = col_spec.strip()

    # Try column letter first
    if cleaned.upper() in snapshot.columns:
        return cleaned.upper()

    # Try matching header name case-insensitively
    norm_spec = cleaned.lower()
    for col, header in zip(snapshot.columns, snapshot.headers, strict=False):
        if header and header.strip().lower() == norm_spec:
            return col

    # Try matching header name ignoring spaces and underscores (e.g. orderStatus vs Order Status)
    fuzzy_spec = norm_spec.replace(" ", "").replace("_", "")
    for col, header in zip(snapshot.columns, snapshot.headers, strict=False):
        if header and header.strip().lower().replace(" ", "").replace("_", "") == fuzzy_spec:
            return col

    # Try column index if integer string
    if cleaned.isdigit():
        idx = int(cleaned)
        if 1 <= idx <= len(snapshot.columns):
            return snapshot.columns[idx - 1]

    valid = [f"'{h}'" for h in snapshot.headers if h]
    raise TargetError(
        f"Column '{col_spec}' not found. Valid headers are: {', '.join(valid)}."
    )


_resolve_column_letter = resolve_column_letter


def resolve_target(snapshot: SheetSnapshot, target: Target) -> list[str]:
    """Resolve target specification to a list of concrete cell addresses."""
    _r1, _c1, r2, _c2 = parse_range(snapshot.used_range)

    if target.kind == "columns":
        if not target.columns:
            raise TargetError("No columns specified for target.")

        matched_cols = [
            _resolve_column_letter(snapshot, c) for c in target.columns
        ]

        data_row_start = snapshot.header_row + 1
        addresses: list[str] = []
        for r in range(data_row_start, r2 + 1):
            for col in matched_cols:
                addresses.append(f"{col}{r}")
        return addresses

    if target.kind == "headers":
        if not target.columns:
            return [f"{col}{snapshot.header_row}" for col in snapshot.columns]

        matched_cols = [
            _resolve_column_letter(snapshot, c) for c in target.columns
        ]
        return [f"{col}{snapshot.header_row}" for col in matched_cols]

    if target.kind == "range":
        if not target.range:
            raise TargetError("Range target requires a range specification.")
        return iter_range(target.range)

    if target.kind == "selection":
        if not snapshot.selection:
            raise TargetError("No cells are currently selected.")
        return iter_range(snapshot.selection)

    raise TargetError(f"Unknown target kind: '{target.kind}'.")
