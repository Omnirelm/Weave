"""Tests for RunTaskRequest validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.models.schemas import RunTaskRequest


def test_run_task_request_requires_slug() -> None:
    with pytest.raises(ValidationError, match="slug"):
        RunTaskRequest(objective="investigate", agent_id="log_analysis")


def test_run_task_request_requires_agent_or_workflow() -> None:
    with pytest.raises(ValidationError, match="workflow_id or agent_id is required"):
        RunTaskRequest(objective="investigate", slug="xcorp")


def test_run_task_request_rejects_both_agent_and_workflow() -> None:
    with pytest.raises(ValidationError, match="not both"):
        RunTaskRequest(
            objective="investigate",
            slug="xcorp",
            agent_id="log_analysis",
            workflow_id="ppl_log_analysis",
        )
