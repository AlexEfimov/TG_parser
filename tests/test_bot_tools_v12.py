"""
Tests for Telegram bot V1.2 tools: add_channel, remove_channel,
get_llm_config, set_llm_config, reset_llm_config.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import (
    TOOL_DECLARATIONS,
    _running_pipelines,
    execute_tool,
)
from tg_parser.storage.ports import Source

_TEST_USER = CurrentUser(
    id="test-user",
    name="tester",
    role="user",
    allowed_channel_ids=None,
    max_channels=20,
)

NOW = datetime(2026, 4, 9, 10, 0, 0, tzinfo=UTC)

INGEST_STATE_PATCH = "tg_parser.services.db_context.ingestion_state_repo"
REMOVAL_REPOS_PATCH = "tg_parser.services.db_context.removal_repos"
CHANNEL_STATS_PATCH = "tg_parser.services.channel_service.get_channel_stats"
LLM_CONFIG_PATCH = "tg_parser.config.llm_config"


def _make_source(
    channel_id: str = "ch",
    status: str = "active",
    **kwargs,
) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status=status,
        include_comments=True,
        channel_username="test",
        created_at=NOW,
        **kwargs,
    )


def _mock_ingestion_state_repo(get_source_result=None, list_sources_result=None):
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.get_source.return_value = get_source_result
    state_repo.list_sources.return_value = list_sources_result or []
    state_repo.upsert_source.return_value = None

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo


def _mock_removal_repos():
    state_repo = AsyncMock()
    raw_repo = AsyncMock()
    proc_repo = AsyncMock()
    failure_repo = AsyncMock()
    embedding_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    job_repo = AsyncMock()
    task_history_repo = AsyncMock()
    db = MagicMock()

    for repo in (
        embedding_repo,
        proc_repo,
        failure_repo,
        topic_card_repo,
        topic_bundle_repo,
        job_repo,
        task_history_repo,
        raw_repo,
    ):
        repo.delete_by_channel.return_value = 0

    state_repo.get_source.return_value = _make_source()
    state_repo.delete_source.return_value = True

    repos_tuple = (
        state_repo,
        raw_repo,
        proc_repo,
        failure_repo,
        embedding_repo,
        topic_card_repo,
        topic_bundle_repo,
        job_repo,
        task_history_repo,
        db,
    )

    @asynccontextmanager
    async def mock_ctx():
        yield repos_tuple

    return mock_ctx, repos_tuple


def _tool_names() -> set[str]:
    return {d["name"] for d in TOOL_DECLARATIONS}


def _sample_llm_config():
    return {
        "global": {"provider": "openai", "model": "gpt-4o", "overridden": False},
        "stages": {
            "processing": {"provider": "openai", "model": "gpt-4o", "overridden": False},
            "topicization": {"provider": "openai", "model": "gpt-4o", "overridden": False},
        },
        "available_providers": {
            "openai": True,
            "anthropic": False,
            "gemini": True,
            "ollama": True,
        },
        "runtime_overrides": {},
    }


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


class TestBotToolDeclarationsV12:
    def test_v12_tools_registered(self):
        names = _tool_names()
        for name in (
            "add_channel",
            "remove_channel",
            "get_llm_config",
            "set_llm_config",
            "reset_llm_config",
        ):
            assert name in names, f"{name} not in TOOL_DECLARATIONS"

    def test_total_tool_count(self):
        assert len(TOOL_DECLARATIONS) == 32


# ---------------------------------------------------------------------------
# add_channel
# ---------------------------------------------------------------------------


class TestExecAddChannel:
    async def test_preview_new_channel(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None, list_sources_result=[])
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("add_channel", {"channel_id": "@new_ch"})

        assert result["preview"] is True
        assert result["channel_id"] == "new_ch"
        assert result["action"] == "create"
        assert result["current_status"] is None
        assert result["active_sources"] == 0
        assert result["limit_reached"] is False

    async def test_preview_existing_channel(self):
        source = _make_source(channel_id="existing", status="paused")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source, list_sources_result=[])
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("add_channel", {"channel_id": "existing"})

        assert result["preview"] is True
        assert result["action"] == "update"
        assert result["current_status"] == "paused"

    async def test_preview_limit_reached(self):
        active = [_make_source(channel_id=f"ch{i}") for i in range(_TEST_USER.max_channels)]
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None, list_sources_result=active)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "over_limit"},
                current_user=_TEST_USER,
            )

        assert result["preview"] is True
        assert result["limit_reached"] is True

    async def test_confirm_creates_new(self):
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None,
            list_sources_result=[],
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "add_channel",
                {
                    "channel_id": "@new_ch",
                    "include_comments": True,
                    "batch_size": 50,
                    "confirm": True,
                },
            )

        assert result["created"] is True
        assert result["status"] == "active"
        assert result["channel_id"] == "new_ch"
        state_repo.upsert_source.assert_awaited_once()
        upserted: Source = state_repo.upsert_source.call_args[0][0]
        assert upserted.channel_id == "new_ch"
        assert upserted.include_comments is True
        assert upserted.batch_size == 50

    async def test_confirm_updates_existing(self):
        existing = _make_source(channel_id="ch", status="paused")
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=existing,
            list_sources_result=[],
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["created"] is False
        assert result["status"] == "active"
        state_repo.upsert_source.assert_awaited_once()

    async def test_confirm_rejected_at_limit(self):
        active = [_make_source(channel_id=f"ch{i}") for i in range(_TEST_USER.max_channels)]
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None,
            list_sources_result=active,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "over_limit", "confirm": True},
                current_user=_TEST_USER,
            )

        assert result["created"] is False
        assert "limit" in result["message"].lower()
        state_repo.upsert_source.assert_not_awaited()


class TestExecAddChannelBlockedPlaceholder:
    """BUG-002 mitigation M2 — placeholder reject in `_exec_add_channel`."""

    async def test_preview_rejects_test_channel(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None, list_sources_result=[]
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("add_channel", {"channel_id": "test_channel"})

        assert result["success"] is False
        assert result["error"] == "blocked_placeholder_name"
        assert result["channel_id"] == "test_channel"
        assert result.get("blocked_list_size", 0) >= 8
        state_repo.upsert_source.assert_not_awaited()

    async def test_confirm_rejects_test_channel_too(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None, list_sources_result=[]
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "test_channel", "confirm": True},
            )

        assert result["success"] is False
        assert result["error"] == "blocked_placeholder_name"
        state_repo.upsert_source.assert_not_awaited()

    async def test_normalized_at_prefix_is_rejected(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None, list_sources_result=[]
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("add_channel", {"channel_id": "@my_channel"})

        assert result["success"] is False
        assert result["error"] == "blocked_placeholder_name"
        assert result["channel_id"] == "my_channel"

    async def test_env_var_extends_blocked_list(self, monkeypatch):
        monkeypatch.setenv("BLOCKED_CHANNEL_IDS", "foo, bar ,baz")
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None, list_sources_result=[]
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("add_channel", {"channel_id": "bar"})

        assert result["success"] is False
        assert result["error"] == "blocked_placeholder_name"
        state_repo.upsert_source.assert_not_awaited()

    async def test_real_channel_proceeds_to_preview(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=None, list_sources_result=[]
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "add_channel", {"channel_id": "real_channel_xyz"}
            )

        assert result.get("preview") is True
        assert result["channel_id"] == "real_channel_xyz"
        assert "error" not in result
        state_repo.upsert_source.assert_not_awaited()


# ---------------------------------------------------------------------------
# remove_channel
# ---------------------------------------------------------------------------


class TestExecRemoveChannel:
    def setup_method(self):
        _running_pipelines.clear()

    async def test_preview_with_stats(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        mock_stats = AsyncMock(
            return_value={
                "processed_documents": 100,
                "topics_count": 10,
                "raw_messages": 500,
            }
        )

        with patch(INGEST_STATE_PATCH, ctx), patch(CHANNEL_STATS_PATCH, mock_stats):
            result = await execute_tool("remove_channel", {"channel_id": "@ch"})

        assert result["preview"] is True
        assert result["channel_id"] == "ch"
        assert result["processed_documents"] == 100
        assert result["topics_count"] == 10
        assert result["raw_messages"] == 500
        assert "IRREVERSIBLE" in result["warning"]

    async def test_preview_not_found(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("remove_channel", {"channel_id": "missing"})

        assert result["removed"] is False
        assert "not found" in result["message"].lower()

    async def test_confirm_cascade_delete(self):
        source = _make_source(channel_id="ch")
        ingest_ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        removal_ctx, repos = _mock_removal_repos()

        (
            state_repo,
            raw_repo,
            proc_repo,
            failure_repo,
            embedding_repo,
            topic_card_repo,
            topic_bundle_repo,
            job_repo,
            task_history_repo,
            _,
        ) = repos

        proc_repo.delete_by_channel.return_value = 50
        embedding_repo.delete_by_channel.return_value = 200
        raw_repo.delete_by_channel.return_value = 300

        with patch(INGEST_STATE_PATCH, ingest_ctx), patch(REMOVAL_REPOS_PATCH, removal_ctx):
            result = await execute_tool(
                "remove_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["removed"] is True
        assert result["details"]["processed_documents"] == 50
        assert result["details"]["embeddings"] == 200
        assert result["details"]["raw_messages"] == 300
        assert result["details"]["source"] == 1
        state_repo.delete_source.assert_awaited_once_with("ch")

    async def test_confirm_blocked_by_running_pipeline(self):
        source = _make_source(channel_id="busy")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        _running_pipelines.add("busy")

        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "remove_channel",
                {"channel_id": "busy", "confirm": True},
            )

        assert result["removed"] is False
        assert "running" in result["message"].lower()

    async def test_preview_stats_error_still_ok(self):
        source = _make_source(channel_id="ch")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        mock_stats = AsyncMock(side_effect=ValueError("no stats"))

        with patch(INGEST_STATE_PATCH, ctx), patch(CHANNEL_STATS_PATCH, mock_stats):
            result = await execute_tool("remove_channel", {"channel_id": "ch"})

        assert result["preview"] is True
        assert result["processed_documents"] == 0


# ---------------------------------------------------------------------------
# get_llm_config
# ---------------------------------------------------------------------------


class TestExecGetLLMConfig:
    async def test_returns_config(self):
        mock_cfg = MagicMock()
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool("get_llm_config", {})

        assert "config" in result
        assert result["config"]["global"]["provider"] == "openai"
        assert "stages" in result["config"]
        assert "available_providers" in result["config"]


# ---------------------------------------------------------------------------
# set_llm_config
# ---------------------------------------------------------------------------


class TestExecSetLLMConfig:
    async def test_preview(self):
        mock_cfg = MagicMock()
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "global", "provider": "anthropic"},
            )

        assert result["preview"] is True
        assert result["will_set"]["scope"] == "global"
        assert result["will_set"]["provider"] == "anthropic"
        assert "current_config" in result

    async def test_confirm_success(self):
        updated = _sample_llm_config()
        updated["global"]["provider"] = "anthropic"
        updated["global"]["overridden"] = True

        mock_cfg = MagicMock()
        mock_cfg.set.return_value = updated

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "global", "provider": "anthropic", "confirm": True},
            )

        assert result["success"] is True
        assert result["config"]["global"]["provider"] == "anthropic"
        mock_cfg.set.assert_called_once_with(
            scope="global",
            provider="anthropic",
            model=None,
            temperature=None,
            max_tokens=None,
        )

    async def test_confirm_with_model(self):
        mock_cfg = MagicMock()
        mock_cfg.set.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "processing", "provider": "openai", "model": "gpt-4o", "confirm": True},
            )

        assert result["success"] is True
        mock_cfg.set.assert_called_once_with(
            scope="processing",
            provider="openai",
            model="gpt-4o",
            temperature=None,
            max_tokens=None,
        )

    async def test_confirm_invalid_provider(self):
        mock_cfg = MagicMock()
        mock_cfg.set.side_effect = ValueError("Unsupported provider 'bad'")
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "global", "provider": "bad", "confirm": True},
            )

        assert "error" in result
        assert "Unsupported" in result["error"]
        assert "config" in result

    async def test_confirm_invalid_scope(self):
        mock_cfg = MagicMock()
        mock_cfg.set.side_effect = ValueError("Invalid scope 'bad'")
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "bad", "provider": "openai", "confirm": True},
            )

        assert "error" in result
        assert "Invalid scope" in result["error"]


# ---------------------------------------------------------------------------
# reset_llm_config
# ---------------------------------------------------------------------------


class TestExecResetLLMConfig:
    async def test_preview_single_scope(self):
        mock_cfg = MagicMock()
        mock_cfg.get_all.return_value = {
            **_sample_llm_config(),
            "runtime_overrides": {"global": {"provider": "anthropic", "model": None}},
        }

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "reset_llm_config",
                {"scope": "global"},
            )

        assert result["preview"] is True
        assert result["scope_to_reset"] == "global"
        assert "global" in result["current_overrides"]

    async def test_preview_all_scopes(self):
        mock_cfg = MagicMock()
        mock_cfg.get_all.return_value = {
            **_sample_llm_config(),
            "runtime_overrides": {
                "global": {"provider": "anthropic", "model": None},
                "processing": {"provider": "gemini", "model": None},
            },
        }

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool("reset_llm_config", {})

        assert result["preview"] is True
        assert result["scope_to_reset"] == "all"
        assert len(result["current_overrides"]) == 2

    async def test_confirm_single_scope(self):
        mock_cfg = MagicMock()
        mock_cfg.clear.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "reset_llm_config",
                {"scope": "processing", "confirm": True},
            )

        assert result["success"] is True
        assert "processing" in result["message"]
        mock_cfg.clear.assert_called_once_with(scope="processing")

    async def test_confirm_all_scopes(self):
        mock_cfg = MagicMock()
        mock_cfg.clear.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "reset_llm_config",
                {"confirm": True},
            )

        assert result["success"] is True
        assert "all scopes" in result["message"]
        mock_cfg.clear.assert_called_once_with(scope=None)
