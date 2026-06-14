"""Repository for tenant_workflows rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models.tenant_workflow import TenantWorkflow
from src.storage.repositories.base import AbstractRepository


class TenantWorkflowRepository(AbstractRepository[TenantWorkflow]):
    model = TenantWorkflow

    async def list_for_tenant(self, tenant_slug: str) -> list[TenantWorkflow]:
        stmt = (
            select(TenantWorkflow)
            .where(TenantWorkflow.tenant_slug == tenant_slug)
            .order_by(TenantWorkflow.workflow_id.asc())
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_for_tenant(
        self, tenant_slug: str, workflow_id: str
    ) -> TenantWorkflow | None:
        async with self._db.session() as session:
            return await session.get(TenantWorkflow, (tenant_slug, workflow_id))

    async def upsert_for_tenant(
        self, tenant_slug: str, payload: dict[str, Any]
    ) -> TenantWorkflow:
        workflow_id = payload["workflow_id"]
        tbl = TenantWorkflow.__table__
        insert_stmt = pg_insert(tbl).values(
            tenant_slug=tenant_slug,
            workflow_id=workflow_id,
            name=payload["name"],
            definition=payload["definition"],
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[tbl.c.tenant_slug, tbl.c.workflow_id],
            set_={
                "name": insert_stmt.excluded.name,
                "definition": insert_stmt.excluded.definition,
                "updated_at": func.now(),
            },
        )
        async with self._db.session() as session:
            await session.execute(stmt)
            row = await session.get(TenantWorkflow, (tenant_slug, workflow_id))
            assert row is not None  # noqa: S101
            return row

    async def delete_for_tenant(self, tenant_slug: str, workflow_id: str) -> bool:
        stmt = delete(TenantWorkflow).where(
            TenantWorkflow.tenant_slug == tenant_slug,
            TenantWorkflow.workflow_id == workflow_id,
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return (result.rowcount or 0) > 0

    async def count_for_tenant(self, tenant_slug: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TenantWorkflow)
            .where(TenantWorkflow.tenant_slug == tenant_slug)
        )
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())
