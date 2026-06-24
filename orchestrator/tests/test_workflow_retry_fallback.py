"""Tests for Workflow-scoped Retry Config."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.adk.agents import LlmAgent

from src.core.agents.builder import AgentBuilder
from src.core.workflows.base import WorkflowDef, WorkflowEdgeDef, WorkflowNodeDef
from src.core.workflows.compiler import WorkflowCompiler


def _agent_row(agent_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=agent_id,
        definition={
            "id": agent_id,
            "name": agent_id,
            "description": "d",
            "instructions": "run",
            "tools": [],
            "mcp_servers": [],
            "model": "gpt-4.1",
        },
    )


@pytest.mark.asyncio
async def test_workflow_compiler_populates_retry_config() -> None:
    storage = MagicMock()
    storage.tenant_agents = MagicMock(
        get_for_tenant=AsyncMock(
            side_effect=lambda _t, agent_id: _agent_row(agent_id),
        )
    )
    tool_provider = MagicMock()
    tool_provider.resolve = AsyncMock(return_value=[])
    mcp_provider = MagicMock()
    mcp_provider.get_toolsets_for_agent = AsyncMock(return_value=[])

    compiler = WorkflowCompiler(AgentBuilder(tool_provider, mcp_provider))
    workflow_def = WorkflowDef(
        id="test_retry_workflow",
        name="Retry Workflow",
        description="desc",
        nodes=[
            WorkflowNodeDef(
                id="step_1",
                agent_id="agent_1",
                max_retries=3,
                initial_delay_seconds=1.5,
                backoff_factor=1.8,
            ),
            WorkflowNodeDef(
                id="step_2",
                agent_id="agent_2",
            ),
        ],
        edges=[
            WorkflowEdgeDef(
                from_node="START",
                to_nodes=["step_1", "step_2"],
            )
        ],
    )

    result = await compiler.compile(
        workflow_def,
        tenant_slug="default",
        storage=storage,
    )

    llm_nodes = [n for n in result.workflow.graph.nodes if isinstance(n, LlmAgent)]
    assert len(llm_nodes) == 2
    
    by_name = {n.name: n for n in llm_nodes}
    agent_1 = by_name["agent_agent_1"]
    agent_2 = by_name["agent_agent_2"]

    assert agent_1.retry_config is not None
    assert agent_1.retry_config.max_attempts == 3
    assert agent_1.retry_config.initial_delay == 1.5
    assert agent_1.retry_config.backoff_factor == 1.8

    assert agent_2.retry_config is None
