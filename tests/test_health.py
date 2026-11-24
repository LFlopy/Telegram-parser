"""Tests for the system endpoints and frontend fallback."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["name"] == "Telegram Manager"
    assert body["version"] == "0.1.0"


def test_unknown_api_returns_404(client: TestClient) -> None:
    resp = client.get("/api/nope")
    assert resp.status_code == 404


def test_spa_fallback(tmp_path: Path) -> None:
    index_file = tmp_path / "index.html"
    index_file.write_text("<main>Telegram Manager</main>", encoding="utf-8")
    app = create_app(frontend_dist=tmp_path)

    with TestClient(app) as spa_client:
        root = spa_client.get("/")
        nested = spa_client.get("/tasks/example")
        api_root = spa_client.get("/api")

    assert root.status_code == 200
    assert nested.status_code == 200
    assert "Telegram Manager" in nested.text
    assert api_root.status_code == 404
