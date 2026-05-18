"""Per-request, tenant-scoped tool resolution backed by tenant_integrations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.tools.base import BaseTool, IntegrationTool, ToolDescriptor, ToolNotFoundError

if TYPE_CHECKING:
    from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)


class ToolProvider:
    """Resolves tools for a tenant at request time.

    Static tools (e.g. HttpTool) are returned directly without a DB query.
    Integration-backed tools are constructed fresh from the tenant's active
    rows in tenant_integrations — one DB query per resolve/list_descriptors call.

    Usage in bootstrap::

        provider = ToolProvider(
            storage=storage,
            static_tools=[HttpTool()],
            integration_tools={
                "loki_fetch_logs":       LokiFetchLogsTool,
                "opensearch_fetch_logs": OpenSearchFetchLogsTool,
                ...
            },
        )
    """

    def __init__(
        self,
        storage: StorageGateway,
        static_tools: list[BaseTool],
        integration_tools: dict[str, type[IntegrationTool]],
    ) -> None:
        self._storage = storage
        self._static: dict[str, BaseTool] = {t.name: t for t in static_tools}
        self._integration_tools = integration_tools  # tool name → IntegrationTool class

    async def resolve(self, names: list[str], tenant_slug: str) -> list[BaseTool]:
        """Return instantiated tools for the given names, scoped to tenant_slug.

        Static tools are returned immediately. Integration-backed tools are built
        from the tenant's active integration rows. Tools with no matching integration
        are skipped with a warning — callers should handle partial results gracefully.
        """
        tools: list[BaseTool] = []
        needs_db: list[str] = []

        for name in names:
            if name in self._static:
                tools.append(self._static[name])
            else:
                needs_db.append(name)

        if not needs_db:
            return tools

        integration_map = await self._load_integration_map(tenant_slug)

        for name in needs_db:
            tool_cls = self._integration_tools.get(name)
            if tool_cls is None:
                logger.warning("Tool %r is not registered; skipping", name)
                continue

            key = (tool_cls.integration_type, tool_cls.integration_flavour)
            config = integration_map.get(key)
            if config is None:
                logger.warning(
                    "No active %r/%r integration for tenant %r; skipping tool %r",
                    key[0], key[1], tenant_slug, name,
                )
                continue

            tools.append(tool_cls.from_config(config))

        return tools

    async def resolve_one(self, name: str, tenant_slug: str) -> BaseTool:
        """Return a single tool by name. Raises ToolNotFoundError if unavailable."""
        tools = await self.resolve([name], tenant_slug)
        if not tools:
            raise ToolNotFoundError(
                f"Tool {name!r} is not available for tenant {tenant_slug!r}"
            )
        return tools[0]

    async def list_descriptors(self, tenant_slug: str) -> list[ToolDescriptor]:
        """Return descriptors for all tools available to this tenant.

        Static tools are always included. Integration-backed tools are included
        only when the tenant has an active integration for the matching
        (integration_type, flavour) pair.
        """
        static_descriptors = [
            ToolDescriptor(name=t.name, description=t.description)
            for t in self._static.values()
        ]

        integration_map = await self._load_integration_map(tenant_slug)
        available_pairs = set(integration_map.keys())

        integration_descriptors = [
            ToolDescriptor(name=name, description=cls.description)
            for name, cls in self._integration_tools.items()
            if (cls.integration_type, cls.integration_flavour) in available_pairs
        ]

        return [*static_descriptors, *integration_descriptors]

    def all_descriptors(self) -> list[ToolDescriptor]:
        """Return descriptors for every registered tool regardless of tenant.

        Useful for informational endpoints that list what the system supports.
        For tenant-filtered availability use list_descriptors(tenant_slug) instead.
        """
        static_descriptors = [
            ToolDescriptor(name=t.name, description=t.description)
            for t in self._static.values()
        ]
        integration_descriptors = [
            ToolDescriptor(name=name, description=cls.description)
            for name, cls in self._integration_tools.items()
        ]
        return [*static_descriptors, *integration_descriptors]

    async def _load_integration_map(
        self, tenant_slug: str
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Query tenant integrations and return a (type, flavour) → config map."""
        rows = await self._storage.integrations.list_for_tenant(tenant_slug)
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if not row.active:
                continue
            cfg = dict(row.config or {})
            # flavour is stored on the row, not inside config (see create_request_to_payload).
            # LogSourceSpec and similar consumers require flavour inside the dict.
            if row.flavour:
                cfg["flavour"] = row.flavour
            out[(row.integration_type, row.flavour)] = cfg
        return out
