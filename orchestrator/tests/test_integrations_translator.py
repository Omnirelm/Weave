from __future__ import annotations

from types import SimpleNamespace

from src.api.models.schemas import JaegerIntegrationBody
from src.api.translators.integrations import create_request_to_payload, integration_to_response


def test_jaeger_integration_persists_base_path_on_create() -> None:
    body = JaegerIntegrationBody.model_validate(
        {
            "type": "TRACE_SOURCE",
            "flavour": "JAEGER",
            "url": "http://jaeger:16686",
            "basePath": "/jaeger/ui",
            "active": True,
        }
    )
    payload = create_request_to_payload(body)
    assert payload["config"]["base_path"] == "/jaeger/ui"


def test_jaeger_integration_roundtrips_base_path_from_db_row() -> None:
    row = SimpleNamespace(
        integration_type="TRACE_SOURCE",
        flavour="JAEGER",
        active=True,
        id="00000000-0000-0000-0000-000000000001",
        config={
            "url": "http://jaeger:16686",
            "base_path": "/jaeger/ui",
        },
        created_at=SimpleNamespace(timestamp=lambda: 1.0),
        updated_at=SimpleNamespace(timestamp=lambda: 2.0),
    )
    response = integration_to_response(row)
    assert response.url == "http://jaeger:16686"
    assert response.base_path == "/jaeger/ui"
    dumped = response.model_dump(by_alias=True, exclude_none=True)
    assert dumped["basePath"] == "/jaeger/ui"
