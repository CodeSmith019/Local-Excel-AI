"""Handlers for Tier 2 structural spreadsheet operations."""

import math
from datetime import date, datetime
from typing import Any

from backend.excel.a1 import col_to_index, index_to_col
from backend.excel.adapter import OpError, TargetError
from backend.excel.serializer import resolve_column_letter
from backend.schemas.intent import (
    Condition,
    DeleteColumnParams,
    FillBlanksParams,
    FilterRowsParams,
    HighlightCellsParams,
    InsertColumnParams,
    MoveColumnParams,
    RemoveDuplicatesParams,
    RenameColumnParams,
    SortRowsParams,
)
from backend.schemas.patch import CellChange, FormatChange, Patch
from backend.schemas.sheet import CellValue, SheetSnapshot

COLOR_MAP: dict[str, str | None] = {
    "yellow": "#FFF2CC",
    "green": "#C6EFCE",
    "red": "#FFC7CE",
    "orange": "#F8CBAD",
    "blue": "#DDEBF7",
    "none": None,
}

FORMULA_MOVE_WARNING = "Formulas were moved but their references were not updated"


# ---------------------------------------------------------------------------
# Value Parsing and Condition Evaluation Helpers
# ---------------------------------------------------------------------------


def is_blank(val: CellValue) -> bool:
    """Return True if value is None or whitespace-only text."""
    return val is None or bool(isinstance(val, str) and not val.strip())


def parse_number(val: Any) -> float | None:
    """Parse a value to float if possible, distinguishing bools and NaNs."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and math.isnan(val):
            return None
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def parse_date(val: Any) -> date | None:
    """Parse a value to date if possible."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        try:
            return date.fromisoformat(cleaned[:10])
        except (ValueError, TypeError):
            return None
    return None


def evaluate_condition(cell_val: CellValue, condition: Condition) -> bool:
    """Evaluate condition on a cell value according to type precedence:

    1. is_blank / is_not_blank
    2. numeric comparison when both sides parse as numbers
    3. date comparison when both sides parse as dates
    4. otherwise case-insensitive text after trimming
    """
    op = condition.operator

    if op == "is_blank":
        return is_blank(cell_val)
    if op == "is_not_blank":
        return not is_blank(cell_val)

    # If cell is blank but operator is something else
    if is_blank(cell_val):
        if op == "equals":
            return is_blank(condition.value)
        if op == "not_equals":
            return not is_blank(condition.value)
        return False

    # Check numeric comparison
    num_cell = parse_number(cell_val)
    num_target = parse_number(condition.value)
    if num_cell is not None and num_target is not None:
        if op == "equals":
            return num_cell == num_target
        if op == "not_equals":
            return num_cell != num_target
        if op == "greater_than":
            return num_cell > num_target
        if op == "less_than":
            return num_cell < num_target
        if op == "greater_or_equal":
            return num_cell >= num_target
        if op == "less_or_equal":
            return num_cell <= num_target
        # Substring operators on numbers
        s_c = str(cell_val).strip().lower()
        s_t = str(condition.value).strip().lower()
        if op == "contains":
            return s_t in s_c
        if op == "not_contains":
            return s_t not in s_c
        if op == "starts_with":
            return s_c.startswith(s_t)
        if op == "ends_with":
            return s_c.endswith(s_t)

    # Check date comparison
    date_cell = parse_date(cell_val)
    date_target = parse_date(condition.value)
    if date_cell is not None and date_target is not None:
        if op == "equals":
            return date_cell == date_target
        if op == "not_equals":
            return date_cell != date_target
        if op == "greater_than":
            return date_cell > date_target
        if op == "less_than":
            return date_cell < date_target
        if op == "greater_or_equal":
            return date_cell >= date_target
        if op == "less_or_equal":
            return date_cell <= date_target

    # Otherwise case-insensitive text after trimming
    s_cell = str(cell_val).strip().lower()
    s_target = str(condition.value if condition.value is not None else "").strip().lower()

    if op == "equals":
        return s_cell == s_target
    if op == "not_equals":
        return s_cell != s_target
    if op == "contains":
        return s_target in s_cell
    if op == "not_contains":
        return s_target not in s_cell
    if op == "starts_with":
        return s_cell.startswith(s_target)
    if op == "ends_with":
        return s_cell.endswith(s_target)
    if op == "greater_than":
        return s_cell > s_target
    if op == "less_than":
        return s_cell < s_target
    if op == "greater_or_equal":
        return s_cell >= s_target
    if op == "less_or_equal":
        return s_cell <= s_target

    return False


