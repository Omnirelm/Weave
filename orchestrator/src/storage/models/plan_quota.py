"""Plan quota row — limit per operation for a plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.plan import Plan


class PlanQuota(Base, TimestampMixin):
    __tablename__ = "plan_quotas"

    plan_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("plans.slug", ondelete="CASCADE"),
        primary_key=True,
    )
    operation: Mapped[str] = mapped_column(String(64), primary_key=True)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)

    plan: Mapped["Plan"] = relationship(back_populates="quotas", lazy="raise")
