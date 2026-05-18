"""
Log tools for Loki, OpenSearch, and ClickHouse backends.

Each flavour has a base class (LokiTool, OpenSearchTool, ClickHouseTool) that
declares the integration_type/flavour and implements from_config. Concrete tools
extend the flavour base and only define their execute/as_function_tool logic.

Adding a new tool for an existing backend:
  1. Subclass the flavour base (e.g. LokiTool).
  2. Assign name and description class attributes.
  3. Implement execute() and as_function_tool().
  4. Register the class in bootstrap.py INTEGRATION_TOOLS.
"""

from __future__ import annotations

import datetime
import logging
from abc import ABC
from typing import Any, ClassVar, List

from agents.tool import function_tool

from src.core.tools.base import IntegrationTool
from src.integrations.flavours import IntegrationType, LogSourceFlavour
from src.integrations.logs.base import LogEntry
from src.integrations.logs.clickhouse import ClickHouseExtractor
from src.integrations.logs.loki import GrafanaLokiExtractor
from src.integrations.logs.opensearch import OpenSearchExtractor
from src.integrations.logs.registry import LogSourceSpec, get_log_extractor

logger = logging.getLogger(__name__)


def _parse_datetime(value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s)
    raise TypeError(f"Expected datetime or ISO string, got {type(value)!r}")


# ---------------------------------------------------------------------------
# Flavour base classes — one per backend
# ---------------------------------------------------------------------------

class LokiTool(IntegrationTool, ABC):
    """Base for all Loki tools. Declares the integration and builds the extractor."""

    integration_type: ClassVar[str] = IntegrationType.LOG_SOURCE
    integration_flavour: ClassVar[str] = LogSourceFlavour.LOKI

    def __init__(self, extractor: GrafanaLokiExtractor) -> None:
        self._extractor = extractor

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LokiTool":
        spec = LogSourceSpec.model_validate(config)
        extractor = get_log_extractor(spec)
        return cls(extractor)  # type: ignore[return-value]


class OpenSearchTool(IntegrationTool, ABC):
    """Base for all OpenSearch tools."""

    integration_type: ClassVar[str] = IntegrationType.LOG_SOURCE
    integration_flavour: ClassVar[str] = LogSourceFlavour.OPENSEARCH

    def __init__(self, extractor: OpenSearchExtractor) -> None:
        self._extractor = extractor

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "OpenSearchTool":
        spec = LogSourceSpec.model_validate(config)
        extractor = get_log_extractor(spec)
        return cls(extractor)  # type: ignore[return-value]


class ClickHouseTool(IntegrationTool, ABC):
    """Base for all ClickHouse tools."""

    integration_type: ClassVar[str] = IntegrationType.LOG_SOURCE
    integration_flavour: ClassVar[str] = LogSourceFlavour.CLICKHOUSE

    def __init__(self, extractor: ClickHouseExtractor) -> None:
        self._extractor = extractor

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ClickHouseTool":
        spec = LogSourceSpec.model_validate(config)
        extractor = get_log_extractor(spec)
        return cls(extractor)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Loki tools
# ---------------------------------------------------------------------------

class GetLabelNamesTool(LokiTool):
    name: ClassVar[str] = "loki_get_label_names"
    description: ClassVar[str] = "Get available label names from Loki."

    def execute(self, **kwargs: Any) -> List[str]:
        if kwargs:
            raise TypeError("loki_get_label_names takes no arguments")
        return self._extractor.get_label_names()

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def loki_get_label_names() -> List[str]:
            """Get available label names from Loki."""
            return ext.get_label_names()

        return loki_get_label_names


