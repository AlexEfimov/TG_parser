"""
Pydantic schemas for HTTP API requests and responses.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

# Re-export shared enums from the domain layer to keep the public API surface
# unchanged while avoiding a circular import between api.schemas and services.
from tg_parser.domain.export import ExportFormat, ExportLevel
from tg_parser.domain.models import TargetChannel, TargetChat

# ============================================================================
# Enums
# ============================================================================


class JobStatus(StrEnum):
    """Status of an async job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


__all__ = [
    "JobStatus",
    "ExportFormat",
    "ExportLevel",
    "HealthResponse",
    "StatusResponse",
    "ProcessRequest",
    "ProcessResponse",
    "PipelineTriggerRequest",
    "PipelineTriggerResponse",
    "JobStatusResponse",
    "ExportRequest",
    "ExportResponse",
    "ErrorResponse",
    "WatchlistCreateRequest",
    "WatchlistSubscribeResponse",
    "WatchlistResponse",
    "WatchlistListResponse",
    "WatchlistMatchItem",
    "WatchlistMatchesResponse",
    "DigestCreateRequest",
    "DigestSubscribeResponse",
    "DigestResponse",
    "DigestListResponse",
]


# ============================================================================
# Health
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok", description="Health status")
    version: str = Field(description="API version")
    timestamp: datetime = Field(description="Current server time")
    database: str | None = Field(default=None, description="Database connectivity status")


class StatusResponse(BaseModel):
    """Detailed status response."""

    status: str = Field(default="ok", description="Overall status")
    version: str = Field(description="API version")
    timestamp: datetime = Field(description="Current server time")
    components: dict[str, str] = Field(description="Component status map")
    stats: dict[str, int] = Field(default_factory=dict, description="Optional statistics")


# ============================================================================
# Process
# ============================================================================


class ProcessRequest(BaseModel):
    """Request to process messages from a channel."""

    channel_id: str = Field(description="Telegram channel identifier")
    force: bool = Field(default=False, description="Force reprocessing of existing messages")
    retry_failed: bool = Field(default=False, description="Only retry previously failed messages")
    provider: str | None = Field(
        default=None, description="LLM provider override (openai, anthropic, gemini, ollama)"
    )
    model: str | None = Field(default=None, description="Model override")
    concurrency: int = Field(default=1, ge=1, le=20, description="Number of parallel requests")

    # Webhook configuration (Phase 2F)
    webhook_url: str | None = Field(
        default=None,
        description="URL to call when job completes",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="HMAC secret for webhook signature verification",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "channel_id": "labdiagnostica",
                    "force": False,
                    "concurrency": 5,
                },
                {
                    "channel_id": "labdiagnostica",
                    "concurrency": 5,
                    "webhook_url": "https://myapp.com/webhook",
                    "webhook_secret": "my-secret-key",
                },
            ]
        }
    }


class ProcessResponse(BaseModel):
    """Response from process request (async job created)."""

    job_id: str = Field(description="Unique job identifier")
    status: JobStatus = Field(description="Current job status")
    channel_id: str = Field(description="Channel being processed")
    created_at: datetime = Field(description="Job creation time")
    message: str = Field(description="Status message")


PipelineJobName = Literal["full_pipeline", "topicization", "link_topics"]


class PipelineTriggerRequest(BaseModel):
    """POST /api/v1/pipeline/trigger request (ADR 0007)."""

    channel_id: str = Field(description="Channel identifier (RBAC + job scope)")
    job: PipelineJobName = Field(
        default="full_pipeline",
        description="Job kind: full_pipeline | topicization | link_topics",
    )
    force: bool = Field(default=False, description="Force re-run where applicable")


class PipelineTriggerResponse(BaseModel):
    """Async acceptance response for pipeline trigger."""

    job_id: str = Field(description="Opaque job identifier for polling/logging")
    created: bool = Field(description="True when a new job was queued")
    status: Literal["queued"] = Field(default="queued", description="Initial async status")
    channel_id: str = Field(description="Normalized channel id")
    job: PipelineJobName = Field(description="Job kind that was queued")


class JobStatusResponse(BaseModel):
    """Response for job status query."""

    job_id: str = Field(description="Unique job identifier")
    status: JobStatus = Field(description="Current job status")
    channel_id: str = Field(description="Channel being processed")
    created_at: datetime = Field(description="Job creation time")
    started_at: datetime | None = Field(default=None, description="Job start time")
    completed_at: datetime | None = Field(default=None, description="Job completion time")
    progress: dict[str, int] = Field(
        default_factory=dict, description="Progress info (processed, total, failed)"
    )
    error: str | None = Field(default=None, description="Error message if failed")
    result: dict[str, Any] | None = Field(default=None, description="Final result if completed")


