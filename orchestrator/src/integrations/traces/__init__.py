"""
Traces package for distributed tracing integrations.
"""

from .base import TraceExtractor, TraceExtractorError
from .jaeger import JaegerExtractor
from .registry import TraceSourceSpec, get_trace_extractor
from .tempo import GrafanaTempoExtractor

__all__ = [
    "TraceExtractor",
    "TraceExtractorError",
    "GrafanaTempoExtractor",
    "JaegerExtractor",
    "TraceSourceSpec",
    "get_trace_extractor",
]
