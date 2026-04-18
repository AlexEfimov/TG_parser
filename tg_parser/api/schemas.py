"""
Pydantic schemas for HTTP API requests and responses.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# Re-export shared enums from the domain layer to keep the public API surface
# unchanged while avoiding a circular import between api.schemas and services.
from tg_parser.domain.export import ExportFormat, ExportLevel

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
    "JobStatusResponse",
    "ExportRequest",
    "ExportResponse",
    "ErrorResponse",
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
