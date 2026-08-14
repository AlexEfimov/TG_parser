"""
BUG-094 — `add_channel` on an EXISTING channel must not rewind ingestion state.

The tool is an idempotent UPSERT (ADR-0009). Before the fix it built an
eight-field `Source` and handed it to a full-row `upsert_source`, so
`last_post_id` / `fail_count` / `channel_username` and the rest became
NULL. Ownership (BUG-093) is already closed; this file is the write-shape
axis: fields the call must not touch.

Covers MCP `add_channel` and bot `_exec_add_channel`. CLI `add-source`
shares the helper; its flags stay as-is (see BUG-094).
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from inspect import signature
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import Source

OWNER_ID = "user-1"
FOREIGN_OWNER_ID = "user-2"

CREATED_AT = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
BACKFILL_AT = datetime(2025, 2, 1, 8, 0, tzinfo=UTC)
LAST_ATTEMPT_AT = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
LAST_SUCCESS_AT = datetime(2026, 8, 10, 9, 5, tzinfo=UTC)
RATE_LIMIT_UNTIL = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
HISTORY_FROM = datetime(2024, 6, 1, tzinfo=UTC)
HISTORY_TO = datetime(2025, 6, 1, tzinfo=UTC)
DELETED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

PRESERVED_ON_UPDATE = (
    "last_post_id",
    "backfill_completed_at",
    "last_attempt_at",
    "last_success_at",
    "fail_count",
    "last_error",
    "rate_limit_until",
    "comments_unavailable",
    "history_from",
    "history_to",
    "poll_interval_seconds",
    "owner_id",
    "created_at",
)


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


def _user(channels: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id=OWNER_ID,
        name="alice",
        role="user",
        allowed_channel_ids=channels if channels is not None else ["own_channel"],
        max_channels=5,
    )


def _existing_source(
    *,
    channel_id: str = "own_channel",
    deleted_at: datetime | None = None,
    include_comments: bool = True,
    batch_size: int = 500,
    channel_username: str | None = "foo",
    owner_id: str = OWNER_ID,
) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        channel_username=channel_username,
        status="paused",
        include_comments=include_comments,
        history_from=HISTORY_FROM,
        history_to=HISTORY_TO,
        poll_interval_seconds=900,
        batch_size=batch_size,
        last_post_id="119",
        backfill_completed_at=BACKFILL_AT,
        last_attempt_at=LAST_ATTEMPT_AT,
        last_success_at=LAST_SUCCESS_AT,
        fail_count=3,
        last_error="timeout",
        rate_limit_until=RATE_LIMIT_UNTIL,
        comments_unavailable=True,
        created_at=CREATED_AT,
        owner_id=owner_id,
        deleted_at=deleted_at,
    )


def _assert_cursor_preserved(upserted: Source, original: Source) -> None:
    for name in PRESERVED_ON_UPDATE:
        assert getattr(upserted, name) == getattr(original, name), name
    assert upserted.status == "active"


@asynccontextmanager
async def _fake_ingestion_ctx(state_repo):
    yield (state_repo, MagicMock())


def _state_repo(existing: Source | None, *, hide_deleted: bool = False) -> AsyncMock:
    """Repo mock. `hide_deleted` mirrors get_source's default filter."""
    repo = AsyncMock()

    async def get_source(source_id: str, *, include_deleted: bool = False):
        if existing is None:
            return None
        if existing.source_id != source_id:
            return None
        if existing.deleted_at is not None and not include_deleted:
            return None
        return existing

    async def get_source_by_username(username: str, *, include_deleted: bool = False):
        if existing is None or existing.channel_username != username:
            return None
        if existing.deleted_at is not None and not include_deleted:
            return None
        return existing

    if hide_deleted:
        repo.get_source = AsyncMock(side_effect=get_source)
        repo.get_source_by_username = AsyncMock(side_effect=get_source_by_username)
    else:
        repo.get_source.return_value = existing
        repo.get_source_by_username.return_value = None
    repo.list_sources.return_value = []
    repo.upsert_source = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# §3.1 Red: existing with a cursor → add_channel → cursor lives
# ---------------------------------------------------------------------------


