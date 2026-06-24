"""Augment agent instructions for ADK workflow graph nodes."""

from __future__ import annotations


def build_workflow_agent_instruction(
    *,
    step_objective: str,
    prior_output_keys: list[str],
) -> str:
    """Append workflow context placeholders and the node step objective.

    Placeholders ``{objective?}`` and ``{user_input?}`` resolve from session state
    at runtime. Prior-step ``output_key`` values use optional ADK state placeholders.
    """
    parts = [
        "### WORKFLOW CONTEXT",
        "Run objective: {objective?}",
        "User context (JSON): {user_input?}",
        "",
        "### STEP OBJECTIVE",
        step_objective.strip() or "Execute this workflow step.",
    ]
    if prior_output_keys:
        parts.extend(["", "### PRIOR STEP OUTPUTS"])
        for key in prior_output_keys:
            parts.append(f"- {{{key}?}}")
    return "\n".join(parts)
