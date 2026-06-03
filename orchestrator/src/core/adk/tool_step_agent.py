"""Non-LLM agent that runs a tenant tool and writes the result to session state."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types
from pydantic import PrivateAttr
from typing_extensions import override


class ToolStepAgent(BaseAgent):
    """Executes a registered tool and stores its output under ``output_key`` in session state."""

    output_key: str
    _execute: Callable[[], Any] = PrivateAttr()

    def __init__(
        self,
        *,
        name: str,
        output_key: str,
        execute: Callable[[], Any],
        description: str = "",
    ) -> None:
        super().__init__(name=name, description=description, output_key=output_key)
        self._execute = execute

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        try:
            result = self._execute()
        except Exception as exc:  # noqa: BLE001
            text = json.dumps({"error": str(exc)})
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=text)],
                ),
                state={self.output_key: text},
            )
            return

        if isinstance(result, str):
            stored = result
            text = result
        else:
            stored = json.dumps(result)
            text = stored

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=text)],
            ),
            state={self.output_key: stored},
        )
