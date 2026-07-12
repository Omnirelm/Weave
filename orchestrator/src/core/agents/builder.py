"""Build ADK LlmAgent instances from tenant AgentDef records."""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from src.core.agents.base import AgentDef
from src.core.mcp.provider import McpProvider
from src.core.tools.provider import ToolProvider
from src.core.agents.workflow_instructions import build_workflow_agent_instruction


from google.adk.workflow import RetryConfig


class AgentBuilder:
    """Resolves tools/MCP and constructs LlmAgent nodes for direct and workflow execution."""

    def __init__(
        self,
        tool_provider: ToolProvider,
        mcp_provider: McpProvider,
    ) -> None:
        self._tool_provider = tool_provider
        self._mcp_provider = mcp_provider

    async def resolve_tool(self, name: str, tenant_id: str) -> Any:
        return await self._tool_provider.resolve_one(name, tenant_id)

    async def _resolve_function_tools(self, agent: AgentDef, tenant_id: str) -> list[Any]:
        resolved_tools = await self._tool_provider.resolve(agent.tools, tenant_id)
        return [t.as_function_tool() for t in resolved_tools]

    async def _resolve_mcp_toolsets(self, agent: AgentDef, tenant_id: str) -> list[Any]:
        return await self._mcp_provider.get_toolsets_for_agent(agent, tenant_id)

    def build_llm_agent(
        self,
        agent: AgentDef,
        *,
        fn_tools: list[Any] | None = None,
        mcp_toolsets: list[Any] | None = None,
        workflow_mode: bool = False,
        step_objective: str | None = None,
        prior_output_keys: list[str] | None = None,
        retry_config: RetryConfig | None = None,
    ) -> LlmAgent:
        tools: list[Any] = []
        if fn_tools is not None:
            tools.extend(fn_tools)
        if mcp_toolsets is not None:
            tools.extend(mcp_toolsets)

        static_instruction = agent.instructions
        if workflow_mode and step_objective is not None:
            dynamic_instruction = build_workflow_agent_instruction(
                step_objective=step_objective,
                prior_output_keys=prior_output_keys or [],
            )
        else:
            dynamic_instruction = "Run objective: {objective?}  Context: {context?}"

        kwargs: dict[str, Any] = {
            "name": f"agent_{agent.id}",
            "model": LiteLlm(model=agent.model),
            "static_instruction": static_instruction,
            "instruction": dynamic_instruction,
            "tools": tools,
            "include_contents": "none",
            "output_key": f"agent_{agent.id}_out",
        }
        if retry_config is not None:
            kwargs["retry_config"] = retry_config
        if workflow_mode:
            kwargs["mode"] = "single_turn"

        return LlmAgent(**kwargs)

    async def build_llm_agent_for_tenant(
        self,
        agent: AgentDef,
        tenant_id: str,
        *,
        workflow_mode: bool = False,
        step_objective: str | None = None,
        prior_output_keys: list[str] | None = None,
        retry_config: RetryConfig | None = None,
    ) -> LlmAgent:
        fn_tools = await self._resolve_function_tools(agent, tenant_id)
        mcp_toolsets = await self._resolve_mcp_toolsets(agent, tenant_id)
        return self.build_llm_agent(
            agent,
            fn_tools=fn_tools,
            mcp_toolsets=mcp_toolsets,
            workflow_mode=workflow_mode,
            step_objective=step_objective,
            prior_output_keys=prior_output_keys,
            retry_config=retry_config,
        )
