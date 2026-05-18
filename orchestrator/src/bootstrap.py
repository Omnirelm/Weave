"""Application wiring: logging, tools, skills, and app.state (invoked once at startup)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from src.config.settings import get_config
from src.core.mcp.provider import McpProvider
from src.core.skills import SkillRegistry, SkillRunner
from src.core.tools.base import IntegrationTool
from src.core.tools.provider import ToolProvider
from src.integrations.http.tool import HttpTool
from src.integrations.logs.tools import (
    ClickHouseCleanQueryStringTool,
    ClickHouseFetchLogsTool,
    ClickHouseGetColumnNamesTool,
    ClickHouseGetTableNameTool,
    ClickHouseValidateQueryTool,
    GetLabelNamesTool,
    GetLabelValuesTool,
    LokiCleanQueryStringTool,
    LokiFetchLogsTool,
    LokiValidateQueryTool,
    OpenSearchCleanQueryStringTool,
    OpenSearchFetchLogsTool,
    OpenSearchGetFieldNamesTool,
    OpenSearchGetIndexNameTool,
    OpenSearchValidateQueryTool,
)
from src.storage import get_storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Integration tool registry
#
# Maps the stable tool name (as declared in skill YAML capabilities) to the
# IntegrationTool class responsible for that tool. ToolProvider uses this at
# request time to resolve tools from tenant_integrations rows.
#
# To add a new integration-backed tool, create the class and add one line here.
# ---------------------------------------------------------------------------

INTEGRATION_TOOLS: dict[str, type[IntegrationTool]] = {
    # Loki
    "loki_get_label_names":      GetLabelNamesTool,
    "loki_get_label_values":     GetLabelValuesTool,
    "loki_validate_query":       LokiValidateQueryTool,
    "loki_fetch_logs":           LokiFetchLogsTool,
    "loki_clean_query_string":   LokiCleanQueryStringTool,
    # OpenSearch
    "opensearch_get_field_names":    OpenSearchGetFieldNamesTool,
    "opensearch_validate_query":     OpenSearchValidateQueryTool,
    "opensearch_fetch_logs":         OpenSearchFetchLogsTool,
    "opensearch_clean_query_string": OpenSearchCleanQueryStringTool,
    "opensearch_get_index_name":     OpenSearchGetIndexNameTool,
    # ClickHouse
    "clickhouse_get_table_name":     ClickHouseGetTableNameTool,
    "clickhouse_get_column_names":   ClickHouseGetColumnNamesTool,
    "clickhouse_validate_query":     ClickHouseValidateQueryTool,
    "clickhouse_fetch_logs":         ClickHouseFetchLogsTool,
    "clickhouse_clean_query_string": ClickHouseCleanQueryStringTool,
}


def _redact_db_url(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


async def wire_application(app: FastAPI) -> None:
    """Build providers and attach them to app.state.

    Called once from ASGI lifespan startup (before traffic).
    Tools and MCP servers are no longer registered here — they are resolved
    from tenant_integrations at request time via ToolProvider and McpProvider.
    """
    import src.storage.models  # noqa: F401 — register all ORM mappers

    config = get_config()
    logging.basicConfig(
        level=config.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    storage = get_storage()
    try:
        await storage.db.ping()
        logger.info(
            "Database connection healthy (%s)",
            _redact_db_url(config.database.url),
        )
    except Exception:
        logger.critical(
            "Database unreachable at startup (%s) — shutting down",
            _redact_db_url(config.database.url),
            exc_info=True,
        )
        raise RuntimeError(
            f"Cannot connect to database at {_redact_db_url(config.database.url)}. "
            "Check that PostgreSQL is running and DATABASE__URL is correct."
        ) from None

    tool_provider = ToolProvider(
        storage=storage,
        static_tools=[HttpTool()],
        integration_tools=INTEGRATION_TOOLS,
    )
    logger.info(
        "ToolProvider ready: %d static tool(s), %d integration tool class(es)",
        1,  # HttpTool
        len(INTEGRATION_TOOLS),
    )

    mcp_provider = McpProvider(storage=storage)
    logger.info("McpProvider ready (tenant MCP servers resolved from DB at request time)")

    orchestrator_root = Path(__file__).resolve().parent.parent
    skill_registry = SkillRegistry(skills_root=orchestrator_root / "skills")

    app.state.tool_provider = tool_provider
    app.state.mcp_provider = mcp_provider
    app.state.skill_registry = skill_registry
    app.state.skill_runner = SkillRunner(storage, tool_provider, mcp_provider)
    app.state.storage = storage
