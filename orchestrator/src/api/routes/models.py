from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.models.schemas import ModelV1, ModelsPageResponse

router = APIRouter(tags=["dictionary"])


# Static list of latest supported models
SUPPORTED_MODELS = [
    # Gemini
    ModelV1(id="gemini/gemini-3.5-flash", name="Gemini 3.5 Flash", provider="gemini"),
    ModelV1(id="gemini/gemini-3-flash", name="Gemini 3 Flash", provider="gemini"),
    ModelV1(id="gemini/gemini-3.1-flash-lite", name="Gemini 3.1 Flash-Lite", provider="gemini"),
    # OpenAI
    ModelV1(id="openai/gpt-5.5", name="GPT-5.5", provider="openai"),
    ModelV1(id="openai/gpt-5.4", name="GPT-5.4", provider="openai"),
    ModelV1(id="openai/gpt-5.4-mini", name="GPT-5.4 Mini", provider="openai"),
    ModelV1(id="openai/gpt-5.4-nano", name="GPT-5.4 Nano", provider="openai"),
    # Anthropic
    ModelV1(id="anthropic/claude-3-5-sonnet", name="Claude 3.5 Sonnet", provider="anthropic"),
    ModelV1(id="anthropic/claude-3-5-haiku", name="Claude 3.5 Haiku", provider="anthropic"),
    ModelV1(id="anthropic/claude-3-opus", name="Claude 3 Opus", provider="anthropic"),
]


@router.get("/models", response_model=ModelsPageResponse)
def get_models(request: Request) -> ModelsPageResponse:
    """List all AI models supported by the orchestrator.

    Returns the list of latest models from Google/Gemini, OpenAI, and Anthropic.
    """
    total = len(SUPPORTED_MODELS)
    return ModelsPageResponse(
        items=SUPPORTED_MODELS,
        total=total,
        page=0,
        size=total,
        total_pages=1 if total > 0 else 0,
        has_more=False,
        is_first=True,
        is_last=True,
    )
