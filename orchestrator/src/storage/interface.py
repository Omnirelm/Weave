"""StorageGateway — single read/write entry point for the rest of the app.

Other packages should depend on this facade only. They never import sessions,
engines, or ORM models directly. This keeps the storage layer swappable
(in-process tests, alternative backends) without leaking SQLAlchemy types.
"""

from __future__ import annotations

from src.storage.db import DatabaseManager
from src.storage.repositories.api_key import ApiKeyRepository
from src.storage.repositories.integration import IntegrationRepository
from src.storage.repositories.quota_usage import QuotaUsageRepository
from src.storage.repositories.task_run import TaskRunRepository
from src.storage.repositories.tenant import TenantRepository
from src.storage.repositories.tenant_agent import TenantAgentRepository
from src.storage.repositories.tenant_workflow import TenantWorkflowRepository


class StorageGateway:
    """Composes all repositories under a single object."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self.tenants = TenantRepository(db)
        self.integrations = IntegrationRepository(db)
        self.api_keys = ApiKeyRepository(db)
        self.quota_usage = QuotaUsageRepository(db)
        self.task_runs = TaskRunRepository(db)
        self.tenant_agents = TenantAgentRepository(db)
        self.tenant_workflows = TenantWorkflowRepository(db)

    @property
    def db(self) -> DatabaseManager:
        return self._db
