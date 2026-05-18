from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.models.schemas import ToolV1, ToolsPageResponse
from src.core.tools.provider import ToolProvider

router = APIRouter(tags=["dictionary"])


@router.get("/tools", response_model=ToolsPageResponse)
def get_tools(request: Request) -> ToolsPageResponse:
    """List all tools registered in the system.

    Returns every tool the orchestrator supports. Actual availability for a
    specific tenant depends on which integrations that tenant has configured.
    """
    tool_provider: ToolProvider = request.app.state.tool_provider
    descriptors = tool_provider.all_descriptors()
    items = [
        ToolV1(name=d.name, description=d.description)
        for d in descriptors
    ]
    total = len(items)
    return ToolsPageResponse(
        items=items,
        total=total,
        page=0,
        size=total,
        total_pages=1 if total > 0 else 0,
        has_more=False,
        is_first=True,
        is_last=True,
    )
