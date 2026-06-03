"""LLM task planner: builds ExecutionPlan from tenant capabilities."""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions.session import Session

from src.agent_factories.instructions import (
    get_agent_instructions,
    get_agent_model,
    get_agent_name,
)
from src.api.translators.tasks import RunTaskRequestDomain
from src.core.adk.session import run_agent_in_session
from src.core.base import InvocationCost
from src.core.orchestration.catalog import build_capability_catalog
from src.core.orchestration.models import ExecutionPlan
from src.core.orchestration.session_state import enrich_planner_instruction
from src.core.skills import SkillRunner
from src.storage.interface import StorageGateway


def _parse_execution_plan(text: str | None, session: Session) -> ExecutionPlan:
    raw = text
    if not raw:
        stored = session.state.get("current_plan")
        if isinstance(stored, str):
            raw = stored
        elif stored is not None:
            raw = json.dumps(stored)
    if not raw:
        raise ValueError("Planner produced no output")
    return ExecutionPlan.model_validate_json(raw)


async def run_planner(
    *,
    task: RunTaskRequestDomain,
    storage: StorageGateway,
    runner: SkillRunner,
    adk_runner: Runner,
    session: Session,
    replan_reason: str | None,
) -> tuple[ExecutionPlan, InvocationCost]:
    agent_key = "task_planner"
    instructions = enrich_planner_instruction(
        get_agent_instructions(agent_key), session
    )
    model = get_agent_model(agent_key)
    name = get_agent_name(agent_key)

    if replan_reason:
        session.state["replan_reason"] = replan_reason

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
    }
    if replan_reason:
        payload["replanReason"] = replan_reason

    agent = LlmAgent(
        name=name,
        model=LiteLlm(model=model),
        instruction=instructions,
        output_schema=ExecutionPlan,
        output_key="current_plan",
        include_contents="none",
        tools=[],
    )
    text, tokens = await run_agent_in_session(
        adk_runner, session, agent, json.dumps(payload)
    )
    plan = _parse_execution_plan(text, session)
    cost = InvocationCost(label="task_planner", total_tokens=tokens)
    return plan, cost
