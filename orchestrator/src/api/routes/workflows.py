from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.api.models.schemas import WorkflowResource
from src.api.translators.workflows import resource_to_workflow_def, workflow_def_to_resource
from src.core.workflows import WorkflowDef
from src.core.workflows.validation import validate_workflow_instance
from src.storage.interface import StorageGateway

router = APIRouter(tags=["workflows"])


def _get_storage(request: Request) -> StorageGateway:
    return request.app.state.storage


async def _require_tenant(storage: StorageGateway, slug: str) -> None:
    if await storage.tenants.get_by_slug(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {slug}",
        )


def _workflow_def_to_upsert_payload(workflow: WorkflowDef) -> dict[str, Any]:
    return {
        "workflow_id": workflow.id,
        "name": workflow.name,
        "definition": workflow.model_dump(mode="python"),
    }


@router.get("/tenants/{slug}/workflows", response_model=list[WorkflowResource])
async def list_workflows(slug: str, request: Request) -> list[WorkflowResource]:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        rows = await storage.tenant_workflows.list_for_tenant(slug)
        return [
            workflow_def_to_resource(WorkflowDef.model_validate(row.definition))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list workflows: {exc}",
        ) from exc


@router.get("/tenants/{slug}/workflows/{workflow_id}", response_model=WorkflowResource)
async def get_workflow(workflow_id: str, slug: str, request: Request) -> WorkflowResource:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        row = await storage.tenant_workflows.get_for_tenant(slug, workflow_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow not found: {workflow_id}",
            )
        return workflow_def_to_resource(WorkflowDef.model_validate(row.definition))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow: {exc}",
        ) from exc


@router.post("/tenants/{slug}/workflows", response_model=WorkflowResource)
async def save_workflow(
    workflow: WorkflowResource, slug: str, request: Request
) -> WorkflowResource:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        workflow_def = resource_to_workflow_def(workflow)
        await validate_workflow_instance(workflow_def, tenant_slug=slug, storage=storage)
        row = await storage.tenant_workflows.upsert_for_tenant(
            slug, _workflow_def_to_upsert_payload(workflow_def)
        )
        return workflow_def_to_resource(WorkflowDef.model_validate(row.definition))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save workflow: {exc}",
        ) from exc


@router.delete(
    "/tenants/{slug}/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow(workflow_id: str, slug: str, request: Request) -> Response:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        deleted = await storage.tenant_workflows.delete_for_tenant(slug, workflow_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow not found: {workflow_id}",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete workflow: {exc}",
        ) from exc
