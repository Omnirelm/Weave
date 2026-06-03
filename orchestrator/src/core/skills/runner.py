"""Execute simple and composed skills via Google ADK."""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions.session import Session

from src.core.adk.session import (
    build_runner,
    create_task_session,
    run_agent_in_session,
    seed_session_state,
)
from src.core.adk.tool_step_agent import ToolStepAgent
from src.core.base import InvocationCost
from src.core.mcp.provider import McpProvider
from src.core.skills import SkillDef, SkillResult, SkillStep, StepResult
from src.core.skills.input_validation import validate_skill_instance
from src.core.skills.output_validation import (
    SkillOutputError,
    validate_skill_output,
    validate_skill_output_or_model_error,
)
from src.core.tools.base import ToolDescriptor, ToolNotFoundError
from src.core.tools.provider import ToolProvider
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

_MAX_SKILL_DEPTH = 20


def _step_output_key(step_id: str) -> str:
    return f"{step_id}_out"


def _append_output_schema_instruction(skill: SkillDef, instruction: str) -> str:
    schema = skill.output_schema
    if not schema or not isinstance(schema, dict) or len(schema) == 0:
        return instruction
    return (
        f"{instruction}\n\n## Required Output Schema\n"
        f"Return JSON conforming to:\n{json.dumps(schema)}"
    )


def _parse_step_output(raw: Any) -> Any:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