def _make_sort_key(val: CellValue) -> tuple[int, Any]:
    """Create a sort key handling mixed types safely: numeric, date, text, blank."""
    if is_blank(val):
        return (3, "")
    num = parse_number(val)
    if num is not None:
        return (0, num)
    d = parse_date(val)
    if d is not None:
        return (1, d)
    return (2, str(val).strip().lower())


def _make_dedupe_key(row_vals: list[CellValue], indices: list[int]) -> tuple[Any, ...]:
    """Create a comparison key for deduplicating rows."""
    key: list[tuple[int, Any]] = []
    for idx in indices:
        v = row_vals[idx] if idx < len(row_vals) else None
        if is_blank(v):
            key.append((0, None))
        else:
            num = parse_number(v)
            if num is not None:
                key.append((1, num))
            else:
                d = parse_date(v)
                if d is not None:
                    key.append((2, d))
                else:
                    key.append((3, str(v).strip().lower()))
    return tuple(key)


# ---------------------------------------------------------------------------
# Tier 2 Handlers
# ---------------------------------------------------------------------------


def handle_sort_rows(snapshot: SheetSnapshot, params: SortRowsParams) -> Patch:
    """Sort data rows by primary column and optional secondary column."""
    if not isinstance(params, SortRowsParams):
        raise OpError(f"Expected SortRowsParams, got {type(params).__name__}")

    col1_letter = resolve_column_letter(snapshot, params.by_column)
    col1_idx = snapshot.columns.index(col1_letter)
    col1_name = snapshot.headers[col1_idx] or col1_letter

    col2_idx: int | None = None
    col2_name: str | None = None
    if params.then_by:
        col2_letter = resolve_column_letter(snapshot, params.then_by)
        col2_idx = snapshot.columns.index(col2_letter)
        col2_name = snapshot.headers[col2_idx] or col2_letter

    # Exclude header row
    data_values = snapshot.values[1:]
    data_formulas = snapshot.formulas[1:]
    num_rows = len(data_values)

    if num_rows <= 1:
        return Patch(
            op="sort_rows",
            sheet=snapshot.sheet,
            cells=[],
            summary="Rows are already sorted",
        )

    records: list[dict[str, Any]] = []
    for orig_idx, (r_vals, r_forms) in enumerate(zip(data_values, data_formulas, strict=False)):
        records.append({
            "_orig_idx": orig_idx,
            "_vals": r_vals,
            "_forms": r_forms,
            "k1": _make_sort_key(r_vals[col1_idx] if col1_idx < len(r_vals) else None),
            "k2": (
                _make_sort_key(r_vals[col2_idx] if col2_idx < len(r_vals) else None)
                if col2_idx is not None
                else (0, 0)
            ),
        })

    # Python's list.sort is stable (Timsort)
    if col2_idx is not None:
        records.sort(key=lambda rec: rec["k2"], reverse=params.then_descending)
    records.sort(key=lambda rec: rec["k1"], reverse=params.descending)

    cells: list[CellChange] = []
    moved_formulas = False
    for new_idx, rec in enumerate(records):
        row_num = snapshot.header_row + 1 + new_idx
        orig_idx = rec["_orig_idx"]
        row_vals = rec["_vals"]
        row_forms = rec["_forms"]

        if orig_idx != new_idx and any(f is not None for f in row_forms):
            moved_formulas = True

        for c_idx, col_letter in enumerate(snapshot.columns):
            new_v = row_vals[c_idx] if c_idx < len(row_vals) else None
            new_f = row_forms[c_idx] if c_idx < len(row_forms) else None
            old_v = data_values[new_idx][c_idx] if c_idx < len(data_values[new_idx]) else None
            old_f = (
                data_formulas[new_idx][c_idx] if c_idx < len(data_formulas[new_idx]) else None
            )

            if new_v != old_v or new_f != old_f:
                cells.append(
                    CellChange(
                        address=f"{col_letter}{row_num}",
                        before=old_v,
                        after=new_v,
                        after_formula=new_f,
                    )
                )

    warnings: list[str] = [FORMULA_MOVE_WARNING] if moved_formulas else []
    desc_str = " (descending)" if params.descending else ""
    summary = f"Sorted rows by {col1_name}{desc_str}"
    if col2_name is not None:
        then_desc = " (descending)" if params.then_descending else ""
        summary += f", then by {col2_name}{then_desc}"

    return Patch(
        op="sort_rows",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
        warnings=warnings,
    )


