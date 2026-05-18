from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.api.models.schemas import SkillResource
from src.api.translators.skills import (
    resource_to_skill_def,
    skill_def_to_resource,
)
from src.core.skills import SkillDef
from src.core.skills.composition_validation import validate_composed_invoke_targets_not_composed
from src.storage.interface import StorageGateway

router = APIRouter(tags=["skills"])


def _get_storage(request: Request) -> StorageGateway:
    return request.app.state.storage


async def _require_tenant(storage: StorageGateway, slug: str) -> None:
    if await storage.tenants.get_by_slug(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {slug}",
        )


def _skill_def_to_upsert_payload(skill: SkillDef) -> dict[str, Any]:
    return {
        "skill_id": skill.id,
        "kind": skill.kind,
        "name": skill.name,
        "model": skill.model,
        "definition": skill.model_dump(mode="python"),
    }


@router.get("/tenants/{slug}/skills", response_model=list[SkillResource])
async def list_skills(slug: str, request: Request) -> list[SkillResource]:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        rows = await storage.tenant_skills.list_for_tenant(slug)
        return [
            skill_def_to_resource(SkillDef.model_validate(row.definition))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list skills: {exc}",
        ) from exc


@router.get("/tenants/{slug}/skills/{skill_id}", response_model=SkillResource)
async def get_skill(skill_id: str, slug: str, request: Request) -> SkillResource:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        row = await storage.tenant_skills.get_for_tenant(slug, skill_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill not found: {skill_id}",
            )
        return skill_def_to_resource(SkillDef.model_validate(row.definition))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get skill: {exc}",
        ) from exc


@router.post("/tenants/{slug}/skills", response_model=SkillResource)
async def save_skill(skill: SkillResource, slug: str, request: Request) -> SkillResource:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        skill_def = resource_to_skill_def(skill)
        await validate_composed_invoke_targets_not_composed(storage, slug, skill_def)
        row = await storage.tenant_skills.upsert_for_tenant(
            slug, _skill_def_to_upsert_payload(skill_def)
        )
        return skill_def_to_resource(SkillDef.model_validate(row.definition))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save skill: {exc}",
        ) from exc


@router.delete("/tenants/{slug}/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: str, slug: str, request: Request) -> Response:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        deleted = await storage.tenant_skills.delete_for_tenant(slug, skill_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill not found: {skill_id}",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete skill: {exc}",
        ) from exc
