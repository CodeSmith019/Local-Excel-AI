"""Tier 3 spreadsheet operations for formula generation and evaluation."""

import logging
import re
from typing import Any

from pydantic import BaseModel

from backend.config import get_settings
from backend.excel.a1 import (
    bounding_range,
    col_to_index,
    index_to_col,
    parse_cell,
    parse_range,
)
from backend.excel.com_thread import com_thread
from backend.excel.fake_adapter import FakeAdapter
from backend.schemas.intent import AddFormulaColumnParams, AddSummaryFormulaParams
from backend.schemas.patch import CellChange, Patch
from backend.schemas.sheet import SheetSnapshot

logger = logging.getLogger(__name__)

ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "SUM",
        "AVERAGE",
        "MIN",
        "MAX",
        "COUNT",
        "COUNTA",
        "COUNTBLANK",
        "COUNTIF",
        "COUNTIFS",
        "SUMIF",
        "SUMIFS",
        "AVERAGEIF",
        "AVERAGEIFS",
        "SUMPRODUCT",
        "ROUND",
        "ROUNDUP",
        "ROUNDDOWN",
        "INT",
        "ABS",
        "MOD",
        "IF",
        "IFS",
        "IFERROR",
        "AND",
        "OR",
        "NOT",
        "LEFT",
        "RIGHT",
        "MID",
        "LEN",
        "FIND",
        "SEARCH",
        "SUBSTITUTE",
        "REPLACE",
        "TRIM",
        "UPPER",
        "LOWER",
        "PROPER",
        "CONCAT",
        "CONCATENATE",
        "TEXTJOIN",
        "TEXT",
        "VALUE",
        "EXACT",
        "DATE",
        "YEAR",
        "MONTH",
        "DAY",
        "TODAY",
        "DATEDIF",
        "EDATE",
        "EOMONTH",
        "WEEKDAY",
        "NETWORKDAYS",
        "DAYS",
    }
)

EXCEL_ERROR_VALUES: frozenset[str] = frozenset(
    {
        "#NAME?",
        "#REF!",
        "#VALUE!",
        "#DIV/0!",
        "#N/A",
        "#NUM!",
        "#NULL!",
        "#SPILL!",
        "#CALC!",
    }
)

# Tokenizer pattern matching:
# Group 1: string literal
# Group 2: function call identifier (followed by '(')
# Group 3: full cell reference
# Group 4: column $ anchor
# Group 5: column letters
# Group 6: row $ anchor
# Group 7: row digits
_FORMULA_TOKEN_PATTERN = re.compile(
    r'("(?:[^"]|"")*")'
    r'|(\b[A-Za-z_][A-Za-z0-9_.]*(?=\s*\())'
    r'|((?<![A-Za-z0-9_$])(\$?)([A-Za-z]+)(\$?)([1-9][0-9]*)(?![A-Za-z0-9]))'
)


