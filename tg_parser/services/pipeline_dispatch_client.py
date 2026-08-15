"""
Thin HTTP client for MCP/Bot → ``tg_parser`` pipeline dispatch (ADR 0007).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx
import structlog
from mcp.server.fastmcp import Context

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.resolvers import hash_credential, resolve_user_by_auth
from tg_parser.config import settings
from tg_parser.services.pipeline_dispatch_service import (
    PipelineJobKind,
)
from tg_parser.utils.channel_id import normalize_channel_id

logger = structlog.get_logger(__name__)

DISPATCH_NOT_IMPLEMENTED = "DispatchNotImplemented"
DISPATCH_HTTP_ERROR = "DispatchHttpError"
DISPATCH_AUTH_REQUIRED = "DispatchAuthRequired"


@dataclass(frozen=True)
class PipelineDispatchClientResult:
    channel_id: str
    triggered: bool
    message: str
    error_class: str | None = None
    job_id: str | None = None
    job: str | None = None
    workaround: str | None = None


@dataclass(frozen=True)
class ExportDispatchClientResult:
    """MCP/Bot → ``POST /api/v1/export`` (BUG-096 / ADR 0007)."""

    job_id: str
    status: str
    message: str
    channel_id: str = ""
    level: str = ""
    format: str = ""
    download_url: str | None = None


def extract_mcp_dispatch_api_key(ctx: Context | None) -> str | None:
    """Return the raw bearer token to forward as ``X-API-Key``."""
    del ctx
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except ImportError:  # pragma: no cover
        return None

    token = get_access_token()
    if token is None:
        return None
    raw = getattr(token, "token", None)
    return str(raw) if raw else None


async def resolve_dispatch_api_key_for_user(user: CurrentUser) -> str | None:
    """Find a settings API key that maps to ``user`` (bot proxy path)."""
    for raw_key in settings.api_keys:
        hashed = hash_credential(raw_key)
        resolved = await resolve_user_by_auth("api_key", hashed)
        if resolved is not None and resolved.id == user.id:
            return raw_key
    for raw_token in settings.mcp_auth_tokens:
        hashed = hash_credential(raw_token)
        resolved = await resolve_user_by_auth("mcp_token", hashed)
        if resolved is not None and resolved.id == user.id:
            return raw_token
    return None


def _dispatch_base_url() -> str:
    return settings.pipeline_dispatch_base_url.rstrip("/")


async def post_pipeline_trigger(
    *,
    channel_id: str,
    job: PipelineJobKind | str,
    force: bool = False,
    api_key: str | None,
    surface: Literal["mcp", "bot"],
) -> PipelineDispatchClientResult:
    """POST ``/api/v1/pipeline/trigger`` on the tg_parser API."""
    normalized = normalize_channel_id(channel_id) or channel_id
    job_value = PipelineJobKind(job).value

    if settings.mcp_auth_enabled and api_key is None and settings.api_key_required:
        return PipelineDispatchClientResult(
            channel_id=normalized,
            triggered=False,
            message="API key required to dispatch pipeline jobs to tg_parser.",
            error_class=DISPATCH_AUTH_REQUIRED,
            job=job_value,
        )

    url = f"{_dispatch_base_url()}/api/v1/pipeline/trigger"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Trigger-Surface": surface,
    }
    if api_key:
        headers["X-API-Key"] = api_key

    body = {"channel_id": normalized, "job": job_value, "force": force}

    try:
        async with httpx.AsyncClient(timeout=settings.pipeline_dispatch_timeout_seconds) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning(
            "pipeline_dispatch_http_failed",
            surface=surface,
            channel_id=normalized,
            job=job_value,
            error=str(exc),
        )
        return PipelineDispatchClientResult(
            channel_id=normalized,
            triggered=False,
            message=(
                f"Could not reach tg_parser API at {url}: {exc}. "
                f"Workaround: docker compose exec tg_parser "
                f"tg-parser ingest --source {normalized}"
            ),
            error_class=DISPATCH_HTTP_ERROR,
            job=job_value,
            workaround=(f"docker compose exec tg_parser tg-parser ingest --source {normalized}"),
        )

    if response.status_code == 401:
        return PipelineDispatchClientResult(
            channel_id=normalized,
            triggered=False,
            message="tg_parser API rejected dispatch: authentication required.",
            error_class=DISPATCH_AUTH_REQUIRED,
            job=job_value,
        )

    if response.status_code == 429:
        retry = response.headers.get("Retry-After", "60")
        return PipelineDispatchClientResult(
            channel_id=normalized,
            triggered=False,
            message=f"Rate limited by tg_parser API. Retry after {retry}s.",
            error_class="RateLimited",
            job=job_value,
        )

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        error_class = _extract_error_class(response) or DISPATCH_HTTP_ERROR
        return PipelineDispatchClientResult(
            channel_id=normalized,
            triggered=False,
            message=detail,
            error_class=error_class,
            job=job_value,
        )

    payload: dict[str, Any] = response.json()
    job_id = str(payload.get("job_id", ""))
    return PipelineDispatchClientResult(
        channel_id=normalized,
        triggered=True,
        message=(
            f"Pipeline job queued (job_id={job_id}, job={job_value}). "
            "Use get_pipeline_status to monitor progress."
        ),
        job_id=job_id or None,
        job=job_value,
    )


def _iso_or_none(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def post_export(
    *,
    channel_id: str,
    level: str,
    format: str,
    api_key: str | None,
    from_date: datetime | str | None = None,
    to_date: datetime | str | None = None,
) -> ExportDispatchClientResult:
    """POST ``/api/v1/export`` on the tg_parser API (same base URL as pipeline)."""
    normalized = normalize_channel_id(channel_id) or channel_id

    if settings.mcp_auth_enabled and api_key is None and settings.api_key_required:
        return ExportDispatchClientResult(
            job_id="",
            status="rejected",
            message="API key required to dispatch export jobs to tg_parser.",
            channel_id=normalized,
            level=level,
            format=format,
        )

    url = f"{_dispatch_base_url()}/api/v1/export"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    body: dict[str, Any] = {
        "channel_id": normalized,
        "level": level,
        "format": format,
    }
    from_iso = _iso_or_none(from_date)
    to_iso = _iso_or_none(to_date)
    if from_iso is not None:
        body["from_date"] = from_iso
    if to_iso is not None:
        body["to_date"] = to_iso

    try:
        async with httpx.AsyncClient(timeout=settings.pipeline_dispatch_timeout_seconds) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning(
            "export_dispatch_http_failed",
            channel_id=normalized,
            level=level,
            format=format,
            error=str(exc),
        )
        return ExportDispatchClientResult(
            job_id="",
            status="rejected",
            message=f"Could not reach tg_parser API at {url}: {exc}.",
            channel_id=normalized,
            level=level,
            format=format,
        )

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        return ExportDispatchClientResult(
            job_id="",
            status="rejected",
            message=detail,
            channel_id=normalized,
            level=level,
            format=format,
        )

    payload: dict[str, Any] = response.json()
    job_id = str(payload.get("job_id", "") or "")
    status = str(payload.get("status") or "pending")
    download_url = payload.get("download_url")
    return ExportDispatchClientResult(
        job_id=job_id,
        status=status,
        message=str(payload.get("message") or f"Export job queued (job_id={job_id})."),
        channel_id=normalized,
        level=str(payload.get("level") or level),
        format=str(payload.get("format") or format),
        download_url=str(download_url) if download_url else None,
    )


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("message") or body)
    return str(body)


def _extract_error_class(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict) and body.get("error_class"):
        return str(body["error_class"])
    return None


def dispatch_not_implemented_result(channel_id: str, *, job: str) -> PipelineDispatchClientResult:
    normalized = normalize_channel_id(channel_id) or channel_id
    ssh_workaround = f"docker compose exec tg_parser tg-parser ingest --source {normalized}"
    return PipelineDispatchClientResult(
        channel_id=normalized,
        triggered=False,
        message=(
            "Pipeline dispatch is not available in this process. "
            "Use POST /api/v1/pipeline/trigger on the tg_parser container "
            f"or run: {ssh_workaround}"
        ),
        error_class=DISPATCH_NOT_IMPLEMENTED,
        job=job,
        workaround=ssh_workaround,
    )
