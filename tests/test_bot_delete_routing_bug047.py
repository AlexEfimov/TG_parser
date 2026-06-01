"""BUG-047 regression suite — deterministic delete-by-name + anaphora routing.

Two production symptoms (both deterministic-routing gaps; the BUG-046
confirm-gate dead-end is ALREADY fixed and must stay intact):

1. Anaphora «удали эту подписку» right after create/show → bot says «Я не
   могу удалить подписку без её ID». No deterministic memory of the
   last-referenced subscription.
2. Bare subscription NAME «Ежечасный дайджест Genotek» → treated as a CHANNEL
   → channel-not-found clarify → «да» yields a SUBSCRIBE preview (create), not
   a delete. No deterministic name→subscription resolver.

The MVP closes them with three pieces (all deterministic, LLM never consulted
on the routing decision):

* B-1 — executor-side owner-scoped name resolver on the unsubscribe tools
  (``subscription_name`` / ``interest_name`` params, exact→casefold→fuzzy
  tiers, owner-scoped fetch, ambiguous→disambiguation clarify, zero→not-found).
* B-2 — a per-chat ``last_subscription`` FSM context (written on create /
  unsubscribe-preview), TTL-governed (15 min), surviving ``state.clear()``.
* B-3 — a ``handle_text`` delete/anaphora pre-router that resolves the target
  deterministically and arms the EXISTING BUG-046 ConfirmFlow preview gate.

These tests are written failing-first (RED on ``712cf00`` before the source
edits). Fakes are mirrored from
``tests/test_bot_unsubscribe_confirm_gate_g1.py`` +
``tests/test_bot_conversation_layer_bug039_042.py``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_bot_confirm_flow import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeDigestSubscriptionRepo,
)
from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
)

from tg_parser.auth.models import CurrentUser  # noqa: E402
from tg_parser.bot.handlers import (  # noqa: E402
    READ_CONTEXT_TTL_SECONDS,
    _handle_clarification_response,
    _handle_confirmation_response,
    handle_text,
)
from tg_parser.bot.states import ClarifyFlow, ConfirmFlow  # noqa: E402
from tg_parser.bot.tools import (  # noqa: E402
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    _exec_unsubscribe_digest,
    _exec_unsubscribe_watchlist,
    execute_tool,
)
from tg_parser.domain.models import (  # noqa: E402
    DigestFormat,
    DigestSubscription,
    NotifyMode,
    WatchInterest,
)
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# New symbols introduced by the BUG-047 fix. Imported defensively so the module
# still COLLECTS against the pre-fix HEAD (each behavioural test then fails on
# its own assertion via the existing entry points rather than erroring at
# import time).
try:  # pragma: no cover — pre-fix self-review branch only
    from tg_parser.bot.tools import _match_subscription_items, resolve_subscription_by_name
except ImportError:  # pragma: no cover
    _match_subscription_items = None  # type: ignore[assignment]
    resolve_subscription_by_name = None  # type: ignore[assignment]

try:  # pragma: no cover
    from tg_parser.bot.states import LastSubscriptionData
except ImportError:  # pragma: no cover
    LastSubscriptionData = None  # type: ignore[assignment]

try:  # pragma: no cover — follow-up fix symbol (fuzzy-suggestion clarify)
    from tg_parser.bot.tools import _build_delete_suggest_clarify
except ImportError:  # pragma: no cover
    _build_delete_suggest_clarify = None  # type: ignore[assignment]


DM_CHAT_ID: int = 700_500_047
SUB_ID: str = "11111111-2222-3333-4444-555555555555"
SUB_ID_2: str = "22222222-3333-4444-5555-666666666666"
INTEREST_ID: str = "99999999-8888-7777-6666-555555555555"
INTEREST_ID_2: str = "88888888-7777-6666-5555-444444444444"

DIGEST_NAME = "Ежечасный дайджест Genotek"
INTEREST_TITLE = "MiCA alerts Genotek"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-047") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="047",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _nonadmin(user_id: str = "user-047") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="047",
        role="user",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _make_state(bot_id: int = 42, chat_id: int = DM_CHAT_ID, user_id: int = 67890) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = DM_CHAT_ID) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


def _sent_text(msg: MagicMock) -> str:
    return " ".join(str(c.args) for c in msg.answer.call_args_list)


def _digest(sub_id: str, name: str, *, owner_id: str = "user-047") -> DigestSubscription:
    return DigestSubscription(
        id=sub_id,
        owner_id=owner_id,
        chat_id=DM_CHAT_ID,
        name=name,
        channel_ids=["genotek"],
        cron_expression="0 * * * *",
        timezone="Europe/Moscow",
        format=DigestFormat.SUMMARY,
        language="ru",
        is_active=True,
    )


def _interest(interest_id: str, title: str, *, user_id: str = "user-047") -> WatchInterest:
    return WatchInterest(
        id=interest_id,
        user_id=user_id,
        chat_id=DM_CHAT_ID,
        title=title,
        description=None,
        keywords=["mica"],
        exclude_keywords=[],
        channel_ids=["genotek"],
        threshold=0.6,
        notify_mode=NotifyMode.INSTANT,
        is_active=True,
        embedding=None,
    )


@asynccontextmanager
async def _digest_repo_ctx(repo: _FakeDigestSubscriptionRepo):
    yield (repo, None)


@asynccontextmanager
async def _watchlist_repos_ctx(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


def _make_watchlist_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


def _routing_patches(
    digest_repo: _FakeDigestSubscriptionRepo,
    ir: _FakeInterestRepo,
    mr: _FakeMatchRepo,
    svc: WatchlistService,
    unregister_spy: MagicMock,
):
    """Patch every repo + the handler-level execute_tool to the REAL one, so a
    pre-router / clarify decision drives the genuine executor end-to-end."""
    return [
        patch(
            "tg_parser.services.db_context.digest_subscription_repo",
            lambda: _digest_repo_ctx(digest_repo),
        ),
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _watchlist_repos_ctx(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            lambda **_kw: svc,
        ),
        patch(
            "tg_parser.services.background_scheduler.unregister_digest_subscription",
            new=unregister_spy,
        ),
        patch("tg_parser.bot.handlers.execute_tool", new=execute_tool),
    ]


def _empty_repos():
    digest_repo = _FakeDigestSubscriptionRepo()
    ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
    svc = _make_watchlist_service(ir, mr)
    return digest_repo, ir, mr, svc, MagicMock()


# ===========================================================================
# 1. Anaphora → last referenced subscription (digest)
# ===========================================================================


@pytest.mark.asyncio
class TestAnaphoraLastSubscriptionDigest:
    async def test_anaphora_arms_unsubscribe_with_stored_id(self):
        """«удали эту подписку» with a non-stale ``last_subscription`` arms
        ConfirmFlow for unsubscribe_digest with the stored id — NO LLM."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await state.update_data(
            last_subscription={
                "id": SUB_ID,
                "kind": "digest",
                "name": DIGEST_NAME,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        msg = _make_message("удали эту подписку")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        # Deterministic: the LLM is never consulted.
        agent.process_message.assert_not_called()
        # ConfirmFlow armed for unsubscribe_digest with the stored id.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
        # The preview names that sub.
        sent = _sent_text(msg)
        assert DIGEST_NAME in sent
        assert "[да/нет]" in sent
        # Nothing deleted yet (preview only).
        assert SUB_ID in digest_repo.store

    async def test_create_then_anaphora_end_to_end(self):
        """A subscribe_digest confirm stores ``last_subscription``; the next-turn
        «удали эту подписку» resolves to it deterministically."""
        # Phase 1 — drive a subscribe_digest confirm via a mocked executor so we
        # don't need the full subscribe side-effects; assert last_subscription
        # is remembered.
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "subscribe_digest",
                "args": {"name": DIGEST_NAME, "channel_ids": ["genotek"]},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(name: str, args: dict, **_kw):
            return {
                "subscription_id": SUB_ID,
                "name": DIGEST_NAME,
                "message": f"✅ Подписка «{DIGEST_NAME}» создана.",
            }

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=_admin())

        data = await state.get_data()
        ls = data.get("last_subscription")
        assert ls is not None, "subscribe_digest confirm must remember last_subscription"
        assert ls["id"] == SUB_ID
        assert ls["kind"] == "digest"