def handle_filter_rows(snapshot: SheetSnapshot, params: FilterRowsParams) -> Patch:
    """Filter rows by condition, keeping or deleting matching rows and clearing vacated rows."""
    if not isinstance(params, FilterRowsParams):
        raise OpError(f"Expected FilterRowsParams, got {type(params).__name__}")

    conditions = params.conditions
    if not conditions:
        raise OpError("Filter rows requires at least one condition.")

    cond_specs: list[tuple[Condition, str, int, str]] = []
    for cond in conditions:
        c_letter = resolve_column_letter(snapshot, cond.column)
        c_idx = snapshot.columns.index(c_letter)
        c_name = snapshot.headers[c_idx] or c_letter
        cond_specs.append((cond, c_letter, c_idx, c_name))

    data_values = snapshot.values[1:]
    data_formulas = snapshot.formulas[1:]
    rows_before = len(data_values)

    kept_records: list[tuple[int, list[CellValue], list[str | None]]] = []
    for orig_idx, (r_vals, r_forms) in enumerate(zip(data_values, data_formulas, strict=False)):
        matches = all(
            evaluate_condition(r_vals[c_idx] if c_idx < len(r_vals) else None, cond)
            for cond, _, c_idx, _ in cond_specs
        )
        should_keep = matches if params.action == "keep_matching" else not matches
        if should_keep:
            kept_records.append((orig_idx, r_vals, r_forms))

    rows_after = len(kept_records)
    deleted_count = rows_before - rows_after

    cells: list[CellChange] = []
    moved_formulas = False

    # 1. Rewrite kept rows into data block
    for new_idx, (orig_idx, r_vals, r_forms) in enumerate(kept_records):
        row_num = snapshot.header_row + 1 + new_idx
        if orig_idx != new_idx and any(f is not None for f in r_forms):
            moved_formulas = True

        for c_idx, c_letter in enumerate(snapshot.columns):
            new_v = r_vals[c_idx] if c_idx < len(r_vals) else None
            new_f = r_forms[c_idx] if c_idx < len(r_forms) else None
            old_v = data_values[new_idx][c_idx] if c_idx < len(data_values[new_idx]) else None
            old_f = (
                data_formulas[new_idx][c_idx] if c_idx < len(data_formulas[new_idx]) else None
            )

            if new_v != old_v or new_f != old_f:
                cells.append(
                    CellChange(
                        address=f"{c_letter}{row_num}",
                        before=old_v,
                        after=new_v,
                        after_formula=new_f,
                    )
                )

    # 2. Clear vacated rows
    for vac_idx in range(rows_after, rows_before):
        row_num = snapshot.header_row + 1 + vac_idx
        for c_idx, c_letter in enumerate(snapshot.columns):
            old_v = data_values[vac_idx][c_idx] if c_idx < len(data_values[vac_idx]) else None
            old_f = (
                data_formulas[vac_idx][c_idx] if c_idx < len(data_formulas[vac_idx]) else None
            )
            if old_v is not None or old_f is not None:
                cells.append(
                    CellChange(
                        address=f"{c_letter}{row_num}",
                        before=old_v,
                        after=None,
                        after_formula=None,
                    )
                )

    warnings: list[str] = [FORMULA_MOVE_WARNING] if moved_formulas else []
    cond_descs = [
        f"{c_name} {cond.operator.replace('_', ' ')}{(' ' + str(cond.value)) if cond.value is not None else ''}"
        for cond, _, _, c_name in cond_specs
    ]
    cond_summary = " and ".join(cond_descs)

    if params.action == "delete_matching":
        summary = (
            f"Deleted {deleted_count} rows where {cond_summary} "
            f"({rows_before} -> {rows_after} rows)"
        )
    else:
        summary = (
            f"Kept {rows_after} rows where {cond_summary} "
            f"({rows_before} -> {rows_after} rows)"
        )

    return Patch(
        op="filter_rows",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
        warnings=warnings,
    )


