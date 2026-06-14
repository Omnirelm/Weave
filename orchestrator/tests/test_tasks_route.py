from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
        input="Logs from checkout:\n```json\n{\"service\":\"checkout\"}\n```",
    )

    response = await tasks.run_task(body, req)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "log_analysis"
    assert runner.calls[0][1]["input"] == body.input
    assert runner.calls[0][1]["objective"] == "do thing"
    assert "task" not in runner.calls[0][1]
    assert response.success is True
    assert response.output == {"summary": "ok"}
    assert response.task_id is not None
    req.app.state.storage.task_runs.create.assert_awaited_once()
    persisted = req.app.state.storage.task_runs.create.await_args.args[0]
    assert persisted["id"] == response.task_id
    assert persisted["agent_id"] == "log_analysis"
    assert persisted["request_input"] == body.input
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
async def test_run_task_accepts_string_input_without_validation() -> None:
    runner = _DummyRunner(AgentResult(success=True, output={}))
    req = _request_with_runner(runner)
    body = RunTaskRequest(
        objective="do thing",
        slug="default",
        agent_id="log_analysis",
        input="free-form context",
    )
    response = await tasks.run_task(body, req)
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
    response = await tasks.run_task(body, req)
    assert response.success is False
    assert response.error == "agent blew up"