class TestMcpPreservesCursor:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_one_field_update_keeps_cursor_and_service_fields(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source()
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("own_channel", include_comments=True, ctx=None)

        assert result.created is False
        assert result.status != "rejected"
        upserted = state_repo.upsert_source.call_args[0][0]
        _assert_cursor_preserved(upserted, original)
        assert upserted.include_comments is True
        assert upserted.batch_size == 500
        assert upserted.channel_username == "foo"
        assert upserted.last_post_id == "119"

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_omitted_args_do_not_null_cursor(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source()
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("own_channel", ctx=None)

        assert result.created is False
        upserted = state_repo.upsert_source.call_args[0][0]
        _assert_cursor_preserved(upserted, original)
        assert upserted.last_post_id == "119"


class TestBotPreservesCursor:
    async def test_one_field_update_keeps_cursor_and_service_fields(self):
        original = _existing_source()
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel", "confirm": True, "include_comments": True},
                current_user=_user(),
            )

        assert result["created"] is False
        upserted = state_repo.upsert_source.call_args[0][0]
        _assert_cursor_preserved(upserted, original)
        assert upserted.include_comments is True
        assert upserted.batch_size == 500
        assert upserted.last_post_id == "119"

    async def test_omitted_args_do_not_null_cursor(self):
        original = _existing_source()
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel", "confirm": True},
                current_user=_user(),
            )

        assert result["created"] is False
        upserted = state_repo.upsert_source.call_args[0][0]
        _assert_cursor_preserved(upserted, original)


# ---------------------------------------------------------------------------
# §3.2 Default ≠ "not passed"
# ---------------------------------------------------------------------------


class TestMcpDefaultIsNotOmitted:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_omitted_kwargs_leave_existing_settings(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            await add_channel("own_channel", ctx=None)

        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.batch_size == 500
        assert upserted.include_comments is True

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_explicit_comments_does_not_reset_batch_size(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            await add_channel("own_channel", include_comments=True, ctx=None)

        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.include_comments is True
        assert upserted.batch_size == 500

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_explicit_batch_size_100_is_applied(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            await add_channel("own_channel", batch_size=100, ctx=None)

        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.batch_size == 100
        assert upserted.include_comments is True

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_explicit_comments_false_is_applied(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            await add_channel("own_channel", include_comments=False, ctx=None)

        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.include_comments is False
        assert upserted.batch_size == 500

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_create_omitted_args_still_default_false_and_100(self, mock_resolve):
        mock_resolve.return_value = _user()
        state_repo = _state_repo(None)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("brand_new_ch", ctx=None)

        assert result.created is True
        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.include_comments is False
        assert upserted.batch_size == 100
        assert upserted.owner_id == OWNER_ID
        assert upserted.last_post_id is None

    def test_mcp_signature_defaults_are_none_not_false_100(self):
        from tg_parser.mcp_server import add_channel

        params = signature(add_channel).parameters
        assert params["include_comments"].default is None
        assert params["batch_size"].default is None

    def test_fastmcp_schema_does_not_inject_false_100(self):
        """Live MCP clients may send schema defaults as explicit values.

        If FastMCP still advertises false/100, a client that fills defaults
        would look like an explicit write. None on the signature is not
        enough in that case — say so, don't pretend.
        """
        from tg_parser.mcp_server import add_channel, mcp

        tool = mcp._tool_manager.get_tool("add_channel")
        schema = tool.parameters
        props = schema.get("properties", {})
        comments = props.get("include_comments", {})
        batch = props.get("batch_size", {})
        comments_default = comments.get("default", None)
        batch_default = batch.get("default", None)
        assert comments_default in (None,) or "default" not in comments, (
            f"FastMCP schema default for include_comments is {comments_default!r}; "
            "clients that materialise schema defaults would assert False. "
            f"full property={comments!r}"
        )
        assert batch_default in (None,) or "default" not in batch, (
            f"FastMCP schema default for batch_size is {batch_default!r}; "
            "clients that materialise schema defaults would assert 100. "
            f"full property={batch!r}"
        )
        params = signature(add_channel).parameters
        assert params["include_comments"].default is None
        assert params["batch_size"].default is None


class TestBotDefaultIsNotOmitted:
    async def test_args_without_keys_leave_existing_settings(self):
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            await _exec_add_channel(
                {"channel_id": "own_channel", "confirm": True},
                current_user=_user(),
            )

        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.batch_size == 500
        assert upserted.include_comments is True

    async def test_explicit_batch_size_100_is_applied(self):
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            await _exec_add_channel(
                {"channel_id": "own_channel", "confirm": True, "batch_size": 100},
                current_user=_user(),
            )

        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.batch_size == 100
        assert upserted.include_comments is True

    async def test_update_preview_shows_current_plus_overlay_not_tool_defaults(self):
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel"},
                current_user=_user(),
            )

        assert result["preview"] is True
        assert result["action"] == "update"
        assert result["settings"]["include_comments"] is True
        assert result["settings"]["batch_size"] == 500
        assert result["settings"]["channel_username"] == "foo"
        state_repo.upsert_source.assert_not_awaited()

    async def test_update_preview_overlay_one_field(self):
        original = _existing_source(include_comments=True, batch_size=500)
        state_repo = _state_repo(original)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel", "include_comments": False},
                current_user=_user(),
            )

        assert result["preview"] is True
        assert result["settings"]["include_comments"] is False
        assert result["settings"]["batch_size"] == 500

    async def test_create_preview_still_shows_tool_defaults(self):
        state_repo = _state_repo(None)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "brand_new_ch"},
                current_user=_user(),
            )

        assert result["preview"] is True
        assert result["action"] == "create"
        assert result["settings"]["include_comments"] is False
        assert result["settings"]["batch_size"] == 100