def handle_remove_duplicates(snapshot: SheetSnapshot, params: RemoveDuplicatesParams) -> Patch:
    """Remove duplicate rows based on specified columns or whole rows."""
    if not isinstance(params, RemoveDuplicatesParams):
        raise OpError(f"Expected RemoveDuplicatesParams, got {type(params).__name__}")

    data_values = snapshot.values[1:]
    data_formulas = snapshot.formulas[1:]
    rows_before = len(data_values)

    if params.columns:
        target_indices = [
            snapshot.columns.index(resolve_column_letter(snapshot, c))
            for c in params.columns
        ]
        cols_display = ", ".join(
            snapshot.headers[idx] or snapshot.columns[idx] for idx in target_indices
        )
    else:
        target_indices = list(range(len(snapshot.columns)))
        cols_display = "all columns"

    # Identify surviving rows
    kept_records: list[tuple[int, list[CellValue], list[str | None]]] = []
    seen_keys: set[tuple[Any, ...]] = set()

    if params.keep == "first":
        for orig_idx, (r_vals, r_forms) in enumerate(zip(data_values, data_formulas, strict=False)):
            key = _make_dedupe_key(r_vals, target_indices)
            if key not in seen_keys:
                seen_keys.add(key)
                kept_records.append((orig_idx, r_vals, r_forms))
    else:  # keep == "last"
        # Collect last occurrences
        rev_records: list[tuple[int, list[CellValue], list[str | None]]] = []
        for orig_idx in reversed(range(rows_before)):
            r_vals = data_values[orig_idx]
            r_forms = data_formulas[orig_idx]
            key = _make_dedupe_key(r_vals, target_indices)
            if key not in seen_keys:
                seen_keys.add(key)
                rev_records.append((orig_idx, r_vals, r_forms))
        kept_records = list(reversed(rev_records))

    rows_after = len(kept_records)
    deleted_count = rows_before - rows_after

    cells: list[CellChange] = []
    moved_formulas = False

    # Rewrite kept rows
    for new_idx, (orig_idx, r_vals, r_forms) in enumerate(kept_records):
        row_num = snapshot.header_row + 1 + new_idx
        if orig_idx != new_idx and any(f is not None for f in r_forms):
            moved_formulas = True

        for c_idx, c_letter in enumerate(snapshot.columns):
            new_v = r_vals[c_idx] if c_idx < len(r_vals) else None
            new_f = r_forms[c_idx] if c_idx < len(r_forms) else None
            old_v = data_values[new_idx][c_idx] if c_idx < len(data_values[new_idx]) else None
            old_f = (
                data_formulas[new_idx][c_idx] if c_idx < len(data_formulas[new_idx]) else None
            )

            if new_v != old_v or new_f != old_f:
                cells.append(
                    CellChange(
                        address=f"{c_letter}{row_num}",
                        before=old_v,
                        after=new_v,
                        after_formula=new_f,
                    )
                )

    # Clear vacated rows
    for vac_idx in range(rows_after, rows_before):
        row_num = snapshot.header_row + 1 + vac_idx
        for c_idx, c_letter in enumerate(snapshot.columns):
            old_v = data_values[vac_idx][c_idx] if c_idx < len(data_values[vac_idx]) else None
            old_f = (
                data_formulas[vac_idx][c_idx] if c_idx < len(data_formulas[vac_idx]) else None
            )
            if old_v is not None or old_f is not None:
                cells.append(
                    CellChange(
                        address=f"{c_letter}{row_num}",
                        before=old_v,
                        after=None,
                        after_formula=None,
                    )
                )

    warnings: list[str] = [FORMULA_MOVE_WARNING] if moved_formulas else []
    if deleted_count == 0:
        summary = f"No duplicate rows found based on {cols_display}"
    else:
        summary = (
            f"Removed {deleted_count} duplicate row(s) based on {cols_display} "
            f"({rows_before} -> {rows_after} rows)"
        )

    return Patch(
        op="remove_duplicates",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
        warnings=warnings,
    )


