"""Task planner endpoint: plan then execute steps (skills, tools, synthesize)."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from agents import Agent, AgentOutputSchema, Runner, RunResult
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.api.models.schemas import RunTaskRequest, RunTaskResponse
from src.api.translators.tasks import (
    RunTaskRequestDomain,
    build_run_task_response,
    extract_preferred_skill_output,
    run_task_request_to_domain,
    serialize_task_output,
)

from src.agent_factories.instructions import (
    get_agent_instructions,
    get_agent_model,
    get_agent_name,
)
from src.core.base import InvocationCost, extract_runner_cost
from src.core.skills import SkillDef, SkillRunner, StepResult
from src.core.skills.input_validation import validate_skill_instance
from src.core.tools.base import ToolNotFoundError
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

_MAX_REPLANS = 2


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
    completed_steps_payload: list[dict[str, Any]] = field(default_factory=list)
    cost_children: list[InvocationCost] = field(default_factory=list)
    last_reasoning: str | None = None
    last_error: str | None = None
    """Set when preferred skill_id run succeeds; used as RunTaskResponse.output."""
    preferred_skill_output: dict[str, Any] | None = None


async def _persist_task_run_record(
    storage: StorageGateway,
    *,
    task_id: uuid.UUID,
    started_at: datetime,
    domain_body: RunTaskRequestDomain,
    state: TaskRunState,
    response: RunTaskResponse,
) -> None:
    finished_at = datetime.now(timezone.utc)
    cost_payload = (
        response.cost.model_dump(by_alias=True, exclude_none=True) if response.cost else None
    )
    steps_payload = [
        step.model_dump(by_alias=True, exclude_none=True) for step in response.steps_completed
    ]
    await storage.task_runs.create(
        {
            "id": task_id,
            "tenant_slug": domain_body.tenant_id,
            "success": response.success,
            "objective": domain_body.task,
            "skill_id": domain_body.skill_id,
            "request_input": domain_body.input or None,
            "output": response.output,
            "summary": None,
            "reasoning": response.reasoning,
            "error": response.error,
            "steps_completed": steps_payload,
            "step_execution_detail": state.completed_steps_payload or None,
            "cost": cost_payload,
            "started_at": started_at,
            "finished_at": finished_at,
        }
    )


async def _return_with_persisted_run(
    storage: StorageGateway,
    *,
    task_id: uuid.UUID,
    started_at: datetime,
    domain_body: RunTaskRequestDomain,
    state: TaskRunState,
    response: RunTaskResponse,
) -> RunTaskResponse:
    try:
        await _persist_task_run_record(
            storage,
            task_id=task_id,
            started_at=started_at,
            domain_body=domain_body,
            state=state,
            response=response,
        )
    except Exception:
        logger.exception("task_run persist failed")
        raise HTTPException(status_code=500, detail="Failed to persist task run") from None
    return response


def _plan_step_to_action(step: PlanStep) -> dict[str, Any]:
    return step.model_dump(mode="json", by_alias=True)


def _plan_step_for_inner_skill_step(sr: StepResult) -> PlanStep:
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


def _record_step(
    *,
    step: PlanStep,
    step_result: StepResult,
    steps_completed: list[StepResult],
    completed_steps_payload: list[dict[str, Any]],
) -> None:
    steps_completed.append(step_result)
    completed_steps_payload.append(
        {
            "action": _plan_step_to_action(step),
            "result": {
                "success": step_result.success,
                "payload": step_result.output,
                "error": step_result.error,
            },
        }
    )


def _skill_input_payload(
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


def _response_with_cost(
    *,
    task_id: uuid.UUID,
    task_domain: RunTaskRequestDomain,
    success: bool,
    state: TaskRunState,
    error: str | None = None,
) -> RunTaskResponse:
    skill_output: dict[str, Any] | None = None
    if success:
        if state.preferred_skill_output is not None:
            skill_output = state.preferred_skill_output
        else:
            skill_output = extract_preferred_skill_output(
                task_domain,
                state.steps_completed,
                state.completed_steps_payload,
            )
    total_tokens = sum(c.total_tokens for c in state.cost_children)
    return build_run_task_response(
        task_id=task_id,
        success=success,
        steps=state.steps_completed,
        reasoning=state.last_reasoning,
        error=error,
        output=skill_output,
        cost=InvocationCost(
            label="run_task",
            children=state.cost_children,
            total_tokens=total_tokens,
        ),
    )


def _finalize_success(
    state: TaskRunState,
    task_domain: RunTaskRequestDomain,
    *,
    task_id: uuid.UUID,
) -> RunTaskResponse:
    return _response_with_cost(
        task_id=task_id,
        success=True,
        state=state,
        task_domain=task_domain,
    )


async def _run_direct_skill_if_requested(
    task: RunTaskRequestDomain, runner: SkillRunner, state: TaskRunState
) -> Literal["not_requested", "succeeded", "failed"]:
    """Run preferred skill before planning and return explicit execution status."""
    if not task.skill_id:
        return "not_requested"

    direct_step = PlanStep(
        stepType="invoke_skill",
        skillId=task.skill_id,
        objective=f"Execute preferred skill '{task.skill_id}' before planning.",
    )
    direct_result = await runner.run_skill(
        task.skill_id,
        _skill_input_payload(task),
        task.tenant_id,
    )
    if direct_result.cost is not None:
        state.cost_children.append(direct_result.cost)

    if direct_result.steps_completed:
        for sr in direct_result.steps_completed:
            _record_step(
                step=_plan_step_for_inner_skill_step(sr),
                step_result=sr,
                steps_completed=state.steps_completed,
                completed_steps_payload=state.completed_steps_payload,
            )
    else:
        step_result = StepResult(
            step_id="plan_step_0",
            objective=direct_step.objective,
            success=direct_result.success,
            output=direct_result.output,
            error=direct_result.error,
        )
        _record_step(
            step=direct_step,
            step_result=step_result,
            steps_completed=state.steps_completed,
            completed_steps_payload=state.completed_steps_payload,
        )
    if direct_result.success:
        state.preferred_skill_output = serialize_task_output(direct_result.output)
        return "succeeded"

    state.last_error = direct_result.error or "Preferred skill failed"
    return "failed"


async def _run_planned_iteration(
    *,
    task: RunTaskRequestDomain,
    plan: ExecutionPlan,
    runner: SkillRunner,
    state: TaskRunState,
) -> bool:
    """Execute one generated plan. Returns True when plan failed."""
    plan_failed = False
    start_index = len(state.steps_completed)

    for idx, step in enumerate(plan.steps):
        global_idx = start_index + idx
        sr, step_costs = await _execute_plan_step(
            step,
            global_idx,
            task=task,
            runner=runner,
            prior_steps=list(state.steps_completed),
        )
        state.cost_children.extend(step_costs)
        _record_step(
            step=step,
            step_result=sr,
            steps_completed=state.steps_completed,
            completed_steps_payload=state.completed_steps_payload,
        )
        if not sr.success:
            plan_failed = True
            state.last_error = sr.error or "Step failed"
            break

    return plan_failed


async def _run_planner(
    *,
    task: RunTaskRequestDomain,
    storage: StorageGateway,
    runner: SkillRunner,
    completed_steps: list[dict[str, Any]],
    replan_reason: str | None,
) -> tuple[ExecutionPlan, InvocationCost]:
    agent_key = "task_planner"
    instructions = get_agent_instructions(agent_key)
    model = get_agent_model(agent_key)
    name = get_agent_name(agent_key)

    rows = await storage.tenant_skills.list_for_tenant(task.tenant_id)
    skills: list[SkillDef] = []
    for row in rows:
        try:
            skills.append(SkillDef.model_validate(row.definition))
        except Exception:
            logger.warning(
                "Skipping invalid tenant skill definition for tenant=%s skill_id=%s",
                task.tenant_id,
                row.skill_id,
                exc_info=True,
            )
    available_skills = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "whenToUse": s.description,
            "input_schema": s.input_schema,
            "output_schema": s.output_schema,
        }
        for s in skills
    ]
    tool_descriptors = await runner.list_tool_descriptors(task.tenant_id)
    available_tools = [
        {"id": t.name, "description": t.description} for t in tool_descriptors
    ]

    payload: dict[str, Any] = {
        "task": {
            "prompt": task.task,
            "tenantId": task.tenant_id,
            "skillId": task.skill_id,
            "input": task.input,
        },
        "availableSkills": available_skills,
        "availableTools": available_tools,
        "completedSteps": completed_steps,
    }
    if replan_reason:
        payload["replanReason"] = replan_reason

    agent = Agent(
        name=name,
        model=model,
        instructions=instructions,
        tools=[],
        output_type=AgentOutputSchema(ExecutionPlan, strict_json_schema=False),
    )
    result: RunResult = await Runner.run(
        starting_agent=agent,
        input=json.dumps(payload),
    )
    plan = result.final_output_as(ExecutionPlan, True)
    cost = extract_runner_cost(result, "task_planner")
    return plan, cost


async def _execute_plan_step(
    step: PlanStep,
    step_index: int,
    *,
    task: RunTaskRequestDomain,
    runner: SkillRunner,
    prior_steps: list[StepResult],
) -> tuple[StepResult, list[InvocationCost]]:
    step_id = f"plan_step_{step_index}"
    if step.step_type == "invoke_skill":
        assert step.skill_id is not None
        input_payload = _skill_input_payload(
            task,
            objective=step.objective,
            prior_steps=[s.model_dump() for s in prior_steps],
        )
        sr = await runner.run_skill(
            step.skill_id,
            input_payload,
            task.tenant_id,
        )
        extra_costs = [sr.cost] if sr.cost is not None else []
        return (
            StepResult(
                step_id=step_id,
                objective=step.objective,
                success=sr.success,
                output=sr.output,
                error=sr.error,
                invoked_skill_id=step.skill_id,
            ),
            extra_costs,
        )

    if step.step_type == "invoke_tool":
        assert step.tool_id is not None
        try:
            tool = await runner.resolve_tool(step.tool_id, task.tenant_id)
            out = tool.execute(**(step.params or {}))
        except (ToolNotFoundError, TypeError, ValueError) as exc:
            return (
                StepResult(
                    step_id=step_id,
                    objective=step.objective,
                    success=False,
                    output=None,
                    error=str(exc),
                    invoked_tool_id=step.tool_id,
                ),
                [
                    InvocationCost(
                        label=f"tool:{step.tool_id}",
                        children=[],
                        total_tokens=0,
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("invoke_tool failed")
            return (
                StepResult(
                    step_id=step_id,
                    objective=step.objective,
                    success=False,
                    output=None,
                    error=str(exc),
                    invoked_tool_id=step.tool_id,
                ),
                [],
            )
        return (
            StepResult(
                step_id=step_id,
                objective=step.objective,
                success=True,
                output=out,
                error=None,
                invoked_tool_id=step.tool_id,
            ),
            [
                InvocationCost(
                    label=f"tool:{step.tool_id}",
                    children=[],
                    total_tokens=0,
                )
            ],
        )

    # synthesize
    instructions = (
        f"{step.objective}\n\n"
        "You synthesize a concise answer from the JSON input: it contains the user task "
        "and prior_steps (orchestration results). Be factual."
    )
    agent = Agent(
        name="task_inline_synthesize",
        model=get_agent_model("task_synthesizer"),
        instructions=instructions,
        tools=[],
        output_type=None,
    )
    synth_input = {
        "task": task.task,
        "prior_steps": [s.model_dump() for s in prior_steps],
    }
    result: RunResult = await Runner.run(
        starting_agent=agent,
        input=json.dumps(synth_input),
    )
    synth_cost = extract_runner_cost(result, f"plan_synthesize:{step_id}")
    return (
        StepResult(
            step_id=step_id,
            objective=step.objective,
            success=True,
            output=result.final_output,
            error=None,
        ),
        [synth_cost],
    )


@router.post("/run", response_model=RunTaskResponse)
async def run_task(body: RunTaskRequest, request: Request) -> RunTaskResponse:
    domain_body = run_task_request_to_domain(body)
    storage: StorageGateway = request.app.state.storage
    runner: SkillRunner = request.app.state.skill_runner

    if domain_body.skill_id:
        row = await storage.tenant_skills.get_for_tenant(
            domain_body.tenant_id, domain_body.skill_id
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown skill_id: {domain_body.skill_id!r}",
            )
        try:
            skill = SkillDef.model_validate(row.definition)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid skill definition in database: {exc}",
            ) from exc
        merged = _skill_input_payload(domain_body)
        try:
            validate_skill_instance(skill, merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    task_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    state = TaskRunState()

    direct_skill_status = await _run_direct_skill_if_requested(domain_body, runner, state)
    if direct_skill_status == "succeeded":
        resp = _finalize_success(
            state,
            domain_body,
            task_id=task_id,
        )
        return await _return_with_persisted_run(
            storage,
            task_id=task_id,
            started_at=started_at,
            domain_body=domain_body,
            state=state,
            response=resp,
        )
    if direct_skill_status == "failed":
        resp = _response_with_cost(
            task_id=task_id,
            success=False,
            state=state,
            error=state.last_error,
            task_domain=domain_body,
        )
        return await _return_with_persisted_run(
            storage,
            task_id=task_id,
            started_at=started_at,
            domain_body=domain_body,
            state=state,
            response=resp,
        )

    for replan_idx in range(_MAX_REPLANS + 1):
        replan_reason: str | None = None
        if replan_idx > 0 and state.last_error:
            replan_reason = f"Execution failed: {state.last_error}. Revise the plan."

        try:
            plan, planner_cost = await _run_planner(
                task=domain_body,
                storage=storage,
                runner=runner,
                completed_steps=state.completed_steps_payload,
                replan_reason=replan_reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("task_planner failed")
            state.cost_children.append(
                InvocationCost(label="task_planner_error", children=[], total_tokens=0)
            )
            resp = _response_with_cost(
                task_id=task_id,
                success=False,
                state=state,
                error=str(exc),
                task_domain=domain_body,
            )
            return await _return_with_persisted_run(
                storage,
                task_id=task_id,
                started_at=started_at,
                domain_body=domain_body,
                state=state,
                response=resp,
            )

        state.cost_children.append(planner_cost)
        state.last_reasoning = plan.reasoning
        plan_failed = await _run_planned_iteration(
            task=domain_body,
            plan=plan,
            runner=runner,
            state=state,
        )

        if not plan_failed:
            resp = _finalize_success(
                state,
                domain_body,
                task_id=task_id,
            )
            return await _return_with_persisted_run(
                storage,
                task_id=task_id,
                started_at=started_at,
                domain_body=domain_body,
                state=state,
                response=resp,
            )

        if replan_idx >= _MAX_REPLANS:
            resp = _response_with_cost(
                task_id=task_id,
                success=False,
                state=state,
                error=state.last_error,
                task_domain=domain_body,
            )
            return await _return_with_persisted_run(
                storage,
                task_id=task_id,
                started_at=started_at,
                domain_body=domain_body,
                state=state,
                response=resp,
            )

    raise RuntimeError("run_task: exhausted replan loop without returning")
