"""Tenant ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin
if TYPE_CHECKING:
    from src.storage.models.integration import TenantIntegration
    from src.storage.models.plan import Plan
    from src.storage.models.skill_report import SkillExecutionReport
    from src.storage.models.task_run import TaskRun
    from src.storage.models.tenant_api_key import TenantApiKey
    from src.storage.models.tenant_quota_usage import TenantQuotaUsage
    from src.storage.models.tenant_skill import TenantSkill


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("plans.slug"),
        nullable=False,
        default="starter",
        server_default=text("'starter'"),
    )

    plan: Mapped["Plan"] = relationship(
        back_populates="tenants",
        foreign_keys=[plan_slug],
        lazy="raise",
    )
    skill_reports: Mapped[list["SkillExecutionReport"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    integrations: Mapped[list["TenantIntegration"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    api_keys: Mapped[list["TenantApiKey"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    quota_usage: Mapped[list["TenantQuotaUsage"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    task_runs: Mapped[list["TaskRun"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    skills: Mapped[list["TenantSkill"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Tenant slug={self.slug!r}>"
