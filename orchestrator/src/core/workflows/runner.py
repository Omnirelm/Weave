"""Execute compiled ADK workflows and collect per-step results."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from google.genai import types

from src.core.adk.session import build_runner, calculate_tokens_by_author, create_task_session
from src.core.base import InvocationCost
from src.core.output import OutputError, coerce_output
from src.core.telemetry import set_weave_context
from src.core.workflows.base import WorkflowDef
from src.core.workflows.compiler import WorkflowCompileResult, WorkflowCompiler
from src.storage.interface import StorageGateway

logger = logging.getLogger(__name__)


def _model_text_from_event(event: Any) -> str | None:
    """Extract final model text from an ADK event when ``event.output`` is unset."""
    content = getattr(event, "content", None)
    if content is None or getattr(content, "role", None) != "model":
        return None
    if event.get_function_calls() or event.get_function_responses():
        return None
    if hasattr(event, "is_final_response") and not event.is_final_response():
        return None
    parts = getattr(content, "parts", None) or []
    text = "".join(
        part.text
        for part in parts
        if getattr(part, "text", None) and not getattr(part, "thought", False)
    )
    if not text.strip():
        text = "".join(part.text for part in parts if getattr(part, "text", None))
    return text if text.strip() else None


def _raw_output_from_event(event: Any) -> Any | None:
    """Return structured or text output from an ADK workflow event."""
    if event.output is not None:
        return event.output
    return _model_text_from_event(event)


@dataclass
class WorkflowStepResult:
    step_id: str
    objective: str
    success: bool
    error: str | None = None
    output: Any = None
    cost: InvocationCost | None = None


@dataclass
class WorkflowResult:
    success: bool
    output: Any = None
    error: str | None = None
    steps_completed: list[WorkflowStepResult] = field(default_factory=list)
    step_execution_detail: dict[str, Any] | None = None
    cost: InvocationCost | None = None


def _workflow_log_suffix(
    *,
    task_id: uuid.UUID | None,
    tenant_id: str,
    workflow_id: str,
    **extra: Any,
) -> str:
    parts = [
        f"task_id={task_id}" if task_id else "task_id=",
        f"tenant={tenant_id}",
        f"workflow_id={workflow_id}",
    ]
    for key, value in extra.items():
        parts.append(f"{key}={value}")
    return " ".join(parts)


def _workflow_session_state(payload: dict[str, Any]) -> dict[str, str]:
    """Seed ADK session state for workflow instruction placeholders."""
    objective = payload.get("objective")
    if not isinstance(objective, str):
        objective = ""
    return {
        "objective": objective,
        "user_input": json.dumps(payload),
    }


class WorkflowRunner:
    """Runs tenant workflows via ADK Workflow graphs."""

    def __init__(
        self,
        storage: StorageGateway,
        compiler: WorkflowCompiler,
    ) -> None:
        self._storage = storage
        self._compiler = compiler

    async def run_workflow(
        self,
        workflow_id: str,
        input_payload: dict[str, Any],
        tenant_id: str,
        *,
        task_id: uuid.UUID | None = None,
    ) -> WorkflowResult:
        row = await self._storage.tenant_workflows.get_for_tenant(tenant_id, workflow_id)
        if row is None:
            return WorkflowResult(success=False, error=f"Unknown workflow_id: {workflow_id!r}")

        try:
            workflow_def = WorkflowDef.model_validate(row.definition)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Invalid workflow definition for %s/%s", tenant_id, workflow_id)
            return WorkflowResult(success=False, error=f"Invalid workflow definition: {exc}")

        payload = dict(input_payload)

        logger.info(
            "workflow.run.start %s",
            _workflow_log_suffix(
                task_id=task_id,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
            ),
        )

        with set_weave_context(tenant_id=tenant_id, task_id=str(task_id) if task_id else None):
            try:
                compiled = await self._compiler.compile(
                    workflow_def,
                    tenant_slug=tenant_id,
                    storage=self._storage,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Workflow compile failed: %s", workflow_id)
                return WorkflowResult(success=False, error=str(exc))

            logger.info(
                "workflow.compile.done %s",
                _workflow_log_suffix(
                    task_id=task_id,
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    node_order=",".join(compiled.node_order),
                    agent_count=len(compiled.node_order),
                ),
            )

            return await self._execute_compiled(
                workflow_def,
                compiled,
                payload,
                tenant_id,
                task_id=task_id,
            )

    async def _execute_compiled(
        self,
        workflow_def: WorkflowDef,
        compiled: WorkflowCompileResult,
        payload: dict[str, Any],
        tenant_id: str,
        *,
        task_id: uuid.UUID | None = None,
    ) -> WorkflowResult:
        started_at = time.monotonic()
        workflow_id = workflow_def.id
        runner = build_runner(compiled.workflow)
        session = await create_task_session(
            runner,
            state=_workflow_session_state(payload),
        )
        message = json.dumps(payload)
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])

        steps_completed: list[WorkflowStepResult] = []
        step_events: list[dict[str, Any]] = []
        cost_children: list[InvocationCost] = []
        tokens_by_author: dict[str, int] = {}
        outputs_by_author: dict[str, Any] = {}
        workflow_error: str | None = None

        def _finish_result(result: WorkflowResult) -> WorkflowResult:
            total_tokens = sum(c.total_tokens for c in cost_children)
            duration_ms = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "workflow.run.finish %s",
                _workflow_log_suffix(
                    task_id=task_id,
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    success=result.success,
                    steps=len(steps_completed),
                    total_tokens=total_tokens,
                    duration_ms=duration_ms,
                ),
            )
            return result

        try:
            async for event in runner.run_async(
                user_id="system",
                session_id=session.id,
                new_message=content,
            ):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "workflow.event %s",
                        _workflow_log_suffix(
                            task_id=task_id,
                            tenant_id=tenant_id,
                            workflow_id=workflow_id,
                            author=event.author or "",
                            has_output=event.output is not None,
                            has_error=getattr(event, "error", None) is not None,
                        ),
                    )

                usage = event.usage_metadata
                if usage is not None:
                    count = getattr(usage, "total_token_count", None)
                    if count is not None and event.author:
                        tokens_by_author[event.author] = (
                            tokens_by_author.get(event.author, 0) + int(count)
                        )

                if getattr(event, "error", None):
                    workflow_error = str(event.error)
                    step_events.append(
                        {
                            "type": "error",
                            "author": event.author,
                            "error": workflow_error,
                        }
                    )
                    logger.info(
                        "workflow.step.done %s",
                        _workflow_log_suffix(
                            task_id=task_id,
                            tenant_id=tenant_id,
                            workflow_id=workflow_id,
                            author=event.author or "",
                            success=False,
                            error=workflow_error,
                        ),
                    )
                    break

                raw_output = _raw_output_from_event(event)
                if raw_output is not None and event.author:
                    outputs_by_author[event.author] = raw_output
                    node_id = compiled.agent_name_to_node_id.get(event.author)
                    if node_id is None:
                        continue
                    agent_id = event.author.removeprefix("agent_")
                    try:
                        validated_output = coerce_output(raw_output)
                    except OutputError as exc:
                        workflow_error = str(exc)
                        step_tokens = tokens_by_author.get(event.author, 0)
                        steps_completed.append(
                            WorkflowStepResult(
                                step_id=node_id,
                                objective=compiled.node_objectives.get(node_id) or agent_id,
                                success=False,
                                error=workflow_error,
                                cost=InvocationCost(
                                    label=f"agent:{agent_id}",
                                    total_tokens=step_tokens,
                                ),
                            )
                        )
                        step_events.append(
                            {
                                "type": "step",
                                "step_id": node_id,
                                "agent_id": agent_id,
                                "success": False,
                                "error": workflow_error,
                            }
                        )
                        logger.info(
                            "workflow.step.done %s",
                            _workflow_log_suffix(
                                task_id=task_id,
                                tenant_id=tenant_id,
                                workflow_id=workflow_id,
                                step_id=node_id,
                                agent_id=agent_id,
                                success=False,
                                tokens=step_tokens,
                                error=workflow_error,
                            ),
                        )
                        break

                    step_cost = InvocationCost(
                        label=f"agent:{agent_id}",
                        total_tokens=tokens_by_author.get(event.author, 0),
                    )
                    cost_children.append(step_cost)
                    steps_completed.append(
                        WorkflowStepResult(
                            step_id=node_id,
                            objective=compiled.node_objectives.get(node_id) or agent_id,
                            success=True,
                            output=validated_output,
                            cost=step_cost,
                        )
                    )
                    step_events.append(
                        {
                            "type": "step",
                            "step_id": node_id,
                            "agent_id": agent_id,
                            "success": True,
                        }
                    )
                    logger.info(
                        "workflow.step.done %s",
                        _workflow_log_suffix(
                            task_id=task_id,
                            tenant_id=tenant_id,
                            workflow_id=workflow_id,
                            step_id=node_id,
                            agent_id=agent_id,
                            success=True,
                            tokens=step_cost.total_tokens,
                        ),
                    )

            try:
                loaded = await runner.session_service.get_session(
                    app_name=runner.app_name,
                    user_id="system",
                    session_id=session.id,
                )
            except (TypeError, AttributeError):
                loaded = None

            if loaded is not None and getattr(loaded, "events", None) is not None:
                tokens_by_author = calculate_tokens_by_author(loaded.events)

            if not steps_completed and loaded is not None:
                for agent_id in compiled.agents_by_id:
                    key = f"agent_{agent_id}_out"
                    if key not in loaded.state:
                        continue
                    author = f"agent_{agent_id}"
                    if author in outputs_by_author:
                        continue
                    node_id = compiled.agent_name_to_node_id.get(author)
                    if node_id is None:
                        continue
                    try:
                        validated_output = coerce_output(loaded.state[key])
                    except OutputError as exc:
                        workflow_error = str(exc)
                        break
                    outputs_by_author[author] = validated_output
                    step_cost = InvocationCost(
                        label=f"agent:{agent_id}",
                        total_tokens=tokens_by_author.get(author, 0),
                    )
                    cost_children.append(step_cost)
                    steps_completed.append(
                        WorkflowStepResult(
                            step_id=node_id,
                            objective=compiled.node_objectives.get(node_id) or agent_id,
                            success=True,
                            output=validated_output,
                            cost=step_cost,
                        )
                    )

            # Update final step costs from the native session events
            for step in steps_completed:
                if step.cost:
                    agent_id = step.cost.label.split(":")[-1]
                    author = f"agent_{agent_id}"
                    step.cost.total_tokens = tokens_by_author.get(author, 0)

            if workflow_error:
                total_tokens = sum(c.total_tokens for c in cost_children)
                return _finish_result(
                    WorkflowResult(
                        success=False,
                        error=workflow_error,
                        steps_completed=steps_completed,
                        step_execution_detail={
                            "schemaVersion": 1,
                            "events": step_events,
                        },
                        cost=InvocationCost(
                            label="workflow",
                            children=cost_children,
                            total_tokens=total_tokens,
                        ),
                    )
                )

            try:
                final_output = self._resolve_final_output(
                    compiled,
                    outputs_by_author,
                    steps_completed,
                )
            except OutputError as exc:
                logger.warning(
                    "workflow.validation.failed %s error=%s",
                    _workflow_log_suffix(
                        task_id=task_id,
                        tenant_id=tenant_id,
                        workflow_id=workflow_id,
                        phase="output",
                    ),
                    exc,
                )
                total_tokens = sum(c.total_tokens for c in cost_children)
                return _finish_result(
                    WorkflowResult(
                        success=False,
                        error=str(exc),
                        steps_completed=steps_completed,
                        step_execution_detail={
                            "schemaVersion": 1,
                            "events": step_events,
                        },
                        cost=InvocationCost(
                            label="workflow",
                            children=cost_children,
                            total_tokens=total_tokens,
                        ),
                    )
                )

            total_tokens = sum(c.total_tokens for c in cost_children)
            return _finish_result(
                WorkflowResult(
                    success=True,
                    output=final_output,
                    steps_completed=steps_completed,
                    step_execution_detail={
                        "schemaVersion": 1,
                        "events": step_events,
                    },
                    cost=InvocationCost(
                        label="workflow",
                        children=cost_children,
                        total_tokens=total_tokens,
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Workflow run failed: %s", workflow_def.id)
            total_tokens = sum(c.total_tokens for c in cost_children)
            return _finish_result(
                WorkflowResult(
                    success=False,
                    error=str(exc),
                    steps_completed=steps_completed,
                    step_execution_detail={
                        "schemaVersion": 1,
                        "events": step_events,
                    },
                    cost=InvocationCost(
                        label="workflow",
                        children=cost_children,
                        total_tokens=total_tokens,
                    ),
                )
            )

    @staticmethod
    def _resolve_final_output(
        compiled: WorkflowCompileResult,
        outputs_by_author: dict[str, Any],
        steps_completed: list[WorkflowStepResult],
    ) -> Any:
        if compiled.node_order:
            terminal_node_id = compiled.node_order[-1]
            for step in reversed(steps_completed):
                if step.step_id == terminal_node_id and step.success:
                    return step.output
        for step in reversed(steps_completed):
            if step.success and step.output is not None:
                return step.output
        for author in reversed(list(outputs_by_author.keys())):
            if outputs_by_author[author] is not None:
                return outputs_by_author[author]
        raise OutputError("Workflow produced no output")
