"""Pytest fixtures for Excel AI tests."""

from collections.abc import Generator

import pytest
from starlette.testclient import TestClient

from backend.main import create_app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient fixture with lifespan events executed."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
