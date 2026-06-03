"""Orchestrated task run: direct skill mode vs plan/execute/replan loop."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions.session import Session

from src.api.models.schemas import RunTaskResponse
from src.api.translators.tasks import (
    RunTaskRequestDomain,
    build_run_task_response,
    resolve_run_task_output,
    serialize_task_output,
)
from src.core.adk.session import build_runner, create_task_session
from src.core.base import InvocationCost
from src.core.orchestration.execution_detail import append_plan_event
from src.core.orchestration.session_state import (
    seed_task_session_state,
    write_plan_step_summary,
)
from src.core.orchestration.executor import execute_plan_step
from src.core.orchestration.models import (
    ExecutionPlan,
    PlanStep,
    TaskRunState,
    plan_step_for_inner_skill_step,
    record_step,
    skill_input_payload,
)
from src.core.orchestration.planner import run_planner
from src.core.skills import SkillRunner, StepResult
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

_MAX_REPLANS = 2
_TASK_ROOT_MODEL = "gemini/gemini-2.0-flash"


async def _create_task_adk_context() -> tuple[Runner, Session]:
    root = LlmAgent(
        name="weave_task_root",
        model=LiteLlm(model=_TASK_ROOT_MODEL),
        instruction=".",
    )
    adk_runner = build_runner(root)
    session = await create_task_session(adk_runner)
    return adk_runner, session


def _output_requests_replan(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    if output.get("needs_replan") is True:
        return True
    if output.get("insufficient_data") is True:
        return True
    return False


def _replan_message_from_output(output: Any) -> str:
    if isinstance(output, dict):
        for key in ("replan_reason", "reason", "message"):
            val = output.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return "Skill output requested a revised plan"


async def _run_direct_skill(
    task: RunTaskRequestDomain,
    runner: SkillRunner,
    state: TaskRunState,
    *,
    adk_runner: Runner,
    session: Session,
) -> Literal["succeeded", "failed"]:
    """Direct mode only: run the requested skill once; no planner."""
    if not task.skill_id:
        raise RuntimeError("_run_direct_skill requires task.skill_id")

    direct_step = PlanStep(
        stepType="invoke_skill",
        skillId=task.skill_id,
        objective=f"Execute preferred skill '{task.skill_id}' (direct mode).",
    )
    direct_result = await runner.run_skill(
        task.skill_id,
        skill_input_payload(task),
        task.tenant_id,
        runner=adk_runner,
        session=session,
    )
    if direct_result.cost is not None:
        state.cost_children.append(direct_result.cost)

    if direct_result.steps_completed:
        for sr in direct_result.steps_completed:
            record_step(
                step=plan_step_for_inner_skill_step(sr),
                step_result=sr,
                steps_completed=state.steps_completed,
                execution_events=state.execution_events,
            )
    else:
        step_result = StepResult(
            step_id="plan_step_0",
            objective=direct_step.objective,
            success=direct_result.success,
            output=direct_result.output,
            error=direct_result.error,
        )
        record_step(
            step=direct_step,
            step_result=step_result,
            steps_completed=state.steps_completed,
            execution_events=state.execution_events,
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
    storage: StorageGateway,
    state: TaskRunState,
    adk_runner: Runner,
    session: Session,
) -> bool:
    """Execute one generated plan. Returns True when plan failed or must replan."""
    plan_failed = False
    start_index = len(state.steps_completed)

    for idx, step in enumerate(plan.steps):
        global_idx = start_index + idx
        sr, step_costs = await execute_plan_step(
            step,
            global_idx,
            task=task,
            runner=runner,
            storage=storage,
            adk_runner=adk_runner,
            session=session,
            prior_steps=list(state.steps_completed),
        )
        state.cost_children.extend(step_costs)
        write_plan_step_summary(session, global_idx, sr)
        record_step(
            step=step,
            step_result=sr,
            steps_completed=state.steps_completed,
            execution_events=state.execution_events,
        )
        if not sr.success:
            plan_failed = True
            state.last_error = sr.error or "Step failed"
            break
        if step.step_type == "invoke_skill" and _output_requests_replan(sr.output):
            plan_failed = True
            state.last_error = _replan_message_from_output(sr.output)
            break

    return plan_failed


def _response_with_cost(
    *,
    task_id: uuid.UUID,
    task_domain: RunTaskRequestDomain,
    success: bool,
    state: TaskRunState,
    error: str | None = None,
) -> RunTaskResponse:
    skill_output = resolve_run_task_output(
        success=success,
        task_domain=task_domain,
        preferred_skill_output=state.preferred_skill_output,
        steps_completed=state.steps_completed,
        execution_events=state.execution_events,
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


async def execute_run_task(
    *,
    task_id: uuid.UUID,
    domain_body: RunTaskRequestDomain,
    storage: StorageGateway,
    runner: SkillRunner,
) -> tuple[RunTaskResponse, TaskRunState]:
    """Run task (direct or orchestrated) and return HTTP-ready response + state for persistence."""
    state = TaskRunState()
    adk_runner, session = await _create_task_adk_context()
    seed_task_session_state(session, domain_body)

    if domain_body.execution_mode == "direct":
        direct_skill_status = await _run_direct_skill(
            domain_body, runner, state, adk_runner=adk_runner, session=session
        )
        if direct_skill_status == "succeeded":
            return _finalize_success(state, domain_body, task_id=task_id), state
        if direct_skill_status == "failed":
            return (
                _response_with_cost(
                    task_id=task_id,
                    success=False,
                    state=state,
                    error=state.last_error,
                    task_domain=domain_body,
                ),
                state,
            )
        raise RuntimeError(
            "execute_run_task: direct mode expected succeeded or failed from _run_direct_skill"
        )

    for replan_idx in range(_MAX_REPLANS + 1):
        replan_reason: str | None = None
        if replan_idx > 0 and state.last_error:
            replan_reason = f"Execution failed: {state.last_error}. Revise the plan."

        try:
            plan, planner_cost = await run_planner(
                task=domain_body,
                storage=storage,
                runner=runner,
                adk_runner=adk_runner,
                session=session,
                replan_reason=replan_reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("task_planner failed")
            state.cost_children.append(
                InvocationCost(label="task_planner_error", children=[], total_tokens=0)
            )
            return (
                _response_with_cost(
                    task_id=task_id,
                    success=False,
                    state=state,
                    error=str(exc),
                    task_domain=domain_body,
                ),
                state,
            )

        state.cost_children.append(planner_cost)
        state.last_reasoning = plan.reasoning
        append_plan_event(
            state.execution_events,
            reasoning=plan.reasoning,
            replan_reason=replan_reason,
            plan=plan,
        )

        plan_failed = await _run_planned_iteration(
            task=domain_body,
            plan=plan,
            runner=runner,
            storage=storage,
            state=state,
            adk_runner=adk_runner,
            session=session,
        )

        if not plan_failed:
            return _finalize_success(state, domain_body, task_id=task_id), state

        if replan_idx >= _MAX_REPLANS:
            return (
                _response_with_cost(
                    task_id=task_id,
                    success=False,
                    state=state,
                    error=state.last_error,
                    task_domain=domain_body,
                ),
                state,
            )

    raise RuntimeError("execute_run_task: exhausted replan loop without returning")
