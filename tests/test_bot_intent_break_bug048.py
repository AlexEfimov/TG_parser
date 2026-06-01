"""BUG-048 (D2) regression suite — FSM intent-break + delete-intent persistence.

Two production defects, both deterministic-routing gaps building on the closed
BUG-047 delete-routing cluster (the BUG-046 confirm-gate + BUG-047 D1
stray-«да» inertness must stay intact):

1. **delete→junk→bare-name → CREATE misroute** — after a ``delete_suggest`` FSM
   is correctly cleared on a zero-match junk reply (BUG-047 D1), a subsequent
   BARE subscription name (no delete verb, no anaphora) fell to the stateless
   agent and the LLM emitted ``subscribe_digest`` (create) instead of a delete.
   Root: the delete intent lived only in the armed FSM; nothing persisted it.
2. **greedy armed FSM** — ConfirmFlow and subscribe/read ClarifyFlow consumed
   ANY non-«нет» input (incl. explicit new commands / questions) as a
   confirm-token / channel-name, wedging the user.

The fix is hybrid A + C:

* **A — ``delete_intent`` TTL snapshot** (``states.py`` ``DeleteIntentData`` +
  ``handlers.py`` helpers + a ``handle_text`` ``_handle_delete_intent_router``):
  the explicit delete intent is recorded the moment a delete verb / anaphora is
  seen, survives an intervening FSM clear (snapshot-restore like
  ``read_context`` / ``last_subscription``), and re-resolves a later bare name
  as a DELETE.
* **C — intent-break / escape guard** (``_looks_like_new_intent`` +
  ``_release_fsm_and_reroute`` applied at ConfirmFlow entry + subscribe/read +
  selective delete ClarifyFlow): an explicit new command / question abandons
  the un-executed flow and reroutes.

Written failing-first (RED on ``cd5f4c2`` before the source edits). Fakes are
mirrored from ``tests/test_bot_delete_routing_bug047.py``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
from tg_parser.bot.agent import AgentResult  # noqa: E402
from tg_parser.bot.handlers import (  # noqa: E402
    READ_CONTEXT_TTL_SECONDS,
    _handle_clarification_response,
    handle_text,
)
from tg_parser.bot.states import ClarifyFlow, ConfirmFlow  # noqa: E402
from tg_parser.bot.tools import execute_tool  # noqa: E402
from tg_parser.domain.models import (  # noqa: E402
    DigestFormat,
    DigestSubscription,
    NotifyMode,
    WatchInterest,
)
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

DM_CHAT_ID: int = 700_500_048
SUB_ID: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

DIGEST_NAME = "Ежечасный дайджест Genotek"


# ---------------------------------------------------------------------------
# Helpers (mirrored from tests/test_bot_delete_routing_bug047.py)
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-048") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="048",
        role="admin",
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


def _digest(sub_id: str, name: str, *, owner_id: str = "user-048") -> DigestSubscription:
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


def _interest(interest_id: str, title: str, *, user_id: str = "user-048") -> WatchInterest:
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
        # The intent-break reroutes that engage the delete path never touch
        # verify_channel_exists; the pre-fix subscribe re-run path does — pin it
        # so RED behaviour is deterministic offline.
        patch("tg_parser.bot.handlers.verify_channel_exists", new=AsyncMock(return_value=True)),
    ]


def _empty_repos():
    digest_repo = _FakeDigestSubscriptionRepo()
    ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
    svc = _make_watchlist_service(ir, mr)
    return digest_repo, ir, mr, svc, MagicMock()


def _subscribe_clarify_action(**overrides: Any) -> dict[str, Any]:
    """A ``kind="subscribe"`` clarify (mirrors BUG-039/G2 fixtures)."""
    base = {
        "kind": "subscribe",
        "tool_name": "subscribe_digest",
        "args": {
            "name": "Ежечасный дайджест",
            "channel_ids": ["pro fendocrinologist"],
            "cron_expression": "0 * * * *",
            "timezone": "Europe/Moscow",
        },
        "channel_index": 0,
        "suggestion": "profendocrinologist",
        "message": "Канал «pro fendocrinologist» не найден. Возможно, …?",
    }
    base.update(overrides)
    return base


# ===========================================================================
# D2-1 / D2-2 / D2-3 — delete → junk → bare-name persistence (defect 1)
# ===========================================================================


@pytest.mark.asyncio
class TestDeleteIntentPersistence:
    async def test_delete_suggest_junk_bare_name_routes_delete_not_subscribe(self):
        """D2-1: «удали подписку Genotek» → «hh» (junk, clears delete_suggest)
        → bare digest name. The third turn must route to a DELETE (unsubscribe
        preview or a re-armed delete_suggest) and NEVER call the agent /
        subscribe_digest."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            # Turn 1 — explicit delete verb + a near-miss name → delete_suggest.
            await handle_text(
                _make_message("удали подписку Genotek"),
                agent=agent,
                state=state,
                current_user=_admin(),
            )
            assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state

            # Turn 2 — junk zero-match reply clears the delete_suggest FSM.
            await handle_text(_make_message("hh"), agent=agent, state=state, current_user=_admin())
            assert await state.get_state() is None

            # Turn 3 — a BARE subscription name (no delete verb, no anaphora).
            msg3 = _make_message(DIGEST_NAME)
            await handle_text(msg3, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        # The agent / LLM is NEVER consulted on turn 3 (deterministic delete).
        agent.process_message.assert_not_called()
        # Routed to a DELETE: an unsubscribe confirm preview was armed …
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
        # … and NOTHING was created (no subscribe), nothing deleted yet.
        assert SUB_ID in digest_repo.store

    async def test_delete_intent_preserved_after_zero_match_fsm_clear(self):
        """D2-2: after the junk zero-match reply clears the delete_suggest FSM,
        the FSM is None but ``delete_intent`` is present AND non-stale."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(
                _make_message("удали подписку Genotek"),
                agent=agent,
                state=state,
                current_user=_admin(),
            )
            await handle_text(_make_message("hh"), agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        assert await state.get_state() is None
        data = await state.get_data()
        di = data.get("delete_intent")
        assert di is not None, "delete_intent must survive the zero-match FSM clear"
        # Non-stale (created within the TTL window).
        created = datetime.fromisoformat(di["created_at"])
        age = (datetime.now(UTC) - created).total_seconds()
        assert 0 <= age < READ_CONTEXT_TTL_SECONDS

    async def test_delete_intent_stray_da_still_inert_after_junk(self):
        """D2-3: a stray «да» AFTER the junk clear (delete_intent present, NO
        armed FSM) must remain inert — no delete executed, no ConfirmFlow armed
        (BUG-047 D1 guard); it falls through to the agent."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(
                _make_message("удали подписку Genotek"),
                agent=agent,
                state=state,
                current_user=_admin(),
            )
            await handle_text(_make_message("hh"), agent=agent, state=state, current_user=_admin())
            # delete_intent persists (RED pre-fix: no delete_intent concept).
            assert (await state.get_data()).get("delete_intent") is not None

            # Stray «да» — inert: routed to the agent, never a delete.
            agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))
            msg = _make_message("да")
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_called_once()
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state
        assert SUB_ID in digest_repo.store


