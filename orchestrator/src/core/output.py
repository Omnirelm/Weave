"""Normalize raw ADK agent and workflow output."""

from __future__ import annotations

import json
from typing import Any


class OutputError(ValueError):
    """Raised when an agent or workflow produces no output."""


def coerce_output(raw: Any) -> Any:
    """Return parsed JSON for JSON strings; pass through other values."""
    if raw is None:
        raise OutputError("Agent produced no output")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw
