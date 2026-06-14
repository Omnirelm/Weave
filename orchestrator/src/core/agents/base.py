from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.core.base import InvocationCost


class AgentDef(BaseModel):
    id: str
    name: str
    description: str
    instructions: str
    tools: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    model: str = "gemini/gemini-3.5-flash"


class AgentResult(BaseModel):
    success: bool
    output: Any = None
    error: str | None = None
    cost: InvocationCost | None = None