# ---------------------------------------------------------------------------
# §3.3 Soft-delete lookup: reanimate keeps the cursor
# ---------------------------------------------------------------------------


class TestMcpReanimatePreservesCursor:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_soft_deleted_with_cursor_reanimates_and_keeps_cursor(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source(deleted_at=DELETED_AT)
        state_repo = _state_repo(original, hide_deleted=True)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("own_channel", ctx=None)

        assert result.created is False, "reanimate is an update, not a create"
        assert result.status == "active"
        upserted = state_repo.upsert_source.call_args[0][0]
        _assert_cursor_preserved(upserted, original)
        assert upserted.last_post_id == "119"
        state_repo.list_sources.assert_not_awaited()

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_soft_deleted_skips_channel_limit(self, mock_resolve):
        user = CurrentUser(
            id=OWNER_ID,
            name="alice",
            role="user",
            allowed_channel_ids=["own_channel"],
            max_channels=0,
        )
        mock_resolve.return_value = user
        original = _existing_source(deleted_at=DELETED_AT)
        state_repo = _state_repo(original, hide_deleted=True)
        state_repo.list_sources.return_value = [MagicMock(), MagicMock()]

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("own_channel", ctx=None)

        assert result.created is False
        assert result.status != "rejected"
        state_repo.upsert_source.assert_awaited_once()

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_foreign_soft_deleted_is_rejected_without_upsert(self, mock_resolve):
        mock_resolve.return_value = _user()
        original = _existing_source(deleted_at=DELETED_AT, owner_id=FOREIGN_OWNER_ID)
        state_repo = _state_repo(original, hide_deleted=True)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("own_channel", ctx=None)

        assert result.created is False
        assert result.status == "rejected"
        assert "No access to channel" in result.message
        state_repo.upsert_source.assert_not_awaited()


class TestBotReanimatePreservesCursor:
    async def test_soft_deleted_with_cursor_reanimates_and_keeps_cursor(self):
        original = _existing_source(deleted_at=DELETED_AT)
        state_repo = _state_repo(original, hide_deleted=True)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel", "confirm": True},
                current_user=_user(),
            )

        assert result["created"] is False
        upserted = state_repo.upsert_source.call_args[0][0]
        _assert_cursor_preserved(upserted, original)
        assert upserted.last_post_id == "119"

    async def test_foreign_soft_deleted_is_rejected_without_upsert(self):
        original = _existing_source(deleted_at=DELETED_AT, owner_id=FOREIGN_OWNER_ID)
        state_repo = _state_repo(original, hide_deleted=True)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel", "confirm": True},
                current_user=_user(),
            )

        assert result["created"] is False
        assert "No access to channel" in result["message"]
        state_repo.upsert_source.assert_not_awaited()


# ---------------------------------------------------------------------------
# Helper: revert this and §3.1–3.3 go red again
# ---------------------------------------------------------------------------


class TestSourceForAddChannelHelper:
    def test_update_overlays_only_provided_fields(self):
        from tg_parser.storage.source_overlay import source_for_add_channel

        original = _existing_source()
        built = source_for_add_channel(
            original,
            source_id="own_channel",
            channel_id="own_channel",
            owner_id=OWNER_ID,
            include_comments=False,
        )
        _assert_cursor_preserved(built, original)
        assert built.include_comments is False
        assert built.batch_size == 500
        assert built.channel_username == "foo"

    def test_create_uses_tool_defaults(self):
        from tg_parser.storage.source_overlay import source_for_add_channel

        built = source_for_add_channel(
            None,
            source_id="new_ch",
            channel_id="new_ch",
            owner_id=OWNER_ID,
        )
        assert built.include_comments is False
        assert built.batch_size == 100
        assert built.last_post_id is None
        assert built.owner_id == OWNER_ID
        assert built.status == "active"
