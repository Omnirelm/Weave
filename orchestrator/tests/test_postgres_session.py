"""Integration tests for database session service and purging."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from google.adk.events.event import Event
from google.adk.sessions.database_session_service import DatabaseSessionService
from sqlalchemy import text


@pytest.mark.asyncio
async def test_database_session_service_sqlite_flow() -> None:
    db_url = "sqlite+aiosqlite:///:memory:"
    service = DatabaseSessionService(db_url)

    # 1. Create a session
    session = await service.create_session(
        app_name="weave",
        user_id="test_user",
        state={"key": "val"},
        session_id="session_123",
    )

    assert session.id == "session_123"
    assert session.state == {"key": "val"}

    # 2. Get the session back
    loaded = await service.get_session(
        app_name="weave",
        user_id="test_user",
        session_id="session_123",
    )
    assert loaded is not None
    assert loaded.id == "session_123"
    assert loaded.state == {"key": "val"}

    # 3. Append an event
    event = Event(id="e1", invocation_id="inv1", author="model")
    await service.append_event(session, event)

    # 4. Get session with event
    loaded_with_event = await service.get_session(
        app_name="weave",
        user_id="test_user",
        session_id="session_123",
    )
    assert loaded_with_event is not None
    assert len(loaded_with_event.events) == 1
    assert loaded_with_event.events[0].id == "e1"

    # 5. Clean up/close
    await service.close()


@pytest.mark.asyncio
async def test_session_purge_query_sqlite() -> None:
    db_url = "sqlite+aiosqlite:///:memory:"
    service = DatabaseSessionService(db_url)

    # 1. Create one expired session and one active session
    await service.create_session(
        app_name="weave",
        user_id="test_u",
        session_id="expired_sess",
    )
    await service.create_session(
        app_name="weave",
        user_id="test_u",
        session_id="active_sess",
    )

    # 2. Manually manipulate update_time in database to simulate expiration (e.g. 25 hours ago)
    async with service.database_session_factory() as sql_session:
        threshold_expired = datetime.now(timezone.utc) - timedelta(hours=25)
        # SQLite doesn't enforce timezone, store naive datetime matching ADK
        stmt = text("UPDATE sessions SET update_time = :new_time WHERE id = 'expired_sess'")
        await sql_session.execute(
            stmt,
            {"new_time": threshold_expired.replace(tzinfo=None)},
        )
        await sql_session.commit()

    # 3. Run the purge query threshold calculation
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    async with service.database_session_factory() as sql_session:
        stmt = text("DELETE FROM sessions WHERE update_time < :threshold")
        result = await sql_session.execute(
            stmt,
            {"threshold": threshold.replace(tzinfo=None)},
        )
        await sql_session.commit()
        assert result.rowcount == 1

    # 4. Check that expired_sess was deleted, but active_sess is still there
    loaded_expired = await service.get_session(
        app_name="weave",
        user_id="test_u",
        session_id="expired_sess",
    )
    loaded_active = await service.get_session(
        app_name="weave",
        user_id="test_u",
        session_id="active_sess",
    )

    assert loaded_expired is None
    assert loaded_active is not None

    await service.close()
