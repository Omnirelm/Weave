"""API-key authentication and quota enforcement (ASGI middleware).

Quota enforcement targets are declared in config ``auth.quota_routes``: each rule
binds a path pattern + HTTP methods to a ``plan_quotas.operation`` string
(``task_run``, ``agent_max``, …). The middleware does not hardcode paths; it
matches the request against those rules in order.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config.settings import AuthConfig, QuotaRouteRule, get_config
from src.security import hash_api_key
from src.security.quota_ops import PERIOD_MONTHLY, PERIOD_NONE
from src.storage.interface import StorageGateway
from src.storage.repositories.quota_usage import QuotaExceededError


def _utc_month_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def compile_quota_route_table(
    auth: AuthConfig,
) -> list[tuple[re.Pattern[str], QuotaRouteRule]]:
    """Pre-compile regex patterns from settings (call once when building the app)."""
    return [(re.compile(rule.path_pattern), rule) for rule in auth.quota_routes]


def compile_public_route_pairs(auth: AuthConfig) -> frozenset[tuple[str, str]]:
    """Set of (METHOD, path) tuples that skip authentication."""
    pairs: list[tuple[str, str]] = []
    for rule in auth.public_routes:
        for m in rule.methods:
            pairs.append((m.upper(), rule.path))
    return frozenset(pairs)


def _normalize_path(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path[:-1]
    return path


def _extract_api_secret(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.headers.get("X-API-Key")


_TENANT_UNDER_TENANTS = re.compile(r"^/tenants/([^/]+)")


def _path_tenant_slug(path: str) -> str | None:
    m = _TENANT_UNDER_TENANTS.match(path)
    return m.group(1) if m else None


def _is_public_route(method: str, path: str, public_pairs: frozenset[tuple[str, str]]) -> bool:
    if method == "OPTIONS":
        return True
    return (method.upper(), path) in public_pairs


def _match_quota_rule(
    method: str,
    path: str,
    quota_route_table: list[tuple[re.Pattern[str], QuotaRouteRule]],
) -> QuotaRouteRule | None:
    for pattern, rule in quota_route_table:
        if method not in rule.methods:
            continue
        if pattern.match(path):
            return rule
    return None


class AuthQuotaMiddleware(BaseHTTPMiddleware):
    """Validates API keys and applies quota rules from config."""

    def __init__(
        self,
        app: Callable,
        *,
        quota_route_table: list[tuple[re.Pattern[str], QuotaRouteRule]],
        public_route_pairs: frozenset[tuple[str, str]],
    ) -> None:
        super().__init__(app)
        self._quota_route_table = quota_route_table
        self._public_route_pairs = public_route_pairs

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        config = get_config()
        method = request.method.upper()
        path = _normalize_path(request.url.path)

        if config.auth.disabled:
            return await call_next(request)

        if _is_public_route(method, path, self._public_route_pairs):
            return await call_next(request)

        storage: StorageGateway = request.app.state.storage

        secret = _extract_api_secret(request)
        if not secret:
            return JSONResponse({"detail": "Missing API key"}, status_code=401)

        digest = hash_api_key(secret, config.auth.api_key_pepper)
        row = await storage.api_keys.get_active_by_hash(digest)
        if row is None:
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)

        tenant_slug = row.tenant_slug
        request.state.tenant_slug = tenant_slug

        path_slug = _path_tenant_slug(path)
        if path_slug is not None and path_slug != tenant_slug:
            return JSONResponse(
                {"detail": "API key does not match tenant in path"},
                status_code=403,
            )

        quota_rule = _match_quota_rule(method, path, self._quota_route_table)

        if quota_rule is not None and quota_rule.tenant_in_body:
            body = await request.body()
            if len(body) > quota_rule.max_body_bytes:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
            body_slug = payload.get(quota_rule.body_slug_field, "default")
            if body_slug != tenant_slug:
                return JSONResponse(
                    {"detail": "API key does not match slug in request body"},
                    status_code=403,
                )
            if not config.auth.quota_disabled:
                qerr = await self._enforce_quota(
                    storage,
                    tenant_slug,
                    quota_rule.operation,
                )
                if qerr is not None:
                    return qerr

            async def receive() -> dict:
                return {"type": "http.request", "body": body, "more_body": False}

            replay = Request(request.scope, receive)
            return await call_next(replay)

        if quota_rule is not None and not quota_rule.tenant_in_body:
            if not config.auth.quota_disabled:
                qerr = await self._enforce_quota(
                    storage,
                    tenant_slug,
                    quota_rule.operation,
                )
                if qerr is not None:
                    return qerr

        return await call_next(request)

    async def _enforce_quota(
        self,
        storage: StorageGateway,
        tenant_slug: str,
        operation: str,
    ) -> Response | None:
        if operation == "task_run":
            return await self._monthly_quota(storage, tenant_slug, operation)
        if operation == "agent_max":
            return await self._agent_max_cap(storage, tenant_slug, operation)
        if operation == "workflow_max":
            return await self._workflow_max_cap(storage, tenant_slug, operation)
        return None

    async def _monthly_quota(
        self, storage: StorageGateway, tenant_slug: str, operation: str
    ) -> Response | None:
        tenant, pq = await storage.quota_usage.get_tenant_and_plan_quota(tenant_slug, operation)
        if tenant is None:
            return JSONResponse({"detail": "Tenant not found"}, status_code=403)
        if pq is None:
            return None
        if pq.period != PERIOD_MONTHLY:
            return None
        try:
            await storage.quota_usage.try_increment_monthly(
                tenant_slug=tenant_slug,
                operation=operation,
                period_key=_utc_month_key(),
                limit=pq.limit_value,
            )
        except QuotaExceededError:
            return JSONResponse(
                {"detail": "Task execution quota exceeded for this billing period"},
                status_code=429,
            )
        return None

    async def _agent_max_cap(
        self,
        storage: StorageGateway,
        tenant_slug: str,
        operation: str,
    ) -> Response | None:
        tenant, pq = await storage.quota_usage.get_tenant_and_plan_quota(tenant_slug, operation)
        if tenant is None:
            return JSONResponse({"detail": "Tenant not found"}, status_code=403)
        if pq is None:
            return None
        if pq.period != PERIOD_NONE:
            return None
        count = await storage.tenant_agents.count_for_tenant(tenant_slug)
        if count >= pq.limit_value:
            return JSONResponse(
                {"detail": "Maximum number of custom agents reached for this plan"},
                status_code=429,
            )
        return None

    async def _workflow_max_cap(
        self,
        storage: StorageGateway,
        tenant_slug: str,
        operation: str,
    ) -> Response | None:
        tenant, pq = await storage.quota_usage.get_tenant_and_plan_quota(tenant_slug, operation)
        if tenant is None:
            return JSONResponse({"detail": "Tenant not found"}, status_code=403)
        if pq is None:
            return None
        if pq.period != PERIOD_NONE:
            return None
        count = await storage.tenant_workflows.count_for_tenant(tenant_slug)
        if count >= pq.limit_value:
            return JSONResponse(
                {"detail": "Maximum number of custom workflows reached for this plan"},
                status_code=429,
            )
        return None
