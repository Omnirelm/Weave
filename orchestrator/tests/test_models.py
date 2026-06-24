import pytest
from fastapi.testclient import TestClient

def test_models_returns_supported_list(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.main import create_app

    client = TestClient(create_app())
    response = client.get("/models")
    assert response.status_code == 200
    body = response.json()
    
    # Check pagination structure
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "size" in body
    assert "total_pages" in body
    
    # Check returned models
    items = body["items"]
    assert len(items) > 0
    
    # Verify we got the specific models we added
    model_ids = {m["id"] for m in items}
    assert "gemini/gemini-3.5-flash" in model_ids
    assert "openai/gpt-5.5" in model_ids
    assert "anthropic/claude-3-5-sonnet" in model_ids
