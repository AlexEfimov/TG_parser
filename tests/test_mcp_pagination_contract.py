"""Contract tests for MCP ``pagination_pending`` symmetry (TD-D-02 / #40).

The bot read-tools centralised the ``pagination_pending`` FSM-hint contract in
``tg_parser/bot/tools.py`` (see ``tests/test_pagination_contract_tdd.py``).
This module is the MCP-side mirror: every paginated MCP read-tool in
``tg_parser.mcp_server._PAGINATED_READ_TOOLS`` must emit the SAME locked
``{tool_name, args, total, offset, limit}`` shape when ``has_more``, reusing
the SAME shared helper (``tg_parser.utils.pagination.build_pagination_pending``)
so the two surfaces cannot drift. The enumeration guard catches a new paginated
MCP read-tool shipped without the contract.

``list_channels`` is intentionally NOT in the registry: it returns a bare
``list[ChannelSummary]`` (no wrapper model to carry the sidecar field) — adding
the contract would be a breaking return-type change, so it is documented as an
explicit exception (BUG_LOG TD-D-02). ``get_cross_channel_stats`` is excluded
for the same reason the bot excludes it (analytics shape, not a flat list).
"""

from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tg_parser.utils.pagination as shared_pagination
from tg_parser.bot.tools import _build_pagination_pending as bot_build_pagination_pending
from tg_parser.mcp_server import (
    _PAGINATED_READ_TOOLS,
    DigestSubscriptionInfo,
    WatchInterestInfo,
    build_pagination_pending,
    list_digests,
    list_topics,
    list_users,
    list_watchlists,
)

# ---------------------------------------------------------------------------
# DRY: MCP and bot reuse the SAME shared helper (no duplicated contract)
# ---------------------------------------------------------------------------


class TestSharedHelperReuse:
    def test_mcp_imports_the_shared_helper(self) -> None:
        assert build_pagination_pending is shared_pagination.build_pagination_pending

    def test_bot_and_mcp_share_one_implementation(self) -> None:
        assert build_pagination_pending is bot_build_pagination_pending


# ---------------------------------------------------------------------------
# Fixtures — minimal mocks so each tool reaches the pagination slice path
# ---------------------------------------------------------------------------


def _admin() -> MagicMock:
    u = MagicMock()
    u.allowed_channel_ids = None
    u.is_admin = True
    u.id = "admin"
    u.role = "admin"
    return u


def _repo_ctx(*yielded: Any):
    @asynccontextmanager
    async def _cm():
        yield yielded

    return _cm


def _patch_resolve(stack: ExitStack) -> None:
    stack.enter_context(
        patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_admin()))
    )


def _setup_list_topics(stack: ExitStack) -> None:
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
    proc = AsyncMock()
    tc = AsyncMock()
    tb = AsyncMock()
    tc.list_all.return_value = cards
    tc.list_by_channel.return_value = cards
    tc.list_by_channels.return_value = cards
    tb.list_all.return_value = []
    tb.list_by_channel.return_value = []
    _patch_resolve(stack)
    stack.enter_context(
        patch("tg_parser.services.db_context.processing_repos", _repo_ctx(proc, tc, tb, MagicMock()))
    )


def _setup_list_users(stack: ExitStack) -> None:
    repo = AsyncMock()
    repo.list_users.return_value = [
        SimpleNamespace(id=f"u{i}", name=f"User {i}", role="user", max_channels=5)
        for i in range(5)
    ]
    repo.get_owned_channel_ids.return_value = []
    _patch_resolve(stack)
    stack.enter_context(patch("tg_parser.auth.ownership.assert_admin", MagicMock()))
    stack.enter_context(
        patch("tg_parser.services.db_context.user_repo", _repo_ctx(repo, MagicMock()))
    )


def _digest_info(sub: Any) -> DigestSubscriptionInfo:
    return DigestSubscriptionInfo(
        id=sub.id,
        owner_id="admin",
        name=f"Digest {sub.id}",
        channel_ids=["ch0"],
        cron_expression="0 9 * * *",
        timezone="UTC",
        format="summary",
        language="ru",
        is_active=True,
    )


def _setup_list_digests(stack: ExitStack) -> None:
    repo = AsyncMock()
    repo.list_all.return_value = [SimpleNamespace(id=f"d{i}") for i in range(5)]
    repo.list_by_owner.return_value = repo.list_all.return_value
    _patch_resolve(stack)
    stack.enter_context(patch("tg_parser.mcp_server._digest_to_info", _digest_info))
    stack.enter_context(
        patch(
            "tg_parser.services.db_context.digest_subscription_repo",
            _repo_ctx(repo, MagicMock()),
        )
    )


