"""Operation registry and execution dispatcher for spreadsheet operations."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.excel.a1 import parse_cell, parse_range
from backend.excel.adapter import OpError
from backend.excel.serializer import resolve_target
from backend.ops.formula_ops import (
    handle_add_formula_column,
    handle_add_summary_formula,
    validate_formula_op,
)
from backend.ops.structure_ops import (
    handle_delete_column,
    handle_fill_blanks,
    handle_filter_rows,
    handle_highlight_cells,
    handle_insert_column,
    handle_move_column,
    handle_remove_duplicates,
    handle_rename_column,
    handle_sort_rows,
)
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
from backend.schemas.intent import (
    AddFormulaColumnParams,
    AddPrefixSuffixParams,
    AddSummaryFormulaParams,
    ChangeCaseParams,
    ConvertCaseStyleParams,
    DeleteColumnParams,
    FillBlanksParams,
    FilterRowsParams,
    FindReplaceParams,
    HighlightCellsParams,
    InsertColumnParams,
    MoveColumnParams,
    RemoveCharactersParams,
    RemoveDuplicatesParams,
    RenameColumnParams,
    SortRowsParams,
    TrimWhitespaceParams,
)
from backend.schemas.patch import CellChange, Patch
from backend.schemas.sheet import CellValue, SheetSnapshot

logger = logging.getLogger(__name__)


@dataclass
class OpSpec:
    """Specification of an executable spreadsheet operation."""

    name: str  # op id, e.g. "convert_case_style"
    title: str  # human readable, e.g. "Convert case style"
    tier: int
    params_model: type[BaseModel]
    description: str  # shown to the classifier
    examples: list[str]  # example instructions shown to the classifier
    handler: Callable[[SheetSnapshot, BaseModel], Patch]
    validator: Callable[..., Awaitable[tuple[list[str], Patch]]] | None = None
    prompt_name: str = "extract_params"


REGISTRY: dict[str, OpSpec] = {}


def register(spec: OpSpec) -> None:
    """Register an operation specification in the global registry."""
    REGISTRY[spec.name] = spec


def implemented_ops() -> list[OpSpec]:
    """Return list of all registered and implemented operation specifications."""
    return list(REGISTRY.values())


def build_cell_patch(
    snapshot: SheetSnapshot,
    addresses: list[str],
    fn: Callable[[CellValue], CellValue],
    op: str,
    summary_template: str,
) -> Patch:
    """Build a Patch applying fn to each addressed cell value.

    Creates a CellChange ONLY when the value really changes.
    The summary reports how many cells changed.
    """
    r1, c1, _r2, _c2 = parse_range(snapshot.used_range)
    cells: list[CellChange] = []

    for addr in addresses:
        row, col = parse_cell(addr)
        row_idx = row - r1
        col_idx = col - c1

        if 0 <= row_idx < len(snapshot.values) and 0 <= col_idx < len(snapshot.values[row_idx]):
            current_val = snapshot.values[row_idx][col_idx]
        else:
            current_val = None

        new_val = fn(current_val)
        if new_val != current_val:
            cells.append(CellChange(address=addr, before=current_val, after=new_val))

    try:
        summary = summary_template.format(count=len(cells))
    except (KeyError, ValueError):
        summary = f"{summary_template} ({len(cells)} cells changed)"

    return Patch(
        op=op,
        sheet=snapshot.sheet,
        cells=cells,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Tier 1 Operation Handlers
# ---------------------------------------------------------------------------


def _handle_change_case(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    if not isinstance(params, ChangeCaseParams):
        raise OpError(f"Expected ChangeCaseParams, got {type(params).__name__}")
    mode_map: dict[str, Callable[[CellValue], CellValue]] = {
        "upper": to_upper,
        "lower": to_lower,
        "title": to_title,
        "sentence": to_sentence,
    }
    fn = mode_map[params.mode]
    addresses = resolve_target(snapshot, params.target)
    summary_tmpl = f"Changed {{count}} cell(s) to {params.mode} case"
    return build_cell_patch(snapshot, addresses, fn, "change_case", summary_tmpl)


def _handle_convert_case_style(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    if not isinstance(params, ConvertCaseStyleParams):
        raise OpError(f"Expected ConvertCaseStyleParams, got {type(params).__name__}")
    style_map: dict[str, Callable[[CellValue], CellValue]] = {
        "camel": to_camel,
        "snake": to_snake,
        "pascal": to_pascal,
        "kebab": to_kebab,
    }
    fn = style_map[params.style]
    addresses = resolve_target(snapshot, params.target)
    style_names = {
        "camel": "camelCase",
        "snake": "snake_case",
        "pascal": "PascalCase",
        "kebab": "kebab-case",
    }
    style_display = style_names.get(params.style, params.style)
    if params.target.kind == "headers":
        summary_tmpl = f"Converted {{count}} headers to {style_display}"
    else:
        summary_tmpl = f"Converted {{count}} cell(s) to {style_display}"
    return build_cell_patch(snapshot, addresses, fn, "convert_case_style", summary_tmpl)


def _handle_trim_whitespace(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    if not isinstance(params, TrimWhitespaceParams):
        raise OpError(f"Expected TrimWhitespaceParams, got {type(params).__name__}")
    addresses = resolve_target(snapshot, params.target)
    return build_cell_patch(
        snapshot,
        addresses,
        trim_whitespace,
        "trim_whitespace",
        "Trimmed spaces in {count} cell(s)",
    )


def _handle_find_replace(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    if not isinstance(params, FindReplaceParams):
        raise OpError(f"Expected FindReplaceParams, got {type(params).__name__}")
    addresses = resolve_target(snapshot, params.target)

    def fn(val: CellValue) -> CellValue:
        return find_replace(
            val,
            params.find,
            params.replace,
            match_case=params.match_case,
            whole_cell=params.whole_cell,
        )

    summary_tmpl = f"Replaced '{params.find}' with '{params.replace}' in {{count}} cell(s)"
    return build_cell_patch(snapshot, addresses, fn, "find_replace", summary_tmpl)


def _handle_add_prefix_suffix(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    if not isinstance(params, AddPrefixSuffixParams):
        raise OpError(f"Expected AddPrefixSuffixParams, got {type(params).__name__}")
    addresses = resolve_target(snapshot, params.target)

    def fn(val: CellValue) -> CellValue:
        return add_prefix_suffix(val, prefix=params.prefix, suffix=params.suffix)

    return build_cell_patch(
        snapshot,
        addresses,
        fn,
        "add_prefix_suffix",
        "Added prefix/suffix to {count} cell(s)",
    )


def _handle_remove_characters(snapshot: SheetSnapshot, params: BaseModel) -> Patch:
    if not isinstance(params, RemoveCharactersParams):
        raise OpError(f"Expected RemoveCharactersParams, got {type(params).__name__}")
    addresses = resolve_target(snapshot, params.target)

    def fn(val: CellValue) -> CellValue:
        return remove_characters(val, remove=params.remove, custom_chars=params.custom_chars)

    summary_tmpl = f"Removed {params.remove} characters from {{count}} cell(s)"
    return build_cell_patch(snapshot, addresses, fn, "remove_characters", summary_tmpl)


# ---------------------------------------------------------------------------
# Register Tier 1 Operations (Section 9)
# ---------------------------------------------------------------------------

register(
    OpSpec(
        name="change_case",
        title="Change text case",
        tier=1,
        params_model=ChangeCaseParams,
        description="Change text case to upper, lower, title, or sentence case",
        examples=[
            "Make the Department column uppercase",
            "Put Full Name in title case",
        ],
        handler=_handle_change_case,
    )
)

register(
    OpSpec(
        name="convert_case_style",
        title="Convert case style",
        tier=1,
        params_model=ConvertCaseStyleParams,
        description="Convert text to camelCase, snake_case, PascalCase, or kebab-case",
        examples=[
            "Convert all column headers to camelCase",
            "Make the headers snake_case",
        ],
        handler=_handle_convert_case_style,
    )
)

register(
    OpSpec(
        name="trim_whitespace",
        title="Trim spaces",
        tier=1,
        params_model=TrimWhitespaceParams,
        description="Remove extra spaces, tabs, and non-breaking spaces",
        examples=[
            "Remove extra spaces in Full Name",
            "Clean up the spaces in column B",
        ],
        handler=_handle_trim_whitespace,
    )
)

register(
    OpSpec(
        name="find_replace",
        title="Find and replace",
        tier=1,
        params_model=FindReplaceParams,
        description="Find and replace text or numbers",
        examples=[
            "Replace Inactive with Former in Status",
            "Change New York to NYC",
        ],
        handler=_handle_find_replace,
    )
)

register(
    OpSpec(
        name="add_prefix_suffix",
        title="Add prefix / suffix",
        tier=1,
        params_model=AddPrefixSuffixParams,
        description="Add prefix before or suffix after text or numbers",
        examples=[
            "Add EMP- before every Emp ID",
            "Add ' (HQ)' after each City",
        ],
        handler=_handle_add_prefix_suffix,
    )
)

register(
    OpSpec(
        name="remove_characters",
        title="Remove characters",
        tier=1,
        params_model=RemoveCharactersParams,
        description="Remove special characters, digits, letters, or custom characters",
        examples=[
            "Keep only digits in the Phone column",
            "Remove symbols from Phone",
        ],
        handler=_handle_remove_characters,
    )
)


# ---------------------------------------------------------------------------
# Tier 2 Structural Operation Validators & Registrations (Section 9)
# ---------------------------------------------------------------------------


async def _validate_no_merged_cells(
    snapshot: SheetSnapshot,
    params: BaseModel,
    patch: Patch,
    adapter: Any = None,
) -> tuple[list[str], Patch]:
    """Validate that the sheet does not contain merged cells."""
    if snapshot.has_merged_cells:
        return (
            [
                "Cannot perform structural operation on a sheet with merged cells. Please unmerge cells first."
            ],
            patch,
        )
    return ([], patch)


register(
    OpSpec(
        name="sort_rows",
        title="Sort rows",
        tier=2,
        params_model=SortRowsParams,
        description="Sort table rows by one or two columns in ascending or descending order",
        examples=[
            "Sort by Salary, highest first",
            "Sort by City then Full Name",
        ],
        handler=handle_sort_rows,
        validator=_validate_no_merged_cells,
    )
)

register(
    OpSpec(
        name="filter_rows",
        title="Filter rows",
        tier=2,
        params_model=FilterRowsParams,
        description="Filter or delete rows based on a matching condition",
        examples=[
            "Delete rows where Status is Inactive",
            "Keep only Engineering employees",
        ],
        handler=handle_filter_rows,
        validator=_validate_no_merged_cells,
    )
)

register(
    OpSpec(
        name="remove_duplicates",
        title="Remove duplicates",
        tier=2,
        params_model=RemoveDuplicatesParams,
        description="Remove duplicate rows based on specific columns or entire rows",
        examples=[
            "Remove duplicate emails",
            "Remove duplicate rows",
        ],
        handler=handle_remove_duplicates,
        validator=_validate_no_merged_cells,
    )
)

register(
    OpSpec(
        name="insert_column",
        title="Insert column",
        tier=2,
        params_model=InsertColumnParams,
        description="Insert a new column at the end or before/after an existing column",
        examples=[
            "Add a column called Bonus after Salary",
            "Insert an empty Notes column at the end",
        ],
        handler=handle_insert_column,
        validator=_validate_no_merged_cells,
    )
)

register(
    OpSpec(
        name="delete_column",
        title="Delete column",
        tier=2,
        params_model=DeleteColumnParams,
        description="Delete a column from the table",
        examples=[
            "Delete the Rating column",
        ],
        handler=handle_delete_column,
        validator=_validate_no_merged_cells,
    )
)

register(
    OpSpec(
        name="rename_column",
        title="Rename column",
        tier=2,
        params_model=RenameColumnParams,
        description="Rename a column header",
        examples=[
            "Rename Emp ID to Employee ID",
        ],
        handler=handle_rename_column,
    )
)

register(
    OpSpec(
        name="move_column",
        title="Move column",
        tier=2,
        params_model=MoveColumnParams,
        description="Move a column to a new position (before, after, start, or end)",
        examples=[
            "Move Email next to Full Name",
            "Put City first",
        ],
        handler=handle_move_column,
        validator=_validate_no_merged_cells,
    )
)

register(
    OpSpec(
        name="fill_blanks",
        title="Fill blanks",
        tier=2,
        params_model=FillBlanksParams,
        description="Fill empty cells in a column with a value or by filling down or up",
        examples=[
            "Fill empty City cells with Unknown",
            "Fill blanks in Notes with N/A",
        ],
        handler=handle_fill_blanks,
    )
)

register(
    OpSpec(
        name="highlight_cells",
        title="Highlight cells",
        tier=2,
        params_model=HighlightCellsParams,
        description="Highlight matching cells or entire rows with a background color",
        examples=[
            "Highlight salaries above 60000 in green",
            "Highlight Inactive rows in red",
        ],
        handler=handle_highlight_cells,
    )
)

register(
    OpSpec(
        name="add_formula_column",
        title="Add formula column",
        tier=3,
        params_model=AddFormulaColumnParams,
        description="Add a new column computed using an Excel formula for each row",
        examples=[
            "Add a Total column = Qty x Unit Price",
            "Add Order Month from Order Date",
            "Add First Name from Full Name",
        ],
        handler=handle_add_formula_column,
        validator=validate_formula_op,
        prompt_name="extract_params_formula",
    )
)

register(
    OpSpec(
        name="add_summary_formula",
        title="Add summary formula",
        tier=3,
        params_model=AddSummaryFormulaParams,
        description="Add a summary or aggregate Excel formula below or beside the table",
        examples=[
            "Add the total of Qty below the table",
            "Count how many orders are paid",
            "Total Qty for the North region",
        ],
        handler=handle_add_summary_formula,
        validator=validate_formula_op,
        prompt_name="extract_params_formula",
    )
)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def execute(op_name: str, snapshot: SheetSnapshot, params: BaseModel | dict) -> Patch:
    """Execute an operation by name on a snapshot with parameters.

    Raises OpError for unknown ops or invalid parameter types.
    """
    if op_name not in REGISTRY:
        raise OpError(f"Unknown operation '{op_name}'. Available: {list(REGISTRY.keys())}")

    spec = REGISTRY[op_name]
    if isinstance(params, dict):
        try:
            validated_params: BaseModel = spec.params_model.model_validate(params)
        except ValidationError as exc:
            raise OpError(f"Invalid parameters for '{op_name}': {exc}") from exc
    elif isinstance(params, spec.params_model):
        validated_params = params
    else:
        raise OpError(
            f"Params for '{op_name}' must be {spec.params_model.__name__} or dict, "
            f"got {type(params).__name__}"
        )

    return spec.handler(snapshot, validated_params)
