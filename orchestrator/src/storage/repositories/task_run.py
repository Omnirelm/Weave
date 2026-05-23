"""Repository for TaskRun rows."""

from __future__ import annotations

from src.storage.db import DatabaseManager
from src.storage.models.task_run import TaskRun
from src.storage.repositories.base import AbstractRepository


class TaskRunRepository(AbstractRepository[TaskRun]):
    model = TaskRun
