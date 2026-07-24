"""F5-C bot topic-history tools — pure-mock tests (no Postgres required).

Locks in the bot-surface parity for the two read-only tools that mirror the
already-shipped MCP ``get_topic_versions`` / ``get_topic_history_diff``:

- declaration presence + total tool-count guard (34);
- ``_exec_get_topic_versions`` happy-path / not-found / no-access / limit;
- ``_exec_get_topic_history_diff`` default genesis→current / archival pair /
  TTL-gap typed not-found (never an exception) / not-found / no-access;
- both tools stay OUT of the confirm / read-context / paginated classifier
  sets (they are plain topic_id-based reads with MCP-shape results).

Backend read-paths (``list_by_topic`` / ``get_two_versions`` /
``diff_topic_summaries``) are reused as-is and covered elsewhere; here we only
verify the bot executors call them with parity to the MCP reference.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import (
    _PAGINATED_READ_TOOLS,
    _READ_TOOLS_TRACKED_FOR_CONTEXT,
    _TOOL_EXECUTORS,
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    TOOL_DECLARATIONS,
    _exec_get_topic_history_diff,
    _exec_get_topic_versions,
)
from tg_parser.domain.models import (
    Anchor,
    MessageType,
    TopicCard,
    TopicCardVersion,
    TopicType,
)


def _admin() -> CurrentUser:
    return CurrentUser(
        id="user-admin",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _scoped(allowed: list[str]) -> CurrentUser:
    return CurrentUser(
        id="user-scoped",
        name="user",
        role="user",
        allowed_channel_ids=list(allowed),
        max_channels=10,
    )


def _make_card(
    *,
    topic_id: str = "topic:tg:c1:post:1",
    sources: list[str] | None = None,
    summary_version: int = 3,
    last_summarized_at: datetime | None = None,
    new_items: int = 0,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title="Test topic",
        summary="Original summary",
        scope_in=["alpha"],
        scope_out=["beta"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="c1",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:c1:post:1",
                score=0.9,
            )
        ],
        sources=sources if sources is not None else ["c1"],
        updated_at=datetime(2026, 4, 26, tzinfo=UTC),
        summary_version=summary_version,
        last_summarized_at=last_summarized_at,
        new_items_since_last_summary=new_items,
    )


def _make_version(version_no: int = 1) -> TopicCardVersion:
    return TopicCardVersion(
        id=version_no,
        topic_id="topic:tg:c1:post:1",
        version_no=version_no,
        summary=f"Snapshot v{version_no}",
        scope_in=["alpha"],
        scope_out=["beta"],
        supporting_items_count_at_time=10 + version_no,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        prompt_version="1.0.0",
        created_at=datetime(2026, 4, 26, 10, version_no, 0, tzinfo=UTC),
    )


class _FakeCardRepo:
    def __init__(self, card: TopicCard | None) -> None:
        self._card = card

    async def get_by_id(self, _topic_id: str) -> TopicCard | None:
        return self._card


class _FakeVersionRepo:
    def __init__(self, versions: list[TopicCardVersion]) -> None:
        self._versions = versions
        self.calls: list[dict] = []

    async def list_by_topic(self, topic_id: str, limit: int = 50):
        self.calls.append({"topic_id": topic_id, "limit": limit})
        return list(self._versions[:limit])

    async def get_two_versions(self, topic_id: str, version_a: int, version_b: int):
        self.calls.append({"get_two_versions": (topic_id, version_a, version_b)})
        wanted = {version_a, version_b}
        return {v.version_no: v for v in self._versions if v.version_no in wanted}


@asynccontextmanager
async def _fake_resummarization_repos(card_repo, version_repo):
    yield (card_repo, "_bundle_repo", version_repo, "_proc_repo", "_db")


def _patch_repos(monkeypatch, card_repo, version_repo) -> None:
    monkeypatch.setattr(
        "tg_parser.services.db_context.resummarization_repos",
        lambda: _fake_resummarization_repos(card_repo, version_repo),
    )


# ---------------------------------------------------------------------------
# Declarations + classifier hygiene
# ---------------------------------------------------------------------------


class TestDeclarations:
    def test_both_tools_declared(self):
        names = {d["name"] for d in TOOL_DECLARATIONS}
        assert {"get_topic_versions", "get_topic_history_diff"} <= names

    def test_total_tool_count(self):
        assert len(TOOL_DECLARATIONS) == 34

    def test_registered_in_dispatch_map(self):
        assert _TOOL_EXECUTORS["get_topic_versions"] is _exec_get_topic_versions
        assert _TOOL_EXECUTORS["get_topic_history_diff"] is _exec_get_topic_history_diff

    def test_read_only_not_in_confirm_set(self):
        assert "get_topic_versions" not in _WRITE_TOOLS_REQUIRING_CONFIRM
        assert "get_topic_history_diff" not in _WRITE_TOOLS_REQUIRING_CONFIRM

    def test_not_in_read_context_set(self):
        # topic_id-based reads (no channel_id) — D-2 contract.
        assert "get_topic_versions" not in _READ_TOOLS_TRACKED_FOR_CONTEXT
        assert "get_topic_history_diff" not in _READ_TOOLS_TRACKED_FOR_CONTEXT

    def test_not_in_paginated_set(self):
        # MCP-shape single-response result, not list-shaped pagination_pending.
        assert "get_topic_versions" not in _PAGINATED_READ_TOOLS
        assert "get_topic_history_diff" not in _PAGINATED_READ_TOOLS


# ---------------------------------------------------------------------------
# _exec_get_topic_versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecGetTopicVersions:
    async def test_happy_path(self, monkeypatch):
        card = _make_card(summary_version=3, new_items=2)
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(card), vr)

        result = await _exec_get_topic_versions(
            {"topic_id": "topic:tg:c1:post:1", "limit": 10}, _admin()
        )

        assert result["topic_id"] == "topic:tg:c1:post:1"
        assert result["current_version"] == 3
        assert result["new_items_since_last_summary"] == 2
        assert len(result["versions"]) == 3
        assert result["versions"][0]["version_no"] == 3
        assert vr.calls == [{"topic_id": "topic:tg:c1:post:1", "limit": 10}]

    async def test_default_limit_is_10(self, monkeypatch):
        vr = _FakeVersionRepo([_make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(_make_card()), vr)

        await _exec_get_topic_versions({"topic_id": "topic:tg:c1:post:1"}, _admin())

        assert vr.calls == [{"topic_id": "topic:tg:c1:post:1", "limit": 10}]

    async def test_not_found(self, monkeypatch):
        vr = _FakeVersionRepo([])
        _patch_repos(monkeypatch, _FakeCardRepo(None), vr)

        result = await _exec_get_topic_versions({"topic_id": "topic:tg:cX:post:1"}, _admin())

        assert "not found" in result["error"].lower()
        assert vr.calls == []

    async def test_owner_of_one_source_allowed(self, monkeypatch):
        card = _make_card(sources=["c1", "c2"])
        vr = _FakeVersionRepo([_make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(card), vr)

        result = await _exec_get_topic_versions({"topic_id": "topic:tg:c1:post:1"}, _scoped(["c1"]))

        assert "error" not in result
        assert len(result["versions"]) == 1

    async def test_no_access_short_circuits(self, monkeypatch):
        card = _make_card(sources=["c1", "c2"])
        vr = _FakeVersionRepo([_make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(card), vr)

        result = await _exec_get_topic_versions(
            {"topic_id": "topic:tg:c1:post:1"}, _scoped(["c-other"])
        )

        assert "no access" in result["error"].lower()
        assert vr.calls == []

    async def test_invalid_limit(self, monkeypatch):
        vr = _FakeVersionRepo([])
        _patch_repos(monkeypatch, _FakeCardRepo(_make_card()), vr)

        low = await _exec_get_topic_versions(
            {"topic_id": "topic:tg:c1:post:1", "limit": 0}, _admin()
        )
        high = await _exec_get_topic_versions(
            {"topic_id": "topic:tg:c1:post:1", "limit": 99999}, _admin()
        )

        assert "limit" in low["error"].lower()
        assert "limit" in high["error"].lower()
        assert vr.calls == []


# ---------------------------------------------------------------------------
# _exec_get_topic_history_diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecGetTopicHistoryDiff:
    async def test_default_is_genesis_to_current(self, monkeypatch):
        card = _make_card(summary_version=3)
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(card), vr)

        result = await _exec_get_topic_history_diff({"topic_id": "topic:tg:c1:post:1"}, _admin())

        assert "error" not in result
        assert result["topic_id"] == "topic:tg:c1:post:1"
        assert result["left"]["version_no"] == 1
        assert result["right"]["version_no"] == "current"
        assert result["right"]["summary_version"] == 3
        assert result["summary_changed"] is True
        assert isinstance(result["summary_diff"], list)
        assert {"get_two_versions": ("topic:tg:c1:post:1", 1, 1)} in vr.calls

    async def test_archival_pair(self, monkeypatch):
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(_make_card(summary_version=4)), vr)

        result = await _exec_get_topic_history_diff(
            {"topic_id": "topic:tg:c1:post:1", "version_a": 1, "version_b": 3}, _admin()
        )

        assert "error" not in result
        assert result["left"]["version_no"] == 1
        assert result["right"]["version_no"] == 3
        assert {"get_two_versions": ("topic:tg:c1:post:1", 1, 3)} in vr.calls

    async def test_purged_version_typed_not_found(self, monkeypatch):
        vr = _FakeVersionRepo([_make_version(1)])  # v99 reclaimed
        _patch_repos(monkeypatch, _FakeCardRepo(_make_card(summary_version=6)), vr)

        result = await _exec_get_topic_history_diff(
            {"topic_id": "topic:tg:c1:post:1", "version_a": 1, "version_b": 99}, _admin()
        )

        assert "reclaimed by retention policy" in result["error"]
        assert result["missing_version"] == 99
        assert result["topic_id"] == "topic:tg:c1:post:1"

    async def test_purged_left_in_current_mode(self, monkeypatch):
        vr = _FakeVersionRepo([_make_version(1)])  # v2 missing
        _patch_repos(monkeypatch, _FakeCardRepo(_make_card(summary_version=6)), vr)

        result = await _exec_get_topic_history_diff(
            {"topic_id": "topic:tg:c1:post:1", "version_a": 2}, _admin()
        )

        assert "reclaimed by retention policy" in result["error"]
        assert result["missing_version"] == 2

    async def test_not_found(self, monkeypatch):
        vr = _FakeVersionRepo([])
        _patch_repos(monkeypatch, _FakeCardRepo(None), vr)

        result = await _exec_get_topic_history_diff({"topic_id": "topic:tg:cX:post:1"}, _admin())

        assert "not found" in result["error"].lower()
        assert vr.calls == []

    async def test_no_access_short_circuits(self, monkeypatch):
        card = _make_card(sources=["c1", "c2"])
        vr = _FakeVersionRepo([_make_version(1)])
        _patch_repos(monkeypatch, _FakeCardRepo(card), vr)

        result = await _exec_get_topic_history_diff(
            {"topic_id": "topic:tg:c1:post:1"}, _scoped(["c-other"])
        )

        assert "no access" in result["error"].lower()
        assert vr.calls == []
