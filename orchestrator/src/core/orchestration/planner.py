"""LLM task planner: builds ExecutionPlan from tenant capabilities."""

from __future__ import annotations

import json
from typing import Any

from agents import Agent, AgentOutputSchema, Runner, RunResult

from src.agent_factories.instructions import (
    get_agent_instructions,
    get_agent_model,
    get_agent_name,
)
from src.api.translators.tasks import RunTaskRequestDomain
from src.core.base import InvocationCost, extract_runner_cost
from src.core.orchestration.catalog import build_capability_catalog
from src.core.orchestration.models import ExecutionPlan
from src.core.skills import SkillRunner
from src.storage.interface import StorageGateway


async def run_planner(
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

    _, available_skills, available_tools = await build_capability_catalog(
        storage, runner, task.tenant_id
    )

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
