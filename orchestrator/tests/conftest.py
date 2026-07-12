"""Test configuration and fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def force_in_memory_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force session service to in_memory for all unit and route tests."""
    monkeypatch.setenv("ORCHESTRATOR_SESSION__SERVICE_TYPE", "in_memory")
