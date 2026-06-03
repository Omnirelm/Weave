"""Shared ADK session runner for one task run."""

from __future__ import annotations

from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.session import Session
from google.genai import types

APP_NAME = "weave"
TASK_USER_ID = "system"


def build_runner(root_agent: BaseAgent) -> Runner:
    """Create a Runner with an in-memory session service."""
    return Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=InMemorySessionService(),
    )


async def create_task_session(runner: Runner) -> Session:
    """Create one session for the entire task run."""
    return await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=TASK_USER_ID,
    )


def seed_session_state(session: Session, state_dict: dict[str, Any]) -> None:
    """Populate initial session.state keys before the first agent runs."""
    session.state.update(state_dict)


async def run_agent_in_session(
    runner: Runner,
    session: Session,
    agent: BaseAgent,
    message: str,
    *,
    user_id: str = TASK_USER_ID,
) -> tuple[str | None, int]:
    """Run one agent turn in the shared session. Returns (final_text, tokens)."""
    agent_runner = Runner(
        agent=agent,
        app_name=runner.app_name,
        session_service=runner.session_service,
    )
    content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
    total_tokens = 0
    final_text: str | None = None
    async for event in agent_runner.run_async(
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
    return final_text, total_tokens
