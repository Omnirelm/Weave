"""Repository for SkillExecutionReport rows."""

from __future__ import annotations

from sqlalchemy import select

from src.storage.models.skill_report import SkillExecutionReport, SkillExecutionStatus
from src.storage.repositories.base import AbstractRepository


class SkillReportRepository(AbstractRepository[SkillExecutionReport]):
    model = SkillExecutionReport

    async def list_for_tenant(
        self,
        tenant_slug: str,
        *,
        status: SkillExecutionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SkillExecutionReport]:
        stmt = (
            select(SkillExecutionReport)
            .where(SkillExecutionReport.tenant_slug == tenant_slug)
            .order_by(SkillExecutionReport.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(SkillExecutionReport.status == status)
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
