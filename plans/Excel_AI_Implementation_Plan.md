# Local LLM Excel AI — Phase-wise Implementation Plan · Tiers 1–3

*Version 1.0 · 27 October 2026 · Same content as `Excel_AI_Implementation_Plan.pdf`. Copy Antigravity prompts from this file: the code blocks keep exact line breaks.*

## Contents

1. Project Overview
2. Architecture
3. Tech Stack
4. Hardware & Model Configuration
5. Feature Scope (Tiers 1–3)
6. Project File Structure
7. Core Contracts
8. Working with Antigravity
9. Phase Roadmap
10. Phase 0 · Machine Setup
11. Phase 1 · Scaffold, Config & Health Check
12. Phase 2 · LLM Client & Structured Output
13. Phase 3 · Excel Bridge
14. Phase 4 · Tier 1 Text Operations
15. Phase 5 · LangGraph Agent & API
16. Phase 6 · Chat UI
17. Phase 7 · Tier 2 Structural Operations
18. Phase 8 · Tier 3 Formula Generation
19. Phase 9 · Evaluation & Benchmark
20. Phase 10 · Excel Task Pane & Packaging (stretch)
21. Testing Strategy
22. Risks & Mitigations
23. Appendix A · PROJECT_CONTEXT.md

---

# Project Overview

## Goal

Prove that a language model running **locally** on our own laptops can understand a plain-English instruction about an open Excel sheet and carry it out correctly, with no internet connection and no cloud AI service.

## Scope of this plan

- Small sheets of about 10 rows × 10 columns, the size we were asked to start with.
- **Tier 1: text transforms.** Case changes, camelCase / snake_case, trimming, find and replace, prefixes, removing characters.
- **Tier 2: structural changes.** Sort, filter, remove duplicates, insert / delete / rename / move columns, fill blanks, highlight.
- **Tier 3: single-formula generation.** Row-wise formulas filled down, plus summary formulas such as SUM, AVERAGE and COUNTIF.
- Tiers 4–6 are out of scope until the proof of concept is accepted. They cover lookups across sheets, tasks that depend on understanding the data, and multi-step agents.

## Core design principle

The model never edits cells itself. It only decides **what** to do: an operation name plus parameters, or a formula. Python code then computes the exact change, shows a before → after preview, and applies it only after the user clicks Apply. Every change can be undone.

This keeps each answer short (about 50 output tokens instead of rewriting 100 cells), makes small models reliable, and means every result can be checked automatically.

## Offline guarantee

Internet is needed only during setup (installing packages, downloading model files) and while coding with Antigravity. At runtime, Excel, the backend and the model server talk to each other only over `localhost`.

## Success criteria (suggested targets)

| Measure | Target (Dell, 7B model) |
|---|---|
| Tier 1 accuracy on the evaluation set | ≥ 90 % |
| Tier 2 accuracy on the evaluation set | ≥ 85 % |
| Tier 3 accuracy (computed values correct) | ≥ 75 % |
| Instruction → preview time, Tier 1–2 | ≤ 5 s |
| Instruction → preview time, Tier 3 | ≤ 10 s |
| Applied changes that can be undone | 100 % |
| Works with Wi-Fi switched off | Yes |

# Architecture

## Components

```text
┌────────────────────────── Windows laptop (fully offline) ──────────────────────────┐
│                                                                                    │
│  Microsoft Excel (desktop)  ◄──── COM via xlwings (one worker thread) ──────┐      │
│                                                                             │      │
│  Chat UI  (frontend/ : HTML + CSS + JS)                                     │      │
│  Phase 6: browser window beside Excel  ·  Phase 10: Excel task pane         │      │
│       │  HTTP + Server-Sent Events  ·  localhost:8000                       │      │
│       ▼                                                                     │      │
│  FastAPI backend ──► LangGraph agent ──► operations (Python) ──► Patch ─────┘      │
│       │                                                                            │
│       │  OpenAI-compatible HTTP  ·  localhost:8080                                 │
│       ▼                                                                            │
│  llama.cpp llama-server + GGUF model                                               │
│  CUDA build on the Dell  ·  Vulkan / SYCL build on the Yoga                        │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## What happens when the user sends an instruction

1. The chat UI sends the instruction to `POST /api/chat` and listens to a stream of progress events.
2. **read_sheet.** xlwings reads the active sheet (values, formulas, selection) into a `SheetSnapshot`. The serializer turns it into a compact text table with column letters and row numbers.
3. **classify_intent (LLM).** The model picks one operation id from the catalog, or `unsupported`.
4. **extract_params (LLM).** The model fills in that operation's parameter schema. llama-server constrains the output to valid JSON, and Pydantic validates it.
5. **execute_op (Python).** Computes a `Patch`: the exact list of cell changes.
6. **validate.** Checks the patch. For formulas it also test-runs them inside Excel. On an error, the error text goes back to step 4 (at most 2 retries).
7. **preview.** The graph pauses (LangGraph `interrupt`) and the UI shows a before → after table with Apply and Cancel buttons.
8. **apply_patch.** Saves an undo snapshot, then writes the patch to Excel.

## LangGraph flow

```text
START
  │
  ▼
read_sheet ──► classify_intent ──► extract_params ──► execute_op ──► validate
                    │                   ▲                              │
                    │ unsupported       └──── error (max 2 retries) ───┤
                    ▼                                                  │ ok
            finish_unsupported                                         ▼
                                                     preview  (interrupt: wait for user)
                                                        │ approved            │ rejected
                                                        ▼                     ▼
                                                   apply_patch        finish_cancelled
```

An empty patch ends in `finish_nothing`. An error that remains after the retries ends in `finish_error`. Every finish node and `apply_patch` lead to END.

# Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language / runtime | Python 3.12, managed by `uv` | Best wheel support for pywin32, xlwings and pandas. Python 3.14 is installed, but `uv` installs 3.12 side by side. |
| Inference engine | llama.cpp `llama-server` (prebuilt Windows binaries) | Runs as its own process with an OpenAI-compatible API and JSON-schema-constrained output. Builds exist for CUDA (Dell) and Vulkan / SYCL (Yoga). |
| Models | GGUF, Q4_K_M | Qwen2.5-Coder-7B-Instruct (Dell), gpt-oss-20b (Yoga) |
| LLM client | `langchain-openai` ChatOpenAI | Points at localhost. `.with_structured_output()` returns Pydantic objects. |
| Orchestration | LangGraph | Graph nodes, conditional retry edges, `interrupt` for user approval, checkpointing |
| Checkpoints and undo | SQLite (`langgraph-checkpoint-sqlite` plus our own table) | A local file with no setup |
| Backend API | FastAPI + Uvicorn + Pydantic v2 + sse-starlette | Async endpoints; progress is streamed to the UI |
| Configuration | pydantic-settings + `.env` profiles | One codebase with a settings file per laptop |
| Excel integration | xlwings (uses pywin32 / COM) | Reads and writes the open workbook live: values, formulas, colours, selection |
| Data operations | pandas, `re`, our own functions | Deterministic, testable transformations |
| Test workbooks | openpyxl | Generates the fixture `.xlsx` files |
| Frontend | Plain HTML + CSS + JavaScript, no build step | Simple. The same page later becomes the Excel task pane. |
| Testing | pytest, pytest-asyncio | Unit, integration and evaluation tests |
| Lint / format | ruff | Keeps Antigravity's code consistent |
| Coding agent | Google Antigravity | Writes the code phase by phase from the prompts in this plan |

# Hardware & Model Configuration

| | Dell G15 5530 | Lenovo Yoga Pro 7 Aura |
|---|---|---|
| CPU / RAM | i5-13450HX · 16 GB DDR5 | Core Ultra 9 285H · 32 GB LPDDR5x |
| GPU used for the model | RTX 3050 6 GB (CUDA) | Arc 140T iGPU (~16 GB shared memory) |
| llama.cpp build | `win-cuda` + matching `cudart` zip | `win-vulkan` (optionally try `win-sycl`) |
| Primary model | Qwen2.5-Coder-7B-Instruct Q4_K_M (~4.7 GB) | gpt-oss-20b MXFP4 (~13 GB) |
| Comparison model | – | Qwen2.5-Coder-7B-Instruct Q4_K_M (same as Dell) |
| Fast fallback | Qwen3-4B-Instruct-2507 Q4_K_M | Qwen3-4B-Instruct-2507 Q4_K_M |
| Context size (`-c`) | 4096 | 8192 |
| Generation speed (approx.) | 25–35 tokens/s | 12–20 tokens/s |
| Prompt reading speed (approx.) | 1,000–1,500 tokens/s | 200–500 tokens/s |
| Typical request (formula) | ~3–4 s | ~6–10 s |

Speeds are estimates for Q4 models with short prompts. Phase 2 measures the real numbers on each laptop.

## Launch commands

```text
Dell : llama\llama-server.exe -m models\Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf -ngl 99 -c 4096 --jinja --host 127.0.0.1 --port 8080
Yoga : llama\llama-server.exe -m models\gpt-oss-20b-mxfp4.gguf -ngl 99 -c 8192 --jinja --host 127.0.0.1 --port 8080
```

- `-ngl 99` puts every layer on the GPU. `-c` sets the context size. `--host 127.0.0.1` keeps the server private to the laptop.
- **Thinking models.** gpt-oss reasons before answering. The Yoga profile sets `reasoning_effort` to low (via `EXAI_LLM_EXTRA_BODY`) so requests stay fast. If you try Qwen3 hybrid models, use the *Instruct-2507* versions, which don't think.

# Feature Scope (Tiers 1–3)

| # | Tier | Feature | Operation id | Example instruction |
|---|---|---|---|---|
| 1 | 1 | Change case (UPPER, lower, Title, Sentence) | change_case | "Make the Department column uppercase" |
| 2 | 1 | camelCase / snake_case / PascalCase / kebab-case | convert_case_style | "Convert all column headers to camelCase" |
| 3 | 1 | Trim and clean spaces | trim_whitespace | "Remove extra spaces in Full Name" |
| 4 | 1 | Find and replace | find_replace | "Replace Inactive with Former in Status" |
| 5 | 1 | Add prefix / suffix | add_prefix_suffix | "Add EMP- before every Emp ID" |
| 6 | 1 | Remove characters | remove_characters | "Keep only digits in the Phone column" |
| 7 | 2 | Sort rows | sort_rows | "Sort by Salary, highest first" |
| 8 | 2 | Filter / delete rows | filter_rows | "Delete rows where Status is Inactive" |
| 9 | 2 | Remove duplicates | remove_duplicates | "Remove duplicate emails" |
| 10 | 2 | Insert / delete / rename / move columns | insert_column, delete_column, rename_column, move_column | "Move Email next to Full Name" |
| 11 | 2 | Fill blanks | fill_blanks | "Fill empty City cells with Unknown" |
| 12 | 2 | Highlight cells or rows | highlight_cells | "Highlight salaries above 60000 in green" |
| 13 | 3 | Summary formulas (SUM, AVERAGE, COUNT…) | add_summary_formula | "Add the total of Qty below the table" |
| 14 | 3 | Row-wise arithmetic, filled down | add_formula_column | "Add a Total column = Qty × Unit Price" |
| 15 | 3 | Conditional formulas (IF, COUNTIF, SUMIF) | add_formula_column, add_summary_formula | "Count how many orders are paid" |
| 16 | 3 | Text formulas (LEFT, MID, FIND, CONCAT) | add_formula_column | "Add First Name from Full Name" |
| 17 | 3 | Date formulas (YEAR, MONTH, DATEDIF) | add_formula_column | "Add Order Month from Order Date" |

Highlighting applies a static fill colour rather than an Excel conditional-formatting rule, so it can be previewed and undone like any other change.

# Project File Structure

```text
excel-ai/
├── PROJECT_CONTEXT.md          # shared brief Antigravity reads before every phase
├── README.md                   # setup + run instructions, results table
├── pyproject.toml              # dependencies (requirements) + ruff + pytest config
├── uv.lock                     # exact pinned versions (generated)
├── requirements.txt            # pip-style export of the same versions (generated)
├── .env.example
├── .gitignore
├── config/                     # per-laptop settings
│   ├── dell.env
│   └── yoga.env
├── backend/                    # ── BACKEND (Python, FastAPI) ──
│   ├── main.py                 # FastAPI app factory, lifespan, serves the frontend
│   ├── config.py               # Settings (pydantic-settings, prefix EXAI_)
│   ├── logging_setup.py
│   ├── api/                    # HTTP endpoints
│   │   ├── deps.py             # get_adapter(), get_graph()
│   │   ├── routes_health.py    # GET  /api/health
│   │   ├── routes_chat.py      # POST /api/chat, /api/confirm  (streaming)
│   │   └── routes_undo.py      # POST /api/undo, GET /api/undo/history
│   ├── llm/                    # talking to llama-server
│   │   ├── client.py           # ChatOpenAI factory, structured_call()
│   │   ├── prompts.py          # load_prompt()
│   │   └── prompts/            # classify_intent.md, extract_params.md, extract_params_formula.md
│   ├── agent/                  # LangGraph
│   │   ├── state.py
│   │   ├── nodes.py
│   │   └── graph.py
│   ├── excel/                  # Excel bridge
│   │   ├── adapter.py          # WorkbookAdapter protocol + errors
│   │   ├── com_thread.py       # the single COM worker thread
│   │   ├── xlwings_adapter.py  # real Excel
│   │   ├── fake_adapter.py     # in-memory Excel for tests
│   │   ├── serializer.py       # sheet -> prompt text, resolve_target()
│   │   ├── a1.py               # "B3" / "A1:J11" helpers
│   │   └── values.py           # display + JSON helpers for cell values
│   ├── ops/                    # the actual operations (deterministic)
│   │   ├── registry.py         # OpSpec, REGISTRY, execute()
│   │   ├── text_ops.py         # Tier 1
│   │   ├── structure_ops.py    # Tier 2
│   │   └── formula_ops.py      # Tier 3
│   ├── schemas/                # Pydantic contracts
│   │   ├── sheet.py            # SheetSnapshot, RegionState
│   │   ├── intent.py           # Target, IntentChoice, *Params models
│   │   ├── patch.py            # CellChange, FormatChange, Patch
│   │   └── api.py              # request / response models
│   └── storage/                # SQLite
│       ├── db.py
│       └── undo.py
├── frontend/                   # ── FRONTEND (HTML/CSS/JS, no build step) ──
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── assets/                 # icons
│   └── vendor/office/          # local office.js (Phase 10)
├── addin/                      # ── EXCEL TASK PANE (Phase 10) ──
│   └── manifest.xml
├── scripts/                    # launchers and dev tools
│   ├── start_llm_dell.bat      # llama-server, Dell profile
│   ├── start_llm_yoga.bat      # llama-server, Yoga profile
│   ├── start_backend.bat       # uvicorn (http)
│   ├── start_backend_https.bat # uvicorn (https, Phase 10)
│   ├── start_all.bat / stop_all.bat
│   ├── check_setup.py          # environment checks
│   ├── make_fixtures.py        # builds the test workbooks
│   ├── llm_smoke.py / llm_bench.py
│   ├── excel_probe.py / chat_cli.py
│   └── compare_runs.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/               # employees.xlsx, sales.xlsx
│   ├── unit/                   # pure functions, no Excel / no LLM
│   ├── integration/            # graph + API with fakes; live-Excel tests marked "excel"
│   └── eval/                   # eval_prompts.yaml + run_eval.py (real model + Excel)
├── docs/
│   └── ADDIN_SETUP.md
├── models/                     # *.gguf files        (not in git)
├── llama/                      # llama.cpp binaries  (not in git)
└── data/                       # SQLite, logs, benchmark + eval reports (not in git)
```

## Requirements (pyproject.toml)

```toml
[project]
name = "excel-ai"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi", "uvicorn[standard]", "sse-starlette",
  "pydantic", "pydantic-settings",
  "langgraph", "langchain-core", "langchain-openai", "langgraph-checkpoint-sqlite",
  "xlwings", "pywin32; sys_platform == 'win32'",
  "pandas", "openpyxl", "httpx", "pyyaml",
]

