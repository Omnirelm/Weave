"""
Integration type and flavour enums shared across API, core, and integrations.

IntegrationType values match TenantIntegrationTypeV1 / DB integration_type column.
Flavour enums identify the specific backend within log and trace categories.
"""
from enum import Enum


class IntegrationType(str, Enum):
    LOG_SOURCE = "LOG_SOURCE"
    TRACE_SOURCE = "TRACE_SOURCE"
    REPOSITORY = "REPOSITORY"
    MCP = "MCP"


class LogSourceFlavour(str, Enum):
    OPENSEARCH = "OPENSEARCH"
    LOKI = "LOKI"
    CLICKHOUSE = "CLICKHOUSE"


class TraceSourceFlavour(str, Enum):
    JAEGER = "JAEGER"
    TEMPO = "TEMPO"