def handle_insert_column(snapshot: SheetSnapshot, params: InsertColumnParams) -> Patch:
    """Insert a new column with header and optional fill value, shifting existing columns."""
    if not isinstance(params, InsertColumnParams):
        raise OpError(f"Expected InsertColumnParams, got {type(params).__name__}")

    num_cols = len(snapshot.columns)
    if params.position == "end":
        insert_idx = num_cols
    elif params.position == "before":
        if not params.reference_column:
            raise TargetError("reference_column is required when inserting 'before'")
        ref_col = resolve_column_letter(snapshot, params.reference_column)
        insert_idx = snapshot.columns.index(ref_col)
    elif params.position == "after":
        if not params.reference_column:
            raise TargetError("reference_column is required when inserting 'after'")
        ref_col = resolve_column_letter(snapshot, params.reference_column)
        insert_idx = snapshot.columns.index(ref_col) + 1
    else:
        raise OpError(f"Unknown position: {params.position}")

    # Build new column letters
    start_c_idx = col_to_index(snapshot.columns[0])
    new_cols = [index_to_col(c) for c in range(start_c_idx, start_c_idx + num_cols + 1)]

    # Build new headers
    new_headers = (
        snapshot.headers[:insert_idx]
        + [params.header]
        + snapshot.headers[insert_idx:]
    )

    data_values = snapshot.values[1:]
    data_formulas = snapshot.formulas[1:]

    cells: list[CellChange] = []
    moved_formulas = False

    # Process all columns from insert_idx onwards
    for col_pos in range(insert_idx, len(new_cols)):
        c_letter = new_cols[col_pos]
        header_addr = f"{c_letter}{snapshot.header_row}"
        old_h = snapshot.headers[col_pos] if col_pos < num_cols else None
        new_h = new_headers[col_pos]
        if new_h != old_h:
            cells.append(CellChange(address=header_addr, before=old_h, after=new_h))

        # Data rows
        for r_offset in range(len(data_values)):
            sheet_row = snapshot.header_row + 1 + r_offset
            addr = f"{c_letter}{sheet_row}"

            if col_pos < num_cols:
                old_v = (
                    data_values[r_offset][col_pos]
                    if col_pos < len(data_values[r_offset])
                    else None
                )
                old_f = (
                    data_formulas[r_offset][col_pos]
                    if col_pos < len(data_formulas[r_offset])
                    else None
                )
            else:
                old_v = None
                old_f = None

            if col_pos == insert_idx:
                new_v = params.fill_value
                new_f = None
            else:
                # Value comes from previous column index
                src_idx = col_pos - 1
                new_v = (
                    data_values[r_offset][src_idx]
                    if src_idx < len(data_values[r_offset])
                    else None
                )
                new_f = (
                    data_formulas[r_offset][src_idx]
                    if src_idx < len(data_formulas[r_offset])
                    else None
                )

            if new_f is not None and col_pos > insert_idx:
                moved_formulas = True

            if new_v != old_v or new_f != old_f:
                cells.append(
                    CellChange(
                        address=addr,
                        before=old_v,
                        after=new_v,
                        after_formula=new_f,
                    )
                )

    warnings: list[str] = [FORMULA_MOVE_WARNING] if moved_formulas else []
    if params.position == "end":
        summary = f"Inserted column '{params.header}' at the end"
    else:
        summary = (
            f"Inserted column '{params.header}' {params.position} {params.reference_column}"
        )

    return Patch(
        op="insert_column",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
        warnings=warnings,
    )


