"""Tests for JSON Schema validation of skill output."""

from __future__ import annotations

import json

import pytest

from src.core.skills.base import SkillDef
from src.core.skills.output_validation import (
    SkillOutputError,
    validate_skill_output,
    validate_skill_output_or_model_error,
)


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


def test_validate_skill_output_no_schema_is_noop() -> None:
    skill = _minimal_skill(output_schema=None)
    validate_skill_output(skill, {"anything": True})


def test_validate_skill_output_empty_schema_is_noop() -> None:
    skill = _minimal_skill(output_schema={})
    validate_skill_output(skill, {})


def test_validate_skill_output_success() -> None:
    skill = _minimal_skill(
        output_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )
    validate_skill_output(skill, {"name": "ok", "extra": 1})


def test_validate_skill_output_missing_required() -> None:
    skill = _minimal_skill(
        output_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )
    with pytest.raises(ValueError, match="name"):
        validate_skill_output(skill, {})


def test_validate_skill_output_or_model_error_bad_json() -> None:
    skill = _minimal_skill(
        output_schema={
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
    )
    with pytest.raises(SkillOutputError, match="JSON"):
        validate_skill_output_or_model_error(skill, "not json")


def test_validate_skill_output_or_model_error_invalid_instance() -> None:
    skill = _minimal_skill(
        output_schema={
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
    )
    raw = json.dumps({"x": "nope"})
    with pytest.raises(SkillOutputError):
        validate_skill_output_or_model_error(skill, raw)
