from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.api.models.schemas import InvocationCostDto, RunTaskRequest, RunTaskResponse
from src.core.base import InvocationCost


@dataclass
class RunTaskRequestDomain:
    objective: str
    tenant_id: str
    agent_id: str = ""
    workflow_id: str = ""
    input: str = ""


def _to_json_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return {"value": value}


def serialize_task_output(value: object) -> dict[str, Any] | None:
    """Normalize agent output for RunTaskResponse.output (open JSON object)."""
    out = _to_json_object(value)
    return dict(out) if out is not None else None


def run_task_request_to_domain(request: RunTaskRequest) -> RunTaskRequestDomain:
    return RunTaskRequestDomain(
        objective=request.objective,
        tenant_id=request.slug,
        agent_id=request.agent_id or "",
        workflow_id=request.workflow_id or "",
        input=(request.input or "").strip(),
    )


def agent_input_payload(domain: RunTaskRequestDomain) -> dict[str, Any]:
    """Build execution payload from run objective and optional input context."""
    payload: dict[str, Any] = {
        "objective": domain.objective,
    }
    if domain.input:
        payload["input"] = domain.input
    return payload


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
    error: str | None,
    cost: InvocationCost | None,
    output: dict[str, Any] | None = None,
) -> RunTaskResponse:
    return RunTaskResponse(
        task_id=task_id,
        success=success,
        output=output,
        reasoning=None,
        error=error,
        cost=invocation_cost_to_dto(cost),
    )
