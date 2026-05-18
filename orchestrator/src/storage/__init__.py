"""Storage package — async PostgreSQL driver behind a single StorageGateway facade.

Public API:
    >>> from src.storage import get_storage
    >>> storage = get_storage()
    >>> tenant = await storage.tenants.get_by_slug("acme")
"""

from functools import lru_cache

from src.storage.db import DatabaseManager, get_database
from src.storage.interface import StorageGateway
@lru_cache(maxsize=1)
def get_storage() -> StorageGateway:
    """Process-wide singleton StorageGateway."""
    return StorageGateway(get_database())


__all__ = [
    "DatabaseManager",
    "StorageGateway",
    "get_database",
    "get_storage",
]
