"""
LLM configuration endpoints — runtime provider/model switching.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tg_parser.api.auth import verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/llm", tags=["LLM Config"])


class LLMConfigUpdateRequest(BaseModel):
    scope: str
    provider: str
    model: str | None = None


class LLMConfigResetRequest(BaseModel):
    scope: str | None = None


class LLMConfigResponse(BaseModel):
    config: dict[str, Any]


class LLMConfigUpdateResponse(BaseModel):
    success: bool
    message: str
    config: dict[str, Any]


@router.get("/config", response_model=LLMConfigResponse)
async def get_llm_config(_client: str | None = Depends(verify_api_key)) -> LLMConfigResponse:
    """Return the current active LLM configuration (global + per-stage)."""
    from tg_parser.config import llm_config

    return LLMConfigResponse(config=llm_config.get_all())


@router.put("/config", response_model=LLMConfigUpdateResponse)
async def set_llm_config(body: LLMConfigUpdateRequest, _client: str | None = Depends(verify_api_key)) -> LLMConfigUpdateResponse:
    """Change the LLM provider/model at runtime (no restart needed)."""
    from tg_parser.config import llm_config

    try:
        updated = llm_config.set(scope=body.scope, provider=body.provider, model=body.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return LLMConfigUpdateResponse(
        success=True,
        message=f"LLM config updated: scope={body.scope}, provider={body.provider}"
        + (f", model={body.model}" if body.model else ""),
        config=updated,
    )


@router.post("/config/reset", response_model=LLMConfigUpdateResponse)
async def reset_llm_config(body: LLMConfigResetRequest | None = None, _client: str | None = Depends(verify_api_key)) -> LLMConfigUpdateResponse:
    """Reset runtime LLM overrides, reverting to .env defaults."""
    from tg_parser.config import llm_config

    scope = body.scope if body else None
    updated = llm_config.clear(scope=scope)
    label = scope or "all scopes"
    return LLMConfigUpdateResponse(
        success=True,
        message=f"LLM config reset for {label}. Now using .env defaults.",
        config=updated,
    )
