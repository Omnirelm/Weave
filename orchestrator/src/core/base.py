"""Cost accounting for LLM/agent invocations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class InvocationCost:
    label: str
    children: List[InvocationCost] = field(default_factory=list)
    total_tokens: int = 0
