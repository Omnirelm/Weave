from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, BackgroundTasks

from src.api.routes.tasks import (
    parse_grafana_payload,
    trigger_grafana_workflow,
    trigger_grafana_agent,
    _execute_trigger_async,
)
from src.core.agents import AgentResult
from src.core.workflows.runner import WorkflowResult
from src.api.translators.tasks import RunTaskRequestDomain


def test_parse_grafana_payload() -> None:
    import json
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "DatabaseConnectionError",
                    "instance": "db-prod-0",
                    "severity": "critical"
                }
            }
        ]
    }
    obj, ctx = parse_grafana_payload(payload)
    assert obj == "Investigate and provide reasoning for Grafana alerts"
    assert json.loads(ctx) == payload


class _DummyRunner:
    def __init__(self, result: AgentResult) -> None:
        self.result = result
        self.calls = []

    async def run_agent(self, agent_id, input_payload, tenant_id, task_id=None, **kwargs):
        self.calls.append((agent_id, input_payload, tenant_id))
        return self.result


class _DummyWorkflowRunner:
    def __init__(self, result: WorkflowResult) -> None:
        self.result = result
        self.calls = []

    async def run_workflow(self, workflow_id, input_payload, tenant_id, task_id=None, **kwargs):
        self.calls.append((workflow_id, input_payload, tenant_id))
        return self.result


def _build_mock_request(
    *,
    payload: dict,
    workflow_row: SimpleNamespace | None = None,
    agent_row: SimpleNamespace | None = None,
    agent_runner: _DummyRunner | None = None,
    workflow_runner: _DummyWorkflowRunner | None = None,
) -> tuple[MagicMock, SimpleNamespace]:
    storage = MagicMock()
    storage.tenants = MagicMock(get_by_slug=AsyncMock(return_value=SimpleNamespace(slug="default")))
    storage.tenant_workflows = MagicMock(get_for_tenant=AsyncMock(return_value=workflow_row))
    storage.tenant_agents = MagicMock(get_for_tenant=AsyncMock(return_value=agent_row))
    storage.task_runs = MagicMock()
    storage.task_runs.create = AsyncMock()

    req_json = AsyncMock(return_value=payload)
    req = SimpleNamespace(
        json=req_json,
        app=SimpleNamespace(
            state=SimpleNamespace(
                storage=storage,
                agent_runner=agent_runner,
                workflow_runner=workflow_runner,
            )
        )
    )
    return storage, req


@pytest.mark.asyncio
async def test_trigger_grafana_workflow_success() -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "TestAlert"}
            }
        ]
    }
    workflow_row = SimpleNamespace(workflow_id="wf1", definition={})
    agent_runner = _DummyRunner(AgentResult(success=True, output={}))
    workflow_runner = _DummyWorkflowRunner(
        WorkflowResult(
            success=True,
            output={"status": "done"},
            step_execution_detail={"steps": []}
        )
    )

    storage, request = _build_mock_request(
        payload=payload,
        workflow_row=workflow_row,
        agent_runner=agent_runner,
        workflow_runner=workflow_runner,
    )

    background_tasks = BackgroundTasks()

    resp = await trigger_grafana_workflow(
        slug="default",
        workflow_id="wf1",
        request=request,
        background_tasks=background_tasks,
    )

    assert resp["status"] == "accepted"
    assert resp["task_id"] is not None

    # Verify background execution
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    await task.func(*task.args, **task.kwargs)

    assert len(workflow_runner.calls) == 1
    assert workflow_runner.calls[0][0] == "wf1"
    assert workflow_runner.calls[0][1]["objective"] == "Investigate and provide reasoning for Grafana alerts"
    
    # Verify persistence was called
    storage.task_runs.create.assert_awaited_once()
    persisted = storage.task_runs.create.await_args.args[0]
    assert persisted["id"] == uuid.UUID(resp["task_id"])
    assert persisted["workflow_id"] == "wf1"
    assert persisted["success"] is True


@pytest.mark.asyncio
async def test_trigger_grafana_workflow_not_found() -> None:
    storage, request = _build_mock_request(payload={}, workflow_row=None)
    background_tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as exc_info:
        await trigger_grafana_workflow(
            slug="default",
            workflow_id="missing_wf",
            request=request,
            background_tasks=background_tasks,
        )
    assert exc_info.value.status_code == 404
    assert "Workflow not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_trigger_grafana_agent_success() -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "TestAgentAlert"}
            }
        ]
    }
    agent_row = SimpleNamespace(agent_id="ag1", definition={})
    agent_runner = _DummyRunner(AgentResult(success=True, output={"status": "completed"}))
    workflow_runner = _DummyWorkflowRunner(AgentResult(success=True, output={}))

    storage, request = _build_mock_request(
        payload=payload,
        agent_row=agent_row,
        agent_runner=agent_runner,
        workflow_runner=workflow_runner,
    )

    background_tasks = BackgroundTasks()

    resp = await trigger_grafana_agent(
        slug="default",
        agent_id="ag1",
        request=request,
        background_tasks=background_tasks,
    )

    assert resp["status"] == "accepted"
    assert resp["task_id"] is not None

    # Verify background execution
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    await task.func(*task.args, **task.kwargs)

    assert len(agent_runner.calls) == 1
    assert agent_runner.calls[0][0] == "ag1"
    assert agent_runner.calls[0][1]["objective"] == "Investigate and provide reasoning for Grafana alerts"
    
    # Verify persistence was called
    storage.task_runs.create.assert_awaited_once()
    persisted = storage.task_runs.create.await_args.args[0]
    assert persisted["id"] == uuid.UUID(resp["task_id"])
    assert persisted["agent_id"] == "ag1"
    assert persisted["success"] is True


@pytest.mark.asyncio
async def test_trigger_grafana_agent_not_found() -> None:
    storage, request = _build_mock_request(payload={}, agent_row=None)
    background_tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as exc_info:
        await trigger_grafana_agent(
            slug="default",
            agent_id="missing_ag",
            request=request,
            background_tasks=background_tasks,
        )
    assert exc_info.value.status_code == 404
    assert "Agent not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_async_execution_handles_exception_and_persists_failure() -> None:
    # Test that when execution runner raises an exception, the background task catches it and stores success=False
    agent_runner = MagicMock()
    agent_runner.run_agent = AsyncMock(side_effect=RuntimeError("Some LLM model error"))
    
    storage = MagicMock()
    storage.task_runs = MagicMock()
    storage.task_runs.create = AsyncMock()
    
    domain_body = RunTaskRequestDomain(
        objective="Test exception handling",
        tenant_id="default",
        agent_id="ag1",
        context="test exception context"
    )
    
    task_id = uuid.uuid4()
    
    await _execute_trigger_async(
        task_id=task_id,
        domain_body=domain_body,
        runner=agent_runner,
        workflow_runner=None,
        storage=storage,
    )
    
    storage.task_runs.create.assert_awaited_once()
    persisted = storage.task_runs.create.await_args.args[0]
    assert persisted["id"] == task_id
    assert persisted["agent_id"] == "ag1"
    assert persisted["success"] is False
    assert "Some LLM model error" in persisted["error"]
