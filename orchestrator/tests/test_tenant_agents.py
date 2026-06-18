"""Tests for tenant_agents persistence, routes, and quota."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.responses import JSONResponse

from src.api.middleware.auth_quota import AuthQuotaMiddleware
from src.api.models.schemas import RunTaskRequest
from src.api.routes import agents as agents_routes
from src.api.routes import tasks as tasks_routes
from src.security.quota_ops import PERIOD_NONE


def _minimal_agent_def_dict(agent_id: str = "my_agent") -> dict:
    return {
        "id": agent_id,
        "name": "My Agent",
        "description": "desc",
        "instructions": "Do the thing.",
        "tools": [],
        "mcp_servers": [],
        "model": "gpt-4.1",
    }


class _FakeTenantAgentRow:
    __slots__ = ("agent_id", "definition")

    def __init__(self, agent_id: str, definition: dict) -> None:
        self.agent_id = agent_id
        self.definition = definition


def _storage_with_tenant(
    *,
    agent_row: _FakeTenantAgentRow | None = None,
    list_rows: list[_FakeTenantAgentRow] | None = None,
    count: int = 0,
) -> MagicMock:
    st = MagicMock()
    st.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    st.tenant_agents = MagicMock(
        get_for_tenant=AsyncMock(return_value=agent_row),
        list_for_tenant=AsyncMock(return_value=list_rows or []),
        count_for_tenant=AsyncMock(return_value=count),
        upsert_for_tenant=AsyncMock(
            side_effect=lambda slug, payload: _FakeTenantAgentRow(
                payload["agent_id"], payload["definition"]
            )
        ),
        delete_for_tenant=AsyncMock(return_value=True),
    )
    st.task_runs = MagicMock(create=AsyncMock(return_value=SimpleNamespace()))
    return st


@pytest.mark.asyncio
async def test_list_agents_empty_for_tenant() -> None:
    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    out = await agents_routes.list_agents("default", request)
    assert out == []
    storage.tenants.get_by_slug.assert_awaited_once_with("default")
    storage.tenant_agents.list_for_tenant.assert_awaited_once_with("default")


@pytest.mark.asyncio
async def test_get_agent_404_when_missing() -> None:
    storage = _storage_with_tenant(agent_row=None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))

    with pytest.raises(HTTPException) as ei:
        await agents_routes.get_agent("missing", "default", request)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_save_agent_upsert_roundtrip() -> None:
    from src.api.models.schemas import AgentResource

    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    body = AgentResource(
        id="a1",
        name="A1",
        description="d",
        instructions="inst",
    )
    saved = await agents_routes.save_agent(body, "default", request)
    assert saved.id == "a1"
    assert saved.name == "A1"
    storage.tenant_agents.upsert_for_tenant.assert_awaited()
    call_kw = storage.tenant_agents.upsert_for_tenant.await_args
    assert call_kw[0][0] == "default"
    payload = call_kw[0][1]
    assert payload["agent_id"] == "a1"
    assert payload["definition"]["id"] == "a1"


@pytest.mark.asyncio
async def test_agent_max_cap_returns_429_at_limit() -> None:
    mw = AuthQuotaMiddleware(
        app=lambda _r: JSONResponse({}),
        quota_route_table=[],
        public_route_pairs=frozenset(),
    )
    tenant = object()
    pq = SimpleNamespace(limit_value=3, period=PERIOD_NONE)

    storage = MagicMock()
    storage.quota_usage.get_tenant_and_plan_quota = AsyncMock(return_value=(tenant, pq))
    storage.tenant_agents.count_for_tenant = AsyncMock(return_value=3)

    err = await mw._agent_max_cap(storage, "acme", "agent_max")  # noqa: SLF001
    assert isinstance(err, JSONResponse)
    assert err.status_code == 429


@pytest.mark.asyncio
async def test_agent_max_cap_allows_below_limit() -> None:
    mw = AuthQuotaMiddleware(
        app=lambda _r: JSONResponse({}),
        quota_route_table=[],
        public_route_pairs=frozenset(),
    )
    tenant = object()
    pq = SimpleNamespace(limit_value=10, period=PERIOD_NONE)

    storage = MagicMock()
    storage.quota_usage.get_tenant_and_plan_quota = AsyncMock(return_value=(tenant, pq))
    storage.tenant_agents.count_for_tenant = AsyncMock(return_value=2)

    err = await mw._agent_max_cap(storage, "acme", "agent_max")  # noqa: SLF001
    assert err is None


@pytest.mark.asyncio
async def test_run_task_unknown_agent_uses_storage_404() -> None:
    storage = _storage_with_tenant(agent_row=None)
    runner = MagicMock()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                storage=storage,
                agent_runner=runner,
                workflow_runner=MagicMock(),
            )
        )
    )
    body = RunTaskRequest(
        objective="x",
        slug="default",
        agent_id="nope",
    )
    with pytest.raises(HTTPException) as ei:
        await tasks_routes.run_task(body.slug, body, request)
    assert ei.value.status_code == 404