# ===========================================================================
# 2. Bare name → delete preview, NOT subscribe (digest)
# ===========================================================================


@pytest.mark.asyncio
class TestBareNameDeleteNotSubscribe:
    async def test_bare_name_previews_delete(self):
        """«удали Ежечасный дайджест Genotek» (owner has it) → previews a DELETE;
        subscribe_digest is NEVER called and no channel-not-found clarify arms."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        msg = _make_message(f"удали {DIGEST_NAME}")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        # Armed a DELETE preview, not a subscribe / channel clarify.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
        sent = _sent_text(msg)
        assert DIGEST_NAME in sent
        # Not deleted yet (preview), and no subscribe happened.
        assert SUB_ID in digest_repo.store

    async def test_executor_resolves_subscription_name(self):
        """B-1 unit: ``_exec_unsubscribe_digest`` with ``subscription_name`` and
        no id resolves owner-scoped and returns the BUG-046 preview gate."""
        digest_repo = _FakeDigestSubscriptionRepo()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)
        patches = [
            patch(
                "tg_parser.services.db_context.digest_subscription_repo",
                lambda: _digest_repo_ctx(digest_repo),
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_name": DIGEST_NAME},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert result["subscription_id"] == SUB_ID
        assert result.get("user_facing_message") is True
        assert DIGEST_NAME in result["message"]
        assert "[да/нет]" in result["message"]
        # Nothing deleted on the preview turn.
        assert SUB_ID in digest_repo.store

    async def test_executor_case_insensitive_match(self):
        digest_repo = _FakeDigestSubscriptionRepo()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)
        patches = [
            patch(
                "tg_parser.services.db_context.digest_subscription_repo",
                lambda: _digest_repo_ctx(digest_repo),
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_name": DIGEST_NAME.upper()},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result.get("preview") is True
        assert result["subscription_id"] == SUB_ID

    async def test_executor_empty_name_keeps_required_error(self):
        """Empty / whitespace name → no fuzzy match, keep the existing
        ``subscription_id is required`` error (never fuzzy-match empty)."""
        digest_repo = _FakeDigestSubscriptionRepo()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)
        patches = [
            patch(
                "tg_parser.services.db_context.digest_subscription_repo",
                lambda: _digest_repo_ctx(digest_repo),
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_name": "   "},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result.get("preview") is not True
        assert "required" in (result.get("error") or "")


# ===========================================================================
# 3. Disambiguation (2 matches) → delete_disambig clarify
# ===========================================================================


@pytest.mark.asyncio
class TestDisambiguation:
    async def test_two_matches_arm_delete_disambig(self):
        """Two fuzzy-matching subscriptions → a ``delete_disambig`` clarify that
        lists BOTH with their real IDs."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, "Дайджест Genotek утро")
        digest_repo.store[SUB_ID_2] = _digest(SUB_ID_2, "Дайджест Genotek вечер")

        state = _make_state()
        msg = _make_message("удали Дайджест Genotek")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        data = await state.get_data()
        clarify = data["clarify_action"]
        assert clarify["kind"] == "delete_disambig"
        cand_ids = {c["id"] for c in clarify["candidates"]}
        assert cand_ids == {SUB_ID, SUB_ID_2}
        sent = _sent_text(msg)
        assert SUB_ID in sent
        assert SUB_ID_2 in sent

    async def test_disambig_selection_routes_to_right_id(self):
        """A follow-up exact-name selection on the disambig clarify routes to the
        chosen id and arms ConfirmFlow for unsubscribe_digest."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, "Дайджест Genotek утро")
        digest_repo.store[SUB_ID_2] = _digest(SUB_ID_2, "Дайджест Genotek вечер")

        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action={
                "kind": "delete_disambig",
                "requested": "Дайджест Genotek",
                "candidates": [
                    {"id": SUB_ID, "name": "Дайджест Genotek утро", "kind": "digest"},
                    {"id": SUB_ID_2, "name": "Дайджест Genotek вечер", "kind": "digest"},
                ],
                "message": "несколько …",
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("Дайджест Genotek вечер")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await _handle_clarification_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID_2


# ===========================================================================
# 4. Not-found name → not-found (closest miss), FSM not wedged
# ===========================================================================


@pytest.mark.asyncio
class TestNotFound:
    async def test_unknown_name_reports_not_found(self):
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        msg = _make_message("удали Совершенно другая подписка")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        # FSM not wedged into a confirm/clarify state.
        assert await state.get_state() is None
        sent = _sent_text(msg).lower()
        assert "не найдена" in sent or "не найден" in sent
        # Nothing deleted.
        assert SUB_ID in digest_repo.store


# ===========================================================================
# 5. Watchlist parity (anaphora, bare name, disambiguation, not-found)
# ===========================================================================


@pytest.mark.asyncio
class TestWatchlistParity:
    async def test_anaphora_arms_unsubscribe_watchlist(self):
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        ir.store[INTEREST_ID] = _interest(INTEREST_ID, INTEREST_TITLE)

        state = _make_state()
        await state.update_data(
            last_subscription={
                "id": INTEREST_ID,
                "kind": "watchlist",
                "name": INTEREST_TITLE,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        msg = _make_message("удали этот watchlist")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_watchlist"
        assert data["pending_action"]["args"]["interest_id"] == INTEREST_ID

    async def test_bare_name_previews_watchlist_delete(self):
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        ir.store[INTEREST_ID] = _interest(INTEREST_ID, INTEREST_TITLE)

        state = _make_state()
        msg = _make_message(f"удали {INTEREST_TITLE}")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_watchlist"
        assert data["pending_action"]["args"]["interest_id"] == INTEREST_ID

    async def test_executor_resolves_interest_name(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        ir.store[INTEREST_ID] = _interest(INTEREST_ID, INTEREST_TITLE)
        svc = _make_watchlist_service(ir, mr)
        patches = [
            patch(
                "tg_parser.services.db_context.watchlist_repos",
                lambda: _watchlist_repos_ctx(ir, mr),
            ),
            patch(
                "tg_parser.services.watchlist_service.make_watchlist_service",
                lambda **_kw: svc,
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_name": INTEREST_TITLE},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result.get("preview") is True
        assert result["interest_id"] == INTEREST_ID
        assert INTEREST_TITLE in result["message"]
        assert ir.store[INTEREST_ID].is_active is True

    async def test_watchlist_not_found(self):
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        ir.store[INTEREST_ID] = _interest(INTEREST_ID, INTEREST_TITLE)

        state = _make_state()
        msg = _make_message("удали Совершенно другой алерт")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() is None
        assert ir.store[INTEREST_ID].is_active is True


# ===========================================================================
# 6. RBAC owner-scoping
# ===========================================================================


@pytest.mark.asyncio
class TestRbacOwnerScoping:
    async def test_nonadmin_cannot_resolve_other_owner_sub(self):
        """A non-admin cannot resolve ANOTHER owner's subscription by name."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME, owner_id="someone-else")

        state = _make_state()
        msg = _make_message(f"удали {DIGEST_NAME}")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_nonadmin("me-not-owner"))
        finally:
            _exit_all(patches)

        # Owner-scoped resolution returns not-found (existence not leaked) — no
        # delete preview armed, nothing deleted, LLM not consulted.
        agent.process_message.assert_not_called()
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state
        assert SUB_ID in digest_repo.store

    async def test_admin_resolves_any_sub_via_list_all(self):
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME, owner_id="someone-else")

        state = _make_state()
        msg = _make_message(f"удали {DIGEST_NAME}")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin("admin-x"))
        finally:
            _exit_all(patches)

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID


