"""Tenant quota usage counters (e.g. monthly task_run)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class TenantQuotaUsage(Base):
    __tablename__ = "tenant_quota_usage"

    tenant_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.slug", ondelete="CASCADE"),
        primary_key=True,
    )
    operation: Mapped[str] = mapped_column(String(64), primary_key=True)
    period_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="quota_usage", lazy="raise")
