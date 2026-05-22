"""
Pipeline one-shot dispatch (ADR 0007 — Wave 1 step 3.1).

``POST /api/v1/pipeline/trigger`` queues ingest / topicize / link-topics
jobs on the ``tg_parser`` container. MCP and Bot call this endpoint via
:class:`tg_parser.services.pipeline_dispatch_client`.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.idempotency import IdempotencyContext, idempotency_key_check
from tg_parser.api.middleware import limiter
from tg_parser.api.schemas import (
    ErrorResponse,
    PipelineTriggerRequest,
    PipelineTriggerResponse,
)
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import assert_channel_access
from tg_parser.config import settings
from tg_parser.services.pipeline_dispatch_service import (
    PipelineDispatchError,
    trigger_pipeline_job,
)

router = APIRouter(prefix="/api/v1/pipeline", tags=["Pipeline"])
logger = structlog.get_logger(__name__)


def _error_response(exc: PipelineDispatchError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "error_class": exc.error_class},
    )


@router.post(
    "/trigger",
    response_model=PipelineTriggerResponse,
    responses={
        401: {"model": ErrorResponse, "description": "API key required"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Source not found"},
        409: {"model": ErrorResponse, "description": "Job already running"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
@limiter.limit(settings.rate_limit_pipeline_trigger)
async def post_pipeline_trigger(
    request: Request,
    body: PipelineTriggerRequest,
    user: CurrentUser = Depends(resolve_current_user),
    idempotency: IdempotencyContext | None = Depends(idempotency_key_check),
) -> PipelineTriggerResponse | JSONResponse:
    """
    Queue a one-shot pipeline job (async).

    Returns ``job_id`` immediately; work runs in the ``tg_parser`` process.
    Poll ``GET /api/v1/status/{job_id}`` when the job was stored, or use
    ``get_pipeline_status`` / container logs for coarse progress.
    """
    if (
        idempotency is not None
        and idempotency.status == "hit"
        and idempotency.cached_body is not None
    ):
        replay = dict(idempotency.cached_body)
        replay["created"] = False
        return JSONResponse(
            status_code=idempotency.cached_status or 200,
            content=replay,
        )

    await assert_channel_access(user, body.channel_id)

    try:
        accepted = await trigger_pipeline_job(
            channel_id=body.channel_id,
            job=body.job,
            force=body.force,
            surface="api",
        )
    except PipelineDispatchError as exc:
        return _error_response(exc)

    response = PipelineTriggerResponse(
        job_id=accepted.job_id,
        created=accepted.created,
        status=accepted.status,
        channel_id=body.channel_id,
        job=body.job,
    )

    if idempotency is not None and idempotency.status == "miss":
        await idempotency.store(
            status_code=200,
            body=response.model_dump(mode="json"),
        )

    logger.info(
        "api_pipeline_trigger",
        job_id=accepted.job_id,
        channel_id=body.channel_id,
        job=body.job,
        user_id=user.id,
    )
    return response
