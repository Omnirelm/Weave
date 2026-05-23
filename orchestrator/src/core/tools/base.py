"""
Base tool abstraction for programmatic and agent invocation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar


class ToolNotFoundError(KeyError):
    """Raised when a requested tool name is not available for the tenant."""


@dataclass(frozen=True)
class ToolDescriptor:
    """Planner-facing metadata for a registered tool name."""

    name: str
    description: str


class BaseTool(ABC):
    """A tool callable by workflows (`execute`) and by agents (`as_function_tool`)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable snake_case identifier used for registry lookup."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Programmatic / workflow invocation."""

    @abstractmethod
    def as_function_tool(self) -> Any:
        """Return a value suitable for `agents.Agent(..., tools=[...])`."""

    @classmethod
    def config_schema(cls) -> type[Any] | None:
        """Optional validation model for tool configuration."""
        return None


class IntegrationTool(BaseTool, ABC):
    """A tool whose connection config is stored in tenant_integrations.

    Concrete subclasses must declare:
      - name: ClassVar[str]           — stable snake_case tool identifier
      - description: ClassVar[str]    — human-readable description
      - integration_type: ClassVar[str]    — matches TenantIntegration.integration_type
      - integration_flavour: ClassVar[str] — matches TenantIntegration.flavour

    The flavour-specific base class (e.g. LokiTool) implements from_config so
    all tools sharing the same backend inherit the construction logic for free.
    """

    integration_type: ClassVar[str]
    integration_flavour: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict[str, Any]) -> "IntegrationTool":
        """Construct this tool from a TenantIntegration config dict."""