# ===========================================================================
# 7. TTL: stale last_subscription → anaphora falls through (no false delete)
# ===========================================================================


@pytest.mark.asyncio
class TestAnaphoraTtl:
    async def test_stale_last_subscription_falls_through_to_agent(self):
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        stale = datetime.now(UTC) - timedelta(seconds=READ_CONTEXT_TTL_SECONDS + 60)
        await state.update_data(
            last_subscription={
                "id": SUB_ID,
                "kind": "digest",
                "name": DIGEST_NAME,
                "created_at": stale.isoformat(),
            }
        )
        msg = _make_message("удали эту подписку")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=__import__("tg_parser.bot.agent", fromlist=["AgentResult"]).AgentResult(
                response_text="ok"
            )
        )

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        # Stale anaphora → the deterministic delete must NOT fire; the agent
        # path handles it and nothing is deleted.
        agent.process_message.assert_called_once()
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state
        assert SUB_ID in digest_repo.store


# ===========================================================================
# 8. Regression guards — channel ops + read clarify untouched by the pre-router
# ===========================================================================


@pytest.mark.asyncio
class TestRegressionGuards:
    async def test_remove_channel_phrasing_falls_through_to_agent(self):
        """«удали канал X» is a CHANNEL op — the subscription pre-router must NOT
        hijack it (remove_channel stays on the agent path)."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        msg = _make_message("удали канал old_channel")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=__import__("tg_parser.bot.agent", fromlist=["AgentResult"]).AgentResult(
                response_text="ok"
            )
        )

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_called_once()

    async def test_non_delete_question_falls_through_to_agent(self):
        """A normal Q&A turn (no delete verb / anaphora) is untouched."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        msg = _make_message("что известно про APOE?")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=__import__("tg_parser.bot.agent", fromlist=["AgentResult"]).AgentResult(
                response_text="ok"
            )
        )

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_called_once()


