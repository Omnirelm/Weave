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
    """orchestrate: plan+execute; direct: single run_skill for skill_id (API requires skill_id)."""
    execution_mode: str = "orchestrate"


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
    mode = request.execution_mode
    if mode not in ("orchestrate", "direct"):
        mode = "orchestrate"
    return RunTaskRequestDomain(
        task=request.objective,
        tenant_id=request.slug or "default",
        skill_id=request.skill_id,
        input=skill_input,
        tool_config={},
        execution_mode=mode,
    )


def step_result_to_dto(step: StepResult) -> StepResultDto:
    return StepResultDto(
        step_id=step.step_id,
        objective=step.objective,
        success=step.success,
        error=step.error,
    )


def step_bundles_from_execution_events(
    execution_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match step events to steps_completed order (action/result bundles only)."""
    out: list[dict[str, Any]] = []
    for e in execution_events:
        if e.get("type") != "step":
            continue
        out.append({"action": e["action"], "result": e["result"]})
    return out


def extract_preferred_skill_output(
    task_domain: RunTaskRequestDomain,
    steps_completed: list[StepResult],
    execution_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Structured payload from the request's skill_id step, when present and successful."""
    if not task_domain.skill_id:
        return None
    bundles = step_bundles_from_execution_events(execution_events)
    for step, bundle in zip(steps_completed, bundles, strict=True):
        action = bundle.get("action") or {}
        if action.get("skillId") != task_domain.skill_id:
            continue
        if not step.success:
            continue
        return serialize_task_output(step.output)
    return None


def extract_final_orchestration_output(
    steps_completed: list[StepResult],
) -> dict[str, Any] | None:
    """Last successful step with non-null output (orchestrated runs without preferred skill)."""
    for step in reversed(steps_completed):
        if step.success and step.output is not None:
            return serialize_task_output(step.output)
    return None


def resolve_run_task_output(
    *,
    success: bool,
    task_domain: RunTaskRequestDomain,
    preferred_skill_output: dict[str, Any] | None,
    steps_completed: list[StepResult],
    execution_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not success:
        return None
    if preferred_skill_output is not None:
        return preferred_skill_output
    hinted = extract_preferred_skill_output(
        task_domain, steps_completed, execution_events
    )
    if hinted is not None:
        return hinted
    return extract_final_orchestration_output(steps_completed)


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
