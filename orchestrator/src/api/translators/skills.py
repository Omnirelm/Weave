from __future__ import annotations

from typing import Literal, cast

from src.api.models.schemas import (
    ExecuteSkillRequest,
    ExecuteSkillResponse,
    InvocationCostDto,
    SkillResource,
    SkillStepResource,
)
from src.core.base import InvocationCost
from src.core.skills import SkillDef, SkillResult, SkillStep


def _to_json_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    # Keep generated response schema strict while preserving scalar/list payloads.
    return {"value": value}


def _invocation_cost_to_dto(cost: InvocationCost | None) -> InvocationCostDto | None:
    if cost is None:
        return None
    return InvocationCostDto(
        label=cost.label,
        total_tokens=cost.total_tokens,
        children=[_invocation_cost_to_dto(child) for child in cost.children],
    )


def _dto_to_invocation_cost(cost: InvocationCostDto | None) -> InvocationCost | None:
    if cost is None:
        return None
    return InvocationCost(
        label=cost.label,
        total_tokens=cost.total_tokens or 0,
        children=[_dto_to_invocation_cost(child) for child in (cost.children or [])],
    )


def skill_def_to_resource(skill: SkillDef) -> SkillResource:
    return SkillResource(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        kind=skill.kind,
        capabilities=skill.capabilities,
        mcp_servers=skill.mcp_servers,
        steps=[
            SkillStepResource(
                id=step.id,
                type=step.type,
                skill_id=step.skill_id,
                tool_id=step.tool_id,
                objective=step.objective,
                params=step.params,
            )
            for step in skill.steps
        ],
        model=skill.model,
        input_schema=skill.input_schema,
        output_schema=skill.output_schema,
    )


def resource_to_skill_def(resource: SkillResource) -> SkillDef:
    # Generated SkillResource / SkillStepResource use StrictStr for kind/type;
    # str() also accepts hand-crafted Enum subclasses from schemas if ever used.
    kind = str(resource.kind) if resource.kind is not None else "simple"
    return SkillDef(
        id=resource.id,
        name=resource.name,
        description=resource.description,
        instructions=resource.instructions or "",
        kind=cast(Literal["simple", "composed"], kind),
        capabilities=resource.capabilities or [],
        mcp_servers=resource.mcp_servers or [],
        steps=[
            SkillStep(
                id=step.id,
                type=cast(Literal["invoke_skill", "invoke_tool", "synthesize"], str(step.type)),
                skill_id=step.skill_id,
                tool_id=step.tool_id,
                objective=step.objective,
                params=step.params,
            )
            for step in (resource.steps or [])
        ],
        model=resource.model or "gpt-4.1",
        input_schema=resource.input_schema,
        output_schema=resource.output_schema,
    )


def skill_result_to_response(result: SkillResult) -> ExecuteSkillResponse:
    return ExecuteSkillResponse(
        success=result.success,
        output=_to_json_object(result.output),
        error=result.error,
        cost=_invocation_cost_to_dto(result.cost),
    )


def execute_request_to_input(request: ExecuteSkillRequest) -> tuple[dict, dict, dict]:
    return request.input, request.context or {}, request.tool_config or {}


def response_to_skill_result(response: ExecuteSkillResponse) -> SkillResult:
    return SkillResult(
        success=response.success,
        output=response.output,
        error=response.error,
        cost=_dto_to_invocation_cost(response.cost),
    )
