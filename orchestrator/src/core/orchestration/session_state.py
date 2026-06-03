"""ADK session.state helpers for task orchestration."""

from __future__ import annotations

import json
from typing import Any

from google.adk.sessions.session import Session

from src.api.translators.tasks import RunTaskRequestDomain
from src.core.skills import StepResult

_SUMMARY_OUTPUT_MAX_CHARS = 4000


def plan_step_summary_key(step_index: int) -> str:
    return f"step_{step_index}_summary"


def _compact_output(output: Any) -> Any:
    if output is None:
        return None
    if isinstance(output, str):
        if len(output) <= _SUMMARY_OUTPUT_MAX_CHARS:
            return output
        return output[:_SUMMARY_OUTPUT_MAX_CHARS] + "...(truncated)"
    if isinstance(output, dict):
        return output
    text = json.dumps(output, default=str)
    if len(text) <= _SUMMARY_OUTPUT_MAX_CHARS:
        return output
    return text[:_SUMMARY_OUTPUT_MAX_CHARS] + "...(truncated)"


def write_plan_step_summary(session: Session, step_index: int, step_result: StepResult) -> None:
    """Store a compact step outcome for planner/synthesize {state_key} injection."""
    summary = {
        "step_id": step_result.step_id,
        "success": step_result.success,
        "objective": step_result.objective,
        "output": _compact_output(step_result.output),
        "error": step_result.error,
        "invoked_skill_id": step_result.invoked_skill_id,
        "invoked_tool_id": step_result.invoked_tool_id,
    }
    session.state[plan_step_summary_key(step_index)] = json.dumps(summary)


def seed_task_session_state(session: Session, task: RunTaskRequestDomain) -> None:
    session.state["task"] = task.task
    session.state["tenant_id"] = task.tenant_id
    if task.skill_id:
        session.state["skill_id"] = task.skill_id
    session.state["original_input"] = json.dumps(task.input)


def enrich_planner_instruction(base: str, session: Session) -> str:
    """Append session state key references for prior plan step summaries."""
    summary_keys = sorted(
        k for k in session.state if k.startswith("step_") and k.endswith("_summary")
    )
    if not summary_keys and "replan_reason" not in session.state:
        return base
    extra_lines = ["", "### PRIOR EXECUTION (session state)"]
    for key in summary_keys:
        extra_lines.append(f"- {{{key}}} — prior step result JSON")
    if "replan_reason" in session.state:
        extra_lines.append("- {replan_reason} — why the plan is being revised")
    return base + "\n".join(extra_lines)


def prior_summary_keys(session: Session) -> list[str]:
    return sorted(
        k for k in session.state if k.startswith("step_") and k.endswith("_summary")
    )
