"""Repository for TaskRun rows."""

from __future__ import annotations

from sqlalchemy import select

from src.storage.db import DatabaseManager
from src.storage.models.task_run import TaskRun
from src.storage.repositories.base import AbstractRepository


class TaskRunRepository(AbstractRepository[TaskRun]):
    model = TaskRun

    async def list_for_tenant(
        self,
        tenant_slug: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskRun]:
        stmt = (
            select(TaskRun)
            .where(TaskRun.tenant_slug == tenant_slug)
            .order_by(TaskRun.finished_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
