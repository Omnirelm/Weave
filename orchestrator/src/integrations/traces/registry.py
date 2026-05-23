"""
Trace extractor registry: register flavour -> factory, get extractor by TraceSourceSpec.
API and core use this single path to create trace extractors.
"""
import logging
from typing import Any, Callable

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from .base import TraceExtractor
from ..flavours import TraceSourceFlavour
from ..common.auth import build_headers_and_oauth_from_auth_dict
from .jaeger import JaegerExtractor
from .tempo import GrafanaTempoExtractor

logger = logging.getLogger(__name__)


class TraceSourceSpec(BaseModel):
    """Validated config for building a TraceExtractor (tenant row config + flavour)."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="ignore")

    flavour: str
    url: str
    auth_mechanism: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("authMechanism", "authentication"),
        serialization_alias="authMechanism",
    )
    base_path: str = Field(
        default="",
        validation_alias=AliasChoices("basePath", "base_path"),
        serialization_alias="basePath",
    )

    @field_validator("flavour", mode="before")
    @classmethod
    def _normalize_flavour(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).upper().strip()


# Type: (spec, tenant_id) -> TraceExtractor
_TraceFactory = Callable[[TraceSourceSpec, str], TraceExtractor]

_REGISTRY: dict[str, _TraceFactory] = {}


def register(trace_flavour: str, factory: _TraceFactory) -> None:
    """Register a trace extractor factory for the given flavour (e.g. JAEGER, TEMPO)."""
    key = trace_flavour.upper().strip()
    _REGISTRY[key] = factory


def get_trace_extractor(spec: TraceSourceSpec, tenant_id: str = "") -> TraceExtractor:
    """
    Create a TraceExtractor from a validated TraceSourceSpec.

    Args:
        spec: Connection and auth fields for the trace backend.
        tenant_id: Tenant slug or id for multi-tenant headers (e.g. X-Scope-OrgID).

    Returns:
        TraceExtractor instance.

    Raises:
        ValueError: If flavour or url is missing/invalid, or flavour is unsupported.
    """
    flavour = spec.flavour
    if not flavour:
        raise ValueError("trace source must have non-empty flavour")
    url = (spec.url or "").strip()
    if not url:
        raise ValueError("trace source must have non-empty url")

    factory = _REGISTRY.get(flavour)
    if not factory:
        raise ValueError(f"Unsupported trace source flavour: {flavour}")

    return factory(spec, tenant_id)


def _factory_jaeger(spec: TraceSourceSpec, tenant_id: str) -> TraceExtractor:
    base_url = spec.url.rstrip("/")
    result = build_headers_and_oauth_from_auth_dict(spec.auth_mechanism)
    # Trace extractors use headers only (OAuth not yet supported for traces)
    bp = (spec.base_path or "").strip().rstrip("/")
    return JaegerExtractor(
        base_url=base_url,
        base_path=bp,
        tenant_id=tenant_id or None,
        headers=result.headers or {},
    )


def _factory_tempo(spec: TraceSourceSpec, tenant_id: str) -> TraceExtractor:
    base_url = spec.url.rstrip("/")
    result = build_headers_and_oauth_from_auth_dict(spec.auth_mechanism)
    return GrafanaTempoExtractor(
        base_url=base_url,
        tenant_id=tenant_id or None,
        headers=result.headers or {},
    )


# Register built-in extractors at module load
register(TraceSourceFlavour.JAEGER.value, _factory_jaeger)
register(TraceSourceFlavour.TEMPO.value, _factory_tempo)
