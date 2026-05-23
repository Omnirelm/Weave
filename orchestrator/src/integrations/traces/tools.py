"""Integration tools for Jaeger and Tempo trace backends."""

from __future__ import annotations

import logging
from abc import ABC
from typing import Any, ClassVar, Dict

from agents.tool import function_tool

from src.core.tools.base import IntegrationTool
from src.integrations.flavours import IntegrationType, TraceSourceFlavour
from src.integrations.traces.jaeger import JaegerExtractor
from src.integrations.traces.registry import TraceSourceSpec, get_trace_extractor
from src.integrations.traces.tempo import GrafanaTempoExtractor

logger = logging.getLogger(__name__)


def _spec_from_integration_config(config: dict[str, Any]) -> TraceSourceSpec:
    payload = {k: v for k, v in config.items() if not k.startswith("_")}
    return TraceSourceSpec.model_validate(payload)


class JaegerTool(IntegrationTool, ABC):
    """Base for Jaeger-backed tools."""

    integration_type: ClassVar[str] = IntegrationType.TRACE_SOURCE
    integration_flavour: ClassVar[str] = TraceSourceFlavour.JAEGER

    def __init__(self, extractor: JaegerExtractor) -> None:
        self._extractor = extractor

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> JaegerTool:
        spec = _spec_from_integration_config(config)
        tenant = str(config.get("_tenantSlug") or "")
        ext = get_trace_extractor(spec, tenant)
        if not isinstance(ext, JaegerExtractor):
            raise TypeError(f"Expected JaegerExtractor, got {type(ext)}")
        return cls(ext)  # type: ignore[return-value]


class TempoTool(IntegrationTool, ABC):
    """Base for Tempo-backed tools."""

    integration_type: ClassVar[str] = IntegrationType.TRACE_SOURCE
    integration_flavour: ClassVar[str] = TraceSourceFlavour.TEMPO

    def __init__(self, extractor: GrafanaTempoExtractor) -> None:
        self._extractor = extractor

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> TempoTool:
        spec = _spec_from_integration_config(config)
        tenant = str(config.get("_tenantSlug") or "")
        ext = get_trace_extractor(spec, tenant)
        if not isinstance(ext, GrafanaTempoExtractor):
            raise TypeError(f"Expected GrafanaTempoExtractor, got {type(ext)}")
        return cls(ext)  # type: ignore[return-value]


class JaegerFetchTraceTool(JaegerTool):
    name: ClassVar[str] = "jaeger_fetch_trace"
    description: ClassVar[str] = (
        "Fetch a distributed trace by ID from Jaeger (parsed spans and metadata)."
    )

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        trace_id = kwargs.get("trace_id")
        if trace_id is None:
            raise TypeError("jaeger_fetch_trace requires trace_id")
        tid = str(trace_id).strip()
        if not tid:
            raise TypeError("jaeger_fetch_trace requires non-empty trace_id")
        logger.debug("jaeger_fetch_trace trace_id=%s", tid)
        return self._extractor.fetch_trace(tid)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def jaeger_fetch_trace(trace_id: str) -> Dict[str, Any]:
            """Fetch a trace by hex trace ID from the tenant's Jaeger integration."""
            return ext.fetch_trace(trace_id.strip())

        return jaeger_fetch_trace


class TempoFetchTraceTool(TempoTool):
    name: ClassVar[str] = "tempo_fetch_trace"
    description: ClassVar[str] = (
        "Fetch a distributed trace by ID from Grafana Tempo (parsed spans and metadata)."
    )

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        trace_id = kwargs.get("trace_id")
        if trace_id is None:
            raise TypeError("tempo_fetch_trace requires trace_id")
        tid = str(trace_id).strip()
        if not tid:
            raise TypeError("tempo_fetch_trace requires non-empty trace_id")
        logger.debug("tempo_fetch_trace trace_id=%s", tid)
        return self._extractor.fetch_trace(tid)

    def as_function_tool(self) -> Any:
        ext = self._extractor

        @function_tool
        def tempo_fetch_trace(trace_id: str) -> Dict[str, Any]:
            """Fetch a trace by hex trace ID from the tenant's Tempo integration."""
            return ext.fetch_trace(trace_id.strip())

        return tempo_fetch_trace
