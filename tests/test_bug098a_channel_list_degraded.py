"""BUG-098 (a) / F-07 — degraded coverage is distinguishable from a measured zero.

The coverage aggregate already isolated its failure (BUG-066). What was
missing is a place for the marker: a bare ``list[ChannelSummary]`` cannot
carry ``degraded``, and ``coverage_percent: float`` cannot be null. After
R3 a failed aggregate yields ``coverage_percent is None`` +
``coverage_degraded=True`` on every row, and MCP/bot ``list_channels``
surface ``degraded=True``. A successful aggregate with zero covered docs
stays ``0.0`` / ``degraded=False``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError

from tg_parser.auth.models import CurrentUser
from tg_parser.services import channel_service
from tg_parser.services.channel_service import get_all_channel_stats


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _source(channel_id: str = "chA") -> SimpleNamespace:
    return SimpleNamespace(channel_id=channel_id, channel_username="@cha", status="active")


def _patch_stats(
    monkeypatch,
    *,
    processed: int,
    covered: int | None,
    coverage_error: Exception | None = None,
) -> None:
    state_repo = SimpleNamespace(list_sources=AsyncMock(return_value=[_source()]))
    raw_repo = SimpleNamespace(count_all_grouped_by_channel=AsyncMock(return_value={"chA": 10}))
    proc_repo = SimpleNamespace(
        count_all_grouped_by_channel=AsyncMock(return_value={"chA": processed}),
        coverage_counts_by_channel=AsyncMock(
            side_effect=coverage_error,
            return_value={} if coverage_error else {"chA": covered or 0},
        ),
    )
    topic_card_repo = SimpleNamespace(count_by_channel_grouped=AsyncMock(return_value={"chA": 1}))

    @asynccontextmanager
    async def _fake():
        yield (state_repo, raw_repo, proc_repo, topic_card_repo, None, None, None, None)

    monkeypatch.setattr(channel_service, "stats_repos", _fake)


async def test_failed_coverage_is_null_and_flagged(monkeypatch) -> None:
    _patch_stats(monkeypatch, processed=4, covered=None, coverage_error=SQLAlchemyError("timeout"))
    row = (await get_all_channel_stats())[0]
    assert row["raw_messages"] == 10
    assert row["processed_documents"] == 4
    assert row["topics_count"] == 1
    assert row["coverage_percent"] is None
    assert row["coverage_degraded"] is True


async def test_successful_zero_covered_is_measured_zero(monkeypatch) -> None:
    _patch_stats(monkeypatch, processed=4, covered=0)
    row = (await get_all_channel_stats())[0]
    assert row["coverage_percent"] == 0.0
    assert row["coverage_degraded"] is False


async def test_mcp_list_channels_surfaces_degraded(monkeypatch) -> None:
    from tg_parser.mcp_server import list_channels

    _patch_stats(monkeypatch, processed=4, covered=None, coverage_error=SQLAlchemyError("timeout"))
    with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_admin())):
        result = await list_channels()
    assert result.degraded is True
    assert result.items[0].coverage_percent is None
    assert result.total == 1
    assert result.has_more is False


async def test_mcp_list_channels_healthy_zero_is_not_degraded(monkeypatch) -> None:
    from tg_parser.mcp_server import list_channels

    _patch_stats(monkeypatch, processed=4, covered=0)
    with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_admin())):
        result = await list_channels()
    assert result.degraded is False
    assert result.items[0].coverage_percent == 0.0


async def test_bot_list_channels_surfaces_degraded(monkeypatch) -> None:
    from tg_parser.bot.tools import _exec_list_channels

    _patch_stats(monkeypatch, processed=4, covered=None, coverage_error=SQLAlchemyError("timeout"))
    result = await _exec_list_channels({}, current_user=_admin())
    assert result["degraded"] is True
    assert result["items"][0]["coverage_percent"] is None
    assert result["channels"][0]["coverage_percent"] is None


async def test_resource_channels_iterates_items(monkeypatch) -> None:
    from tg_parser.mcp_server import resource_channels

    _patch_stats(monkeypatch, processed=4, covered=0)
    with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_admin())):
        payload = await resource_channels()
    rows = json.loads(payload)
    assert isinstance(rows, list)
    assert rows[0]["channel_id"] == "chA"
    assert rows[0]["coverage_percent"] == 0.0


async def test_bot_list_channels_healthy_zero_is_not_degraded(monkeypatch) -> None:
    from tg_parser.bot.tools import _exec_list_channels

    _patch_stats(monkeypatch, processed=4, covered=0)
    result = await _exec_list_channels({}, current_user=_admin())
    assert result["degraded"] is False
    assert result["items"][0]["coverage_percent"] == 0.0
