"""Compile WorkflowDef into google.adk.Workflow graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.workflow import RetryConfig, Workflow

from src.core.agents.base import AgentDef
from src.core.agents.builder import AgentBuilder
from src.core.workflows.base import WorkflowDef
from src.core.workflows.validation import _sequential_node_order
from src.storage.interface import StorageGateway


@dataclass
class WorkflowCompileResult:
    workflow: Workflow
    node_order: list[str]
    node_objectives: dict[str, str | None]
    agent_name_to_node_id: dict[str, str]
    agents_by_id: dict[str, AgentDef] = field(default_factory=dict)


class WorkflowCompiler:
    """Compiles tenant workflow definitions into ADK Workflow graphs."""

    def __init__(self, agent_builder: AgentBuilder) -> None:
        self._agent_builder = agent_builder

    async def compile(
        self,
        workflow_def: WorkflowDef,
        *,
        tenant_slug: str,
        storage: StorageGateway,
    ) -> WorkflowCompileResult:
        if any(edge.routes for edge in workflow_def.edges):
            raise ValueError("Conditional workflow routes are not supported in v1")

        node_by_id = {node.id: node for node in workflow_def.nodes}
        order = _sequential_node_order(workflow_def)
        if not order:
            raise ValueError("Workflow has no executable agent chain")

        llm_agents: list[LlmAgent] = []
        agent_name_to_node_id: dict[str, str] = {}
        agents_by_id: dict[str, AgentDef] = {}
        node_objectives: dict[str, str | None] = {}
        prior_output_keys: list[str] = []

        for node_id in order:
            node = node_by_id[node_id]
            row = await storage.tenant_agents.get_for_tenant(tenant_slug, node.agent_id)
            if row is None:
                raise ValueError(f"Unknown agent_id: {node.agent_id!r}")
            agent = AgentDef.model_validate(row.definition)
            agents_by_id[agent.id] = agent
            step_objective = node.objective or node_id

            adk_retry_config = None
            if node.max_retries is not None:
                adk_retry_config = RetryConfig(
                    max_attempts=node.max_retries,
                    initial_delay=node.initial_delay_seconds if node.initial_delay_seconds is not None else 1.0,
                    backoff_factor=node.backoff_factor if node.backoff_factor is not None else 2.0,
                    jitter=1.0,
                )

            llm_agent = await self._agent_builder.build_llm_agent_for_tenant(
                agent,
                tenant_slug,
                workflow_mode=True,
                step_objective=step_objective,
                prior_output_keys=list(prior_output_keys),
                retry_config=adk_retry_config,
            )
            llm_agents.append(llm_agent)
            agent_name_to_node_id[llm_agent.name] = node_id
            node_objectives[node_id] = node.objective
            prior_output_keys.append(llm_agent.output_key or f"agent_{agent.id}_out")

        # ADK edge tuple ("START", *agents) runs agents sequentially: START→a→b→c.
        workflow_kwargs: dict[str, Any] = {
            "name": workflow_def.id,
            "description": workflow_def.description,
            "edges": [("START", *llm_agents)],
        }

        return WorkflowCompileResult(
            workflow=Workflow(**workflow_kwargs),
            node_order=order,
            node_objectives=node_objectives,
            agent_name_to_node_id=agent_name_to_node_id,
            agents_by_id=agents_by_id,
        )
