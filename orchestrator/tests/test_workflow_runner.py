"""Tests for WorkflowRunner step collection and cost aggregation."""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from src.core.workflows.compiler import WorkflowCompiler, WorkflowCompileResult
from src.core.workflows.runner import WorkflowRunner


class _FakeEvent:
    def __init__(
        self,
        *,
        author: str = "",
        output=None,
        tokens: int = 0,
        error=None,
        content: types.Content | None = None,
    ) -> None:
        self.author = author
        self.output = output
        self.error = error
        self.content = content
        self.partial = False
        self.usage_metadata = SimpleNamespace(total_token_count=tokens) if tokens else None

    def get_function_calls(self) -> list:
        return []

    def get_function_responses(self) -> list:
        return []

    def is_final_response(self) -> bool:
        return self.content is not None and self.content.role == "model"


def _workflow_row(*, three_step: bool = False) -> SimpleNamespace:
    nodes = [
        {"id": "ppl_generation", "type": "agent", "agent_id": "ppl_generation"},
        {
            "id": "fetch_and_analyze",
            "type": "agent",
            "agent_id": "fetch_and_analyze",
            "objective": "Fetch and analyze",
        },
    ]
    edges = [{"from_node": "START", "to_nodes": ["ppl_generation", "fetch_and_analyze"]}]
    if three_step:
        nodes.append(
            {
                "id": "code_analysis",
                "type": "agent",
                "agent_id": "git_inference",
                "objective": "Identify code issues from log RCA",
            }
        )
        edges = [
            {
                "from_node": "START",
                "to_nodes": ["ppl_generation", "fetch_and_analyze", "code_analysis"],
            }
        ]

    definition: dict = {
        "id": "ppl_log_analysis",
        "name": "PPL",
        "description": "desc",
        "nodes": nodes,
        "edges": edges,
    }

    return SimpleNamespace(
        workflow_id="ppl_log_analysis",
        definition=definition,
    )


def _agent_row(agent_id: str) -> SimpleNamespace:
    definition: dict = {
        "id": agent_id,
        "name": agent_id,
        "description": "d",
        "instructions": "run",
        "tools": [],
        "mcp_servers": ["github"] if agent_id == "git_inference" else [],
        "model": "gpt-4.1",
    }
    return SimpleNamespace(agent_id=agent_id, definition=definition)


@pytest.mark.asyncio
async def test_workflow_runner_collects_steps_and_costs() -> None:
    storage = MagicMock()
    storage.tenant_workflows = MagicMock(get_for_tenant=AsyncMock(return_value=_workflow_row()))
    storage.tenant_agents = MagicMock(
        get_for_tenant=AsyncMock(
            side_effect=lambda _t, agent_id: _agent_row(agent_id)
        )
    )

    tool_provider = MagicMock()
    tool_provider.resolve = AsyncMock(return_value=[])
    mcp_provider = MagicMock()
    mcp_provider.get_toolsets_for_agent = AsyncMock(return_value=[])

    from src.core.agents.builder import AgentBuilder

    compiler = WorkflowCompiler(AgentBuilder(tool_provider, mcp_provider))
    runner = WorkflowRunner(storage, compiler)

    async def _fake_run_async(**_kwargs):
        yield _FakeEvent(
            author="agent_ppl_generation",
            output="QUERY: search source=logs | head 10\nLANGUAGE: PPL\nSTATUS: success\nERROR:",
            tokens=100,
        )
        yield _FakeEvent(
            author="agent_fetch_and_analyze",
            output={"summary": "root cause found"},
            tokens=250,
        )

    fake_session = SimpleNamespace(id="sess-1", state={})
    fake_runner = MagicMock()
    fake_runner.run_async = _fake_run_async
    fake_runner.session_service = MagicMock()

    create_session = AsyncMock(return_value=fake_session)
    with (
        patch("src.core.workflows.runner.build_runner", return_value=fake_runner),
        patch(
            "src.core.workflows.runner.create_task_session",
            new=create_session,
        ),
    ):
        result = await runner.run_workflow(
            "ppl_log_analysis",
            {"labels": [], "objective": "investigate"},
            "default",
        )

    create_session.assert_awaited_once()
    session_state = create_session.await_args.kwargs["state"]
    assert session_state["objective"] == "investigate"
    assert "investigate" in session_state["user_input"]

    assert result.success is True
    assert result.output == {"summary": "root cause found"}
    assert len(result.steps_completed) == 2
    assert result.steps_completed[0].step_id == "ppl_generation"
    assert result.steps_completed[1].step_id == "fetch_and_analyze"
    assert result.cost is not None
    assert result.cost.total_tokens == 350
    assert len(result.cost.children) == 2


