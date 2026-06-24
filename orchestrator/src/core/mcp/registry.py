"""MCP server registry: register by name and build ADK McpToolset instances."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Literal

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    SseConnectionParams,
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from mcp import StdioServerParameters
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.mcp.auth import get_auth_handler

logger = logging.getLogger(__name__)


class McpAuthMechanism(BaseModel):
    """Auth mechanism config mirroring the API schema."""
    model_config = ConfigDict(extra="ignore")

    basic: dict | None = None  # {username, password}
    bearer: dict | None = None  # {token}
    oauth: dict | None = None  # {oauth_config: {client_id, client_secret, token_url, scope}}
    api_key: dict | None = None  # {api_key, api_key_header_name}


class McpServerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str | None = None
    enabled: bool = False
    type: Literal["stdio", "sse", "streamable_http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float | None = None
    sse_read_timeout: float | None = None
    cache_tools_list: bool = False
    auth_mechanism: McpAuthMechanism | None = None

    @model_validator(mode="after")
    def _transport_fields(self) -> "McpServerConfig":
        if not self.enabled:
            return self
        if self.type == "stdio" and not (self.command or "").strip():
            raise ValueError("MCP server type stdio requires non-empty command")
        if self.type in ("sse", "streamable_http") and not (self.url or "").strip():
            raise ValueError(f"MCP server type {self.type} requires non-empty url")
        return self


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    servers: dict[str, McpServerConfig] = Field(default_factory=dict)


class McpServerRegistry:
    """Stores enabled MCP server configs and builds runtime McpToolset instances."""

    def __init__(self, configs: Mapping[str, McpServerConfig] | None = None) -> None:
        self._registry: dict[str, McpServerConfig] = {}
        if configs:
            self.register_many(configs)

    def register(self, config: McpServerConfig, *, name: str | None = None) -> None:
        """Register or replace a config by normalized name."""
        normalized_name = (name or config.name or "").strip()
        if name and (config.name or "").strip() != normalized_name:
            config = config.model_copy(update={"name": normalized_name})
        name = normalized_name
        if not name:
            logger.warning("Skipping MCP server registration with empty name")
            return
        self._registry[name] = config

    def register_many(
        self,
        configs: Mapping[str, McpServerConfig],
        *,
        only_enabled: bool = True,
    ) -> None:
        """Register MCP configs from a mapping keyed by server name."""
        for name, config in configs.items():
            if only_enabled and not config.enabled:
                continue
            self.register(config, name=name)

    def get(self, name: str) -> McpServerConfig | None:
        return self._registry.get(name)

    def names(self) -> list[str]:
        return sorted(self._registry.keys())

    def resolve(self, names: Sequence[str]) -> list[McpServerConfig]:
        """Resolve declared names to known configs and warn on missing names."""
        resolved: list[McpServerConfig] = []
        for name in names:
            config = self.get(name)
            if config is None:
                logger.warning(
                    "Agent declared MCP server %r but it is not enabled or configured; skipping",
                    name,
                )
                continue
            resolved.append(config)
        return resolved

    def build_toolset(
        self, config: McpServerConfig, auth_headers: dict[str, str] | None = None
    ) -> McpToolset:
        """Build one ADK McpToolset from config.

        Args:
            config: MCP server configuration
            auth_headers: Pre-resolved authentication headers to merge with static headers

        Returns:
            McpToolset configured for this server
        """
        if config.type == "stdio":
            env = {k: v for k, v in config.env.items() if v} or None
            server_params = StdioServerParameters(
                command=config.command or "",
                args=list(config.args) if config.args else [],
                env=env,
            )
            timeout = config.timeout if config.timeout is not None else 5.0
            connection_params = StdioConnectionParams(
                server_params=server_params,
                timeout=timeout,
            )
            return McpToolset(connection_params=connection_params)

        # Merge static headers with auth headers for HTTP transports
        headers = dict(config.headers) if config.headers else {}
        if auth_headers:
            headers.update(auth_headers)
        final_headers = headers if headers else None

        if config.type == "streamable_http":
            kwargs: dict = {
                "url": config.url or "",
                "headers": final_headers,
            }
            if config.timeout is not None:
                kwargs["timeout"] = config.timeout
            if config.sse_read_timeout is not None:
                kwargs["sse_read_timeout"] = config.sse_read_timeout
            return McpToolset(
                connection_params=StreamableHTTPConnectionParams(**kwargs)
            )

        # SSE transport
        kwargs = {
            "url": config.url or "",
            "headers": final_headers,
        }
        if config.timeout is not None:
            kwargs["timeout"] = config.timeout
        if config.sse_read_timeout is not None:
            kwargs["sse_read_timeout"] = config.sse_read_timeout
        return McpToolset(connection_params=SseConnectionParams(**kwargs))

    async def build_toolset_async(self, config: McpServerConfig) -> McpToolset:
        """Build McpToolset with async auth resolution.

        This method resolves OAuth tokens before building the toolset.
        Use this when auth_mechanism may contain OAuth configuration.
        """
        auth_headers: dict[str, str] | None = None

        if config.auth_mechanism:
            auth_handler = get_auth_handler()
            auth_dict = config.auth_mechanism.model_dump(exclude_none=True)
            auth_headers = await auth_handler.get_auth_headers(auth_dict)

        return self.build_toolset(config, auth_headers=auth_headers)

    def build_toolsets(self, names: Sequence[str]) -> list[McpToolset]:
        return [self.build_toolset(config) for config in self.resolve(names)]

    def build_server(self, config: McpServerConfig) -> McpToolset:
        """Backward-compatible alias for :meth:`build_toolset`."""
        return self.build_toolset(config)

    def build_servers(self, names: Sequence[str]) -> list[McpToolset]:
        """Backward-compatible alias for :meth:`build_toolsets`."""
        return self.build_toolsets(names)
