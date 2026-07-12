from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from src.api.models.schemas import RunTaskRequest
from src.api.routes import tasks
from src.core.agents import AgentResult

_DEFAULT_AGENT_ROW = object()


def _log_analysis_agent_row() -> SimpleNamespace:
    definition = {
        "id": "log_analysis",
        "name": "Log analysis",
        "description": "d",
        "instructions": "Analyze logs.",
        "tools": [],
        "mcp_servers": [],
        "model": "gpt-4.1",
    }
    return SimpleNamespace(agent_id="log_analysis", definition=definition)


class _DummyRunner:
    def __init__(self, agent_result: AgentResult) -> None:
        self._agent_result = agent_result
        self.calls: list[tuple[str, dict, str]] = []

    async def run_agent(
        self,
        agent_id: str,
        input_payload: dict,
        tenant_id: str,
        task_id: Any = None,
        **kwargs: Any,
    ) -> AgentResult:
        self.calls.append((agent_id, input_payload, tenant_id))
        return self._agent_result


def _request_with_runner(
    runner: _DummyRunner,
    *,
    agent_row: SimpleNamespace | None | object = _DEFAULT_AGENT_ROW,
) -> SimpleNamespace:
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))

    if agent_row is None:
        storage.tenant_agents = MagicMock(get_for_tenant=AsyncMock(return_value=None))
    elif agent_row is _DEFAULT_AGENT_ROW:
        row = _log_analysis_agent_row()
        storage.tenant_agents = MagicMock(get_for_tenant=AsyncMock(return_value=row))
    else:
        assert isinstance(agent_row, SimpleNamespace)
        storage.tenant_agents = MagicMock(get_for_tenant=AsyncMock(return_value=agent_row))

    storage.task_runs = MagicMock()
    storage.task_runs.create = AsyncMock(return_value=SimpleNamespace())

    workflow_runner = MagicMock()

    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                agent_runner=runner,
                workflow_runner=workflow_runner,
                storage=storage,
            ),
        )
    )


@pytest.mark.asyncio
async def test_run_task_executes_agent() -> None:
    runner = _DummyRunner(AgentResult(success=True, output={"summary": "ok"}))
    req = _request_with_runner(runner)
    body = RunTaskRequest(
        objective="do thing",
        slug="default",
        agent_id="log_analysis",
        context="Logs from checkout:\n```json\n{\"service\":\"checkout\"}\n```",
    )

    response = await tasks.run_task(body.slug, body, req)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "log_analysis"
    assert runner.calls[0][1]["context"] == body.context
    assert runner.calls[0][1]["objective"] == "do thing"
    assert "task" not in runner.calls[0][1]
    assert response.success is True
    assert response.output == {"summary": "ok"}
    assert response.task_id is not None
    req.app.state.storage.task_runs.create.assert_awaited_once()
    persisted = req.app.state.storage.task_runs.create.await_args.args[0]
    assert persisted["id"] == response.task_id
    assert persisted["agent_id"] == "log_analysis"
    assert persisted["request_context"] == body.context
    assert persisted["success"] is True


@pytest.mark.asyncio
async def test_run_task_without_agent_or_workflow_rejected() -> None:
    with pytest.raises(ValidationError, match="workflow_id or agent_id is required"):
        RunTaskRequest(objective="do thing", slug="xcorp")


@pytest.mark.asyncio
async def test_run_task_rejects_both_agent_and_workflow() -> None:
    with pytest.raises(ValidationError, match="not both"):
        RunTaskRequest(
            objective="do thing",
            slug="xcorp",
            agent_id="log_analysis",
            workflow_id="ppl_log_analysis",
        )


@pytest.mark.asyncio
async def test_run_task_accepts_string_context_without_validation() -> None:
    runner = _DummyRunner(AgentResult(success=True, output={}))
    req = _request_with_runner(runner)
    body = RunTaskRequest(
        objective="do thing",
        slug="default",
        agent_id="log_analysis",
        context="free-form context",
    )
    response = await tasks.run_task(body.slug, body, req)
    assert response.success is True
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_run_task_agent_failure_returns_error() -> None:
    runner = _DummyRunner(AgentResult(success=False, error="agent blew up"))
    req = _request_with_runner(runner)
    body = RunTaskRequest(
        objective="do thing",
        slug="default",
        agent_id="log_analysis",
    )
    response = await tasks.run_task(body.slug, body, req)
    assert response.success is False
    assert response.error == "agent blew up"


@pytest.mark.asyncio
async def test_list_runs_returns_runs() -> None:
    req = MagicMock()
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    
    import uuid
    from datetime import datetime, timezone
    run1 = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_slug="default",
        success=True,
        objective="obj1",
        agent_id="agent1",
        workflow_id=None,
        request_context="input1",
        output={"out": "1"},
        summary=None,
        reasoning="reason1",
        error=None,
        step_execution_detail={"steps": []},
        cost=None,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    storage.task_runs = MagicMock(list_for_tenant=AsyncMock(return_value=[run1]))
    req.app.state.storage = storage

    response = await tasks.list_runs("default", req)
    assert len(response) == 1
    assert response[0].id == run1.id
    assert response[0].objective == "obj1"
    storage.task_runs.list_for_tenant.assert_awaited_once_with("default")


@pytest.mark.asyncio
async def test_get_run_returns_run() -> None:
    req = MagicMock()
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    
    import uuid
    from datetime import datetime, timezone
    run_id = uuid.uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_slug="default",
        success=True,
        objective="obj1",
        agent_id="agent1",
        workflow_id=None,
        request_context="input1",
        output={"out": "1"},
        summary=None,
        reasoning="reason1",
        error=None,
        step_execution_detail={"steps": []},
        cost=None,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    storage.task_runs = MagicMock(get_for_tenant=AsyncMock(return_value=run))
    req.app.state.storage = storage

    response = await tasks.get_run("default", run_id, req)
    assert response.id == run_id
    assert response.objective == "obj1"
    storage.task_runs.get_for_tenant.assert_awaited_once_with("default", run_id)


@pytest.mark.asyncio
async def test_get_run_not_found_raises_http_exception() -> None:
    req = MagicMock()
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    storage.task_runs = MagicMock(get_for_tenant=AsyncMock(return_value=None))
    req.app.state.storage = storage

    import uuid
    with pytest.raises(HTTPException) as exc_info:
        await tasks.get_run("default", uuid.uuid4(), req)
    assert exc_info.value.status_code == 404

