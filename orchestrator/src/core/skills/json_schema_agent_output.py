"""Agent structured output from a JSON Schema object (e.g. skill YAML ``output_schema``)."""

from __future__ import annotations

from typing import Any

from agents.agent_output import AgentOutputSchemaBase

from src.core.skills.base import SkillDef
from src.core.skills.output_validation import validate_skill_output_or_model_error


class SkillJsonSchemaOutput(AgentOutputSchemaBase):
    """Feeds the model a JSON Schema from ``SkillDef.output_schema`` and validates responses."""

    def __init__(self, skill: SkillDef, *, strict_json_schema: bool = False) -> None:
        schema = skill.output_schema
        if not schema or not isinstance(schema, dict):
            raise ValueError("SkillJsonSchemaOutput requires a non-empty output_schema dict")
        self._skill = skill
        self._schema = schema
        self._strict = strict_json_schema

    def is_plain_text(self) -> bool:
        return False

    def name(self) -> str:
        return f"skill_output:{self._skill.id}"

    def json_schema(self) -> dict[str, Any]:
        return self._schema

    def is_strict_json_schema(self) -> bool:
        return self._strict

    def validate_json(self, json_str: str) -> Any:
        return validate_skill_output_or_model_error(self._skill, json_str)