@pytest.mark.asyncio
async def test_workflow_runner_emits_step_logs(caplog: pytest.LogCaptureFixture) -> None:
    task_id = uuid.uuid4()
    storage = MagicMock()
    storage.tenant_workflows = MagicMock(get_for_tenant=AsyncMock(return_value=_workflow_row()))
    storage.tenant_agents = MagicMock(
        get_for_tenant=AsyncMock(
            side_effect=lambda _t, agent_id: _agent_row(agent_id)
        )
    )

    tool_provider = MagicMock()
    tool_provider.resolve = AsyncMock(return_value=[])
    mcp_provider = MagicMock()
    mcp_provider.get_toolsets_for_agent = AsyncMock(return_value=[])

    from src.core.agents.builder import AgentBuilder

    compiler = WorkflowCompiler(AgentBuilder(tool_provider, mcp_provider))
    runner = WorkflowRunner(storage, compiler)

    async def _fake_run_async(**_kwargs):
        yield _FakeEvent(
            author="agent_fetch_and_analyze",
            output={"summary": "done"},
            tokens=42,
        )

    fake_session = SimpleNamespace(id="sess-1", state={})
    fake_runner = MagicMock()
    fake_runner.run_async = _fake_run_async
    fake_runner.session_service = MagicMock()

    with (
        patch("src.core.workflows.runner.build_runner", return_value=fake_runner),
        patch(
            "src.core.workflows.runner.create_task_session",
            new=AsyncMock(return_value=fake_session),
        ),
        caplog.at_level(logging.INFO, logger="src.core.workflows.runner"),
    ):
        result = await runner.run_workflow(
            "ppl_log_analysis",
            {"labels": [], "objective": "investigate"},
            "default",
            task_id=task_id,
        )

    assert result.success is True
    messages = [record.message for record in caplog.records]
    assert any("workflow.run.start" in msg and str(task_id) in msg for msg in messages)
    assert any("workflow.step.done" in msg and "fetch_and_analyze" in msg for msg in messages)
    assert any("workflow.run.finish" in msg and "success=True" in msg for msg in messages)


@pytest.mark.asyncio
async def test_workflow_runner_parses_json_from_model_content_when_output_missing() -> None:
    storage = MagicMock()
    storage.tenant_workflows = MagicMock(get_for_tenant=AsyncMock(return_value=_workflow_row()))
    storage.tenant_agents = MagicMock(
        get_for_tenant=AsyncMock(
            side_effect=lambda _t, agent_id: _agent_row(agent_id)
        )
    )

    tool_provider = MagicMock()
    tool_provider.resolve = AsyncMock(return_value=[])
    mcp_provider = MagicMock()
    mcp_provider.get_toolsets_for_agent = AsyncMock(return_value=[])

    from src.core.agents.builder import AgentBuilder

    compiler = WorkflowCompiler(AgentBuilder(tool_provider, mcp_provider))
    runner = WorkflowRunner(storage, compiler)

    payload = {"summary": "parsed from model content"}
    async def _fake_run_async(**_kwargs):
        yield _FakeEvent(
            author="agent_fetch_and_analyze",
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=json.dumps(payload))],
            ),
            tokens=99,
        )

    fake_session = SimpleNamespace(id="sess-1", state={})
    fake_runner = MagicMock()
    fake_runner.run_async = _fake_run_async
    fake_runner.session_service = MagicMock()
    fake_runner.app_name = "weave"
    fake_runner.session_service.get_session = AsyncMock(return_value=fake_session)

    with (
        patch("src.core.workflows.runner.build_runner", return_value=fake_runner),
        patch(
            "src.core.workflows.runner.create_task_session",
            new=AsyncMock(return_value=fake_session),
        ),
    ):
        result = await runner.run_workflow(
            "ppl_log_analysis",
            {"labels": [], "objective": "investigate"},
            "default",
        )

    assert result.success is True
    assert result.output == payload
    assert len(result.steps_completed) == 1
    assert result.steps_completed[0].output == payload


