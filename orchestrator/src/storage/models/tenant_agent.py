"""One row per (tenant, agent_id); definition holds AgentDef.model_dump()."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class TenantAgent(Base, TimestampMixin):
    __tablename__ = "tenant_agents"

    tenant_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.slug", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="gemini/gemini-3.5-flash",
        server_default=text("'gemini/gemini-3.5-flash'"),
    )
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="agents", lazy="raise")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<TenantAgent tenant_slug={self.tenant_slug!r} agent_id={self.agent_id!r}>"
