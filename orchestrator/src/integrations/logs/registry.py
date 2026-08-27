"""
Log extractor registry: register flavour -> factory, get extractor by LogSourceSpec.
API and core use this single path to create log extractors.
"""
from typing import Callable

from .base import LogExtractor
from ..flavours import LogSourceFlavour
from ..common.auth import build_headers_and_oauth_from_auth_dict
from .loki import GrafanaLokiExtractor
from .opensearch import OpenSearchExtractor
from .clickhouse import ClickHouseExtractor
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from typing import Any

# Type: (spec, default_loki_org_id) -> LogExtractor




class LogSourceSpec(BaseModel):
    """
    Everything needed to build a LogExtractor (no YAML-only fields like name/enabled).

    External dicts (e.g. API) can use ``LogSourceSpec.model_validate(data)``; camelCase
    aliases are accepted via populate_by_name.
    """

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    flavour: str
    url: str
    loki_org_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("lokiOrgId", "tenantId"),
        serialization_alias="lokiOrgId",
    )
    headers: dict[str, str] = Field(default_factory=dict)
    index_pattern: str | None = Field(default=None, alias="indexPattern")
    database: str | None = None
    table: str | None = None
    auth_mechanism: dict[str, Any] | None = Field(default=None, alias="authMechanism")

    @field_validator("flavour", mode="before")
    @classmethod
    def _normalize_flavour(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).upper().strip()


_LogFactory = Callable[[LogSourceSpec, str], LogExtractor]



def _merge_spec_headers(
    spec: LogSourceSpec,
    auth_headers: dict[str, str] | None,
) -> dict[str, str] | None:
    """Merge spec.headers with auth-derived headers; auth wins on key clash."""
    extra_norm = {
        str(k): str(v) for k, v in spec.headers.items() if v is not None
    }
    auth_norm = dict(auth_headers) if auth_headers else {}
    merged = {**extra_norm, **auth_norm}
    return merged if merged else None


_REGISTRY: dict[str, _LogFactory] = {}


def register(log_flavour: str, factory: _LogFactory) -> None:
    """Register a log extractor factory for the given flavour (e.g. LOKI, OPENSEARCH)."""
    key = log_flavour.upper().strip()
    _REGISTRY[key] = factory


def get_log_extractor(
    spec: LogSourceSpec,
    default_loki_org_id: str = "default",
) -> LogExtractor:
    """
    Create a LogExtractor from a validated LogSourceSpec.

    For raw dict input (e.g. HTTP API), use ``LogSourceSpec.model_validate(data)`` first.

    Args:
        spec: Connection and auth fields for the log backend.
        default_loki_org_id: Loki org id when spec.loki_org_id is unset.

    Returns:
        LogExtractor instance.

    Raises:
        ValueError: If flavour or url is missing/invalid, or flavour is unsupported.
    """
    flavour = spec.flavour
    if not flavour:
        raise ValueError("log source must have non-empty flavour")
    url = (spec.url or "").strip()
    if not url:
        raise ValueError("log source must have non-empty url")

    factory = _REGISTRY.get(flavour)
    if not factory:
        raise ValueError(f"Unsupported log source flavour: {flavour}")

    return factory(spec, default_loki_org_id)


def _factory_opensearch(spec: LogSourceSpec, default_loki_org_id: str) -> LogExtractor:
    _ = default_loki_org_id
    base_url = spec.url.rstrip("/")
    index_pattern = spec.index_pattern or "logs-*"
    result = build_headers_and_oauth_from_auth_dict(spec.auth_mechanism)
    headers = _merge_spec_headers(spec, result.headers)
    return OpenSearchExtractor(
        base_url=base_url,
        index_pattern=index_pattern,
        headers=headers,
        oauth_token_manager=result.oauth_token_manager,
    )


def _factory_loki(spec: LogSourceSpec, default_loki_org_id: str) -> LogExtractor:
    _ = default_loki_org_id
    base_url = spec.url.rstrip("/")
    result = build_headers_and_oauth_from_auth_dict(spec.auth_mechanism)
    # Only send X-Scope-OrgID when explicitly configured; no "default" fallback.
    effective_loki_org_id = (spec.loki_org_id or "").strip() or None
    headers = _merge_spec_headers(spec, result.headers)
    return GrafanaLokiExtractor(
        base_url=base_url,
        loki_org_id=effective_loki_org_id,
        headers=headers,
        oauth_token_manager=result.oauth_token_manager,
    )


def _factory_clickhouse(spec: LogSourceSpec, default_loki_org_id: str) -> LogExtractor:
    _ = default_loki_org_id
    base_url = spec.url.rstrip("/")
    database = spec.database or "default"
    table = spec.table or "otel_logs"
    result = build_headers_and_oauth_from_auth_dict(spec.auth_mechanism)
    headers = _merge_spec_headers(spec, result.headers)
    return ClickHouseExtractor(
        base_url=base_url,
        database=database,
        table=table,
        headers=headers,
        oauth_token_manager=result.oauth_token_manager,
    )


# Register built-in extractors at module load
register(LogSourceFlavour.OPENSEARCH.value, _factory_opensearch)
register(LogSourceFlavour.LOKI.value, _factory_loki)
register(LogSourceFlavour.CLICKHOUSE.value, _factory_clickhouse)
