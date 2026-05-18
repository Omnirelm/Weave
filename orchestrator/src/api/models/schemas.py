"""Public API surface for all request/response models.

Re-exports every generated schema from models/models/ and extends them with
hand-crafted subclasses, enums, and discriminated unions that cannot be produced
by the OpenAPI generator.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from .models.click_house_v1 import ClickHouseV1
from .models.code_repository_v1 import CodeRepositoryV1
from .models.error_response import ErrorResponse
from .models.health_response import HealthResponse
from .models.invocation_cost_dto import InvocationCostDto
from .models.jaeger_v1 import JaegerV1
from .models.log_source_auth_api_key_v1 import LogSourceAuthAPIKeyV1
from .models.log_source_auth_basic_v1 import LogSourceAuthBasicV1
from .models.log_source_auth_bearer_v1 import LogSourceAuthBearerV1
from .models.log_source_auth_mechanism_v1 import LogSourceAuthMechanismV1
from .models.log_source_auth_o_auth_v1 import LogSourceAuthOAuthV1
from .models.log_source_o_auth_config_v1 import LogSourceOAuthConfigV1
from .models.log_source_v1 import LogSourceV1
from .models.loki_v1 import LokiV1
from .models.mcp_server_v1 import McpServerV1
from .models.open_search_v1 import OpenSearchV1
from .models.page import Page
from .models.run_task_request import RunTaskRequest
from .models.run_task_response import RunTaskResponse
from .models.skill_resource import SkillResource
from .models.skill_step_resource import SkillStepResource
from .models.step_result_dto import StepResultDto
from .models.tempo_v1 import TempoV1
from .models.tenant_integration_type_v1 import TenantIntegrationTypeV1
from .models.tenant_integration_v1 import TenantIntegrationV1
from .models.tenant_v1 import TenantV1
from .models.tool_v1 import ToolV1
from .models.tools_page_response import ToolsPageResponse
from .models.trace_source_v1 import TraceSourceV1


class Type(str, Enum):
    invoke_skill = "invoke_skill"
    invoke_tool = "invoke_tool"
    synthesize = "synthesize"


class Kind(str, Enum):
    simple = "simple"
    composed = "composed"


class CreateTenantRequest(TenantV1):
    pass


TenantResource = TenantV1


class PatchTenantToolConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, Any]


class ExecuteSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: dict[str, Any]
    context: dict[str, Any] | None = {}
    tool_config: dict[str, Any] | None = {}


class ExecuteSkillResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    cost: InvocationCostDto | None = None


# ---------------------------------------------------------------------------
# Integration discriminated-union models
# Each subclass extends a generated leaf model, narrows type/flavour to
# Literal, adds active + server-side fields (id, timestamps), and
# provides a validate() method for domain-level checks.
# ---------------------------------------------------------------------------

class LokiIntegrationBody(LokiV1):
    type: Literal["LOG_SOURCE"]
    flavour: Literal["LOKI"]
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        pass  # url already required by LokiV1


class OpenSearchIntegrationBody(OpenSearchV1):
    type: Literal["LOG_SOURCE"]
    flavour: Literal["OPENSEARCH"]
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        pass  # url already required by OpenSearchV1


class ClickHouseIntegrationBody(ClickHouseV1):
    type: Literal["LOG_SOURCE"]
    flavour: Literal["CLICKHOUSE"]
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        pass  # url + database + table already required by ClickHouseV1


class GitIntegrationBody(CodeRepositoryV1):
    type: Literal["REPOSITORY"]
    flavour: Literal["GIT"]
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        pass  # pat minLength:1 already enforced by CodeRepositoryV1


class JaegerIntegrationBody(JaegerV1):
    type: Literal["TRACE_SOURCE"]
    flavour: Literal["JAEGER"]
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        pass  # url already required by JaegerV1


class TempoIntegrationBody(TempoV1):
    type: Literal["TRACE_SOURCE"]
    flavour: Literal["TEMPO"]
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        pass  # url already required by TempoV1


class McpServerIntegrationBody(McpServerV1):
    type: Literal["MCP"]
    flavour: str
    active: bool = True
    id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None

    def validate(self) -> None:
        if self.transport in ("sse", "streamable_http") and not (self.url or "").strip():
            raise ValueError(f"MCP transport {self.transport!r} requires url")
        if self.transport == "stdio" and not (self.command or "").strip():
            raise ValueError("MCP transport 'stdio' requires command")


# Level-2 unions: within each type, discriminate by flavour.
_LogSourceUnion = Annotated[
    Union[LokiIntegrationBody, OpenSearchIntegrationBody, ClickHouseIntegrationBody],
    Field(discriminator="flavour"),
]
_TraceSourceUnion = Annotated[
    Union[JaegerIntegrationBody, TempoIntegrationBody],
    Field(discriminator="flavour"),
]

# Public aliases for type hints and extensibility.
LogSourceIntegration   = _LogSourceUnion
RepositoryIntegration  = GitIntegrationBody
TraceSourceIntegration = _TraceSourceUnion

# Top-level union: type is the first discriminator, flavour is the second.
# Missing type  → "Unable to extract tag using discriminator 'type'"
# Wrong flavour → "Unable to extract tag using discriminator 'flavour'"
_IntegrationUnion = Annotated[
    Union[
        _LogSourceUnion,
        GitIntegrationBody,
        _TraceSourceUnion,
        McpServerIntegrationBody,
    ],
    Field(discriminator="type"),
]

CreateIntegrationRequest = _IntegrationUnion
UpdateIntegrationRequest = _IntegrationUnion
IntegrationResponse      = _IntegrationUnion
