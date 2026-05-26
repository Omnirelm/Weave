"""Pydantic models and run state for task orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.translators.tasks import RunTaskRequestDomain
from src.core.base import InvocationCost
from src.core.skills import StepResult


class PlanStep(BaseModel):
    """Planner step; YAML / LLM use camelCase (stepType, skillId, toolId)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    step_type: Literal["invoke_skill", "invoke_tool", "synthesize"] = Field(
        ..., alias="stepType"
    )
    skill_id: str | None = Field(default=None, alias="skillId")
    tool_id: str | None = Field(default=None, alias="toolId")
    objective: str
    params: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _ids_for_type(self) -> PlanStep:
        if self.step_type == "invoke_skill" and not self.skill_id:
            raise ValueError("invoke_skill plan step requires skillId")
        if self.step_type == "invoke_tool" and not self.tool_id:
            raise ValueError("invoke_tool plan step requires toolId")
        return self


class ExecutionPlan(BaseModel):
    steps: list[PlanStep]
    reasoning: str


@dataclass
class TaskRunState:
    steps_completed: list[StepResult] = field(default_factory=list)
    """Chronological plan + step events for persistence (schemaVersion 1)."""
    execution_events: list[dict[str, Any]] = field(default_factory=list)
    cost_children: list[InvocationCost] = field(default_factory=list)
    last_reasoning: str | None = None
    last_error: str | None = None
    """Set when direct-mode preferred skill run succeeds."""
    preferred_skill_output: dict[str, Any] | None = None


def plan_step_to_action(step: PlanStep) -> dict[str, Any]:
    return step.model_dump(mode="json", by_alias=True)


def plan_step_for_inner_skill_step(sr: StepResult) -> PlanStep:
    """Build a PlanStep for persisted step_execution_detail when expanding composed skills."""
    if sr.invoked_skill_id:
        return PlanStep(
            stepType="invoke_skill",
            skillId=sr.invoked_skill_id,
            objective=sr.objective,
        )
    if sr.invoked_tool_id:
        return PlanStep(
            stepType="invoke_tool",
            toolId=sr.invoked_tool_id,
            objective=sr.objective,
        )
    return PlanStep(stepType="synthesize", objective=sr.objective)


def record_step(
    *,
    step: PlanStep,
    step_result: StepResult,
    steps_completed: list[StepResult],
    execution_events: list[dict[str, Any]],
) -> None:
    steps_completed.append(step_result)
    execution_events.append(
        {
            "type": "step",
            "seq": len(execution_events),
            "action": plan_step_to_action(step),
            "result": {
                "success": step_result.success,
                "payload": step_result.output,
                "error": step_result.error,
            },
        }
    )


def skill_input_payload(
    task: RunTaskRequestDomain,
    *,
    objective: str | None = None,
    prior_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge request input with orchestrator fields for skill invocation."""
    payload = dict(task.input)
    payload.setdefault("objective", objective if objective is not None else task.task)
    payload.setdefault("task", task.task)
    if prior_steps is not None:
        payload["prior_steps"] = prior_steps
    else:
        payload.setdefault("prior_steps", [])
    return payload
