from src.core.agents.base import AgentDef, AgentResult
from src.core.agents.builder import AgentBuilder

__all__ = ["AgentDef", "AgentResult", "AgentBuilder", "AgentRunner"]


def __getattr__(name: str):
    if name == "AgentRunner":
        from src.core.agents.runner import AgentRunner

        return AgentRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
