"""Periodic background session purging loop."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from sqlalchemy import text

from src.config.settings import get_config
from src.storage.db import get_database

logger = logging.getLogger(__name__)


async def start_session_purge_loop(app: FastAPI) -> None:
    """Start periodic session purging as a background task on the FastAPI app."""
    config = get_config()
    if config.session.service_type != "postgres":
        logger.info(
            "Session service type is %r; background purge loop disabled.",
            config.session.service_type,
        )
        return

    async def purge_task() -> None:
        lifespan_hours = config.session.lifespan_hours
        interval_seconds = config.session.purge_interval_seconds
        db = get_database()

        logger.info(
            "Starting background session purge task (interval=%ds, lifespan=%dh)",
            interval_seconds,
            lifespan_hours,
        )

        while True:
            try:
                await asyncio.sleep(interval_seconds)
                logger.debug("Running session purge query...")

                async with db.session() as session:
                    threshold = (
                        datetime.now(timezone.utc) - timedelta(hours=lifespan_hours)
                    ).replace(tzinfo=None)
                    # The tables are created dynamically by ADK's DatabaseSessionService
                    stmt = text("DELETE FROM sessions WHERE update_time < :threshold")
                    result = await session.execute(stmt, {"threshold": threshold})
                    if result.rowcount > 0:
                        logger.info("Purged %d expired session(s) from database.", result.rowcount)
            except asyncio.CancelledError:
                logger.info("Session purge task cancelled.")
                break
            except Exception:
                logger.exception("Error in session purge background task")

    app.state.session_purge_task = asyncio.create_task(purge_task())
