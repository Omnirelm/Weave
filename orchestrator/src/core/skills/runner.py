"""Execute simple and composed skills via OpenAI Agents SDK."""

from __future__ import annotations

import json
import logging
from typing import Any

from agents import Agent, Runner, RunResult
from agents.mcp import MCPServerManager

from src.core.base import InvocationCost, extract_runner_cost
from src.core.mcp.provider import McpProvider
from src.core.skills import (
    SkillDef,
    SkillResult,
    SkillRunContext,
    SkillStep,
    StepResult,
)
from src.core.skills.input_validation import validate_skill_instance
from src.core.skills.json_schema_agent_output import SkillJsonSchemaOutput
from src.core.tools.base import ToolDescriptor, ToolNotFoundError
from src.core.tools.provider import ToolProvider
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

_MAX_SKILL_DEPTH = 20


class SkillRunner:
    """Runs skills using tenant-scoped tools and MCP servers resolved from the DB."""

    def __init__(
        self,
        storage: StorageGateway,
        tool_provider: ToolProvider,
        mcp_provider: McpProvider,
    ) -> None:
        self._storage = storage
        self._tool_provider = tool_provider
        self._mcp_provider = mcp_provider

    async def resolve_tool(self, name: str, tenant_id: str) -> Any:
        """Resolve a single tool by name for the given tenant. Raises ToolNotFoundError."""
        return await self._tool_provider.resolve_one(name, tenant_id)

    async def list_tool_descriptors(self, tenant_id: str) -> list[ToolDescriptor]:
        """Return descriptors for all tools available to the given tenant."""
        return await self._tool_provider.list_descriptors(tenant_id)

    async def run_skill(
        self,
        skill_id: str,
        input_payload: dict[str, Any],
        tenant_id: str,
        *,
        _depth: int = 0,
    ) -> SkillResult:
        if _depth > _MAX_SKILL_DEPTH:
            return SkillResult(
                success=False,
                error=f"Max skill nesting depth exceeded ({_MAX_SKILL_DEPTH})",
                steps_completed=[],
            )
        row = await self._storage.tenant_skills.get_for_tenant(tenant_id, skill_id)
        if row is None:
            return SkillResult(success=False, error=f"Unknown skill_id: {skill_id!r}", steps_completed=[])
        try:
            skill = SkillDef.model_validate(row.definition)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Invalid skill definition for %s/%s", tenant_id, skill_id)
            return SkillResult(success=False, error=f"Invalid skill definition: {exc}", steps_completed=[])

        if skill.kind == "composed" and _depth > 0:
            return SkillResult(
                success=False,
                error=(
                    f"Nested composed skills are not allowed: {skill_id!r} cannot be invoked "
                    "from inside another composed skill"
                ),
                steps_completed=[],
            )

        try:
            self._validate_input(skill, input_payload)
        except ValueError as e:
            return SkillResult(success=False, error=str(e), steps_completed=[])

        try:
            if skill.kind == "simple":
                return await self._run_simple(skill, input_payload, tenant_id, _depth)
            return await self._run_composed(skill, input_payload, tenant_id, _depth)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Skill run failed: %s", skill_id)
            return SkillResult(success=False, error=str(exc), steps_completed=[])

    def _validate_input(self, skill: SkillDef, input_payload: dict[str, Any]) -> None:
        validate_skill_instance(skill, input_payload)

    async def _run_simple(
        self,
        skill: SkillDef,
        input_payload: dict[str, Any],
        tenant_id: str,
        _depth: int,
    ) -> SkillResult:
        resolved_tools = await self._tool_provider.resolve(skill.capabilities, tenant_id)
        tools = [t.as_function_tool() for t in resolved_tools]

        mcp_instances = await self._mcp_provider.resolve(skill.mcp_servers, tenant_id)
        output_type: SkillJsonSchemaOutput | None = None
        schema = skill.output_schema
        if schema and isinstance(schema, dict) and len(schema) > 0:
            output_type = SkillJsonSchemaOutput(skill, strict_json_schema=False)

        if mcp_instances:
            async with MCPServerManager(
                mcp_instances,
                strict=False,
                drop_failed_servers=True,
            ) as mgr:
                agent = Agent(
                    name=skill.name,
                    model=skill.model,
                    instructions=skill.instructions,
                    tools=tools,
                    mcp_servers=mgr.active_servers,
                    output_type=output_type,
                )
                result: RunResult = await Runner.run(
                    starting_agent=agent,
                    input=json.dumps(input_payload),
                )
        else:
            agent = Agent(
                name=skill.name,
                model=skill.model,
                instructions=skill.instructions,
                tools=tools,
                mcp_servers=[],
                output_type=output_type,
            )
            result = await Runner.run(
                starting_agent=agent,
                input=json.dumps(input_payload),
            )

        cost = extract_runner_cost(result, f"simple_skill:{skill.id}")
        return SkillResult(
            success=True,
            output=result.final_output,
            cost=cost,
            steps_completed=[],
        )

    async def _run_composed(
        self,
        skill: SkillDef,
        input_payload: dict[str, Any],
        tenant_id: str,
        _depth: int,
    ) -> SkillResult:
        run_context = SkillRunContext(original_input=dict(input_payload))
        children: list[InvocationCost] = []

        for step in skill.steps:
            step_result, step_cost = await self._execute_step(
                step=step,
                run_context=run_context,
                tenant_id=tenant_id,
                parent_model=skill.model,
                _depth=_depth,
            )
            run_context.steps_completed.append(step_result)
            if step_cost is not None:
                children.append(step_cost)

            if not step_result.success:
                total = sum(c.total_tokens for c in children)
                last_out = (
                    run_context.steps_completed[-1].output
                    if run_context.steps_completed
                    else None
                )
                return SkillResult(
                    success=False,
                    output=last_out,
                    error=step_result.error or "Step failed",
                    steps_completed=list(run_context.steps_completed),
                    cost=InvocationCost(
                        label=f"composed_skill:{skill.id}",
                        children=children,
                        total_tokens=total,
                    ),
                )

        total = sum(c.total_tokens for c in children)
        last_out = (
            run_context.steps_completed[-1].output
            if run_context.steps_completed
            else None
        )
        return SkillResult(
            success=True,
            output=last_out,
            steps_completed=list(run_context.steps_completed),
            cost=InvocationCost(
                label=f"composed_skill:{skill.id}",
                children=children,
                total_tokens=total,
            ),
        )

    async def _execute_step(
        self,
        step: SkillStep,
        run_context: SkillRunContext,
        tenant_id: str,
        parent_model: str,
        _depth: int,
    ) -> tuple[StepResult, InvocationCost | None]:
        if step.type == "invoke_skill":
            assert step.skill_id is not None
            sub = await self.run_skill(
                step.skill_id,
                run_context.model_dump(),
                tenant_id,
                _depth=_depth + 1,
            )
            return (
                StepResult(
                    step_id=step.id,
                    objective=step.objective,
                    success=sub.success,
                    output=sub.output,
                    error=sub.error,
                    invoked_skill_id=step.skill_id,
                ),
                sub.cost,
            )

        if step.type == "invoke_tool":
            assert step.tool_id is not None
            try:
                tool = await self._tool_provider.resolve_one(step.tool_id, tenant_id)
                out = tool.execute(**(step.params or {}))
            except Exception as exc:  # noqa: BLE001
                return (
                    StepResult(
                        step_id=step.id,
                        objective=step.objective,
                        success=False,
                        output=None,
                        error=str(exc),
                        invoked_tool_id=step.tool_id,
                    ),
                    InvocationCost(
                        label=f"tool:{step.tool_id}",
                        children=[],
                        total_tokens=0,
                    ),
                )
            return (
                StepResult(
                    step_id=step.id,
                    objective=step.objective,
                    success=True,
                    output=out,
                    error=None,
                    invoked_tool_id=step.tool_id,
                ),
                InvocationCost(
                    label=f"tool:{step.tool_id}",
                    children=[],
                    total_tokens=0,
                ),
            )

        # synthesize
        instructions = (
            f"{step.objective}\n\n"
            "You are executing a synthesis step in a composed skill workflow.\n"
            "The input JSON contains original_input and steps_completed from prior steps.\n"
            "Use that context to produce a concise result that fulfills the objective."
        )
        agent = Agent(
            name=f"synthesize_{step.id}",
            model=parent_model,
            instructions=instructions,
            tools=[],
            output_type=None,
        )
        result: RunResult = await Runner.run(
            starting_agent=agent,
            input=json.dumps(run_context.model_dump()),
        )
        cost = extract_runner_cost(result, f"synthesize:{step.id}")
        return (
            StepResult(
                step_id=step.id,
                objective=step.objective,
                success=True,
                output=result.final_output,
                error=None,
            ),
            cost,
        )