[dependency-groups]
dev = ["pytest", "pytest-asyncio", "ruff"]
```

`uv sync` installs these and records exact versions in `uv.lock`. `uv export --no-hashes -o requirements.txt` produces a pip-compatible `requirements.txt` for anyone not using uv. Non-Python requirements: the llama.cpp binaries, the GGUF model files, Microsoft Excel desktop, and (Phase 10 only) Node.js LTS for the localhost certificate tool.

## Which phase builds what

| Folder | Responsibility | Built in phase |
|---|---|---|
| config/, scripts/start_*.bat | Laptop profiles and launchers | 1 (start_all in 10) |
| backend/api | HTTP endpoints | 1, 3, 5 |
| backend/llm | Model client and prompt templates | 2, 5, 8 |
| backend/excel, backend/storage | Excel bridge and undo store | 3 |
| backend/ops | Operations | 4 (Tier 1), 7 (Tier 2), 8 (Tier 3) |
| backend/agent | LangGraph agent | 5 |
| frontend | Chat UI | 6 (task pane in 10) |
| tests/eval | Accuracy and speed evidence | 9 |
| addin, docs | Excel task pane | 10 |

# Core Contracts

Every phase builds against the same small set of data models, defined in full in `PROJECT_CONTEXT.md` section 7 (Appendix A). Because Antigravity reads that file before each phase, code written in different phases (and conversations) fits together.

| Contract | Purpose | Created in |
|---|---|---|
| SheetSnapshot | Everything read from the active sheet: values, formulas, headers, selection | Phase 3 |
| Target | Which cells an operation applies to: columns by header name, headers, a range, or the selection | Phase 3 |
| CellChange / FormatChange / Patch | The exact change set: before and after per cell, fill colours, summary, warnings | Phase 3 |
| RegionState | Saved cell state used for undo and for formula trial runs | Phase 3 |
| OpSpec + REGISTRY | One entry per operation: params model, handler, examples, optional validator | Phase 4 |
| *Params models | Parameters the model must fill in for each operation | Phases 4, 7, 8 |
| IntentChoice | Classifier output: op id (restricted to registered ops) and a one-line explanation | Phase 5 |
| SSE events | status, plan, preview, done, error | Phase 5 |

# Working with Antigravity

## Before Phase 1

1. Create the project folder **outside OneDrive**, for example `C:\dev\excel-ai`. OneDrive sync conflicts with `.venv`, SQLite files and Excel file locks.
2. Copy `PROJECT_CONTEXT.md` (provided with this plan and printed in Appendix A) into that folder.
3. Open the folder in Antigravity.

## Rules for every phase

- **One phase per new agent conversation.** A fresh conversation keeps the agent focused and stops it drifting into other phases.
- **Use Planning mode.** Antigravity first produces a task list and an implementation plan. Read them, comment on anything that contradicts `PROJECT_CONTEXT.md`, then let it build. Use Fast mode only for small follow-up fixes.
- **Paste the phase prompt exactly as written.** All the values it needs are inside the prompt or in `PROJECT_CONTEXT.md`.
- **Keep llama-server running from Phase 2 onwards**, and Excel open with `tests\fixtures\employees.xlsx` from Phase 3 onwards, so the agent can run its checks.
- **Watch the terminal commands it runs.** Allow `uv`, `pytest`, `ruff`, `git` and the project scripts. Deny installing packages not in the list, and any download from the internet, except `uv sync` and the Node certificate tool in Phase 10.
- **After each phase:** run the *Done when* checks yourself, then `git add -A` and `git commit -m "Phase N: <name>"`. If a check fails, ask for the fix in the same conversation before moving on.
- **If it calls a library function that doesn't exist** (LangGraph and xlwings change between versions), reply: *"Check the installed version with `uv pip show <package>` and read the installed source under `.venv\Lib\site-packages` before changing the code."*
- **Contracts change only on purpose.** Any change to a contract must also be made in `PROJECT_CONTEXT.md` in the same commit.
- **Two people, two laptops:** use one git branch per phase and merge after its tests pass. Phases 6 and 7 can run in parallel once Phase 5 is merged.

## How each prompt is built

Each prompt does the following:

- names its phase and tells Antigravity to read `PROJECT_CONTEXT.md` first
- states the goal in one sentence
- lists the exact files and behaviours to build
- lists the tests to write
- gives the commands that must pass
- ends with "give me a walkthrough, then stop"

# Phase Roadmap

| Phase | Name | Tier | What it gives us | Est. | Needs |
|---|---|---|---|---|---|
| 0 | Machine setup | – | Python 3.12, uv, llama.cpp and the models installed and verified on both laptops | 0.5 d | – |
| 1 | Scaffold, config, health check | – | Runnable FastAPI skeleton, per-laptop config, `/api/health` that pings the model, launchers, git | 0.5 d | 0 |
| 2 | LLM client and structured output | – | A reliable call that returns validated JSON from the local model, plus measured speeds | 1 d | 1 |
| 3 | Excel bridge | – | Read the open sheet, turn it into prompt text, write changes, undo them; test workbooks | 1.5 d | 2 |
| 4 | Tier 1 text operations | 1 | Six tested text operations (12 variants) and the operation registry | 1 d | 3 |
| 5 | LangGraph agent and API | 1 | First end-to-end result: instruction → preview → approve → Excel changes → undo | 2 d | 4 |
| 6 | Chat UI | 1 | A usable chat panel with live progress, preview table, Apply, Cancel and Undo | 1.5 d | 5 |
| 7 | Tier 2 structural operations | 2 | Sort, filter, dedupe, column changes, fill blanks, highlight | 2 d | 5 |
| 8 | Tier 3 formula generation | 3 | Formulas written by the model, checked, trial-run in Excel, retried on errors | 2.5 d | 7 |
| 9 | Evaluation and benchmark | 1–3 | Accuracy and speed numbers per tier, model and laptop: the proof-of-concept evidence | 1.5 d | 8 |
| 10 | Excel task pane and packaging (stretch) | – | Chat inside Excel, one-click start, verified with Wi-Fi off | 1.5 d | 9 |

Total: about 15–16 working days for one developer. With two people, run Phases 6 and 7 in parallel, and write the evaluation cases for Phase 9 while Phase 8 is being built.

# Phase 0 · Machine Setup

**Done by:** you, manually, on both laptops · **Estimate:** 0.5 day · **Needs:** nothing

## What this phase gives us

Both laptops get the right Python, the tools, and a working local model server **before any code is written**. GPU, driver and model-file problems are the most common blockers, and finding them here saves days later. At the end you know the real model speed on each laptop.

## Steps

1. **Project folder:** create `C:\dev\excel-ai` (outside OneDrive) and copy `PROJECT_CONTEXT.md` into it.
2. **Tools:** install Git for Windows and `uv`, then Python 3.12:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv python install 3.12
```

3. **GPU drivers:** update the NVIDIA driver on the Dell and the Intel Arc graphics driver on the Yoga.
4. **llama.cpp:** download the latest Windows release from `github.com/ggml-org/llama.cpp/releases` and unzip it into `C:\dev\excel-ai\llama\`.
   - Dell: `llama-<build>-bin-win-cuda-12.x-x64.zip` **and** `cudart-llama-bin-win-cuda-12.x-x64.zip`, both into the same folder.
   - Yoga: `llama-<build>-bin-win-vulkan-x64.zip`. Later you can also try the `sycl` build and keep whichever is faster.
5. **Models:** download into `C:\dev\excel-ai\models\`. Check the exact file names on the model pages; any Q4_K_M GGUF of the same model works.

```powershell
uv tool install "huggingface_hub[cli]"
hf download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf --local-dir models
hf download ggml-org/gpt-oss-20b-GGUF gpt-oss-20b-mxfp4.gguf --local-dir models   # Yoga only
```

6. **Start the model server** from `C:\dev\excel-ai`, using the Dell or Yoga command from the *Hardware & Model Configuration* section. In a second terminal, test it:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/v1/chat/completions -Method Post -ContentType 'application/json' -Body '{"messages":[{"role":"user","content":"Reply with only the Excel formula that multiplies D2 by E2."}]}' | ConvertTo-Json -Depth 6
```

7. **Excel:** open Excel once, go to *File › Options › Formulas*, and make sure *Workbook Calculation* is set to *Automatic*.
8. **Antigravity:** install it and sign in. Antigravity needs internet while you code; the app you build does not. Node.js LTS is only needed in Phase 10.

## Done when

- On the Dell, the llama-server log shows every layer on the GPU (e.g. `offloaded 29/29 layers to GPU`).
- The test request returns `=D2*E2` or equivalent.
- The `eval time … tokens per second` line in the server log is roughly in the expected range: Dell 25–35 tok/s with the 7B model, Yoga 12–20 tok/s with gpt-oss-20b.
- `git --version` and `uv --version` work, and `uv python list` shows 3.12.

# Phase 1 · Scaffold, Config & Health Check

**Tier:** foundation · **Estimate:** 0.5 day · **Needs:** Phase 0

## What this phase gives us

A clean, runnable project skeleton. The folder layout matches the plan, dependencies are pinned, and each laptop has its own config profile. A FastAPI server reports whether the local model is reachable. Every later phase plugs into this skeleton, and the health endpoint becomes our first "is everything running?" check.

## Files created

