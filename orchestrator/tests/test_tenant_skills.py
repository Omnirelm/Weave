"""Tests for tenant_skills persistence, routes, quota, and task planner integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.responses import JSONResponse

from src.api.middleware.auth_quota import AuthQuotaMiddleware
from src.api.routes import skills as skills_routes
from src.api.routes import tasks as tasks_routes
from src.api.translators.tasks import RunTaskRequestDomain
from src.core.base import InvocationCost
from src.security.quota_ops import PERIOD_NONE


def _minimal_skill_def_dict(skill_id: str = "my_skill", *, input_schema: dict | None = None) -> dict:
    return {
        "id": skill_id,
        "name": "My Skill",
        "description": "desc",
        "instructions": "Do the thing.",
        "kind": "simple",
        "capabilities": [],
        "mcp_servers": [],
        "steps": [],
        "model": "gpt-4.1",
        "input_schema": input_schema,
        "output_schema": None,
    }


class _FakeTenantSkillRow:
    __slots__ = ("skill_id", "definition")

    def __init__(self, skill_id: str, definition: dict) -> None:
        self.skill_id = skill_id
        self.definition = definition


def _storage_with_tenant(
    *,
    skill_row: _FakeTenantSkillRow | None = None,
    list_rows: list[_FakeTenantSkillRow] | None = None,
    count: int = 0,
) -> MagicMock:
    st = MagicMock()
    st.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    st.tenant_skills = MagicMock(
        get_for_tenant=AsyncMock(return_value=skill_row),
        list_for_tenant=AsyncMock(return_value=list_rows or []),
        count_for_tenant=AsyncMock(return_value=count),
        upsert_for_tenant=AsyncMock(
            side_effect=lambda slug, payload: _FakeTenantSkillRow(
                payload["skill_id"], payload["definition"]
            )
        ),
        delete_for_tenant=AsyncMock(return_value=True),
    )
    return st


@pytest.mark.asyncio
async def test_list_skills_empty_for_tenant() -> None:
    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    out = await skills_routes.list_skills("default", request)
    assert out == []
    storage.tenants.get_by_slug.assert_awaited_once_with("default")
    storage.tenant_skills.list_for_tenant.assert_awaited_once_with("default")


@pytest.mark.asyncio
async def test_get_skill_404_when_missing() -> None:
    storage = _storage_with_tenant(skill_row=None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))

    with pytest.raises(HTTPException) as ei:
        await skills_routes.get_skill("missing", "default", request)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_save_skill_upsert_roundtrip() -> None:
    from src.api.models.schemas import SkillResource

    storage = _storage_with_tenant()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    body = SkillResource(
        id="s1",
        name="S1",
        description="d",
        instructions="inst",
        kind="simple",
    )
    saved = await skills_routes.save_skill(body, "default", request)
    assert saved.id == "s1"
    assert saved.name == "S1"
    storage.tenant_skills.upsert_for_tenant.assert_awaited()
    call_kw = storage.tenant_skills.upsert_for_tenant.await_args
    assert call_kw[0][0] == "default"
    payload = call_kw[0][1]
    assert payload["skill_id"] == "s1"
    assert payload["kind"] == "simple"
    assert payload["definition"]["id"] == "s1"


@pytest.mark.asyncio
async def test_save_skill_rejects_composed_step_targeting_composed_skill() -> None:
    from src.api.models.schemas import SkillResource, SkillStepResource

    inner_composed = {
        "id": "inner_comp",
        "name": "Inner",
        "description": "d",
        "instructions": "i",
        "kind": "composed",
        "capabilities": [],
        "mcp_servers": [],
        "steps": [
            {
                "id": "s1",
                "type": "synthesize",
                "objective": "noop",
            }
        ],
        "model": "gpt-4.1",
        "input_schema": None,
        "output_schema": None,
    }

    async def get_for_tenant(_slug: str, skill_id: str) -> _FakeTenantSkillRow | None:
        if skill_id == "inner_comp":
            return _FakeTenantSkillRow("inner_comp", inner_composed)
        return None

    storage = _storage_with_tenant()
    storage.tenant_skills.get_for_tenant = AsyncMock(side_effect=get_for_tenant)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    body = SkillResource(
        id="outer_comp",
        name="Outer",
        description="d",
        instructions="outer",
        kind="composed",
        steps=[
            SkillStepResource(
                id="step1",
                type="invoke_skill",
                skill_id="inner_comp",
                objective="must not invoke composed",
            ),
        ],
    )
    with pytest.raises(HTTPException) as ei:
        await skills_routes.save_skill(body, "default", request)
    assert ei.value.status_code == 400
    assert "composed" in ei.value.detail.lower()
    storage.tenant_skills.upsert_for_tenant.assert_not_called()


@pytest.mark.asyncio
async def test_skill_max_cap_returns_429_at_limit() -> None:
    mw = AuthQuotaMiddleware(
        app=lambda _r: JSONResponse({}),
        quota_route_table=[],
        public_route_pairs=frozenset(),
    )
    tenant = object()
    pq = SimpleNamespace(limit_value=3, period=PERIOD_NONE)

    storage = MagicMock()
    storage.quota_usage.get_tenant_and_plan_quota = AsyncMock(return_value=(tenant, pq))
    storage.tenant_skills.count_for_tenant = AsyncMock(return_value=3)

    err = await mw._skill_max_cap(storage, "acme", "skill_max")  # noqa: SLF001
    assert isinstance(err, JSONResponse)
    assert err.status_code == 429


@pytest.mark.asyncio
async def test_skill_max_cap_allows_below_limit() -> None:
    mw = AuthQuotaMiddleware(
        app=lambda _r: JSONResponse({}),
        quota_route_table=[],
        public_route_pairs=frozenset(),
    )
    tenant = object()
    pq = SimpleNamespace(limit_value=10, period=PERIOD_NONE)

    storage = MagicMock()
    storage.quota_usage.get_tenant_and_plan_quota = AsyncMock(return_value=(tenant, pq))
    storage.tenant_skills.count_for_tenant = AsyncMock(return_value=2)

    err = await mw._skill_max_cap(storage, "acme", "skill_max")  # noqa: SLF001
    assert err is None


@pytest.mark.asyncio
async def test_run_planner_uses_db_skills_list(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeRunResult:
        def final_output_as(
            self, _model: type[tasks_routes.ExecutionPlan], _strict: bool
        ) -> tasks_routes.ExecutionPlan:
            return tasks_routes.ExecutionPlan(steps=[], reasoning="ok")

    async def fake_runner_run(*, starting_agent: object, input: str) -> _FakeRunResult:
        del starting_agent
        captured["payload"] = __import__("json").loads(input)
        return _FakeRunResult()

    monkeypatch.setattr(tasks_routes.Runner, "run", staticmethod(fake_runner_run))
    monkeypatch.setattr(
        tasks_routes,
        "extract_runner_cost",
        lambda *_: InvocationCost(label="planner", total_tokens=0),
    )
    monkeypatch.setattr(tasks_routes, "get_agent_instructions", lambda _k: "instructions")
    monkeypatch.setattr(tasks_routes, "get_agent_model", lambda _k: "gpt-5-mini")
    monkeypatch.setattr(tasks_routes, "get_agent_name", lambda _k: "planner")

    row = _FakeTenantSkillRow("skill_a", _minimal_skill_def_dict("skill_a"))
    storage = MagicMock()
    storage.tenant_skills = MagicMock(list_for_tenant=AsyncMock(return_value=[row]))

    async def _empty_descriptors(_tid: str) -> list:
        return []

    runner = SimpleNamespace(list_tool_descriptors=_empty_descriptors)
    task = RunTaskRequestDomain(
        task="investigate",
        tenant_id="default",
        skill_id="hint",
        input={"alert_id": "a-1"},
    )

    await tasks_routes._run_planner(
        task=task,
        storage=storage,
        runner=runner,
        completed_steps=[],
        replan_reason=None,
    )

    avail = captured["payload"]["availableSkills"]
    assert len(avail) == 1
    assert avail[0]["id"] == "skill_a"
    storage.tenant_skills.list_for_tenant.assert_awaited_once_with("default")


@pytest.mark.asyncio
async def test_run_task_unknown_skill_uses_storage_404() -> None:
    storage = _storage_with_tenant(skill_row=None)
    runner = MagicMock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage, skill_runner=runner)))
    body = tasks_routes.RunTaskRequest(
        objective="x",
        slug="default",
        skill_id="nope",
        input={},
    )
    with pytest.raises(HTTPException) as ei:
        await tasks_routes.run_task(body, request)
    assert ei.value.status_code == 404
