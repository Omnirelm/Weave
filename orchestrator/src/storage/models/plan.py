"""Plan ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.plan_quota import PlanQuota
    from src.storage.models.tenant import Tenant


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    quotas: Mapped[list["PlanQuota"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    tenants: Mapped[list["Tenant"]] = relationship(
        back_populates="plan",
        lazy="raise",
    )
