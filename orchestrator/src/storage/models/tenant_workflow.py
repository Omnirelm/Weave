"""One row per (tenant, workflow_id); definition holds WorkflowDef.model_dump()."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class TenantWorkflow(Base, TimestampMixin):
    __tablename__ = "tenant_workflows"

    tenant_slug: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.slug", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    workflow_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="workflows", lazy="raise")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<TenantWorkflow tenant_slug={self.tenant_slug!r} "
            f"workflow_id={self.workflow_id!r}>"
        )
