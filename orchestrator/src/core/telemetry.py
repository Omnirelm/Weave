"""Telemetry helpers for context-propagated tracing attributes (task_id, tenant_id)."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Generator

from opentelemetry import context
from opentelemetry.context import get_value
from opentelemetry.sdk.trace import SpanProcessor

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import Span


class WeaveSpanProcessor(SpanProcessor):
    """Span processor that propagates weave context attributes to all created spans."""

    def on_start(self, span: Span, parent_context: context.Context | None = None) -> None:
        tenant_id = get_value("weave.tenant_id", parent_context)
        task_id = get_value("weave.task_id", parent_context)
        if tenant_id:
            span.set_attribute("weave.tenant_id", tenant_id)
        if task_id:
            span.set_attribute("weave.task_id", str(task_id))


@contextlib.contextmanager
def set_weave_context(*, tenant_id: str, task_id: str | None = None) -> Generator[None, None, None]:
    """Context manager to bind tenant_id and task_id to the active OpenTelemetry context."""
    ctx = context.get_current()
    ctx = context.set_value("weave.tenant_id", tenant_id, ctx)
    if task_id:
        ctx = context.set_value("weave.task_id", str(task_id), ctx)
    token = context.attach(ctx)
    try:
        yield
    finally:
        context.detach(token)
