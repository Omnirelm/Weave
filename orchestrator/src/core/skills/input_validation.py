"""Validate skill runtime input against the skill YAML ``input_schema`` (JSON Schema)."""

from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import ValidationError

from src.core.skills.base import SkillDef


def validate_skill_instance(skill: SkillDef, instance: dict[str, Any]) -> None:
    """Raise ``ValueError`` when ``instance`` does not satisfy ``skill.input_schema``."""
    schema = skill.input_schema
    if not schema or not isinstance(schema, dict) or len(schema) == 0:
        return
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else ""
        msg = e.message
        if path:
            msg = f"{path}: {msg}"
        raise ValueError(msg) from e
