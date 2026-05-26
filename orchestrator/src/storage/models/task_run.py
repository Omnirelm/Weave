"""TaskRun ORM model — one persisted POST /tasks/run execution."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    tenant_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.slug", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    skill_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps_completed: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    step_execution_detail: Mapped[Any | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="v1 JSON: {schemaVersion:1, events:[plan|step,...]} or null",
    )
    cost: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="task_runs", lazy="raise")