@pytest.mark.asyncio
async def test_workflow_runner_three_step_code_analysis_chain() -> None:
    storage = MagicMock()
    storage.tenant_workflows = MagicMock(
        get_for_tenant=AsyncMock(return_value=_workflow_row(three_step=True))
    )
    storage.tenant_agents = MagicMock(
        get_for_tenant=AsyncMock(
            side_effect=lambda _t, agent_id: _agent_row(agent_id)
        )
    )

    tool_provider = MagicMock()
    tool_provider.resolve = AsyncMock(return_value=[])
    mcp_provider = MagicMock()
    mcp_provider.get_toolsets_for_agent = AsyncMock(return_value=[])

    from src.core.agents.builder import AgentBuilder

    compiler = WorkflowCompiler(AgentBuilder(tool_provider, mcp_provider))
    runner = WorkflowRunner(storage, compiler)

    code_output = (
        "SUMMARY: Null check missing in charge handler at charge.go:142\n"
        "EVIDENCE:\n"
        "- charge.go:142 does not guard nil card — "
        "https://github.com/open-telemetry/opentelemetry-demo/blob/main/src/payment/charge.go#L142"
    )

    async def _fake_run_async(**_kwargs):
        yield _FakeEvent(
            author="agent_ppl_generation",
            output=(
                "QUERY: search source=otel-logs-* | where service.name=payment\n"
                "LANGUAGE: PPL\nSTATUS: success\nERROR:\n"
                "REPO: open-telemetry/opentelemetry-demo"
            ),
            tokens=100,
        )
        yield _FakeEvent(
            author="agent_fetch_and_analyze",
            output=(
                "REPO: open-telemetry/opentelemetry-demo\n"
                "SUMMARY: Payment service panics on nil card\n"
                "EVIDENCE:\n"
                "- [2026-06-09T10:05:00Z] panic: runtime error: invalid memory address"
                " — root exception in charge handler"
            ),
            tokens=250,
        )
        yield _FakeEvent(
            author="agent_git_inference",
            output=code_output,
            tokens=180,
        )

    fake_session = SimpleNamespace(id="sess-1", state={})
    fake_runner = MagicMock()
    fake_runner.run_async = _fake_run_async
    fake_runner.session_service = MagicMock()

    with (
        patch("src.core.workflows.runner.build_runner", return_value=fake_runner),
        patch(
            "src.core.workflows.runner.create_task_session",
            new=AsyncMock(return_value=fake_session),
        ),
    ):
        result = await runner.run_workflow(
            "ppl_log_analysis",
            {
                "repo": "open-telemetry/opentelemetry-demo",
                "labels": [{"name": "service.name", "value": "payment"}],
                "objective": "investigate payment errors",
            },
            "default",
        )

    assert result.success is True
    assert result.output == code_output
    assert len(result.steps_completed) == 3
    assert [step.step_id for step in result.steps_completed] == [
        "ppl_generation",
        "fetch_and_analyze",
        "code_analysis",
    ]
    assert result.steps_completed[2].objective == "Identify code issues from log RCA"
    assert result.cost is not None
    assert result.cost.total_tokens == 530
