"""Translators between TenantIntegration ORM rows and integration body models."""

from __future__ import annotations

from typing import Any

from src.api.models.schemas import (
    ClickHouseIntegrationBody,
    GitIntegrationBody,
    IntegrationResponse,
    JaegerIntegrationBody,
    LokiIntegrationBody,
    McpServerIntegrationBody,
    OpenSearchIntegrationBody,
    TempoIntegrationBody,
)
from src.storage.models.integration import TenantIntegration

_SERVER_FIELDS = {"type", "flavour", "active", "id", "created_at", "updated_at"}

_FLAVOUR_TO_CLASS: dict[str, type] = {
    "LOKI": LokiIntegrationBody,
    "OPENSEARCH": OpenSearchIntegrationBody,
    "CLICKHOUSE": ClickHouseIntegrationBody,
    "GIT": GitIntegrationBody,
    "JAEGER": JaegerIntegrationBody,
    "TEMPO": TempoIntegrationBody,
}


def integration_to_response(row: TenantIntegration) -> IntegrationResponse:
    """Convert an ORM row to the appropriate typed integration body."""
    if row.integration_type == "MCP":
        config: dict[str, Any] = row.config or {}
        return McpServerIntegrationBody(
            **config,
            type=row.integration_type,
            flavour=row.flavour,
            id=str(row.id),
            active=row.active,
            created_at=int(row.created_at.timestamp()),
            updated_at=int(row.updated_at.timestamp()),
        )

    cls = _FLAVOUR_TO_CLASS.get(row.flavour)
    if cls is None:
        raise ValueError(f"Unknown integration flavour: {row.flavour!r}")

    config = row.config or {}
    return cls(
        **config,
        type=row.integration_type,
        flavour=row.flavour,
        id=str(row.id),
        active=row.active,
        created_at=int(row.created_at.timestamp()),
        updated_at=int(row.updated_at.timestamp()),
    )


def create_request_to_payload(body: Any) -> dict[str, Any]:
    """Convert a create request body to the DB row payload dict."""
    config = body.model_dump(
        exclude=_SERVER_FIELDS,
        exclude_none=True,
    )
    return {
        "integration_type": body.type,
        "flavour": body.flavour,
        "active": body.active,
        "config": config,
    }


def update_request_to_payload(body: Any) -> dict[str, Any]:
    """Convert an update request body to the DB update payload dict.

    integration_type and flavour are immutable — excluded from update.
    """
    config = body.model_dump(
        exclude=_SERVER_FIELDS,
        exclude_none=True,
    )
    return {
        "active": body.active,
        "config": config,
    }
