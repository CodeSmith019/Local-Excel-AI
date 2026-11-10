"""Schemas for cell changes, format changes, and patches."""

from pydantic import BaseModel, Field

from backend.schemas.sheet import CellValue


class CellChange(BaseModel):
    """A change to a single cell's value or formula."""

    address: str  # "B3"
    before: CellValue
    after: CellValue = None
    after_formula: str | None = None  # set when a formula is written


class FormatChange(BaseModel):
    """A formatting change to a single cell."""

    address: str
    fill_hex: str | None = None  # "#C6EFCE"; None clears the fill


class Patch(BaseModel):
    """A collection of changes to be previewed and applied to a sheet."""

    op: str
    sheet: str
    cells: list[CellChange] = Field(default_factory=list)
    formats: list[FormatChange] = Field(default_factory=list)
    summary: str  # e.g. "Converted 10 headers to camelCase"
    warnings: list[str] = Field(default_factory=list)
    preview_values: dict[str, CellValue] = Field(default_factory=dict)

