"""Task routes: run a tenant workflow or agent and persist the result."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from typing import Any
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, status

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
            "request_context": domain_body.context or None,
            "output": response.output,
            "summary": None,
            "reasoning": response.reasoning,
            "error": response.error,
            "step_execution_detail": state_step_detail,
            "cost": cost_payload,
            "session_id": str(task_id),
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
                request_context=row.request_context,
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
            request_context=row.request_context,
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


def parse_grafana_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """Parse Grafana Alertmanager webhook payload and extract objective + context."""
    objective = "Investigate and provide reasoning for Grafana alerts"
    context = json.dumps(payload, indent=2)
    return objective, context


async def _execute_trigger_async(
    task_id: uuid.UUID,
    domain_body: RunTaskRequestDomain,
    runner: Any,
    workflow_runner: Any,
    storage: StorageGateway,
) -> None:
    started_at = datetime.now(timezone.utc)
    try:
        response, state = await execute_run_task(
            task_id=task_id,
            domain_body=domain_body,
            runner=runner,
            workflow_runner=workflow_runner,
        )
        await _persist_task_run_record(
            storage,
            task_id=task_id,
            started_at=started_at,
            domain_body=domain_body,
            response=response,
            state_step_detail=state.step_execution_detail,
        )
    except Exception as exc:
        logger.exception("async webhook execution failed task_id=%s", task_id)
        try:
            from src.api.translators.tasks import build_run_task_response
            response = build_run_task_response(
                task_id=task_id,
                success=False,
                error=str(exc) or "Webhook background execution failed",
                cost=None,
            )
            await _persist_task_run_record(
                storage,
                task_id=task_id,
                started_at=started_at,
                domain_body=domain_body,
                response=response,
            )
        except Exception:
            logger.exception("failed to persist failure task run record task_id=%s", task_id)


async def _handle_grafana_trigger(
    slug: str,
    target_id: str,
    target_type: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    storage: StorageGateway = request.app.state.storage
    await _require_tenant(storage, slug)

    if target_type == "workflow":
        row = await storage.tenant_workflows.get_for_tenant(slug, target_id)
        err_msg = f"Workflow not found: {target_id}"
    else:
        row = await storage.tenant_agents.get_for_tenant(slug, target_id)
        err_msg = f"Agent not found: {target_id}"

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=err_msg,
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload",
        )

    objective, context = parse_grafana_payload(payload)

    domain_body = RunTaskRequestDomain(
        objective=objective,
        tenant_id=slug,
        workflow_id=target_id if target_type == "workflow" else "",
        agent_id=target_id if target_type == "agent" else "",
        context=context,
    )

    task_id = uuid.uuid4()

    runner = request.app.state.agent_runner
    workflow_runner = request.app.state.workflow_runner

    background_tasks.add_task(
        _execute_trigger_async,
        task_id=task_id,
        domain_body=domain_body,
        runner=runner,
        workflow_runner=workflow_runner,
        storage=storage,
    )

    return {"task_id": str(task_id), "status": "accepted"}


@router.post(
    "/tenants/{slug}/triggers/grafana/workflows/{workflow_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_grafana_workflow(
    slug: str,
    workflow_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    return await _handle_grafana_trigger(
        slug=slug,
        target_id=workflow_id,
        target_type="workflow",
        request=request,
        background_tasks=background_tasks,
    )


@router.post(
    "/tenants/{slug}/triggers/grafana/agents/{agent_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_grafana_agent(
    slug: str,
    agent_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    return await _handle_grafana_trigger(
        slug=slug,
        target_id=agent_id,
        target_type="agent",
        request=request,
        background_tasks=background_tasks,
    )

