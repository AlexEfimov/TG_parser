"""Contract tests for the Wave 2 Bot-UX hygiene track (TD-D-01/02/03).

Covers three coupled tracks that share the bot list-render path:

* **TD-D-02 (#40)** — ``pagination_pending`` coverage. The shared helpers
  ``_build_pagination_pending`` / ``_paginate_read_result`` produce the locked
  ``{tool_name, args, total, offset, limit}`` hint shape, and EVERY paginated
  read-tool in ``_PAGINATED_READ_TOOLS`` actually emits it when ``has_more``
  (the enumeration guard catches a new paginated tool shipped without the
  contract — the latent BUG-004 re-entry class).
* **TD-D-01 (#39)** — renderer unification. ``_format_paginated_list`` is the
  SINGLE rich deterministic template used for page 1 and page 2+; the template
  is byte-identical across pages (no visual jump) and carries a per-tool header.
* **TD-D-03 (#41)** — ``_format_tool_result`` synthesizes an informative
  fallback from the result identifiers, and NO write-tool can produce an empty
  user-facing message.
"""

from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.bot.handlers import (
    _PAGINATED_LIST_HEADERS,
    _format_paginated_list,
    _format_tool_result,
)
from tg_parser.bot.tools import (
    _PAGINATED_READ_TOOLS,
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    _build_pagination_pending,
    _exec_list_channels,
    _exec_list_digests,
    _exec_list_topics,
    _exec_list_users,
    _exec_list_watchlists,
    _paginate_read_result,
)

# ---------------------------------------------------------------------------
# TD-D-02: shared helper unit contract
# ---------------------------------------------------------------------------


class TestBuildPaginationPending:
    def test_shape_is_locked(self) -> None:
        pp = _build_pagination_pending(
            "list_topics",
            {"channel_id": "genotek", "offset": 0, "limit": 10},
            total=25,
            offset=0,
            limit=10,
        )
        assert set(pp.keys()) == {"tool_name", "args", "total", "offset", "limit"}
        assert pp["tool_name"] == "list_topics"
        assert pp["total"] == 25
        assert pp["offset"] == 10
        assert pp["limit"] == 10

    def test_offset_replaced_not_duplicated_and_filters_preserved(self) -> None:
        pp = _build_pagination_pending(
            "list_topics",
            {"channel_id": "genotek", "topic_type": "singleton", "offset": 5, "limit": 10},
            total=40,
            offset=5,
            limit=10,
        )
        assert pp["args"]["offset"] == 15
        assert pp["args"]["limit"] == 10
        # Every non-paging filter survives verbatim into the next page.
        assert pp["args"]["channel_id"] == "genotek"
        assert pp["args"]["topic_type"] == "singleton"


class TestPaginateReadResult:
    def _rows(self, n: int) -> list[dict[str, Any]]:
        return [{"id": f"r{i}", "title": f"T{i}"} for i in range(n)]

    def test_first_page_has_more_emits_pagination_pending(self) -> None:
        result = _paginate_read_result(
            "list_channels", {"offset": 0, "limit": 2}, self._rows(5), legacy_key="channels"
        )
        assert result["total"] == 5
        assert result["offset"] == 0
        assert result["limit"] == 2
        assert result["has_more"] is True
        assert [i["n"] for i in result["items"]] == [1, 2]
        pp = result["pagination_pending"]
        assert pp["tool_name"] == "list_channels"
        assert pp["args"]["offset"] == 2
        assert pp["total"] == 5

    def test_global_numbering_continues_on_later_page(self) -> None:
        result = _paginate_read_result("list_channels", {"offset": 2, "limit": 2}, self._rows(5))
        assert [i["n"] for i in result["items"]] == [3, 4]
        assert result["pagination_pending"]["args"]["offset"] == 4

    def test_terminal_page_omits_pagination_pending(self) -> None:
        result = _paginate_read_result("list_channels", {"offset": 4, "limit": 2}, self._rows(5))
        assert result["has_more"] is False
        assert "pagination_pending" not in result
        assert [i["n"] for i in result["items"]] == [5]

    def test_legacy_key_mirrors_page_and_count_is_total(self) -> None:
        result = _paginate_read_result(
            "list_channels", {"offset": 0, "limit": 2}, self._rows(5), legacy_key="channels"
        )
        # Legacy key points at the SAME page slice; count is the GLOBAL total.
        assert result["channels"] == result["items"]
        assert result["count"] == 5

    def test_small_list_stays_single_page_no_hint(self) -> None:
        # Default limit (20) keeps a small fixture on one page → back-compat:
        # no pagination_pending, has_more False (existing tests unaffected).
        result = _paginate_read_result("list_users", {}, self._rows(3), legacy_key="users")
        assert result["has_more"] is False
        assert "pagination_pending" not in result
        assert result["users"] == result["items"]
        assert result["count"] == 3


