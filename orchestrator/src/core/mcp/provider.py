"""Per-request, tenant-scoped MCP server resolution backed by tenant_integrations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.mcp.registry import McpServerConfig, McpServerRegistry
from src.integrations.flavours import IntegrationType

if TYPE_CHECKING:
    from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

# Singleton registry used only for building SDK server instances from configs.
_server_builder = McpServerRegistry()


class McpProvider:
    """Resolves MCP servers for a tenant at request time.

    Skill YAMLs declare MCP servers by flavour name (e.g. ``["GITHUB", "JIRA"]``).
    At execution time McpProvider queries tenant_integrations for active rows with
    ``integration_type='MCP'`` and the requested flavours, then builds ready-to-use
    MCPServer* instances from each row's config dict.

    Integration rows store transport settings under ``config`` with key ``transport``
    (stdio | sse | streamable_http); that is mapped to ``McpServerConfig.type`` for
    the Agents SDK.
    """

    def __init__(self, storage: StorageGateway) -> None:
        self._storage = storage

    async def resolve(self, flavours: list[str], tenant_slug: str) -> list[Any]:
        """Return built MCPServer* instances for the requested flavours.

        Flavours with no active integration row are skipped with a warning.
        The returned servers are ready to pass to MCPServerManager.
        """
        if not flavours:
            return []

        rows = await self._storage.integrations.list_for_tenant(tenant_slug)
        flavour_set = {f.upper() for f in flavours}

        servers: list[Any] = []
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
            servers.append(_server_builder.build_server(config))

        missing = flavour_set - matched_flavours
        for flavour in missing:
            logger.warning(
                "No active MCP integration for flavour %r on tenant %r; skipping",
                flavour,
                tenant_slug,
            )

        return servers

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
