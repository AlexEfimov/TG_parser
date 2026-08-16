"""BUG-103 / R5 — four independent bot/MCP surface defects in one batch.

F-06: ``_MCP_INSTRUCTIONS`` must describe unknown/foreign ``workspace_id``
as an empty / 404-like *result*, not a raised error.
F-09: MCP resources must iterate the envelope ``.items`` (or dump a card),
not a Pydantic model.
F-08: negative / zero ``limit`` must not slice from the end or emit a
``pagination_pending`` that the bot-FSM «ещё» replays.
F-11: watchlist confirmation HTML-escapes the user-controlled title.

Each finding has its own tests so a revert of one fix fails only that
finding (the other three stay green).
"""

from __future__ import annotations

import json
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from test_watchlist_service import (  # type: ignore[import-not-found]
    _FakeBot,
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
)

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import (
    TOOL_DECLARATIONS,
    _exec_list_topics,
    _exec_subscribe_watchlist,
    _paginate_read_result,
)
from tg_parser.mcp_server import (
    _MCP_INSTRUCTIONS,
    ChannelListResult,
    ChannelSummary,
    TopicDetail,
    TopicListResult,
    TopicSummary,
    get_topic_versions,
    list_channels,
    list_topics,
    resource_channel_topics,
    resource_channels,
    resource_topic,
)
from tg_parser.services.watchlist_service import WatchlistService
from tg_parser.utils.pagination import paginate_items


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"id": f"r{i}", "title": f"T{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# F-06 — server instructions match the empty / 404-like result
# ---------------------------------------------------------------------------


def test_mcp_instructions_unknown_workspace_is_empty_or_404_like() -> None:
    assert "raises a 404-like error" not in _MCP_INSTRUCTIONS
    lowered = _MCP_INSTRUCTIONS.lower()
    assert "empty" in lowered
    assert "404-like" in lowered


# ---------------------------------------------------------------------------
# F-09 — three resource smokes (topics is the live defect; the other two
# guard the next return-type drift)
# ---------------------------------------------------------------------------


async def test_resource_channels_json_list_has_channel_id() -> None:
    envelope = ChannelListResult(
        items=[
            ChannelSummary(
                channel_id="chA",
                status="active",
                raw_messages=1,
                processed_documents=1,
                topics_count=0,
                coverage_percent=0.0,
            )
        ],
        total=1,
        offset=0,
        limit=None,
        has_more=False,
        degraded=False,
    )
    with patch("tg_parser.mcp_server.list_channels", AsyncMock(return_value=envelope)):
        payload = await resource_channels()
    rows = json.loads(payload)
    assert isinstance(rows, list)
    assert rows[0]["channel_id"] == "chA"


async def test_resource_channel_topics_iterates_items() -> None:
    envelope = TopicListResult(
        total=1,
        offset=0,
        limit=50,
        has_more=False,
        items=[
            TopicSummary(
                id="topic:ch:1",
                title="T1",
                type="singleton",
                summary="S",
                items_count=0,
                sources=["ch"],
            )
        ],
    )
    with patch("tg_parser.mcp_server.list_topics", AsyncMock(return_value=envelope)):
        payload = await resource_channel_topics("ch")
    rows = json.loads(payload)
    assert isinstance(rows, list)
    assert rows[0]["id"] == "topic:ch:1"
    assert rows[0]["title"] == "T1"


async def test_resource_topic_dumps_card_or_error() -> None:
    card = TopicDetail(
        id="topic:ch:1",
        title="T1",
        type="singleton",
        summary="S",
        scope_in=["in"],
        scope_out=["out"],
        anchors=[],
        sources=["ch"],
    )
    with patch("tg_parser.mcp_server.get_topic_details", AsyncMock(return_value=card)):
        payload = await resource_topic("topic:ch:1")
    data = json.loads(payload)
    assert data["id"] == "topic:ch:1"
    assert data["title"] == "T1"

    with patch(
        "tg_parser.mcp_server.get_topic_details",
        AsyncMock(return_value="Topic not found: missing"),
    ):
        err_payload = await resource_topic("missing")
    err = json.loads(err_payload)
    assert "error" in err


# ---------------------------------------------------------------------------
# F-08 — lower-bound clamp; no upper page cap
# ---------------------------------------------------------------------------


def test_paginate_items_negative_limit_is_one_not_from_end() -> None:
    items = list(range(50))
    page, total, has_more = paginate_items(items, offset=0, limit=-5)
    assert total == 50
    assert page == [0]
    assert has_more is True


def test_paginate_items_negative_offset_matches_zero() -> None:
    items = list(range(50))
    page_neg, _, _ = paginate_items(items, offset=-10, limit=5)
    page_zero, _, _ = paginate_items(items, offset=0, limit=5)
    assert page_neg == page_zero == [0, 1, 2, 3, 4]


def test_paginate_items_limit_none_unchanged() -> None:
    items = list(range(7))
    page, total, has_more = paginate_items(items, offset=0, limit=None)
    assert page == items
    assert total == 7
    assert has_more is False


def test_paginate_items_large_limit_not_capped() -> None:
    items = list(range(50))
    page, total, has_more = paginate_items(items, offset=0, limit=500)
    assert page == items
    assert total == 50
    assert has_more is False


