"""Run state for task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.base import InvocationCost


@dataclass
class TaskRunState:
    cost_children: list[InvocationCost] = field(default_factory=list)
    last_error: str | None = None
    agent_output: dict[str, Any] | None = None
    agent_id: str | None = None
    workflow_id: str | None = None
    step_execution_detail: dict[str, Any] | None = None
