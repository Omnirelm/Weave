from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.api.routes import tasks
from src.api.translators.tasks import RunTaskRequestDomain
from src.core.base import InvocationCost
from src.core.skills import SkillResult, StepResult

_DEFAULT_SKILL_ROW = object()


def _log_analysis_skill_row(*, require_logs: bool) -> SimpleNamespace:
    schema = None
    if require_logs:
        schema = {
            "type": "object",
            "required": ["logs"],
            "properties": {"logs": {"type": "array"}},
        }
    definition = {
        "id": "log_analysis",
        "name": "Log analysis",
        "description": "d",
        "instructions": "Analyze logs.",
        "kind": "simple",
        "capabilities": [],
        "mcp_servers": [],
        "steps": [],
        "model": "gpt-4.1",
        "input_schema": schema,
        "output_schema": None,
    }
    return SimpleNamespace(skill_id="log_analysis", definition=definition)


class _DummyRunner:
    def __init__(self, skill_result: SkillResult) -> None:
        self._skill_result = skill_result
        self.calls: list[tuple[str, dict, str]] = []

    async def list_tool_descriptors(self, tenant_id: str) -> list:
        del tenant_id
        return []

    async def run_skill(
        self,
        skill_id: str,
        input_payload: dict,
        tenant_id: str,
        *,
        _depth: int = 0,
    ) -> SkillResult:
        del _depth
        self.calls.append((skill_id, input_payload, tenant_id))
        return self._skill_result


def _request_with_runner(
    runner: _DummyRunner,
    *,
    skill_row: SimpleNamespace | None | object = _DEFAULT_SKILL_ROW,
) -> SimpleNamespace:
    """Build request.app.state with storage + runner.

    skill_row:
      - default: return log_analysis row without input schema (any input passes validation)
      - None: get_for_tenant always returns None
      - SimpleNamespace: always return this row for get_for_tenant
    """
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))

    if skill_row is None:
        storage.tenant_skills = MagicMock(
            get_for_tenant=AsyncMock(return_value=None),
            list_for_tenant=AsyncMock(return_value=[]),
        )
    elif skill_row is _DEFAULT_SKILL_ROW:
        row = _log_analysis_skill_row(require_logs=False)
        storage.tenant_skills = MagicMock(
            get_for_tenant=AsyncMock(return_value=row),
            list_for_tenant=AsyncMock(return_value=[]),
        )
    else:
        assert isinstance(skill_row, SimpleNamespace)
        storage.tenant_skills = MagicMock(
            get_for_tenant=AsyncMock(return_value=skill_row),
            list_for_tenant=AsyncMock(return_value=[]),
        )

    storage.task_runs = MagicMock()
    storage.task_runs.create = AsyncMock(return_value=SimpleNamespace())

    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(skill_runner=runner, storage=storage),
        )
    )


@pytest.mark.asyncio
async def test_run_task_planner_only_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    planner_called = {"value": False}

    async def fake_run_planner(**_: object) -> tuple[tasks.ExecutionPlan, InvocationCost]:
        planner_called["value"] = True
        return (
            tasks.ExecutionPlan(
                steps=[tasks.PlanStep(stepType="synthesize", objective="Summarize")],
                reasoning="plan",
            ),
            InvocationCost(label="planner", total_tokens=5),
        )

    async def fake_execute_plan_step(
        step: tasks.PlanStep,
        step_index: int,
        **_: object,
    ) -> tuple[StepResult, list[InvocationCost]]:
        return (
            StepResult(
                step_id=f"plan_step_{step_index}",
                objective=step.objective,
                success=True,
                output={"ok": True},
                error=None,
            ),
            [],
        )

    monkeypatch.setattr(tasks, "_run_planner", fake_run_planner)
    monkeypatch.setattr(tasks, "_execute_plan_step", fake_execute_plan_step)

    runner = _DummyRunner(SkillResult(success=True, output={"ignored": True}))
    req = _request_with_runner(runner)
    body = tasks.RunTaskRequest(
        objective="do thing",
        slug="default",
    )

    response = await tasks.run_task(body, req)

    assert planner_called["value"] is True
    assert len(runner.calls) == 0
    assert response.success is True
    assert response.output is None
    assert response.task_id is not None
    req.app.state.storage.task_runs.create.assert_awaited_once()
    persisted = req.app.state.storage.task_runs.create.await_args.args[0]
    assert persisted["id"] == response.task_id
    assert persisted["success"] is True
    assert persisted["tenant_slug"] == "default"
    assert persisted["objective"] == "do thing"
    assert persisted["cost"] is not None
    assert len(persisted["steps_completed"]) == 1


