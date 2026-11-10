"""Generate test fixture workbooks (employees.xlsx and sales.xlsx) according to Section 12."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

EMPLOYEES_SHEET = "Employees"
EMPLOYEES_HEADERS = [
    "Emp ID",
    "Full Name",
    "Department",
    "Email",
    "Phone",
    "Salary",
    "Join Date",
    "City",
    "Status",
    "Rating",
]
EMPLOYEES_ROWS = [
    [101, "  john smith ", "Sales", "john.smith@acme.com", "(555) 123-4567", 52000, "2021-03-04", "New York", "Active", 4.2],
    [102, "PRIYA SHARMA", "Engineering", "priya.sharma@acme.com", "555.987.6543", 78000, "2019-07-15", "Pune", "Active", 4.8],
    [103, "carlos  mendez", "Marketing", "carlos.mendez@acme.com", "555-222-3333", 61000, "2022-01-10", None, "Inactive", 3.9],
    [104, "Aisha Khan", "Sales", "aisha.khan@acme.com", "+1 555 444 5555", 49500, "2023-05-22", "Chicago", "Active", 4.0],
    [105, "li wei", "Engineering", "li.wei@acme.com", "5556667777", 83000, "2018-11-30", "Seattle", "Active", 4.6],
    [106, "Tom O'Brien", "Finance", "tom.obrien@acme.com", "(555) 888-9999", 58000, "2020-02-17", None, "Inactive", 3.5],
    [107, "priya sharma", "Engineering", "priya.sharma@acme.com", "555.987.6543", 78000, "2019-07-15", "Pune", "Active", 4.8],
    [108, "Elena Petrova", "HR", "elena.petrova@acme.com", "555-101-2020", 55000, "2021-09-01", "Boston", "Active", 4.1],
    [109, "raj patel", "Finance", "raj.patel@acme.com", "555 303 4040", 67000, "2017-04-12", "New York", "Active", 4.4],
    [110, "Sara  Lee ", "Marketing", "sara.lee@acme.com", "555-505-6060", 45000, "2024-06-03", "Chicago", "Inactive", 3.7],
]

SALES_SHEET = "Sales"
SALES_HEADERS = [
    "Order ID",
    "Region",
    "Product",
    "Qty",
    "Unit Price",
    "Order Date",
    "Customer",
    "Paid",
    "Discount",
    "Notes",
]
SALES_ROWS = [
    ["SO-1001", "North", "Laptop", 2, 850, "2026-01-05", "Acme Corp", "Yes", 0.05, "urgent delivery"],
    ["SO-1002", "South", "Mouse", 15, 12.5, "2026-01-07", "Beta Ltd", "No", 0, None],
    ["SO-1003", "East", "Monitor", 4, 210, "2026-01-12", "Acme Corp", "Yes", 0.1, "bulk order"],
    ["SO-1004", "West", "Keyboard", 10, 35, "2026-02-02", "Gamma Inc", "Yes", 0, None],
    ["SO-1005", "North", "Laptop", 1, 900, "2026-02-14", "Delta LLC", "No", 0, "gift wrap"],
    ["SO-1006", "South", "Monitor", 3, 199, "2026-02-20", "Beta Ltd", "Yes", 0.05, None],
    ["SO-1007", "East", "Mouse", 25, 11, "2026-03-01", "Gamma Inc", "Yes", 0.15, "bulk order"],
    ["SO-1008", "West", "Laptop", 2, 875, "2026-03-09", "Acme Corp", "No", 0, None],
    ["SO-1009", "North", "Keyboard", 8, 32, "2026-03-15", "Delta LLC", "Yes", 0, "follow up"],
    ["SO-1010", "South", "Monitor", 5, 205, "2026-03-28", "Gamma Inc", "Yes", 0.1, None],
]


def create_workbook(
    sheet_title: str,
    headers: list[str],
    rows: list[list[object]],
    date_col_idx: int,
    output_path: Path,
) -> None:
    """Create an Excel workbook with bold headers, real dates, and sensible column widths."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title

    # Write header row
    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = Font(bold=True)

    # Write data rows
    for row in rows:
        row_copy = list(row)
        # Convert date string to real date
        if row_copy[date_col_idx] is not None and isinstance(row_copy[date_col_idx], str):
            row_copy[date_col_idx] = date.fromisoformat(row_copy[date_col_idx])
        ws.append(row_copy)

    # Format date cells and adjust column widths
    for col_idx in range(1, len(headers) + 1):
        col_letter = get_column_letter(col_idx)
        max_len = len(str(headers[col_idx - 1]))

        for row_idx in range(2, len(rows) + 2):
            cell = ws.cell(row=row_idx, column=col_idx)
            if col_idx - 1 == date_col_idx and isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
                val_len = 10
            elif cell.value is not None:
                val_len = len(str(cell.value))
            else:
                val_len = 0
            max_len = max(max_len, val_len)

        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Created: {output_path}")


def main() -> None:
    """Generate both fixture workbooks."""
    fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    create_workbook(
        EMPLOYEES_SHEET,
        EMPLOYEES_HEADERS,
        EMPLOYEES_ROWS,
        date_col_idx=6,
        output_path=fixtures_dir / "employees.xlsx",
    )
    create_workbook(
        SALES_SHEET,
        SALES_HEADERS,
        SALES_ROWS,
        date_col_idx=5,
        output_path=fixtures_dir / "sales.xlsx",
    )


if __name__ == "__main__":
    main()
