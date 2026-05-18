from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from src.core.base import InvocationCost


class SkillStep(BaseModel):
    id: str
    type: Literal["invoke_skill", "invoke_tool", "synthesize"]
    skill_id: str | None = None
    tool_id: str | None = None
    objective: str
    params: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_ids(self) -> Self:
        if self.type == "invoke_skill" and not self.skill_id:
            raise ValueError("invoke_skill step requires skill_id")
        if self.type == "invoke_tool" and not self.tool_id:
            raise ValueError("invoke_tool step requires tool_id")
        return self


class StepResult(BaseModel):
    step_id: str
    objective: str
    success: bool
    output: Any = None
    error: str | None = None
    """When this step invoked a sub-skill or tool, the target id (for audit / UI)."""
    invoked_skill_id: str | None = None
    invoked_tool_id: str | None = None


class SkillRunContext(BaseModel):
    """Execution-time accumulator. This object is not persisted."""

    original_input: dict[str, Any]
    steps_completed: list[StepResult] = Field(default_factory=list)


class SkillDef(BaseModel):
    id: str
    name: str
    description: str
    instructions: str = ""
    kind: Literal["simple", "composed"] = "simple"
    capabilities: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    steps: list[SkillStep] = Field(default_factory=list)
    model: str = "gpt-4.1"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "For simple skills: JSON Schema for structured LLM output. "
            "For composed skills: unused at runtime (effective shape is the last step's output); "
            "omit or leave null."
        ),
    )

    @model_validator(mode="after")
    def _check_kind(self) -> Self:
        if self.kind == "simple" and not self.instructions.strip():
            raise ValueError("simple skill requires instructions")
        if self.kind == "composed" and not self.steps:
            raise ValueError("composed skill requires at least one step")
        return self


class SkillInput(BaseModel):
    skill_id: str
    input: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"


class SkillResult(BaseModel):
    success: bool
    output: Any = None
    error: str | None = None
    cost: InvocationCost | None = None
    """Inner steps for composed skills; empty for simple skills."""
    steps_completed: list[StepResult] = Field(default_factory=list)
