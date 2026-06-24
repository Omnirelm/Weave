from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.api.models.schemas import AgentResource
from src.api.translators.agents import agent_def_to_resource, resource_to_agent_def
from src.core.agents import AgentDef
from src.storage.interface import StorageGateway

router = APIRouter(tags=["agents"])


def _get_storage(request: Request) -> StorageGateway:
    return request.app.state.storage


async def _require_tenant(storage: StorageGateway, slug: str) -> None:
    if await storage.tenants.get_by_slug(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {slug}",
        )


def _agent_def_to_upsert_payload(agent: AgentDef) -> dict[str, Any]:
    return {
        "agent_id": agent.id,
        "name": agent.name,
        "model": agent.model,
        "definition": agent.model_dump(mode="python"),
    }


@router.get("/tenants/{slug}/agents", response_model=list[AgentResource])
async def list_agents(slug: str, request: Request) -> list[AgentResource]:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        rows = await storage.tenant_agents.list_for_tenant(slug)
        return [
            agent_def_to_resource(AgentDef.model_validate(row.definition))
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents: {exc}",
        ) from exc


@router.get("/tenants/{slug}/agents/{agent_id}", response_model=AgentResource)
async def get_agent(agent_id: str, slug: str, request: Request) -> AgentResource:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        row = await storage.tenant_agents.get_for_tenant(slug, agent_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_id}",
            )
        return agent_def_to_resource(AgentDef.model_validate(row.definition))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent: {exc}",
        ) from exc


@router.post("/tenants/{slug}/agents", response_model=AgentResource)
async def save_agent(agent: AgentResource, slug: str, request: Request) -> AgentResource:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        agent_def = resource_to_agent_def(agent)
        row = await storage.tenant_agents.upsert_for_tenant(
            slug, _agent_def_to_upsert_payload(agent_def)
        )
        return agent_def_to_resource(AgentDef.model_validate(row.definition))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save agent: {exc}",
        ) from exc


@router.delete("/tenants/{slug}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, slug: str, request: Request) -> Response:
    storage = _get_storage(request)
    await _require_tenant(storage, slug)
    try:
        deleted = await storage.tenant_agents.delete_for_tenant(slug, agent_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_id}",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete agent: {exc}",
        ) from exc
