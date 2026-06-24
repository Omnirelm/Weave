"""Tests for workflow agent instruction augmentation."""

from __future__ import annotations

from src.core.agents.workflow_instructions import build_workflow_agent_instruction


def test_build_workflow_agent_instruction_includes_context_placeholders() -> None:
    text = build_workflow_agent_instruction(
        step_objective="Generate PPL query",
        prior_output_keys=[],
    )
    assert "Run objective: {objective?}" in text
    assert "User context (JSON): {user_input?}" in text
    assert "### STEP OBJECTIVE" in text
    assert "Generate PPL query" in text
    assert "PRIOR STEP OUTPUTS" not in text


def test_build_workflow_agent_instruction_includes_prior_output_keys() -> None:
    text = build_workflow_agent_instruction(
        step_objective="Produce RCA report",
        prior_output_keys=["agent_ppl_generation_out"],
    )
    assert "{agent_ppl_generation_out?}" in text
    assert "PRIOR STEP OUTPUTS" in text
