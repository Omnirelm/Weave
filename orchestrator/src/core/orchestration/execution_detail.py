"""Unified v1 execution timeline for task runs (plan + step events)."""

from __future__ import annotations

from typing import Any

from src.core.orchestration.models import ExecutionPlan

STEP_EXECUTION_DETAIL_SCHEMA_VERSION = 1


def append_plan_event(
    execution_events: list[dict[str, Any]],
    *,
    reasoning: str,
    replan_reason: str | None,
    plan: ExecutionPlan,
) -> None:
    execution_events.append(
        {
            "type": "plan",
            "seq": len(execution_events),
            "reasoning": reasoning,
            "replanReason": replan_reason,
            "plan": {
                "steps": [s.model_dump(mode="json", by_alias=True) for s in plan.steps],
            },
        }
    )


def completed_steps_for_planner(execution_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build completedSteps payload for the planner LLM (only executed step outcomes)."""
    return step_bundles_from_events(execution_events)


def step_bundles_from_events(execution_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordered {action, result} bundles for each step event (matches legacy completed_steps_payload)."""
    out: list[dict[str, Any]] = []
    for e in execution_events:
        if e.get("type") != "step":
            continue
        out.append({"action": e["action"], "result": e["result"]})
    return out


def execution_detail_for_persist(execution_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Persistable JSON for task_runs.step_execution_detail; null when nothing recorded."""
    if not execution_events:
        return None
    return {
        "schemaVersion": STEP_EXECUTION_DETAIL_SCHEMA_VERSION,
        "events": execution_events,
    }
