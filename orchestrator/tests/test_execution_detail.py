from __future__ import annotations

from src.core.orchestration.execution_detail import (
    append_plan_event,
    completed_steps_for_planner,
    execution_detail_for_persist,
    step_bundles_from_events,
)
from src.core.orchestration.models import ExecutionPlan, PlanStep


def test_completed_steps_for_planner_filters_and_preserves_order() -> None:
    events: list[dict] = [
        {
            "type": "plan",
            "seq": 0,
            "reasoning": "r",
            "replanReason": None,
            "plan": {"steps": []},
        },
        {
            "type": "step",
            "seq": 1,
            "action": {"stepType": "invoke_skill", "skillId": "a"},
            "result": {"success": True, "payload": {"x": 1}, "error": None},
        },
        {
            "type": "step",
            "seq": 2,
            "action": {"stepType": "synthesize"},
            "result": {"success": False, "payload": None, "error": "e"},
        },
    ]
    steps = completed_steps_for_planner(events)
    assert len(steps) == 2
    assert steps[0]["action"]["skillId"] == "a"
    assert steps[0]["result"]["success"] is True
    assert steps[1]["result"]["error"] == "e"


def test_step_bundles_from_events_matches_completed_steps_for_planner() -> None:
    events: list[dict] = [
        {"type": "step", "seq": 0, "action": {"a": 1}, "result": {"success": True}},
    ]
    assert step_bundles_from_events(events) == completed_steps_for_planner(events)


def test_append_plan_event_then_steps_seq_monotonic() -> None:
    ev: list[dict] = []
    plan = ExecutionPlan(
        steps=[PlanStep(stepType="synthesize", objective="o")],
        reasoning="because",
    )
    append_plan_event(ev, reasoning=plan.reasoning, replan_reason=None, plan=plan)
    assert len(ev) == 1
    assert ev[0]["type"] == "plan"
    assert ev[0]["seq"] == 0
    assert ev[0]["replanReason"] is None
    assert ev[0]["plan"]["steps"][0]["stepType"] == "synthesize"


def test_execution_detail_for_persist_none_when_empty() -> None:
    assert execution_detail_for_persist([]) is None


def test_execution_detail_for_persist_wraps_events() -> None:
    d = execution_detail_for_persist([{"type": "step", "seq": 0}])
    assert d is not None
    assert d["schemaVersion"] == 1
    assert d["events"] == [{"type": "step", "seq": 0}]
