"""In-memory fake Excel adapter for offline unit testing."""

from pathlib import Path
from typing import Any

import openpyxl

from backend.excel.a1 import bounding_range, index_to_col, parse_range
from backend.excel.adapter import WorkbookAdapter
from backend.excel.values import display_value
from backend.schemas.patch import Patch
from backend.schemas.sheet import CellValue, RegionState, SheetSnapshot


class FakeAdapter(WorkbookAdapter):
    """In-memory workbook adapter that simulates Excel sheets without COM."""

    def __init__(
        self,
        sheet_name: str = "Sheet1",
        rows: list[list[CellValue]] | None = None,
        file_path: Path | str | None = None,
        has_merged_cells: bool = False,
    ) -> None:
        self.sheet_name = sheet_name
        self.workbook_name = Path(file_path).name if file_path else "fake_book.xlsx"
        self._grid: dict[str, dict[str, Any]] = {}
        self.applied_patches: list[Patch] = []
        self.selection: str | None = None
        self.calculate_called: int = 0
        self.has_merged_cells = has_merged_cells

        if file_path is not None:
            self._load_from_file(Path(file_path))
        elif rows is not None:
            self._load_from_rows(rows)

    def _load_from_rows(self, rows: list[list[CellValue]]) -> None:
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, val in enumerate(row, start=1):
                addr = f"{index_to_col(c_idx)}{r_idx}"
                formula = None
                value = val
                if isinstance(val, str) and val.startswith("="):
                    formula = val
                    value = None
                self._grid[addr] = {"value": value, "formula": formula, "fill": None}

    def _load_from_file(self, path: Path) -> None:
        wb = openpyxl.load_workbook(path, data_only=False)
        ws = wb.active
        self.sheet_name = ws.title if ws is not None else "Sheet1"
        if ws is None:
            return

        for row in ws.iter_rows(values_only=False):
            for cell in row:
                addr = cell.coordinate
                val = cell.value
                formula = None
                if isinstance(val, str) and val.startswith("="):
                    formula = val
                    val = None

                fill_hex = None
                if (
                    cell.fill
                    and cell.fill.start_color
                    and cell.fill.start_color.rgb
                    and isinstance(cell.fill.start_color.rgb, str)
                ):
                    rgb_str = cell.fill.start_color.rgb
                    if len(rgb_str) == 8:  # AARRGGBB
                        fill_hex = f"#{rgb_str[2:]}"
                    elif len(rgb_str) == 6:
                        fill_hex = f"#{rgb_str}"

                self._grid[addr] = {"value": val, "formula": formula, "fill": fill_hex}

    def describe(self) -> dict[str, Any]:
        """Return fake connection status."""
        return {
            "connected": True,
            "workbook": self.workbook_name,
            "sheet": self.sheet_name,
            "error": None,
        }

    def read_snapshot(self) -> SheetSnapshot:
        """Read all grid cells into a SheetSnapshot."""
        if not self._grid:
            return SheetSnapshot(
                workbook=self.workbook_name,
                sheet=self.sheet_name,
                used_range="A1",
                header_row=1,
                columns=["A"],
                headers=[""],
                values=[[None]],
                formulas=[[None]],
                selection=self.selection,
                has_merged_cells=self.has_merged_cells,
            )

        used_range = bounding_range(self._grid.keys())
        r1, c1, r2, c2 = parse_range(used_range)
        columns = [index_to_col(c) for c in range(c1, c2 + 1)]

        values: list[list[CellValue]] = []
        formulas: list[list[str | None]] = []
        for r in range(r1, r2 + 1):
            row_vals: list[CellValue] = []
            row_forms: list[str | None] = []
            for c in range(c1, c2 + 1):
                addr = f"{index_to_col(c)}{r}"
                cell_info = self._grid.get(addr, {})
                row_vals.append(cell_info.get("value"))
                row_forms.append(cell_info.get("formula"))
            values.append(row_vals)
            formulas.append(row_forms)

        headers: list[str] = []
        if values:
            for val in values[0]:
                headers.append(display_value(val))
        else:
            headers = ["" for _ in columns]

        return SheetSnapshot(
            workbook=self.workbook_name,
            sheet=self.sheet_name,
            used_range=used_range,
            header_row=r1,
            columns=columns,
            headers=headers,
            values=values,
            formulas=formulas,
            selection=self.selection,
            has_merged_cells=self.has_merged_cells,
        )

    def read_region(self, region: str) -> RegionState:
        """Read values, formulas, and fills for a bounding region."""
        clean_region = region.replace("$", "")
        r1, c1, r2, c2 = parse_range(clean_region)

        values: list[list[CellValue]] = []
        formulas: list[list[str | None]] = []
        fills: list[list[str | None]] = []

        for r in range(r1, r2 + 1):
            row_vals: list[CellValue] = []
            row_forms: list[str | None] = []
            row_fills: list[str | None] = []
            for c in range(c1, c2 + 1):
                addr = f"{index_to_col(c)}{r}"
                cell_info = self._grid.get(addr, {})
                row_vals.append(cell_info.get("value"))
                row_forms.append(cell_info.get("formula"))
                row_fills.append(cell_info.get("fill"))
            values.append(row_vals)
            formulas.append(row_forms)
            fills.append(row_fills)

        return RegionState(
            sheet=self.sheet_name,
            region=clean_region,
            values=values,
            formulas=formulas,
            fills=fills,
        )

    def apply_patch(self, patch: Patch) -> None:
        """Apply patch to in-memory grid and record in applied_patches."""
        self.applied_patches.append(patch)
        for change in patch.cells:
            addr = change.address.replace("$", "")
            if change.after_formula is not None:
                self._grid.setdefault(addr, {})["formula"] = change.after_formula
                self._grid[addr]["value"] = None
            else:
                self._grid.setdefault(addr, {})["formula"] = None
                self._grid[addr]["value"] = change.after

        for fmt in patch.formats:
            addr = fmt.address.replace("$", "")
            self._grid.setdefault(addr, {})["fill"] = fmt.fill_hex

    def restore_region(self, state: RegionState) -> None:
        """Restore in-memory grid from RegionState."""
        clean_region = state.region.replace("$", "")
        r1, c1, r2, c2 = parse_range(clean_region)
        num_rows = r2 - r1 + 1
        num_cols = c2 - c1 + 1

        for i in range(num_rows):
            for j in range(num_cols):
                addr = f"{index_to_col(c1 + j)}{r1 + i}"
                val = (
                    state.values[i][j]
                    if i < len(state.values) and j < len(state.values[i])
                    else None
                )
                form = (
                    state.formulas[i][j]
                    if i < len(state.formulas) and j < len(state.formulas[i])
                    else None
                )
                fill = (
                    state.fills[i][j]
                    if i < len(state.fills) and j < len(state.fills[i])
                    else None
                )
                self._grid[addr] = {"value": val, "formula": form, "fill": fill}

    def calculate(self) -> None:
        """Record calculate call."""
        self.calculate_called += 1

    def read_values(self, region: str) -> list[list[CellValue]]:
        """Return in-memory values, returning formula string for formula cells."""
        clean_region = region.replace("$", "")
        r1, c1, r2, c2 = parse_range(clean_region)
        result: list[list[CellValue]] = []

        for r in range(r1, r2 + 1):
            row_vals: list[CellValue] = []
            for c in range(c1, c2 + 1):
                addr = f"{index_to_col(c)}{r}"
                cell_info = self._grid.get(addr, {})
                formula = cell_info.get("formula")
                if formula is not None:
                    row_vals.append(formula)
                else:
                    row_vals.append(cell_info.get("value"))
            result.append(row_vals)
        return result

