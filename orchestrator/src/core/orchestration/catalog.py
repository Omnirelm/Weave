"""Tenant-scoped capability catalog for planners (skills + tools)."""

from __future__ import annotations

import logging
from typing import Any

from src.core.skills import SkillDef, SkillRunner
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)


async def load_tenant_skills(storage: StorageGateway, tenant_id: str) -> list[SkillDef]:
    """Load and validate SkillDef rows for a tenant; skip invalid definitions."""
    rows = await storage.tenant_skills.list_for_tenant(tenant_id)
    skills: list[SkillDef] = []
    for row in rows:
        try:
            skills.append(SkillDef.model_validate(row.definition))
        except Exception:
            logger.warning(
                "Skipping invalid tenant skill definition for tenant=%s skill_id=%s",
                tenant_id,
                row.skill_id,
                exc_info=True,
            )
    return skills


def skills_to_planner_payload(skills: list[SkillDef]) -> list[dict[str, Any]]:
    """Planner-facing skill entries (ids must match invoke_skill skillId)."""
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "whenToUse": s.description,
            "kind": s.kind,
            "capabilities": s.capabilities,
            "input_schema": s.input_schema,
            "output_schema": s.output_schema,
        }
        for s in skills
    ]


async def load_tool_planner_payload(
    runner: SkillRunner, tenant_id: str
) -> list[dict[str, str]]:
    descriptors = await runner.list_tool_descriptors(tenant_id)
    return [{"id": t.name, "description": t.description} for t in descriptors]


async def build_capability_catalog(
    storage: StorageGateway,
    runner: SkillRunner,
    tenant_id: str,
) -> tuple[list[SkillDef], list[dict[str, Any]], list[dict[str, str]]]:
    """Return (validated skills, availableSkills payload, availableTools payload)."""
    skills = await load_tenant_skills(storage, tenant_id)
    available_skills = skills_to_planner_payload(skills)
    available_tools = await load_tool_planner_payload(runner, tenant_id)
    return skills, available_skills, available_tools
