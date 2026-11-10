"""Intent and target schemas for operations."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Target(BaseModel):
    """Specification of target cells for an operation."""

    kind: Literal["columns", "headers", "range", "selection"] = Field(
        description="Target type: 'columns' for data columns, 'headers' for header row, 'range' for A1 range, or 'selection' for active selection"
    )
    columns: list[str] = Field(
        default_factory=list,
        description="Column names (headers) or letters to target",
    )
    range: str | None = Field(
        default=None,
        description="A1 range address (e.g. 'A1:C10') when kind is 'range'",
    )


class ChangeCaseParams(BaseModel):
    """Parameters for changing text case."""

    target: Target = Field(description="Target cells, columns, or headers to modify")
    mode: Literal["upper", "lower", "title", "sentence"] = Field(
        description="Case transformation mode: upper, lower, title, or sentence"
    )


class ConvertCaseStyleParams(BaseModel):
    """Parameters for converting text casing style."""

    target: Target = Field(description="Target cells, columns, or headers to modify")
    style: Literal["camel", "snake", "pascal", "kebab"] = Field(
        description="Target case style: camel, snake, pascal, or kebab"
    )


class TrimWhitespaceParams(BaseModel):
    """Parameters for trimming whitespace."""

    target: Target = Field(description="Target cells, columns, or headers to modify")


class FindReplaceParams(BaseModel):
    """Parameters for finding and replacing text or values."""

    target: Target = Field(description="Target cells, columns, or headers to modify")
    find: str = Field(description="Text substring or pattern to find")
    replace: str = Field(description="Text to replace matches with")
    match_case: bool = Field(
        default=False,
        description="Whether search is case-sensitive (default False)",
    )
    whole_cell: bool = Field(
        default=False,
        description="Whether to match entire cell contents only (default False)",
    )


class AddPrefixSuffixParams(BaseModel):
    """Parameters for adding prefix or suffix to cell values."""

    target: Target = Field(description="Target cells, columns, or headers to modify")
    prefix: str = Field(default="", description="Text prefix to prepend to cell values")
    suffix: str = Field(default="", description="Text suffix to append to cell values")


class RemoveCharactersParams(BaseModel):
    """Parameters for removing characters from cell values."""

    target: Target = Field(description="Target cells, columns, or headers to modify")
    remove: Literal["special", "digits", "letters", "non_digits", "custom"] = Field(
        description="Type of characters to remove: special, digits, letters, non_digits, or custom"
    )
    custom_chars: str = Field(
        default="",
        description="Characters to remove when remove mode is 'custom'",
    )


# ---------------------------------------------------------------------------
# Tier 2 Structural Operation Schemas
# ---------------------------------------------------------------------------


class Condition(BaseModel):
    """Condition for filtering or highlighting rows and cells."""

    column: str = Field(description="Column header name or column letter to test")
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "greater_than",
        "less_than",
        "greater_or_equal",
        "less_or_equal",
        "is_blank",
        "is_not_blank",
    ] = Field(description="Comparison operator to evaluate")
    value: str | float | None = Field(
        default=None,
        description="Target value to compare against (omit or null for is_blank/is_not_blank)",
    )


class SortRowsParams(BaseModel):
    """Parameters for sorting data rows."""

    by_column: str = Field(description="Primary column header name or column letter to sort by")
    descending: bool = Field(
        default=False,
        description="Whether to sort descending (default False, i.e. ascending)",
    )
    then_by: str | None = Field(
        default=None,
        description="Optional secondary column header name or column letter to sort by",
    )
    then_descending: bool = Field(
        default=False,
        description="Whether secondary sort is descending (default False)",
    )


class FilterRowsParams(BaseModel):
    """Parameters for filtering or deleting rows by condition."""

    conditions: list[Condition] = Field(
        min_length=1,
        description="One or more conditions to evaluate (combined with AND logic).",
    )
    action: Literal["keep_matching", "delete_matching"] = Field(
        description="Action to take: 'keep_matching' to keep rows that match, 'delete_matching' to delete rows that match"
    )

    def __init__(self, *args: Any, condition: Condition | None = None, **kwargs: Any) -> None:
        if condition is not None:
            existing = list(kwargs.get("conditions") or [])
            if condition not in existing:
                existing.insert(0, condition)
            kwargs["conditions"] = existing
        super().__init__(*args, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def populate_conditions_from_legacy(cls, data: Any) -> Any:
        """Allow legacy 'condition' key in dicts to populate 'conditions'."""
        if isinstance(data, dict):
            cond = data.get("condition")
            conds = list(data.get("conditions") or [])
            if cond and cond not in conds:
                conds.insert(0, cond)
            if conds:
                data["conditions"] = conds
        return data

    @property
    def condition(self) -> Condition | None:
        """Backward compatibility helper returning the primary condition."""
        return self.conditions[0] if self.conditions else None


class RemoveDuplicatesParams(BaseModel):
    """Parameters for removing duplicate rows."""

    columns: list[str] = Field(
        default_factory=list,
        description="List of column names or letters to consider when checking duplicates (empty compares whole rows)",
    )
    keep: Literal["first", "last"] = Field(
        default="first",
        description="Which duplicate occurrence to keep: 'first' or 'last'",
    )


class InsertColumnParams(BaseModel):
    """Parameters for inserting a new column."""

    header: str = Field(description="Header name for the new column")
    position: Literal["end", "before", "after"] = Field(
        default="end",
        description="Position to insert: 'end' of table, 'before' reference column, or 'after' reference column",
    )
    reference_column: str | None = Field(
        default=None,
        description="Reference column header name or letter when position is 'before' or 'after'",
    )
    fill_value: str | None = Field(
        default=None,
        description="Optional value to fill in all data rows of the new column",
    )


class DeleteColumnParams(BaseModel):
    """Parameters for deleting a column."""

    column: str = Field(description="Column header name or column letter to delete")


class RenameColumnParams(BaseModel):
    """Parameters for renaming a column header."""

    column: str = Field(description="Current column header name or column letter to rename")
    new_header: str = Field(description="New header text for the column")


class MoveColumnParams(BaseModel):
    """Parameters for moving a column to a new position."""

    column: str = Field(description="Column header name or column letter to move")
    position: Literal["before", "after", "start", "end"] = Field(
        description="Target position: 'before' or 'after' reference column, 'start' of table, or 'end' of table"
    )
    reference_column: str | None = Field(
        default=None,
        description="Reference column header name or letter when position is 'before' or 'after'",
    )


class FillBlanksParams(BaseModel):
    """Parameters for filling blank cells in a column."""

    column: str = Field(description="Column header name or column letter to fill blanks in")
    mode: Literal["value", "down", "up"] = Field(
        description="Fill mode: 'value' (use static value), 'down' (forward-fill from above), or 'up' (backward-fill from below)"
    )
    value: str | None = Field(
        default=None,
        description="Static value to insert when mode is 'value'",
    )


class HighlightCellsParams(BaseModel):
    """Parameters for highlighting cells or rows matching a condition."""

    conditions: list[Condition] = Field(
        min_length=1,
        description="One or more conditions to evaluate (combined with AND logic).",
    )
    color: Literal["yellow", "green", "red", "orange", "blue", "none"] = Field(
        default="yellow",
        description="Highlight color: yellow, green, red, orange, blue, or none (to clear)",
    )
    whole_row: bool = Field(
        default=False,
        description="Whether to highlight the entire row (True) or only the condition column cell (False)",
    )

    def __init__(self, *args: Any, condition: Condition | None = None, **kwargs: Any) -> None:
        if condition is not None:
            existing = list(kwargs.get("conditions") or [])
            if condition not in existing:
                existing.insert(0, condition)
            kwargs["conditions"] = existing
        super().__init__(*args, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def populate_conditions_from_legacy(cls, data: Any) -> Any:
        """Allow legacy 'condition' key in dicts to populate 'conditions'."""
        if isinstance(data, dict):
            cond = data.get("condition")
            conds = list(data.get("conditions") or [])
            if cond and cond not in conds:
                conds.insert(0, cond)
            if conds:
                data["conditions"] = conds
        return data

    @property
    def condition(self) -> Condition | None:
        """Backward compatibility helper returning the primary condition."""
        return self.conditions[0] if self.conditions else None


# ---------------------------------------------------------------------------
# Tier 3 Formula Generation Operation Schemas
# ---------------------------------------------------------------------------


class AddFormulaColumnParams(BaseModel):
    """Parameters for adding a new calculated formula column."""

    new_header: str = Field(description="Header name for the new formula column")
    formula: str = Field(
        description="Formula for the FIRST data row using relative references (e.g. '=D2*E2')"
    )
    target_column: str | None = Field(
        default=None,
        description="Existing header to overwrite; None = next empty column",
    )


class AddSummaryFormulaParams(BaseModel):
    """Parameters for adding a summary or aggregate formula."""

    formula: str = Field(
        description="Excel summary formula (e.g. '=SUM(D2:D11)')"
    )
    label: str | None = Field(
        default=None,
        description="Optional label for the summary cell, placed in the cell to its left if empty",
    )
    target_cell: str | None = Field(
        default=None,
        description="Target cell (e.g. 'D13'); None = two rows below the last data row, in the column of the first referenced range",
    )


class IntentChoice(BaseModel):
    """Operation intent choice classified from user instruction."""

    op: str = Field(description="Operation identifier or 'unsupported'")
    explanation: str = Field(
        description="One short sentence explaining why this operation was chosen"
    )