# ============================================================================
# Export
# ============================================================================


class ExportRequest(BaseModel):
    """Request to export processed data."""

    channel_id: str | None = Field(
        default=None,
        description="Filter by channel (required when level='raw')",
    )
    level: ExportLevel = Field(
        default=ExportLevel.FULL,
        description=(
            "Export level: 'raw' = RawTelegramMessage[] (parse-only, no LLM), "
            "'processed' = KnowledgeBaseEntry[] only, "
            "'full' = processed + topics (legacy default)"
        ),
    )
    format: ExportFormat = Field(default=ExportFormat.NDJSON, description="Export format")
    include_topics: bool = Field(default=True, description="Include topicized data")
    from_date: datetime | None = Field(
        default=None,
        description="Filter messages from this UTC datetime (inclusive)",
    )
    to_date: datetime | None = Field(
        default=None,
        description="Filter messages up to this UTC datetime (inclusive)",
    )

    # Webhook configuration (Phase 2F)
    webhook_url: str | None = Field(
        default=None,
        description="URL to call when export completes",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="HMAC secret for webhook signature verification",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "channel_id": "labdiagnostica",
                    "format": "ndjson",
                    "include_topics": True,
                },
                {
                    "channel_id": "labdiagnostica",
                    "level": "raw",
                    "format": "json",
                },
                {
                    "format": "json",
                    "webhook_url": "https://myapp.com/export-webhook",
                },
            ]
        }
    }


class ExportResponse(BaseModel):
    """Response from export request."""

    job_id: str = Field(description="Export job identifier")
    status: JobStatus = Field(description="Current job status")
    format: ExportFormat = Field(description="Export format")
    level: ExportLevel = Field(
        default=ExportLevel.FULL,
        description="Export level that produced this job",
    )
    created_at: datetime = Field(description="Job creation time")
    download_url: str | None = Field(default=None, description="Download URL when ready")
    message: str = Field(description="Status message")


# ============================================================================
# Error
# ============================================================================


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(description="Error type")
    message: str = Field(description="Error message")
    details: dict[str, Any] | None = Field(default=None, description="Additional error details")


# ============================================================================
# Watchlist (P-1 Surface Parity MVP — Wave 1 step 3 commit 2/4)
# ============================================================================
#
# Schemas mirror the F11 ``WatchInterest`` / ``WatchMatch`` domain models
# (see :mod:`tg_parser.domain.models`) while keeping the public HTTP
# surface decoupled from the storage layer. They live in this flat
# ``schemas.py`` module per Q7 (sprint prompt §3) — no ``schemas/``
# package split. The Q-OPEN-3 contract requires the GET responses to
# emit ``workspace_id`` *plus* ``workspace_name`` (single JOIN at the
# router level), so :class:`WatchlistResponse` carries both.


class WatchlistCreateRequest(BaseModel):
    """POST /api/v1/watchlists request body.

    Mirrors :class:`tg_parser.domain.models.WatchInterest` with the
    request-side defaults locked by Wave 1 step 3 §3 Q-locks:

    * ``title`` — natural key for the (user_id, title) idempotent upsert
      (BUG-022); min_length matches the domain validator so a blank
      payload surfaces as a 422 at the HTTP boundary.
    * ``channel_ids`` — non-empty (min_length=1) to mirror the domain
      ``_channel_ids_nonempty`` validator; an empty list returns 422
      rather than a 500 from the service layer.
    * ``chat_id`` — Q6 lock: int only (polymorphic targets deferred).
    * ``workspace_id`` — ENH-9: optional FK to a workspace owned by the
      caller (admin: any workspace). Unknown / foreign → 404-like
      ``WorkspaceNotFound`` at the service layer.
    """

    title: str = Field(min_length=1, max_length=300, description="Short human label")
    channel_ids: list[str] = Field(
        min_length=1,
        description="Channels to watch (non-empty, mirrors domain constraint)",
    )
    chat_id: int | None = Field(
        default=None,
        description="Legacy delivery chat_id (mutually exclusive with ``target``)",
    )
    target: TargetChat | TargetChannel | None = Field(
        default=None,
        description="Polymorphic delivery target (ADR 0008)",
    )
    keywords: list[str] = Field(default_factory=list, description="Positive keywords")
    description: str | None = Field(default=None, description="Free-form description")
    exclude_keywords: list[str] = Field(
        default_factory=list, description="Negative filter — any match zeroes the score"
    )
    threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Combined-score cutoff (default 0.6)",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Optional workspace context FK (ENH-9)",
    )

    @model_validator(mode="after")
    def _validate_target_exclusive(self) -> Self:
        if self.chat_id is not None and self.target is not None:
            raise ValueError("provide one of chat_id (legacy) or target (new)")
        if self.chat_id is None and self.target is None:
            raise ValueError("either chat_id or target is required")
        return self


