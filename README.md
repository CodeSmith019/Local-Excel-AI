# Local LLM Excel AI

> An offline, privacy-first AI copilot for Microsoft Excel desktop on Windows, powered by local LLMs via `llama.cpp` and deterministic Python.

---

## 📌 Prerequisites

- **OS**: Windows 10/11 (x64)
- **Python**: Python 3.12 (managed via `uv`)
- **Package Manager**: [uv](https://github.com/astral-sh/uv) (>= 0.5.0)
- **Spreadsheet**: Microsoft Excel desktop (Windows) with calculation set to Automatic
- **Local LLM Engine**:
  - `llama-server.exe` placed in `llama/`
  - Model weights placed in `models/`:
    - Dell G15: `models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf`
    - Yoga Pro 7: `models/gpt-oss-20b-mxfp4.gguf` (and optionally Qwen 7B for parity tests)

---

## 🚀 Setup

1. **Clone the repository**:
   ```powershell
   git clone <repo-url>
   cd mp2
   ```

2. **Install dependencies with `uv`**:
   ```powershell
   uv sync
   ```

3. **Verify the local environment**:
   ```powershell
   uv run python scripts/check_setup.py
   ```
   This will verify your Python version, check for `llama-server.exe`, list available GGUF models in `models/`, and test the model server endpoint.

---

## 🖥️ Running the Application

### 1. Start `llama-server`

Open a terminal and run the startup script for your hardware profile:

- **Dell G15 (NVIDIA GPU)**:
  ```powershell
  scripts\start_llm_dell.bat
  ```
- **Yoga Pro 7 (AMD / Integrated / Parity)**:
  ```powershell
  scripts\start_llm_yoga.bat
  ```
  *(To run in parity mode with the Qwen 7B model on Yoga, run: `scripts\start_llm_yoga.bat qwen`)*

### 2. Start the FastAPI Backend

Open a second terminal and start the backend with your profile:

- **Dell G15**:
  ```powershell
  scripts\start_backend.bat dell
  ```
- **Yoga Pro 7**:
  ```powershell
  scripts\start_backend.bat yoga
  ```

The backend starts at `http://127.0.0.1:8000/`.

### 3. Open the Web Interface

Open your browser to:
[http://127.0.0.1:8000/](http://127.0.0.1:8000/)

You will see the placeholder status page showing health details retrieved from `/api/health`.

---

## 🧪 Testing and Code Quality

Run the test suite:
```powershell
# Run unit and integration tests (excluding tests that require a live Excel desktop instance)
uv run pytest -q -m "not excel"

# Run all tests (requires active Excel desktop session)
uv run pytest -q
```

Run code formatting and lint checks:
```powershell
uv run ruff check .
```

---

## 🛡️ Core Safety Rules

1. **100% Offline at Runtime**: No external APIs, cloud telemetry, analytics, remote fonts, or CDNs. Communication happens strictly over localhost.
2. **The LLM Never Edits Cells Directly**: The LLM only identifies the operation and validates structured arguments. Deterministic Python constructs a formal `Patch`.
3. **Mandatory Human-in-the-Loop Preview**: Every modification generates a side-by-side preview with cell diffs. The user must approve or reject before anything touches Excel.
4. **Snapshot-Based Complete Undo**: Every applied change is snapshotted into local SQLite storage, enabling reliable rollback.
5. **Thread-Safe COM Automation**: All Excel COM interactions run through an isolated single worker thread.

---

## 📂 Project Structure

```text
├── backend/
│   ├── api/             # FastAPI routes (health, SSE chat, confirm, undo)
│   ├── agent/           # LangGraph state machine, nodes, and graphs
│   ├── excel/           # COM worker thread, xlwings adapter, serializer, A1 math
│   ├── llm/             # ChatOpenAI client, structured schemas, prompt templates
│   ├── ops/             # Deterministic operations registry (Tiers 1, 2, 3)
│   ├── schemas/         # Pydantic models for snapshots, patches, targets, and API
│   └── storage/         # SQLite persistence and snapshot-based undo engine
├── frontend/            # Local browser UI (HTML, CSS, JS)
├── config/              # Hardware/machine environment profiles (.env)
├── scripts/             # Startup scripts, fixture generators, diagnostics, LLM benchmarks
├── tests/               # Unit, integration, and eval test suites
├── models/              # Local GGUF model files (gitignored)
└── llama/               # llama.cpp server binaries (gitignored)
```
