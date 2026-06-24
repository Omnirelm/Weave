from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from src.api.models.schemas import (
    CreateIntegrationRequest,
    IntegrationResponse,
    TenantIntegrationV1,
    UpdateIntegrationRequest,
)
from src.api.translators.integrations import (
    create_request_to_payload,
    integration_to_response,
    update_request_to_payload,
)
from src.storage.interface import StorageGateway

router = APIRouter(prefix="/tenants/{slug}/integrations", tags=["integrations"])


def _get_storage(request: Request) -> StorageGateway:
    return request.app.state.storage


async def _require_tenant(storage: StorageGateway, slug: str) -> None:
    if await storage.tenants.get_by_slug(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {slug}",
        )


@router.get("", response_model=list[TenantIntegrationV1], response_model_exclude_none=True)
async def list_integrations(slug: str, request: Request) -> list[IntegrationResponse]:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    rows = await storage.integrations.list_for_tenant(slug)
    return [integration_to_response(row) for row in rows]


@router.post("", response_model=TenantIntegrationV1, response_model_exclude_none=True, status_code=status.HTTP_201_CREATED)
async def create_integration(
    slug: str,
    body: CreateIntegrationRequest,
    request: Request,
) -> IntegrationResponse:
    try:
        body.validate()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    storage = _get_storage(request)
    await _require_tenant(storage, slug)

    try:
        row = await storage.integrations.create_for_tenant(slug, create_request_to_payload(body))
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Integration with type={body.type!r} flavour={body.flavour!r} already exists for tenant {slug!r}",
        ) from exc

    return integration_to_response(row)


@router.get("/{integration_id}", response_model=TenantIntegrationV1, response_model_exclude_none=True)
async def get_integration(
    slug: str,
    integration_id: uuid.UUID,
    request: Request,
) -> IntegrationResponse:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)

    row = await storage.integrations.get_for_tenant(slug, integration_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration not found: {integration_id}",
        )

    return integration_to_response(row)


@router.put("/{integration_id}", response_model=TenantIntegrationV1, response_model_exclude_none=True)
async def update_integration(
    slug: str,
    integration_id: uuid.UUID,
    body: UpdateIntegrationRequest,
    request: Request,
) -> IntegrationResponse:
    try:
        body.validate()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    storage = _get_storage(request)
    await _require_tenant(storage, slug)

    existing = await storage.integrations.get_for_tenant(slug, integration_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration not found: {integration_id}",
        )

    if body.flavour != existing.flavour:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Integration flavour is immutable: expected {existing.flavour!r}, got {body.flavour!r}",
        )

    row = await storage.integrations.update_for_tenant(slug, integration_id, update_request_to_payload(body))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration not found: {integration_id}",
        )

    return integration_to_response(row)
