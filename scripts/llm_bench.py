"""Benchmark script measuring prompt and generation speed against local llama-server.

Directly queries {llm_base_url}/chat/completions using httpx with a ~1,500-token prompt,
repeats 5 times, extracts server timings, prints min and average speeds, and saves
results to data/bench/<machine_name>_<YYYYmmdd_HHMMSS>.json.
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure repository root is on sys.path for standalone script execution
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import httpx

from backend.config import get_settings


def build_benchmark_prompt() -> str:
    """Build a ~1,500-token prompt containing a 10x10 markdown table and JSON task."""
    table_header = (
        "| ID | Full Name | Department | Role | Email | Location | Base Salary | "
        "Hire Date | Strategic Project Assignment | Performance Appraisal Summary |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )

    rows = [
        (
            "| EMP-1001 | Dr. Alexander Vance | Research & Development | Principal Systems Architect | "
            "alexander.vance@enterprise-corp.internal | Boston Technical Campus, Building 4 | $145,000 | "
            "2018-03-15 | Leading multi-quarter migration of enterprise columnar query storage engine to "
            "vectorized execution pipelines with zero-downtime replication. | Consistently exceeds technical "
            "delivery milestones while demonstrating exceptional architectural mentorship across engineering teams. |"
        ),
        (
            "| EMP-1002 | Sarah Montgomery-Chen | Global Operations | Director of Logistics Automation | "
            "sarah.chen@enterprise-corp.internal | Chicago Distribution Hub, Facility North | $132,000 | "
            "2019-07-22 | Coordinating automated guided vehicles fleet telemetry integration with internal "
            "SAP ERP inventory routing software. | Transformed warehouse turnaround latency by 28 percent over "
            "consecutive fiscal quarters; highly valued cross-functional leader. |"
        ),
        (
            "| EMP-1003 | Marcus Aurelius Thorne | Corporate Infrastructure | Senior Database Administrator | "
            "marcus.thorne@enterprise-corp.internal | New York Headquarters, Floor 32 | $124,500 | "
            "2020-01-10 | Modernizing mission-critical PostgreSQL clustering topologies with continuous point-in-time "
            "recovery and asynchronous off-site hot standbys. | Exceptional operational discipline during severe cloud "
            "provider network outages; resolved database failover within 45 seconds. |"
        ),
        (
            "| EMP-1004 | Elena Rostova-Ivanova | Information Security | Lead Incident Response Specialist | "
            "elena.rostova@enterprise-corp.internal | Frankfurt Secure Operations Center | $118,000 | "
            "2021-05-18 | Implementing automated endpoint threat detection heuristics with behavioral anomaly "
            "quarantine across 12,000 corporate workstations. | Authored gold-standard internal runbooks for ransomware "
            "containment; regularly conducts high-fidelity adversary simulations. |"
        ),
        (
            "| EMP-1005 | Rajeshwar Patel | Quantitative Analytics | Lead Financial Systems Modeler | "
            "rajesh.patel@enterprise-corp.internal | London Financial Center, Canary Wharf | $138,000 | "
            "2017-11-04 | Designing Monte Carlo risk sensitivity engines for multi-currency trade exposures under "
            "extreme liquidity stress scenarios. | Recognized by the Executive Committee for identifying derivative "
            "hedging mismatches six weeks before quarterly close. |"
        ),
        (
            "| EMP-1006 | Samantha Joanne Miller | Product Strategy | VP of Digital Commerce Experience | "
            "samantha.miller@enterprise-corp.internal | San Francisco Tech Center, 5th Floor | $152,000 | "
            "2016-08-30 | Spearheading unified customer omnichannel checkout platform integrating local payment "
            "methods across 42 sovereign territories. | Unmatched visionary product execution; expanded mobile "
            "conversion funnel throughput by 19 percent year-over-year. |"
        ),
        (
            "| EMP-1007 | Takashi Takahashi | Quality Engineering | Staff Reliability Automation Architect | "
            "takashi.takahashi@enterprise-corp.internal | Tokyo Regional Office, Shinjuku Tower | $121,000 | "
            "2021-09-12 | Developing distributed end-to-end chaos engineering test harnesses validating microservice "
            "fault resilience under artificial packet drops. | Exceptional rigor in automated regression test coverage; "
            "reduced customer-reported production escapes by 41 percent. |"
        ),
        (
            "| EMP-1008 | Fatima Al-Mansoor | Human Resources & Culture | Head of Global Talent Acquisition | "
            "fatima.mansoor@enterprise-corp.internal | Dubai Internet City, Innovation Hub | $112,000 | "
            "2022-02-01 | Deploying algorithmic talent matching systems and predictive attrition forecasting dashboards "
            "for specialized senior engineering hires. | Reduced average technical vacancy fulfillment cycle from 84 "
            "days to 37 days while elevating candidate satisfaction. |"
        ),
        (
            "| EMP-1009 | Liam Patrick O'Connor | Legal Compliance | Senior Regulatory Affairs Counsel | "
            "liam.oconnor@enterprise-corp.internal | Dublin Regulatory Campus, Docklands | $129,000 | "
            "2019-10-15 | Conducting international cross-border data transfer impact assessments and managing "
            "statutory data sovereignty compliance across EU jurisdictions. | Provided impeccable legal guidance "
            "during complex multinational regulatory audits with zero compliance penalties. |"
        ),
        (
            "| EMP-1010 | Beatriz Silveira Santos | Customer Experience | Senior Operations Enablement Manager | "
            "beatriz.santos@enterprise-corp.internal | São Paulo Regional Center, Berrini | $98,000 | "
            "2023-04-11 | Streamlining tier-3 enterprise escalations workflow with intelligent priority queuing and "
            "multilingual knowledge graph integration. | Raised net promoter score for enterprise account support "
            "from 61 to 84 within first twelve months of rollout. |"
        ),
    ]

    instruction = (
        "\n\nINSTRUCTION:\n"
        "Carefully analyze the 10 employee records in the table above.\n"
        "Respond strictly with a compact JSON object containing exactly the following keys:\n"
        "- total_records (integer): total count of employee records in table\n"
        "- departments (array of strings): sorted unique list of all department names\n"
        "- highest_paid_employee (string): full name of the employee with the highest salary\n"
        "- summary (string): concise one-sentence executive summary of the global distribution\n"
        "Return valid JSON only. Do not include markdown codeblocks or conversational preamble."
    )

    return table_header + "\n".join(rows) + instruction


def main() -> None:
    """Run the benchmark against llama-server and record metrics."""
    settings = get_settings()
    endpoint = f"{settings.llm_base_url.rstrip('/')}/chat/completions"

    prompt_text = build_benchmark_prompt()
    approx_tokens = len(prompt_text) // 4
    print("=" * 65)
    print("  LOCAL LLM BENCHMARK (llama-server)")
    print(f"  Machine Profile: {settings.machine_name}")
    print(f"  Target Endpoint: {endpoint}")
    print(f"  Model Name:      {settings.llm_model}")
    print(f"  Prompt Size:     ~{approx_tokens} tokens ({len(prompt_text)} characters)")
    print("=" * 65)

    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "system",
                "content": "You are a specialized enterprise data analysis engine. Always output pure valid JSON.",
            },
            {"role": "user", "content": prompt_text},
        ],
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        **settings.llm_extra_body,
    }

    runs: list[dict] = []
    num_runs = 5

    try:
        with httpx.Client(timeout=float(settings.llm_timeout_s)) as client:
            for i in range(1, num_runs + 1):
                print(f"\n[Run {i}/{num_runs}] Sending request to llama-server...", flush=True)
                t0 = time.perf_counter()
                resp = client.post(endpoint, json=payload)
                t_wall = time.perf_counter() - t0

                if resp.status_code != 200:
                    print(f"  [ERROR] Server returned HTTP {resp.status_code}: {resp.text}")
                    sys.exit(1)

                data = resp.json()
                timings = data.get("timings")
                usage = data.get("usage", {})

                if timings and "prompt_per_second" in timings:
                    prompt_n = int(timings.get("prompt_n", 0))
                    prompt_per_sec = float(timings.get("prompt_per_second", 0.0))
                    predicted_n = int(timings.get("predicted_n", 0))
                    predicted_per_sec = float(timings.get("predicted_per_second", 0.0))
                    source = "llama-server timings"
                else:
                    prompt_n = int(usage.get("prompt_tokens", approx_tokens))
                    predicted_n = int(usage.get("completion_tokens", 0))
                    predicted_per_sec = (predicted_n / t_wall) if t_wall > 0 else 0.0
                    prompt_per_sec = (prompt_n / t_wall) if t_wall > 0 else 0.0
                    source = "wall-clock fallback"

                print(f"  Source:    {source}")
                print(f"  Prompt:    {prompt_n} tokens @ {prompt_per_sec:.2f} tokens/s")
                print(f"  Predicted: {predicted_n} tokens @ {predicted_per_sec:.2f} tokens/s")
                print(f"  Wall time: {t_wall:.2f} s")

                runs.append({
                    "run": i,
                    "source": source,
                    "prompt_n": prompt_n,
                    "prompt_per_second": round(prompt_per_sec, 2),
                    "predicted_n": predicted_n,
                    "predicted_per_second": round(predicted_per_sec, 2),
                    "wall_clock_s": round(t_wall, 3),
                    "raw_timings": timings,
                })

    except httpx.ConnectError as exc:
        print(f"\n[CONNECTION ERROR] Could not reach llama-server at {endpoint}: {exc}")
        print("Please start llama-server before running the benchmark.")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[UNEXPECTED ERROR] Benchmark failed: {type(exc).__name__}: {exc}")
        sys.exit(1)

    prompt_speeds = [r["prompt_per_second"] for r in runs]
    pred_speeds = [r["predicted_per_second"] for r in runs]

    min_prompt = min(prompt_speeds)
    avg_prompt = sum(prompt_speeds) / len(prompt_speeds)
    min_pred = min(pred_speeds)
    avg_pred = sum(pred_speeds) / len(pred_speeds)

    print("\n" + "=" * 65)
    print("  BENCHMARK SUMMARY")
    print(f"  Prompt Evaluation Speed:   min: {min_prompt:.2f} t/s | avg: {avg_prompt:.2f} t/s")
    print(f"  Token Generation Speed:    min: {min_pred:.2f} t/s | avg: {avg_pred:.2f} t/s")
    print("=" * 65)

    # Save to data/bench/<machine_name>_<YYYYmmdd_HHMMSS>.json
    bench_dir = Path("data") / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    filename = f"{settings.machine_name}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    bench_file = bench_dir / filename

    report = {
        "machine_name": settings.machine_name,
        "timestamp_utc": now.isoformat(),
        "model": settings.llm_model,
        "endpoint": endpoint,
        "runs_count": num_runs,
        "summary": {
            "prompt_tokens_per_second": {
                "min": round(min_prompt, 2),
                "avg": round(avg_prompt, 2),
            },
            "predicted_tokens_per_second": {
                "min": round(min_pred, 2),
                "avg": round(avg_pred, 2),
            },
        },
        "runs": runs,
    }

    bench_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved benchmark results to: {bench_file}")


if __name__ == "__main__":
    main()
