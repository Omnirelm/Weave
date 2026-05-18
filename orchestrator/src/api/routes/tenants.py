from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from src.api.models.schemas import CreateTenantRequest, TenantV1
from src.storage.interface import StorageGateway
from src.storage.models.tenant import Tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _tenant_to_resource(tenant: Tenant) -> TenantV1:
    return TenantV1(
        slug=tenant.slug,
        display_name=tenant.display_name,
        plan_slug=tenant.plan_slug,
    )


@router.post("", response_model=TenantV1, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: CreateTenantRequest, request: Request) -> TenantV1:
    storage: StorageGateway = request.app.state.storage

    existing = await storage.tenants.get_by_slug(body.slug)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant already exists: {body.slug}",
        )

    created = await storage.tenants.create(
        {
            "slug": body.slug,
            "display_name": body.display_name,
            "plan_slug": body.plan_slug,
        }
    )
    return _tenant_to_resource(created)


@router.get("/{slug}", response_model=TenantV1)
async def get_tenant(slug: str, request: Request) -> TenantV1:
    storage: StorageGateway = request.app.state.storage
    tenant = await storage.tenants.get_by_slug(slug)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {slug}",
        )
    return _tenant_to_resource(tenant)
