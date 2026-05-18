"""Tests for auth/quota helpers and middleware allowlist behaviour."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.middleware.auth_quota import (
    _is_public_route,
    _path_tenant_slug,
    compile_public_route_pairs,
)
from src.config.settings import load_config
from src.security import hash_api_key


@pytest.fixture
def public_pairs() -> frozenset[tuple[str, str]]:
    return compile_public_route_pairs(load_config().auth)


def test_public_routes_health_and_tenant_create(public_pairs: frozenset[tuple[str, str]]) -> None:
    assert _is_public_route("GET", "/health", public_pairs) is True
    assert _is_public_route("OPTIONS", "/any", public_pairs) is True
    assert _is_public_route("POST", "/tenants", public_pairs) is True
    assert _is_public_route("GET", "/tasks/run", public_pairs) is False


def test_path_tenant_slug() -> None:
    assert _path_tenant_slug("/tenants/acme/skills") == "acme"
    assert _path_tenant_slug("/tasks/run") is None


def test_extract_api_secret_bearer_and_header() -> None:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer secret-token")],
        "client": ("127.0.0.1", 123),
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
    }

    from src.api.middleware.auth_quota import _extract_api_secret

    req = Request(scope)
    assert _extract_api_secret(req) == "secret-token"

    scope2 = dict(scope)
    scope2["headers"] = [(b"x-api-key", b"abc")]
    assert _extract_api_secret(Request(scope2)) == "abc"


def test_hash_api_key_stable() -> None:
    h = hash_api_key("my-secret", "pepper")
    assert len(h) == 64
    assert h == hash_api_key("my-secret", "pepper")
    assert h != hash_api_key("other", "pepper")


@pytest.mark.asyncio
async def test_middleware_auth_disabled_skips_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_AUTH__DISABLED", "true")
    from src.config.settings import get_config

    get_config.cache_clear()
    try:
        from unittest.mock import AsyncMock, MagicMock

        import src.main as main_mod

        async def fake_wire(app: object) -> None:
            storage = MagicMock()
            storage.tenants.get_by_slug = AsyncMock(return_value=SimpleNamespace(slug="foo"))
            storage.tenant_skills.list_for_tenant = AsyncMock(return_value=[])
            storage.db.dispose = AsyncMock()
            app.state.storage = storage  # type: ignore[attr-defined]
            app.state.tool_provider = MagicMock()
            app.state.mcp_provider = MagicMock()
            app.state.skill_registry = MagicMock()
            app.state.skill_runner = MagicMock()

        monkeypatch.setattr(main_mod, "wire_application", fake_wire)

        from src.main import create_app

        TestClient = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient
        with TestClient(create_app()) as client:
            r = client.get("/tenants/foo/skills")
        assert r.status_code in (200, 500)
    finally:
        get_config.cache_clear()


@pytest.mark.asyncio
async def test_middleware_missing_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_AUTH__DISABLED", "false")
    monkeypatch.delenv("ORCHESTRATOR_AUTH__QUOTA_DISABLED", raising=False)
    from src.config.settings import get_config

    get_config.cache_clear()
    try:
        from unittest.mock import AsyncMock, MagicMock

        import src.main as main_mod

        async def fake_wire(app: object) -> None:
            storage = MagicMock()
            storage.tenants.get_by_slug = AsyncMock(return_value=SimpleNamespace(slug="foo"))
            storage.tenant_skills.list_for_tenant = AsyncMock(return_value=[])
            storage.db.dispose = AsyncMock()
            app.state.storage = storage  # type: ignore[attr-defined]
            app.state.tool_provider = MagicMock()
            app.state.mcp_provider = MagicMock()
            app.state.skill_registry = MagicMock()
            app.state.skill_runner = MagicMock()

        monkeypatch.setattr(main_mod, "wire_application", fake_wire)

        from src.main import create_app

        TestClient = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient
        with TestClient(create_app()) as client:
            r = client.get("/tenants/foo/skills")
        assert r.status_code == 401
        assert r.json()["detail"] == "Missing API key"
    finally:
        get_config.cache_clear()
