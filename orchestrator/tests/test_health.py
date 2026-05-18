import pytest
from fastapi.testclient import TestClient

def test_health_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ORCHESTRATOR_MCP__GITHUB__HEADERS__Authorization",
        "Bearer test",
    )
    from src.main import create_app

    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "orchestrator"
