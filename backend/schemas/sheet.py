"""Schemas for sheet snapshots and region states."""

from datetime import datetime

from pydantic import BaseModel

CellValue = str | int | float | bool | datetime | None


class SheetSnapshot(BaseModel):
    """Full snapshot of an Excel worksheet."""

    workbook: str
    sheet: str
    used_range: str  # "A1:J11" (never contains $)
    header_row: int = 1  # PoC assumption: first row of the used range holds headers
    columns: list[str]  # ["A", ..., "J"]
    headers: list[str]  # header text per column ("" if empty)
    values: list[list[CellValue]]  # whole used range, header row included
    formulas: list[list[str | None]]  # "=..." or None for constants / empty cells
    selection: str | None = None  # "B2:B4" or None
    has_merged_cells: bool = False  # filled in Phase 7


class RegionState(BaseModel):
    """Saved state of a cell region for undo and trial runs."""

    sheet: str
    region: str  # bounding A1 range
    values: list[list[CellValue]]
    formulas: list[list[str | None]]
    fills: list[list[str | None]]  # "#RRGGBB" or None
