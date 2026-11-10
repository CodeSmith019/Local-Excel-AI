"""Manual verification probe for live Excel connection and undo capabilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.excel.adapter import ExcelNotConnectedError
from backend.excel.serializer import snapshot_to_prompt
from backend.excel.xlwings_adapter import XlwingsAdapter
from backend.schemas.patch import CellChange, Patch
from backend.storage.undo import pop_latest, save_snapshot


def main() -> None:
    print("=" * 60)
    print("Excel AI — Phase 3 Live Excel Probe")
    print("=" * 60)

    adapter = XlwingsAdapter()
    try:
        desc = adapter.describe()
        if not desc["connected"]:
            fixture_path = (
                Path(__file__).resolve().parent.parent
                / "tests"
                / "fixtures"
                / "employees.xlsx"
            )
            if fixture_path.exists():
                print(
                    f"No active workbook found. Opening '{fixture_path.name}' via adapter..."
                )
                adapter = XlwingsAdapter(book_path=fixture_path)
                desc = adapter.describe()
            else:
                print(f"Error: {desc['error']}")
                print(
                    "Please open 'tests/fixtures/employees.xlsx' in Microsoft Excel and rerun."
                )
                sys.exit(1)

        print(f"Connected to Excel: {desc['workbook']} (Sheet: {desc['sheet']})\n")

        print("--- 1. Snapshot Prompt Text (What the LLM sees) ---")
        snapshot = adapter.read_snapshot()
        prompt_text = snapshot_to_prompt(snapshot)
        print(prompt_text)
        print("--------------------------------------------------\n")

        print("--- 2. Saving undo snapshot for B2:B3 ---")
        original_state = adapter.read_region("B2:B3")
        snap_id = save_snapshot(
            thread_id="probe",
            state=original_state,
            summary="Probe upper-case test on B2:B3",
        )
        print(f"Saved undo snapshot ID: {snap_id}")

        print("--- 3. Applying patch: Uppercase B2:B3 ---")
        val_b2 = original_state.values[0][0]
        val_b3 = original_state.values[1][0]
        patch = Patch(
            op="change_case",
            sheet=snapshot.sheet,
            cells=[
                CellChange(address="B2", before=val_b2, after=str(val_b2).upper()),
                CellChange(address="B3", before=val_b3, after=str(val_b3).upper()),
            ],
            summary="Upper-cased B2:B3",
        )
        adapter.apply_patch(patch)
        print("Patch applied to Excel!")

        print("\n>>> Check Excel: cells B2 and B3 should now be UPPERCASE.")
        try:
            input(">>> Press Enter to restore original values... ")
        except (EOFError, KeyboardInterrupt):
            print("Proceeding with restoration...")

        print("\n--- 4. Restoring region from undo store ---")
        popped = pop_latest()
        if popped is None:
            print("Error: No snapshot found to restore.")
            sys.exit(1)

        state_to_restore, summary = popped
        adapter.restore_region(state_to_restore)
        print(f"Restored: '{summary}'")
        print("Original cell values have been restored in Excel. Probe complete!")

    except ExcelNotConnectedError as exc:
        print(f"Excel connection failed: {exc}")
        print("Please open 'tests/fixtures/employees.xlsx' in Excel and try again.")
        sys.exit(1)
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