@pytest.mark.asyncio
async def test_run_task_direct_skill_success_skips_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner_called = {"value": False}

    async def fake_run_planner(**_: object) -> tuple[tasks.ExecutionPlan, InvocationCost]:
        planner_called["value"] = True
        raise AssertionError("Planner should not run on direct skill success")

    monkeypatch.setattr(tasks, "_run_planner", fake_run_planner)

    runner = _DummyRunner(SkillResult(success=True, output={"direct": True}))
    req = _request_with_runner(runner)
    body = tasks.RunTaskRequest(
        objective="investigate",
        slug="default",
        skill_id="log_analysis",
        input={"logs": [], "alert_id": "a-1"},
    )

    response = await tasks.run_task(body, req)

    assert planner_called["value"] is False
    assert response.success is True
    assert len(response.steps_completed) == 1
    assert response.output == {"direct": True}
    assert response.task_id is not None
    persist = req.app.state.storage.task_runs.create.await_args.args[0]
    assert persist["id"] == response.task_id
    assert persist["success"] is True
    assert persist["steps_completed"][0]["success"] is True
    first_call = runner.calls[0]
    assert first_call[0] == "log_analysis"
    assert first_call[1]["alert_id"] == "a-1"
    assert first_call[1]["objective"] == "investigate"
    assert first_call[2] == "default"


@pytest.mark.asyncio
async def test_run_task_direct_skill_failure_returns_error_without_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner_called = {"value": False}

    async def fake_run_planner(**_: object) -> tuple[tasks.ExecutionPlan, InvocationCost]:
        planner_called["value"] = True
        raise AssertionError("Planner should not run on direct skill failure")

    monkeypatch.setattr(tasks, "_run_planner", fake_run_planner)

    runner = _DummyRunner(SkillResult(success=False, error="boom"))
    req = _request_with_runner(runner)
    body = tasks.RunTaskRequest(
        objective="investigate",
        slug="default",
        skill_id="log_analysis",
        input={"logs": []},
    )

    response = await tasks.run_task(body, req)

    assert planner_called["value"] is False
    assert response.success is False
    assert response.error == "boom"
    assert len(response.steps_completed) == 1
    assert response.steps_completed[0].success is False
    assert response.steps_completed[0].error == "boom"
    assert response.output is None
    persist = req.app.state.storage.task_runs.create.await_args.args[0]
    assert persist["success"] is False
    assert persist["error"] == "boom"


@pytest.mark.asyncio
async def test_run_task_unknown_skill_returns_404() -> None:
    runner = _DummyRunner(SkillResult(success=True, output={}))
    req = _request_with_runner(runner, skill_row=None)
    body = tasks.RunTaskRequest(
        objective="x",
        slug="default",
        skill_id="definitely_missing_skill_id_12345",
        input={},
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks.run_task(body, req)
    assert exc_info.value.status_code == 404
    req.app.state.storage.task_runs.create.assert_not_called()


@pytest.mark.asyncio
async def test_run_task_direct_skill_invalid_input_returns_422() -> None:
    runner = _DummyRunner(SkillResult(success=True, output={}))
    row = _log_analysis_skill_row(require_logs=True)
    req = _request_with_runner(runner, skill_row=row)
    body = tasks.RunTaskRequest(
        objective="investigate",
        slug="default",
        skill_id="log_analysis",
        input={"alert_id": "only-this-no-logs"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks.run_task(body, req)
    assert exc_info.value.status_code == 422
    req.app.state.storage.task_runs.create.assert_not_called()


@pytest.mark.asyncio
async def test_run_planner_includes_skill_hint_and_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeRunResult:
        def final_output_as(
            self, _model: type[tasks.ExecutionPlan], _strict: bool
        ) -> tasks.ExecutionPlan:
            return tasks.ExecutionPlan(steps=[], reasoning="ok")

    async def fake_runner_run(*, starting_agent: object, input: str) -> _FakeRunResult:
        del starting_agent
        captured["payload"] = json.loads(input)
        return _FakeRunResult()

    monkeypatch.setattr(tasks.Runner, "run", staticmethod(fake_runner_run))
    monkeypatch.setattr(
        tasks,
        "extract_runner_cost",
        lambda *_: InvocationCost(label="planner", total_tokens=0),
    )
    monkeypatch.setattr(tasks, "get_agent_instructions", lambda _k: "instructions")
    monkeypatch.setattr(tasks, "get_agent_model", lambda _k: "gpt-5-mini")
    monkeypatch.setattr(tasks, "get_agent_name", lambda _k: "planner")

    storage = MagicMock()
    storage.tenant_skills = MagicMock(list_for_tenant=AsyncMock(return_value=[]))

    async def _empty_descriptors(_tid: str) -> list:
        return []

    runner = SimpleNamespace(list_tool_descriptors=_empty_descriptors)
    task = RunTaskRequestDomain(
        task="investigate",
        tenant_id="default",
        skill_id="log_analysis",
        input={"alert_id": "a-1"},
    )

    await tasks._run_planner(
        task=task,
        storage=storage,
        runner=runner,
        completed_steps=[],
        replan_reason=None,
    )

    planner_task = captured["payload"]["task"]
    assert planner_task["prompt"] == "investigate"
    assert planner_task["tenantId"] == "default"
    assert planner_task["skillId"] == "log_analysis"
    assert planner_task["input"] == {"alert_id": "a-1"}
