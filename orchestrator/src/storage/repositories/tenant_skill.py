"""Repository for tenant_skills rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models.tenant_skill import TenantSkill
from src.storage.repositories.base import AbstractRepository


class TenantSkillRepository(AbstractRepository[TenantSkill]):
    model = TenantSkill

    async def list_for_tenant(self, tenant_slug: str) -> list[TenantSkill]:
        stmt = (
            select(TenantSkill)
            .where(TenantSkill.tenant_slug == tenant_slug)
            .order_by(TenantSkill.skill_id.asc())
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_for_tenant(self, tenant_slug: str, skill_id: str) -> TenantSkill | None:
        async with self._db.session() as session:
            return await session.get(TenantSkill, (tenant_slug, skill_id))

    async def upsert_for_tenant(self, tenant_slug: str, payload: dict[str, Any]) -> TenantSkill:
        """Insert or update by (tenant_slug, skill_id). Sets updated_at on conflict."""
        skill_id = payload["skill_id"]
        tbl = TenantSkill.__table__
        insert_stmt = pg_insert(tbl).values(
            tenant_slug=tenant_slug,
            skill_id=skill_id,
            kind=payload["kind"],
            name=payload["name"],
            model=payload["model"],
            definition=payload["definition"],
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[tbl.c.tenant_slug, tbl.c.skill_id],
            set_={
                "kind": insert_stmt.excluded.kind,
                "name": insert_stmt.excluded.name,
                "model": insert_stmt.excluded.model,
                "definition": insert_stmt.excluded.definition,
                "updated_at": func.now(),
            },
        )
        async with self._db.session() as session:
            await session.execute(stmt)
            row = await session.get(TenantSkill, (tenant_slug, skill_id))
            assert row is not None  # noqa: S101
            return row

    async def delete_for_tenant(self, tenant_slug: str, skill_id: str) -> bool:
        stmt = delete(TenantSkill).where(
            TenantSkill.tenant_slug == tenant_slug,
            TenantSkill.skill_id == skill_id,
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return (result.rowcount or 0) > 0

    async def count_for_tenant(self, tenant_slug: str) -> int:
        stmt = select(func.count()).select_from(TenantSkill).where(TenantSkill.tenant_slug == tenant_slug)
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())
