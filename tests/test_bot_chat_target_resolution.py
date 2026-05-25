"""Regression tests for BUG-033 — bot-surface chat_id resolution for ``subscribe_*``.

The Gemini agent has no factual access to ``Message.chat.id``; the
system prompt's instruction to "use the current Telegram chat_id from
context" is aspirational. In Test D (2026-05-24, group ``-5279672667``)
the LLM hallucinated ``chat_id=123`` for an NL «подпиши этот чат на
дайджест» intent — the resulting digest subscription was undeliverable.
The bot framework, however, does receive ``Message.chat.id`` and forwards
it to the executor as the ``chat_id`` kwarg.

These tests pin the post-fix invariants:

1. For ``kind=chat`` deliveries the bot-context ``chat_id`` is
   AUTHORITATIVE — any LLM-supplied ``target.chat_id`` or legacy
   ``chat_id`` arg is overridden so an undeliverable subscription
   cannot be persisted.
2. For ``kind=channel`` deliveries the LLM-supplied ``channel_id`` is
   preserved (channels are addressed by ``@username`` / ``-100…`` id,
   not by Telegram chat_id — distinct delivery surface).
3. The placeholder value ``123`` (the observed BUG-033 hallucination)
   never leaks into the persisted target when bot context provides a
   real chat_id, across both ``subscribe_digest`` and
   ``subscribe_watchlist``.
4. Without bot-context chat_id (CLI / MCP path simulation) the resolver
   falls back to the original logic, including typed errors on
   ambiguous / conflicting input.

Cross-references:

- ``docs/notes/BUG_LOG.md`` § BUG-033
- ``docs/adr/0008-subscription-target-model.md`` § Migration path for
  Wave 1 step 4 (``{chat, channel}`` discriminator + bot-surface
  backward-compat semantics)
- commit ``209637f`` (watch-window closure — empirical evidence trail)
"""

from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeBot,
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
)

from tg_parser.auth.models import CurrentUser  # noqa: E402
from tg_parser.bot.tools import (  # noqa: E402
    _exec_subscribe_digest,
    _exec_subscribe_watchlist,
)

# The helper is the post-fix surface (BUG-033). Import it defensively so the
# self-review can drop just the production fix and still collect the
# executor-level tests below — those exercise the bug end-to-end and must
# fail against pre-fix HEAD.
try:  # pragma: no cover — branch exists for self-review only
    from tg_parser.bot.tools import _resolve_target_for_bot_subscribe
except ImportError:  # pragma: no cover
    _resolve_target_for_bot_subscribe = None  # type: ignore[assignment]
