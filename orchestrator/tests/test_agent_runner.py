"""Tests for AgentRunner and AgentBuilder."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.core.agents.base import AgentDef
from src.core.agents.runner import AgentRunner
from src.core.agents.builder import AgentBuilder
from src.core.output import coerce_output


def _agent_def(**kwargs: object) -> AgentDef:
    base = {
        "id": "ppl_generation",
        "name": "PPL Generation",
        "description": "Generate PPL queries.",
        "instructions": "Generate a query.",
        "model": "gemini/gemini-2.5-flash",
    }
    base.update(kwargs)
    return AgentDef.model_validate(base)


def _runner() -> AgentRunner:
    tool_provider = MagicMock()
    mcp_provider = MagicMock()
    return AgentRunner(
        storage=MagicMock(),
        agent_builder=AgentBuilder(tool_provider, mcp_provider),
    )


def test_build_llm_agent_uses_agent_instructions() -> None:
    agent = _agent_def()

    llm_agent = _runner()._build_llm_agent(agent)

    assert llm_agent.output_schema is None
    assert llm_agent.output_key == "agent_ppl_generation_out"
    assert llm_agent.static_instruction == "Generate a query."
    assert llm_agent.instruction == "Run objective: {objective?}"
    assert llm_agent.generate_content_config is None


def test_build_llm_agent_single_turn_in_workflow_mode() -> None:
    agent = _agent_def()
    tool_provider = MagicMock()
    mcp_provider = MagicMock()
    llm_agent = AgentBuilder(tool_provider, mcp_provider).build_llm_agent(
        agent,
        workflow_mode=True,
    )

    assert llm_agent.output_schema is None
    assert llm_agent.mode == "single_turn"


def test_coerce_output_reads_session_state_value() -> None:
    session = SimpleNamespace(
        state={"agent_ppl_generation_out": {"query": "search source=logs | head 10"}}
    )
    key = "agent_ppl_generation_out"
    raw = session.state.get(key) if key in session.state else None

    assert coerce_output(raw) == {"query": "search source=logs | head 10"}
