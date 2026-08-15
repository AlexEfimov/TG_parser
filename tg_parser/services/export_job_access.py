"""Export-job visibility and level recovery shared by API and MCP.

BUG-096 / ADR-0004: these helpers used to live on ``api.routes.export``.
MCP ``get_export_status`` must not import that route module.
"""

from __future__ import annotations

from tg_parser.auth.models import CurrentUser
from tg_parser.domain.export import ExportLevel
from tg_parser.storage.ports import Job


def export_job_visible_to(user: CurrentUser, job: Job) -> bool:
    """BUG-101: isolate export jobs by ``Job.client``, not UUID secrecy.

    Both writers (HTTP ``start_export``, MCP ``export_channel``) already
    persist ``client=user.name``. Admin (``is_admin`` / ``allowed_channel_ids
    is None``) passes. A missing ``client`` on a legacy row is treated as
    not owned by a non-admin — same as unknown, not as «everyone».
    Disposition: compare ``job.client == user.name`` rather than add
    ``owner_user_id``; no migration, data is already there. Rename risk
    is accepted (``update_user`` on name is admin-only and rare).
    """
    if user.is_admin or user.allowed_channel_ids is None:
        return True
    return bool(job.client) and job.client == user.name


def resolve_job_level(job: Job) -> ExportLevel:
    """Recover ``ExportLevel`` stored on the job.

    We stash ``body.level.value`` into ``job.progress['level']`` at
    creation time (and copy into ``result`` on completion). For pre-F2
    jobs that never saw ``level`` (no such key) we default to
    ``ExportLevel.FULL`` — the legacy behaviour.
    """
    candidate: str | None = None
    if job.result and isinstance(job.result, dict):
        candidate = job.result.get("level") or candidate
    if not candidate and job.progress and isinstance(job.progress, dict):
        candidate = job.progress.get("level")
    if not candidate:
        return ExportLevel.FULL
    try:
        return ExportLevel(candidate)
    except ValueError:
        return ExportLevel.FULL
