"""
Tool registry and base tool abstraction for programmatic and agent invocation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Dict, List, Sequence


class ToolNotFoundError(KeyError):
    """Raised when a tool name is not registered in a ToolRegistry."""


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


class ToolRegistry:
    """Scoped registry of tools (not a singleton)."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}
        self._factories: Dict[str, Callable[[dict[str, Any]], BaseTool]] = {}
        self._factory_descriptors: Dict[str, ToolDescriptor] = {}
        self._config_schemas: Dict[str, type[Any] | None] = {}

    def register(self, tool: BaseTool) -> ToolRegistry:
        """Register a tool by `tool.name`. Returns self for chaining."""
        self._tools[tool.name] = tool
        self._config_schemas[tool.name] = type(tool).config_schema()
        return self

    def get(self, name: str) -> BaseTool:
        """Return the tool registered under `name`."""
        try:
            return self._tools[name]
        except KeyError as e:
            raise ToolNotFoundError(f"Tool not found: {name!r}") from e

    def register_factory(
        self,
        name: str,
        fn: Callable[[dict[str, Any]], BaseTool],
        *,
        description: str | None = None,
        config_schema: type[Any] | None = None,
    ) -> ToolRegistry:
        """Register a factory for context-dependent tools."""
        self._factories[name] = fn
        self._factory_descriptors[name] = ToolDescriptor(
            name=name,
            description=description or f"Factory-registered tool {name}.",
        )
        self._config_schemas[name] = config_schema
        return self

    def resolve(self, name: str, context: dict[str, Any]) -> BaseTool:
        """Return a static tool instance or instantiate a factory."""
        if name in self._tools:
            return self._tools[name]
        factory = self._factories.get(name)
        if factory is not None:
            return factory(context)
        raise ToolNotFoundError(f"Tool not found: {name!r}")

    def list_tools(self) -> List[BaseTool]:
        """All registered tools."""
        return list(self._tools.values())

    def list_tool_descriptors(self) -> List[ToolDescriptor]:
        """Planner-facing metadata for static and factory tool registrations."""
        static_descriptors = [
            ToolDescriptor(name=t.name, description=t.description)
            for t in self._tools.values()
        ]
        return [*static_descriptors, *self._factory_descriptors.values()]

    def names(self) -> List[str]:
        """Registered tool names, including factory registrations."""
        return [descriptor.name for descriptor in self.list_tool_descriptors()]

    def get_function_tools(self, names: Sequence[str]) -> List[Any]:
        """Build agent tool list in the given order."""
        return [self.get(n).as_function_tool() for n in names]

    def config_schema(self, name: str) -> type[Any] | None:
        """Return the configured schema for a tool if one exists."""
        return self._config_schemas.get(name)
