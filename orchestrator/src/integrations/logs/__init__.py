"""
Logs package for log extraction integrations.
"""

from .base import (
    LogExtractor,
    LogExtractorError,
    LogEntry,
    DedupedLogEntry,
    DedupedLogsResult,
    LogDedupeError,
    OAuthConfig,
    OAuthTokenManager,
    QueryGenerationError,
)
from .clickhouse import ClickHouseExtractor
from .dedupe import de_dupe_logs
from .loki import GrafanaLokiExtractor
from .opensearch import OpenSearchExtractor
from .registry import LogSourceSpec

__all__ = [
    'ClickHouseExtractor',
    'DedupedLogEntry',
    'DedupedLogsResult',
    'GrafanaLokiExtractor',
    'LogDedupeError',
    'LogEntry',
    'LogExtractor',
    'LogExtractorError',
    'LogSourceSpec',
    'OAuthConfig',
    'OAuthTokenManager',
    'OpenSearchExtractor',
    'QueryGenerationError',
    'de_dupe_logs',
]