# ===========================================================================
# 9. Contract guards — confirm-set membership intact (BUG-046 / BUG-009)
# ===========================================================================


class TestConfirmContractIntact:
    def test_unsubscribe_tools_still_in_guard_set(self) -> None:
        assert "unsubscribe_digest" in _WRITE_TOOLS_REQUIRING_CONFIRM
        assert "unsubscribe_watchlist" in _WRITE_TOOLS_REQUIRING_CONFIRM


# ===========================================================================
# 10. Name-resolver tiers (direct unit) — guarded behind the new symbol
# ===========================================================================


@pytest.mark.skipif(_match_subscription_items is None, reason="resolver not implemented yet")
class TestMatchTiersUnit:
    def test_exact_single(self) -> None:
        items = [{"id": "a", "name": "Genotek утро", "kind": "digest"}]
        r = _match_subscription_items("Genotek утро", items)
        assert r["status"] == "resolved"
        assert r["id"] == "a"

    def test_casefold_single(self) -> None:
        items = [{"id": "a", "name": "Genotek Утро", "kind": "digest"}]
        r = _match_subscription_items("genotek утро", items)
        assert r["status"] == "resolved"

    def test_ambiguous_multiple(self) -> None:
        items = [
            {"id": "a", "name": "Genotek утро", "kind": "digest"},
            {"id": "b", "name": "Genotek вечер", "kind": "digest"},
        ]
        r = _match_subscription_items("Genotek", items)
        assert r["status"] == "ambiguous"
        assert len(r["candidates"]) == 2

    def test_empty_is_not_found(self) -> None:
        items = [{"id": "a", "name": "Genotek", "kind": "digest"}]
        r = _match_subscription_items("   ", items)
        assert r["status"] == "not_found"

    def test_single_fuzzy_suggestion_is_suggest(self) -> None:
        """A bare token that is a substring of one subscription name (below the
        auto-resolve cutoff) must surface as ``suggest`` (single candidate),
        NOT a bare ``not_found`` — this is the G1-class dead-end fix."""
        items = [{"id": "a", "name": "Ежечасный дайджест Genotek", "kind": "digest"}]
        r = _match_subscription_items("Genotek", items)
        assert r["status"] == "suggest"
        assert r["suggestion"]["id"] == "a"
        assert r["suggestion"]["kind"] == "digest"

    def test_no_suggestion_below_cutoff_is_not_found(self) -> None:
        """A genuinely unrelated name → plain ``not_found`` (FSM stays inert)."""
        items = [{"id": "a", "name": "Ежечасный дайджест Genotek", "kind": "digest"}]
        r = _match_subscription_items("Совершенно другая подписка", items)
        assert r["status"] == "not_found"