def handle_delete_column(snapshot: SheetSnapshot, params: DeleteColumnParams) -> Patch:
    """Delete a column, shifting subsequent columns left and clearing the vacated last column."""
    if not isinstance(params, DeleteColumnParams):
        raise OpError(f"Expected DeleteColumnParams, got {type(params).__name__}")

    del_col = resolve_column_letter(snapshot, params.column)
    del_idx = snapshot.columns.index(del_col)
    del_header = snapshot.headers[del_idx] or del_col
    num_cols = len(snapshot.columns)

    data_values = snapshot.values[1:]
    data_formulas = snapshot.formulas[1:]

    cells: list[CellChange] = []
    moved_formulas = False

    # Shift columns to the right of del_idx to the left
    for col_pos in range(del_idx, num_cols - 1):
        c_letter = snapshot.columns[col_pos]
        header_addr = f"{c_letter}{snapshot.header_row}"
        old_h = snapshot.headers[col_pos]
        new_h = snapshot.headers[col_pos + 1]
        if new_h != old_h:
            cells.append(CellChange(address=header_addr, before=old_h, after=new_h))

        for r_offset in range(len(data_values)):
            sheet_row = snapshot.header_row + 1 + r_offset
            addr = f"{c_letter}{sheet_row}"
            old_v = (
                data_values[r_offset][col_pos]
                if col_pos < len(data_values[r_offset])
                else None
            )
            old_f = (
                data_formulas[r_offset][col_pos]
                if col_pos < len(data_formulas[r_offset])
                else None
            )
            new_v = (
                data_values[r_offset][col_pos + 1]
                if (col_pos + 1) < len(data_values[r_offset])
                else None
            )
            new_f = (
                data_formulas[r_offset][col_pos + 1]
                if (col_pos + 1) < len(data_formulas[r_offset])
                else None
            )

            if new_f is not None:
                moved_formulas = True

            if new_v != old_v or new_f != old_f:
                cells.append(
                    CellChange(
                        address=addr,
                        before=old_v,
                        after=new_v,
                        after_formula=new_f,
                    )
                )

    # Clear last column
    last_col = snapshot.columns[-1]
    last_h_addr = f"{last_col}{snapshot.header_row}"
    old_last_h = snapshot.headers[-1]
    if old_last_h is not None and old_last_h != "":
        cells.append(CellChange(address=last_h_addr, before=old_last_h, after=None))

    for r_offset in range(len(data_values)):
        sheet_row = snapshot.header_row + 1 + r_offset
        addr = f"{last_col}{sheet_row}"
        old_v = (
            data_values[r_offset][-1]
            if len(data_values[r_offset]) == num_cols
            else None
        )
        old_f = (
            data_formulas[r_offset][-1]
            if len(data_formulas[r_offset]) == num_cols
            else None
        )
        if old_v is not None or old_f is not None:
            cells.append(
                CellChange(address=addr, before=old_v, after=None, after_formula=None)
            )

    warnings: list[str] = [FORMULA_MOVE_WARNING] if moved_formulas else []
    summary = f"Deleted column '{del_header}' ({del_col})"

    return Patch(
        op="delete_column",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
        warnings=warnings,
    )


def handle_rename_column(snapshot: SheetSnapshot, params: RenameColumnParams) -> Patch:
    """Rename a single column header."""
    if not isinstance(params, RenameColumnParams):
        raise OpError(f"Expected RenameColumnParams, got {type(params).__name__}")

    col_letter = resolve_column_letter(snapshot, params.column)
    col_idx = snapshot.columns.index(col_letter)
    old_header = snapshot.headers[col_idx]
    header_addr = f"{col_letter}{snapshot.header_row}"

    cells: list[CellChange] = []
    if old_header != params.new_header:
        cells.append(
            CellChange(
                address=header_addr,
                before=old_header,
                after=params.new_header,
            )
        )

    summary = f"Renamed column '{old_header}' to '{params.new_header}'"
    return Patch(
        op="rename_column",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
    )


