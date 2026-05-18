"""Rules for composed skill definitions (step targets, nesting)."""

from __future__ import annotations

from src.core.skills.base import SkillDef
from src.storage.interface import StorageGateway


async def validate_composed_invoke_targets_not_composed(
    storage: StorageGateway,
    tenant_id: str,
    skill: SkillDef,
) -> None:
    """Each invoke_skill step on a composed skill must target a simple skill (tenant DB)."""
    if skill.kind != "composed":
        return
    for step in skill.steps:
        if step.type != "invoke_skill" or not step.skill_id:
            continue
        row = await storage.tenant_skills.get_for_tenant(tenant_id, step.skill_id)
        if row is None:
            msg = (
                f"Composed skill {skill.id!r}: step {step.id!r} references unknown skill "
                f"{step.skill_id!r}"
            )
            raise ValueError(msg)
        child = SkillDef.model_validate(row.definition)
        if child.kind == "composed":
            msg = (
                f"Composed skill {skill.id!r}: step {step.id!r} must not invoke another composed "
                f"skill ({step.skill_id!r})"
            )
            raise ValueError(msg)


def assert_composed_invokes_resolve_to_simple_skills(
    skill: SkillDef,
    definitions_by_id: dict[str, SkillDef],
    *,
    context: str,
) -> None:
    """Validate invoke_skill targets exist and are simple (for YAML registry loads)."""
    if skill.kind != "composed":
        return
    for step in skill.steps:
        if step.type != "invoke_skill" or not step.skill_id:
            continue
        child = definitions_by_id.get(step.skill_id)
        if child is None:
            raise ValueError(
                f"{context}: composed skill {skill.id!r} step {step.id!r} references unknown "
                f"skill {step.skill_id!r}",
            )
        if child.kind == "composed":
            raise ValueError(
                f"{context}: composed skill {skill.id!r} step {step.id!r} must not invoke composed "
                f"skill {step.skill_id!r}",
            )
