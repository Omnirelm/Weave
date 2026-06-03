"""Validate skill runtime output against the skill YAML ``output_schema`` (JSON Schema)."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
from jsonschema import ValidationError

from src.core.skills.base import SkillDef


class SkillOutputError(ValueError):
    """Raised when skill LLM output is not valid JSON or fails output_schema validation."""


def validate_skill_output(skill: SkillDef, instance: Any) -> None:
    """Raise ``ValueError`` when ``instance`` does not satisfy ``skill.output_schema``."""
    schema = skill.output_schema
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


def validate_skill_output_or_model_error(skill: SkillDef, json_str: str) -> Any:
    """Parse JSON and validate against ``skill.output_schema``; raise ``SkillOutputError`` on failure."""
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise SkillOutputError(f"Skill output is not valid JSON: {e}") from e
    try:
        validate_skill_output(skill, parsed)
    except ValueError as e:
        raise SkillOutputError(str(e)) from e
    return parsed
