"""Project an internal ``SearchResult`` onto the three read surfaces.

BUG-102 / F-04: retrieval already distinguishes ``entry_type="topic"``
(data on ``topic_card``) from a document hit (data on ``document``). The
six serializers used to read only ``document``, so a topic hit left the
wire as a row of nulls. One helper outside ``api.routes`` (ADR-0004:
HTTP and bot must not import ``mcp_server``) returns a dict; each
surface wraps it in its own model.

``preview_limit`` is 300 on MCP / bot search, 200 on HTTP, and ``None``
on bot ask (that executor never had ``text_preview`` — omit the key).
"""

from __future__ import annotations

from typing import Any

from tg_parser.services.retrieval_service import SearchResult


def project_search_result(
    result: SearchResult,
    *,
    preview_limit: int | None,
) -> dict[str, Any]:
    """Return a surface-agnostic dict for one search / ask source hit.

    Does not return an MCP or HTTP ``SearchResultItem``. Callers construct
    their own models (or pass the dict through as-is on the bot).
    """
    payload: dict[str, Any] = {
        "source_ref": result.source_ref,
        "score": round(result.score, 4),
    }
    card = result.topic_card
    if result.entry_type == "topic" and card is not None:
        payload["entry_type"] = "topic"
        payload["title"] = card.title
        payload["summary"] = card.summary
        payload["channel_id"] = card.sources[0]
        if preview_limit is not None:
            payload["text_preview"] = card.summary[:preview_limit]
        return payload

    doc = result.document
    payload["entry_type"] = "message"
    payload["title"] = None
    payload["summary"] = doc.summary if doc else None
    payload["channel_id"] = doc.channel_id if doc else None
    if preview_limit is not None:
        payload["text_preview"] = doc.text_clean[:preview_limit] if doc else None
    return payload
