"""Generic async repository base.

Concrete repositories override `model` and may add domain-specific queries.
All public methods open their own short-lived session via DatabaseManager.session()
so callers do not need to manage transactions for simple CRUD operations.
"""

from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import select

from src.storage.db import DatabaseManager
from src.storage.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class AbstractRepository(Generic[ModelT]):
    """Common CRUD surface backed by an async SQLAlchemy session."""

    model: ClassVar[type[ModelT]]

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get(self, id: Any) -> ModelT | None:
        async with self._db.session() as session:
            return await session.get(self.model, id)  # type: ignore[return-value]

    async def list(self, *, limit: int | None = None, offset: int | None = None) -> list[ModelT]:
        stmt = select(self.model)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())  # type: ignore[return-value]

    async def create(self, data: dict[str, Any]) -> ModelT:
        instance = self.model(**data)  # type: ignore[call-arg]
        async with self._db.session() as session:
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
        return instance  # type: ignore[return-value]

    async def update(self, id: Any, data: dict[str, Any]) -> ModelT | None:
        async with self._db.session() as session:
            instance = await session.get(self.model, id)
            if instance is None:
                return None
            for key, value in data.items():
                setattr(instance, key, value)
            await session.flush()
            await session.refresh(instance)
            return instance  # type: ignore[return-value]

    async def delete(self, id: Any) -> bool:
        async with self._db.session() as session:
            instance = await session.get(self.model, id)
            if instance is None:
                return False
            await session.delete(instance)
            return True
