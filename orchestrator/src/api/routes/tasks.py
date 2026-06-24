"""Task routes: run a tenant workflow or agent and persist the result."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src.api.models.schemas import RunTaskRequest, RunTaskResponse, TaskRunResponse
from src.api.translators.tasks import RunTaskRequestDomain, run_task_request_to_domain
from src.core.orchestration.service import execute_run_task
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])


async def _persist_task_run_record(
    storage: StorageGateway,
    *,
    task_id: uuid.UUID,
    started_at: datetime,
    domain_body: RunTaskRequestDomain,
    response: RunTaskResponse,
    state_step_detail: dict | None = None,
) -> None:
    finished_at = datetime.now(timezone.utc)
    cost_payload = (
        response.cost.model_dump(by_alias=True, exclude_none=True) if response.cost else None
    )
    await storage.task_runs.create(
        {
            "id": task_id,
            "tenant_slug": domain_body.tenant_id,
            "success": response.success,
            "objective": domain_body.objective,
            "agent_id": domain_body.agent_id or None,
            "workflow_id": domain_body.workflow_id or None,
            "request_input": domain_body.input or None,
            "output": response.output,
            "summary": None,
            "reasoning": response.reasoning,
            "error": response.error,
            "step_execution_detail": state_step_detail,
            "cost": cost_payload,
            "started_at": started_at,
            "finished_at": finished_at,
        }
    )


async def _return_with_persisted_run(
    storage: StorageGateway,
    *,
    task_id: uuid.UUID,
    started_at: datetime,
    domain_body: RunTaskRequestDomain,
    response: RunTaskResponse,
    state_step_detail: dict | None = None,
) -> RunTaskResponse:
    try:
        await _persist_task_run_record(
            storage,
            task_id=task_id,
            started_at=started_at,
            domain_body=domain_body,
            response=response,
            state_step_detail=state_step_detail,
        )
    except Exception:
        logger.exception("task_run persist failed")
        raise HTTPException(status_code=500, detail="Failed to persist task run") from None
    return response


@router.post("/tenants/{slug}/runs", response_model=RunTaskResponse)
async def run_task(slug: str, body: RunTaskRequest, request: Request) -> RunTaskResponse:
    if body.slug != slug:
        raise HTTPException(
            status_code=400,
            detail=f"Tenant slug in body {body.slug!r} does not match path {slug!r}",
        )
    domain_body = run_task_request_to_domain(body)

    storage: StorageGateway = request.app.state.storage
    runner = request.app.state.agent_runner
    workflow_runner = request.app.state.workflow_runner

    if domain_body.workflow_id:
        row = await storage.tenant_workflows.get_for_tenant(
            domain_body.tenant_id, domain_body.workflow_id
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown workflow_id: {domain_body.workflow_id!r}",
            )
    else:
        row = await storage.tenant_agents.get_for_tenant(
            domain_body.tenant_id, domain_body.agent_id
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown agent_id: {domain_body.agent_id!r}",
            )

    task_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    response, state = await execute_run_task(
        task_id=task_id,
        domain_body=domain_body,
        runner=runner,
        workflow_runner=workflow_runner,
    )
    return await _return_with_persisted_run(
        storage,
        task_id=task_id,
        started_at=started_at,
        domain_body=domain_body,
        response=response,
        state_step_detail=state.step_execution_detail,
    )


async def _require_tenant(storage: StorageGateway, slug: str) -> None:
    if await storage.tenants.get_by_slug(slug) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant not found: {slug}",
        )


@router.get("/tenants/{slug}/runs", response_model=list[TaskRunResponse])
async def list_runs(slug: str, request: Request) -> list[TaskRunResponse]:
    storage: StorageGateway = request.app.state.storage
    await _require_tenant(storage, slug)
    try:
        rows = await storage.task_runs.list_for_tenant(slug)
        return [
            TaskRunResponse(
                id=row.id,
                tenant_slug=row.tenant_slug,
                success=row.success,
                objective=row.objective,
                agent_id=row.agent_id,
                workflow_id=row.workflow_id,
                request_input=row.request_input,
                output=row.output,
                summary=row.summary,
                reasoning=row.reasoning,
                error=row.error,
                step_execution_detail=row.step_execution_detail,
                cost=row.cost,
                started_at=row.started_at,
                finished_at=row.finished_at,
            )
            for row in rows
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list task runs: {exc}",
        ) from exc


@router.get("/tenants/{slug}/runs/{run_id}", response_model=TaskRunResponse)
async def get_run(slug: str, run_id: uuid.UUID, request: Request) -> TaskRunResponse:
    storage: StorageGateway = request.app.state.storage
    await _require_tenant(storage, slug)
    try:
        row = await storage.task_runs.get_for_tenant(slug, run_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Task run not found: {run_id}",
            )
        return TaskRunResponse(
            id=row.id,
            tenant_slug=row.tenant_slug,
            success=row.success,
            objective=row.objective,
            agent_id=row.agent_id,
            workflow_id=row.workflow_id,
            request_input=row.request_input,
            output=row.output,
            summary=row.summary,
            reasoning=row.reasoning,
            error=row.error,
            step_execution_detail=row.step_execution_detail,
            cost=row.cost,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task run: {exc}",
        ) from exc

