"""Integration tests for the chat and undo SSE API endpoints."""

import json
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from starlette.testclient import TestClient

from backend.agent.graph import build_graph
from backend.excel.fake_adapter import FakeAdapter
from backend.llm.client import StructuredResult
from backend.main import create_app
from backend.schemas.intent import ConvertCaseStyleParams, Target
from scripts.chat_cli import parse_sse_stream

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "employees.xlsx"


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    """Create a FakeAdapter preloaded with employees.xlsx."""
    return FakeAdapter(file_path=FIXTURE_PATH)


@pytest.fixture
def test_client(
    fake_adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Any:
    """Create TestClient with FakeAdapter, isolated SQLite DB, and in-memory graph."""
    test_db = tmp_path / "test_api_app.sqlite"
    monkeypatch.setattr(
        "backend.storage.db.get_db_path",
        lambda custom_path=None: test_db if custom_path is None else Path(custom_path),
    )

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

    app = create_app()
    app.state.adapter = fake_adapter
    app.state.graph = build_graph(InMemorySaver())

    with TestClient(app) as client:
        yield client


def test_chat_confirm_and_undo_pipeline(
    test_client: TestClient, fake_adapter: FakeAdapter
) -> None:
    """End-to-end API pipeline: chat -> preview -> confirm -> Excel updated -> undo restored."""
    # 1. Start chat
    response = test_client.post(
        "/api/chat",
        json={"message": "convert the column headers to camelCase"},
    )
    assert response.status_code == 200

    events = list(parse_sse_stream(response.iter_lines()))
    event_names = [e[0] for e in events]

    assert "status" in event_names
    assert "plan" in event_names
    assert "preview" in event_names

    # Check plan event payload
    plan_raw = next(data for ev, data in events if ev == "plan")
    plan_data = json.loads(plan_raw)
    assert plan_data["op"] == "convert_case_style"
    assert "camelCase" in plan_data["explanation"]

    # Check preview event payload
    preview_raw = next(data for ev, data in events if ev == "preview")
    preview_data = json.loads(preview_raw)
    thread_id = preview_data["thread_id"]
    assert thread_id
    assert len(preview_data["changes"]) > 0

    # 2. Confirm changes
    conf_response = test_client.post(
        "/api/confirm",
        json={"thread_id": thread_id, "approved": True},
    )
    assert conf_response.status_code == 200

    conf_events = list(parse_sse_stream(conf_response.iter_lines()))
    conf_names = [e[0] for e in conf_events]

    assert "done" in conf_names
    done_raw = next(data for ev, data in conf_events if ev == "done")
    done_data = json.loads(done_raw)
    assert done_data["applied"] is True

    # Verify FakeAdapter has camelCase headers
    assert fake_adapter._grid["A1"]["value"] == "empId"
    assert fake_adapter._grid["B1"]["value"] == "fullName"

    # 3. Undo changes
    undo_resp = test_client.post("/api/undo")
    assert undo_resp.status_code == 200
    undo_data = undo_resp.json()
    assert undo_data["restored"] is True

    # Verify original headers restored
    assert fake_adapter._grid["A1"]["value"] == "Emp ID"
    assert fake_adapter._grid["B1"]["value"] == "Full Name"

    # 4. Check undo history
    hist_resp = test_client.get("/api/undo/history")
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert isinstance(history, list)


def test_chat_confirm_rejected(
    test_client: TestClient, fake_adapter: FakeAdapter
) -> None:
    """Chat pipeline where user rejects changes at preview."""
    response = test_client.post(
        "/api/chat",
        json={"message": "convert the column headers to camelCase"},
    )
    assert response.status_code == 200

    events = list(parse_sse_stream(response.iter_lines()))
    preview_raw = next(data for ev, data in events if ev == "preview")
    preview_data = json.loads(preview_raw)
    thread_id = preview_data["thread_id"]

    # Reject
    conf_response = test_client.post(
        "/api/confirm",
        json={"thread_id": thread_id, "approved": False},
    )
    assert conf_response.status_code == 200

    conf_events = list(parse_sse_stream(conf_response.iter_lines()))
    done_raw = next(data for ev, data in conf_events if ev == "done")
    done_data = json.loads(done_raw)
    assert done_data["applied"] is False
    assert done_data["summary"] == "Operation cancelled"

    # Original headers unchanged
    assert fake_adapter._grid["A1"]["value"] == "Emp ID"


def test_undo_when_empty(test_client: TestClient) -> None:
    """Calling undo when no snapshots exist returns restored: False."""
    undo_resp = test_client.post("/api/undo")
    assert undo_resp.status_code == 200
    data = undo_resp.json()
    assert data["restored"] is False
    assert "No changes to undo" in data["summary"]

