from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.api.models.schemas import InvocationCostDto, RunTaskRequest, RunTaskResponse, StepResultDto
from src.core.base import InvocationCost
from src.core.skills import StepResult


@dataclass
class RunTaskRequestDomain:
    task: str
    tenant_id: str = "default"
    skill_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    tool_config: dict[str, Any] = field(default_factory=dict)


def _to_json_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    # Generated REST schema expects object output for step payloads.
    return {"value": value}


def serialize_task_output(value: object) -> dict[str, Any] | None:
    """Normalize skill / step output for RunTaskResponse.output (open JSON object)."""
    out = _to_json_object(value)
    return dict(out) if out is not None else None


def run_task_request_to_domain(request: RunTaskRequest) -> RunTaskRequestDomain:
    skill_input: dict[str, Any] = {}
    if request.input is not None:
        skill_input = dict(request.input)
    return RunTaskRequestDomain(
        task=request.objective,
        tenant_id=request.slug or "default",
        skill_id=request.skill_id,
        input=skill_input,
        tool_config={},
    )


def step_result_to_dto(step: StepResult) -> StepResultDto:
    return StepResultDto(
        step_id=step.step_id,
        objective=step.objective,
        success=step.success,
        error=step.error,
    )


def extract_preferred_skill_output(
    task_domain: RunTaskRequestDomain,
    steps_completed: list[StepResult],
    completed_steps_payload: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Structured payload from the request's skill_id step, when present and successful."""
    if not task_domain.skill_id:
        return None
    for step, bundle in zip(steps_completed, completed_steps_payload, strict=True):
        action = bundle.get("action") or {}
        if action.get("skillId") != task_domain.skill_id:
            continue
        if not step.success:
            continue
        return serialize_task_output(step.output)
    return None


def invocation_cost_to_dto(cost: InvocationCost | None) -> InvocationCostDto | None:
    if cost is None:
        return None
    return InvocationCostDto(
        label=cost.label,
        total_tokens=cost.total_tokens,
        children=[invocation_cost_to_dto(child) for child in cost.children],
    )


def build_run_task_response(
    *,
    task_id: UUID,
    success: bool,
    steps: list[StepResult],
    reasoning: str | None,
    error: str | None,
    cost: InvocationCost | None,
    output: dict[str, Any] | None = None,
) -> RunTaskResponse:
    return RunTaskResponse(
        task_id=task_id,
        success=success,
        output=output,
        steps_completed=[step_result_to_dto(step) for step in steps],
        reasoning=reasoning,
        error=error,
        cost=invocation_cost_to_dto(cost),
    )
