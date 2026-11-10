"""Evaluation and benchmarking runner for Local LLM Excel AI.

Measures accuracy and latency across Tier 1, Tier 2, Tier 3, and unsupported operations.
Reuses a single hidden Excel instance via COM thread and outputs detailed metrics in CSV and Markdown.
"""

import argparse
import asyncio
import csv
import fnmatch
import logging
import math
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import backend.agent.nodes
from backend.agent.graph import build_graph
from backend.config import get_settings
from backend.excel.com_thread import com_thread
from backend.excel.xlwings_adapter import XlwingsAdapter, create_hidden_app, quit_app
from backend.schemas.sheet import CellValue

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "case_id",
    "repetition",
    "tier",
    "fixture",
    "instruction",
    "expected_op",
    "op_chosen",
    "op_correct",
    "cells_correct",
    "fully_correct",
    "retries",
    "error",
    "latency_total_ms",
    "latency_read_sheet_ms",
    "latency_classify_intent_ms",
    "latency_extract_params_ms",
    "latency_execute_op_ms",
    "latency_validate_ms",
    "latency_preview_ms",
    "latency_apply_patch_ms",
    "llm_calls",
    "prompt_tokens",
    "completion_tokens",
    "params_extracted",
]

EXCEL_ERRORS = {
    "#NAME?",
    "#REF!",
    "#VALUE!",
    "#DIV/0!",
    "#N/A",
    "#NUM!",
    "#NULL!",
    "#SPILL!",
    "#CALC!",
}


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for eval runner."""
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run Excel AI evaluation benchmark.")
    parser.add_argument(
        "--cases",
        type=str,
        default=None,
        help="Case IDs or glob pattern(s) separated by commas (e.g. 't1_*', 't1_headers_camel').",
    )
    parser.add_argument(
        "--tier",
        type=int,
        default=None,
        help="Filter evaluation cases by tier number (0, 1, 2, or 3).",
    )
    parser.add_argument(
        "--model-label",
        type=str,
        default=settings.llm_model,
        help=f"Model label for reports (default: {settings.llm_model}).",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to repeat each case (default: 1).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop execution immediately on first failure.",
    )
    return parser.parse_args()


def load_cases(
    yaml_path: Path,
    tier_filter: int | None = None,
    cases_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Load and filter test cases from YAML configuration file."""
    with open(yaml_path, encoding="utf-8") as f:
        cases: list[dict[str, Any]] = yaml.safe_load(f)

    filtered = cases
    if tier_filter is not None:
        filtered = [c for c in filtered if c.get("tier") == tier_filter]

    if cases_filter:
        patterns = [p.strip() for p in cases_filter.split(",") if p.strip()]
        matched = []
        for c in filtered:
            cid = c.get("id", "")
            if any(fnmatch.fnmatch(cid, pat) for pat in patterns):
                matched.append(c)
        filtered = matched

    return filtered


async def fetch_server_metadata(base_url: str) -> tuple[str, str]:
    """Retrieve model path and context size from llama-server if reachable."""
    model_path = "unavailable"
    context_size = "unavailable"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r_models = await client.get(f"{base_url.rstrip('/')}/models")
            if r_models.status_code == 200:
                data = r_models.json()
                if "data" in data and len(data["data"]) > 0:
                    model_path = data["data"][0].get("id", "unknown")

            server_root = base_url.rstrip("/").removesuffix("/v1")
            r_props = await client.get(f"{server_root}/props")
            if r_props.status_code == 200:
                props = r_props.json()
                gen_settings = props.get("default_generation_settings", {})
                ctx = gen_settings.get("n_ctx", props.get("n_ctx"))
                if ctx is not None:
                    context_size = str(ctx)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed querying llama-server metadata: %s", exc)

    return model_path, context_size


