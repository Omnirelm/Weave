"""Execute a single plan step (skill, tool, or synthesize)."""

from __future__ import annotations

import json
import logging
from typing import Any

from agents import Agent, Runner, RunResult

from src.agent_factories.instructions import get_agent_model
from src.api.translators.tasks import RunTaskRequestDomain
from src.core.base import InvocationCost, extract_runner_cost
from src.core.orchestration.models import PlanStep, skill_input_payload
from src.core.skills import SkillDef, SkillRunner, StepResult
from src.core.skills.input_validation import validate_skill_instance
from src.core.tools.base import ToolNotFoundError
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)


async def execute_plan_step(
    step: PlanStep,
    step_index: int,
    *,
    task: RunTaskRequestDomain,
    runner: SkillRunner,
    storage: StorageGateway,
    prior_steps: list[StepResult],
) -> tuple[StepResult, list[InvocationCost]]:
    step_id = f"plan_step_{step_index}"
    if step.step_type == "invoke_skill":
        assert step.skill_id is not None
        row = await storage.tenant_skills.get_for_tenant(task.tenant_id, step.skill_id)
        if row is None:
            return (
                StepResult(
                    step_id=step_id,
                    objective=step.objective,
                    success=False,
                    output=None,
                    error=f"Unknown skill_id: {step.skill_id!r}",
                    invoked_skill_id=step.skill_id,
                ),
                [],
            )
        try:
            skill = SkillDef.model_validate(row.definition)
        except Exception as exc:  # noqa: BLE001
            return (
                StepResult(
                    step_id=step_id,
                    objective=step.objective,
                    success=False,
                    output=None,
                    error=f"Invalid skill definition: {exc}",
                    invoked_skill_id=step.skill_id,
                ),
                [],
            )
        input_payload = skill_input_payload(
            task,
            objective=step.objective,
            prior_steps=[s.model_dump() for s in prior_steps],
        )
        try:
            validate_skill_instance(skill, input_payload)
        except ValueError as exc:
            return (
                StepResult(
                    step_id=step_id,
                    objective=step.objective,
                    success=False,
                    output=None,
                    error=str(exc),
                    invoked_skill_id=step.skill_id,
                ),
                [],
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
