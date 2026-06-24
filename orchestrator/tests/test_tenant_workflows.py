"""Tests for tenant_workflows persistence, routes, and quota."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.responses import JSONResponse

from src.api.middleware.auth_quota import AuthQuotaMiddleware
from src.api.models.schemas import WorkflowEdgeResource, WorkflowNodeResource, WorkflowResource
from src.api.routes import workflows as workflows_routes
from src.security.quota_ops import PERIOD_NONE


def _minimal_workflow_resource(*, agent_id: str = "log_analysis") -> WorkflowResource:
    return WorkflowResource(
        id="wf_test",
        name="Test Workflow",
        description="desc",
        nodes=[
            WorkflowNodeResource(
                id="analyze",
                type="agent",
                agent_id=agent_id,
                objective="analyze",
            ),
        ],
        edges=[
            WorkflowEdgeResource(
                from_node="START",
                to_nodes=["analyze"],
            ),
        ],
    )


class _FakeTenantWorkflowRow:
    __slots__ = ("workflow_id", "definition")

    def __init__(self, workflow_id: str, definition: dict) -> None:
        self.workflow_id = workflow_id
        self.definition = definition


class _FakeTenantAgentRow:
    __slots__ = ("agent_id", "definition")

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.definition = {"id": agent_id}


def _storage_with_tenant(
    *,
    workflow_row: _FakeTenantWorkflowRow | None = None,
    list_rows: list[_FakeTenantWorkflowRow] | None = None,
    count: int = 0,
    agent_exists: bool = True,
) -> MagicMock:
    st = MagicMock()
    st.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    st.tenant_workflows = MagicMock(
        get_for_tenant=AsyncMock(return_value=workflow_row),
        list_for_tenant=AsyncMock(return_value=list_rows or []),
        count_for_tenant=AsyncMock(return_value=count),
        upsert_for_tenant=AsyncMock(
            side_effect=lambda slug, payload: _FakeTenantWorkflowRow(
                payload["workflow_id"], payload["definition"]
            )
        ),
        delete_for_tenant=AsyncMock(return_value=True),
    )
    agent_row = _FakeTenantAgentRow("log_analysis") if agent_exists else None
    st.tenant_agents = MagicMock(get_for_tenant=AsyncMock(return_value=agent_row))
    return st


@pytest.mark.asyncio
async def test_list_workflows_empty_for_tenant() -> None:
    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    out = await workflows_routes.list_workflows("default", request)
    assert out == []
    storage.tenant_workflows.list_for_tenant.assert_awaited_once_with("default")


@pytest.mark.asyncio
async def test_get_workflow_404_when_missing() -> None:
    storage = _storage_with_tenant(workflow_row=None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))

    with pytest.raises(HTTPException) as ei:
        await workflows_routes.get_workflow("missing", "default", request)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_save_workflow_upsert_roundtrip() -> None:
    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    body = _minimal_workflow_resource()
    saved = await workflows_routes.save_workflow(body, "default", request)
    assert saved.id == "wf_test"
    assert saved.name == "Test Workflow"
    storage.tenant_workflows.upsert_for_tenant.assert_awaited()
    call_args = storage.tenant_workflows.upsert_for_tenant.await_args
    assert call_args[0][0] == "default"
    payload = call_args[0][1]
    assert payload["workflow_id"] == "wf_test"
    assert payload["definition"]["id"] == "wf_test"


@pytest.mark.asyncio
async def test_save_workflow_rejects_unknown_agent_id() -> None:
    storage = _storage_with_tenant(agent_exists=False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    body = _minimal_workflow_resource(agent_id="nope")

    with pytest.raises(HTTPException) as ei:
        await workflows_routes.save_workflow(body, "default", request)
    assert ei.value.status_code == 400
    assert "nope" in ei.value.detail


@pytest.mark.asyncio
async def test_save_workflow_rejects_dangling_edge() -> None:
    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    body = WorkflowResource(
        id="bad",
        name="Bad",
        description="d",
        nodes=[
            WorkflowNodeResource(id="a", type="agent", agent_id="log_analysis"),
        ],
        edges=[
            WorkflowEdgeResource(from_node="START", to_nodes=["missing"]),
        ],
    )

    with pytest.raises(HTTPException) as ei:
        await workflows_routes.save_workflow(body, "default", request)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_workflow_max_cap_returns_429_at_limit() -> None:
    mw = AuthQuotaMiddleware(
        app=lambda _r: JSONResponse({}),
        quota_route_table=[],
        public_route_pairs=frozenset(),
    )
    tenant = object()
    pq = SimpleNamespace(limit_value=5, period=PERIOD_NONE)

    storage = MagicMock()
    storage.quota_usage.get_tenant_and_plan_quota = AsyncMock(return_value=(tenant, pq))
    storage.tenant_workflows.count_for_tenant = AsyncMock(return_value=5)

    err = await mw._workflow_max_cap(storage, "acme", "workflow_max")  # noqa: SLF001
    assert isinstance(err, JSONResponse)
    assert err.status_code == 429


@pytest.mark.asyncio
async def test_workflow_max_cap_allows_below_limit() -> None:
    mw = AuthQuotaMiddleware(
        app=lambda _r: JSONResponse({}),
        quota_route_table=[],
        public_route_pairs=frozenset(),
    )
    tenant = object()
    pq = SimpleNamespace(limit_value=50, period=PERIOD_NONE)

    storage = MagicMock()
    storage.quota_usage.get_tenant_and_plan_quota = AsyncMock(return_value=(tenant, pq))
    storage.tenant_workflows.count_for_tenant = AsyncMock(return_value=2)

    err = await mw._workflow_max_cap(storage, "acme", "workflow_max")  # noqa: SLF001
    assert err is None
