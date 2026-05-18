"""Tenant API key lookup by hash."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from src.storage.db import DatabaseManager
from src.storage.models.tenant_api_key import TenantApiKey


class ApiKeyRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get_active_by_hash(self, key_hash: str) -> TenantApiKey | None:
        async with self._db.session() as session:
            stmt = select(TenantApiKey).where(
                TenantApiKey.key_hash == key_hash,
                TenantApiKey.revoked_at.is_(None),
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_key(self, *, tenant_slug: str, key_prefix: str, key_hash: str) -> TenantApiKey:
        payload: dict[str, Any] = {
            "id": uuid.uuid4(),
            "tenant_slug": tenant_slug,
            "key_prefix": key_prefix,
            "key_hash": key_hash,
        }
        row = TenantApiKey(**payload)
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            await session.refresh(row)
        return row
