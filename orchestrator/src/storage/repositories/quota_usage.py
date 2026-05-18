"""Atomic quota consumption for monthly counters."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, select

from src.storage.db import DatabaseManager
from src.storage.models.plan_quota import PlanQuota
from src.storage.models.tenant import Tenant
from src.storage.models.tenant_quota_usage import TenantQuotaUsage


class QuotaExceededError(Exception):
    """Raised when a tenant has exhausted quota for an operation."""


class QuotaUsageRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def try_increment_monthly(
        self,
        *,
        tenant_slug: str,
        operation: str,
        period_key: str,
        limit: int,
    ) -> int:
        """Increment usage for a monthly bucket if below limit. Returns new used count."""
        if limit <= 0:
            raise QuotaExceededError("quota disabled or zero limit")
        async with self._db.session() as session:
            async with session.begin():
                stmt = (
                    select(TenantQuotaUsage)
                    .where(
                        TenantQuotaUsage.tenant_slug == tenant_slug,
                        TenantQuotaUsage.operation == operation,
                        TenantQuotaUsage.period_key == period_key,
                    )
                    .with_for_update()
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row is None:
                    if 1 > limit:
                        raise QuotaExceededError("quota exceeded")
                    row = TenantQuotaUsage(
                        tenant_slug=tenant_slug,
                        operation=operation,
                        period_key=period_key,
                        used=1,
                    )
                    session.add(row)
                    await session.flush()
                    return row.used
                if row.used >= limit:
                    raise QuotaExceededError("quota exceeded")
                row.used += 1
                row.updated_at = datetime.now(timezone.utc)
                await session.flush()
                return row.used

    async def get_tenant_and_plan_quota(
        self, tenant_slug: str, operation: str
    ) -> tuple[Tenant | None, PlanQuota | None]:
        """Load tenant and the plan_quotas row for `operation` in one query."""
        async with self._db.session() as session:
            stmt = (
                select(Tenant, PlanQuota)
                .outerjoin(
                    PlanQuota,
                    and_(
                        PlanQuota.plan_slug == Tenant.plan_slug,
                        PlanQuota.operation == operation,
                    ),
                )
                .where(Tenant.slug == tenant_slug)
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            if row is None:
                return (None, None)
            return (row[0], row[1])
