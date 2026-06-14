"""Shared ``pagination_pending`` contract (TD-D-02 / #40).

Single source of truth for the ``pagination_pending`` FSM-hint shape so the
bot read-tools (:mod:`tg_parser.bot.tools`) and the MCP read-tools
(:mod:`tg_parser.mcp_server`) stay byte-identical across surfaces. The bot
drives an "ещё" replay FSM off this hint; MCP clients re-call with the
advanced ``offset``. Both want the SAME locked shape
``{tool_name, args, total, offset, limit}`` so a single paginated read-tool
behaves consistently whether reached over the bot or over MCP.

DRY note: the bot centralised this in ``tg_parser/bot/tools.py`` first; this
module hoists the canonical implementation up so MCP can reuse it instead of
duplicating (and drifting from) the contract.
"""

from __future__ import annotations

from typing import Any


def build_pagination_pending(
    tool_name: str,
    args: dict[str, Any],
    *,
    total: int,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Build the canonical ``pagination_pending`` hint (TD-D-02 / #40).

    ``args`` is the ORIGINAL tool args; every filter field is preserved
    verbatim and only ``offset`` is advanced to the next page (``limit``
    carried forward). The locked shape is
    ``{tool_name, args, total, offset, limit}``.
    """
    next_args: dict[str, Any] = {k: v for k, v in args.items() if k not in {"offset", "limit"}}
    next_args["offset"] = offset + limit
    next_args["limit"] = limit
    return {
        "tool_name": tool_name,
        "args": next_args,
        "total": total,
        "offset": offset + limit,
        "limit": limit,
    }


def paginate_items[T](
    items: list[T],
    *,
    offset: int,
    limit: int | None,
) -> tuple[list[T], int, bool]:
    """Slice ``items`` into a single page.

    Returns ``(page, total, has_more)``. ``limit=None`` disables paging — the
    full list is returned, ``has_more`` is ``False`` (used by MCP tools that
    were historically un-paginated so an offset/limit-less call stays
    bit-for-bit backward compatible). A non-negative ``offset`` past the end
    yields an empty page.
    """
    total = len(items)
    if limit is None:
        return list(items), total, False
    safe_offset = max(offset, 0)
    page = items[safe_offset : safe_offset + limit]
    has_more = safe_offset + limit < total
    return page, total, has_more
