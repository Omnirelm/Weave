"""Tenant-defined skill rows — full SkillDef stored in JSONB."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class TenantSkill(Base, TimestampMixin):
    """One row per (tenant, skill_id); definition holds SkillDef.model_dump()."""

    __tablename__ = "tenant_skills"

    tenant_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.slug", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    skill_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="gpt-4.1",
        server_default=text("'gpt-4.1'"),
    )
    definition: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="skills", lazy="raise")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<TenantSkill tenant_slug={self.tenant_slug!r} skill_id={self.skill_id!r}>"