def _interest_info(interest: Any) -> WatchInterestInfo:
    return WatchInterestInfo(
        id=interest.id,
        user_id="admin",
        title=f"Interest {interest.id}",
        keywords=["k"],
        exclude_keywords=[],
        channel_ids=["ch0"],
        threshold=0.6,
        notify_mode="push",
        is_active=True,
    )


def _setup_list_watchlists(stack: ExitStack) -> None:
    repo = AsyncMock()
    repo.list_all.return_value = [SimpleNamespace(id=f"w{i}") for i in range(5)]
    repo.list_for_user.return_value = repo.list_all.return_value
    _patch_resolve(stack)
    stack.enter_context(patch("tg_parser.mcp_server._interest_to_info", _interest_info))
    stack.enter_context(
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            _repo_ctx(repo, MagicMock(), MagicMock(), MagicMock(), MagicMock()),
        )
    )


_TOOL_FIXTURES: dict[str, Any] = {
    "list_topics": (list_topics, _setup_list_topics),
    "list_users": (list_users, _setup_list_users),
    "list_digests": (list_digests, _setup_list_digests),
    "list_watchlists": (list_watchlists, _setup_list_watchlists),
}


# ---------------------------------------------------------------------------
# Every paginated MCP read-tool actually wires the contract
# ---------------------------------------------------------------------------


class TestMcpPaginatedReadToolCoverage:
    def test_registry_and_fixtures_agree(self) -> None:
        """Guard: a new paginated MCP read-tool must register a contract fixture."""
        assert set(_TOOL_FIXTURES) == set(_PAGINATED_READ_TOOLS)

    def test_list_channels_documented_exception(self) -> None:
        """list_channels returns a bare list → cannot carry the sidecar field."""
        assert "list_channels" not in _PAGINATED_READ_TOOLS

    @pytest.mark.parametrize("tool_name", sorted(_PAGINATED_READ_TOOLS))
    async def test_emits_pagination_pending_when_has_more(self, tool_name: str) -> None:
        fn, setup = _TOOL_FIXTURES[tool_name]
        with ExitStack() as stack:
            setup(stack)
            result = await fn(offset=0, limit=2)

        assert result.total == 5
        assert result.has_more is True
        assert len(result.items) == 2
        pp = result.pagination_pending
        assert pp is not None, f"{tool_name} dropped pagination_pending"
        assert set(pp.keys()) == {"tool_name", "args", "total", "offset", "limit"}
        assert pp["tool_name"] == tool_name
        assert pp["args"]["offset"] == 2
        assert pp["args"]["limit"] == 2
        assert pp["total"] == 5

    @pytest.mark.parametrize("tool_name", sorted(_PAGINATED_READ_TOOLS))
    async def test_terminal_page_has_no_hint(self, tool_name: str) -> None:
        fn, setup = _TOOL_FIXTURES[tool_name]
        with ExitStack() as stack:
            setup(stack)
            result = await fn(offset=4, limit=2)
        assert result.has_more is False
        assert result.pagination_pending is None
        assert len(result.items) == 1


# ---------------------------------------------------------------------------
# Backward compatibility — no offset/limit ⇒ bit-for-bit legacy behaviour
# ---------------------------------------------------------------------------


class TestMcpBackwardCompatibility:
    async def test_list_users_unpaginated_returns_all(self) -> None:
        with ExitStack() as stack:
            _setup_list_users(stack)
            result = await list_users()
        assert result.success is True
        assert len(result.users) == 5
        assert result.has_more is False
        assert result.pagination_pending is None

    async def test_list_digests_unpaginated_returns_all(self) -> None:
        with ExitStack() as stack:
            _setup_list_digests(stack)
            result = await list_digests()
        assert result.count == 5
        assert len(result.subscriptions) == 5
        assert result.has_more is False
        assert result.pagination_pending is None

    async def test_list_watchlists_unpaginated_returns_all(self) -> None:
        with ExitStack() as stack:
            _setup_list_watchlists(stack)
            result = await list_watchlists()
        assert result.count == 5
        assert len(result.interests) == 5
        assert result.has_more is False
        assert result.pagination_pending is None

    async def test_list_topics_small_list_no_hint(self) -> None:
        with ExitStack() as stack:
            _setup_list_topics(stack)
            result = await list_topics()
        assert result.total == 5
        assert result.has_more is False
        assert result.pagination_pending is None
        assert len(result.items) == 5
