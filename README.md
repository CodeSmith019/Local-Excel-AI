# Local LLM Excel AI

> An offline, privacy-first AI copilot for Microsoft Excel desktop on Windows, powered by local LLMs via `llama.cpp` and deterministic Python.

---

## 📌 Overview

**Local LLM Excel AI** enables natural language spreadsheet manipulation directly on Windows desktop without sending data to any cloud service. 

Users type instructions in plain English (such as *"convert headers to camelCase"*, *"remove duplicate rows by email"*, or *"add a Total column = Qty x Unit Price"*). The system uses a local quantized LLM to understand **intent and parameters**, while deterministic, testable Python code computes the exact changes, presents an interactive preview, and applies modifications only upon explicit user approval.

---

## 🛡️ Core Principles & Safety Rules

1. **100% Offline at Runtime**  
   All computation occurs locally. No external APIs, cloud telemetry, analytics, remote fonts, or CDN dependencies. The only communication happens over localhost between the UI, FastAPI backend, Excel, and `llama-server`.
2. **The LLM Never Edits Cells Directly**  
   The LLM only identifies the operation and validates structured arguments. Deterministic Python constructs a formal `Patch` object containing cell diffs and formatting changes.
3. **Mandatory Human-in-the-Loop Preview**  
   Every modification generates a side-by-side preview with computed cell diffs and warnings. The user must approve or reject the patch before anything touches the spreadsheet.
4. **Snapshot-Based Complete Undo**  
   Excel's native `Ctrl+Z` does not undo actions performed via COM automation. Every applied patch is snapshotted into a local SQLite undo store, enabling reliable rollback.
5. **Thread-Safe COM Automation**  
   All Excel interactions run through a dedicated single COM worker thread to eliminate Windows COM concurrency issues.

---

## 🏗️ Architecture

```text
Excel Desktop (Windows)
      ▲
      │ COM (xlwings, isolated single worker thread)
      ▼
FastAPI Backend (localhost:8000)
  ├── LangGraph State Machine (agent flow)
  ├── Deterministic Operation Handlers (backend/ops)
  └── SQLite Undo Store & Checkpointing
      ▲                              ▲
      │ HTTP + SSE                   │ OpenAI-compatible HTTP (localhost:8080)
      ▼                              ▼
Local Chat UI (HTML / Vanilla JS)  llama-server (llama.cpp + GGUF model)
```

### LangGraph Agent Flow

```text
START ──► read_sheet ──► classify_intent
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
      [unsupported]                          [valid op]
            │                                     │
            ▼                                     ▼
    finish_unsupported                      extract_params
            │                                     │
            ▼                                     ▼
           END                              execute_op
                                                  │
                                                  ▼
                                               validate ──(error / retry)──┐
                                                  │                        │
                                      ┌───────────┴───────────┐            │
                                  [no changes]               [ok] ◄────────┘
                                      │                       │
                                      ▼                       ▼
                               finish_nothing              preview (Interrupt)
                                      │                       │
                                      ▼               ┌───────┴───────┐
                                     END              ▼               ▼
                                                 [approved]      [rejected]
                                                      │               │
                                                      ▼               ▼
                                                 apply_patch   finish_cancelled
                                                      │               │
                                                      ▼               ▼
                                                     END             END
```

---

## ⚙️ Scope of Operations

The system handles operations across three distinct tiers:

### 🔤 Tier 1: Text Transforms
- **Change Text Case**: Convert targeted columns or ranges to uppercase, lowercase, title case, or sentence case.
- **Convert Case Style**: Transform column headers to `camelCase`, `snake_case`, `kebab-case`, or `PascalCase`.
- **Trim Whitespace**: Remove leading, trailing, and redundant inner spaces from cell contents.
- **Find and Replace**: Literal string substitutions across targeted columns or ranges.
- **Add Prefix / Suffix**: Append or prepend fixed text to cell values.
- **Remove Characters**: Strip punctuation, non-alphanumeric symbols, or non-digit characters.

### 📐 Tier 2: Structural Changes
- **Sort Rows**: Sort table records by one or more columns in ascending or descending order.
- **Filter / Delete Rows**: Remove rows matching specific criteria (e.g., status, numerical thresholds, empty values).
- **Remove Duplicates**: Deduplicate records based on specific key columns or full rows.
- **Insert / Delete / Move Columns**: Add empty or default-value columns, remove columns, or reorder column positions.
- **Rename Columns**: Update header names while preserving row alignment.
- **Fill Blanks**: Impute empty cells with constants or forward/backward values.
- **Highlight Cells**: Apply Excel soft cell formatting / background fills according to rules.

### 🧮 Tier 3: Single-Formula Generation
- **Formula Columns**: Compute row-wise formulas for a new or existing column (e.g., `=D2*E2`, `=TEXT(G2,"yyyy-mm")`, string concatenations).
- **Summary Formulas**: Insert summary calculations below tables (e.g., `=SUM(F2:F11)`, `=AVERAGE(...)`, `=COUNTIF(...)`).
- **Validation**: Generated formulas are validated against allowed Excel functions and tested before applying to avoid Excel calculation errors (`#NAME?`, `#VALUE!`, `#REF!`).

---

## 🛠️ Tech Stack

- **Language & Runtime**: Python 3.12 (managed via `uv`)
- **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [SSE-Starlette](https://github.com/sysid/sse-starlette)
- **Agent & Orchestration**: [LangGraph](https://github.com/langchain-ai/langgraph), [LangChain Core](https://github.com/langchain-ai/langchain)
- **Data Validation & Schemas**: [Pydantic v2](https://docs.pydantic.dev/), `pydantic-settings`
- **Spreadsheet Automation**: [xlwings](https://www.xlwings.org/), `pywin32`
- **Data & File Processing**: `pandas`, `openpyxl`
- **Local Inference Engine**: [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`) with GGUF models (e.g. Qwen2.5-Coder-7B-Instruct, GPT-OSS-20B)
- **Persistence & State**: SQLite (via `langgraph-checkpoint-sqlite` and custom undo tables)
- **Testing & Code Quality**: `pytest`, `pytest-asyncio`, `ruff`
- **Frontend**: Local web interface (HTML5, CSS3, vanilla JavaScript with Server-Sent Events)

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

