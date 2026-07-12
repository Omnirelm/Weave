"""Public API surface for all request/response models.

Re-exports every generated schema from models/models/ and extends them with
hand-crafted subclasses, enums, and discriminated unions that cannot be produced
by the OpenAPI generator.
"""
from __future__ import annotations

from typing import Annotated, Union

from pydantic import AliasChoices, Field, model_validator

from typing_extensions import Literal, Self

from .models.agent_resource import AgentResource
from .models.workflow_edge_resource import WorkflowEdgeResource
from .models.workflow_node_resource import WorkflowNodeResource
from .models.workflow_resource import WorkflowResource
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
from .models.run_task_request import RunTaskRequest as _GeneratedRunTaskRequest
from .models.run_task_response import RunTaskResponse
from .models.tempo_v1 import TempoV1
from .models.tenant_integration_type_v1 import TenantIntegrationTypeV1
from .models.tenant_v1 import TenantV1
from .models.tool_v1 import ToolV1
from .models.tools_page_response import ToolsPageResponse
from .models.model_v1 import ModelV1
from .models.models_page_response import ModelsPageResponse
from .models.trace_source_v1 import TraceSourceV1


class CreateTenantRequest(TenantV1):
    pass


class RunTaskRequest(_GeneratedRunTaskRequest):
    @model_validator(mode="after")
    def validate_execution_target(self) -> Self:
        has_agent = bool(self.agent_id and str(self.agent_id).strip())
        has_workflow = bool(self.workflow_id and str(self.workflow_id).strip())
        if not has_agent and not has_workflow:
            raise ValueError("workflow_id or agent_id is required")
        if has_agent and has_workflow:
            raise ValueError("Provide workflow_id or agent_id, not both")
        return self


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
    base_path: str | None = Field(
        default=None,
        description=(
            "Optional path prefix before /api/v3 on the Jaeger query service "
            "(e.g. '/jaeger/ui' when jaeger_query.base_path is configured)."
        ),
        validation_alias=AliasChoices("basePath", "base_path"),
        serialization_alias="basePath",
    )

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
    auth_mechanism: LogSourceAuthMechanismV1 | None = None

    def validate(self) -> None:
        if self.transport in ("sse", "streamable_http") and not (self.url or "").strip():
            raise ValueError(f"MCP transport {self.transport!r} requires url")
        if self.transport == "stdio" and not (self.command or "").strip():
            raise ValueError("MCP transport 'stdio' requires command")
        # Auth mechanism validation
        if self.auth_mechanism:
            self._validate_auth_mechanism()

    def _validate_auth_mechanism(self) -> None:
        auth = self.auth_mechanism
        mechanisms = [auth.basic, auth.bearer, auth.oauth, auth.api_key]
        active = [m for m in mechanisms if m is not None]
        if len(active) > 1:
            raise ValueError("Only one auth mechanism can be specified")
        if auth.basic:
            if not (auth.basic.username or "").strip():
                raise ValueError("Basic auth requires username")
            if not (auth.basic.password or "").strip():
                raise ValueError("Basic auth requires password")
        if auth.bearer:
            if not (auth.bearer.token or "").strip():
                raise ValueError("Bearer auth requires token")
        if auth.oauth:
            cfg = auth.oauth.oauth_config
            if not cfg or not (cfg.token_url or "").strip():
                raise ValueError("OAuth requires token_url")
        if auth.api_key:
            if not (auth.api_key.api_key or "").strip():
                raise ValueError("API key auth requires api_key")
            if not (auth.api_key.api_key_header_name or "").strip():
                raise ValueError("API key auth requires api_key_header_name")


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

TenantIntegrationV1 = _IntegrationUnion
CreateIntegrationRequest = TenantIntegrationV1
UpdateIntegrationRequest = TenantIntegrationV1
IntegrationResponse = TenantIntegrationV1


from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from typing import Any

class TaskRunResponse(BaseModel):
    id: UUID
    tenant_slug: str
    success: bool
    objective: str
    agent_id: str | None = None
    workflow_id: str | None = None
    request_context: Any = None
    output: dict[str, Any] | None = None
    summary: str | None = None
    reasoning: str | None = None
    error: str | None = None
    step_execution_detail: Any = None
    cost: InvocationCostDto | None = None
    started_at: datetime
    finished_at: datetime