class GetLabelValuesTool(LokiTool):
    name: ClassVar[str] = "loki_get_label_values"
    description: ClassVar[str] = "Get available values for a specific label name from Loki."

    def execute(self, **kwargs: Any) -> List[str]:
        label_name = kwargs.get("label_name")
        if label_name is None:
            raise TypeError("loki_get_label_values requires label_name")
        return self._extractor.get_label_values(label_name)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def loki_get_label_values(label_name: str) -> List[str]:
            """Get available values for a specific label name from Loki.

            Args:
                label_name: The name of the label to get values for
            """
            return ext.get_label_values(label_name)

        return loki_get_label_values


class LokiValidateQueryTool(LokiTool):
    name: ClassVar[str] = "loki_validate_query"
    description: ClassVar[str] = "Fetch logs from Loki using a query."

    def execute(self, **kwargs: Any) -> List[LogEntry]:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("loki_validate_query requires query")
        start = _parse_datetime(kwargs["start"]) if kwargs.get("start") is not None else None
        end = _parse_datetime(kwargs["end"]) if kwargs.get("end") is not None else None
        limit = kwargs.get("limit", 100)
        logger.info("Validating query: %s from %s to %s", query, start, end)
        result = self._extractor.fetch_logs(query, start=start, end=end, limit=limit)
        logger.info("Result: %d logs fetched", len(result))
        return result

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def loki_validate_query(
            query: str,
            start: datetime.datetime | None = None,
            end: datetime.datetime | None = None,
            limit: int = 100,
        ) -> List[LogEntry]:
            """Fetch logs from Loki using a query. start and end are optional; if omitted the last 100 logs are returned."""
            logger.info("Validating query: %s from %s to %s", query, start, end)
            result = ext.fetch_logs(query, start=start, end=end, limit=limit)
            logger.info("Result: %d logs fetched", len(result))
            return result

        return loki_validate_query


class LokiFetchLogsTool(LokiTool):
    name: ClassVar[str] = "loki_fetch_logs"
    description: ClassVar[str] = "Fetch logs from Loki using a query and optional time range."

    def execute(self, **kwargs: Any) -> List[LogEntry]:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("loki_fetch_logs requires query")
        start = _parse_datetime(kwargs["start"]) if kwargs.get("start") is not None else None
        end = _parse_datetime(kwargs["end"]) if kwargs.get("end") is not None else None
        limit = kwargs.get("limit", 100)
        logger.info("Fetching Loki logs: query=%s start=%s end=%s", query, start, end)
        result = self._extractor.fetch_logs(query, start=start, end=end, limit=limit)
        logger.info("Result: %d logs fetched", len(result))
        return result

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def loki_fetch_logs(
            query: str,
            start: datetime.datetime | None = None,
            end: datetime.datetime | None = None,
            limit: int = 100,
        ) -> List[LogEntry]:
            """Fetch logs from Loki using a query and optional time range. If start/end are omitted, the last 100 logs are returned."""
            logger.info("Fetching Loki logs: query=%s start=%s end=%s", query, start, end)
            result = ext.fetch_logs(query, start=start, end=end, limit=limit)
            logger.info("Result: %d logs fetched", len(result))
            return result

        return loki_fetch_logs


class LokiCleanQueryStringTool(LokiTool):
    name: ClassVar[str] = "loki_clean_query_string"
    description: ClassVar[str] = (
        "Clean the query string by removing markdown code blocks, newlines, "
        "and extra whitespace."
    )

    def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("loki_clean_query_string requires query")
        return self._extractor._clean_query_string(query)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def loki_clean_query_string(query: str) -> str:
            """Clean the query string by removing markdown code blocks, newlines, and extra whitespace."""
            return ext._clean_query_string(query)

        return loki_clean_query_string


# ---------------------------------------------------------------------------
# OpenSearch tools
# ---------------------------------------------------------------------------

class OpenSearchGetFieldNamesTool(OpenSearchTool):
    name: ClassVar[str] = "opensearch_get_field_names"
    description: ClassVar[str] = "Get available field names from OpenSearch."

    def execute(self, **kwargs: Any) -> List[str]:
        index = kwargs.get("index")
        if index is None:
            raise TypeError("opensearch_get_field_names requires index")
        return self._extractor.get_field_names(index=index)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def opensearch_get_field_names(index: str) -> List[str]:
            """Get available field names from OpenSearch."""
            return ext.get_field_names(index=index)

        return opensearch_get_field_names


