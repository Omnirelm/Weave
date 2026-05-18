"""Skill registry for built-in and tenant-defined skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.core.skills import SkillDef
from src.core.skills.composition_validation import assert_composed_invokes_resolve_to_simple_skills


class SkillRegistry:
    """Registry that merges built-in and tenant-specific YAML skills."""

    def __init__(self, skills_root: Path | None = None) -> None:
        self._skills_root = skills_root or Path(__file__).resolve().parents[3] / "skills"
        self._builtins = self._load_builtin_skills()
        self._tenant_overrides: dict[str, dict[str, SkillDef]] = {}

    def list_skills(self, tenant_id: str) -> list[SkillDef]:
        merged: dict[str, SkillDef] = {}
        merged.update(self._builtins)
        merged.update(self._load_tenant_skills(tenant_id))
        merged.update(self._tenant_overrides.get(tenant_id, {}))
        return list(merged.values())

    def get(self, skill_id: str, tenant_id: str) -> SkillDef:
        override = self._tenant_overrides.get(tenant_id, {}).get(skill_id)
        if override is not None:
            return override

        tenant_skill = self._load_tenant_skills(tenant_id).get(skill_id)
        if tenant_skill is not None:
            return tenant_skill

        builtin = self._builtins.get(skill_id)
        if builtin is not None:
            return builtin

        raise KeyError(f"Unknown skill_id: {skill_id!r}")

    def register(self, skill_def: SkillDef, tenant_id: str) -> SkillDef:
        overrides = self._tenant_overrides.setdefault(tenant_id, {})
        overrides[skill_def.id] = skill_def
        return skill_def

    def save(self, skill_def: SkillDef, tenant_id: str) -> SkillDef:
        self.register(skill_def, tenant_id)
        tenant_dir = self._tenant_dir(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        skill_path = tenant_dir / f"{skill_def.id}.yaml"
        payload = skill_def.model_dump(mode="python")
        skill_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return skill_def

    def delete(self, skill_id: str, tenant_id: str) -> None:
        if tenant_id in self._tenant_overrides:
            self._tenant_overrides[tenant_id].pop(skill_id, None)

        skill_path = self._tenant_dir(tenant_id) / f"{skill_id}.yaml"
        if skill_path.exists():
            skill_path.unlink()
            return

        if skill_id in self._builtins:
            raise ValueError(f"Built-in skill is read-only and cannot be deleted: {skill_id}")

        raise KeyError(f"Unknown tenant skill: {skill_id!r}")

    def _tenant_dir(self, tenant_id: str) -> Path:
        return self._skills_root / tenant_id

    def _load_builtin_skills(self) -> dict[str, SkillDef]:
        defaults_dir = self._skills_root / "defaults"
        if not defaults_dir.exists():
            return {}

        builtins: dict[str, SkillDef] = {}
        for path in sorted(defaults_dir.glob("*.y*ml")):
            payload = self._load_yaml_payload(path.read_text(encoding="utf-8"), str(path))
            if "id" not in payload:
                payload["id"] = path.stem
            skill = self._validate_skill(payload, str(path))
            builtins[skill.id] = skill
        for sid, skill in builtins.items():
            assert_composed_invokes_resolve_to_simple_skills(
                skill, builtins, context=f"built-in skill {sid!r}"
            )
        return builtins

    def _load_tenant_skills(self, tenant_id: str) -> dict[str, SkillDef]:
        tenant_dir = self._tenant_dir(tenant_id)
        if not tenant_dir.exists():
            return {}

        tenant_skills: dict[str, SkillDef] = {}
        for path in sorted(tenant_dir.glob("*.y*ml")):
            payload = self._load_yaml_payload(path.read_text(encoding="utf-8"), str(path))
            if "id" not in payload:
                payload["id"] = path.stem
            skill = self._validate_skill(payload, str(path))
            tenant_skills[skill.id] = skill
        merged = {**self._builtins, **tenant_skills}
        for sid, skill in tenant_skills.items():
            assert_composed_invokes_resolve_to_simple_skills(
                skill, merged, context=f"tenant {tenant_id!r} skill {sid!r}"
            )
        return tenant_skills

    def _load_yaml_payload(self, content: str, source: str) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError(f"Malformed YAML in {source}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Expected mapping in YAML file {source}")
        return payload

    def _validate_skill(self, payload: dict[str, Any], source: str) -> SkillDef:
        try:
            return SkillDef.model_validate(payload)
        except Exception as exc:
            raise ValueError(f"Invalid skill definition in {source}: {exc}") from exc