# ---------------------------------------------------------------------------
# TD-D-02: every paginated read-tool actually wires the contract
# ---------------------------------------------------------------------------


def _admin_user() -> MagicMock:
    u = MagicMock()
    u.allowed_channel_ids = None
    u.is_admin = True
    u.id = "admin"
    u.role = "admin"
    return u


@asynccontextmanager
async def _ctx(*yielded: Any):
    yield yielded if len(yielded) != 1 else yielded[0]


def _patches_list_channels(stack: ExitStack) -> None:
    stats = [
        {
            "channel_id": f"ch{i}",
            "channel_username": f"u{i}",
            "status": "active",
            "raw_messages": i,
            "processed_documents": i,
            "topics_count": i,
            "coverage_percent": 100.0,
        }
        for i in range(5)
    ]
    stack.enter_context(
        patch(
            "tg_parser.services.channel_service.get_all_channel_stats",
            AsyncMock(return_value=stats),
        )
    )


def _patches_list_users(stack: ExitStack) -> None:
    repo = AsyncMock()
    repo.list_users.return_value = [
        SimpleNamespace(id=f"u{i}", name=f"User {i}", role="user", max_channels=5) for i in range(5)
    ]
    repo.get_owned_channel_ids.return_value = []
    stack.enter_context(patch("tg_parser.auth.ownership.assert_admin", MagicMock()))
    stack.enter_context(
        patch("tg_parser.services.db_context.user_repo", lambda: _ctx(repo, MagicMock()))
    )


def _patches_list_digests(stack: ExitStack) -> None:
    repo = AsyncMock()
    repo.list_all.return_value = [
        SimpleNamespace(
            id=f"d{i}",
            owner_id="admin",
            chat_id=1,
            name=f"Digest {i}",
            channel_ids=["ch0"],
            cron_expression="0 9 * * *",
            timezone="UTC",
            format=SimpleNamespace(value="summary"),
            language="ru",
            is_active=True,
            last_sent_at=None,
            last_digest_cursor=None,
        )
        for i in range(5)
    ]
    stack.enter_context(
        patch(
            "tg_parser.services.db_context.digest_subscription_repo",
            lambda: _ctx(repo, MagicMock()),
        )
    )


def _patches_list_watchlists(stack: ExitStack) -> None:
    interest_repo = AsyncMock()
    interest_repo.list_all.return_value = [
        SimpleNamespace(
            id=f"w{i}",
            user_id="admin",
            chat_id=1,
            title=f"Interest {i}",
            description="d",
            keywords=["k"],
            exclude_keywords=[],
            channel_ids=["ch0"],
            threshold=0.6,
            notify_mode=SimpleNamespace(value="push"),
            is_active=True,
            workspace_id=None,
            last_checked_at=None,
            last_match_at=None,
        )
        for i in range(5)
    ]
    stack.enter_context(
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _ctx(interest_repo, MagicMock(), MagicMock(), MagicMock(), MagicMock()),
        )
    )


def _patches_list_topics(stack: ExitStack) -> None:
    cards = [
        SimpleNamespace(
            id=f"topic:ch:{i}",
            title=f"Topic {i}",
            summary=f"S{i}",
            type=SimpleNamespace(value="singleton"),
            sources=["ch0"],
        )
        for i in range(5)
    ]
    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = cards
    topic_card_repo.list_by_channels.return_value = cards
    topic_card_repo.list_all.return_value = cards
    topic_bundle_repo.list_by_channel.return_value = []
    topic_bundle_repo.list_all.return_value = []
    stack.enter_context(
        patch(
            "tg_parser.services.db_context.processing_repos",
            lambda: _ctx(proc_repo, topic_card_repo, topic_bundle_repo, MagicMock()),
        )
    )


_TOOL_FIXTURES: dict[str, Any] = {
    "list_topics": (_exec_list_topics, _patches_list_topics),
    "list_channels": (_exec_list_channels, _patches_list_channels),
    "list_digests": (_exec_list_digests, _patches_list_digests),
    "list_watchlists": (_exec_list_watchlists, _patches_list_watchlists),
    "list_users": (_exec_list_users, _patches_list_users),
}


