"""Singleton DatabaseManager — owns the async engine and session factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import DatabaseConfig, get_config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Owns the async engine + session factory for the lifetime of the process.

    Use the `session()` context manager for short-lived unit-of-work scopes;
    it commits on success and rolls back on any exception.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._engine: AsyncEngine = create_async_engine(
            config.url,
            echo=config.echo,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow,
            pool_timeout=config.pool_timeout,
            pool_recycle=config.pool_recycle,
            pool_pre_ping=True,
            future=True,
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session inside a transactional unit-of-work block.

        - Commits on clean exit.
        - Rolls back and re-raises on any exception.
        - Always closes the session.
        """
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def ping(self) -> None:
        """Lightweight connectivity check; raises if the DB is unreachable."""
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()


@lru_cache(maxsize=1)
def get_database() -> DatabaseManager:
    """Process-wide singleton DatabaseManager built from the orchestrator config."""
    config = get_config()
    logger.debug("Initializing DatabaseManager (pool_size=%d)", config.database.pool_size)
    return DatabaseManager(config.database)
