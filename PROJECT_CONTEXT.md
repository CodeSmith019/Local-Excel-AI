# PROJECT_CONTEXT — Local LLM Excel AI

> Read this whole file before every task. It is the single source of truth for architecture, folder layout, contracts and conventions. If a task requires a contract to change, update this file in the same change.

## 1. What we are building

An assistant for Microsoft Excel desktop on Windows that runs completely offline. The user types an instruction about the open sheet, for example "convert the headers to camelCase" or "add a Total column = Qty x Unit Price". A local LLM served by llama.cpp decides **what** to do. Deterministic Python decides **how**: it computes the exact change, shows a preview and applies it only after the user approves.

Proof-of-concept scope: sheets of about 10 rows x 10 columns, operations from Tier 1 (text transforms), Tier 2 (structural changes) and Tier 3 (single-formula generation). See section 9.

## 2. Non-negotiable rules

1. **Offline at runtime.** The only network traffic allowed is (a) backend to the local llama-server at `EXAI_LLM_BASE_URL` and (b) UI to backend on localhost. No cloud APIs, telemetry, CDNs, remote fonts or analytics. Never set LangSmith / LangChain tracing environment variables.
2. **The LLM never edits cells.** It returns an operation id and validated parameters (or a formula). Python builds a `Patch`, the user approves the preview, then the patch is applied.
3. **Every applied change is undoable** through our own snapshots. Excel's Ctrl+Z does not undo changes made through COM.
4. **All xlwings / COM calls run on the single COM worker thread** (`backend/excel/com_thread.py`). Import `xlwings` only in `backend/excel/xlwings_adapter.py` and in `scripts/`.
5. Python 3.12 managed with `uv`. Full type hints, Pydantic v2, `ruff` clean, docstrings on public functions.
6. Tests use pytest. A test may need Excel only if it is marked `@pytest.mark.excel`; tests in `tests/eval/` may need Excel and llama-server. Everything else uses `FakeAdapter` and a fake LLM.
7. No dependencies beyond section 4 without asking first.
8. Work only on the current phase. Do not start later phases or rewrite earlier phases' files unless the task says so.

## 3. Architecture

```text
Excel desktop  <-- COM (xlwings, one worker thread) -->  FastAPI backend
                                                          |-- LangGraph agent (backend/agent)
                                                          |-- operations      (backend/ops)
                                                          |-- undo store      (SQLite)
Chat UI (frontend/, HTML+JS) <-- HTTP + SSE, localhost:8000 --> FastAPI backend
FastAPI backend <-- OpenAI-compatible HTTP, localhost:8080 --> llama-server (llama.cpp + GGUF model)
```

### LangGraph flow

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

## 4. Tech stack and key APIs

- Runtime dependencies: fastapi, uvicorn[standard], sse-starlette, pydantic, pydantic-settings, langgraph, langchain-core, langchain-openai, langgraph-checkpoint-sqlite, xlwings, pywin32 (Windows only), pandas, openpyxl, httpx, pyyaml.
- Dev dependencies: pytest, pytest-asyncio, ruff.
- LLM: `langchain_openai.ChatOpenAI(base_url=EXAI_LLM_BASE_URL, api_key="sk-local", model=EXAI_LLM_MODEL, temperature=0, extra_body=EXAI_LLM_EXTRA_BODY)` and `.with_structured_output(Model, method="json_schema", include_raw=True)`.
- Graph: `langgraph.graph.StateGraph`, `START`, `END`; `langgraph.types.interrupt`, `Command`; checkpointer `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` (tests: `langgraph.checkpoint.memory.InMemorySaver`).
- Excel: xlwings (`xw.apps.active`, `Range.options(ndim=2, err_to_str=True)`, `Range.formula`, `Range.color`, `App.calculate()`, `App.screen_updating`).
- Streaming: `sse_starlette.sse.EventSourceResponse`.
- Inference server: llama.cpp `llama-server` (OpenAI-compatible `/v1/chat/completions`, `/v1/models`, `/health`, `/props`).

## 5. Folder layout

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

## 6. Machine profiles

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

## 7. Core contracts

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

## 8. Sheet serialization (what the model sees)

```text
Sheet "Employees" | used range A1:J11 | header row 1 | data rows 2-11 | selection: B2:B4
Columns: A=Emp ID, B=Full Name, C=Department, D=Email, E=Phone, F=Salary, G=Join Date, H=City, I=Status, J=Rating
Row | A | B | C | D | E | F | G | H | I | J
1 | Emp ID | Full Name | Department | Email | Phone | Salary | Join Date | City | Status | Rating
2 | 101 | "  john smith " | Sales | john.smith@acme.com | (555) 123-4567 | 52000 | 2021-03-04 | New York | Active | 4.2
4 | 103 | "carlos  mendez" | Marketing | carlos.mendez@acme.com | 555-222-3333 | 61000 | 2022-01-10 | (empty) | Inactive | 3.9
```

Rules: quote text that has leading, trailing or repeated spaces or contains `|`. Empty cells are `(empty)`. Whole numbers have no `.0`. Dates are `YYYY-MM-DD`. Formula cells are shown as `{=D2*E2}`. Cell text is cut at 40 characters with `...`. If there are more than `EXAI_MAX_PROMPT_ROWS` data rows, show the first ones and add `(... N more rows not shown)`.

## 9. Operation catalog

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

## 10. Formula rules

- Formulas start with `=`, use commas as argument separators and double quotes for text.
- Row-wise formulas are written for the first data row (row 2) with relative references; Python shifts them for the other rows.
- Allowed functions: SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, COUNTBLANK, COUNTIF, COUNTIFS, SUMIF, SUMIFS, AVERAGEIF, AVERAGEIFS, SUMPRODUCT, ROUND, ROUNDUP, ROUNDDOWN, INT, ABS, MOD, IF, IFS, IFERROR, AND, OR, NOT, LEFT, RIGHT, MID, LEN, FIND, SEARCH, SUBSTITUTE, REPLACE, TRIM, UPPER, LOWER, PROPER, CONCAT, CONCATENATE, TEXTJOIN, TEXT, VALUE, EXACT, DATE, YEAR, MONTH, DAY, TODAY, DATEDIF, EDATE, EOMONTH, WEEKDAY, NETWORKDAYS, DAYS. Add TEXTBEFORE and TEXTAFTER only if the team's Excel is Microsoft 365.
- Excel error values to detect: #NAME?, #REF!, #VALUE!, #DIV/0!, #N/A, #NUM!, #NULL!, #SPILL!, #CALC!.

## 11. API and SSE events

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

## 12. Fixtures

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

## 13. Evaluation cases

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

## 14. Conventions

- Small modules with one responsibility each. Keep functions short and give them clear names.
- Use `logging.getLogger(__name__)`. No `print` in `backend/`.
- Prompt templates live in `backend/llm/prompts/*.md` and are never inlined in Python.
- User-facing text is short and plain English, and says what happened and what to do next.
- Every phase ends with `uv run ruff check .` and `uv run pytest -q -m "not excel"` passing.
