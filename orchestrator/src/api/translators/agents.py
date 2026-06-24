from __future__ import annotations

from src.api.models.schemas import AgentResource
from src.core.agents import AgentDef


def agent_def_to_resource(agent: AgentDef) -> AgentResource:
    return AgentResource(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        tools=agent.tools,
        mcp_servers=agent.mcp_servers,
        model=agent.model,
    )


def resource_to_agent_def(resource: AgentResource) -> AgentDef:
    return AgentDef(
        id=resource.id,
        name=resource.name,
        description=resource.description,
        instructions=resource.instructions,
        tools=resource.tools or [],
        mcp_servers=resource.mcp_servers or [],
        model=resource.model or "gemini/gemini-3.5-flash",
    )