def shift_relative_refs(formula: str, row_offset: int) -> str:
    """Shift row numbers of non-$-anchored cell references by row_offset.

    Leaves $-anchored rows, column letters, function names, and string literals untouched.
    """
    if row_offset == 0:
        return formula

    def _replace(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            # String literal untouched
            return match.group(1)
        if match.group(2) is not None:
            # Function name untouched
            return match.group(2)

        # Cell reference
        col_anchor = match.group(4)
        col = match.group(5)
        row_anchor = match.group(6)
        row_str = match.group(7)

        if row_anchor == "$":
            return match.group(3)

        new_row = int(row_str) + row_offset
        return f"{col_anchor}{col}{row_anchor}{new_row}"

    return _FORMULA_TOKEN_PATTERN.sub(_replace, formula)


def static_check(
    formula: str,
    snapshot: SheetSnapshot,
    target_col: str | None,
    row_wise: bool,
) -> list[str]:
    """Statically validate an Excel formula against snapshot and safety rules."""
    errors: list[str] = []

    if not formula or not formula.startswith("="):
        errors.append("Formula must start with '='")
        return errors

    if len(formula) >= 500:
        errors.append("Formula length must be less than 500 characters")

    # Balanced double quotes
    if formula.count('"') % 2 != 0:
        errors.append("Formula has unbalanced double quotes")

    # Balanced parentheses (outside string literals)
    in_quote = False
    depth = 0
    unbalanced = False
    for ch in formula:
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    unbalanced = True
    if depth != 0 or unbalanced:
        errors.append("Formula has unbalanced parentheses")

    # Parse used range bounds
    min_r, min_c, max_r, max_c = parse_range(snapshot.used_range)
    min_col_str = index_to_col(min_c)
    max_col_str = index_to_col(max_c)

    # Clean target column for circular reference check
    clean_target_col = target_col.replace("$", "").upper() if target_col else None

    # Inspect function calls and cell references
    for match in _FORMULA_TOKEN_PATTERN.finditer(formula):
        if match.group(1) is not None:
            # String literal - ignore contents
            continue

        if match.group(2) is not None:
            # Function name
            fn_name = match.group(2).upper()
            if fn_name not in ALLOWED_FUNCTIONS:
                errors.append(f"Function '{match.group(2)}' is not allowed")
            continue

        # Cell reference
        col = match.group(5).upper()
        row_anchor = match.group(6)
        row_num = int(match.group(7))

        try:
            col_idx = col_to_index(col)
        except ValueError:
            errors.append(f"Invalid column name: {col}")
            continue

        # Check used range bounds
        if not (min_c <= col_idx <= max_c):
            errors.append(
                f"Column '{col}' is outside the table; data columns are {min_col_str}-{max_col_str}"
            )
        if not (min_r <= row_num <= max_r):
            errors.append(
                f"Row {row_num} in '{col}{row_num}' is outside used range ({snapshot.used_range})"
            )

        # Row-wise relative reference rule: must reference row 2 (first data row)
        if row_wise and row_anchor != "$" and row_num != 2:
            errors.append(
                f"Relative reference '{col}{row_num}' must reference row 2 (the first data row)"
            )

        # Circular reference check against target column
        if clean_target_col and col == clean_target_col:
            errors.append(
                f"Formula cannot reference target column '{clean_target_col}' (circular reference)"
            )

    return errors


def _extract_first_referenced_column(formula: str) -> str | None:
    """Find the column letter of the first cell reference in the formula."""
    for match in _FORMULA_TOKEN_PATTERN.finditer(formula):
        if match.group(1) is not None or match.group(2) is not None:
            continue
        return match.group(5).upper()
    return None


def _is_cell_empty(snapshot: SheetSnapshot, address: str) -> bool:
    """Check if cell at address is empty in snapshot."""
    r1, c1, r2, c2 = parse_range(snapshot.used_range)
    r, c = parse_cell(address)
    if r < r1 or r > r2 or c < c1 or c > c2:
        return True
    row_idx = r - r1
    col_idx = c - c1
    if 0 <= row_idx < len(snapshot.values) and 0 <= col_idx < len(snapshot.values[row_idx]):
        val = snapshot.values[row_idx][col_idx]
        return val is None or val == ""
    return True


def handle_add_formula_column(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    """Handle add_formula_column operation."""
    if not isinstance(params, AddFormulaColumnParams):
        params = AddFormulaColumnParams.model_validate(params)

    r1, c1, r2, c2 = parse_range(snapshot.used_range)

    # Determine target column
    target_col: str
    if params.target_column:
        cand = params.target_column.strip()
        if cand in snapshot.headers:
            target_col = snapshot.columns[snapshot.headers.index(cand)]
        elif cand.upper() in snapshot.columns:
            target_col = cand.upper()
        else:
            target_col = index_to_col(c2 + 1)
    else:
        target_col = index_to_col(c2 + 1)

    changes: list[CellChange] = []
    target_c_idx = col_to_index(target_col)

    # 1. Header cell
    header_addr = f"{target_col}{snapshot.header_row}"
    before_val = None
    if c1 <= target_c_idx <= c2:
        row_idx = snapshot.header_row - r1
        col_idx = target_c_idx - c1
        if 0 <= row_idx < len(snapshot.values) and 0 <= col_idx < len(snapshot.values[row_idx]):
            before_val = snapshot.values[row_idx][col_idx]

    changes.append(
        CellChange(
            address=header_addr,
            before=before_val,
            after=params.new_header,
            after_formula=None,
        )
    )

    # 2. Data rows
    for r in range(snapshot.header_row + 1, r2 + 1):
        addr = f"{target_col}{r}"
        before_row_val = None
        if c1 <= target_c_idx <= c2:
            row_idx = r - r1
            col_idx = target_c_idx - c1
            if 0 <= row_idx < len(snapshot.values) and 0 <= col_idx < len(snapshot.values[row_idx]):
                before_row_val = snapshot.values[row_idx][col_idx]

        row_offset = r - (snapshot.header_row + 1)
        shifted_formula = shift_relative_refs(params.formula, row_offset)
        changes.append(
            CellChange(
                address=addr,
                before=before_row_val,
                after=None,
                after_formula=shifted_formula,
            )
        )

    summary = f"Added formula column '{params.new_header}' at column {target_col}"
    return Patch(
        op="add_formula_column",
        sheet=snapshot.sheet,
        cells=changes,
        summary=summary,
    )


def handle_add_summary_formula(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    """Handle add_summary_formula operation."""
    if not isinstance(params, AddSummaryFormulaParams):
        params = AddSummaryFormulaParams.model_validate(params)

    _r1, _, r2, _ = parse_range(snapshot.used_range)

    # Determine target cell
    if params.target_cell:
        target_cell = params.target_cell.replace("$", "").upper()
    else:
        first_col = _extract_first_referenced_column(params.formula) or snapshot.columns[0]
        target_cell = f"{first_col}{r2 + 2}"

    changes: list[CellChange] = []
    target_r, target_c = parse_cell(target_cell)

    # Label cell placed to the left if label provided and cell is empty
    if params.label and target_c > 1:
        left_col = index_to_col(target_c - 1)
        left_addr = f"{left_col}{target_r}"
        if _is_cell_empty(snapshot, left_addr):
            changes.append(
                CellChange(
                    address=left_addr,
                    before=None,
                    after=params.label,
                    after_formula=None,
                )
            )

    # Formula cell
    changes.append(
        CellChange(
            address=target_cell,
            before=None,
            after=None,
            after_formula=params.formula,
        )
    )

    label_part = f" with label '{params.label}'" if params.label else ""
    summary = f"Added summary formula {params.formula} at {target_cell}{label_part}"
    return Patch(
        op="add_summary_formula",
        sheet=snapshot.sheet,
        cells=changes,
        summary=summary,
    )


async def validate_formula_op(
    snapshot: SheetSnapshot,
    params: BaseModel,
    patch: Patch,
    adapter: Any,
) -> tuple[list[str], Patch]:
    """Validate formula operation with static check and optional live Excel trial run."""
    row_wise = patch.op == "add_formula_column"
    target_col: str | None = None
    if row_wise and patch.cells:
        _, c = parse_cell(patch.cells[0].address)
        target_col = index_to_col(c)

    formula = getattr(params, "formula", "")
    errors = static_check(formula, snapshot, target_col, row_wise)
    if errors:
        return errors, patch

    settings = get_settings()
    is_fake = isinstance(adapter, FakeAdapter) or type(adapter).__name__ == "FakeAdapter"

    if settings.formula_trial_run and not is_fake:
        addrs = [c.address for c in patch.cells]
        if addrs:
            region = bounding_range(addrs)
            r1, c1, _, _ = parse_range(region)
            saved_state = await com_thread.run(adapter.read_region, region)
            try:
                await com_thread.run(adapter.apply_patch, patch)
                await com_thread.run(adapter.calculate)
                computed = await com_thread.run(adapter.read_values, region)
            finally:
                await com_thread.run(adapter.restore_region, saved_state)

            for cell in patch.cells:
                cr, cc = parse_cell(cell.address)
                val = computed[cr - r1][cc - c1]
                val_str = str(val).strip() if val is not None else ""
                if val_str in EXCEL_ERROR_VALUES:
                    formula_str = cell.after_formula or formula
                    _min_r, min_c, _max_r, max_c = parse_range(snapshot.used_range)
                    col_bounds = f"{index_to_col(min_c)}-{index_to_col(max_c)}"
                    err_msg = f"{cell.address}: {formula_str} gives {val_str}"
                    if val_str == "#NAME?":
                        err_msg += f" - unknown function or column name; data columns are {col_bounds}"
                    elif val_str == "#DIV/0!":
                        err_msg += " - division by zero"
                    errors.append(err_msg)
                else:
                    patch.preview_values[cell.address] = val

            if errors:
                return errors, patch

    return [], patch