class WatchlistSubscribeResponse(BaseModel):
    """POST response per Q-OPEN-1 / Q7 (sprint prompt §3).

    Same-args replay → ``created=False, changed_fields=[]``.
    Same key with different args → ``created=False`` and
    ``changed_fields`` lists the Pydantic field names that the
    service layer rewrote on the existing row (subset of
    ``WatchInterest`` fields like ``keywords``, ``threshold``,
    ``workspace_id`` …).
    """

    watchlist_id: str = Field(description="Server-assigned interest UUID")
    created: bool = Field(description="True on first INSERT; False on idempotent replay/update")
    changed_fields: list[str] = Field(
        default_factory=list,
        description="Pydantic field names rewritten on upsert; empty on no-op replay",
    )
    target: dict[str, Any] = Field(description="Resolved delivery target (ADR 0008)")


class WatchlistResponse(BaseModel):
    """GET single response — full ``WatchInterest`` shape minus ``embedding``.

    Per Q-OPEN-3 emits both ``workspace_id`` and ``workspace_name``
    (the latter from a single ``workspaces.name`` JOIN at the router
    layer). ``workspace_name`` is ``null`` when ``workspace_id`` is
    NULL (pre-ENH-9 rows + un-scoped interests).

    The 1536-dim ``embedding`` is intentionally elided from the HTTP
    surface — it bloats the payload, is opaque to clients, and the
    service layer manages it lazily.
    """

    id: str
    user_id: str
    target: dict[str, Any] = Field(description="Resolved delivery target (ADR 0008)")
    chat_id: int | None = None
    channel_id: str | None = None
    title: str
    workspace_id: str | None = None
    workspace_name: str | None = None
    description: str | None = None
    keywords: list[str]
    exclude_keywords: list[str]
    channel_ids: list[str]
    threshold: float
    notify_mode: str = Field(description="``instant`` | ``batch`` | ``silent``")
    is_active: bool
    last_checked_at: datetime | None = None
    last_match_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WatchlistListResponse(BaseModel):
    """GET list response (Q7 — ``{items, total}`` envelope)."""

    items: list[WatchlistResponse]
    total: int = Field(ge=0, description="Total interests for the caller (pre-pagination)")


class WatchlistMatchItem(BaseModel):
    """Single ``WatchMatch`` row projection for the matches endpoint.

    Mirrors the domain ``WatchMatch`` model. ``match_id`` is the
    underlying ``BIGSERIAL`` surfaced as a string so the JSON contract
    stays language-agnostic; downstream typed clients deserialise it
    back to an integer if they want one.
    """

    match_id: int = Field(description="BIGSERIAL row id from ``watch_matches``")
    interest_id: str
    source_ref: str
    channel_id: str
    keyword_score: float = Field(ge=0.0, le=1.0)
    semantic_score: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)
    notified: bool
    created_at: datetime


class WatchlistMatchesResponse(BaseModel):
    """GET matches response (Q-OPEN-4 — ``?since=`` + offset/limit pagination)."""

    items: list[WatchlistMatchItem]
    total: int = Field(ge=0, description="Total matches for the interest (after ``since`` filter)")


# ============================================================================
# Digest (P-2 Surface Parity MVP — Wave 1 step 3 commit 3/4)
# ============================================================================
#
# Schemas mirror the F6 ``DigestSubscription`` domain model (see
# :mod:`tg_parser.domain.models`). Asymmetries vs the watchlist surface
# (sprint prompt §3 Q6 + Q8):
#
# * **Label field is ``name``**, not ``title`` — domain pin.
# * **DELETE semantics is HARD DELETE** — the second DELETE on the same
#   id returns 404 (REST-strict per parent Q-OPEN-8 lock). The HTTP
#   surface inherits this asymmetry from :meth:`DigestSubscriptionRepo.delete`
#   which physically removes the row (no ``is_active`` flip).
#
# Q-OPEN-3 contract is identical to P-1: GET responses emit
# ``workspace_id`` *plus* ``workspace_name`` (single JOIN at the router
# level). ``language`` is intentionally exposed nullable on the request
# (``str | None``) so the service-layer default (``"ru"``) flows through
# untouched when the caller omits it; the response always carries the
# stored value (never NULL — the column has a NOT NULL default).


