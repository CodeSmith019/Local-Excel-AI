"""WorkbookAdapter protocol and error classes for Excel operations."""

from typing import Protocol, runtime_checkable

from backend.schemas.patch import Patch
from backend.schemas.sheet import CellValue, RegionState, SheetSnapshot


class ExcelNotConnectedError(Exception):
    """Raised when Excel or a workbook is not open."""

    def __init__(self, message: str = "Open a workbook in Excel first.") -> None:
        super().__init__(message)


class TargetError(Exception):
    """Raised when a target cannot be resolved on the sheet."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class OpError(Exception):
    """Raised when an operation cannot be executed or parameters are invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@runtime_checkable
class WorkbookAdapter(Protocol):
    """Protocol defining synchronous operations on an Excel workbook."""

    def read_snapshot(self) -> SheetSnapshot:
        """Read the used range, headers, values, formulas, and selection of the active sheet."""
        ...

    def read_region(self, region: str) -> RegionState:
        """Read values, formulas, and fills for a bounding A1 region."""
        ...

    def apply_patch(self, patch: Patch) -> None:
        """Apply a patch (values, formulas, and format fills) to the sheet."""
        ...

    def restore_region(self, state: RegionState) -> None:
        """Restore a previously saved region state (values, formulas, and fills)."""
        ...

    def calculate(self) -> None:
        """Trigger Excel calculation on the workbook."""
        ...

    def read_values(self, region: str) -> list[list[CellValue]]:
        """Read evaluated cell values from a region, returning errors as strings (e.g. '#DIV/0!')."""
        ...

    def describe(self) -> dict:
        """Return status dict: {'connected': bool, 'workbook': str | None, 'sheet': str | None, 'error': str | None}."""
        ...

