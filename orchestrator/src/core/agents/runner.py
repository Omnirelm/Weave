"""Execute tenant agents via Google ADK."""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.agents import LlmAgent

from src.core.adk.session import build_runner, create_task_session, run_runner_turn
from src.core.agents.base import AgentDef, AgentResult
from src.core.agents.builder import AgentBuilder
from src.core.base import InvocationCost
from src.core.output import OutputError, coerce_output
from src.core.telemetry import set_weave_context
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)


def _initial_session_state(
    *,
    input_payload: dict[str, Any],
) -> dict[str, str]:
    """Keys referenced by agent instruction templates ({user_input}, {objective})."""
    objective = input_payload.get("objective")
    if not isinstance(objective, str):
        objective = ""
    return {
        "objective": objective,
        "user_input": json.dumps(input_payload),
    }


class AgentRunner:
    """Runs tenant agents with resolved tools and MCP toolsets."""

    def __init__(
        self,
        storage: StorageGateway,
        agent_builder: AgentBuilder,
    ) -> None:
        self._storage = storage
        self._agent_builder = agent_builder

    async def run_agent(
        self,
        agent_id: str,
        input_payload: dict[str, Any],
        tenant_id: str,
    ) -> AgentResult:
        row = await self._storage.tenant_agents.get_for_tenant(tenant_id, agent_id)
        if row is None:
            return AgentResult(success=False, error=f"Unknown agent_id: {agent_id!r}")
        try:
            agent = AgentDef.model_validate(row.definition)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Invalid agent definition for %s/%s", tenant_id, agent_id)
            return AgentResult(success=False, error=f"Invalid agent definition: {exc}")

        try:
            with set_weave_context(tenant_id=tenant_id):
                llm_agent = await self._resolve_and_build_llm_agent(agent, tenant_id)
                runner = build_runner(llm_agent)
                session = await create_task_session(
                    runner,
                    state=_initial_session_state(input_payload=input_payload),
                )
                text, tokens = await run_runner_turn(
                    runner, session, json.dumps(input_payload)
                )
                key = llm_agent.output_key or f"agent_{agent.id}_out"
                raw = session.state.get(key) if key in session.state else text
                output = coerce_output(raw)
                cost = InvocationCost(
                    label=f"agent:{agent.id}",
                    total_tokens=tokens,
                )
                return AgentResult(success=True, output=output, cost=cost)
        except OutputError as exc:
            return AgentResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent run failed: %s", agent_id)
            return AgentResult(success=False, error=str(exc))

    def _build_llm_agent(
        self,
        agent: AgentDef,
        *,
        fn_tools: list[Any] | None = None,
        mcp_toolsets: list[Any] | None = None,
    ) -> LlmAgent:
        return self._agent_builder.build_llm_agent(
            agent,
            fn_tools=fn_tools,
            mcp_toolsets=mcp_toolsets,
            workflow_mode=False,
        )

    async def _resolve_and_build_llm_agent(
        self, agent: AgentDef, tenant_id: str
    ) -> LlmAgent:
        return await self._agent_builder.build_llm_agent_for_tenant(
            agent,
            tenant_id,
            workflow_mode=False,
        )
