"""TenantIntegration ORM model — per-tenant integration configs (type + flavour + JSONB)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.storage.models.tenant import Tenant


class TenantIntegration(Base, TimestampMixin):
    """One integration row per (tenant_slug, type, flavour); config holds flavour-specific payload."""

    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_slug",
            "type",
            "flavour",
            name="uq_tenant_integrations_type_flavour",
        ),
    )

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
    # Column name `type` in DB; Python name avoids shadowing builtin `type`.
    integration_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    flavour: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="integrations", lazy="raise")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<TenantIntegration id={self.id} tenant_slug={self.tenant_slug!r} "
            f"type={self.integration_type!r} flavour={self.flavour!r}>"
        )
