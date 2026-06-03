from __future__ import annotations

from typing import Literal, cast

from src.api.models.schemas import SkillResource, SkillStepResource
from src.core.skills import SkillDef, SkillStep


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
        model=resource.model or "gemini/gemini-2.0-flash",
        input_schema=resource.input_schema,
        output_schema=resource.output_schema,
    )