class TestPaginatedReadToolCoverage:
    def test_registry_and_fixtures_agree(self) -> None:
        """Guard: a new paginated read-tool must register a contract fixture."""
        assert set(_TOOL_FIXTURES) == set(_PAGINATED_READ_TOOLS)

    @pytest.mark.parametrize("tool_name", sorted(_PAGINATED_READ_TOOLS))
    async def test_emits_pagination_pending_when_has_more(self, tool_name: str) -> None:
        exec_fn, setup = _TOOL_FIXTURES[tool_name]
        with ExitStack() as stack:
            setup(stack)
            result = await exec_fn({"offset": 0, "limit": 2}, current_user=_admin_user())

        assert result["total"] == 5
        assert result["has_more"] is True
        assert "pagination_pending" in result, f"{tool_name} dropped pagination_pending"
        pp = result["pagination_pending"]
        assert set(pp.keys()) == {"tool_name", "args", "total", "offset", "limit"}
        assert pp["tool_name"] == tool_name
        assert pp["args"]["offset"] == 2
        assert pp["args"]["limit"] == 2
        assert pp["total"] == 5
        # Items carry the global 1-based numbering.
        assert [i["n"] for i in result["items"]] == [1, 2]

    @pytest.mark.parametrize("tool_name", sorted(_PAGINATED_READ_TOOLS))
    async def test_terminal_page_has_no_hint(self, tool_name: str) -> None:
        exec_fn, setup = _TOOL_FIXTURES[tool_name]
        with ExitStack() as stack:
            setup(stack)
            result = await exec_fn({"offset": 4, "limit": 2}, current_user=_admin_user())
        assert result["has_more"] is False
        assert "pagination_pending" not in result


# ---------------------------------------------------------------------------
# TD-D-01: renderer unification
# ---------------------------------------------------------------------------


class TestRendererUnification:
    def _page(self, tool: str, offset: int, has_more: bool) -> dict[str, Any]:
        items = [{"n": offset + 1, "title": "Alpha", "summary": "s"}]
        return {
            "total": 4,
            "offset": offset,
            "limit": 1,
            "has_more": has_more,
            "items": items,
        }

    @pytest.mark.parametrize("tool_name", sorted(_PAGINATED_LIST_HEADERS))
    def test_header_present_per_tool(self, tool_name: str) -> None:
        text = _format_paginated_list(tool_name, self._page(tool_name, 0, True))
        assert _PAGINATED_LIST_HEADERS[tool_name] in text

    def test_page1_and_page2_share_identical_template(self) -> None:
        """The whole point of TD-D-01: page 1 and page 2 use one renderer.

        Render two consecutive pages and assert the structural template
        (header line + numbered body line + footer) is byte-identical modulo
        the item index / range — i.e. no page1→page2 visual jump.
        """
        page1 = _format_paginated_list("list_topics", self._page("list_topics", 0, True))
        page2 = _format_paginated_list("list_topics", self._page("list_topics", 1, True))
        # Same header line.
        assert page1.splitlines()[0] == page2.splitlines()[0]
        # Same continuation affordance on both pages.
        assert "ещё" in page1.lower()
        assert "ещё" in page2.lower()
        # Numbering advanced (global n), proving it is one shared template.
        assert "<b>1.</b>" in page1
        assert "<b>2.</b>" in page2

    def test_unknown_tool_falls_back_to_generic_header(self) -> None:
        text = _format_paginated_list("list_something_new", self._page("x", 0, False))
        assert "📋 Список" in text


# ---------------------------------------------------------------------------
# TD-D-03: _format_tool_result fallback + write-tool message guard
# ---------------------------------------------------------------------------


class TestFormatToolResultFallback:
    def test_message_wins_when_present(self) -> None:
        assert _format_tool_result("add_channel", {"message": "Канал добавлен"}) == "Канал добавлен"

    def test_error_is_surfaced(self) -> None:
        out = _format_tool_result("add_channel", {"error": "boom"})
        assert out.startswith("❗")
        assert "boom" in out

    def test_synthesizes_from_channel_id_and_status(self) -> None:
        out = _format_tool_result("add_channel", {"channel_id": "genotek", "status": "active"})
        assert "genotek" in out
        assert "active" in out
        assert out != "✅ Готово: add_channel."

    def test_synthesizes_from_id_only(self) -> None:
        out = _format_tool_result("register_user", {"id": "u-42"})
        assert "u-42" in out

    def test_generic_fallback_when_no_identifiers(self) -> None:
        assert _format_tool_result("reset_llm_config", {}) == "✅ Готово: reset_llm_config."

    @pytest.mark.parametrize("tool_name", sorted(_WRITE_TOOLS_REQUIRING_CONFIRM))
    def test_no_write_tool_ever_renders_empty(self, tool_name: str) -> None:
        """Contract: a confirmed write-tool can never produce an empty message.

        Catches a new write-tool whose executor forgot to set ``message`` —
        the runtime fallback guarantees a non-empty informative string for
        every shape (empty dict, id-only, status-only, channel-only).
        """
        for shape in ({}, {"id": "x"}, {"status": "ok"}, {"channel_id": "c"}):
            out = _format_tool_result(tool_name, shape)
            assert isinstance(out, str) and out.strip(), f"{tool_name} rendered empty for {shape!r}"