# ===========================================================================
# 11. Fuzzy-suggestion clarify (BUG-047 follow-up: close the «да» dead-end on
#     the not-found-with-suggestion path — arm a deterministic clarify FSM)
# ===========================================================================


@pytest.mark.asyncio
class TestFuzzySuggestionClarify:
    async def test_prerouter_single_suggestion_arms_clarify(self):
        """«удали Genotek» (a single fuzzy/substring suggestion, no exact match)
        must ARM a ``delete_suggest`` clarify FSM — not emit a bare message."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        msg = _make_message("удали Genotek")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        # A clarify FSM is ARMED (not a stateless message).
        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        data = await state.get_data()
        clarify = data["clarify_action"]
        assert clarify["kind"] == "delete_suggest"
        assert clarify["suggestion"]["id"] == SUB_ID
        # The suggested name is surfaced to the user.
        assert DIGEST_NAME in _sent_text(msg)
        # Nothing deleted.
        assert SUB_ID in digest_repo.store

    async def test_suggestion_da_routes_to_delete_preview_then_deletes(self):
        """«да» on the suggestion → delete CONFIRM PREVIEW (NOT an immediate
        delete: BUG-009/BUG-046 contract). A SECOND «да» then deletes."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action={
                "kind": "delete_suggest",
                "requested": "Genotek",
                "suggestion": {"id": SUB_ID, "name": DIGEST_NAME, "kind": "digest"},
                "message": "Возможно, вы имели в виду …?",
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            # First «да» → must arm the confirm PREVIEW, NOT delete.
            msg1 = _make_message("да")
            await _handle_clarification_response(msg1, agent, state, current_user=_admin())
            agent.process_message.assert_not_called()
            assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
            data = await state.get_data()
            assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
            assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
            assert SUB_ID in digest_repo.store  # NOT deleted yet
            assert "[да/нет]" in _sent_text(msg1)

            # Second «да» → confirm → actually deletes.
            msg2 = _make_message("да")
            await _handle_confirmation_response(msg2, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)

        assert SUB_ID not in digest_repo.store

    async def test_executor_digest_suggestion_returns_clarify_pending(self):
        """B-1: ``_exec_unsubscribe_digest`` with a fuzzy-suggestion name returns
        a ``delete_suggest`` clarify_pending (NOT a bare not-found error, NOT a
        delete) so the LLM/agent path arms the clarify FSM."""
        digest_repo = _FakeDigestSubscriptionRepo()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)
        patches = [
            patch(
                "tg_parser.services.db_context.digest_subscription_repo",
                lambda: _digest_repo_ctx(digest_repo),
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_name": "Genotek"},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is not True
        clarify = result.get("clarify_pending")
        assert isinstance(clarify, dict)
        assert clarify["kind"] == "delete_suggest"
        assert clarify["suggestion"]["id"] == SUB_ID
        assert SUB_ID in digest_repo.store  # nothing deleted

    async def test_executor_watchlist_suggestion_returns_clarify_pending(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        ir.store[INTEREST_ID] = _interest(INTEREST_ID, INTEREST_TITLE)
        svc = _make_watchlist_service(ir, mr)
        patches = [
            patch(
                "tg_parser.services.db_context.watchlist_repos",
                lambda: _watchlist_repos_ctx(ir, mr),
            ),
            patch(
                "tg_parser.services.watchlist_service.make_watchlist_service",
                lambda **_kw: svc,
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_name": "Genotek"},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is not True
        clarify = result.get("clarify_pending")
        assert isinstance(clarify, dict)
        assert clarify["kind"] == "delete_suggest"
        assert clarify["suggestion"]["id"] == INTEREST_ID
        assert ir.store[INTEREST_ID].is_active is True  # nothing deleted

    async def test_zero_match_stray_da_is_inert(self):
        """ZERO match + NO suggestion → plain not-found, FSM not armed; a stray
        «да» afterwards does NOT delete anything (falls through to the agent)."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            msg = _make_message("удали Совершенно другая подписка")
            agent = MagicMock()
            agent.process_message = AsyncMock()
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
            # not-found, FSM inert
            assert await state.get_state() is None
            agent.process_message.assert_not_called()

            # Stray «да» → no armed FSM, must not delete; routed to the agent.
            msg2 = _make_message("да")
            agent.process_message = AsyncMock(
                return_value=__import__(
                    "tg_parser.bot.agent", fromlist=["AgentResult"]
                ).AgentResult(response_text="ok")
            )
            await handle_text(msg2, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        assert SUB_ID in digest_repo.store

    async def test_suggestion_another_name_near_miss_rearms_and_da_previews(self):
        """D1 (BUG-047) — the failing-first guard.

        On a ``delete_suggest`` clarify, a DIFFERENT reply that the FIRST
        (pre-router) pass would resolve must follow the SAME path: a
        noun-connector name («подписку Genotek») is sliced (noun stripped →
        «Genotek» → a single near-miss / substring of ``DIGEST_NAME``), so the
        repeat pass must RE-ARM ``delete_suggest`` AND a following «да» must
        reach the confirm-preview gate — never the opaque LLM fallback.

        Pre-fix the repeat resolve fed the WHOLE reply to the resolver verbatim
        — no verb / connector-noun candidate slicing like the pre-router does —
        so «подписку Genotek» fell to an FSM-less not-found («… Ближайшее
        совпадение: X») and the next «да» dead-ended (G1-class). The first
        (pre-router) pass armed; the repeat pass did not. THAT asymmetry is D1.
        """
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action={
                "kind": "delete_suggest",
                "requested": "Genotk",
                "suggestion": {"id": SUB_ID, "name": DIGEST_NAME, "kind": "digest"},
                "message": "Возможно, вы имели в виду …?",
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            # A noun-connector "another name" reply — the pre-router strips the
            # leading «подписку» → «Genotek» (a single near-miss / substring of
            # DIGEST_NAME). The repeat pass MUST do the same.
            msg1 = _make_message("подписку Genotek")
            await _handle_clarification_response(msg1, agent, state, current_user=_admin())
            agent.process_message.assert_not_called()
            # FSM must be RE-ARMED as a delete_suggest pointing at the sub.
            assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
            data = await state.get_data()
            clarify = data["clarify_action"]
            assert clarify["kind"] == "delete_suggest"
            assert clarify["suggestion"]["id"] == SUB_ID
            assert DIGEST_NAME in _sent_text(msg1)

            # The following «да» must reach the confirm PREVIEW, not the fallback.
            msg2 = _make_message("да")
            await _handle_clarification_response(msg2, agent, state, current_user=_admin())
            agent.process_message.assert_not_called()
            assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
            data = await state.get_data()
            assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
            assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
            assert SUB_ID in digest_repo.store  # nothing deleted yet
        finally:
            _exit_all(patches)

    async def test_suggestion_zero_match_stray_da_is_inert(self):
        """D1 (BUG-047): on a ``delete_suggest`` clarify, a DIFFERENT name with
        ZERO real match (no near-miss) must clear the FSM (snapshot-restore of
        read_context / last_subscription) so a stray «да» afterwards is inert —
        it never fires a false delete and never wedges a confirm/clarify."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action={
                "kind": "delete_suggest",
                "requested": "Genotek",
                "suggestion": {"id": SUB_ID, "name": DIGEST_NAME, "kind": "digest"},
                "message": "Возможно, вы имели в виду …?",
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            # An unrelated token with no near-miss → clean not-found, FSM cleared.
            msg1 = _make_message("hh")
            await _handle_clarification_response(msg1, agent, state, current_user=_admin())
            agent.process_message.assert_not_called()
            assert await state.get_state() is None
            # D1 Symptom A: the rendered not-found must be CLEAN — a sub-threshold
            # nearest name must NOT be surfaced as an (inactive) actionable hint.
            sent1 = _sent_text(msg1)
            assert "не найдена" in sent1.lower()
            assert "Ближайшее совпадение" not in sent1

            # Stray «да» → no armed FSM; routed to the agent, never a delete.
            msg2 = _make_message("да")
            agent.process_message = AsyncMock(
                return_value=__import__(
                    "tg_parser.bot.agent", fromlist=["AgentResult"]
                ).AgentResult(response_text="ok")
            )
            await handle_text(msg2, agent=agent, state=state, current_user=_admin())
            agent.process_message.assert_called_once()
        finally:
            _exit_all(patches)

        assert SUB_ID in digest_repo.store

    async def test_suggestion_different_name_reresolves(self):
        """On a ``delete_suggest`` clarify, a DIFFERENT name (not «да»/«нет»)
        re-resolves: an exact name routes straight to the delete preview."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action={
                "kind": "delete_suggest",
                "requested": "Genotek",
                "suggestion": {"id": SUB_ID, "name": DIGEST_NAME, "kind": "digest"},
                "message": "Возможно, вы имели в виду …?",
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(DIGEST_NAME)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await _handle_clarification_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
