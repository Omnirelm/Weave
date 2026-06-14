"""Tests for WorkflowCompiler."""

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
async def test_compiler_builds_sequential_workflow_with_single_turn_agents() -> None:
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
        id="ppl_log_analysis",
        name="PPL",
        description="desc",
        nodes=[
            WorkflowNodeDef(
                id="ppl_generation",
                agent_id="ppl_generation",
                objective="Generate PPL query",
            ),
            WorkflowNodeDef(
                id="fetch_and_analyze",
                agent_id="fetch_and_analyze",
                objective="Fetch logs and analyze",
            ),
        ],
        edges=[
            WorkflowEdgeDef(
                from_node="START",
                to_nodes=["ppl_generation", "fetch_and_analyze"],
            )
        ],
    )

    result = await compiler.compile(
        workflow_def,
        tenant_slug="default",
        storage=storage,
    )

    assert result.node_order == ["ppl_generation", "fetch_and_analyze"]
    assert result.workflow.name == "ppl_log_analysis"
    llm_nodes = [n for n in result.workflow.graph.nodes if isinstance(n, LlmAgent)]
    assert len(llm_nodes) == 2
    by_name = {n.name: n for n in llm_nodes}
    assert "Generate PPL query" in by_name["agent_ppl_generation"].instruction
    assert "{objective?}" in by_name["agent_ppl_generation"].instruction
    assert "Fetch logs and analyze" in by_name["agent_fetch_and_analyze"].instruction
    assert "{agent_ppl_generation_out?}" in by_name["agent_fetch_and_analyze"].instruction
    for node in llm_nodes:
        assert node.output_schema is None
        assert node.mode == "single_turn"
        assert node.output_key == f"agent_{node.name.removeprefix('agent_')}_out"


@pytest.mark.asyncio
async def test_compiler_does_not_set_adk_workflow_schemas() -> None:
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
        id="ppl_log_analysis",
        name="PPL",
        description="desc",
        nodes=[WorkflowNodeDef(id="ppl_generation", agent_id="ppl_generation")],
        edges=[WorkflowEdgeDef(from_node="START", to_nodes=["ppl_generation"])],
    )

    result = await compiler.compile(
        workflow_def,
        tenant_slug="default",
        storage=storage,
    )

    assert result.workflow.input_schema is None
    assert result.workflow.output_schema is None


@pytest.mark.asyncio
async def test_compiler_builds_three_step_ppl_log_analysis_chain() -> None:
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
        id="ppl_log_analysis",
        name="PPL",
        description="desc",
        nodes=[
            WorkflowNodeDef(id="ppl_generation", agent_id="ppl_generation"),
            WorkflowNodeDef(id="fetch_and_analyze", agent_id="fetch_and_analyze"),
            WorkflowNodeDef(id="code_analysis", agent_id="git_inference"),
        ],
        edges=[
            WorkflowEdgeDef(
                from_node="START",
                to_nodes=["ppl_generation", "fetch_and_analyze", "code_analysis"],
            )
        ],
    )

    result = await compiler.compile(
        workflow_def,
        tenant_slug="default",
        storage=storage,
    )

    assert result.node_order == [
        "ppl_generation",
        "fetch_and_analyze",
        "code_analysis",
    ]
    llm_nodes = [n for n in result.workflow.graph.nodes if isinstance(n, LlmAgent)]
    assert len(llm_nodes) == 3
    assert result.agent_name_to_node_id["agent_git_inference"] == "code_analysis"
    for node in llm_nodes:
        assert node.output_schema is None
