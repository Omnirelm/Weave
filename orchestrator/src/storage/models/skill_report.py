"""SkillExecutionReport ORM model — captures one run of a skill for a tenant."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class SkillExecutionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SkillExecutionReport(Base, TimestampMixin):
    __tablename__ = "skill_execution_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.slug", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[SkillExecutionStatus] = mapped_column(
        Enum(
            SkillExecutionStatus,
            name="skill_execution_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=SkillExecutionStatus.PENDING,
        index=True,
    )
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="skill_reports", lazy="raise")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<SkillExecutionReport id={self.id} "
            f"skill={self.skill_name!r} status={self.status.value}>"
        )