class SkillRunner:
    """Runs skills using tenant-scoped tools and MCP toolsets resolved from the DB."""

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
        runner: Runner | None = None,
        session: Session | None = None,
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

        owns_session = runner is None or session is None
        if owns_session:
            runner, session = await self._create_skill_session(skill)

        try:
            if skill.kind == "simple":
                return await self._run_simple(
                    skill, input_payload, tenant_id, runner, session
                )
            return await self._run_composed(
                skill, input_payload, tenant_id, runner, session
            )
        except SkillOutputError as exc:
            return SkillResult(success=False, error=str(exc), steps_completed=[])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Skill run failed: %s", skill_id)
            return SkillResult(success=False, error=str(exc), steps_completed=[])

    def _validate_input(self, skill: SkillDef, input_payload: dict[str, Any]) -> None:
        validate_skill_instance(skill, input_payload)

    async def _create_skill_session(self, skill: SkillDef) -> tuple[Runner, Session]:
        root = LlmAgent(
            name="weave_skill_root",
            model=LiteLlm(model=skill.model),
            instruction=".",
        )
        runner = build_runner(root)
        session = await create_task_session(runner)
        return runner, session

    async def _resolve_function_tools(self, skill: SkillDef, tenant_id: str) -> list[Any]:
        resolved_tools = await self._tool_provider.resolve(skill.capabilities, tenant_id)
        return [t.as_function_tool() for t in resolved_tools]

    async def _resolve_mcp_toolsets(self, skill: SkillDef, tenant_id: str) -> list[Any]:
        return await self._mcp_provider.get_toolsets_for_skill(skill, tenant_id)

    def _build_simple_llm_agent(
        self,
        skill: SkillDef,
        *,
        name: str | None = None,
        output_key: str | None = None,
        include_contents: str = "default",
        fn_tools: list[Any] | None = None,
        mcp_toolsets: list[Any] | None = None,
        instruction_override: str | None = None,
    ) -> LlmAgent:
        instruction = instruction_override or _append_output_schema_instruction(
            skill, skill.instructions
        )
        tools: list[Any] = []
        if fn_tools is not None:
            tools.extend(fn_tools)
        if mcp_toolsets is not None:
            tools.extend(mcp_toolsets)
        return LlmAgent(
            name=name or f"skill_{skill.id}",
            model=LiteLlm(model=skill.model),
            instruction=instruction,
            tools=tools,
            output_key=output_key or f"skill_{skill.id}_out",
            include_contents=include_contents,  # type: ignore[arg-type]
        )

    async def _build_simple_llm_agent_for_skill(
        self,
        skill: SkillDef,
        tenant_id: str,
        *,
        name: str | None = None,
        output_key: str | None = None,
        include_contents: str = "default",
    ) -> LlmAgent:
        fn_tools = await self._resolve_function_tools(skill, tenant_id)
        mcp_toolsets = await self._resolve_mcp_toolsets(skill, tenant_id)
        return self._build_simple_llm_agent(
            skill,
            name=name,
            output_key=output_key,
            include_contents=include_contents,
            fn_tools=fn_tools,
            mcp_toolsets=mcp_toolsets,
        )

    async def _run_simple(
        self,
        skill: SkillDef,
        input_payload: dict[str, Any],
        tenant_id: str,
        runner: Runner,
        session: Session,
    ) -> SkillResult:
        agent = await self._build_simple_llm_agent_for_skill(skill, tenant_id)
        text, tokens = await run_agent_in_session(
            runner, session, agent, json.dumps(input_payload)
        )
        output = self._finalize_simple_output(skill, text, session, agent.output_key)
        cost = InvocationCost(
            label=f"simple_skill:{skill.id}",
            total_tokens=tokens,
        )
        return SkillResult(success=True, output=output, cost=cost, steps_completed=[])

    def _finalize_simple_output(
        self,
        skill: SkillDef,
        text: str | None,
        session: Session,
        output_key: str | None,
    ) -> Any:
        key = output_key or f"skill_{skill.id}_out"
        raw = session.state.get(key) if key in session.state else text
        if raw is None:
            raise SkillOutputError("Skill produced no output")
        if skill.output_schema and isinstance(raw, str):
            return validate_skill_output_or_model_error(skill, raw)
        if skill.output_schema:
            validate_skill_output(skill, raw)
            return raw
        return _parse_step_output(raw)

    async def _run_composed(
        self,
        skill: SkillDef,
        input_payload: dict[str, Any],
        tenant_id: str,
        runner: Runner,
        session: Session,
    ) -> SkillResult:
        seed_session_state(session, {"original_input": input_payload})
        step_agents = await self._build_composed_step_agents(skill, tenant_id)
        composed = SequentialAgent(
            name=f"composed_{skill.id}",
            sub_agents=step_agents,
        )
        _, tokens = await run_agent_in_session(
            runner, session, composed, json.dumps(input_payload)
        )
        steps_completed = self._steps_completed_from_session(skill, session)
        last_key = _step_output_key(skill.steps[-1].id)
        last_raw = session.state.get(last_key)
        last_out = _parse_step_output(last_raw)

        failed = next((s for s in steps_completed if not s.success), None)
        if failed is not None:
            return SkillResult(
                success=False,
                output=failed.output,
                error=failed.error or "Step failed",
                steps_completed=steps_completed,
                cost=InvocationCost(
                    label=f"composed_skill:{skill.id}",
                    total_tokens=tokens,
                ),
            )

        return SkillResult(
            success=True,
            output=last_out,
            steps_completed=steps_completed,
            cost=InvocationCost(
                label=f"composed_skill:{skill.id}",
                total_tokens=tokens,
            ),
        )

    async def _build_composed_step_agents(
        self, skill: SkillDef, tenant_id: str
    ) -> list[BaseAgent]:
        agents: list[BaseAgent] = []
        for index, step in enumerate(skill.steps):
            agents.append(
                await self._build_composed_step_agent(
                    step, skill, tenant_id, is_first=index == 0
                )
            )
        return agents

    async def _build_composed_step_agent(
        self,
        step: SkillStep,
        parent_skill: SkillDef,
        tenant_id: str,
        *,
        is_first: bool,
    ) -> BaseAgent:
        output_key = _step_output_key(step.id)
        include_contents = "default" if is_first else "none"

        if step.type == "invoke_skill":
            assert step.skill_id is not None
            row = await self._storage.tenant_skills.get_for_tenant(tenant_id, step.skill_id)
            if row is None:
                raise RuntimeError(f"Unknown skill_id: {step.skill_id!r}")
            child = SkillDef.model_validate(row.definition)
            instruction = _append_output_schema_instruction(child, child.instructions)
            if not is_first:
                prior_refs = " ".join(
                    f"{{{_step_output_key(s.id)}}}"
                    for s in parent_skill.steps
                    if s.id != step.id
                )
                instruction = (
                    f"{instruction}\n\n"
                    "Use values from session state for prior steps: "
                    f"{prior_refs}. Original request fields are in {{original_input}}."
                )
            fn_tools = await self._resolve_function_tools(child, tenant_id)
            mcp_toolsets = await self._resolve_mcp_toolsets(child, tenant_id)
            return self._build_simple_llm_agent(
                child,
                name=f"step_{step.id}",
                output_key=output_key,
                include_contents=include_contents,
                fn_tools=fn_tools,
                mcp_toolsets=mcp_toolsets,
                instruction_override=instruction,
            )

        if step.type == "invoke_tool":
            assert step.tool_id is not None
            tool = await self._tool_provider.resolve_one(step.tool_id, tenant_id)

            def _execute() -> Any:
                return tool.execute(**(step.params or {}))

            return ToolStepAgent(
                name=f"tool_{step.id}",
                output_key=output_key,
                execute=_execute,
                description=step.objective,
            )

        instruction = (
            f"{step.objective}\n\n"
            "You are executing a synthesis step in a composed skill workflow.\n"
            "Prior step outputs are available in session state.\n"
            "Use {original_input} and prior step outputs "
            + " ".join(f"{{{_step_output_key(s.id)}}}" for s in parent_skill.steps if s.id != step.id)
            + " to produce a concise result that fulfills the objective."
        )
        return LlmAgent(
            name=f"synthesize_{step.id}",
            model=LiteLlm(model=parent_skill.model),
            instruction=instruction,
            tools=[],
            output_key=output_key,
            include_contents="none",
        )

    def _steps_completed_from_session(
        self, skill: SkillDef, session: Session
    ) -> list[StepResult]:
        results: list[StepResult] = []
        for step in skill.steps:
            key = _step_output_key(step.id)
            raw = session.state.get(key)
            parsed = _parse_step_output(raw)
            error: str | None = None
            success = raw is not None
            if isinstance(parsed, dict) and parsed.get("error"):
                err_val = parsed.get("error")
                if isinstance(err_val, str) and err_val.strip():
                    error = err_val
                    success = False
            results.append(
                StepResult(
                    step_id=step.id,
                    objective=step.objective,
                    success=success,
                    output=parsed,
                    error=error,
                    invoked_skill_id=step.skill_id if step.type == "invoke_skill" else None,
                    invoked_tool_id=step.tool_id if step.type == "invoke_tool" else None,
                )
            )
        return results