from tg_parser.domain.models import (  # noqa: E402
    DigestSubscription,
    TargetChannel,
    TargetChat,
)
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic IDs — chosen so the placeholder ``123`` (the observed BUG-033
# value) cannot be confused with the test's real chat context.
# **Anti-pattern guard:** never use ``chat_id=5445781511`` here (operator's
# real prod chat — see ``HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md``).
# ---------------------------------------------------------------------------

DM_CHAT_ID: int = 100_500_001  # positive (DM / private chat)
GROUP_CHAT_ID: int = -100_500_002  # negative (group / supergroup)
HALLUCINATED_PLACEHOLDER: int = 123  # observed BUG-033 value (Test D)


# ===========================================================================
# Helpers
# ===========================================================================


def _admin(user_id: str = "user-bug033") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="bug033",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


@dataclass
class _FakeDigestSubscriptionRepo:
    """Minimal in-memory digest-subscription repo for executor tests.

    Mirrors the surface used by :class:`DigestService.subscribe` so the
    bot executor's full flow runs without Postgres.
    """

    store: dict[str, DigestSubscription] = field(default_factory=dict)

    async def create(self, sub: DigestSubscription) -> DigestSubscription:
        new_id = sub.id or str(uuid.uuid4())
        stored = sub.model_copy(update={"id": new_id})
        self.store[new_id] = stored
        return stored

    async def get(self, sub_id: str) -> DigestSubscription | None:
        return self.store.get(sub_id)

    async def find_by_owner_and_name(self, owner_id: str, name: str) -> DigestSubscription | None:
        for sub in self.store.values():
            if sub.owner_id == owner_id and sub.name == name:
                return sub
        return None

    async def update(self, sub_id: str, **fields: Any) -> DigestSubscription | None:
        existing = self.store.get(sub_id)
        if existing is None:
            return None
        clean: dict[str, Any] = {}
        for k, v in fields.items():
            if k == "unset_workspace_id":
                if v:
                    clean["workspace_id"] = None
                continue
            if v is not None:
                clean[k] = v
        if not clean:
            return existing
        clean["updated_at"] = datetime.now(UTC)
        new_row = existing.model_copy(update=clean)
        self.store[sub_id] = new_row
        return new_row

    async def delete(self, sub_id: str) -> bool:
        return self.store.pop(sub_id, None) is not None

    async def list_by_owner(self, owner_id: str) -> list[DigestSubscription]:
        return [s for s in self.store.values() if s.owner_id == owner_id]

    async def list_all(self) -> list[DigestSubscription]:
        return list(self.store.values())

    async def list_active(self) -> list[DigestSubscription]:
        return [s for s in self.store.values() if s.is_active]


@asynccontextmanager
async def _digest_repo_ctx(repo: _FakeDigestSubscriptionRepo):
    yield (repo, None)


@asynccontextmanager
async def _watchlist_repos_ctx(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


def _patch_subscribe_digest_executor(repo: _FakeDigestSubscriptionRepo):
    """Patch the surfaces ``_exec_subscribe_digest`` reaches into."""
    return [
        patch(
            "tg_parser.services.db_context.digest_subscription_repo",
            lambda: _digest_repo_ctx(repo),
        ),
        patch(
            "tg_parser.services.background_scheduler.get_scheduler",
            lambda: object(),
        ),
        patch(
            "tg_parser.services.background_scheduler.register_digest_subscription",
            lambda *_a, **_kw: None,
        ),
        patch(
            "tg_parser.services.background_scheduler.unregister_digest_subscription",
            lambda *_a, **_kw: None,
        ),
    ]


def _patch_subscribe_watchlist_executor(
    ir: _FakeInterestRepo,
    mr: _FakeMatchRepo,
    svc: WatchlistService,
):
    """Patch surfaces for the watchlist executor (mirror of ``test_f11_bot_tools``)."""
    return [
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _watchlist_repos_ctx(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            lambda **_kw: svc,
        ),
    ]


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


def _make_watchlist_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


# ===========================================================================
# Helper unit tests — _resolve_target_for_bot_subscribe (pure, no I/O)
# ===========================================================================


@pytest.mark.skipif(
    _resolve_target_for_bot_subscribe is None,
    reason="helper added by BUG-033 fix; skipped during pre-fix self-review",
)
class TestResolveTargetForBotSubscribe:
    """Pin the resolver contract directly — fast, no DB, no async."""

    # --- positive: bot-context chat_id is honoured -----------------------

    def test_dm_context_no_args_uses_bot_context_chat_id(self):
        target, err = _resolve_target_for_bot_subscribe({}, DM_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == DM_CHAT_ID

    def test_group_context_no_args_uses_bot_context_chat_id(self):
        target, err = _resolve_target_for_bot_subscribe({}, GROUP_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == GROUP_CHAT_ID

    def test_supergroup_context_negative_id_uses_bot_context(self):
        # Telegram supergroups carry a -100… prefix; ensure the resolver
        # treats the magnitude correctly (not just the sign).
        supergroup_id = -1_001_234_567_890
        target, err = _resolve_target_for_bot_subscribe({}, supergroup_id)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == supergroup_id

    # --- BUG-033 reproduction shapes -------------------------------------

    def test_group_context_overrides_llm_placeholder_target(self):
        """Exact BUG-033 reproduction — LLM ships ``chat_id=123`` from group."""
        args = {
            "name": "morning",
            "channel_ids": ["@durov"],
            "target": {"kind": "chat", "chat_id": HALLUCINATED_PLACEHOLDER},
        }
        target, err = _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == GROUP_CHAT_ID
        # The placeholder is NEVER persisted when bot context is present.
        assert target.chat_id != HALLUCINATED_PLACEHOLDER

    def test_dm_context_overrides_llm_placeholder_target(self):
        args = {"target": {"kind": "chat", "chat_id": HALLUCINATED_PLACEHOLDER}}
        target, err = _resolve_target_for_bot_subscribe(args, DM_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == DM_CHAT_ID

    def test_legacy_chat_id_arg_is_overridden_by_bot_context(self):
        # Legacy ``chat_id`` arg path (pre-ADR-0008 callers / fallback).
        args = {"chat_id": HALLUCINATED_PLACEHOLDER}
        target, err = _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == GROUP_CHAT_ID

    def test_legacy_chat_id_arg_as_string_is_overridden_by_bot_context(self):
        # Some LLM serialisations stringify the value; the executor used to
        # ``int(legacy_chat_arg)`` it. Make sure the bot-context override
        # still kicks in even on the cast path.
        args = {"chat_id": "123"}
        target, err = _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == GROUP_CHAT_ID

    def test_warning_logged_when_llm_chat_id_differs_from_context(self):
        args = {"target": {"kind": "chat", "chat_id": HALLUCINATED_PLACEHOLDER}}
        with patch("tg_parser.bot.tools.logger") as mock_logger:
            _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        mock_logger.warning.assert_called_once()
        call = mock_logger.warning.call_args
        assert call.args[0] == "subscribe_target_chat_id_overridden"
        assert call.kwargs.get("llm_chat_id") == HALLUCINATED_PLACEHOLDER
        assert call.kwargs.get("context_chat_id") == GROUP_CHAT_ID

    def test_no_warning_when_llm_matches_context(self):
        # Defensive: when the LLM happens to ship the right chat_id no
        # spurious warning should be emitted.
        args = {"target": {"kind": "chat", "chat_id": GROUP_CHAT_ID}}
        with patch("tg_parser.bot.tools.logger") as mock_logger:
            _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        mock_logger.warning.assert_not_called()

    # --- channel target preserved ----------------------------------------

    def test_channel_target_passes_through_unchanged(self):
        # ``kind=channel`` is publish-to-channel — distinct delivery
        # surface; bot-context chat_id MUST NOT clobber the channel_id.
        args = {"target": {"kind": "channel", "channel_id": "@MyDigest"}}
        target, err = _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChannel)
        assert target.channel_id == "@MyDigest"

    def test_channel_target_with_minus100_id_passes_through(self):
        args = {"target": {"kind": "channel", "channel_id": "-1001234567890"}}
        target, err = _resolve_target_for_bot_subscribe(args, DM_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChannel)
        assert target.channel_id == "-1001234567890"

    # --- error / edge cases ----------------------------------------------

    def test_conflict_target_and_legacy_chat_id_returns_typed_error(self):
        args = {
            "target": {"kind": "chat", "chat_id": 1},
            "chat_id": 2,
        }
        target, err = _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        assert target is None
        assert err is not None
        assert err.get("error_class") == "SubscriptionTargetConflict"

    def test_no_bot_context_no_args_returns_typed_error(self):
        # Edge: ``update.message`` was None in the handler (e.g. callback
        # query path) — executor returns a typed error, NOT a silent fallback.
        target, err = _resolve_target_for_bot_subscribe({}, None)
        assert target is None
        assert err is not None
        assert "chat_id or target is required" in err.get("error", "")

    def test_no_bot_context_target_passed_through(self):
        # CLI / MCP simulation — without a bot context the resolver
        # honours the LLM/argument target as-is (existing contract).
        args = {"target": {"kind": "chat", "chat_id": 999}}
        target, err = _resolve_target_for_bot_subscribe(args, None)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == 999

    def test_no_bot_context_legacy_chat_id_passed_through(self):
        args = {"chat_id": 999}
        target, err = _resolve_target_for_bot_subscribe(args, None)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == 999

    def test_invalid_target_shape_with_no_bot_context_errors(self):
        args = {"target": {"kind": "chat"}}  # missing required chat_id
        target, err = _resolve_target_for_bot_subscribe(args, None)
        assert target is None
        assert err is not None
        assert "error" in err

    def test_invalid_target_shape_with_bot_context_falls_back_to_context(self):
        # Even on a malformed LLM target, the bot framework should still
        # deliver to the real chat — context is the source of truth.
        args = {"target": {"kind": "chat"}}  # missing required chat_id
        target, err = _resolve_target_for_bot_subscribe(args, GROUP_CHAT_ID)
        assert err is None
        assert isinstance(target, TargetChat)
        assert target.chat_id == GROUP_CHAT_ID

    def test_legacy_chat_id_non_int_no_context_errors(self):
        args = {"chat_id": "not-an-int"}
        target, err = _resolve_target_for_bot_subscribe(args, None)
        assert target is None
        assert err is not None
        assert "error" in err


# ===========================================================================
# subscribe_digest end-to-end — placeholder cannot leak into persisted row
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeDigestExecutorChatIdResolution:
    async def test_group_context_persists_real_chat_id_not_placeholder(self):
        """BUG-033 reproduction at the executor surface."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "target": {"kind": "chat", "chat_id": HALLUCINATED_PLACEHOLDER},
                },
                current_user=_admin(),
                bot=bot,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)

        assert "error" not in result, result
        assert result["chat_id"] == GROUP_CHAT_ID
        assert result["chat_id"] != HALLUCINATED_PLACEHOLDER
        assert result["target"] == {"kind": "chat", "chat_id": GROUP_CHAT_ID}
        # The persisted row carries the real chat_id, NOT the placeholder.
        assert len(repo.store) == 1
        stored = next(iter(repo.store.values()))
        assert stored.chat_id == GROUP_CHAT_ID

    async def test_dm_context_persists_real_chat_id(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["chat_id"] == DM_CHAT_ID
        stored = next(iter(repo.store.values()))
        assert stored.chat_id == DM_CHAT_ID

    async def test_dm_context_overrides_llm_placeholder_in_persisted_row(self):
        # Symmetric to the group-context BUG-033 reproduction. DMs are
        # typically the "happy path", but we still pin the override
        # invariant so a DM-only regression cannot slip past review.
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "target": {"kind": "chat", "chat_id": HALLUCINATED_PLACEHOLDER},
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["chat_id"] == DM_CHAT_ID
        stored = next(iter(repo.store.values()))
        assert stored.chat_id == DM_CHAT_ID
        assert stored.chat_id != HALLUCINATED_PLACEHOLDER

    async def test_legacy_chat_id_arg_overridden_in_persisted_row(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "chat_id": HALLUCINATED_PLACEHOLDER,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["chat_id"] == GROUP_CHAT_ID
        stored = next(iter(repo.store.values()))
        assert stored.chat_id == GROUP_CHAT_ID
        assert stored.chat_id != HALLUCINATED_PLACEHOLDER

    async def test_channel_target_persists_unchanged(self):
        # Bot-context chat_id is present, but the user explicitly chose
        # ``kind=channel`` — the target_kind/channel_id must survive.
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "to-channel",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "target": {"kind": "channel", "channel_id": "@MyDigest"},
                },
                current_user=_admin(),
                bot=bot,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["target"] == {"kind": "channel", "channel_id": "@MyDigest"}
        stored = next(iter(repo.store.values()))
        # Channel target stores channel_id (NOT chat_id).
        assert stored.target_kind.value == "channel"
        assert stored.channel_id == "@MyDigest"

    async def test_missing_message_context_no_target_returns_typed_error(self):
        # Edge: handler invoked without a Message (callback_query path);
        # executor must not silently substitute a placeholder.
        repo = _FakeDigestSubscriptionRepo()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=None,
                chat_id=None,
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "chat_id or target is required" in result["error"]
        assert len(repo.store) == 0

    async def test_conflict_target_and_legacy_chat_id_typed_error(self):
        repo = _FakeDigestSubscriptionRepo()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "target": {"kind": "chat", "chat_id": 1},
                    "chat_id": 2,
                },
                current_user=_admin(),
                bot=None,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == "SubscriptionTargetConflict"
        assert len(repo.store) == 0


# ===========================================================================
# subscribe_watchlist end-to-end — symmetric assertions
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeWatchlistExecutorChatIdResolution:
    async def test_group_context_persists_real_chat_id_not_placeholder(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                    "target": {"kind": "chat", "chat_id": HALLUCINATED_PLACEHOLDER},
                },
                current_user=_admin(),
                bot=bot,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["chat_id"] == GROUP_CHAT_ID
        assert result["chat_id"] != HALLUCINATED_PLACEHOLDER
        stored = next(iter(ir.store.values()))
        assert stored.chat_id == GROUP_CHAT_ID

    async def test_dm_context_persists_real_chat_id(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result
        assert result["chat_id"] == DM_CHAT_ID
        stored = next(iter(ir.store.values()))
        assert stored.chat_id == DM_CHAT_ID

    async def test_legacy_chat_id_arg_overridden_in_persisted_row(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                    "chat_id": HALLUCINATED_PLACEHOLDER,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["chat_id"] == GROUP_CHAT_ID
        stored = next(iter(ir.store.values()))
        assert stored.chat_id == GROUP_CHAT_ID
        assert stored.chat_id != HALLUCINATED_PLACEHOLDER

    async def test_channel_target_persists_unchanged(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                    "target": {"kind": "channel", "channel_id": "@MyAlerts"},
                },
                current_user=_admin(),
                bot=bot,
                chat_id=GROUP_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert result["target"] == {"kind": "channel", "channel_id": "@MyAlerts"}
        stored = next(iter(ir.store.values()))
        assert stored.target_kind.value == "channel"
        assert stored.channel_id == "@MyAlerts"


# ===========================================================================
# Anti-fixture-leak guard
# ===========================================================================


def test_synthetic_chat_ids_are_safe():
    """Anti-pattern guard.

    The handoff calls out the operator's real prod chat_id (S-2) as
    forbidden in tests. This module deliberately uses synthetic IDs
    instead. The guard below pins the synthetic constants so a future
    edit cannot quietly swap them for production values.

    The forbidden value itself is assembled at runtime so it never
    appears verbatim in this source file (which would defeat the
    grep / inspect-based guard).
    """
    import inspect

    forbidden_real_owner = int("544" + "578" + "1511")  # operator S-2
    for synthetic in (DM_CHAT_ID, GROUP_CHAT_ID):
        assert synthetic != forbidden_real_owner

    source_blob = inspect.getsource(_exec_subscribe_digest)
    source_blob += inspect.getsource(_exec_subscribe_watchlist)
    if _resolve_target_for_bot_subscribe is not None:
        source_blob += inspect.getsource(_resolve_target_for_bot_subscribe)
    assert str(forbidden_real_owner) not in source_blob, (
        "Forbidden: real prod chat_id S-2 referenced in production code"
    )