def compute_percentile(values: list[float], p: float) -> float:
    """Compute percentile value using nearest rank method."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = math.ceil((p / 100.0) * len(sorted_vals)) - 1
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


async def evaluate_single_case(
    case: dict[str, Any],
    repetition: int,
    shared_app: Any,
    fixtures_dir: Path,
    temp_dir: Path,
) -> dict[str, Any]:
    """Run a single test case evaluation and return recorded metrics."""
    case_id = case["id"]
    tier = case.get("tier", 1)
    fixture_name = case["fixture"]
    instruction = case["instruction"]
    expected_op = case.get("expected_op")
    volatile = bool(case.get("volatile", False))
    expected_cells: dict[str, Any] = case.get("expected") or {}
    must_not_change: list[str] = case.get("must_not_change") or []

    # Copy fixture to temp directory
    src_fixture = fixtures_dir / fixture_name
    temp_book_path = temp_dir / f"{case_id}_{repetition}_{uuid.uuid4().hex[:6]}_{fixture_name}"
    shutil.copy2(src_fixture, temp_book_path)

    adapter: XlwingsAdapter | None = None
    try:
        adapter = await com_thread.run(XlwingsAdapter, book_path=temp_book_path, app=shared_app)

        # Pre-read must_not_change ranges
        pre_unchanged_values: dict[str, list[list[CellValue]]] = {}
        for rng in must_not_change:
            pre_vals = await com_thread.run(adapter.read_values, rng)
            pre_unchanged_values[rng] = pre_vals

        # Set up graph & checkpointer
        checkpointer = InMemorySaver()
        graph = build_graph(checkpointer)
        tid = f"eval_{case_id}_{repetition}_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": tid, "adapter": adapter}}
        initial_state = {
            "thread_id": tid,
            "user_message": instruction,
            "retries": 0,
            "validation_errors": [],
        }

        # Track LLM calls and tokens
        llm_calls = 0
        prompt_tokens = 0
        completion_tokens = 0
        orig_structured_call = backend.agent.nodes.structured_call

        async def tracking_structured_call(*args: Any, **kwargs: Any) -> Any:
            nonlocal llm_calls, prompt_tokens, completion_tokens
            res = await orig_structured_call(*args, **kwargs)
            llm_calls += 1
            usage = getattr(res, "usage", {}) or {}
            p_tok = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            c_tok = usage.get("completion_tokens") or usage.get("output_tokens") or 0
            prompt_tokens += int(p_tok)
            completion_tokens += int(c_tok)
            return res

        backend.agent.nodes.structured_call = tracking_structured_call

        node_latencies: dict[str, float] = {
            "read_sheet": 0.0,
            "classify_intent": 0.0,
            "extract_params": 0.0,
            "execute_op": 0.0,
            "validate": 0.0,
            "preview": 0.0,
            "apply_patch": 0.0,
        }

        total_t0 = time.perf_counter()
        interrupted = False
        t_node_start = time.perf_counter()

        try:
            async for chunk in graph.astream(initial_state, config=config, stream_mode="updates"):
                elapsed_ms = (time.perf_counter() - t_node_start) * 1000.0
                t_node_start = time.perf_counter()

                if "__interrupt__" in chunk:
                    interrupted = True
                    node_latencies["preview"] += elapsed_ms
                    break

                for node_name in chunk:
                    if node_name in node_latencies:
                        node_latencies[node_name] += elapsed_ms

            if interrupted:
                resume_cmd = Command(resume={"approved": True})
                t_node_start = time.perf_counter()
                async for chunk in graph.astream(
                    resume_cmd, config=config, stream_mode="updates"
                ):
                    elapsed_ms = (time.perf_counter() - t_node_start) * 1000.0
                    t_node_start = time.perf_counter()
                    for node_name in chunk:
                        if node_name in node_latencies:
                            node_latencies[node_name] += elapsed_ms
        finally:
            backend.agent.nodes.structured_call = orig_structured_call

        total_latency_ms = (time.perf_counter() - total_t0) * 1000.0

        # Retrieve final state
        state_snap = await graph.aget_state(config)
        final_state = state_snap.values
        op_chosen = final_state.get("op")
        retries = final_state.get("retries", 0)
        error = final_state.get("error")
        applied = bool(final_state.get("applied", False))
        params_extracted = final_state.get("params")

        # Determine accuracy
        op_correct = (op_chosen == expected_op)

        cells_correct = True
        cell_failure_reasons: list[str] = []

        if expected_op == "unsupported":
            cells_correct = (op_chosen == "unsupported")
        elif error or not applied:
            cells_correct = False
            cell_failure_reasons.append(error or "Patch was not applied")
        else:
            for addr, exp_val in expected_cells.items():
                val_grid = await com_thread.run(adapter.read_values, addr)
                act_val = val_grid[0][0] if (val_grid and val_grid[0]) else None

                if volatile:
                    region_st = await com_thread.run(adapter.read_region, addr)
                    formula = (
                        region_st.formulas[0][0]
                        if (region_st.formulas and region_st.formulas[0])
                        else None
                    )
                    if formula is None or not str(formula).startswith("="):
                        cells_correct = False
                        cell_failure_reasons.append(f"{addr}: missing formula (got {formula})")
                        break
                    act_str = str(act_val) if act_val is not None else ""
                    if any(err in act_str for err in EXCEL_ERRORS):
                        cells_correct = False
                        cell_failure_reasons.append(f"{addr}: excel error {act_str}")
                        break
                else:
                    if exp_val is None:
                        if act_val is not None and str(act_val).strip() != "":
                            cells_correct = False
                            cell_failure_reasons.append(f"{addr}: expected None, got '{act_val}'")
                            break
                    elif isinstance(exp_val, (int, float)):
                        try:
                            if act_val is None or abs(float(act_val) - float(exp_val)) > 0.01:
                                cells_correct = False
                                cell_failure_reasons.append(
                                    f"{addr}: expected {exp_val}, got {act_val}"
                                )
                                break
                        except (ValueError, TypeError):
                            cells_correct = False
                            cell_failure_reasons.append(
                                f"{addr}: non-numeric value '{act_val}' for expected {exp_val}"
                            )
                            break
                    else:
                        exp_str = str(exp_val)
                        act_str = str(act_val) if act_val is not None else ""
                        if act_str != exp_str:
                            cells_correct = False
                            cell_failure_reasons.append(
                                f"{addr}: expected '{exp_str}', got '{act_str}'"
                            )
                            break

            if cells_correct:
                for rng, orig_vals in pre_unchanged_values.items():
                    curr_vals = await com_thread.run(adapter.read_values, rng)
                    if curr_vals != orig_vals:
                        cells_correct = False
                        cell_failure_reasons.append(f"Range {rng} unexpectedly changed")
                        break

        if cell_failure_reasons and not error:
            error = "; ".join(cell_failure_reasons)

        fully_correct = op_correct and cells_correct and (
            error is None or expected_op == "unsupported"
        )

        return {
            "case_id": case_id,
            "repetition": repetition,
            "tier": tier,
            "fixture": fixture_name,
            "instruction": instruction,
            "expected_op": expected_op,
            "op_chosen": op_chosen,
            "op_correct": op_correct,
            "cells_correct": cells_correct,
            "fully_correct": fully_correct,
            "retries": retries,
            "error": error or "",
            "latency_total_ms": round(total_latency_ms, 2),
            "latency_read_sheet_ms": round(node_latencies["read_sheet"], 2),
            "latency_classify_intent_ms": round(node_latencies["classify_intent"], 2),
            "latency_extract_params_ms": round(node_latencies["extract_params"], 2),
            "latency_execute_op_ms": round(node_latencies["execute_op"], 2),
            "latency_validate_ms": round(node_latencies["validate"], 2),
            "latency_preview_ms": round(node_latencies["preview"], 2),
            "latency_apply_patch_ms": round(node_latencies["apply_patch"], 2),
            "llm_calls": llm_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "params_extracted": str(params_extracted) if params_extracted else "",
        }

    finally:
        if adapter is not None:
            await com_thread.run(adapter.close)
        if temp_book_path.exists():
            try:
                temp_book_path.unlink()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed deleting temp file %s: %s", temp_book_path, exc)


def generate_markdown_summary(
    records: list[dict[str, Any]],
    machine: str,
    model_label: str,
    model_path: str,
    context_size: str,
    timestamp_str: str,
) -> str:
    """Generate Markdown summary report from evaluation results."""
    lines: list[str] = []
    lines.append(f"# Evaluation Summary — {machine} — {model_label}")
    lines.append(f"**Date:** {timestamp_str}")
    lines.append(f"**Machine:** `{machine}`")
    lines.append(f"**Model Label:** `{model_label}`")
    lines.append(f"**Server Model Path:** `{model_path}`")
    lines.append(f"**Server Context Size:** `{context_size}`")
    lines.append("")

    # 1. Accuracy per Tier
    lines.append("## 1. Accuracy per Tier")
    lines.append("| Tier | Count | Op Acc (%) | Cell Acc (%) | Full Acc (%) |")
    lines.append("|---|---|---|---|---|")

    all_tiers = sorted({r["tier"] for r in records})
    for t in all_tiers:
        t_records = [r for r in records if r["tier"] == t]
        count = len(t_records)
        op_acc = sum(1 for r in t_records if r["op_correct"]) / count * 100.0 if count else 0.0
        cell_acc = (
            sum(1 for r in t_records if r["cells_correct"]) / count * 100.0 if count else 0.0
        )
        full_acc = (
            sum(1 for r in t_records if r["fully_correct"]) / count * 100.0 if count else 0.0
        )
        tier_title = f"Tier {t}" if t > 0 else "Unsupported (0)"
        lines.append(
            f"| {tier_title} | {count} | {op_acc:.1f}% | {cell_acc:.1f}% | {full_acc:.1f}% |"
        )

    total_count = len(records)
    tot_op = sum(1 for r in records if r["op_correct"]) / total_count * 100.0 if total_count else 0.0
    tot_cell = (
        sum(1 for r in records if r["cells_correct"]) / total_count * 100.0 if total_count else 0.0
    )
    tot_full = (
        sum(1 for r in records if r["fully_correct"]) / total_count * 100.0 if total_count else 0.0
    )
    lines.append(
        f"| **Overall** | **{total_count}** | **{tot_op:.1f}%** | **{tot_cell:.1f}%** | **{tot_full:.1f}%** |"
    )
    lines.append("")

    # 2. Accuracy per Operation
    lines.append("## 2. Accuracy per Operation")
    lines.append("| Expected Op | Tier | Count | Op Acc (%) | Full Acc (%) |")
    lines.append("|---|---|---|---|---|")

    ops = sorted({r["expected_op"] for r in records})
    for op in ops:
        op_records = [r for r in records if r["expected_op"] == op]
        count = len(op_records)
        op_tier = op_records[0]["tier"]
        op_acc = sum(1 for r in op_records if r["op_correct"]) / count * 100.0 if count else 0.0
        full_acc = (
            sum(1 for r in op_records if r["fully_correct"]) / count * 100.0 if count else 0.0
        )
        lines.append(f"| `{op}` | {op_tier} | {count} | {op_acc:.1f}% | {full_acc:.1f}% |")
    lines.append("")

    # 3. Latency & Resource Usage per Tier
    lines.append("## 3. Latency & LLM Resource Usage per Tier")
    lines.append("| Tier | Median Latency (ms) | P90 Latency (ms) | Median LLM Calls | Avg Prompt Tokens | Avg Comp Tokens |")
    lines.append("|---|---|---|---|---|---|")

    for t in all_tiers:
        t_records = [r for r in records if r["tier"] == t]
        lats = [float(r["latency_total_ms"]) for r in t_records]
        calls = [float(r["llm_calls"]) for r in t_records]
        p_toks = [float(r["prompt_tokens"]) for r in t_records]
        c_toks = [float(r["completion_tokens"]) for r in t_records]

        med_lat = compute_percentile(lats, 50)
        p90_lat = compute_percentile(lats, 90)
        med_calls = compute_percentile(calls, 50)
        avg_ptok = sum(p_toks) / len(p_toks) if p_toks else 0.0
        avg_ctok = sum(c_toks) / len(c_toks) if c_toks else 0.0
        tier_title = f"Tier {t}" if t > 0 else "Unsupported (0)"
        lines.append(
            f"| {tier_title} | {med_lat:.1f} | {p90_lat:.1f} | {med_calls:.0f} | {avg_ptok:.0f} | {avg_ctok:.0f} |"
        )
    lines.append("")

    # 4. Top Failures
    failures = [r for r in records if not r["fully_correct"]]
    lines.append("## 4. Top Failures (Up to 10)")
    if not failures:
        lines.append("No failures! All cases completed with full accuracy.")
    else:
        lines.append("| Case ID | Instruction | Expected Op | Chosen Op | Retries | Error / Failure Reason |")
        lines.append("|---|---|---|---|---|---|")
        for f in failures[:10]:
            cid = f["case_id"]
            instr = f["instruction"].replace("|", "\\|")
            exp = f["expected_op"]
            act = f["op_chosen"]
            retries = f["retries"]
            err = (f["error"] or "Cell mismatch").replace("|", "\\|")
            lines.append(f"| `{cid}` | {instr} | `{exp}` | `{act}` | {retries} | {err} |")
    lines.append("")

    return "\n".join(lines)


def write_results(
    csv_path: Path,
    md_path: Path,
    records: list[dict[str, Any]],
    md_summary: str,
) -> None:
    """Save records to CSV and summary report to Markdown."""
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(r)
    print(f"\nWrote CSV output to: {csv_path}")

    with open(md_path, mode="w", encoding="utf-8") as f:
        f.write(md_summary)
    print(f"Wrote Markdown summary to: {md_path}\n")


async def main_async() -> int:
    """Async main routine running evaluation."""
    args = parse_args()
    settings = get_settings()

    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
    yaml_path = Path(__file__).resolve().parent / "eval_prompts.yaml"

    cases = load_cases(yaml_path, tier_filter=args.tier, cases_filter=args.cases)
    if not cases:
        print("No cases matched the specified filters.", file=sys.stderr)
        return 1

    print(
        f"Starting evaluation of {len(cases)} cases (repeat={args.repeat}, total runs={len(cases) * args.repeat})..."
    )
    print(f"Machine: {settings.machine_name} | Model: {args.model_label}")

    model_path, context_size = await fetch_server_metadata(settings.llm_base_url)
    print(f"Server model: {model_path} | Context size: {context_size}")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_machine = re.sub(r"[^a-zA-Z0-9_-]", "_", settings.machine_name)
    clean_model = re.sub(r"[^a-zA-Z0-9_-]", "_", args.model_label)
    eval_dir = settings.data_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    csv_path = eval_dir / f"{clean_machine}_{clean_model}_{timestamp_str}.csv"
    md_path = eval_dir / f"{clean_machine}_{clean_model}_{timestamp_str}.md"

    # Create temporary directory for fixture copies
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="exai_eval_")
    temp_dir = Path(temp_dir_obj.name)

    # Initialize single shared Excel instance
    print("Launching shared hidden Excel instance on COM thread...")
    shared_app = await com_thread.run(create_hidden_app)

    records: list[dict[str, Any]] = []
    stop_early = False

    try:
        total_runs = len(cases) * args.repeat
        run_idx = 0

        for rep in range(1, args.repeat + 1):
            if stop_early:
                break
            for case in cases:
                run_idx += 1
                cid = case["id"]
                print(
                    f"[{run_idx}/{total_runs}] Running {cid} (rep {rep}/{args.repeat})... ",
                    end="",
                    flush=True,
                )

                record = await evaluate_single_case(
                    case,
                    repetition=rep,
                    shared_app=shared_app,
                    fixtures_dir=fixtures_dir,
                    temp_dir=temp_dir,
                )
                records.append(record)

                status_str = "OK" if record["fully_correct"] else "FAIL"
                lat = record["latency_total_ms"]
                print(f"{status_str} ({lat:.0f}ms)")

                if args.fail_fast and not record["fully_correct"]:
                    print(
                        f"\nFail-fast triggered on case '{cid}': {record['error'] or 'Mismatch'}"
                    )
                    stop_early = True
                    break

    finally:
        print("Closing shared Excel instance...")
        await com_thread.run(quit_app, shared_app)
        com_thread.shutdown()
        temp_dir_obj.cleanup()

    # Write outputs
    md_summary = generate_markdown_summary(
        records,
        machine=settings.machine_name,
        model_label=args.model_label,
        model_path=model_path,
        context_size=context_size,
        timestamp_str=timestamp_str,
    )
    write_results(csv_path, md_path, records, md_summary)

    # Print summary to console
    print("=" * 80)
    print(md_summary)
    print("=" * 80)

    # Return 0 if all correct or ran to completion
    return 0


def main() -> None:
    """Entry point for CLI execution."""
    exit_code = asyncio.run(main_async())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
