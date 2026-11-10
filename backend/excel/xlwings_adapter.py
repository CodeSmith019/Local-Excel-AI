"""Xlwings-based adapter for live Excel desktop automation on Windows."""

import logging
from pathlib import Path
from typing import Any

import xlwings as xw

from backend.excel.a1 import index_to_col, parse_range
from backend.excel.adapter import ExcelNotConnectedError, WorkbookAdapter
from backend.excel.values import display_value
from backend.schemas.patch import Patch
from backend.schemas.sheet import CellValue, RegionState, SheetSnapshot

logger = logging.getLogger(__name__)


def create_hidden_app() -> xw.App:
    """Create a hidden Excel instance for batch runs."""
    app = xw.App(visible=False, add_book=False)
    app.display_alerts = False
    return app


def quit_app(app: xw.App | None) -> None:
    """Close all books and quit an Excel app instance."""
    if app is None:
        return
    try:
        for book in list(app.books):
            try:
                book.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed closing book during quit: %s", exc)
        app.quit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error quitting app: %s", exc)


class XlwingsAdapter(WorkbookAdapter):
    """Excel workbook adapter backed by xlwings and desktop Excel via COM."""

    def __init__(
        self,
        book_path: Path | str | None = None,
        app: xw.App | None = None,
    ) -> None:
        self._book_path = Path(book_path) if book_path else None
        self._app: xw.App | None = app
        self._owned_app = False
        self._opened_book: xw.Book | None = None

        if self._book_path is not None:
            if self._app is None:
                self._app = xw.App(visible=False, add_book=False)
                self._owned_app = True
            self._app.display_alerts = False
            self._opened_book = self._app.books.open(str(self._book_path.resolve()))

    def close(self) -> None:
        """Close opened workbooks and quit app if owned by this adapter."""
        if self._opened_book is not None:
            try:
                if self._app is not None:
                    self._app.display_alerts = False
                self._opened_book.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed closing opened book: %s", exc)
            self._opened_book = None

        if self._owned_app and self._app is not None:
            try:
                for book in list(self._app.books):
                    try:
                        book.close()
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Failed closing book: %s", exc)
                self._app.quit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing Excel instance: %s", exc)
            finally:
                self._app = None

    def _get_target(self) -> tuple[xw.App, xw.Book, xw.Sheet]:
        """Resolve active app, workbook, and worksheet.

        Never caches COM objects between method calls.
        """
        if self._app is not None:
            try:
                app = self._app
                if len(app.books) == 0:
                    raise ExcelNotConnectedError("Open a workbook in Excel first.")
                book = app.books.active
                sheet = book.sheets.active
                return app, book, sheet
            except ExcelNotConnectedError:
                raise
            except Exception as exc:
                raise ExcelNotConnectedError("Open a workbook in Excel first.") from exc

        try:
            app = xw.apps.active
        except Exception as exc:
            raise ExcelNotConnectedError("Open a workbook in Excel first.") from exc

        if app is None or len(app.books) == 0:
            raise ExcelNotConnectedError("Open a workbook in Excel first.")

        try:
            book = app.books.active
            sheet = book.sheets.active
            return app, book, sheet
        except Exception as exc:
            raise ExcelNotConnectedError("Open a workbook in Excel first.") from exc

    def describe(self) -> dict[str, Any]:
        """Describe connection status without raising exceptions."""
        try:
            _, book, sheet = self._get_target()
            return {
                "connected": True,
                "workbook": book.name,
                "sheet": sheet.name,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "connected": False,
                "workbook": None,
                "sheet": None,
                "error": str(exc),
            }

    def read_snapshot(self) -> SheetSnapshot:
        """Read active worksheet into SheetSnapshot."""
        app, book, sheet = self._get_target()
        used = sheet.used_range
        used_range_addr = used.address.replace("$", "")
        r1, c1, r2, c2 = parse_range(used_range_addr)

        raw_values = used.options(ndim=2).value
        raw_formula = used.formula

        formulas: list[list[str | None]] = []
        if r1 == r2 and c1 == c2:
            f_val = (
                str(raw_formula)
                if isinstance(raw_formula, str) and raw_formula.startswith("=")
                else None
            )
            formulas = [[f_val]]
        elif isinstance(raw_formula, (tuple, list)):
            for row in raw_formula:
                row_f: list[str | None] = []
                for cell_f in row:
                    if isinstance(cell_f, str) and cell_f.startswith("="):
                        row_f.append(cell_f)
                    else:
                        row_f.append(None)
                formulas.append(row_f)
        else:
            formulas = [[None for _ in range(c1, c2 + 1)] for _ in range(r1, r2 + 1)]

        header_row = r1
        columns = [index_to_col(c) for c in range(c1, c2 + 1)]

        headers: list[str] = []
        if raw_values and len(raw_values) > 0:
            first_row = raw_values[0]
            for val in first_row:
                headers.append(display_value(val))
        else:
            headers = ["" for _ in columns]

        selection: str | None = None
        try:
            sel = app.selection
            if sel is not None and sel.sheet.name == sheet.name:
                selection = sel.address.replace("$", "")
        except Exception:  # noqa: BLE001
            selection = None

        has_merged_cells = False
        try:
            has_merged_cells = used.api.MergeCells is not False
        except Exception:  # noqa: BLE001
            has_merged_cells = False

        return SheetSnapshot(
            workbook=book.name,
            sheet=sheet.name,
            used_range=used_range_addr,
            header_row=header_row,
            columns=columns,
            headers=headers,
            values=raw_values,
            formulas=formulas,
            selection=selection,
            has_merged_cells=has_merged_cells,
        )

    def read_region(self, region: str) -> RegionState:
        """Read region values, formulas, and fill colors."""
        _, _, sheet = self._get_target()
        clean_region = region.replace("$", "")
        rng = sheet.range(clean_region)
        r1, c1, r2, c2 = parse_range(clean_region)

        raw_values = rng.options(ndim=2).value
        raw_formula = rng.formula

        formulas: list[list[str | None]] = []
        if r1 == r2 and c1 == c2:
            f_val = (
                str(raw_formula)
                if isinstance(raw_formula, str) and raw_formula.startswith("=")
                else None
            )
            formulas = [[f_val]]
        elif isinstance(raw_formula, (tuple, list)):
            for row in raw_formula:
                row_f: list[str | None] = []
                for cell_f in row:
                    if isinstance(cell_f, str) and cell_f.startswith("="):
                        row_f.append(cell_f)
                    else:
                        row_f.append(None)
                formulas.append(row_f)
        else:
            formulas = [[None for _ in range(c1, c2 + 1)] for _ in range(r1, r2 + 1)]

        fills: list[list[str | None]] = []
        for row in rng.rows:
            row_fills: list[str | None] = []
            for cell in row:
                col = cell.color
                if col is not None and isinstance(col, tuple) and len(col) == 3:
                    row_fills.append(f"#{col[0]:02X}{col[1]:02X}{col[2]:02X}")
                else:
                    row_fills.append(None)
            fills.append(row_fills)

        return RegionState(
            sheet=sheet.name,
            region=clean_region,
            values=raw_values,
            formulas=formulas,
            fills=fills,
        )

    def apply_patch(self, patch: Patch) -> None:
        """Apply cell updates and color formats to worksheet."""
        app, _, sheet = self._get_target()
        old_updating = app.screen_updating
        try:
            app.screen_updating = False
            for change in patch.cells:
                cell_rng = sheet.range(change.address)
                if change.after_formula is not None:
                    cell_rng.formula = change.after_formula
                else:
                    cell_rng.value = change.after

            for fmt in patch.formats:
                cell_rng = sheet.range(fmt.address)
                if fmt.fill_hex is None:
                    cell_rng.color = None
                else:
                    clean_hex = fmt.fill_hex.lstrip("#")
                    r = int(clean_hex[0:2], 16)
                    g = int(clean_hex[2:4], 16)
                    b = int(clean_hex[4:6], 16)
                    cell_rng.color = (r, g, b)
        finally:
            app.screen_updating = old_updating

    def restore_region(self, state: RegionState) -> None:
        """Restore cell values, formulas, and fill colors from a RegionState."""
        app, _, sheet = self._get_target()
        old_updating = app.screen_updating
        try:
            app.screen_updating = False
            r1, c1, r2, c2 = parse_range(state.region)
            num_rows = r2 - r1 + 1
            num_cols = c2 - c1 + 1
            for i in range(num_rows):
                for j in range(num_cols):
                    addr = f"{index_to_col(c1 + j)}{r1 + i}"
                    cell_rng = sheet.range(addr)

                    formula = (
                        state.formulas[i][j]
                        if i < len(state.formulas) and j < len(state.formulas[i])
                        else None
                    )
                    if formula is not None:
                        cell_rng.formula = formula
                    else:
                        val = (
                            state.values[i][j]
                            if i < len(state.values) and j < len(state.values[i])
                            else None
                        )
                        cell_rng.value = val

                    fill = (
                        state.fills[i][j]
                        if i < len(state.fills) and j < len(state.fills[i])
                        else None
                    )
                    if fill is None:
                        cell_rng.color = None
                    else:
                        clean_hex = fill.lstrip("#")
                        r = int(clean_hex[0:2], 16)
                        g = int(clean_hex[2:4], 16)
                        b = int(clean_hex[4:6], 16)
                        cell_rng.color = (r, g, b)
        finally:
            app.screen_updating = old_updating

    def calculate(self) -> None:
        """Calculate formulas in Excel."""
        app, _, _ = self._get_target()
        app.calculate()

    def read_values(self, region: str) -> list[list[CellValue]]:
        """Read calculated values, returning errors as strings."""
        _, _, sheet = self._get_target()
        rng = sheet.range(region.replace("$", ""))
        return rng.options(ndim=2, err_to_str=True).value
