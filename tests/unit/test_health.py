"""Unit tests for the /api/health endpoint and frontend root."""

import httpx
import pytest
from starlette.testclient import TestClient


def test_health_reachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test health endpoint when llama-server is reachable."""

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "mock-qwen-model"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    assert data["backend"] == "ok"
    assert "machine" in data
    assert data["llm"]["reachable"] is True
    assert data["llm"]["model"] == "mock-qwen-model"
    assert data["llm"]["error"] is None


def test_health_unreachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test health endpoint when llama-server is unreachable."""

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("Connection refused to llama-server")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    assert data["backend"] == "ok"
    assert "machine" in data
    assert data["llm"]["reachable"] is False
    assert data["llm"]["model"] is None
    assert data["llm"]["error"] is not None
    assert "ConnectError" in data["llm"]["error"]


def test_health_json_shape(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the exact JSON response shape of /api/health."""

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "test-model"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    assert set(data.keys()) == {"backend", "machine", "llm"}
    assert set(data["llm"].keys()) == {"reachable", "model", "error"}
    assert isinstance(data["backend"], str)
    assert isinstance(data["machine"], str)
    assert isinstance(data["llm"]["reachable"], bool)


def test_root_serves_frontend(client: TestClient) -> None:
    """Test that GET / serves the placeholder frontend index.html."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Excel AI" in response.text

