"""Repository for Tenant rows."""

from __future__ import annotations

from src.storage.models.tenant import Tenant
from src.storage.repositories.base import AbstractRepository


class TenantRepository(AbstractRepository[Tenant]):
    model = Tenant

    async def get_by_slug(self, slug: str) -> Tenant | None:
        return await self.get(slug)
