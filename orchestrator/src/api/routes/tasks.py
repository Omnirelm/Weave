"""Task routes: validate hints, persist runs; orchestration lives in core.orchestration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.models.schemas import RunTaskRequest, RunTaskResponse
from src.api.translators.tasks import RunTaskRequestDomain, run_task_request_to_domain
from src.core.orchestration.execution_detail import execution_detail_for_persist
from src.core.orchestration.executor import execute_plan_step as _execute_plan_step
from src.core.orchestration.models import (
    ExecutionPlan,
    PlanStep,
    TaskRunState,
    skill_input_payload as _skill_input_payload,
)
from src.core.orchestration.planner import run_planner as _run_planner
from src.core.orchestration.service import execute_run_task
from src.core.skills import SkillDef
from src.core.skills.input_validation import validate_skill_instance
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _step_execution_detail_for_persist(state: TaskRunState) -> Any:
    return execution_detail_for_persist(state.execution_events)


async def _persist_task_run_record(
    storage: StorageGateway,
    *,
    task_id: uuid.UUID,
    started_at: datetime,
    domain_body: RunTaskRequestDomain,
    state: TaskRunState,
    response: RunTaskResponse,
) -> None:
    finished_at = datetime.now(timezone.utc)
    cost_payload = (
        response.cost.model_dump(by_alias=True, exclude_none=True) if response.cost else None
    )
    steps_payload = [
        step.model_dump(by_alias=True, exclude_none=True) for step in response.steps_completed
    ]
    await storage.task_runs.create(
        {
            "id": task_id,
            "tenant_slug": domain_body.tenant_id,
            "success": response.success,
            "objective": domain_body.task,
            "skill_id": domain_body.skill_id,
            "request_input": domain_body.input or None,
            "output": response.output,
            "summary": None,
            "reasoning": response.reasoning,
            "error": response.error,
            "steps_completed": steps_payload,
            "step_execution_detail": _step_execution_detail_for_persist(state) or None,
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
    state: TaskRunState,
    response: RunTaskResponse,
) -> RunTaskResponse:
    try:
        await _persist_task_run_record(
            storage,
            task_id=task_id,
            started_at=started_at,
            domain_body=domain_body,
            state=state,
            response=response,
        )
    except Exception:
        logger.exception("task_run persist failed")
        raise HTTPException(status_code=500, detail="Failed to persist task run") from None
    return response


@router.post("/run", response_model=RunTaskResponse)
async def run_task(body: RunTaskRequest, request: Request) -> RunTaskResponse:
    domain_body = run_task_request_to_domain(body)
    storage: StorageGateway = request.app.state.storage
    runner = request.app.state.skill_runner

    if domain_body.skill_id:
        row = await storage.tenant_skills.get_for_tenant(
            domain_body.tenant_id, domain_body.skill_id
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown skill_id: {domain_body.skill_id!r}",
            )
        try:
            skill = SkillDef.model_validate(row.definition)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid skill definition in database: {exc}",
            ) from exc
        merged = _skill_input_payload(domain_body)
        try:
            validate_skill_instance(skill, merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    task_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    response, state = await execute_run_task(
        task_id=task_id,
        domain_body=domain_body,
        storage=storage,
        runner=runner,
    )
    return await _return_with_persisted_run(
        storage,
        task_id=task_id,
        started_at=started_at,
        domain_body=domain_body,
        state=state,
        response=response,
    )
