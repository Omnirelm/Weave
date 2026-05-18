"""Plan and plan_quotas reads."""

from __future__ import annotations

from sqlalchemy import select

from src.storage.db import DatabaseManager
from src.storage.models.plan_quota import PlanQuota


class PlanRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get_quota(self, plan_slug: str, operation: str) -> PlanQuota | None:
        async with self._db.session() as session:
            stmt = select(PlanQuota).where(
                PlanQuota.plan_slug == plan_slug,
                PlanQuota.operation == operation,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