- `pyproject.toml`, `uv.lock`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`
- `config/dell.env`, `config/yoga.env`
- `backend/main.py`, `backend/config.py`, `backend/logging_setup.py`, `backend/api/routes_health.py`, plus empty packages for all other backend folders
- `frontend/index.html` (placeholder)
- `scripts/start_llm_dell.bat`, `scripts/start_llm_yoga.bat`, `scripts/start_backend.bat`, `scripts/check_setup.py`
- `tests/conftest.py`, `tests/unit/test_health.py`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md in the repository root completely before doing anything. It is the source of
truth for architecture, folder layout, contracts and conventions. This is PHASE 1: project scaffold,
configuration and health check. Do not implement anything from later phases.

GOAL
A runnable FastAPI skeleton with per-laptop configuration and a health endpoint that reports whether
the local llama-server is reachable.

TASKS
1. Initialise the project with uv for Python 3.12 (uv init --python 3.12; delete the sample main.py /
   hello.py that uv creates). Create the full folder tree from PROJECT_CONTEXT.md section 5 with an
   __init__.py in every backend package. Later-phase modules are NOT created yet - only folders.
2. pyproject.toml: add exactly the runtime and dev dependencies from PROJECT_CONTEXT.md section 4
   (pywin32 with the marker sys_platform == 'win32'). Configure ruff (line-length 100, target py312)
   and pytest: testpaths = ["tests"], pythonpath = ["."], asyncio_mode = "auto",
   markers = ["excel: needs a running Microsoft Excel (Windows)"]. Run uv sync, then
   uv export --no-hashes -o requirements.txt.
3. backend/config.py: pydantic-settings class Settings with env_prefix "EXAI_" and env_file taken from
   the environment variable EXAI_ENV_FILE (default ".env"). Fields and defaults:
   llm_base_url="http://127.0.0.1:8080/v1", llm_model="local-model", llm_temperature=0.0,
   llm_max_tokens=512, llm_timeout_s=120, llm_extra_body: dict = {} (JSON in env),
   machine_name="dev", backend_host="127.0.0.1", backend_port=8000, data_dir=Path("data"),
   max_retries=2, max_prompt_rows=30. Provide get_settings() cached with functools.lru_cache.
4. .env.example plus config/dell.env and config/yoga.env with exactly the values in
   PROJECT_CONTEXT.md section 6.
5. backend/logging_setup.py: configure_logging(settings) -> console + rotating file
   data/logs/app.log (1 MB x 3 files), format "time level logger: message".
6. backend/main.py: create_app() factory. A lifespan handler creates data_dir and data/logs and calls
   configure_logging. All API routes use the prefix /api. Mount frontend/ with
   StaticFiles(html=True) at "/" AFTER the API routers so it does not shadow them.
7. backend/api/routes_health.py: GET /api/health returns
   {"backend": "ok", "machine": <machine_name>,
    "llm": {"reachable": bool, "model": str | None, "error": str | None}}.
   Check the LLM with httpx GET {llm_base_url}/models (timeout 3 s), take the first model id.
   Never raise: report problems in "error". (The "excel" field is added in Phase 3.)
8. frontend/index.html: a minimal placeholder page titled "Excel AI" that fetches /api/health and
   shows the JSON. No external resources.
9. scripts:
   - start_llm_dell.bat / start_llm_yoga.bat: cd to the project root (cd /d %~dp0..) and run the
     exact llama-server commands from PROJECT_CONTEXT.md section 6. start_llm_yoga.bat accepts an
     optional argument "qwen" to load the Qwen 7B model instead (parity test).
   - start_backend.bat: takes "dell" or "yoga", sets EXAI_ENV_FILE=config\<profile>.env and runs
     uv run uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
   - check_setup.py: prints Python version, whether llama.cpp's llama-server.exe exists under llama\,
     which .gguf files exist under models\, and whether http://127.0.0.1:8080/health answers.
     It must never crash; print OK / MISSING per line.
10. .gitignore: .venv/, __pycache__/, .pytest_cache/, .ruff_cache/, data/, models/, llama/, *.gguf,
    addin/certs/, .env. README.md: prerequisites, setup (uv sync), how to start llama-server and
    the backend on each laptop, how to run tests.
11. tests/unit/test_health.py: FastAPI TestClient; monkeypatch the LLM check so the test passes
    without llama-server; test both reachable and unreachable responses and the JSON shape.
12. git init and create the first commit "Phase 1: scaffold".

RULES
Follow PROJECT_CONTEXT.md (offline only, Python 3.12, full type hints, no extra dependencies).

VERIFY (all must pass)
uv run ruff check .
uv run pytest -q -m "not excel"
scripts\start_backend.bat dell   then open http://127.0.0.1:8000/  -> llm.reachable is true while
llama-server is running, false (with an error message) when it is stopped.

Finish with a walkthrough: files created, commands run and their output, anything I must do by hand.
Then stop. Do not start Phase 2.
```

## Done when

- `uv run pytest -q -m "not excel"` and `uv run ruff check .` pass.
- `http://127.0.0.1:8000/` shows `"reachable": true` with llama-server running, and an error message when it is stopped.
- `uv run python scripts/check_setup.py` prints OK for the llama binary, the model file and the server.

# Phase 2 · LLM Client & Structured Output

**Tier:** foundation · **Estimate:** 1 day · **Needs:** Phase 1, llama-server running

## What this phase gives us

One reusable function the whole app uses to ask the local model a question and get back a **validated Pydantic object** instead of free text. llama-server's JSON-schema mode forces the output to the right shape. If an answer still fails validation, the call retries once with the error message attached. This phase also gives us **measured** speeds (prompt reading and generation, in tokens per second) on each laptop, which replace the estimates.

## Files created / changed

- `backend/llm/client.py`, `backend/llm/prompts.py`, `backend/llm/prompts/smoke_test.md`
- `scripts/llm_smoke.py`, `scripts/llm_bench.py`
- `backend/api/routes_health.py` (model name)
- `tests/unit/test_prompts.py`, `tests/unit/test_llm_client.py`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first (sections 2, 4 and 6). This is PHASE 2: LLM client and structured output.
Phase 1 is complete. Do not implement anything from later phases.

GOAL
A single reusable way to call the local model and receive validated Pydantic objects, plus scripts that
prove it works and measure speed on this laptop.

TASKS
1. backend/llm/client.py
   - get_chat_model() -> ChatOpenAI, cached. Built from Settings: base_url=llm_base_url,
     api_key="sk-local" (llama-server ignores it), model=llm_model, temperature=llm_temperature,
     max_tokens=llm_max_tokens, timeout=llm_timeout_s, max_retries=0, extra_body=llm_extra_body.
   - A generic result model StructuredResult[T] with: value: T | None, raw_text: str,
     error: str | None, latency_ms: float, usage: dict.
   - async def structured_call(schema: type[T], system_prompt: str, user_prompt: str)
     -> StructuredResult[T]. Use get_chat_model().with_structured_output(schema,
     method="json_schema", include_raw=True); the result is a dict with "raw", "parsed",
     "parsing_error". If parsed is None or parsing failed, retry ONCE with the validation error
     appended to the user prompt ("Your previous answer was invalid: ... Return only valid JSON.").
     Never raise for model or network errors - return them in .error.
   - Fallback: if llama-server rejects method="json_schema", switch to method="json_mode" with the
     JSON schema embedded in the system prompt and validate with Pydantic. Log which mode is used.
   - Log every call at INFO (prompt characters, latency, ok/error) and the full prompts at DEBUG.
2. backend/llm/prompts.py: load_prompt(name: str, **variables) -> str reads
   backend/llm/prompts/{name}.md and fills {placeholders} with str.format_map. Missing variables raise
   a clear KeyError naming the template and the variable. Literal braces in templates are written {{ }}.
3. backend/llm/prompts/smoke_test.md: a short system prompt telling the model it writes Excel formulas
   and must answer in the requested JSON format.
4. scripts/llm_smoke.py: defines SmokeAnswer(formula: str, explanation: str) and runs 3 structured
   calls (multiply D2 by E2; sum F2:F11; IF G2 is "Yes" then "Paid" else "Due"). Print each parsed
   object and latency. Exit code 1 if any call fails.
5. scripts/llm_bench.py: use httpx directly (not LangChain) against {llm_base_url}/chat/completions.
   Build a ~1,500-token prompt (a 10x10 pipe table + an instruction asking for a short JSON answer)
   and send it 5 times. Read llama-server's "timings" object from each response (prompt_n,
   prompt_per_second, predicted_n, predicted_per_second); if it is missing, fall back to wall-clock
   time and the "usage" token counts. Print min / average and save all results to
   data/bench/<machine_name>_<YYYYmmdd_HHMMSS>.json.
6. backend/api/routes_health.py: llm.model shows the id returned by /models.
7. Tests (none may need llama-server):
   - tests/unit/test_prompts.py: load + fill, missing-variable error, escaped braces.
   - tests/unit/test_llm_client.py: monkeypatch get_chat_model with a fake whose structured runnable
     returns scripted dicts; test (a) success first time, (b) invalid first answer then valid ->
     value set and 2 calls made, (c) invalid twice -> error set, (d) exception -> error set.

RULES
Follow PROJECT_CONTEXT.md. No new dependencies. No network calls except to llm_base_url.

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"
With llama-server running:
uv run python scripts/llm_smoke.py     -> 3 successful structured answers
uv run python scripts/llm_bench.py     -> speeds printed and saved

