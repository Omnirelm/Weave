"""Repository for tenant_agents rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models.tenant_agent import TenantAgent
from src.storage.repositories.base import AbstractRepository


class TenantAgentRepository(AbstractRepository[TenantAgent]):
    model = TenantAgent

    async def list_for_tenant(self, tenant_slug: str) -> list[TenantAgent]:
        stmt = (
            select(TenantAgent)
            .where(TenantAgent.tenant_slug == tenant_slug)
            .order_by(TenantAgent.agent_id.asc())
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_for_tenant(self, tenant_slug: str, agent_id: str) -> TenantAgent | None:
        async with self._db.session() as session:
            return await session.get(TenantAgent, (tenant_slug, agent_id))

    async def upsert_for_tenant(self, tenant_slug: str, payload: dict[str, Any]) -> TenantAgent:
        agent_id = payload["agent_id"]
        tbl = TenantAgent.__table__
        insert_stmt = pg_insert(tbl).values(
            tenant_slug=tenant_slug,
            agent_id=agent_id,
            name=payload["name"],
            model=payload["model"],
            definition=payload["definition"],
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[tbl.c.tenant_slug, tbl.c.agent_id],
            set_={
                "name": insert_stmt.excluded.name,
                "model": insert_stmt.excluded.model,
                "definition": insert_stmt.excluded.definition,
                "updated_at": func.now(),
            },
        )
        async with self._db.session() as session:
            await session.execute(stmt)
            row = await session.get(TenantAgent, (tenant_slug, agent_id))
            assert row is not None  # noqa: S101
            return row

    async def delete_for_tenant(self, tenant_slug: str, agent_id: str) -> bool:
        stmt = delete(TenantAgent).where(
            TenantAgent.tenant_slug == tenant_slug,
            TenantAgent.agent_id == agent_id,
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return (result.rowcount or 0) > 0

    async def count_for_tenant(self, tenant_slug: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TenantAgent)
            .where(TenantAgent.tenant_slug == tenant_slug)
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())
