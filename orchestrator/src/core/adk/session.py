"""ADK Runner + Session helpers for a single agent run."""

from __future__ import annotations

from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.session import Session
from google.genai import types

APP_NAME = "weave"
TASK_USER_ID = "system"


def build_runner(agent: BaseAgent) -> Runner:
    """Create a Runner with an in-memory session service."""
    return Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=InMemorySessionService(),
    )


async def create_task_session(
    runner: Runner,
    *,
    state: dict[str, Any] | None = None,
) -> Session:
    """Create a session, optionally with initial state (ADK-native)."""
    return await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=TASK_USER_ID,
        state=state,
    )


async def run_runner_turn(
    runner: Runner,
    session: Session,
    message: str,
    *,
    user_id: str = TASK_USER_ID,
) -> tuple[str | None, int]:
    """Run one turn on the Runner's root agent. Returns (final_text, tokens)."""
    content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
    total_tokens = 0
    final_text: str | None = None
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=content,
    ):
        usage = event.usage_metadata
        if usage is not None:
            count = getattr(usage, "total_token_count", None)
            if count is not None:
                total_tokens += int(count)
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text = part.text
                    break

    loaded = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session.id,
    )
    if loaded is not None:
        session.state.update(loaded.state)

    return final_text, total_tokens
