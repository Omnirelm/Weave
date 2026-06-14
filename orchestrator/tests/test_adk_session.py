"""Tests for ADK session helpers."""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from src.core.adk.session import TASK_USER_ID, build_runner, create_task_session


@pytest.mark.asyncio
async def test_create_task_session_initial_state_visible_to_get_session() -> None:
    runner = build_runner(
        LlmAgent(
            name="agent_test",
            model=LiteLlm(model="gemini/gemini-2.5-flash"),
            instruction=".",
        )
    )
    session = await create_task_session(
        runner,
        state={"user_input": '{"ok": true}'},
    )

    loaded = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=TASK_USER_ID,
        session_id=session.id,
    )
    assert loaded is not None
    assert loaded.state["user_input"] == '{"ok": true}'
