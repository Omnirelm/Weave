"""Repository for TenantIntegration rows with tenant-scoped access."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from src.storage.models.integration import TenantIntegration
from src.storage.repositories.base import AbstractRepository


def _normalize_create_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Map API-style `type` key to ORM attribute `integration_type`."""
    payload = dict(data)
    if "type" in payload and "integration_type" not in payload:
        payload["integration_type"] = payload.pop("type")
    elif "type" in payload and "integration_type" in payload:
        payload.pop("type", None)
    return payload


def _normalize_update_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Same as create; drop tenant_slug so integrations cannot move tenants."""
    payload = _normalize_create_payload(data)
    payload.pop("tenant_slug", None)
    payload.pop("id", None)
    return payload


class IntegrationRepository(AbstractRepository[TenantIntegration]):
    model = TenantIntegration

    async def list_for_tenant(
        self,
        tenant_slug: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TenantIntegration]:
        stmt = (
            select(TenantIntegration)
            .where(TenantIntegration.tenant_slug == tenant_slug)
            .order_by(TenantIntegration.created_at.desc())
        )
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_for_tenant(
        self,
        tenant_slug: str,
        integration_id: uuid.UUID,
    ) -> TenantIntegration | None:
        stmt = select(TenantIntegration).where(
            TenantIntegration.tenant_slug == tenant_slug,
            TenantIntegration.id == integration_id,
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_for_tenant(
        self,
        tenant_slug: str,
        data: dict[str, Any],
    ) -> TenantIntegration:
        payload = _normalize_create_payload(data)
        payload["tenant_slug"] = tenant_slug
        return await self.create(payload)

    async def update_for_tenant(
        self,
        tenant_slug: str,
        integration_id: uuid.UUID,
        data: dict[str, Any],
    ) -> TenantIntegration | None:
        existing = await self.get_for_tenant(tenant_slug, integration_id)
        if existing is None:
            return None
        payload = _normalize_update_payload(data)
        return await self.update(integration_id, payload)

    async def delete_for_tenant(self, tenant_slug: str, integration_id: uuid.UUID) -> bool:
        existing = await self.get_for_tenant(tenant_slug, integration_id)
        if existing is None:
            return False
        return await self.delete(integration_id)