def test_paginate_read_result_negative_limit_clamped() -> None:
    result = _paginate_read_result("list_watchlists", {"limit": -5}, _rows(50))
    assert result["limit"] >= 1
    assert len(result["items"]) == result["limit"]
    assert result["has_more"] is True
    assert result["pagination_pending"]["args"]["offset"] >= 0
    assert result["pagination_pending"]["limit"] >= 1


def test_paginate_read_result_zero_limit_uses_default() -> None:
    result = _paginate_read_result("list_watchlists", {"limit": 0}, _rows(50))
    assert result["limit"] == 20
    assert len(result["items"]) == 20
    assert result["has_more"] is True


def _topic_cards(n: int) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=f"topic:ch:{i}",
            title=f"Topic {i}",
            summary=f"S{i}",
            type=SimpleNamespace(value="singleton"),
            sources=["ch"],
        )
        for i in range(n)
    ]


@asynccontextmanager
async def _processing_repos(cards: list[SimpleNamespace]):
    proc = AsyncMock()
    tc = AsyncMock()
    tb = AsyncMock()
    tc.list_all.return_value = cards
    tc.list_by_channel.return_value = cards
    tc.list_by_channels.return_value = cards
    tb.list_all.return_value = []
    tb.list_by_channel.return_value = []
    yield (proc, tc, tb, MagicMock())


def _patch_list_topics_repos(cards: list[SimpleNamespace]) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_admin()))
    )
    stack.enter_context(
        patch(
            "tg_parser.services.db_context.processing_repos",
            lambda: _processing_repos(cards),
        )
    )
    return stack


async def test_mcp_list_topics_negative_limit_is_one_not_from_end() -> None:
    cards = _topic_cards(50)
    with _patch_list_topics_repos(cards):
        result = await list_topics(limit=-5)
    assert isinstance(result, TopicListResult)
    assert result.total == 50
    assert len(result.items) == 1
    assert result.limit == 1
    assert result.offset == 0
    assert result.has_more is True


async def test_mcp_list_topics_zero_limit_is_one() -> None:
    cards = _topic_cards(50)
    with _patch_list_topics_repos(cards):
        result = await list_topics(limit=0)
    assert len(result.items) == 1
    assert result.limit == 1
    assert result.has_more is True


async def test_bot_list_topics_negative_limit_is_one_not_from_end() -> None:
    cards = _topic_cards(50)
    with patch(
        "tg_parser.services.db_context.processing_repos",
        lambda: _processing_repos(cards),
    ):
        result = await _exec_list_topics({"limit": -5}, current_user=_admin())
    assert result["total"] == 50
    assert len(result["items"]) == 1
    assert result["limit"] == 1
    assert result["offset"] == 0
    assert result["has_more"] is True
    assert result["pagination_pending"]["args"]["offset"] >= 0


async def test_bot_list_topics_zero_limit_is_one() -> None:
    cards = _topic_cards(50)
    with patch(
        "tg_parser.services.db_context.processing_repos",
        lambda: _processing_repos(cards),
    ):
        result = await _exec_list_topics({"limit": 0}, current_user=_admin())
    assert len(result["items"]) == 1
    assert result["limit"] == 1
    assert result["has_more"] is True


async def test_list_channels_unknown_workspace_echoes_clamped_bounds() -> None:
    from tg_parser.auth.ownership import WorkspaceNotFound

    with (
        patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_admin())),
        patch(
            "tg_parser.mcp_server._resolve_workspace_scope",
            AsyncMock(side_effect=WorkspaceNotFound()),
        ),
    ):
        result = await list_channels(
            workspace_id="00000000-0000-0000-0000-000000000999",
            offset=-10,
            limit=-5,
        )
    assert result.items == []
    assert result.total == 0
    assert result.offset == 0
    assert result.limit == 1
    assert result.has_more is False


async def test_get_topic_versions_limit_zero_still_errors() -> None:
    result = await get_topic_versions(topic_id="topic:tg:c1:post:1", limit=0)
    assert "error" in result
    assert "1" in result["error"] and "200" in result["error"]


def test_tool_declaration_integers_have_bounds() -> None:
    missing: list[str] = []
    for tool in TOOL_DECLARATIONS:
        props = tool.get("parameters", {}).get("properties", {})
        for name, schema in props.items():
            if schema.get("type") != "INTEGER":
                continue
            label = f"{tool['name']}.{name}"
            if "minimum" not in schema or "maximum" not in schema:
                missing.append(label)
    assert missing == [], f"INTEGER params missing minimum/maximum: {missing}"


# ---------------------------------------------------------------------------
# F-11 — watchlist confirmation escapes < and &
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _fake_watchlist_repos(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


async def test_watchlist_confirmation_escapes_title_html() -> None:
    ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
    svc = WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )
    bot = _FakeBot()

    def _make(**_kwargs):
        return svc

    with (
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _fake_watchlist_repos(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            _make,
        ),
    ):
        result = await _exec_subscribe_watchlist(
            {
                "title": "A < B & C",
                "channel_ids": ["@crypto_news"],
                "keywords": ["mica"],
                "threshold": 0.5,
                "confirm": True,
            },
            current_user=_admin(),
            bot=bot,
            chat_id=987,
        )

    assert "error" not in result
    assert len(bot.sent) == 1
    assert "<b>A &lt; B &amp; C</b>" in bot.sent[0]["text"]
    assert bot.sent[0]["parse_mode"] == "HTML"
