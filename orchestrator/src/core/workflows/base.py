from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class WorkflowNodeDef(BaseModel):
    id: str
    type: Literal["agent"] = "agent"
    agent_id: str
    objective: str | None = None


class WorkflowEdgeDef(BaseModel):
    """One edge row in the ADK edges array."""

    from_node: str | Literal["START"]
    to_nodes: list[str] = Field(default_factory=list)
    routes: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate_edge_shape(self) -> WorkflowEdgeDef:
        if self.routes:
            if self.to_nodes:
                raise ValueError(
                    f"Edge from {self.from_node!r}: to_nodes and routes are mutually exclusive"
                )
        elif not self.to_nodes:
            raise ValueError(f"Edge from {self.from_node!r}: to_nodes or routes is required")
        return self


class WorkflowDef(BaseModel):
    id: str
    name: str
    description: str
    nodes: list[WorkflowNodeDef]
    edges: list[WorkflowEdgeDef]
