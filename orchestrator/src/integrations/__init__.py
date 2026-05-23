"""
Integrations package: external datapoints and backends that agents connect to
(logs, traces, etc.).
"""

from .flavours import LogSourceFlavour, TraceSourceFlavour
from .logs import (
    LogExtractor,
    LogExtractorError,
    LogEntry,
    GrafanaLokiExtractor,
    OpenSearchExtractor,
)
from .traces import (
    GrafanaTempoExtractor,
    JaegerExtractor,
    TraceExtractor,
    TraceExtractorError,
    TraceSourceSpec,
    get_trace_extractor,
)
from .repository import validate_repository, parse_github_repo_url

__all__ = [
    # Flavours (shared with API)
    "LogSourceFlavour",
    "TraceSourceFlavour",
    # Logs
    "LogExtractor",
    "LogExtractorError",
    "LogEntry",
    "GrafanaLokiExtractor",
    "OpenSearchExtractor",
    # Traces
    "TraceExtractor",
    "TraceExtractorError",
    "JaegerExtractor",
    "GrafanaTempoExtractor",
    "TraceSourceSpec",
    "get_trace_extractor",
    # Repository (GitHub validation)
    "validate_repository",
    "parse_github_repo_url",
]
