"""ADK Runner + Session helpers for a single agent run."""

from __future__ import annotations

from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.session import Session
from google.genai import types

from google.adk.events.event import Event

APP_NAME = "weave"
TASK_USER_ID = "system"


def calculate_session_token_cost(events: list[Event]) -> int:
    """Calculate total token count across all events in a session."""
    total_tokens = 0
    for event in events:
        usage = event.usage_metadata
        if usage is not None:
            count = getattr(usage, "total_token_count", None)
            if count is not None:
                total_tokens += int(count)
    return total_tokens


def calculate_tokens_by_author(events: list[Event]) -> dict[str, int]:
    """Calculate token counts grouped by event author."""
    tokens_by_author = {}
    for event in events:
        if not event.author:
            continue
        usage = event.usage_metadata
        if usage is not None:
            count = getattr(usage, "total_token_count", None)
            if count is not None:
                tokens_by_author[event.author] = (
                    tokens_by_author.get(event.author, 0) + int(count)
                )
    return tokens_by_author


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

    try:
        loaded = await runner.session_service.get_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session.id,
        )
    except (TypeError, AttributeError):
        loaded = None

    if loaded is not None:
        session.state.update(loaded.state)
        if getattr(loaded, "events", None) is not None:
            total_tokens = calculate_session_token_cost(loaded.events)

    return final_text, total_tokens
