"""Task run: execute a tenant workflow or single agent."""

from __future__ import annotations

import logging
import uuid

from src.api.models.schemas import RunTaskResponse
from src.api.translators.tasks import (
    RunTaskRequestDomain,
    agent_context_payload,
    build_run_task_response,
    invocation_cost_to_dto,
    serialize_task_output,
)
from src.core.agents import AgentRunner
from src.core.base import InvocationCost
from src.core.orchestration.models import TaskRunState
from src.core.workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)


async def _execute_single_agent(
    *,
    task_id: uuid.UUID,
    domain_body: RunTaskRequestDomain,
    runner: AgentRunner,
) -> tuple[RunTaskResponse, TaskRunState]:
    state = TaskRunState(agent_id=domain_body.agent_id)
    payload = agent_context_payload(domain_body)

    result = await runner.run_agent(
        domain_body.agent_id,
        payload,
        domain_body.tenant_id,
        task_id=task_id,
    )

    if result.cost is not None:
        state.cost_children.append(result.cost)

    if result.success:
        state.agent_output = serialize_task_output(result.output)
        total_tokens = sum(c.total_tokens for c in state.cost_children)
        return (
            build_run_task_response(
                task_id=task_id,
                success=True,
                error=None,
                output=state.agent_output,
                cost=InvocationCost(
                    label="run_task",
                    children=state.cost_children,
                    total_tokens=total_tokens,
                ),
            ),
            state,
        )

    state.last_error = result.error or "Agent run failed"
    total_tokens = sum(c.total_tokens for c in state.cost_children)
    return (
        build_run_task_response(
            task_id=task_id,
            success=False,
            error=state.last_error,
            output=None,
            cost=InvocationCost(
                label="run_task",
                children=state.cost_children,
                total_tokens=total_tokens,
            ),
        ),
        state,
    )


async def _execute_workflow(
    *,
    task_id: uuid.UUID,
    domain_body: RunTaskRequestDomain,
    workflow_runner: WorkflowRunner,
) -> tuple[RunTaskResponse, TaskRunState]:
    state = TaskRunState(workflow_id=domain_body.workflow_id)
    payload = agent_context_payload(domain_body)

    logger.info(
        "task.workflow.start task_id=%s tenant=%s workflow_id=%s",
        task_id,
        domain_body.tenant_id,
        domain_body.workflow_id,
    )

    result = await workflow_runner.run_workflow(
        domain_body.workflow_id,
        payload,
        domain_body.tenant_id,
        task_id=task_id,
    )

    logger.info(
        "task.workflow.finish task_id=%s tenant=%s workflow_id=%s success=%s",
        task_id,
        domain_body.tenant_id,
        domain_body.workflow_id,
        result.success,
    )

    if result.cost is not None and result.cost.children:
        state.cost_children.extend(result.cost.children)

    state.step_execution_detail = result.step_execution_detail

    if result.success:
        state.agent_output = serialize_task_output(result.output)
        total_tokens = sum(c.total_tokens for c in state.cost_children)
        return (
            build_run_task_response(
                task_id=task_id,
                success=True,
                error=None,
                output=state.agent_output,
                cost=InvocationCost(
                    label="run_task",
                    children=state.cost_children,
                    total_tokens=total_tokens,
                ),
            ),
            state,
        )

    state.last_error = result.error or "Workflow run failed"
    total_tokens = sum(c.total_tokens for c in state.cost_children)
    return (
        build_run_task_response(
            task_id=task_id,
            success=False,
            error=state.last_error,
            output=None,
            cost=InvocationCost(
                label="run_task",
                children=state.cost_children,
                total_tokens=total_tokens,
            ),
        ),
        state,
    )


async def execute_run_task(
    *,
    task_id: uuid.UUID,
    domain_body: RunTaskRequestDomain,
    runner: AgentRunner,
    workflow_runner: WorkflowRunner | None = None,
) -> tuple[RunTaskResponse, TaskRunState]:
    """Run the requested workflow or agent and return response + persistence state."""
    if domain_body.workflow_id:
        if workflow_runner is None:
            raise ValueError("workflow_runner is required for workflow execution")
        return await _execute_workflow(
            task_id=task_id,
            domain_body=domain_body,
            workflow_runner=workflow_runner,
        )
    if domain_body.agent_id:
        return await _execute_single_agent(
            task_id=task_id,
            domain_body=domain_body,
            runner=runner,
        )
    raise ValueError("workflow_id or agent_id required")
