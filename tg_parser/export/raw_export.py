"""Raw Telegram message export (F2: Parse-Only).

Pure writer module — takes ``list[RawTelegramMessage]`` + channel metadata,
writes JSON envelope or NDJSON stream. No I/O to DB.

Privacy invariant: ``raw_payload`` is ALWAYS excluded from the output
(private Telethon structs, file_refs, auth artefacts).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from tg_parser.domain.json_utils import stable_json_dumps
from tg_parser.domain.models import MessageType, RawTelegramMessage

SCHEMA_VERSION: Final[str] = "raw_channel_export.v1"


def export_raw_channel_json(
    *,
    messages: list[RawTelegramMessage],
    channel_id: str,
    channel_username: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
    output_path: Path,
    pretty: bool = False,
) -> dict[str, int]:
    """Write grouped JSON envelope to ``output_path``. Returns stats dict."""
    posts_sorted, grouped, orphan_comments = _group_messages(messages)

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "channel_id": channel_id,
        "channel_username": channel_username,
        "exported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filters": {
            "from_date": _iso_or_none(from_date),
            "to_date": _iso_or_none(to_date),
        },
        "messages_count": len(posts_sorted),
        "comments_count": sum(len(g) for g in grouped.values()),
        "orphan_comments_count": len(orphan_comments),
        "messages": [
            _post_with_comments(post, grouped.get(post.id, [])) for post in posts_sorted
        ],
        "orphan_comments": [_message_payload(c) for c in orphan_comments],
    }

    payload = stable_json_dumps(envelope, pretty=pretty)
    output_path.write_text(payload, encoding="utf-8")

    return {
        "posts": len(posts_sorted),
        "comments": envelope["comments_count"],
        "orphan_comments": len(orphan_comments),
    }


def export_raw_channel_ndjson(
    *,
    messages: list[RawTelegramMessage],
    output_path: Path,
) -> dict[str, int]:
    """Write one message per line (no grouping, stream-friendly).

    Order: posts first (by date), then comments (by date). Caller is responsible
    for providing pre-filtered messages.
    """
    posts = sorted(
        [m for m in messages if m.message_type == MessageType.POST],
        key=lambda m: m.date,
    )
    comments = sorted(
        [m for m in messages if m.message_type == MessageType.COMMENT],
        key=lambda m: m.date,
    )

    with output_path.open("w", encoding="utf-8") as f:
        for msg in [*posts, *comments]:
            f.write(stable_json_dumps(_message_payload(msg)))
            f.write("\n")

    return {"posts": len(posts), "comments": len(comments), "orphan_comments": 0}


def _group_messages(
    messages: list[RawTelegramMessage],
) -> tuple[
    list[RawTelegramMessage],
    dict[str, list[RawTelegramMessage]],
    list[RawTelegramMessage],
]:
    """Split into (posts_sorted, {post_id: comments_sorted}, orphan_comments_sorted).

    A comment is considered "orphan" when its ``parent_message_id`` does not
    refer to a post present in the filtered ``messages`` list (e.g. because
    the parent post falls outside the ``from_date`` / ``to_date`` range).
    """
    posts = sorted(
        [m for m in messages if m.message_type == MessageType.POST],
        key=lambda m: m.date,
    )
    post_ids = {p.id for p in posts}

    comments_sorted = sorted(
        [m for m in messages if m.message_type == MessageType.COMMENT],
        key=lambda m: m.date,
    )

    grouped: dict[str, list[RawTelegramMessage]] = {}
    orphans: list[RawTelegramMessage] = []
    for comment in comments_sorted:
        parent = comment.parent_message_id
        if parent and parent in post_ids:
            grouped.setdefault(parent, []).append(comment)
        else:
            orphans.append(comment)

    return posts, grouped, orphans


def _post_with_comments(
    post: RawTelegramMessage,
    comments: list[RawTelegramMessage],
) -> dict[str, Any]:
    payload = _message_payload(post)
    payload["comments"] = [_message_payload(c) for c in comments]
    return payload


def _message_payload(msg: RawTelegramMessage) -> dict[str, Any]:
    """Serialize a message without ``raw_payload`` (privacy + size invariant)."""
    return msg.model_dump(mode="json", exclude={"raw_payload"})


def _iso_or_none(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.isoformat()
