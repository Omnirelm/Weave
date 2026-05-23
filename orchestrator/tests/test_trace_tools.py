"""Tests for Jaeger/Tempo trace integration tools and TraceSourceSpec registry."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.tools.base import ToolNotFoundError
from src.core.tools.provider import ToolProvider
from src.integrations.http.tool import HttpTool
from src.integrations.traces.base import TraceExtractorError
from src.integrations.traces.jaeger import JaegerExtractor
from src.integrations.traces.registry import TraceSourceSpec, get_trace_extractor
from src.integrations.traces.tools import JaegerFetchTraceTool, TempoFetchTraceTool


def test_jaeger_fetch_trace_execute_requires_trace_id() -> None:
    ext = MagicMock()
    ext.fetch_trace.return_value = {"traceID": "abc"}
    tool = JaegerFetchTraceTool(ext)
    with pytest.raises(TypeError, match="trace_id"):
        tool.execute()
    with pytest.raises(TypeError, match="non-empty"):
        tool.execute(trace_id="  ")


def test_jaeger_fetch_trace_execute_delegates() -> None:
    ext = MagicMock()
    ext.fetch_trace.return_value = {"traceID": "deadbeef"}
    tool = JaegerFetchTraceTool(ext)
    out = tool.execute(trace_id="  deadbeef  ")
    assert out == {"traceID": "deadbeef"}
    ext.fetch_trace.assert_called_once_with("deadbeef")


def test_tempo_fetch_trace_execute_delegates() -> None:
    ext = MagicMock()
    ext.fetch_trace.return_value = {"traceID": "x"}
    tool = TempoFetchTraceTool(ext)
    out = tool.execute(trace_id="x")
    assert out == {"traceID": "x"}
    ext.fetch_trace.assert_called_once_with("x")


def test_get_trace_extractor_uses_auth_mechanism_for_jaeger() -> None:
    spec = TraceSourceSpec(
        flavour="JAEGER",
        url="http://jaeger:16686",
        auth_mechanism={"bearer": {"token": "t0ken"}},
    )
    ext = get_trace_extractor(spec, "org-1")
    assert isinstance(ext, JaegerExtractor)
    assert ext.headers.get("Authorization") == "Bearer t0ken"
    assert ext.headers.get("X-Scope-OrgID") == "org-1"
    assert ext.api_base == "http://jaeger:16686/api/v3"


def test_get_trace_extractor_accepts_authentication_alias() -> None:
    spec = TraceSourceSpec.model_validate(
        {
            "flavour": "JAEGER",
            "url": "http://jaeger:16686",
            "authentication": {"bearer": {"token": "legacy"}},
        }
    )
    ext = get_trace_extractor(spec, "")
    assert isinstance(ext, JaegerExtractor)
    assert ext.headers.get("Authorization") == "Bearer legacy"


@pytest.mark.asyncio
async def test_tool_provider_lists_jaeger_when_integration_present() -> None:
    row = SimpleNamespace(
        integration_type="TRACE_SOURCE",
        flavour="JAEGER",
        active=True,
        config={"url": "http://localhost:16686"},
    )
    storage = SimpleNamespace(
        integrations=SimpleNamespace(list_for_tenant=AsyncMock(return_value=[row]))
    )
    provider = ToolProvider(
        storage,  # type: ignore[arg-type]
        static_tools=[HttpTool()],
        integration_tools={"jaeger_fetch_trace": JaegerFetchTraceTool},
    )
    descriptors = await provider.list_descriptors("acme")
    names = {d.name for d in descriptors}
    assert "http_request" in names
    assert "jaeger_fetch_trace" in names


@pytest.mark.asyncio
async def test_tool_provider_resolve_one_jaeger_tool() -> None:
    row = SimpleNamespace(
        integration_type="TRACE_SOURCE",
        flavour="JAEGER",
        active=True,
        config={"url": "http://localhost:16686"},
    )
    storage = SimpleNamespace(
        integrations=SimpleNamespace(list_for_tenant=AsyncMock(return_value=[row]))
    )
    provider = ToolProvider(
        storage,  # type: ignore[arg-type]
        static_tools=[HttpTool()],
        integration_tools={"jaeger_fetch_trace": JaegerFetchTraceTool},
    )
    tool = await provider.resolve_one("jaeger_fetch_trace", "acme")
    assert isinstance(tool, JaegerFetchTraceTool)
    assert tool._extractor.api_base == "http://localhost:16686/api/v3"


@pytest.mark.asyncio
async def test_tool_provider_resolve_one_missing_integration_raises() -> None:
    storage = SimpleNamespace(
        integrations=SimpleNamespace(list_for_tenant=AsyncMock(return_value=[]))
    )
    provider = ToolProvider(
        storage,  # type: ignore[arg-type]
        static_tools=[HttpTool()],
        integration_tools={"jaeger_fetch_trace": JaegerFetchTraceTool},
    )
    with pytest.raises(ToolNotFoundError):
        await provider.resolve_one("jaeger_fetch_trace", "acme")


@pytest.mark.asyncio
async def test_tool_provider_passes_tenant_slug_to_extractor() -> None:
    row = SimpleNamespace(
        integration_type="TRACE_SOURCE",
        flavour="JAEGER",
        active=True,
        config={"url": "http://localhost:16686"},
    )
    storage = SimpleNamespace(
        integrations=SimpleNamespace(list_for_tenant=AsyncMock(return_value=[row]))
    )
    provider = ToolProvider(
        storage,  # type: ignore[arg-type]
        static_tools=[HttpTool()],
        integration_tools={"jaeger_fetch_trace": JaegerFetchTraceTool},
    )
    tool = await provider.resolve_one("jaeger_fetch_trace", "tenant-z")
    assert tool._extractor.headers.get("X-Scope-OrgID") == "tenant-z"


def _response(*, status_code: int = 200, text: str = "", json_data: object | None = None):
    class _FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self.reason = "Error"
            if json_data is not None:
                self.text = json.dumps(json_data)
                self._json = json_data
            else:
                self.text = text
                self._json = None

        def json(self) -> object:
            if self._json is not None:
                return self._json
            return json.loads(self.text)

    return _FakeResponse()


def test_jaeger_fetch_trace_uses_v3_api() -> None:
    ext = JaegerExtractor("http://jaeger:16686")
    v3_payload = {
        "result": {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "frontend"}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "scope"},
                            "spans": [
                                {
                                    "traceId": "abc123",
                                    "spanId": "span1",
                                    "name": "GET /",
                                    "startTimeUnixNano": "1000000000",
                                    "endTimeUnixNano": "2000000000",
                                    "status": {"code": 1},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }

    with patch.object(
        JaegerExtractor,
        "_make_request",
        side_effect=[
            _response(json_data=v3_payload),
        ],
    ) as mock_request:
        out = ext.fetch_trace("abc123")

    assert out["traceID"] == "abc123"
    assert out["spanCount"] == 1
    assert out["services"] == ["frontend"]
    span = out["spans"][0]
    assert span["startTime"] == 1_000_000_000
    assert span["endTime"] == 2_000_000_000
    assert span["duration"] == 1_000_000_000
    assert out["duration"] == 1_000_000_000
    mock_request.assert_called_once_with(
        "GET",
        "http://jaeger:16686/api/v3/traces/abc123",
        params={},
    )


def test_jaeger_fetch_trace_rejects_missing_result_envelope() -> None:
    ext = JaegerExtractor("http://jaeger:16686")
    with patch.object(
        JaegerExtractor,
        "_make_request",
        return_value=_response(json_data={"unexpected": True}),
    ):
        with pytest.raises(TraceExtractorError, match="missing 'result' envelope"):
            ext.fetch_trace("abc123")


def test_jaeger_fetch_trace_reports_non_json_body() -> None:
    ext = JaegerExtractor("http://jaeger:16686")
    with patch.object(
        JaegerExtractor,
        "_make_request",
        return_value=_response(status_code=200, text="<html>Jaeger UI</html>"),
    ):
        with pytest.raises(TraceExtractorError, match="Non-JSON response"):
            ext.fetch_trace("abc123")
