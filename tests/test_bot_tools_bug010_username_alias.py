"""BUG-010 unit tests — source username alias resolution (Session I, 2026-05-06).

Verifies that ``_resolve_source`` correctly falls back to username lookup
when PK lookup returns None, and that all 4 write-tool executors route
through ``_resolve_source`` (so a user typing "AgeManagment" instead of
the numeric source_id no longer gets "Channel not found").

Tests U-1..U-6 mirror the plan in
``docs/notes/START_PROMPT_FIX_BUG010_SOURCE_USERNAME_ALIAS_SESSION_I_2026-05-06.md``
§ 4.2.

CI-class: unit (mock-based, no DB, runs in default pytest mode).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import (
    _exec_pause_channel,
    _exec_remove_channel,
    _exec_resume_channel,
    _exec_trigger_pipeline,
    _resolve_source,
)
from tg_parser.storage.ports import Source

NOW = datetime(2026, 5, 6, 14, 0, 0, tzinfo=UTC)

ADMIN_USER = CurrentUser(
    id="admin",
    name="admin",
    role="admin",
    allowed_channel_ids=None,
    max_channels=100,
)


def _make_source(
    *,
    source_id: str = "-1002111111",
    channel_username: str = "AgeManagment",
    status: str = "active",
) -> Source:
    return Source(
        source_id=source_id,
        channel_id=source_id,
        channel_username=channel_username,
        status=status,
        include_comments=False,
        created_at=NOW,
    )


def _mock_repo(
    *,
    pk_result: Source | None = None,
    username_result: Source | None = None,
) -> tuple:
    """Return (mock_ctx, state_repo) with configurable get_source / get_source_by_username."""
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.get_source.return_value = pk_result
    state_repo.get_source_by_username.return_value = username_result
    state_repo.list_sources.return_value = []
    state_repo.upsert_source.return_value = None
    state_repo.delete_source.return_value = True

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo


# ---------------------------------------------------------------------------
# U-1 — _resolve_source: falls back to username when PK returns None
# ---------------------------------------------------------------------------


class TestResolveSourcFallback:
    async def test_resolve_source_calls_username_fallback_on_none(self):
        """U-1: PK miss → username fallback called; source returned."""
        source = _make_source()
        _, state_repo = _mock_repo(pk_result=None, username_result=source)

        result = await _resolve_source("AgeManagment", state_repo)

        assert result is source
        state_repo.get_source.assert_awaited_once_with("AgeManagment")
        state_repo.get_source_by_username.assert_awaited_once_with("AgeManagment")

    async def test_resolve_source_no_fallback_when_pk_found(self):
        """U-2: PK hit → username fallback NOT called."""
        source = _make_source()
        _, state_repo = _mock_repo(pk_result=source, username_result=None)

        result = await _resolve_source("-1002111111", state_repo)

        assert result is source
        state_repo.get_source.assert_awaited_once_with("-1002111111")
        state_repo.get_source_by_username.assert_not_awaited()

    async def test_resolve_source_returns_none_when_both_miss(self):
        """Extra: both lookups miss → None."""
        _, state_repo = _mock_repo(pk_result=None, username_result=None)

        result = await _resolve_source("unknown_channel", state_repo)

        assert result is None
        state_repo.get_source_by_username.assert_awaited_once_with("unknown_channel")


# ---------------------------------------------------------------------------
# U-3 — _exec_remove_channel: username resolution via fallback
# ---------------------------------------------------------------------------


class TestRemoveChannelUsernameResolution:
    async def test_exec_remove_channel_uses_username_resolution(self):
        """U-3: remove_channel(channel_id='AgeManagment') finds channel via
        username fallback; returns preview (not 'Channel not found')."""
        source = _make_source()
        mock_ctx, state_repo = _mock_repo(pk_result=None, username_result=source)

        with (
            patch("tg_parser.services.db_context.ingestion_state_repo", mock_ctx),
            patch(
                "tg_parser.services.channel_service.get_channel_stats",
                return_value={"processed_documents": 10, "topics_count": 3, "raw_messages": 50},
            ),
        ):
            result = await _exec_remove_channel(
                {"channel_id": "AgeManagment", "confirm": False},
                current_user=ADMIN_USER,
            )

        # BUG-010 regression: channel found → preview, not "not found" error
        assert result.get("preview") is True, (
            f"Expected preview=True (channel found via username), got: {result}"
        )
        assert "removed" not in result, "Should not see 'removed: False' (not-found path)"
        state_repo.get_source_by_username.assert_awaited_once_with("AgeManagment")


# ---------------------------------------------------------------------------
# U-4 — _exec_pause_channel: username resolution via fallback
# ---------------------------------------------------------------------------


class TestPauseChannelUsernameResolution:
    async def test_exec_pause_channel_uses_username_resolution(self):
        """U-4: pause_channel(channel_id='AgeManagment') finds channel via
        username fallback; preview has 'action' key (not 'error': 'not_found')."""
        source = _make_source()
        mock_ctx, state_repo = _mock_repo(pk_result=None, username_result=source)

        with patch("tg_parser.services.db_context.ingestion_state_repo", mock_ctx):
            result = await _exec_pause_channel(
                {"channel_id": "AgeManagment", "confirm": False},
                current_user=ADMIN_USER,
            )

        # BUG-010 regression: channel found → no "error": "not_found"
        assert result.get("error") != "not_found", (
            f"Expected channel found via username, got not_found path: {result}"
        )
        assert result.get("action") == "pause", (
            f"Expected action=pause (source found), got: {result}"
        )
        state_repo.get_source_by_username.assert_awaited_once_with("AgeManagment")


# ---------------------------------------------------------------------------
# U-5 — _exec_resume_channel: username resolution via fallback
# ---------------------------------------------------------------------------


class TestResumeChannelUsernameResolution:
    async def test_exec_resume_channel_uses_username_resolution(self):
        """U-5: resume_channel(channel_id='AgeManagment') finds channel via
        username fallback; preview has 'action' key (not 'error': 'not_found')."""
        source = _make_source(status="paused")
        mock_ctx, state_repo = _mock_repo(pk_result=None, username_result=source)

        with patch("tg_parser.services.db_context.ingestion_state_repo", mock_ctx):
            result = await _exec_resume_channel(
                {"channel_id": "AgeManagment", "confirm": False},
                current_user=ADMIN_USER,
            )

        assert result.get("error") != "not_found", (
            f"Expected channel found via username, got not_found path: {result}"
        )
        assert result.get("action") == "resume", (
            f"Expected action=resume (source found), got: {result}"
        )
        state_repo.get_source_by_username.assert_awaited_once_with("AgeManagment")


# ---------------------------------------------------------------------------
# U-6 — _exec_trigger_pipeline: username resolution via fallback
# ---------------------------------------------------------------------------


class TestTriggerPipelineUsernameResolution:
    async def test_exec_trigger_pipeline_uses_username_resolution(self):
        """U-6: trigger_pipeline(channel_id='AgeManagment') finds channel via
        username fallback; preview has source_exists=True."""
        source = _make_source()
        mock_ctx, state_repo = _mock_repo(pk_result=None, username_result=source)

        fake_sched = {"sources": []}

        with (
            patch("tg_parser.services.db_context.ingestion_state_repo", mock_ctx),
            patch(
                "tg_parser.services.scheduler_service.get_scheduler_status",
                return_value=fake_sched,
            ),
            patch(
                "tg_parser.services.channel_service.get_channel_stats",
                side_effect=ValueError("no stats"),
            ),
        ):
            result = await _exec_trigger_pipeline(
                {"channel_id": "AgeManagment", "confirm": False},
                current_user=ADMIN_USER,
            )

        # BUG-010 regression: source found via username → source_exists=True
        assert result.get("source_exists") is True, (
            f"Expected source_exists=True (channel found via username), got: {result}"
        )
        state_repo.get_source_by_username.assert_awaited_once_with("AgeManagment")
