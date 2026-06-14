"""Per-request, tenant-scoped MCP toolset resolution backed by tenant_integrations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from google.adk.tools.mcp_tool import McpToolset

from src.core.mcp.registry import McpServerConfig, McpServerRegistry
from src.integrations.flavours import IntegrationType

if TYPE_CHECKING:
    from src.core.agents.base import AgentDef
    from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

_server_builder = McpServerRegistry()


class McpProvider:
    """Resolves MCP toolsets for a tenant at request time.

    Agent definitions declare MCP servers by flavour name (e.g. ``["GITHUB", "JIRA"]``).
    At execution time McpProvider queries tenant_integrations for active rows with
    ``integration_type='MCP'`` and the requested flavours, then builds ADK
    ``McpToolset`` instances from each row's config dict.
    """

    def __init__(self, storage: StorageGateway) -> None:
        self._storage = storage

    async def get_toolsets_for_agent(
        self, agent: "AgentDef", tenant_slug: str
    ) -> list[McpToolset]:
        """Return ``McpToolset`` instances declared on the agent for this tenant."""
        return await self.get_toolsets_for_flavours(agent.mcp_servers, tenant_slug)

    async def get_toolsets_for_flavours(
        self, flavours: list[str], tenant_slug: str
    ) -> list[McpToolset]:
        """Return built ``McpToolset`` instances for the requested flavours."""
        if not flavours:
            return []

        rows = await self._storage.integrations.list_for_tenant(tenant_slug)
        flavour_set = {f.upper() for f in flavours}

        toolsets: list[McpToolset] = []
        matched_flavours: set[str] = set()
        for row in rows:
            if not row.active:
                continue
            if row.integration_type != IntegrationType.MCP:
                continue
            if row.flavour not in flavour_set:
                continue

            config = self._build_server_config(row.flavour, row.config)
            if config is None:
                continue

            matched_flavours.add(row.flavour)
            toolsets.append(_server_builder.build_toolset(config))

        missing = flavour_set - matched_flavours
        for flavour in missing:
            logger.warning(
                "No active MCP integration for flavour %r on tenant %r; skipping",
                flavour,
                tenant_slug,
            )

        return toolsets

    async def resolve(self, flavours: list[str], tenant_slug: str) -> list[McpToolset]:
        """Backward-compatible alias for :meth:`get_toolsets_for_flavours`."""
        return await self.get_toolsets_for_flavours(flavours, tenant_slug)

    def _build_server_config(
        self, flavour: str, config: dict[str, Any]
    ) -> McpServerConfig | None:
        """Validate and return a McpServerConfig from an integration's config dict."""
        try:
            payload = dict(config)
            transport = payload.pop("transport", None)
            if not transport:
                logger.warning("MCP config missing transport for flavour %r", flavour)
                return None
            payload["type"] = transport
            payload["name"] = flavour
            payload["enabled"] = True
            return McpServerConfig.model_validate(payload)
        except Exception:
            logger.exception(
                "Invalid MCP config for flavour %r; skipping", flavour
            )
            return None
