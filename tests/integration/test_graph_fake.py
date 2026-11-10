"""Integration tests for the LangGraph agent using FakeAdapter and scripted LLM calls."""

from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.agent.graph import build_graph
from backend.excel.fake_adapter import FakeAdapter
from backend.llm.client import StructuredResult
from backend.schemas.intent import (
    AddFormulaColumnParams,
    ChangeCaseParams,
    Condition,
    ConvertCaseStyleParams,
    FilterRowsParams,
    FindReplaceParams,
    HighlightCellsParams,
    SortRowsParams,
    Target,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "employees.xlsx"


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    """Create a FakeAdapter preloaded with employees.xlsx."""
    return FakeAdapter(file_path=FIXTURE_PATH)


@pytest.mark.asyncio
async def test_headers_camel_case_approved(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 1: Convert headers to camelCase and approve; cells change in sheet."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="convert_case_style",
                    explanation="Convert column headers to camelCase",
                )
            )
        if issubclass(schema, ConvertCaseStyleParams):
            return StructuredResult(
                value=ConvertCaseStyleParams(
                    target=Target(kind="headers"),
                    style="camel",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_1", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_1",
        "user_message": "convert the column headers to camelCase",
        "retries": 0,
        "validation_errors": [],
    }

    # Initial stream until interrupt (preview)
    preview_seen = False
    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            preview_seen = True
            break
    assert preview_seen

    # Resume with approval
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is True
    assert final_state.values.get("error") is None

    # Check that headers changed in fake adapter
    new_snapshot = fake_adapter.read_snapshot()
    assert new_snapshot.headers[0] == "empId"
    assert new_snapshot.headers[1] == "fullName"
    assert new_snapshot.headers[2] == "department"


@pytest.mark.asyncio
async def test_headers_camel_case_rejected(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 2: Convert headers to camelCase and reject; cells remain unchanged."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="convert_case_style",
                    explanation="Convert column headers to camelCase",
                )
            )
        if issubclass(schema, ConvertCaseStyleParams):
            return StructuredResult(
                value=ConvertCaseStyleParams(
                    target=Target(kind="headers"),
                    style="camel",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_2", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_2",
        "user_message": "convert the column headers to camelCase",
        "retries": 0,
        "validation_errors": [],
    }

    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            break

    # Reject
    async for _ in graph.astream(
        Command(resume={"approved": False}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is False
    assert final_state.values.get("result_summary") == "Operation cancelled"

    # Headers remain unchanged
    new_snapshot = fake_adapter.read_snapshot()
    assert new_snapshot.headers[0] == "Emp ID"
    assert new_snapshot.headers[1] == "Full Name"


@pytest.mark.asyncio
async def test_unsupported_operation(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 3: Unsupported instruction returns message listing capabilities."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="unsupported",
                    explanation="I cannot draw charts or graphs.",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_3", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_3",
        "user_message": "draw a pie chart of sales",
        "retries": 0,
        "validation_errors": [],
    }

    async for _ in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is False
    summary = final_state.values.get("result_summary", "")
    assert "I cannot do that yet. Here is what I can do:" in summary
    assert "Convert case style" in summary


@pytest.mark.asyncio
async def test_unknown_column_retry_success(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 4: Unknown column name on first try, correct one on retry; succeeds."""
    call_count = 0

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        nonlocal call_count
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="change_case",
                    explanation="Make the Department column uppercase",
                )
            )
        if issubclass(schema, ChangeCaseParams):
            call_count += 1
            if call_count == 1:
                # Wrong column name
                return StructuredResult(
                    value=ChangeCaseParams(
                        target=Target(kind="columns", columns=["Dep"]),
                        mode="upper",
                    )
                )
            # Correct column name on retry
            return StructuredResult(
                value=ChangeCaseParams(
                    target=Target(kind="columns", columns=["Department"]),
                    mode="upper",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_4", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_4",
        "user_message": "Make Department uppercase",
        "retries": 0,
        "validation_errors": [],
    }

    # Should retry internally and stop at preview
    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            break

    assert call_count == 2

    # Approve
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is True

    # Check cell C2 (Department of row 2) is UPPERCASE
    assert fake_adapter._grid["C2"]["value"] == "SALES"


@pytest.mark.asyncio
async def test_wrong_twice_finish_error(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 5: Invalid parameters on every retry leads to finish_error."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="change_case",
                    explanation="Make column uppercase",
                )
            )
        if issubclass(schema, ChangeCaseParams):
            # Always invalid column
            return StructuredResult(
                value=ChangeCaseParams(
                    target=Target(kind="columns", columns=["NonExistentColumn"]),
                    mode="upper",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_5", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_5",
        "user_message": "Make column uppercase",
        "retries": 0,
        "validation_errors": [],
    }

    async for _ in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is False
    assert final_state.values.get("error") is not None
    assert "not found" in str(final_state.values.get("error"))


@pytest.mark.asyncio
async def test_nothing_to_change(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 6: Operation produces no changes; routes to finish_nothing."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="find_replace",
                    explanation="Find and replace text that does not exist",
                )
            )
        if issubclass(schema, FindReplaceParams):
            return StructuredResult(
                value=FindReplaceParams(
                    target=Target(kind="columns", columns=["Department"]),
                    find="NON_EXISTENT_TEXT",
                    replace="REPLACEMENT",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_6", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_6",
        "user_message": "Replace NON_EXISTENT_TEXT with REPLACEMENT in Department",
        "retries": 0,
        "validation_errors": [],
    }

    async for _ in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is False
    assert final_state.values.get("result_summary") == "Nothing to change"


@pytest.mark.asyncio
async def test_sheet_modified_between_preview_and_apply(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 7: Sheet modified externally after preview; apply is refused."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="convert_case_style",
                    explanation="Convert headers to camelCase",
                )
            )
        if issubclass(schema, ConvertCaseStyleParams):
            return StructuredResult(
                value=ConvertCaseStyleParams(
                    target=Target(kind="headers"),
                    style="camel",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_7", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_7",
        "user_message": "convert the column headers to camelCase",
        "retries": 0,
        "validation_errors": [],
    }

    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            break

    # Sheet is modified externally before approval
    fake_adapter._grid["A1"]["value"] = "ModifiedExternally"

    # Resume with approval
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is False
    expected_msg = "The sheet changed since the preview - please ask again."
    assert final_state.values.get("error") == expected_msg


# ---------------------------------------------------------------------------
# Tier 2 Structural Operations End-to-End Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sort_rows_e2e(fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sort rows by Salary descending end-to-end with approval."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="sort_rows",
                    explanation="Sort rows by Salary highest first",
                )
            )
        if issubclass(schema, SortRowsParams):
            return StructuredResult(
                value=SortRowsParams(
                    by_column="Salary",
                    descending=True,
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_t2_sort", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_t2_sort",
        "user_message": "sort by Salary highest first",
        "retries": 0,
        "validation_errors": [],
    }

    preview_seen = False
    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            preview_seen = True
            break
    assert preview_seen

    # Resume with approval
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is True
    assert "Sorted rows by Salary (descending)" in final_state.values.get("result_summary", "")

    # Top salary in adapter is 83000 (Row 2, F2)
    assert fake_adapter._grid["F2"]["value"] == 83000


@pytest.mark.asyncio
async def test_filter_rows_e2e(fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete inactive rows end-to-end with approval and row cleanup."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="filter_rows",
                    explanation="Delete rows where Status is Inactive",
                )
            )
        if issubclass(schema, FilterRowsParams):
            return StructuredResult(
                value=FilterRowsParams(
                    condition=Condition(column="Status", operator="equals", value="Inactive"),
                    action="delete_matching",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_t2_filter", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_t2_filter",
        "user_message": "delete rows where Status is Inactive",
        "retries": 0,
        "validation_errors": [],
    }

    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            break

    # Resume with approval
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is True
    assert "(10 -> 7 rows)" in final_state.values.get("result_summary", "")

    # Vacated rows 9, 10, 11 (Excel rows 10, 11) must be cleared
    assert fake_adapter._grid["A10"]["value"] is None
    assert fake_adapter._grid["A11"]["value"] is None


@pytest.mark.asyncio
async def test_highlight_cells_e2e(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Highlight inactive rows in red end-to-end with approval."""

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="highlight_cells",
                    explanation="Highlight Inactive rows in red",
                )
            )
        if issubclass(schema, HighlightCellsParams):
            return StructuredResult(
                value=HighlightCellsParams(
                    condition=Condition(column="Status", operator="equals", value="Inactive"),
                    color="red",
                    whole_row=True,
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_t2_highlight", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_t2_highlight",
        "user_message": "highlight Inactive rows in red",
        "retries": 0,
        "validation_errors": [],
    }

    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            break

    # Resume with approval
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is True

    # Carlos Mendez is in row 4, Inactive -> A4 to J4 should have fill #FFC7CE
    assert fake_adapter._grid["A4"]["fill"] == "#FFC7CE"
    assert fake_adapter._grid["I4"]["fill"] == "#FFC7CE"


@pytest.mark.asyncio
async def test_merged_cells_refusal_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural operation on a sheet with merged cells refuses and routes to finish_error."""
    adapter = FakeAdapter(file_path=FIXTURE_PATH, has_merged_cells=True)

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="sort_rows",
                    explanation="Sort rows by Salary highest first",
                )
            )
        if issubclass(schema, SortRowsParams):
            return StructuredResult(
                value=SortRowsParams(
                    by_column="Salary",
                    descending=True,
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_t2_merged", "adapter": adapter}}

    initial_state = {
        "thread_id": "test_t2_merged",
        "user_message": "sort by Salary highest first",
        "retries": 0,
        "validation_errors": [],
    }

    async for _ in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is False
    assert final_state.values.get("error") is not None
    assert "merged cells" in final_state.values.get("error", "").lower()


@pytest.mark.asyncio
async def test_formula_retry_on_invalid_function_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake LLM first returns unknown function =D2*XYZ(E2), retries, then =D2*E2 -> success."""
    sales_fixture = Path(__file__).resolve().parent.parent / "fixtures" / "sales.xlsx"
    fake_adapter = FakeAdapter(file_path=sales_fixture)

    call_count = 0

    async def fake_call(
        schema: type[Any], system_prompt: str, user_prompt: str
    ) -> StructuredResult[Any]:
        nonlocal call_count
        if "DynamicIntentChoice" in schema.__name__:
            return StructuredResult(
                value=schema(
                    op="add_formula_column",
                    explanation="Add a Total column multiplying Qty by Unit Price",
                )
            )
        if issubclass(schema, AddFormulaColumnParams):
            call_count += 1
            if call_count == 1:
                # First attempt: invalid function XYZ
                return StructuredResult(
                    value=AddFormulaColumnParams(
                        new_header="Total",
                        formula="=D2*XYZ(E2)",
                    )
                )
            # Second attempt: valid formula
            return StructuredResult(
                value=AddFormulaColumnParams(
                    new_header="Total",
                    formula="=D2*E2",
                )
            )
        raise ValueError(f"Unexpected schema: {schema}")

    monkeypatch.setattr("backend.agent.nodes.structured_call", fake_call)

    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_formula_retry", "adapter": fake_adapter}}

    initial_state = {
        "thread_id": "test_formula_retry",
        "user_message": "add a Total column = Qty x Unit Price",
        "retries": 0,
        "validation_errors": [],
    }

    # Initial stream until interrupt (preview)
    preview_seen = False
    async for chunk in graph.astream(initial_state, config=cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            preview_seen = True
            break
    assert preview_seen
    assert call_count == 2  # Verify retry occurred!

    # Resume with approval
    async for _ in graph.astream(
        Command(resume={"approved": True}), config=cfg, stream_mode="updates"
    ):
        pass

    final_state = await graph.aget_state(cfg)
    assert final_state.values.get("applied") is True
    assert final_state.values.get("error") is None

    # Check fake_adapter grid
    assert fake_adapter._grid["K1"]["value"] == "Total"
    assert fake_adapter._grid["K2"]["formula"] == "=D2*E2"
    assert fake_adapter._grid["K11"]["formula"] == "=D11*E11"

