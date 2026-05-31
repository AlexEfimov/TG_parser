"""G1 / BUG-046 regression suite — unsubscribe_* two-phase confirm gate.

Defect G1 (top user-facing defect after PR #158 merged at ``a1dd040``):
the delete / unsubscribe confirmation «да» / «yes» dead-ended on the
opaque «Я не совсем понимаю ваш ответ» fallback.

Root cause: ``unsubscribe_digest`` / ``unsubscribe_watchlist`` were NOT
part of the deterministic two-phase preview/confirm contract — they had
no ``confirm`` parameter, no preview gate, and were absent from
``_WRITE_TOOLS_REQUIRING_CONFIRM``. The LLM therefore volunteered an
ad-hoc confirmation sentence («Подписка "…" (ID: …) будет удалена.
Подтвердите [да/нет]») that never armed ``ConfirmFlow``; the follow-up
«да» hit ``current_state is None``, routed to a memoryless LLM turn, and
yielded the opaque fallback.

This module pins the fix (symmetric with the BUG-031 ``subscribe_*``
gate in ``tests/test_bot_confirm_flow.py``):

1. ``_exec_unsubscribe_digest`` / ``_exec_unsubscribe_watchlist`` return
   ``{"preview": True, "user_facing_message": True, "message": "…[да/нет]"}``
   and DO NOT delete when ``confirm`` is not truthy. The preview message
   NAMES the subscription / interest and shows its real ID.
2. The deterministic ``ConfirmFlow`` confirm-turn replays the call with
   ``confirm=True`` → the deletion actually happens. Covered for «да»
   AND «yes»; «нет» cancels with no deletion.
3. Both tools are present in ``_WRITE_TOOLS_REQUIRING_CONFIRM``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
    _handle_confirmation_response,
)
from tg_parser.bot.states import ConfirmFlow  # noqa: E402
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

DM_CHAT_ID: int = 700_500_001
SUB_ID: str = "11111111-2222-3333-4444-555555555555"
INTEREST_ID: str = "99999999-8888-7777-6666-555555555555"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-g1") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="g1",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _make_state(bot_id: int = 42, chat_id: int = 12345, user_id: int = 67890) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = 12345) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


def _seed_digest(repo: _FakeDigestSubscriptionRepo, *, owner_id: str = "user-g1") -> None:
    repo.store[SUB_ID] = DigestSubscription(
        id=SUB_ID,
        owner_id=owner_id,
        chat_id=DM_CHAT_ID,
        name="Ежечасный дайджест",
        channel_ids=["durov"],
        cron_expression="0 * * * *",
        timezone="Europe/Moscow",
        format=DigestFormat.SUMMARY,
        language="ru",
        is_active=True,
    )


def _seed_interest(repo: _FakeInterestRepo, *, user_id: str = "user-g1") -> None:
    repo.store[INTEREST_ID] = WatchInterest(
        id=INTEREST_ID,
        user_id=user_id,
        chat_id=DM_CHAT_ID,
        title="MiCA alerts",
        description=None,
        keywords=["mica"],
        exclude_keywords=[],
        channel_ids=["crypto_news"],
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


def _patch_unsubscribe_digest_executor(repo: _FakeDigestSubscriptionRepo, unregister_spy):
    return [
        patch(
            "tg_parser.services.db_context.digest_subscription_repo",
            lambda: _digest_repo_ctx(repo),
        ),
        patch(
            "tg_parser.services.background_scheduler.unregister_digest_subscription",
            new=unregister_spy,
        ),
    ]


def _patch_unsubscribe_watchlist_executor(
    ir: _FakeInterestRepo,
    mr: _FakeMatchRepo,
    svc: WatchlistService,
):
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


# ===========================================================================
# 1. unsubscribe_digest — preview gate (confirm falsy → no deletion)
# ===========================================================================


@pytest.mark.asyncio
class TestUnsubscribeDigestPreviewGate:
    async def test_preview_call_does_not_delete(self):
        repo = _FakeDigestSubscriptionRepo()
        _seed_digest(repo)
        unregister_spy = MagicMock()
        patches = _patch_unsubscribe_digest_executor(repo, unregister_spy)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_id": SUB_ID},  # confirm omitted — preview turn
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert result.get("user_facing_message") is True
        # G1 canonical regression: nothing deleted, scheduler untouched.
        assert SUB_ID in repo.store
        unregister_spy.assert_not_called()

    async def test_preview_message_names_subscription_and_id(self):
        repo = _FakeDigestSubscriptionRepo()
        _seed_digest(repo)
        unregister_spy = MagicMock()
        patches = _patch_unsubscribe_digest_executor(repo, unregister_spy)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_id": SUB_ID, "confirm": False},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        msg = result["message"]
        assert "Ежечасный дайджест" in msg
        assert SUB_ID in msg
        assert "[да/нет]" in msg

    async def test_not_found_keeps_existing_error(self):
        repo = _FakeDigestSubscriptionRepo()  # empty — nothing seeded
        unregister_spy = MagicMock()
        patches = _patch_unsubscribe_digest_executor(repo, unregister_spy)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_id": SUB_ID},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is not True
        assert "not found" in (result.get("error") or "")
        assert result["subscription_id"] == SUB_ID

    async def test_confirm_true_deletes(self):
        repo = _FakeDigestSubscriptionRepo()
        _seed_digest(repo)
        unregister_spy = MagicMock()
        patches = _patch_unsubscribe_digest_executor(repo, unregister_spy)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_digest(
                {"subscription_id": SUB_ID, "confirm": True},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("deleted") is True
        assert SUB_ID not in repo.store
        unregister_spy.assert_called_once()


# ===========================================================================
# 2. unsubscribe_digest — ConfirmFlow end-to-end (да / yes / нет)
# ===========================================================================


@pytest.mark.asyncio
class TestUnsubscribeDigestConfirmFlow:
    async def _drive_confirm(self, token: str) -> tuple[_FakeDigestSubscriptionRepo, MagicMock]:
        repo = _FakeDigestSubscriptionRepo()
        _seed_digest(repo)
        unregister_spy = MagicMock()
        executor_patches = _patch_unsubscribe_digest_executor(repo, unregister_spy)

        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "unsubscribe_digest",
                "args": {"subscription_id": SUB_ID},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(token)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = executor_patches + [
            # Route the handler through the REAL execute_tool so the FSM
            # confirm-turn drives the full guard + executor path.
            patch("tg_parser.bot.handlers.execute_tool", new=execute_tool),
        ]
        _enter_all(patches)
        try:
            await _handle_confirmation_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)
        return repo, msg

    async def test_affirmative_da_deletes(self):
        repo, msg = await self._drive_confirm("да")
        assert SUB_ID not in repo.store
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "не совсем понимаю" not in sent.lower()

    async def test_affirmative_yes_deletes(self):
        repo, _msg = await self._drive_confirm("yes")
        assert SUB_ID not in repo.store

    async def test_negative_net_cancels(self):
        repo, msg = await self._drive_confirm("нет")
        # Nothing deleted on a negative confirm.
        assert SUB_ID in repo.store
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "Отменено" in sent


# ===========================================================================
# 3. unsubscribe_watchlist — symmetric coverage
# ===========================================================================


@pytest.mark.asyncio
class TestUnsubscribeWatchlistPreviewGate:
    async def test_preview_call_does_not_delete(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        _seed_interest(ir)
        svc = _make_watchlist_service(ir, mr)
        patches = _patch_unsubscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": INTEREST_ID},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert result.get("user_facing_message") is True
        # Interest still active — nothing soft-deleted.
        assert ir.store[INTEREST_ID].is_active is True

    async def test_preview_message_names_interest_and_id(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        _seed_interest(ir)
        svc = _make_watchlist_service(ir, mr)
        patches = _patch_unsubscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": INTEREST_ID, "confirm": False},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        msg = result["message"]
        assert "MiCA alerts" in msg
        assert INTEREST_ID in msg
        assert "[да/нет]" in msg

    async def test_not_found_keeps_existing_error(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()  # empty
        svc = _make_watchlist_service(ir, mr)
        patches = _patch_unsubscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": INTEREST_ID},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is not True
        assert result.get("deleted") is False
        assert "not found" in (result.get("error") or "")

    async def test_confirm_true_deletes(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        _seed_interest(ir)
        svc = _make_watchlist_service(ir, mr)
        patches = _patch_unsubscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": INTEREST_ID, "confirm": True},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("deleted") is True
        assert ir.store[INTEREST_ID].is_active is False


@pytest.mark.asyncio
class TestUnsubscribeWatchlistConfirmFlow:
    async def _drive_confirm(self, token: str) -> tuple[_FakeInterestRepo, MagicMock]:
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        _seed_interest(ir)
        svc = _make_watchlist_service(ir, mr)
        executor_patches = _patch_unsubscribe_watchlist_executor(ir, mr, svc)

        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "unsubscribe_watchlist",
                "args": {"interest_id": INTEREST_ID},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(token)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = executor_patches + [
            patch("tg_parser.bot.handlers.execute_tool", new=execute_tool),
        ]
        _enter_all(patches)
        try:
            await _handle_confirmation_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)
        return ir, msg

    async def test_affirmative_da_deletes(self):
        ir, _msg = await self._drive_confirm("да")
        assert ir.store[INTEREST_ID].is_active is False

    async def test_affirmative_yes_deletes(self):
        ir, _msg = await self._drive_confirm("yes")
        assert ir.store[INTEREST_ID].is_active is False

    async def test_negative_net_cancels(self):
        ir, msg = await self._drive_confirm("нет")
        assert ir.store[INTEREST_ID].is_active is True
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "Отменено" in sent


# ===========================================================================
# 4. Contract guard — both tools must be in _WRITE_TOOLS_REQUIRING_CONFIRM
# ===========================================================================


class TestUnsubscribeToolsInGuardSet:
    def test_unsubscribe_digest_in_guard_set(self) -> None:
        assert "unsubscribe_digest" in _WRITE_TOOLS_REQUIRING_CONFIRM, (
            "G1/BUG-046 regression — unsubscribe_digest must be in "
            "_WRITE_TOOLS_REQUIRING_CONFIRM so the two-phase confirm gate "
            "arms ConfirmFlow instead of dead-ending on «да»."
        )

    def test_unsubscribe_watchlist_in_guard_set(self) -> None:
        assert "unsubscribe_watchlist" in _WRITE_TOOLS_REQUIRING_CONFIRM, (
            "G1/BUG-046 regression — unsubscribe_watchlist must be in "
            "_WRITE_TOOLS_REQUIRING_CONFIRM (symmetric with unsubscribe_digest)."
        )
