"""Smoke test script for local LLM structured output.

Runs 3 test calls to generate Excel formulas and validates the returned Pydantic objects.
Exits with code 1 if any call fails.
"""

import asyncio
import sys
from pathlib import Path

# Ensure repository root is on sys.path for standalone script execution
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from pydantic import BaseModel

from backend.llm.client import structured_call
from backend.llm.prompts import load_prompt


class SmokeAnswer(BaseModel):
    """Schema for smoke test formula response."""

    formula: str
    explanation: str


async def main() -> None:
    """Execute smoke test structured calls."""
    system_prompt = load_prompt("smoke_test")

    queries = [
        "Write an Excel formula to multiply D2 by E2",
        "Write an Excel formula to sum F2:F11",
        "Write an Excel formula: IF G2 is 'Yes' then 'Paid' else 'Due'",
    ]

    print("Running LLM smoke test (3 structured calls)...")
    failed = False

    for idx, user_prompt in enumerate(queries, 1):
        print(f"\n[Test {idx}/3] Instruction: {user_prompt}")
        result = await structured_call(SmokeAnswer, system_prompt, user_prompt)

        if result.value is not None:
            print(f"  -> Parsed Object: formula={result.value.formula!r}")
            print(f"     Explanation:   {result.value.explanation!r}")
            print(f"     Latency:       {result.latency_ms:.1f} ms")
        else:
            print(f"  -> FAILED: {result.error}")
            print(f"     Latency:       {result.latency_ms:.1f} ms")
            if result.raw_text:
                print(f"     Raw response:  {result.raw_text[:200]}")
            failed = True

    if failed:
        print("\n[FAIL] Smoke test encountered failures.")
        sys.exit(1)
    else:
        print("\n[OK] All 3 structured calls succeeded.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
