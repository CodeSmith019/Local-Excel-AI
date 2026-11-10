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

## 🎬 Demo Day Checklist (One-Click Start & Excel Task Pane)

Use this checklist for a live or offline demonstration of Excel AI:

### 1. Prerequisites (One-Time Setup)
- Ensure certificates are installed and trusted:
  ```powershell
  npx office-addin-dev-certs install
  ```
- Ensure the Excel Add-in is sideloaded via Shared Folder Catalog (see [docs/ADDIN_SETUP.md](docs/ADDIN_SETUP.md)).
- If testing offline capability, **turn Wi-Fi OFF**.

### 2. One-Click Cold Start
Launch all components with one command:
- **Dell G15**:
  ```powershell
  scripts\start_all.bat dell https
  ```
- **Yoga Pro 7**:
  ```powershell
  scripts\start_all.bat yoga https
  ```
*This starts `llama-server` minimized, polls `/health` until ready, launches the HTTPS backend on port 8443, and opens Microsoft Excel.*

### 3. Open Test Workbook & Task Pane
1. In Excel, open one of the generated test workbooks:
   - `tests\fixtures\employees.xlsx`
   - or `tests\fixtures\sales.xlsx`
2. On the Excel ribbon **Home** tab, click the **Excel AI** button.
3. Verify both status dots in the task pane header are **green**:
   - 🟢 **Model**: `Qwen2.5-Coder-7B-Instruct-Q4_K_M` (or `gpt-oss-20b-mxfp4`)
   - 🟢 **Excel**: Connected to active workbook and sheet

### 4. Run Example Demo Instructions

#### Tier 1 — Text Transformation
- **Instruction**: `Convert headers to camelCase`
- **What happens**:
  - Agent classifies intent to `convert_case_style` (`style="camel"`).
  - Displays plan and side-by-side diff preview for all 10 headers (e.g. `Emp ID` -> `empId`, `Full Name` -> `fullName`).
  - Click **Approve**: changes are applied instantly in Excel.

#### Tier 2 — Structural Operations
- **Instruction**: `Sort by Salary, highest first`
- **What happens**:
  - Agent selects `sort_rows` (`by_column="Salary"`, `descending=True`).
  - Displays plan and preview showing reordered employee rows.
  - Click **Approve**: rows are sorted directly in Excel.

#### Tier 3 — Formula Computation
- Open `tests\fixtures\sales.xlsx` (or switch to Sales sheet).
- **Instruction**: `Add a Total column that multiplies Qty by Unit Price`
- **What happens**:
  - Agent selects `add_formula_column` (`header="Total"`, `formula="=D2*E2"`).
  - Trial-runs formula in Excel scratch area and previews computed values (e.g. `1700`, `187.5`).
  - Click **Approve**: new column `Total` is inserted with formulas and computed values.

#### Complete Undo Rollback
- Click the **Undo** button in the task pane header (or type `Undo`).
- **What happens**: The snapshot engine rolls back the sheet to its exact prior state.

### 5. Clean Shutdown
When the demonstration is complete, stop all background services:
```powershell
scripts\stop_all.bat
```

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

## 📊 Results

### Running the Evaluation Benchmark

The evaluation benchmark evaluates accuracy (intent classification, parameter extraction, and resulting cell values) and latency across Tier 1 (text transforms), Tier 2 (structural modifications), Tier 3 (formula generation), and unsupported requests using 43 hand-verified cases in `tests/eval/eval_prompts.yaml`.

```powershell
# Run full evaluation benchmark on the active hardware profile
uv run python tests/eval/run_eval.py

# Quick check on a single tier (e.g. Tier 1)
uv run python tests/eval/run_eval.py --tier 1

# Filter by case IDs or glob pattern
uv run python tests/eval/run_eval.py --cases "t1_*,t3_total_*"

# Custom model label, repetitions, or fail-fast
uv run python tests/eval/run_eval.py --model-label qwen2.5-coder-7b-instruct-q4_k_m --repeat 1 --fail-fast

# Compare multiple evaluation runs from data/eval/*.csv
uv run python scripts/compare_runs.py
```

Evaluation outputs are saved to `data/eval/<machine>_<model_label>_<YYYYmmdd_HHMMSS>.csv` and a companion Markdown report.

### Benchmark Results

| Machine | Model | Tier 1 Acc | Tier 2 Acc | Tier 3 Acc | Overall Acc | Median Latency (T1 / T2 / T3) | Retries / Case |
|---|---|---|---|---|---|---|---|
| `dell-g15` | `qwen2.5-coder-7b-instruct-q4_k_m` | 86.7% | 84.6% | 75.0% | 83.7% | 7854ms / 3966ms / 7441ms | 0.00 |
| `yoga-pro-7` | `gpt-oss-20b-mxfp4` | *TBD* | *TBD* | *TBD* | *TBD* | *TBD* | *TBD* |
| `yoga-pro-7` | `qwen2.5-coder-7b-instruct-q4_k_m` | *TBD* | *TBD* | *TBD* | *TBD* | *TBD* | *TBD* |

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
