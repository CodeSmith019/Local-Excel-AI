"""Compare evaluation runs from data/eval/*.csv and output a Markdown table."""

import argparse
import csv
import glob
import math
import re
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for run comparison."""
    parser = argparse.ArgumentParser(
        description="Compare evaluation benchmark runs across machines and models."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Path(s) to evaluation CSV files. If omitted, scans data/eval/*.csv.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional path to write the Markdown comparison table.",
    )
    return parser.parse_args()


def compute_median(values: list[float]) -> float:
    """Compute 50th percentile (median) value."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = math.ceil(0.5 * len(sorted_vals)) - 1
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


def parse_filename_metadata(csv_path: Path) -> tuple[str, str, str]:
    """Extract machine, model_label, and timestamp from filename."""
    stem = csv_path.stem
    match = re.match(r"^([^_]+(?:-[^_]+)*)_(.+)_(\d{8}_\d{6})$", stem)
    if match:
        return match.group(1), match.group(2), match.group(3)
    parts = stem.split("_")
    if len(parts) >= 3:
        return parts[0], "_".join(parts[1:-2]), "_".join(parts[-2:])
    return stem, "unknown", ""


def analyze_csv(csv_path: Path) -> dict[str, Any] | None:
    """Read an evaluation CSV and compute summary statistics."""
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return None

    machine, model_label, timestamp = parse_filename_metadata(csv_path)

    t1_rows = [r for r in rows if r.get("tier") == "1"]
    t2_rows = [r for r in rows if r.get("tier") == "2"]
    t3_rows = [r for r in rows if r.get("tier") == "3"]

    def calc_acc(subset: list[dict[str, str]]) -> float:
        if not subset:
            return 0.0
        correct = sum(1 for r in subset if r.get("fully_correct", "").lower() in ("true", "1"))
        return correct / len(subset) * 100.0

    t1_acc = calc_acc(t1_rows)
    t2_acc = calc_acc(t2_rows)
    t3_acc = calc_acc(t3_rows)
    overall_acc = calc_acc(rows)

    def calc_median_latency(subset: list[dict[str, str]]) -> float:
        lats: list[float] = []
        for r in subset:
            try:
                lats.append(float(r.get("latency_total_ms", 0.0)))
            except (ValueError, TypeError):
                continue
        return compute_median(lats)

    t1_lat = calc_median_latency(t1_rows)
    t2_lat = calc_median_latency(t2_rows)
    t3_lat = calc_median_latency(t3_rows)

    total_retries = 0
    for r in rows:
        try:
            total_retries += int(r.get("retries", 0))
        except (ValueError, TypeError):
            continue
    avg_retries = total_retries / len(rows) if rows else 0.0

    return {
        "file": csv_path.name,
        "machine": machine,
        "model": model_label,
        "timestamp": timestamp,
        "total_cases": len(rows),
        "t1_acc": t1_acc,
        "t2_acc": t2_acc,
        "t3_acc": t3_acc,
        "overall_acc": overall_acc,
        "t1_lat": t1_lat,
        "t2_lat": t2_lat,
        "t3_lat": t3_lat,
        "avg_retries": avg_retries,
    }


def format_comparison_table(results: list[dict[str, Any]]) -> str:
    """Format evaluation run results as a Markdown table."""
    lines: list[str] = []
    lines.append("# Evaluation Benchmark Comparison")
    lines.append("")
    lines.append(
        "| Machine | Model | Tier 1 Acc | Tier 2 Acc | Tier 3 Acc | Overall Acc | Median Latency (T1 / T2 / T3) | Retries / Case | Run Timestamp |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|"
    )

    for res in results:
        m = res["machine"]
        model = res["model"]
        t1 = f"{res['t1_acc']:.1f}%"
        t2 = f"{res['t2_acc']:.1f}%"
        t3 = f"{res['t3_acc']:.1f}%"
        overall = f"{res['overall_acc']:.1f}%"
        lat = f"{res['t1_lat']:.0f}ms / {res['t2_lat']:.0f}ms / {res['t3_lat']:.0f}ms"
        retries = f"{res['avg_retries']:.2f}"
        ts = res["timestamp"]
        lines.append(
            f"| `{m}` | `{model}` | {t1} | {t2} | {t3} | {overall} | {lat} | {retries} | {ts} |"
        )

    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    args = parse_args()

    files = args.files
    if not files:
        files = sorted(glob.glob("data/eval/*.csv"))

    if not files:
        print("No evaluation CSV files found.", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    for fp in files:
        p = Path(fp)
        if not p.is_file():
            print(f"Skipping non-existent file: {p}", file=sys.stderr)
            continue
        analyzed = analyze_csv(p)
        if analyzed is not None:
            results.append(analyzed)

    if not results:
        print("No valid evaluation data found in CSV files.", file=sys.stderr)
        return 1

    table_md = format_comparison_table(results)
    print(table_md)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, mode="w", encoding="utf-8") as f:
            f.write(table_md + "\n")
        print(f"\nSaved comparison table to: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