class OpenSearchValidateQueryTool(OpenSearchTool):
    name: ClassVar[str] = "opensearch_validate_query"
    description: ClassVar[str] = "Fetch logs from OpenSearch using a query."

    def execute(self, **kwargs: Any) -> List[LogEntry]:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("opensearch_validate_query requires query")
        result = self._extractor.fetch_logs(query)
        sample = result[0].model_dump() if result else None
        logger.info(
            "opensearch_validate_query execute returned count=%d sample=%s",
            len(result), sample,
        )
        return result

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def opensearch_validate_query(query: str) -> List[LogEntry]:
            """Fetch logs from OpenSearch using a query."""
            result = ext.fetch_logs(query)
            sample = result[0].model_dump() if result else None
            logger.info(
                "opensearch_validate_query tool returned count=%d sample=%s",
                len(result), sample,
            )
            return result

        return opensearch_validate_query


class OpenSearchFetchLogsTool(OpenSearchTool):
    name: ClassVar[str] = "opensearch_fetch_logs"
    description: ClassVar[str] = "Fetch logs from OpenSearch using a query and optional time range."

    def execute(self, **kwargs: Any) -> List[LogEntry]:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("opensearch_fetch_logs requires query")
        start = _parse_datetime(kwargs["start"]) if kwargs.get("start") is not None else None
        end = _parse_datetime(kwargs["end"]) if kwargs.get("end") is not None else None
        limit = kwargs.get("limit", 100)
        result = self._extractor.fetch_logs(query, start=start, end=end, limit=limit)
        sample = result[0].model_dump() if result else None
        logger.info(
            "opensearch_fetch_logs execute returned count=%d sample=%s",
            len(result), sample,
        )
        return result

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def opensearch_fetch_logs(
            query: str,
            start: datetime.datetime | None = None,
            end: datetime.datetime | None = None,
            limit: int = 100,
        ) -> List[LogEntry]:
            """Fetch logs from OpenSearch using a query and optional time range. If start/end are omitted, the last 100 logs are returned."""
            result = ext.fetch_logs(query, start=start, end=end, limit=limit)
            sample = result[0].model_dump() if result else None
            logger.info(
                "opensearch_fetch_logs tool returned count=%d sample=%s",
                len(result), sample,
            )
            return result

        return opensearch_fetch_logs


class OpenSearchCleanQueryStringTool(OpenSearchTool):
    name: ClassVar[str] = "opensearch_clean_query_string"
    description: ClassVar[str] = (
        "Clean the query string by removing markdown code blocks, newlines, "
        "and extra whitespace."
    )

    def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("opensearch_clean_query_string requires query")
        return self._extractor._clean_query_string(query)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def opensearch_clean_query_string(query: str) -> str:
            """Clean the query string by removing markdown code blocks, newlines, and extra whitespace."""
            return ext._clean_query_string(query)

        return opensearch_clean_query_string


class OpenSearchGetIndexNameTool(OpenSearchTool):
    name: ClassVar[str] = "opensearch_get_index_name"
    description: ClassVar[str] = "Get available index names from OpenSearch."

    def execute(self, **kwargs: Any) -> str:
        if kwargs:
            raise TypeError("opensearch_get_index_name takes no arguments")
        return self._extractor.get_index_name()

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def opensearch_get_index_name() -> str:
            """Get available index names from OpenSearch."""
            return ext.get_index_name()

        return opensearch_get_index_name


# ---------------------------------------------------------------------------
# ClickHouse tools
# ---------------------------------------------------------------------------