def handle_move_column(snapshot: SheetSnapshot, params: MoveColumnParams) -> Patch:
    """Move a column to a new position (before, after, start, or end)."""
    if not isinstance(params, MoveColumnParams):
        raise OpError(f"Expected MoveColumnParams, got {type(params).__name__}")

    src_col = resolve_column_letter(snapshot, params.column)
    src_idx = snapshot.columns.index(src_col)
    src_header = snapshot.headers[src_idx] or src_col
    num_cols = len(snapshot.columns)

    if params.position == "start":
        dest_idx = 0
    elif params.position == "end":
        dest_idx = num_cols - 1
    elif params.position == "before":
        if not params.reference_column:
            raise TargetError("reference_column is required when moving 'before'")
        ref_col = resolve_column_letter(snapshot, params.reference_column)
        ref_idx = snapshot.columns.index(ref_col)
        dest_idx = ref_idx - 1 if src_idx < ref_idx else ref_idx
    elif params.position == "after":
        if not params.reference_column:
            raise TargetError("reference_column is required when moving 'after'")
        ref_col = resolve_column_letter(snapshot, params.reference_column)
        ref_idx = snapshot.columns.index(ref_col)
        dest_idx = ref_idx if src_idx < ref_idx else ref_idx + 1
    else:
        raise OpError(f"Unknown position: {params.position}")

    if src_idx == dest_idx:
        return Patch(
            op="move_column",
            sheet=snapshot.sheet,
            cells=[],
            summary=f"Column '{src_header}' is already at target position",
        )

    # Reorder column indices
    new_order = list(range(num_cols))
    new_order.pop(src_idx)
    new_order.insert(dest_idx, src_idx)

    data_values = snapshot.values[1:]
    data_formulas = snapshot.formulas[1:]

    cells: list[CellChange] = []
    moved_formulas = False

    for target_pos, source_col_idx in enumerate(new_order):
        if target_pos == source_col_idx:
            continue

        c_letter = snapshot.columns[target_pos]
        # Header
        header_addr = f"{c_letter}{snapshot.header_row}"
        old_h = snapshot.headers[target_pos]
        new_h = snapshot.headers[source_col_idx]
        if new_h != old_h:
            cells.append(CellChange(address=header_addr, before=old_h, after=new_h))

        # Data rows
        for r_offset in range(len(data_values)):
            sheet_row = snapshot.header_row + 1 + r_offset
            addr = f"{c_letter}{sheet_row}"
            old_v = (
                data_values[r_offset][target_pos]
                if target_pos < len(data_values[r_offset])
                else None
            )
            old_f = (
                data_formulas[r_offset][target_pos]
                if target_pos < len(data_formulas[r_offset])
                else None
            )
            new_v = (
                data_values[r_offset][source_col_idx]
                if source_col_idx < len(data_values[r_offset])
                else None
            )
            new_f = (
                data_formulas[r_offset][source_col_idx]
                if source_col_idx < len(data_formulas[r_offset])
                else None
            )

            if new_f is not None:
                moved_formulas = True

            if new_v != old_v or new_f != old_f:
                cells.append(
                    CellChange(
                        address=addr,
                        before=old_v,
                        after=new_v,
                        after_formula=new_f,
                    )
                )

    warnings: list[str] = [FORMULA_MOVE_WARNING] if moved_formulas else []
    summary = f"Moved column '{src_header}' {params.position}"
    if params.reference_column:
        summary += f" {params.reference_column}"

    return Patch(
        op="move_column",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
        warnings=warnings,
    )


