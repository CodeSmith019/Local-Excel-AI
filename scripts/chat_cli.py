"""Command-line chat client for Excel AI assistant."""

import argparse
import json
import sys
from collections.abc import Generator, Iterable

import httpx


def parse_sse_stream(lines: Iterable[str]) -> Generator[tuple[str, str], None, None]:
    """Parse SSE lines into (event_type, json_data) tuples."""
    event_type = "message"
    data_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if data_lines:
                yield event_type, "\n".join(data_lines)
                event_type = "message"
                data_lines = []
            continue

        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())

    if data_lines:
        yield event_type, "\n".join(data_lines)


def handle_undo(base_url: str) -> None:
    """Trigger undo endpoint and display result."""
    url = f"{base_url.rstrip('/')}/api/undo"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url)
            resp.raise_for_status()
            data = resp.json()
            if data.get("restored"):
                print(f"[undo] Restored: {data.get('summary')}")
            else:
                print(f"[undo] Nothing to undo: {data.get('summary')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[undo error] {exc}", file=sys.stderr)
        sys.exit(1)


def handle_chat(base_url: str, message: str) -> None:
    """Send user instruction to /api/chat and handle interactive confirmation."""
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    confirm_url = f"{base_url.rstrip('/')}/api/confirm"

    with httpx.Client(timeout=120.0) as client:
        try:
            with client.stream("POST", chat_url, json={"message": message}) as response:
                response.raise_for_status()
                for event_type, raw_data in parse_sse_stream(response.iter_lines()):
                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        data = {"raw": raw_data}

                    if event_type == "status":
                        print(f"[{data.get('node', 'status')}] {data.get('label', '')}")
                    elif event_type == "plan":
                        print(f"\n[Plan] {data.get('op_title', '')} ({data.get('op', '')})")
                        print(f"       {data.get('explanation', '')}\n")
                    elif event_type == "preview":
                        thread_id = data.get("thread_id", "")
                        summary = data.get("summary", "")
                        changes = data.get("changes", [])
                        formats = data.get("formats", [])
                        warnings = data.get("warnings", [])

                        print(f"\n=== PREVIEW: {summary} ===")
                        if changes:
                            print(
                                f"{'Address':<10} | {'Before':<22} | {'After':<22} | {'Formula'}"
                            )
                            print("-" * 75)
                            for ch in changes:
                                addr = ch.get("address", "")
                                before = str(ch.get("before") or "")
                                after = str(ch.get("after") or "")
                                formula = str(ch.get("formula") or "")
                                print(
                                    f"{addr:<10} | {before:<22} | {after:<22} | {formula}"
                                )

                        if formats:
                            print(f"Formatting changes: {len(formats)} cell(s)")
                        if warnings:
                            print(f"Warnings: {warnings}")

                        # Prompt user for confirmation
                        ans = input("\nApply? [y/n]: ").strip().lower()
                        approved = ans in ("y", "yes")

                        # Send confirmation to resume graph
                        with client.stream(
                            "POST",
                            confirm_url,
                            json={"thread_id": thread_id, "approved": approved},
                        ) as conf_resp:
                            conf_resp.raise_for_status()
                            for c_type, c_raw in parse_sse_stream(
                                conf_resp.iter_lines()
                            ):
                                try:
                                    c_data = json.loads(c_raw)
                                except json.JSONDecodeError:
                                    c_data = {"raw": c_raw}

                                if c_type == "status":
                                    print(
                                        f"[{c_data.get('node', 'status')}] {c_data.get('label', '')}"
                                    )
                                elif c_type == "done":
                                    applied_str = (
                                        "Applied"
                                        if c_data.get("applied")
                                        else "Not applied"
                                    )
                                    print(f"\n[{applied_str}] {c_data.get('summary', '')}")
                                elif c_type == "error":
                                    print(
                                        f"\n[error] {c_data.get('message', '')}",
                                        file=sys.stderr,
                                    )
                    elif event_type == "done":
                        applied_str = (
                            "Applied" if data.get("applied") else "Not applied"
                        )
                        print(f"\n[{applied_str}] {data.get('summary', '')}")
                    elif event_type == "error":
                        print(f"\n[error] {data.get('message', '')}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    """Parse CLI arguments and dispatch chat or undo action."""
    parser = argparse.ArgumentParser(description="Excel AI Assistant Chat CLI")
    parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Instruction for Excel assistant (e.g. 'convert headers to camelCase')",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Undo the last applied change",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of backend server (default: http://127.0.0.1:8000)",
    )

    args = parser.parse_args()

    if args.undo:
        handle_undo(args.base_url)
    elif args.message:
        handle_chat(args.base_url, args.message)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