class ClickHouseGetTableNameTool(ClickHouseTool):
    name: ClassVar[str] = "clickhouse_get_table_name"
    description: ClassVar[str] = "Get the fully-qualified ClickHouse table name for querying logs."

    def execute(self, **kwargs: Any) -> str:
        if kwargs:
            raise TypeError("clickhouse_get_table_name takes no arguments")
        return self._extractor.get_index_name()

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def clickhouse_get_table_name() -> str:
            """Get the fully-qualified ClickHouse table name for querying logs."""
            return ext.get_index_name()

        return clickhouse_get_table_name


class ClickHouseGetColumnNamesTool(ClickHouseTool):
    name: ClassVar[str] = "clickhouse_get_column_names"
    description: ClassVar[str] = "Get available column names from the ClickHouse log table."

    def execute(self, **kwargs: Any) -> List[str]:
        if kwargs:
            raise TypeError("clickhouse_get_column_names takes no arguments")
        return self._extractor.get_field_names()

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def clickhouse_get_column_names() -> List[str]:
            """Get available column names from the ClickHouse log table."""
            return ext.get_field_names()

        return clickhouse_get_column_names


class ClickHouseValidateQueryTool(ClickHouseTool):
    name: ClassVar[str] = "clickhouse_validate_query"
    description: ClassVar[str] = "Execute a SQL SELECT query against ClickHouse and return log entries."

    def execute(self, **kwargs: Any) -> List[LogEntry]:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("clickhouse_validate_query requires query")
        logger.info("Validating ClickHouse SQL query: %s", query)
        result = self._extractor.fetch_logs(query)
        logger.info("Result: %d logs fetched", len(result))
        return result

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def clickhouse_validate_query(query: str) -> List[LogEntry]:
            """Execute a SQL SELECT query against ClickHouse and return log entries."""
            logger.info("Validating ClickHouse SQL query: %s", query)
            result = ext.fetch_logs(query)
            logger.info("Result: %d logs fetched", len(result))
            return result

        return clickhouse_validate_query


class ClickHouseFetchLogsTool(ClickHouseTool):
    name: ClassVar[str] = "clickhouse_fetch_logs"
    description: ClassVar[str] = "Fetch logs from ClickHouse using a query and optional time range."

    def execute(self, **kwargs: Any) -> List[LogEntry]:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("clickhouse_fetch_logs requires query")
        start = _parse_datetime(kwargs["start"]) if kwargs.get("start") is not None else None
        end = _parse_datetime(kwargs["end"]) if kwargs.get("end") is not None else None
        limit = kwargs.get("limit", 100)
        logger.info("Fetching ClickHouse logs: query=%s start=%s end=%s", query, start, end)
        result = self._extractor.fetch_logs(query, start=start, end=end, limit=limit)
        logger.info("Result: %d logs fetched", len(result))
        return result

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def clickhouse_fetch_logs(
            query: str,
            start: datetime.datetime | None = None,
            end: datetime.datetime | None = None,
            limit: int = 100,
        ) -> List[LogEntry]:
            """Fetch logs from ClickHouse using a query and optional time range. If start/end are omitted, the last 100 logs are returned."""
            logger.info(
                "Fetching ClickHouse logs: query=%s start=%s end=%s",
                query, start, end,
            )
            result = ext.fetch_logs(query, start=start, end=end, limit=limit)
            logger.info("Result: %d logs fetched", len(result))
            return result

        return clickhouse_fetch_logs


class ClickHouseCleanQueryStringTool(ClickHouseTool):
    name: ClassVar[str] = "clickhouse_clean_query_string"
    description: ClassVar[str] = (
        "Clean the query string by removing markdown code blocks, newlines, "
        "and extra whitespace."
    )

    def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query")
        if query is None:
            raise TypeError("clickhouse_clean_query_string requires query")
        return self._extractor._clean_query_string(query)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def clickhouse_clean_query_string(query: str) -> str:
            """Clean the query string by removing markdown code blocks, newlines, and extra whitespace."""
            return ext._clean_query_string(query)

        return clickhouse_clean_query_string