def handle_fill_blanks(snapshot: SheetSnapshot, params: FillBlanksParams) -> Patch:
    """Fill blank cells in a column using static value, fill-down, or fill-up."""
    if not isinstance(params, FillBlanksParams):
        raise OpError(f"Expected FillBlanksParams, got {type(params).__name__}")

    col_letter = resolve_column_letter(snapshot, params.column)
    col_idx = snapshot.columns.index(col_letter)
    col_name = snapshot.headers[col_idx] or col_letter

    data_values = snapshot.values[1:]
    col_vals = [
        r[col_idx] if col_idx < len(r) else None for r in data_values
    ]
    new_vals = list(col_vals)

    if params.mode == "value":
        for i, v in enumerate(col_vals):
            if is_blank(v):
                new_vals[i] = params.value
    elif params.mode == "down":
        last_non_blank = None
        for i, v in enumerate(col_vals):
            if not is_blank(v):
                last_non_blank = v
            else:
                if last_non_blank is not None:
                    new_vals[i] = last_non_blank
    elif params.mode == "up":
        last_non_blank = None
        for i in reversed(range(len(col_vals))):
            v = col_vals[i]
            if not is_blank(v):
                last_non_blank = v
            else:
                if last_non_blank is not None:
                    new_vals[i] = last_non_blank
    else:
        raise OpError(f"Unknown fill mode: {params.mode}")

    cells: list[CellChange] = []
    for i, (old_v, new_v) in enumerate(zip(col_vals, new_vals, strict=False)):
        if new_v != old_v:
            sheet_row = snapshot.header_row + 1 + i
            cells.append(
                CellChange(
                    address=f"{col_letter}{sheet_row}",
                    before=old_v,
                    after=new_v,
                )
            )

    if params.mode == "value":
        summary = (
            f"Filled {len(cells)} blank cell(s) in {col_name} with '{params.value}'"
        )
    else:
        summary = f"Filled {len(cells)} blank cell(s) {params.mode} in {col_name}"

    return Patch(
        op="fill_blanks",
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
    )


def handle_highlight_cells(snapshot: SheetSnapshot, params: HighlightCellsParams) -> Patch:
    """Highlight matching cells or whole rows with a background color fill."""
    if not isinstance(params, HighlightCellsParams):
        raise OpError(f"Expected HighlightCellsParams, got {type(params).__name__}")

    conditions = params.conditions
    if not conditions:
        raise OpError("Highlight cells requires at least one condition.")

    cond_specs: list[tuple[Condition, str, int, str]] = []
    for cond in conditions:
        col_letter = resolve_column_letter(snapshot, cond.column)
        col_idx = snapshot.columns.index(col_letter)
        col_name = snapshot.headers[col_idx] or col_letter
        cond_specs.append((cond, col_letter, col_idx, col_name))

    fill_hex = COLOR_MAP.get(params.color)

    data_values = snapshot.values[1:]
    formats: list[FormatChange] = []
    match_count = 0

    for r_offset, r_vals in enumerate(data_values):
        sheet_row = snapshot.header_row + 1 + r_offset
        row_matches = all(
            evaluate_condition(
                r_vals[c_idx] if c_idx < len(r_vals) else None,
                cond,
            )
            for cond, _, c_idx, _ in cond_specs
        )

        if row_matches:
            match_count += 1
            if params.whole_row:
                for c_letter in snapshot.columns:
                    formats.append(
                        FormatChange(address=f"{c_letter}{sheet_row}", fill_hex=fill_hex)
                    )
            else:
                for _, c_letter, _, _ in cond_specs:
                    formats.append(
                        FormatChange(address=f"{c_letter}{sheet_row}", fill_hex=fill_hex)
                    )

    target_type = "row(s)" if params.whole_row else "cell(s)"
    color_desc = "cleared fill" if params.color == "none" else f"in {params.color}"

    cond_descs = [
        f"{c_name} {cond.operator.replace('_', ' ')}{(' ' + str(cond.value)) if cond.value is not None else ''}"
        for cond, _, _, c_name in cond_specs
    ]
    summary = (
        f"Highlighted {match_count} {target_type} where {' and '.join(cond_descs)} "
        f"{color_desc}".strip()
    )

    return Patch(
        op="highlight_cells",
        sheet=snapshot.sheet,
        cells=[],
        formats=formats,
        summary=summary,
    )