class DigestCreateRequest(BaseModel):
    """POST /api/v1/digests request body.

    Mirrors :class:`tg_parser.domain.models.DigestSubscription` with the
    request-side defaults locked by Wave 1 step 3 §3 Q-locks:

    * ``name`` — natural key for the (owner_id, name) idempotent upsert
      (BUG-022); min_length matches the domain validator so a blank
      payload surfaces as a 422 at the HTTP boundary.
    * ``channel_ids`` — non-empty (min_length=1) to mirror the domain
      ``_channel_ids_nonempty`` validator; an empty list returns 422
      rather than a 500 from the service layer.
    * ``chat_id`` — Q6 lock: int only (polymorphic targets deferred).
    * ``format`` — Literal narrows the input to the three
      :class:`DigestFormat` values so an unknown enum surfaces as 422
      before reaching the service layer.
    * ``language`` — nullable: ``None`` lets the service fall back to
      its own default (``"ru"``) instead of forcing the client to
      hardcode a locale.
    * ``cron_expression`` / ``timezone`` — pre-validated at the router
      layer (mirror of the MCP tool path) so an invalid spec returns
      422 *before* the upsert runs and never leaves a half-written row
      behind.
    * ``workspace_id`` — ENH-9: optional FK to a workspace owned by the
      caller (admin: any workspace). Unknown / foreign → 404-like
      ``WorkspaceNotFound`` at the service layer.
    """

    name: str = Field(min_length=1, max_length=200, description="Human label (natural key)")
    channel_ids: list[str] = Field(
        min_length=1,
        description="Channels to digest (non-empty, mirrors domain constraint)",
    )
    chat_id: int | None = Field(
        default=None,
        description="Legacy delivery chat_id (mutually exclusive with ``target``)",
    )
    target: TargetChat | TargetChannel | None = Field(
        default=None,
        description="Polymorphic delivery target (ADR 0008)",
    )
    cron_expression: str = Field(
        default="0 9 * * *",
        max_length=100,
        description="Standard 5-field cron expression evaluated in ``timezone``",
    )
    timezone: str = Field(
        default="UTC",
        max_length=50,
        description="IANA timezone name (e.g. ``Europe/Moscow``)",
    )
    format: Literal["summary", "bullets", "detailed"] = Field(
        default="summary",
        description="Output style",
    )
    language: str | None = Field(
        default=None,
        max_length=10,
        description="Output language code; ``None`` defers to the service default",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Optional workspace context FK (ENH-9)",
    )

    @model_validator(mode="after")
    def _validate_target_exclusive(self) -> Self:
        if self.chat_id is not None and self.target is not None:
            raise ValueError("provide one of chat_id (legacy) or target (new)")
        if self.chat_id is None and self.target is None:
            raise ValueError("either chat_id or target is required")
        return self


class DigestSubscribeResponse(BaseModel):
    """POST response per Q-OPEN-1 / Q7 (sprint prompt §3).

    Note the label is ``digest_id`` (Q6 asymmetry vs the watchlist
    surface's ``watchlist_id``). Same-args replay →
    ``created=False, changed_fields=[]``; same key + different args →
    ``created=False`` with ``changed_fields`` listing the
    :class:`DigestSubscription` field names rewritten on the existing
    row.
    """

    digest_id: str = Field(description="Server-assigned subscription UUID")
    created: bool = Field(description="True on first INSERT; False on idempotent replay/update")
    changed_fields: list[str] = Field(
        default_factory=list,
        description="DigestSubscription field names rewritten on upsert; empty on no-op replay",
    )
    target: dict[str, Any] = Field(description="Resolved delivery target (ADR 0008)")


class DigestResponse(BaseModel):
    """GET single response — full ``DigestSubscription`` shape + ``workspace_name``.

    Per Q-OPEN-3 emits both ``workspace_id`` and ``workspace_name``
    (the latter from a single ``workspaces.name`` JOIN at the router
    layer). ``workspace_name`` is ``null`` when ``workspace_id`` is
    NULL (pre-ENH-9 rows + un-scoped subscriptions).
    """

    id: str
    owner_id: str
    target: dict[str, Any] = Field(description="Resolved delivery target (ADR 0008)")
    chat_id: int | None = None
    channel_id: str | None = None
    name: str
    workspace_id: str | None = None
    workspace_name: str | None = None
    channel_ids: list[str]
    cron_expression: str
    timezone: str
    format: str = Field(description="``summary`` | ``bullets`` | ``detailed``")
    language: str
    is_active: bool
    last_sent_at: datetime | None = None
    last_digest_cursor: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DigestListResponse(BaseModel):
    """GET list response (Q7 — ``{items, total}`` envelope)."""

    items: list[DigestResponse]
    total: int = Field(ge=0, description="Total subscriptions for the caller (pre-pagination)")