# ===========================================================================
# D2-4 / D2-5 / D2-6 — subscribe ClarifyFlow intent-break (defect 2)
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeClarifyIntentBreak:
    async def _arm_subscribe_clarify(self, state: FSMContext) -> None:
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_subscribe_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )

    async def test_subscribe_clarify_breaks_on_delete_verb(self):
        """D2-4: an armed subscribe ClarifyFlow + «удали {DIGEST_NAME}» must
        BREAK out of the subscribe flow and engage the delete path — NOT treat
        «удали …» as a channel name («Канал «удали…» не найден»)."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await self._arm_subscribe_clarify(state)
        msg = _make_message(f"удали {DIGEST_NAME}")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await _handle_clarification_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)

        # The delete path engaged: an unsubscribe confirm preview is armed.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
        # NOT the pre-fix "channel «удали …» не найден" dead-end.
        sent = _sent_text(msg)
        assert "удали" not in sent.lower() or "не найден" not in sent.lower()

    async def test_subscribe_clarify_breaks_on_show_command(self):
        """D2-5: an armed subscribe ClarifyFlow + «покажи подписки на дайджесты»
        must clear the FSM and reroute to the agent."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()

        state = _make_state()
        await self._arm_subscribe_clarify(state)
        msg = _make_message("покажи подписки на дайджесты")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await _handle_clarification_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_called_once()
        assert await state.get_state() != ClarifyFlow.awaiting_channel_clarification.state

    async def test_subscribe_clarify_breaks_on_question(self):
        """D2-6: an armed subscribe ClarifyFlow + «какие у тебя есть подписки»
        (a question) must clear the FSM and reroute to the agent."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()

        state = _make_state()
        await self._arm_subscribe_clarify(state)
        msg = _make_message("какие у тебя есть подписки")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await _handle_clarification_response(msg, agent, state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_called_once()
        assert await state.get_state() != ClarifyFlow.awaiting_channel_clarification.state

    async def test_bare_channel_name_does_not_break_subscribe_clarify(self):
        """Regression guard (BUG-040): a BARE channel name reply
        («profendocrinologist») must NOT trigger an intent-break — it stays
        in-flow and re-runs subscribe (no false escape, agent never consulted)."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()

        state = _make_state()
        await self._arm_subscribe_clarify(state)
        msg = _make_message("profendocrinologist")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {"preview": True, "tool": name, "message": "Подтвердите [да/нет]."}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert invoked == ["subscribe_digest"]
        agent.process_message.assert_not_called()


# ===========================================================================
# D2-7 / D2-8 — ConfirmFlow intent-break (defect 2)
# ===========================================================================


@pytest.mark.asyncio
class TestConfirmFlowIntentBreak:
    async def _arm_subscribe_confirm(self, state: FSMContext) -> None:
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "subscribe_digest",
                "args": {"name": "Ежечасный дайджест", "channel_ids": ["genotek"]},
            },
            created_at=datetime.now(UTC).isoformat(),
        )

    async def test_confirm_flow_breaks_on_delete_verb(self):
        """D2-7: ConfirmFlow with a subscribe preview pending + «удали
        {DIGEST_NAME}» → the un-executed preview is ABANDONED and the delete
        path engages (NOT the opaque «Не понял…» BUG-032 reprompt)."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        await self._arm_subscribe_confirm(state)
        msg = _make_message(f"удали {DIGEST_NAME}")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert "Не понял" not in _sent_text(msg)
        # Delete path engaged; the subscribe preview was abandoned (never run).
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID

    async def test_confirm_flow_breaks_on_show_command(self):
        """D2-8: ConfirmFlow with a subscribe preview pending + «покажи каналы»
        → the FSM is cleared and the agent is invoked."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()

        state = _make_state()
        await self._arm_subscribe_confirm(state)
        msg = _make_message("покажи каналы")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_called_once()
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state

    async def test_confirm_flow_maybe_still_reprompts(self):
        """Regression guard (BUG-032): a genuine unknown non-command token
        («maybe») is NOT a new intent — it must keep the ConfirmFlow armed and
        re-prompt да/нет, NOT reroute."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()

        state = _make_state()
        await self._arm_subscribe_confirm(state)
        msg = _make_message("maybe")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        assert "Не понял" in _sent_text(msg)
