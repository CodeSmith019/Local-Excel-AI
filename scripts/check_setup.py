"""Diagnostic script to check environment, binaries, models, and server health."""

import sys
import urllib.error
import urllib.request
from pathlib import Path


def check_setup() -> None:
    """Run all environment and dependency checks, reporting OK / MISSING."""
    root_dir = Path(__file__).resolve().parent.parent

    # 1. Python version
    py_ver = sys.version.split()[0]
    if sys.version_info[:2] == (3, 12):
        print(f"[OK] Python version: {py_ver}")
    else:
        print(f"[MISSING] Python 3.12 required, detected: {py_ver}")

    # 2. llama-server binary
    llama_server = root_dir / "llama" / "llama-server.exe"
    if llama_server.is_file():
        print(f"[OK] llama-server executable: {llama_server.relative_to(root_dir)}")
    else:
        print(f"[MISSING] llama-server executable under {llama_server.relative_to(root_dir)}")

    # 3. .gguf models
    models_dir = root_dir / "models"
    gguf_files = list(models_dir.glob("*.gguf")) if models_dir.is_dir() else []
    if gguf_files:
        for model in gguf_files:
            print(f"[OK] Model found: {model.name}")
    else:
        print("[MISSING] No .gguf model files found under models/")

    # 4. llama-server HTTP health check
    health_url = "http://127.0.0.1:8080/health"
    try:
        req = urllib.request.Request(health_url, headers={"User-Agent": "Excel-AI-Diagnostic"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                print(f"[OK] llama-server reachable at {health_url}")
            else:
                print(f"[MISSING] llama-server returned HTTP {resp.status} at {health_url}")
    except Exception as exc:  # noqa: BLE001 (spec: must never crash; print OK / MISSING per line)
        print(f"[MISSING] llama-server not answering at {health_url} ({type(exc).__name__})")


if __name__ == "__main__":
    check_setup()
