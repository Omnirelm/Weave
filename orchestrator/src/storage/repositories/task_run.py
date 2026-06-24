"""Repository for TaskRun rows."""

from __future__ import annotations

import uuid
from sqlalchemy import select

from src.storage.db import DatabaseManager
from src.storage.models.task_run import TaskRun
from src.storage.repositories.base import AbstractRepository


class TaskRunRepository(AbstractRepository[TaskRun]):
    model = TaskRun

    async def list_for_tenant(self, tenant_slug: str, *, limit: int = 50) -> list[TaskRun]:
        stmt = (
            select(self.model)
            .where(self.model.tenant_slug == tenant_slug)
            .order_by(self.model.started_at.desc())
            .limit(limit)
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_for_tenant(self, tenant_slug: str, id: uuid.UUID) -> TaskRun | None:
        async with self._db.session() as session:
            instance = await session.get(self.model, id)
            if instance is not None and instance.tenant_slug == tenant_slug:
                return instance
            return None
