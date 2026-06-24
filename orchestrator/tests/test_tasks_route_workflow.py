"""Tests for POST /tasks/run workflow execution path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.models.schemas import RunTaskRequest
from src.api.routes import tasks
from src.core.workflows.runner import WorkflowResult


class _DummyWorkflowRunner:
    def __init__(self, result: WorkflowResult) -> None:
        self._result = result
        self.calls: list[tuple[str, dict, str]] = []

    async def run_workflow(
        self,
        workflow_id: str,
        input_payload: dict,
        tenant_id: str,
        *,
        task_id=None,
    ) -> WorkflowResult:
        del task_id
        self.calls.append((workflow_id, input_payload, tenant_id))
        return self._result


def _workflow_row() -> SimpleNamespace:
    return SimpleNamespace(
        workflow_id="ppl_log_analysis",
        definition={
            "id": "ppl_log_analysis",
            "name": "PPL",
            "description": "desc",
            "nodes": [
                {"id": "ppl_generation", "type": "agent", "agent_id": "ppl_generation"},
                {"id": "fetch_and_analyze", "type": "agent", "agent_id": "fetch_and_analyze"},
            ],
            "edges": [
                {"from_node": "START", "to_nodes": ["ppl_generation", "fetch_and_analyze"]}
            ],
        },
    )


def _request_with_runners(
    *,
    workflow_runner: _DummyWorkflowRunner,
    workflow_row: SimpleNamespace | None = _workflow_row(),
) -> SimpleNamespace:
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    if workflow_row is None:
        storage.tenant_workflows = MagicMock(get_for_tenant=AsyncMock(return_value=None))
    else:
        storage.tenant_workflows = MagicMock(get_for_tenant=AsyncMock(return_value=workflow_row))
    storage.task_runs = MagicMock()
    storage.task_runs.create = AsyncMock(return_value=SimpleNamespace())
    agent_runner = MagicMock()

    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                agent_runner=agent_runner,
                workflow_runner=workflow_runner,
                storage=storage,
            ),
        )
    )


@pytest.mark.asyncio
async def test_run_task_executes_workflow() -> None:
    workflow_runner = _DummyWorkflowRunner(
        WorkflowResult(
            success=True,
            output={"summary": "ok"},
            step_execution_detail={
                "schemaVersion": 1,
                "events": [{"type": "step", "step_id": "fetch_and_analyze", "success": True}],
            },
        )
    )
    req = _request_with_runners(workflow_runner=workflow_runner)
    body = RunTaskRequest(
        objective="investigate errors",
        slug="default",
        workflow_id="ppl_log_analysis",
        input="Labels: checkout, env prod",
    )

    response = await tasks.run_task(body.slug, body, req)

    assert len(workflow_runner.calls) == 1
    assert workflow_runner.calls[0][0] == "ppl_log_analysis"
    assert response.success is True
    assert response.output == {"summary": "ok"}
    req.app.state.storage.task_runs.create.assert_awaited_once()
    persisted = req.app.state.storage.task_runs.create.await_args.args[0]
    assert persisted["workflow_id"] == "ppl_log_analysis"
    assert persisted["agent_id"] is None
    assert persisted["step_execution_detail"]["schemaVersion"] == 1
    assert "steps_completed" not in persisted


@pytest.mark.asyncio
async def test_run_task_workflow_not_found_404() -> None:
    workflow_runner = _DummyWorkflowRunner(WorkflowResult(success=True))
    req = _request_with_runners(workflow_runner=workflow_runner, workflow_row=None)
    body = RunTaskRequest(
        objective="investigate",
        slug="default",
        workflow_id="missing",
    )
    with pytest.raises(HTTPException) as ei:
        await tasks.run_task(body.slug, body, req)
    assert ei.value.status_code == 404
    assert len(workflow_runner.calls) == 0


@pytest.mark.asyncio
async def test_run_task_requires_workflow_or_agent() -> None:
    with pytest.raises(ValidationError, match="workflow_id or agent_id is required"):
        RunTaskRequest(objective="investigate", slug="xcorp")
