"""Build a `Source` for `add_channel` without wiping ingestion state (BUG-094).

`upsert_source` is a full-row UPSERT. Callers that only know the settings
the user passed must start from the loaded row and overlay those fields;
otherwise `last_post_id` and the rest become NULL and the next tick
re-fetches the channel from Telegram.

Create (`existing is None`) still applies the tool defaults
(`include_comments=False`, `batch_size=100`). `None` on a settings field
means "not passed", not the tool default.
"""

from __future__ import annotations

from tg_parser.storage.ports import Source

CREATE_DEFAULT_INCLUDE_COMMENTS = False
CREATE_DEFAULT_BATCH_SIZE = 100


def source_for_add_channel(
    existing: Source | None,
    *,
    source_id: str,
    channel_id: str,
    owner_id: str,
    channel_username: str | None = None,
    include_comments: bool | None = None,
    batch_size: int | None = None,
) -> Source:
    """Return a `Source` ready for `upsert_source`.

    On update, identity (`source_id`, `channel_id`, `owner_id`, `created_at`)
    and ingestion cursors come from `existing`. `status` is forced to
    ``active`` (re-add reactivates). `deleted_at` is left on the object;
    the SQL upsert is what sets it to NULL (BUG-002 M3).
    """
    if existing is None:
        return Source(
            source_id=source_id,
            channel_id=channel_id,
            channel_username=channel_username,
            status="active",
            include_comments=(
                CREATE_DEFAULT_INCLUDE_COMMENTS
                if include_comments is None
                else include_comments
            ),
            batch_size=CREATE_DEFAULT_BATCH_SIZE if batch_size is None else batch_size,
            owner_id=owner_id,
        )

    return Source(
        source_id=existing.source_id,
        channel_id=existing.channel_id,
        channel_username=(
            existing.channel_username if channel_username is None else channel_username
        ),
        status="active",
        include_comments=(
            existing.include_comments if include_comments is None else include_comments
        ),
        history_from=existing.history_from,
        history_to=existing.history_to,
        poll_interval_seconds=existing.poll_interval_seconds,
        batch_size=existing.batch_size if batch_size is None else batch_size,
        last_post_id=existing.last_post_id,
        backfill_completed_at=existing.backfill_completed_at,
        last_attempt_at=existing.last_attempt_at,
        last_success_at=existing.last_success_at,
        fail_count=existing.fail_count,
        last_error=existing.last_error,
        rate_limit_until=existing.rate_limit_until,
        comments_unavailable=existing.comments_unavailable,
        created_at=existing.created_at,
        owner_id=existing.owner_id,
        deleted_at=existing.deleted_at,
    )


def preview_add_channel_settings(
    existing: Source | None,
    *,
    channel_username: str | None,
    include_comments: bool | None,
    batch_size: int | None,
) -> dict[str, object]:
    """Settings the bot preview should show: current row plus overlay."""
    if existing is None:
        return {
            "channel_username": channel_username,
            "include_comments": (
                CREATE_DEFAULT_INCLUDE_COMMENTS
                if include_comments is None
                else include_comments
            ),
            "batch_size": CREATE_DEFAULT_BATCH_SIZE if batch_size is None else batch_size,
        }
    return {
        "channel_username": (
            existing.channel_username if channel_username is None else channel_username
        ),
        "include_comments": (
            existing.include_comments if include_comments is None else include_comments
        ),
        "batch_size": existing.batch_size if batch_size is None else batch_size,
    }