Finish with a walkthrough that includes the benchmark numbers. Then stop. Do not start Phase 3.
```

## Done when

- The smoke script prints three valid formulas as parsed objects.
- The benchmark JSON exists in `data/bench/` for each laptop. Record the prompt and generation speeds in `README.md`.
- Tests pass without llama-server running.

# Phase 3 · Excel Bridge

**Tier:** foundation · **Estimate:** 1.5 days · **Needs:** Phase 2, Excel installed

## What this phase gives us

The connection between Python and the open Excel workbook, built safely:

- read the active sheet (values, formulas, selection)
- turn it into the compact text table the model sees
- write a set of changes
- save the previous state and restore it (undo)

All Excel calls run on one dedicated thread, which avoids the most common xlwings/COM crash. A fake in-memory workbook lets every later phase test its logic without Excel, and the two fixture workbooks become our standard test data.

## Files created / changed

- `backend/schemas/sheet.py`, `backend/schemas/patch.py`, `backend/schemas/intent.py` (Target only)
- `backend/excel/a1.py`, `values.py`, `adapter.py`, `com_thread.py`, `xlwings_adapter.py`, `fake_adapter.py`, `serializer.py`
- `backend/storage/db.py`, `backend/storage/undo.py`, `backend/api/deps.py`, `backend/api/routes_health.py` (excel status)
- `scripts/make_fixtures.py`, `scripts/excel_probe.py`, `tests/fixtures/*.xlsx`
- Tests for A1 helpers, serializer, target resolution, fake adapter, undo store, and a live Excel round-trip

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially sections 2, 7, 8 and 12. This is PHASE 3: the Excel bridge.
Phases 1-2 are complete. Do not implement anything from later phases.

GOAL
Read the open Excel sheet into a SheetSnapshot, turn it into prompt text, apply a Patch, and undo it.
All COM access happens on one dedicated thread.

TASKS
1. Schemas exactly as in PROJECT_CONTEXT.md section 7:
   backend/schemas/sheet.py (SheetSnapshot, RegionState), backend/schemas/patch.py (CellChange,
   FormatChange, Patch), backend/schemas/intent.py (only Target for now).
2. backend/excel/a1.py (pure functions, ValueError on bad input, "$" stripped):
   col_to_index("A")=1, index_to_col(28)="AB", parse_cell("$B$3")->(3, 2),
   parse_range("A1:J11")->(1, 1, 11, 10) (a single cell is a 1x1 range), make_range(r1, c1, r2, c2),
   iter_range(range)->list of addresses row by row, bounding_range(addresses)->"A1:C4".
3. backend/excel/values.py: display_value(v) (whole floats without .0, dates YYYY-MM-DD, None -> "");
   to_jsonable / from_jsonable that encode datetime as {"$date": iso} and back (lists of lists too).
4. backend/excel/adapter.py: WorkbookAdapter Protocol with SYNC methods
   read_snapshot() -> SheetSnapshot; read_region(region: str) -> RegionState;
   apply_patch(patch: Patch) -> None; restore_region(state: RegionState) -> None;
   calculate() -> None; read_values(region: str) -> list[list[CellValue]] (Excel errors returned as
   text such as "#DIV/0!"); describe() -> dict (connected, workbook, sheet, error).
   Error classes ExcelNotConnectedError and TargetError with friendly messages.
5. backend/excel/com_thread.py: class ComThread with a ThreadPoolExecutor(max_workers=1) whose
   initializer calls pythoncom.CoInitialize(); async def run(fn, *args, **kwargs) uses
   loop.run_in_executor. Module-level singleton com_thread. Add a shutdown() used by the FastAPI
   lifespan.
6. backend/excel/xlwings_adapter.py: XlwingsAdapter implementing the protocol.
   - Default target: the active workbook and active sheet of the running Excel (xw.apps.active).
     Raise ExcelNotConnectedError("Open a workbook in Excel first.") if Excel or a workbook is not
     open. Optional constructor argument book_path: open that file in a hidden instance
     (xw.App(visible=False, add_book=False)) - used later by the evaluation runner; add close().
   - Never cache COM objects between calls: get the book/sheet inside every method.
   - read_snapshot: used_range values via .options(ndim=2).value; formulas via .formula (keep only
     strings starting with "=", else None); header row = first row of the used range; selection via
     the app's selection address (None if it fails or lies on another sheet); dates stay datetime.
   - apply_patch: screen_updating False while writing; for each CellChange write after_formula if
     set, else after (None clears the cell); FormatChange: "#RRGGBB" -> RGB tuple, None -> color None;
     restore screen_updating in finally.
   - read_values uses .options(ndim=2, err_to_str=True).value. calculate() calls app.calculate().
7. backend/excel/fake_adapter.py: FakeAdapter implementing the same protocol on an in-memory grid,
   constructed from (sheet_name, rows) or from an .xlsx path via openpyxl. It does not calculate:
   read_values returns the formula text for formula cells. It records applied patches for tests.
8. backend/excel/serializer.py:
   - snapshot_to_prompt(snapshot, max_rows) -> str in EXACTLY the format and rules of section 8.
   - resolve_target(snapshot, target) -> list[str] addresses:
     columns -> data-row cells of those columns (header names matched case-insensitively after
     trimming, or column letters); headers -> header-row cells (all columns, or only the listed ones);
     range -> cells of that A1 range; selection -> cells of snapshot.selection. Raise TargetError
     listing the valid header names when something does not resolve.
9. backend/storage/db.py + backend/storage/undo.py: SQLite file data/app.sqlite, table
   undo_snapshots(id INTEGER PK, created_at TEXT, thread_id TEXT, sheet TEXT, region TEXT,
   state_json TEXT, summary TEXT). Functions save_snapshot(thread_id, state, summary) -> id,
   pop_latest() -> (RegionState, summary) | None, list_recent(n). Keep only the newest 50.
10. backend/api/deps.py: get_adapter() returns the adapter stored on app.state (XlwingsAdapter by
    default) so tests can swap in FakeAdapter. /api/health gains "excel": adapter.describe() executed
    through com_thread - never raise.
11. scripts/make_fixtures.py: write tests/fixtures/employees.xlsx and tests/fixtures/sales.xlsx with
    EXACTLY the data in section 12 (date strings written as real dates, bold header row, sensible
    column widths). Run it and commit the two files.
12. scripts/excel_probe.py (manual check, Excel open on employees.xlsx): print snapshot_to_prompt();
    save an undo snapshot of B2:B3; apply a patch that upper-cases B2:B3; wait for Enter; restore.
13. Tests:
    - tests/unit/test_a1.py, test_values.py, test_serializer.py (golden string for a small fake sheet,
      quoting rules, (empty), truncation, more rows than max_rows), test_resolve_target.py (header
      names, letters, headers kind, selection, unknown column -> TargetError listing headers),
      test_fake_adapter.py (apply + restore round-trip), test_undo_store.py (temp SQLite file).
    - tests/integration/test_excel_live.py marked @pytest.mark.excel: open
      tests/fixtures/employees.xlsx in a hidden Excel, read snapshot, apply a patch, read back,
      restore, verify the original values.

RULES
Follow PROJECT_CONTEXT.md. xlwings may be imported only in xlwings_adapter.py and scripts/.
Every xlwings call from the backend must go through com_thread.run(...).

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"
uv run pytest -q -m excel          (Excel installed; closes its hidden instance afterwards)
uv run python scripts/excel_probe.py

Finish with a walkthrough including the printed prompt text for employees.xlsx. Then stop.
Do not start Phase 4.
```

## Done when

- The probe prints the Employees table in the section 8 format and the upper-case change appears and disappears in Excel.
- `/api/health` shows the open workbook and sheet name.
- Both the fake and the live (`-m excel`) tests pass.

# Phase 4 · Tier 1 Text Operations

**Tier:** 1 · **Estimate:** 1 day · **Needs:** Phase 3

## What this phase gives us

All Tier 1 features as **plain, fully tested Python functions**: change case, camelCase / snake_case / PascalCase / kebab-case, trim, find and replace, prefix / suffix, remove characters. It also adds the **operation registry**: one entry per operation holding its parameter schema, description, example instructions and handler. The agent in Phase 5 reads this registry to know what it can do. Because these functions don't involve the LLM, correctness here is guaranteed by tests, and the model only has to choose the right operation and column.

## Files created / changed

- `backend/schemas/intent.py` (op ids + Tier 1 params models)
- `backend/ops/text_ops.py`, `backend/ops/registry.py`
- `tests/unit/test_text_ops.py`, `tests/unit/test_registry_tier1.py`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially sections 7 and 9. This is PHASE 4: Tier 1 text operations.
Phases 1-3 are complete. Do not implement anything from later phases. No LLM is used in this phase.

GOAL
Deterministic, fully tested implementations of every Tier 1 operation, plus the operation registry the
agent will use.

TASKS
1. backend/schemas/intent.py - add Pydantic params models for Tier 1. EVERY field has
   Field(description=...) because these descriptions are shown to the model:
   - ChangeCaseParams(target: Target, mode: Literal["upper","lower","title","sentence"])
   - ConvertCaseStyleParams(target: Target, style: Literal["camel","snake","pascal","kebab"])
   - TrimWhitespaceParams(target: Target)
   - FindReplaceParams(target: Target, find: str, replace: str, match_case: bool = False,
     whole_cell: bool = False)
   - AddPrefixSuffixParams(target: Target, prefix: str = "", suffix: str = "")
   - RemoveCharactersParams(target: Target,
     remove: Literal["special","digits","letters","non_digits","custom"], custom_chars: str = "")
2. backend/ops/text_ops.py - pure functions on single values (no Excel, no Pydantic):
   to_upper, to_lower, to_title, to_sentence, to_camel, to_snake, to_pascal, to_kebab,
   trim_whitespace (strip + collapse runs of spaces / tabs / non-breaking spaces to one space),
   find_replace, add_prefix_suffix, remove_characters ("special" = anything that is not a letter,
   digit or space; "non_digits" keeps only 0-9).
   - Word splitting for the case styles handles spaces, underscores, hyphens, dots, existing
     camelCase / PascalCase boundaries, acronyms (HTTPServer -> HTTP, Server) and digits.
   - Non-string values (numbers, dates, None) are returned unchanged, EXCEPT find_replace and
     add_prefix_suffix, which also apply to numbers (whole numbers formatted without .0) and
     return text.
3. backend/ops/registry.py
   - OpSpec dataclass exactly as in PROJECT_CONTEXT.md section 7.
   - REGISTRY: dict[str, OpSpec]; register(spec) helper; implemented_ops() -> list[OpSpec].
   - build_cell_patch(snapshot, addresses, fn, op, summary_template) -> Patch: applies fn to each
     addressed cell value and creates a CellChange ONLY when the value really changes; the summary
     says how many cells changed (e.g. "Converted 10 headers to camelCase").
   - Register the 6 Tier 1 ops with the titles and example instructions from section 9 and a one-line
     description each. Handlers resolve the target with serializer.resolve_target.
   - execute(op_name, snapshot, params) -> Patch; raises OpError for unknown ops or params of the
     wrong type.
4. Tests
   - tests/unit/test_text_ops.py, parametrised, at least 8 cases per case style, including:
     camel: "Full Name"->"fullName", "emp_id"->"empId", "  join   date "->"joinDate",
     "HTTPServer"->"httpServer", "already camelCase"->"alreadyCamelCase", "Order-ID"->"orderId",
     "Address 2"->"address2", ""->"".
     snake: "Full Name"->"full_name", "fullName"->"full_name". Equivalent sets for pascal / kebab.
     Also: title / sentence, trim (tabs, NBSP), find_replace (case-insensitive default, match_case,
     whole_cell, numbers), prefix / suffix on numbers ("101" -> "EMP-101"), every remove mode.
   - tests/unit/test_registry_tier1.py: build a FakeAdapter from tests/fixtures/employees.xlsx, run
     every Tier 1 op through registry.execute and assert the exact CellChanges (e.g. headers to
     camelCase -> A1 "empId" ... J1 "rating"; trim Full Name changes exactly B2, B4 and B11).

RULES
Follow PROJECT_CONTEXT.md. No new dependencies.

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"

Finish with a walkthrough listing the operations and their test counts. Then stop. Do not start Phase 5.
```

## Done when

- All Tier 1 tests pass. Spot-check a few camelCase results by hand.
- `registry.implemented_ops()` lists exactly the six Tier 1 operations.

# Phase 5 · LangGraph Agent & API

**Tier:** 1 (end to end) · **Estimate:** 2 days · **Needs:** Phase 4, llama-server and Excel running

## What this phase gives us

**The first complete, working proof of concept.** You type "convert the column headers to camelCase", the local model works out what you mean, the backend shows exactly which cells will change, you approve, Excel updates, and Undo puts it back. This phase builds the LangGraph agent (read → classify → extract → execute → validate → preview → apply, with retries) and the streaming API, plus a small terminal client so it can be demonstrated before the UI exists.

## Files created / changed

- `backend/agent/state.py`, `backend/agent/nodes.py`, `backend/agent/graph.py`
- `backend/llm/prompts/classify_intent.md`, `backend/llm/prompts/extract_params.md`
- `backend/api/routes_chat.py`, `backend/api/routes_undo.py`, `backend/schemas/api.py`, `backend/api/deps.py`, `backend/main.py`
- `scripts/chat_cli.py`
- `tests/integration/test_graph_fake.py`, `tests/integration/test_api_chat.py`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially sections 3, 7, 8, 9 and 11. This is PHASE 5: the LangGraph
agent and the API. Phases 1-4 are complete. Do not implement anything from later phases.

GOAL
End-to-end pipeline: instruction -> plan -> preview -> user approval -> applied to Excel -> undo,
streamed to the client as Server-Sent Events.

TASKS
1. backend/agent/state.py - AgentState TypedDict: thread_id, user_message, snapshot (dict),
   sheet_text, op (str | None), op_explanation, params (dict | None), patch (dict | None),
   validation_errors (list[str]), retries (int), result_summary (str | None), applied (bool),
   error (str | None). Store Pydantic objects as model_dump() dicts.
2. Prompt templates (backend/llm/prompts/):
   - classify_intent.md: role ("You decide which spreadsheet operation the user wants"), the list of
     implemented operations GENERATED from the registry (id, title, description, examples), the
     sheet_text, the user instruction, and rules: choose exactly one id; choose "unsupported" if
     nothing fits; never invent ids; explanation = one short sentence.
   - extract_params.md: the chosen operation (id, title, description), the sheet_text, the user
     instruction, any previous validation errors, and rules: refer to columns by header name exactly
     as listed in "Columns:"; use target.kind="headers" when the user talks about headers / column
     names; use kind="selection" for "selected" / "highlighted" cells; only fill fields of the schema.
3. backend/agent/nodes.py - async node functions, each returning a partial state update:
   - read_sheet: snapshot via com_thread.run(adapter.read_snapshot); sheet_text via the serializer.
     ExcelNotConnectedError -> error.
   - classify_intent: structured_call with IntentChoice built dynamically
     (pydantic.create_model with op: Literal[tuple(implemented op ids + ["unsupported"])]).
   - extract_params: structured_call with REGISTRY[op].params_model using the template named by
     OpSpec.prompt_name; include validation_errors on retries; increment retries on each retry.
   - execute_op: registry.execute(...); TargetError / OpError / ValidationError -> validation_errors.
   - validate: no changes -> route to finish_nothing; every address must lie inside the used range
     extended by 2 columns to the right and 3 rows down; then run OpSpec.validator if present
     (await validator(snapshot, params, patch, adapter)).
   - preview: build {thread_id, summary, changes: [{address, before, after, formula}],
     formats, warnings} using display_value (max 200 changes) and call interrupt(payload).
     IMPORTANT: this node re-runs from the start when resumed, so it must have no side effects
     before interrupt(). The resume value is {"approved": bool}.
   - apply_patch: re-read the region; if any "before" value no longer matches the current sheet,
     stop with "The sheet changed since the preview - please ask again." Otherwise save an undo
     snapshot (read_region of the patch's bounding range), apply the patch, set applied=True and
     result_summary.
   - finish_unsupported (lists what the assistant can do, from the registry titles), finish_error,
     finish_nothing ("Nothing to change"), finish_cancelled.
4. backend/agent/graph.py - build_graph(checkpointer) wiring EXACTLY the flow in section 3 with
   conditional edges (retry while retries < settings.max_retries). In the FastAPI lifespan, open
   AsyncSqliteSaver.from_conn_string("data/checkpoints.sqlite") (async context manager), compile
   the graph and store it on app.state; get_graph() in deps.py returns it.
5. backend/schemas/api.py: ChatRequest(message, thread_id: str | None), ConfirmRequest(thread_id,
   approved), UndoResponse(restored, summary).
6. backend/api/routes_chat.py (sse_starlette EventSourceResponse; all data is JSON):
   - POST /api/chat: thread_id = request value or uuid4. Stream graph.astream(initial_state,
     config={"configurable": {"thread_id": tid}}, stream_mode="updates"). Emit "status"
     {node, label} after each node (human labels: "Reading sheet", "Understanding request",
     "Working out details", "Preparing changes", "Checking changes"); "plan" after extract_params;
     "preview" when the stream yields "__interrupt__"; "done" or "error" at the end.
   - POST /api/confirm: resume with Command(resume={"approved": approved}) on the same thread_id,
     emitting status / done / error.
   Also log per-node latency at INFO.
7. backend/api/routes_undo.py: POST /api/undo pops the latest snapshot and restores it through the
   adapter on com_thread -> {restored, summary}; GET /api/undo/history -> last 10 summaries.
8. scripts/chat_cli.py: terminal client using httpx streaming. Usage:
   uv run python scripts/chat_cli.py "convert the column headers to camelCase"
   Prints events, shows the preview table, asks "Apply? [y/n]", calls /api/confirm. --undo calls
   /api/undo.
9. Tests (no llama-server, no Excel):
   - tests/integration/test_graph_fake.py: compile the graph with InMemorySaver, FakeAdapter
     (employees.xlsx) and a fake structured_call returning scripted IntentChoice / params. Cases:
     headers -> camelCase approved (cells changed); rejected (unchanged); unsupported (message);
     unknown column name then a correct one (1 retry, success); wrong twice (finish_error);
     nothing to change (finish_nothing); sheet modified between preview and apply (refused).
   - tests/integration/test_api_chat.py: TestClient with the same fakes; parse the SSE stream of
     /api/chat, then /api/confirm; then /api/undo restores the original values.

RULES
Follow PROJECT_CONTEXT.md. No new dependencies. Only the "excel" folder touches xlwings.

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"
Manual: llama-server + scripts\start_backend.bat dell + Excel open on tests\fixtures\employees.xlsx:
uv run python scripts/chat_cli.py "convert the column headers to camelCase"   -> approve -> Excel changes
uv run python scripts/chat_cli.py --undo                                       -> headers restored
Also try: "make the Department column uppercase", "remove extra spaces in Full Name",
"keep only digits in Phone", "draw a chart" (must be unsupported).

Finish with a walkthrough including per-node latencies from the log. Then stop. Do not start Phase 6.
```

## Done when

- All six Tier 1 operations work from `chat_cli.py` against real Excel, and Undo restores the sheet.
- "Draw a chart" is politely rejected as unsupported.
- The log shows instruction → preview in about 5 s or less on the Dell.

# Phase 6 · Chat UI

**Tier:** 1 · **Estimate:** 1.5 days · **Needs:** Phase 5

## What this phase gives us

A real user interface for demos: a narrow chat panel that sits beside Excel. It shows live progress ("Reading sheet…", "Understanding request…"), the plan, a before → after preview table with Apply and Cancel, and Undo. It's built with plain HTML/CSS/JS and no external resources, so it works offline. It's designed to fit a narrow task pane, so Phase 10 can load the same page inside Excel without changes.

## Files created / changed

- `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`, `frontend/assets/`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially section 11 (API and SSE events). This is PHASE 6: the chat UI.
Phases 1-5 are complete. Do not implement anything from later phases.

GOAL
A clean single-page chat panel that works in a normal browser window placed beside Excel and, later,
inside an Excel task pane. It must work at 320-450 px wide without horizontal scrolling.

TASKS (plain HTML / CSS / JavaScript, no frameworks, no CDN, no build step, all assets local)
1. frontend/index.html, frontend/styles.css, frontend/app.js (replace the Phase 1 placeholder).
2. Header: app name; status dots for "Model" and "Excel" from GET /api/health polled every 10 s
   (tooltip / small text: model id, workbook and sheet name); an Undo button.
3. Chat log: user bubbles, assistant messages, and one live "working" line per request that updates
   on every "status" event.
4. Plan card from the "plan" event: operation title + explanation; a collapsible "details" section
   with the params JSON.
5. Preview card from the "preview" event: summary, warnings, and a compact table
   Cell | Before | After (After cell highlighted; show the formula in a tooltip / second line when
   present); Apply and Cancel buttons that POST /api/confirm and stream the result into the same card.
   Disable both buttons after a click.
6. "done" -> success message with an "Undo" link; "error" -> red system message.
7. Input: textarea; Enter sends, Shift+Enter adds a newline; disabled while a request is running;
   example chips under it: "Convert headers to camelCase", "Trim spaces in Full Name",
   "Make Department uppercase", "Keep only digits in Phone".
8. SSE over POST: EventSource cannot POST, so implement postSSE(url, body, onEvent) with fetch +
   ReadableStream + TextDecoder that parses "event:" and "data:" lines, handles chunks split
   mid-line and multi-line data, and supports aborting. Network failures must never leave the UI
   stuck in "working".
9. Keep the last 30 chat items in sessionStorage so a page reload keeps the conversation.
10. Style: neutral Office-like look, system font stack ("Segoe UI", system-ui, sans-serif), light
    theme, good contrast, visible focus outlines, aria-live region for status updates, buttons usable
    by keyboard.
Backend changes only if a small addition to an SSE payload is needed - then also update section 11
of PROJECT_CONTEXT.md.

VERIFY
uv run ruff check .   and   uv run pytest -q -m "not excel"   (still green)
Manual: open http://127.0.0.1:8000 in a browser about 400 px wide beside Excel (employees.xlsx).
Run 3 Tier 1 instructions end to end including one Cancel and one Undo; reload the page mid-way;
stop llama-server and check the Model dot turns red and errors are readable.

Finish with a walkthrough with screenshots. Then stop. Do not start Phase 7.
```

## Done when

- A non-developer can carry out a Tier 1 change, cancel one, and undo one, using only the panel.
- No horizontal scrolling at 350 px width, and no network requests other than to `127.0.0.1:8000`. Check the browser DevTools Network tab.

# Phase 7 · Tier 2 Structural Operations

**Tier:** 2 · **Estimate:** 2 days · **Needs:** Phase 5 (Phase 6 recommended)

## What this phase gives us

The assistant can now **reorganise the table**: sort rows, filter or delete rows by a condition, remove duplicates, insert / delete / rename / move columns, fill blanks, and highlight cells or rows. These go through the same plan → preview → apply → undo pipeline. The new operations register themselves in the registry, so the agent picks them up without any graph changes. Conditions use a small, strict schema (column, operator, value), which small models fill in reliably.

## Files created / changed

- `backend/schemas/intent.py` (Condition + Tier 2 params)
- `backend/ops/structure_ops.py`, `backend/ops/registry.py`
- `backend/excel/xlwings_adapter.py` (merged-cell detection)
- `frontend/app.js` (format swatches, row counts in preview)
- `tests/unit/test_structure_ops.py`, `tests/integration/test_graph_fake.py`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially sections 7 and 9. This is PHASE 7: Tier 2 structural
operations. Phases 1-6 are complete. Do not implement anything from later phases.

GOAL
The agent can reorganise the table - sort, filter, dedupe, column changes, fill blanks, highlight -
through the existing plan -> preview -> apply -> undo pipeline.

TASKS
1. backend/schemas/intent.py - add (every field with a description):
   - Condition(column: str, operator: Literal["equals","not_equals","contains","not_contains",
     "starts_with","ends_with","greater_than","less_than","greater_or_equal","less_or_equal",
     "is_blank","is_not_blank"], value: str | float | None = None)
   - SortRowsParams(by_column: str, descending: bool = False, then_by: str | None = None,
     then_descending: bool = False)
   - FilterRowsParams(condition: Condition, action: Literal["keep_matching","delete_matching"])
   - RemoveDuplicatesParams(columns: list[str] = [] (empty = compare whole rows),
     keep: Literal["first","last"] = "first")
   - InsertColumnParams(header: str, position: Literal["end","before","after"] = "end",
     reference_column: str | None = None, fill_value: str | None = None)
   - DeleteColumnParams(column: str)
   - RenameColumnParams(column: str, new_header: str)
   - MoveColumnParams(column: str, position: Literal["before","after","start","end"],
     reference_column: str | None = None)
   - FillBlanksParams(column: str, mode: Literal["value","down","up"], value: str | None = None)
   - HighlightCellsParams(condition: Condition,
     color: Literal["yellow","green","red","orange","blue","none"] = "yellow", whole_row: bool = False)
2. backend/ops/structure_ops.py - one handler per op: handler(snapshot, params) -> Patch, using pandas
   on the data rows (header row excluded; column names resolved through the serializer's header
   matching; unknown names raise TargetError listing valid headers).
   - Comparisons: numeric when both sides parse as numbers; date when both parse as dates;
     otherwise case-insensitive text after trimming. Blank = None or whitespace-only text.
   - Row operations rewrite the data block and clear rows that become empty (after = None).
     Column operations rewrite the affected columns including the header row. Only cells that
     really change go into the Patch.
   - Cells holding formulas move as formula text; add the warning "Formulas were moved but their
     references were not updated" (documented proof-of-concept limitation).
   - Highlight -> FormatChange entries. Colour map: yellow #FFF2CC, green #C6EFCE, red #FFC7CE,
     orange #F8CBAD, blue #DDEBF7, none -> None (clear).
   - Summaries such as "Deleted 3 rows where Status equals Inactive (10 -> 7 rows)".
3. Register all 9 Tier 2 ops (titles and examples from section 9). The classifier prompt picks them up
   automatically from the registry - do not hard-code them in prompts.
4. Merged cells: XlwingsAdapter.read_snapshot fills has_merged_cells (used range .api.MergeCells is
   not False). sort_rows, filter_rows, remove_duplicates, insert/delete/move_column refuse with a clear
   message when has_merged_cells is True (OpSpec.validator).
5. UI (frontend/app.js, styles.css): the preview also shows FormatChanges as colour swatches and, for
   row operations, a "rows before -> rows after" line.
6. Tests:
   - tests/unit/test_structure_ops.py using FakeAdapter on both fixtures: every op; every operator;
     numeric vs text vs date comparisons; blanks; dedupe on Email keep first / last (Emp IDs 102 and 107);
     move column before / after / start / end; insert with fill value; rename; delete; fill down / up /
     value; highlight cells and whole rows; idempotency (sorting an already sorted column -> no
     changes -> finish_nothing).
   - Extend tests/integration/test_graph_fake.py with scripted LLM outputs for sort_rows,
     filter_rows and highlight_cells end to end.

RULES
Follow PROJECT_CONTEXT.md. No new dependencies.

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"
Manual in Excel through the UI (Undo after each): "sort by Salary highest first",
"delete rows where Status is Inactive", "remove duplicate emails", "move Email next to Full Name",
"add a column called Bonus after Salary", "fill empty City cells with Unknown",
"highlight salaries above 60000 in green", "highlight Inactive rows in red".

Finish with a walkthrough. Then stop. Do not start Phase 8.
```

## Done when

- All eight manual instructions produce the right preview and result, and each one undoes cleanly.
- Tier 1 still works (no regressions), and all tests pass.

# Phase 8 · Tier 3 Formula Generation

**Tier:** 3 · **Estimate:** 2.5 days · **Needs:** Phase 7

## What this phase gives us

The headline feature: **describe a calculation in plain English and get a working Excel formula.** The model writes the formula for the first data row. Python first checks it statically (allowed functions, valid references, balanced brackets). It then **test-runs it inside Excel**: write, calculate, read the results, and immediately restore the sheet. Any `#NAME?`, `#DIV/0!` or other error goes back to the model for a corrected attempt. The preview shows each formula with its real computed value, so the user approves results they can see. Covers summary formulas, row-wise arithmetic, IF / COUNTIF / SUMIF, text formulas and date formulas.

## Files created / changed

- `backend/schemas/intent.py` (Tier 3 params)
- `backend/ops/formula_ops.py`, `backend/ops/registry.py`
- `backend/llm/prompts/extract_params_formula.md`
- `backend/config.py` (`formula_trial_run`), `frontend/app.js` (formula preview)
- `tests/unit/test_formula_ops.py`, `tests/integration/test_graph_fake.py`, `tests/integration/test_excel_live.py`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially sections 7, 9 and 10. This is PHASE 8: Tier 3 formula
generation. Phases 1-7 are complete. Do not implement anything from later phases.

GOAL
The user describes a calculation in plain English; the model writes an Excel formula; we check it
statically, trial-run it inside Excel, retry with the error if it fails, and preview formula + value.

TASKS
1. backend/schemas/intent.py - add (fields with descriptions):
   - AddFormulaColumnParams(new_header: str,
     formula: str  (formula for the FIRST data row, relative references, e.g. "=D2*E2"),
     target_column: str | None = None  (existing header to overwrite; None = next empty column))
   - AddSummaryFormulaParams(formula: str (e.g. "=SUM(D2:D11)"), label: str | None = None,
     target_cell: str | None = None  (None = two rows below the last data row, in the column of the
     first referenced range; the label goes in the cell to its left if that cell is empty))
2. backend/llm/prompts/extract_params_formula.md - used for both formula ops (OpSpec.prompt_name =
   "extract_params_formula"). Contents: the sheet text; the column-letter map; "data rows are 2..N";
   the formula rules and allowed functions from section 10; "never reference the target column";
   and 6 few-shot examples on the Sales / Employees fixtures:
   arithmetic (=D2*E2), IF (=IF(H2="Yes","Done","Pending")), COUNTIF (=COUNTIF(H2:H11,"Yes")),
   SUMIF (=SUMIF(B2:B11,"North",D2:D11)), text (=LEFT(TRIM(B2),FIND(" ",TRIM(B2))-1)), date (=MONTH(F2)).
3. backend/ops/formula_ops.py
   - ALLOWED_FUNCTIONS from section 10 (one constant).
   - static_check(formula, snapshot, target_col: str | None, row_wise: bool) -> list[str]:
     starts with "="; balanced parentheses and double quotes; every function name is allowed;
     every A1 reference (with or without $, ranges included) lies inside the used range; row-wise
     formulas reference only row 2 (relative) or absolute rows; no reference to the target column
     (circular); length < 500.
   - shift_relative_refs(formula, row_offset) -> str: shifts row numbers of references that are not
     $-anchored, leaves $-anchored rows, column letters, function names and anything inside string
     literals untouched.
   - add_formula_column handler: header cell + one CellChange per data row with after_formula =
     shift_relative_refs(formula, row - 2). New column = first empty column right of the used range.
   - add_summary_formula handler: label cell (optional) + formula cell.
   - Shared validator (OpSpec.validator) for both ops:
     (a) static_check -> errors;
     (b) if settings.formula_trial_run and the adapter is not FakeAdapter: on com_thread save
         read_region(bounding range of the patch), apply_patch, calculate(), read_values, then
         ALWAYS restore_region in a finally block. Any Excel error value (section 10) -> an error
         message naming the cell, the formula and the error, e.g.
         "K2: =D2*X2 gives #NAME? - column X does not exist; data columns are A-J".
         Otherwise store the computed values in patch.preview_values.
     Errors flow back to extract_params through the existing retry loop.
4. backend/config.py: formula_trial_run: bool = True.
5. Preview (nodes.preview + frontend): for formula ops show Cell | Formula | Value (from
   preview_values), first 10 rows then "... N more".
6. Tests:
   - tests/unit/test_formula_ops.py: shift_relative_refs (relative, $A$2, $A2, A$2, ranges D2:D11,
     multi-letter columns AA2, references inside "text" untouched, function names like LOG10 untouched);
     static_check (each failure type + valid formulas); both handlers on the Sales fixture
     (Total column -> K1 "Total", K2 "=D2*E2", K11 "=D11*E11"; summary under the data).
   - tests/integration/test_graph_fake.py: fake LLM first returns =D2*XYZ(E2) (unknown function),
     then =D2*E2 -> one retry, then success.
   - tests/integration/test_excel_live.py (@pytest.mark.excel): trial run of =D2/0 is detected as
     #DIV/0! and the sheet is restored exactly; a valid formula yields correct preview_values.

RULES
Follow PROJECT_CONTEXT.md. No new dependencies.

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"   and   uv run pytest -q -m excel
Manual on tests\fixtures\sales.xlsx through the UI (check the formula bar, then Undo):
"add a Total column = Qty x Unit Price", "add the total of Qty below the table",
"count how many orders are paid", "total Qty for the North region",
"add a column Net that applies the Discount to Qty x Unit Price",
"add Order Month from Order Date", "add a column Status that says Pending if Paid is No, else Done".
On employees.xlsx: "add First Name from Full Name", "add Years of Service from Join Date".

Finish with a walkthrough listing every manual instruction, the formula produced, retries used and
latency. Then stop. Do not start Phase 9.
```

## Done when

- Most of the nine manual instructions produce a correct formula, and the walkthrough records any failure.
- A deliberately broken formula is caught by the trial run, and the sheet is left exactly as it was.
- Undo removes inserted formula columns and summary cells.

# Phase 9 · Evaluation & Benchmark

**Tier:** 1–3 · **Estimate:** 1.5 days · **Needs:** Phase 8

## What this phase gives us

**The evidence that the concept works.** A repeatable test set of about 40 real instructions across Tiers 1–3 runs automatically against real Excel and the real local model. It measures how often the model picks the right operation, how often the final cells are exactly right, how many retries were needed, and how long each step took. Running it on both laptops and with different models gives a comparison table for the report or presentation, and the same suite catches regressions whenever prompts or models change.

## Files created / changed

- `tests/eval/eval_prompts.yaml`, `tests/eval/run_eval.py`
- `scripts/compare_runs.py`
- `README.md` (Results section)

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first, especially section 13. This is PHASE 9: evaluation and benchmarking.
Phases 1-8 are complete. Do not implement Phase 10.

GOAL
Hard numbers: accuracy and latency for every Tier 1-3 feature, per model and per laptop.

TASKS
1. tests/eval/eval_prompts.yaml - at least 40 cases in the section 13 format:
   Tier 1: 15, Tier 2: 13, Tier 3: 12, plus 3 unsupported requests. Use both fixtures. Include
   paraphrases and informal wording ("pls make dept caps", "get rid of the dupes by email") and at
   least 2 cases that refer to columns by letter. Work out expected values by hand from the fixture
   data in section 12 and double-check them. Mark date-dependent cases volatile: true.
2. tests/eval/run_eval.py - CLI (argparse):
   --cases (ids or glob), --tier, --model-label (default: settings.llm_model), --repeat N (default 1),
   --fail-fast.
   For each case: copy the fixture to a temp folder; open it with XlwingsAdapter(book_path=...) in a
   hidden Excel; run the compiled graph (InMemorySaver) with that adapter and auto-approve (resume
   with approved=True when interrupted); read the expected addresses with read_values; compare
   (text: exact; numbers: tolerance 0.01; volatile: formula present and not an error;
   must_not_change ranges unchanged); close without saving. Reuse one hidden Excel instance for the
   whole run.
   Record per case: op_chosen, op_correct, cells_correct, fully_correct, retries, error,
   latency per node and total, number of LLM calls, prompt/completion tokens (from usage).
3. Output to data/eval/<machine>_<model_label>_<YYYYmmdd_HHMMSS>.csv (one row per case and
   repetition) plus a Markdown summary next to it: header with machine, model label, llama-server
   model path and context size (GET {base}/models and {server root}/props when available); accuracy
   per tier and per op; median and p90 latency per tier; the 10 worst failures with the chosen op,
   params and error. Print the summary to the console.
4. scripts/compare_runs.py: read several summary CSVs and print / save a Markdown comparison table:
   rows = machine x model, columns = Tier 1/2/3 accuracy, median latency per tier, retries per case.
5. README.md: add a "Results" section with how to run the evaluation and a placeholder table.

RULES
Follow PROJECT_CONTEXT.md. No new dependencies (yaml via pyyaml, CSV via the standard library).

VERIFY
uv run ruff check .
uv run pytest -q -m "not excel"
uv run python tests/eval/run_eval.py --tier 1        (quick check)
uv run python tests/eval/run_eval.py                 (full run on this laptop)

Finish with a walkthrough containing the summary table and the worst failures, with a suggestion for
each failure (prompt wording, schema description or validation). Then stop. Do not start Phase 10.
```

## Done when

- A full run has completed on the Dell (Qwen2.5-Coder-7B) and on the Yoga (gpt-oss-20b, plus Qwen2.5-Coder-7B for a fair comparison).
- `compare_runs.py` produces the comparison table, and it is copied into `README.md`.
- The numbers are compared with the success criteria in the *Project Overview*. Fix the worst failures (usually prompt wording or schema descriptions) and re-run.

# Phase 10 · Excel Task Pane & Packaging (stretch)

**Tier:** presentation · **Estimate:** 1.5 days · **Needs:** Phase 9

## What this phase gives us

The final demo experience: the chat panel opens **inside Excel** from a ribbon button, and one script starts everything. The backend keeps using xlwings, so the task pane is only the Phase 6 page loaded inside Excel and none of the logic changes. The phase ends with a full test of the whole app with Wi-Fi switched off, proving it is offline. If loading the add-in is blocked on a machine, the fallback is the same page in a browser window beside Excel.

## Files created / changed

- `addin/manifest.xml`, `docs/ADDIN_SETUP.md`
- `frontend/vendor/office/` (local office.js), `frontend/assets/` (icons), `frontend/app.js` (`Office.onReady`)
- `backend/config.py` (SSL settings), `scripts/start_backend_https.bat`, `scripts/start_all.bat`, `scripts/stop_all.bat`

## Antigravity prompt

```text
Read PROJECT_CONTEXT.md first. This is PHASE 10 (stretch): load the chat UI inside Excel as a task pane
and package the app for one-click start. Phases 1-9 are complete. The backend keeps using xlwings;
the task pane is ONLY the existing frontend page.

TASKS
1. HTTPS on localhost (Office requires it). Document a one-time setup that needs Node.js LTS:
   npx office-addin-dev-certs install   (creates and trusts a localhost certificate in
   %USERPROFILE%\.office-addin-dev-certs). Add optional settings ssl_certfile / ssl_keyfile.
   scripts/start_backend_https.bat runs uvicorn on https://localhost:8443 with those files.
2. addin/manifest.xml: XML add-in-only manifest for Excel, TaskPaneApp, a new GUID, DisplayName
   "Excel AI (Local)", SourceLocation https://localhost:8443/index.html, permission
   ReadWriteDocument, icons 16/32/80 px served from frontend/assets (generate simple PNG icons with a
   small Python script using only the standard library: zlib + struct - no new dependencies),
   and VersionOverrides with a button on the Home tab that opens the task pane.
3. Office.js offline: get office.js from the npm package @microsoft/office-js (one-time download with
   Node) and copy its dist files into frontend/vendor/office/. Reference it with a relative path.
   In app.js call Office.onReady() when Office is present, and keep working as a normal web page
   when it is not (browser mode). The UI must not depend on Office APIs - all Excel work stays in
   the backend.
4. docs/ADDIN_SETUP.md: step-by-step sideloading - put manifest.xml in a folder, share it
   (e.g. \\<PC-NAME>\excel-ai-addin), add the share in Excel > File > Options > Trust Center >
   Trust Center Settings > Trusted Add-in Catalogs, tick "Show in Menu", restart Excel, then
   Home (or Insert) > Add-ins > My Add-ins > Shared Folder > Excel AI (Local). Include a
   troubleshooting section (certificate not trusted, blank pane, clearing the Office cache at
   %LOCALAPPDATA%\Microsoft\Office\16.0\Wef\).
5. scripts/start_all.bat <dell|yoga> [https]: starts llama-server minimised with the right profile,
   waits (poll /health, timeout 120 s) until the model is loaded, starts the backend with the
   matching EXAI_ENV_FILE, then opens Excel. scripts/stop_all.bat stops both processes.
6. README.md: "Demo day" checklist (start_all, open workbook, open pane, example instructions).
7. Offline test: with Wi-Fi OFF, run start_all, open the pane, and run one Tier 1, one Tier 2 and
   one Tier 3 instruction plus an Undo. Record the results in the walkthrough.

RULES
Follow PROJECT_CONTEXT.md. No new Python dependencies. Node.js is used only for the one-time
certificate and office.js download, never at runtime.

VERIFY
uv run ruff check .   and   uv run pytest -q -m "not excel"
Excel ribbon button opens the pane; health dots are green; the offline test passes on both laptops.

Finish with a walkthrough including screenshots of the pane inside Excel. Then stop.
```

## Done when

- The ribbon button opens the chat panel inside Excel, and the Tier 1–3 demo instructions work from it.
- `start_all.bat` brings everything up from a cold start with one command.
- The full demo works with Wi-Fi switched off on both laptops.

# Testing Strategy

| Level | What is tested | Where | Needs | Runs |
|---|---|---|---|---|
| Unit | A1 helpers, value formatting, serializer, target resolution, every text / structure / formula operation, prompt loader, LLM retry logic | tests/unit | Nothing | Every phase: `pytest -m "not excel"` |
| Integration (fake) | Whole LangGraph flow and the API with FakeAdapter and a scripted fake LLM: approve, reject, retry, unsupported, stale sheet | tests/integration | Nothing | Phase 5 onwards |
| Live Excel | Adapter read / write / restore, merged cells, formula trial runs | tests/integration (marker `excel`) | Excel | Phases 3, 7, 8: `pytest -m excel` |
| Smoke / benchmark | Model reachable, JSON output valid, real speeds | scripts/llm_smoke.py, llm_bench.py | llama-server | Phase 2, and whenever the model changes |
| Evaluation | ~40 real instructions end to end, accuracy + latency | tests/eval | Excel + llama-server | Phase 9, then before every demo |
| Manual demo | Chat UI beside / inside Excel, Undo, offline | – | Everything | Phases 6 and 10 |

**Rule:** a phase is finished only when `uv run ruff check .` and `uv run pytest -q -m "not excel"` pass, plus that phase's own *Done when* checks.

# Risks & Mitigations

| Risk | Effect | Mitigation |
|---|---|---|
| COM calls from several threads | Random "CoInitialize has not been called" errors or Excel hangs | One COM worker thread; xlwings imported only in the adapter (Phase 3) |
| Excel's Ctrl+Z can't undo COM changes | User can't revert an AI change | Our own undo snapshots in SQLite plus an Undo button (Phases 3, 5, 6) |
| Sheet edited between preview and apply | Stale changes overwrite the user's edits | apply_patch re-checks the "before" values and refuses if they changed (Phase 5) |
| Workbook in Manual calculation mode | Formula trial run reads stale values | The adapter calls `calculate()` before reading results (Phase 8) |
| Excel errors read as empty by xlwings | Broken formulas slip through | Results read with `err_to_str=True` (Phases 3, 8) |
| Small model picks the wrong operation or column | Wrong change | Column letters + header names in the prompt, JSON-schema output, validation with retries, user approval before apply |
| 6 GB GPU runs out of memory | Big slowdown (layers spill to the CPU) | Q4_K_M model, context 4096, close other GPU apps; check "offloaded N/N layers" |
| gpt-oss reasoning conflicts with JSON mode | Empty or invalid answers on the Yoga | reasoning_effort low, max_tokens 1024, json_mode fallback; else use Qwen2.5-Coder-7B on the Yoga too |
| Library APIs differ from what Antigravity expects | Code that doesn't run | `uv.lock` pins versions; prompts name exact APIs; the agent is told to read the installed source |
| Tier 2 moves don't re-reference formulas | Formulas point at the wrong cells after a sort | Documented limitation; warning shown in the preview |
| Task pane needs HTTPS and office.js | Pane does not load offline | Local certificate and local office.js; fallback = browser window beside Excel (Phase 10) |
| Project kept inside OneDrive | File locks and sync conflicts | Keep the project in `C:\dev\excel-ai` |

---

# Appendix A · PROJECT_CONTEXT.md

Save this as `PROJECT_CONTEXT.md` in the project root before Phase 1. It is also supplied as a separate file next to this plan. Every Antigravity prompt starts by telling the agent to read it, which keeps all phases consistent.

## PROJECT_CONTEXT — Local LLM Excel AI

> Read this whole file before every task. It is the single source of truth for architecture, folder layout, contracts and conventions. If a task requires a contract to change, update this file in the same change.

### 1. What we are building

An assistant for Microsoft Excel desktop on Windows that runs completely offline. The user types an instruction about the open sheet, for example "convert the headers to camelCase" or "add a Total column = Qty x Unit Price". A local LLM served by llama.cpp decides **what** to do. Deterministic Python decides **how**: it computes the exact change, shows a preview and applies it only after the user approves.

Proof-of-concept scope: sheets of about 10 rows x 10 columns, operations from Tier 1 (text transforms), Tier 2 (structural changes) and Tier 3 (single-formula generation). See section 9.

### 2. Non-negotiable rules

1. **Offline at runtime.** The only network traffic allowed is (a) backend to the local llama-server at `EXAI_LLM_BASE_URL` and (b) UI to backend on localhost. No cloud APIs, telemetry, CDNs, remote fonts or analytics. Never set LangSmith / LangChain tracing environment variables.
2. **The LLM never edits cells.** It returns an operation id and validated parameters (or a formula). Python builds a `Patch`, the user approves the preview, then the patch is applied.
3. **Every applied change is undoable** through our own snapshots. Excel's Ctrl+Z does not undo changes made through COM.
4. **All xlwings / COM calls run on the single COM worker thread** (`backend/excel/com_thread.py`). Import `xlwings` only in `backend/excel/xlwings_adapter.py` and in `scripts/`.
5. Python 3.12 managed with `uv`. Full type hints, Pydantic v2, `ruff` clean, docstrings on public functions.
6. Tests use pytest. A test may need Excel only if it is marked `@pytest.mark.excel`; tests in `tests/eval/` may need Excel and llama-server. Everything else uses `FakeAdapter` and a fake LLM.
7. No dependencies beyond section 4 without asking first.
8. Work only on the current phase. Do not start later phases or rewrite earlier phases' files unless the task says so.

### 3. Architecture

```text
Excel desktop  <-- COM (xlwings, one worker thread) -->  FastAPI backend
                                                          |-- LangGraph agent (backend/agent)
                                                          |-- operations      (backend/ops)
                                                          |-- undo store      (SQLite)
Chat UI (frontend/, HTML+JS) <-- HTTP + SSE, localhost:8000 --> FastAPI backend
FastAPI backend <-- OpenAI-compatible HTTP, localhost:8080 --> llama-server (llama.cpp + GGUF model)
```

#### LangGraph flow

```text
START -> read_sheet -> classify_intent
classify_intent --(op == "unsupported")--> finish_unsupported -> END
classify_intent --> extract_params -> execute_op -> validate
execute_op / validate --(error and retries < EXAI_MAX_RETRIES)--> extract_params   (errors are shown to the model)
execute_op / validate --(error and no retries left)--> finish_error -> END
validate --(patch has no changes)--> finish_nothing -> END
validate --(ok)--> preview   [interrupt(): waits for approve / reject]
preview --(approved)--> apply_patch -> END
preview --(rejected)--> finish_cancelled -> END
```

### 4. Tech stack and key APIs

- Runtime dependencies: fastapi, uvicorn[standard], sse-starlette, pydantic, pydantic-settings, langgraph, langchain-core, langchain-openai, langgraph-checkpoint-sqlite, xlwings, pywin32 (Windows only), pandas, openpyxl, httpx, pyyaml.
- Dev dependencies: pytest, pytest-asyncio, ruff.
- LLM: `langchain_openai.ChatOpenAI(base_url=EXAI_LLM_BASE_URL, api_key="sk-local", model=EXAI_LLM_MODEL, temperature=0, extra_body=EXAI_LLM_EXTRA_BODY)` and `.with_structured_output(Model, method="json_schema", include_raw=True)`.
- Graph: `langgraph.graph.StateGraph`, `START`, `END`; `langgraph.types.interrupt`, `Command`; checkpointer `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` (tests: `langgraph.checkpoint.memory.InMemorySaver`).
- Excel: xlwings (`xw.apps.active`, `Range.options(ndim=2, err_to_str=True)`, `Range.formula`, `Range.color`, `App.calculate()`, `App.screen_updating`).
- Streaming: `sse_starlette.sse.EventSourceResponse`.
- Inference server: llama.cpp `llama-server` (OpenAI-compatible `/v1/chat/completions`, `/v1/models`, `/health`, `/props`).

### 5. Folder layout

```text
excel-ai/
├── PROJECT_CONTEXT.md          # this file
├── README.md
├── pyproject.toml              # uv project + ruff + pytest config
├── uv.lock
├── requirements.txt            # generated: uv export --no-hashes
├── .env.example
├── .gitignore
├── config/
│   ├── dell.env
│   └── yoga.env
├── backend/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app factory, lifespan, static mount
│   ├── config.py               # Settings (pydantic-settings, prefix EXAI_)
│   ├── logging_setup.py
│   ├── api/
│   │   ├── deps.py             # get_adapter(), get_graph()
│   │   ├── routes_health.py
│   │   ├── routes_chat.py      # /api/chat and /api/confirm (SSE)
│   │   └── routes_undo.py
│   ├── llm/
│   │   ├── client.py           # ChatOpenAI factory, structured_call()
│   │   ├── prompts.py          # load_prompt()
│   │   └── prompts/            # *.md prompt templates
│   ├── agent/
│   │   ├── state.py
│   │   ├── nodes.py
│   │   └── graph.py
│   ├── excel/
│   │   ├── adapter.py          # WorkbookAdapter protocol + errors
│   │   ├── com_thread.py       # single COM worker thread
│   │   ├── xlwings_adapter.py
│   │   ├── fake_adapter.py     # in-memory adapter for tests
│   │   ├── serializer.py       # snapshot -> prompt text, resolve_target()
│   │   ├── a1.py               # A1 address helpers
│   │   └── values.py           # display_value(), JSON encode/decode of cell values
│   ├── ops/
│   │   ├── registry.py         # OpSpec, REGISTRY, execute()
│   │   ├── text_ops.py         # Tier 1
│   │   ├── structure_ops.py    # Tier 2
│   │   └── formula_ops.py      # Tier 3
│   ├── schemas/
│   │   ├── sheet.py            # SheetSnapshot, RegionState
│   │   ├── intent.py           # Target, IntentChoice, *Params models
│   │   ├── patch.py            # CellChange, FormatChange, Patch
│   │   └── api.py              # request / response models
│   └── storage/
│       ├── db.py               # SQLite helpers
│       └── undo.py             # undo snapshots
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── assets/                 # icons
│   └── vendor/office/          # local office.js copy (Phase 10)
├── addin/
│   └── manifest.xml            # Excel task pane manifest (Phase 10)
├── scripts/
│   ├── start_llm_dell.bat
│   ├── start_llm_yoga.bat
│   ├── start_backend.bat
│   ├── start_backend_https.bat # Phase 10
│   ├── start_all.bat           # Phase 10
│   ├── stop_all.bat            # Phase 10
│   ├── check_setup.py
│   ├── make_fixtures.py
│   ├── llm_smoke.py
│   ├── llm_bench.py
│   ├── excel_probe.py
│   ├── chat_cli.py
│   └── compare_runs.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/               # employees.xlsx, sales.xlsx (generated)
│   ├── unit/
│   ├── integration/
│   └── eval/
│       ├── eval_prompts.yaml
│       └── run_eval.py
├── docs/
│   └── ADDIN_SETUP.md          # Phase 10
├── models/                     # *.gguf model files        (gitignored)
├── llama/                      # llama.cpp binaries        (gitignored)
└── data/                       # SQLite, logs, bench, eval (gitignored)
```

Every package folder under `backend/` has an `__init__.py`.

### 6. Machine profiles

`config/dell.env`

```text
EXAI_MACHINE_NAME=dell-g15
EXAI_LLM_BASE_URL=http://127.0.0.1:8080/v1
EXAI_LLM_MODEL=qwen2.5-coder-7b-instruct-q4_k_m
EXAI_LLM_MAX_TOKENS=512
EXAI_LLM_EXTRA_BODY={}
EXAI_MAX_RETRIES=2
```

`config/yoga.env`

```text
EXAI_MACHINE_NAME=yoga-pro-7
EXAI_LLM_BASE_URL=http://127.0.0.1:8080/v1
EXAI_LLM_MODEL=gpt-oss-20b-mxfp4
EXAI_LLM_MAX_TOKENS=1024
EXAI_LLM_EXTRA_BODY={"chat_template_kwargs": {"reasoning_effort": "low"}}
EXAI_MAX_RETRIES=2
```

The backend picks the profile from the environment variable `EXAI_ENV_FILE` (default `.env`). llama-server serves one model, so `EXAI_LLM_MODEL` is only a label for logs and reports.

llama-server commands (run from the project root):

```text
Dell : llama\llama-server.exe -m models\Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf -ngl 99 -c 4096 --jinja --host 127.0.0.1 --port 8080
Yoga : llama\llama-server.exe -m models\gpt-oss-20b-mxfp4.gguf -ngl 99 -c 8192 --jinja --host 127.0.0.1 --port 8080
Yoga (parity with Dell): same as Dell but with -c 8192
```

### 7. Core contracts

```python
CellValue = str | int | float | bool | datetime | None

class SheetSnapshot(BaseModel):
    workbook: str
    sheet: str
    used_range: str                      # "A1:J11" (never contains $)
    header_row: int = 1                  # PoC assumption: first row of the used range holds headers
    columns: list[str]                   # ["A", ..., "J"]
    headers: list[str]                   # header text per column ("" if empty)
    values: list[list[CellValue]]        # whole used range, header row included
    formulas: list[list[str | None]]     # "=..." or None for constants / empty cells
    selection: str | None = None         # "B2:B4" or None
    has_merged_cells: bool = False       # filled in Phase 7

class RegionState(BaseModel):            # saved for undo and for formula trial runs
    sheet: str
    region: str                          # bounding A1 range
    values: list[list[CellValue]]
    formulas: list[list[str | None]]
    fills: list[list[str | None]]        # "#RRGGBB" or None

class Target(BaseModel):
    kind: Literal["columns", "headers", "range", "selection"]
    columns: list[str] = []              # header names (preferred) or column letters
    range: str | None = None             # A1 range when kind == "range"

class CellChange(BaseModel):
    address: str                         # "B3"
    before: CellValue
    after: CellValue = None
    after_formula: str | None = None     # set when a formula is written

class FormatChange(BaseModel):
    address: str
    fill_hex: str | None                 # "#C6EFCE"; None clears the fill

class Patch(BaseModel):
    op: str
    sheet: str
    cells: list[CellChange] = []
    formats: list[FormatChange] = []
    summary: str                         # "Converted 10 headers to camelCase"
    warnings: list[str] = []
    preview_values: dict[str, CellValue] = {}   # Phase 8: computed formula results by address

class IntentChoice(BaseModel):           # built dynamically: op is a Literal of registered op ids + "unsupported"
    op: str
    explanation: str                     # one short sentence shown to the user

@dataclass
class OpSpec:
    name: str                            # op id, e.g. "convert_case_style"
    title: str                           # human readable, e.g. "Convert case style"
    tier: int
    params_model: type[BaseModel]
    description: str                     # shown to the classifier
    examples: list[str]                  # example instructions shown to the classifier
    handler: Callable[[SheetSnapshot, BaseModel], Patch]
    validator: Callable[..., Awaitable[tuple[list[str], Patch]]] | None = None
    #   async validator(snapshot, params, patch, adapter) -> (errors, possibly updated patch)
    prompt_name: str = "extract_params"  # formula ops use "extract_params_formula"
```

- Cell values inside the backend may be `datetime`. At JSON boundaries (SQLite undo store, SSE) use `backend/excel/values.py`: `to_jsonable()` / `from_jsonable()` encode datetimes as `{"$date": "YYYY-MM-DDTHH:MM:SS"}`; `display_value()` gives the text shown to users and the model.
- Addresses are uppercase A1 without `$` everywhere except inside formulas.
- Errors shown to users: `ExcelNotConnectedError`, `TargetError`, `OpError`, `FormulaError`. Messages are short, plain English and say how to fix the problem.

### 8. Sheet serialization (what the model sees)

```text
Sheet "Employees" | used range A1:J11 | header row 1 | data rows 2-11 | selection: B2:B4
Columns: A=Emp ID, B=Full Name, C=Department, D=Email, E=Phone, F=Salary, G=Join Date, H=City, I=Status, J=Rating
Row | A | B | C | D | E | F | G | H | I | J
1 | Emp ID | Full Name | Department | Email | Phone | Salary | Join Date | City | Status | Rating
2 | 101 | "  john smith " | Sales | john.smith@acme.com | (555) 123-4567 | 52000 | 2021-03-04 | New York | Active | 4.2
4 | 103 | "carlos  mendez" | Marketing | carlos.mendez@acme.com | 555-222-3333 | 61000 | 2022-01-10 | (empty) | Inactive | 3.9
```

Rules: quote text that has leading, trailing or repeated spaces or contains `|`. Empty cells are `(empty)`. Whole numbers have no `.0`. Dates are `YYYY-MM-DD`. Formula cells are shown as `{=D2*E2}`. Cell text is cut at 40 characters with `...`. If there are more than `EXAI_MAX_PROMPT_ROWS` data rows, show the first ones and add `(... N more rows not shown)`.

### 9. Operation catalog

| Op id | Tier | Title | Params model | Example instructions |
|---|---|---|---|---|
| change_case | 1 | Change text case | ChangeCaseParams | "Make the Department column uppercase"; "Put Full Name in title case" |
| convert_case_style | 1 | Convert case style | ConvertCaseStyleParams | "Convert all column headers to camelCase"; "Make the headers snake_case" |
| trim_whitespace | 1 | Trim spaces | TrimWhitespaceParams | "Remove extra spaces in Full Name"; "Clean up the spaces in column B" |
| find_replace | 1 | Find and replace | FindReplaceParams | "Replace Inactive with Former in Status"; "Change New York to NYC" |
| add_prefix_suffix | 1 | Add prefix / suffix | AddPrefixSuffixParams | "Add EMP- before every Emp ID"; "Add ' (HQ)' after each City" |
| remove_characters | 1 | Remove characters | RemoveCharactersParams | "Keep only digits in the Phone column"; "Remove symbols from Phone" |
| sort_rows | 2 | Sort rows | SortRowsParams | "Sort by Salary, highest first"; "Sort by City then Full Name" |
| filter_rows | 2 | Filter rows | FilterRowsParams | "Delete rows where Status is Inactive"; "Keep only Engineering employees" |
| remove_duplicates | 2 | Remove duplicates | RemoveDuplicatesParams | "Remove duplicate emails"; "Remove duplicate rows" |
| insert_column | 2 | Insert column | InsertColumnParams | "Add a column called Bonus after Salary"; "Insert an empty Notes column at the end" |
| delete_column | 2 | Delete column | DeleteColumnParams | "Delete the Rating column" |
| rename_column | 2 | Rename column | RenameColumnParams | "Rename Emp ID to Employee ID" |
| move_column | 2 | Move column | MoveColumnParams | "Move Email next to Full Name"; "Put City first" |
| fill_blanks | 2 | Fill blanks | FillBlanksParams | "Fill empty City cells with Unknown"; "Fill blanks in Notes with N/A" |
| highlight_cells | 2 | Highlight cells | HighlightCellsParams | "Highlight salaries above 60000 in green"; "Highlight Inactive rows in red" |
| add_formula_column | 3 | Add formula column | AddFormulaColumnParams | "Add a Total column = Qty x Unit Price"; "Add Order Month from Order Date"; "Add First Name from Full Name" |
| add_summary_formula | 3 | Add summary formula | AddSummaryFormulaParams | "Add the total of Qty below the table"; "Count how many orders are paid"; "Total Qty for the North region" |
| unsupported | - | Not supported yet | - | Anything else: the agent explains what it can do |

### 10. Formula rules

- Formulas start with `=`, use commas as argument separators and double quotes for text.
- Row-wise formulas are written for the first data row (row 2) with relative references; Python shifts them for the other rows.
- Allowed functions: SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, COUNTBLANK, COUNTIF, COUNTIFS, SUMIF, SUMIFS, AVERAGEIF, AVERAGEIFS, SUMPRODUCT, ROUND, ROUNDUP, ROUNDDOWN, INT, ABS, MOD, IF, IFS, IFERROR, AND, OR, NOT, LEFT, RIGHT, MID, LEN, FIND, SEARCH, SUBSTITUTE, REPLACE, TRIM, UPPER, LOWER, PROPER, CONCAT, CONCATENATE, TEXTJOIN, TEXT, VALUE, EXACT, DATE, YEAR, MONTH, DAY, TODAY, DATEDIF, EDATE, EOMONTH, WEEKDAY, NETWORKDAYS, DAYS. Add TEXTBEFORE and TEXTAFTER only if the team's Excel is Microsoft 365.
- Excel error values to detect: #NAME?, #REF!, #VALUE!, #DIV/0!, #N/A, #NUM!, #NULL!, #SPILL!, #CALC!.

### 11. API and SSE events

```text
GET  /api/health          -> {backend, machine, llm: {reachable, model, error}, excel: {connected, workbook, sheet, error}}
POST /api/chat            {message, thread_id?}     -> text/event-stream
POST /api/confirm         {thread_id, approved}     -> text/event-stream
POST /api/undo                                      -> {restored, summary}
GET  /api/undo/history                              -> [{id, created_at, summary}]
GET  /                                              -> frontend/index.html
```

SSE events (event name, then JSON data):

```text
status   {node, label}                                   e.g. {"node": "read_sheet", "label": "Reading sheet"}
plan     {op, op_title, params, explanation}
preview  {thread_id, summary, changes: [{address, before, after, formula}], formats: [{address, fill_hex}], warnings: []}
done     {applied, summary}
error    {message}
```

### 12. Fixtures

`scripts/make_fixtures.py` writes these two workbooks with openpyxl. Dates are written as real Excel dates. `None` means an empty cell. The text values contain deliberate extra spaces and mixed case.

```python
EMPLOYEES_SHEET = "Employees"
EMPLOYEES_HEADERS = ["Emp ID", "Full Name", "Department", "Email", "Phone",
                     "Salary", "Join Date", "City", "Status", "Rating"]
EMPLOYEES_ROWS = [
    [101, "  john smith ", "Sales", "john.smith@acme.com", "(555) 123-4567", 52000, "2021-03-04", "New York", "Active", 4.2],
    [102, "PRIYA SHARMA", "Engineering", "priya.sharma@acme.com", "555.987.6543", 78000, "2019-07-15", "Pune", "Active", 4.8],
    [103, "carlos  mendez", "Marketing", "carlos.mendez@acme.com", "555-222-3333", 61000, "2022-01-10", None, "Inactive", 3.9],
    [104, "Aisha Khan", "Sales", "aisha.khan@acme.com", "+1 555 444 5555", 49500, "2023-05-22", "Chicago", "Active", 4.0],
    [105, "li wei", "Engineering", "li.wei@acme.com", "5556667777", 83000, "2018-11-30", "Seattle", "Active", 4.6],
    [106, "Tom O'Brien", "Finance", "tom.obrien@acme.com", "(555) 888-9999", 58000, "2020-02-17", None, "Inactive", 3.5],
    [107, "priya sharma", "Engineering", "priya.sharma@acme.com", "555.987.6543", 78000, "2019-07-15", "Pune", "Active", 4.8],
    [108, "Elena Petrova", "HR", "elena.petrova@acme.com", "555-101-2020", 55000, "2021-09-01", "Boston", "Active", 4.1],
    [109, "raj patel", "Finance", "raj.patel@acme.com", "555 303 4040", 67000, "2017-04-12", "New York", "Active", 4.4],
    [110, "Sara  Lee ", "Marketing", "sara.lee@acme.com", "555-505-6060", 45000, "2024-06-03", "Chicago", "Inactive", 3.7],
]

SALES_SHEET = "Sales"
SALES_HEADERS = ["Order ID", "Region", "Product", "Qty", "Unit Price",
                 "Order Date", "Customer", "Paid", "Discount", "Notes"]
SALES_ROWS = [
    ["SO-1001", "North", "Laptop", 2, 850, "2026-01-05", "Acme Corp", "Yes", 0.05, "urgent delivery"],
    ["SO-1002", "South", "Mouse", 15, 12.5, "2026-01-07", "Beta Ltd", "No", 0, None],
    ["SO-1003", "East", "Monitor", 4, 210, "2026-01-12", "Acme Corp", "Yes", 0.1, "bulk order"],
    ["SO-1004", "West", "Keyboard", 10, 35, "2026-02-02", "Gamma Inc", "Yes", 0, None],
    ["SO-1005", "North", "Laptop", 1, 900, "2026-02-14", "Delta LLC", "No", 0, "gift wrap"],
    ["SO-1006", "South", "Monitor", 3, 199, "2026-02-20", "Beta Ltd", "Yes", 0.05, None],
    ["SO-1007", "East", "Mouse", 25, 11, "2026-03-01", "Gamma Inc", "Yes", 0.15, "bulk order"],
    ["SO-1008", "West", "Laptop", 2, 875, "2026-03-09", "Acme Corp", "No", 0, None],
    ["SO-1009", "North", "Keyboard", 8, 32, "2026-03-15", "Delta LLC", "Yes", 0, "follow up"],
    ["SO-1010", "South", "Monitor", 5, 205, "2026-03-28", "Gamma Inc", "Yes", 0.1, None],
]
```

### 13. Evaluation cases

`tests/eval/eval_prompts.yaml` holds a list of cases in this format:

```yaml
- id: t1_headers_camel
  tier: 1
  fixture: employees.xlsx
  instruction: "Convert all the column headers to camelCase"
  expected_op: convert_case_style
  expected:            # address -> value after the change is applied
    A1: empId
    B1: fullName
    G1: joinDate
  must_not_change: ["A2:J11"]

- id: t3_total_column
  tier: 3
  fixture: sales.xlsx
  instruction: "Add a Total column that multiplies Qty by Unit Price"
  expected_op: add_formula_column
  expected:            # for formulas compare COMPUTED values (tolerance 0.01), not formula text
    K1: Total
    K2: 1700
    K3: 187.5

- id: unsupported_chart
  tier: 0
  fixture: sales.xlsx
  instruction: "Draw a pie chart of sales by region"
  expected_op: unsupported
```

Cases whose result depends on today's date (TODAY, DATEDIF to today) set `volatile: true`. For those, only check that a formula exists and the result is not an Excel error.

### 14. Conventions

- Small modules with one responsibility each. Keep functions short and give them clear names.
- Use `logging.getLogger(__name__)`. No `print` in `backend/`.
- Prompt templates live in `backend/llm/prompts/*.md` and are never inlined in Python.
- User-facing text is short and plain English, and says what happened and what to do next.
- Every phase ends with `uv run ruff check .` and `uv run pytest -q -m "not excel"` passing.
