"""Tests for JSON Schema validation of skill input."""

from __future__ import annotations

import pytest

from src.core.skills.base import SkillDef
from src.core.skills.input_validation import validate_skill_instance


def _minimal_skill(**kwargs: object) -> SkillDef:
    base = {
        "id": "test_skill",
        "name": "Test",
        "description": "Test skill",
        "instructions": "Do something.",
        "kind": "simple",
    }
    base.update(kwargs)
    return SkillDef.model_validate(base)


def test_validate_skill_instance_no_schema_is_noop() -> None:
    skill = _minimal_skill(input_schema=None)
    validate_skill_instance(skill, {"anything": True})


def test_validate_skill_instance_empty_schema_is_noop() -> None:
    skill = _minimal_skill(input_schema={})
    validate_skill_instance(skill, {})


def test_validate_skill_instance_success() -> None:
    skill = _minimal_skill(
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )
    validate_skill_instance(skill, {"name": "ok", "extra": 1})


def test_validate_skill_instance_missing_required() -> None:
    skill = _minimal_skill(
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )
    with pytest.raises(ValueError, match="name"):
        validate_skill_instance(skill, {})


def test_validate_skill_instance_wrong_type() -> None:
    skill = _minimal_skill(
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        }
    )
    with pytest.raises(ValueError, match="count"):
        validate_skill_instance(skill, {"count": "not-int"})
