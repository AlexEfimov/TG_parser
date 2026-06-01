"""BUG-050 regression suite — subscribe-create channel-not-found resume.

The defect (D2 / BUG-040 class, SUBSCRIBE surface — the analogue of BUG-048's
``delete_intent`` gap): on a subscribe-create request with an unknown/typo
channel, the LLM SOMETIMES answers conversationally («Извините, канал "enotek"
не найден. Возможно вы имели в виду "Genotek"?») instead of calling
``subscribe_digest``. Because the tool isn't called, the deterministic G2 path
(``_reject_nonexistent_channel`` → ``_build_subscribe_clarify_pending``) never
runs and NO ``ClarifyFlow`` is armed. The user's follow-up bare channel name
«genotek» is then processed statelessly and the LLM picks ``list_topics``
(«Показываю топ-20 тем канала…») instead of resuming the subscribe.

The fix is hybrid: prompt v1.7.6 hardening + a ``subscribe_intent`` TTL router.

* POST-agent detector — SET ``subscribe_intent`` ONLY when a turn had a
  subscribe-create verb AND the agent returned TEXT-ONLY (no clarify_pending /
  preview_pending / pagination_pending).
* ``_handle_subscribe_intent_router`` (in ``handle_text`` AFTER the delete-intent
  router, BEFORE the agent) — on the bare-channel follow-up, merges the token as
  the channel and re-runs ``subscribe_digest`` (confirm=false), arming the
  existing ClarifyFlow / ConfirmFlow gate.

Written failing-first (the new-behaviour cases — 050-1/2/7 — are RED on
``9ab998c``/main before the source edits; the regression guards — 050-3/4/5/6/8
— stay green on both). Fakes are mirrored from
``tests/test_bot_intent_break_bug048.py`` and
``tests/test_bot_conversation_layer_bug039_042.py``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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
from tg_parser.bot.tools import _exec_subscribe_digest, execute_tool  # noqa: E402
from tg_parser.domain.models import DigestFormat, DigestSubscription  # noqa: E402

DM_CHAT_ID: int = 700_500_050
SUB_ID: str = "5050aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FULL_CRON = "0 * * * *"
TYPO_CHANNEL = "enotek"
GOOD_CHANNEL = "genotek"


# ---------------------------------------------------------------------------
# Helpers (mirrored from tests/test_bot_intent_break_bug048.py)
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-050") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="050",
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stale_iso() -> str:
    return (datetime.now(UTC) - timedelta(seconds=READ_CONTEXT_TTL_SECONDS + 60)).isoformat()


def _digest(sub_id: str, name: str, *, owner_id: str = "user-050") -> DigestSubscription:
    return DigestSubscription(
        id=sub_id,
        owner_id=owner_id,
        chat_id=DM_CHAT_ID,
        name=name,
        channel_ids=[GOOD_CHANNEL],
        cron_expression=FULL_CRON,
        timezone="Europe/Moscow",
        format=DigestFormat.SUMMARY,
        language="ru",
        is_active=True,
    )


async def _verify_channel(cid: str | None) -> bool | None:
    """Existence stub: genotek present, enotek absent, everything else unknown."""
    norm = (cid or "").lower().lstrip("@")
    if norm == GOOD_CHANNEL:
        return True
    if norm == TYPO_CHANNEL:
        return False
    return None


class _FakeSource:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id


def _state_repo_ctx(channel_ids: list[str]):
    """Patch target for ``ingestion_state_repo`` returning fixed sources
    (drives ``_channel_suggestion_lookup`` for the G2 suggestion)."""

    @asynccontextmanager
    async def _ctx():
        repo = MagicMock()
        repo.list_sources = AsyncMock(return_value=[_FakeSource(c) for c in channel_ids])
        yield (repo, MagicMock())

    return _ctx


@asynccontextmanager
async def _digest_repo_ctx(repo: _FakeDigestSubscriptionRepo):
    yield (repo, None)


@asynccontextmanager
async def _watchlist_repos_ctx(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


def _subscribe_intent(*, created_at: str | None = None, cron: str | None = FULL_CRON) -> dict:
    intent: dict[str, Any] = {
        "created_at": created_at or _now_iso(),
        "requested_channel": TYPO_CHANNEL,
    }
    if cron:
        intent["partial_args"] = {"cron_expression": cron}
    return intent


# ===========================================================================
# 050-1 — POST-agent detector arms subscribe_intent on a text-only turn
# ===========================================================================


@pytest.mark.asyncio
class TestPostAgentDetector:
    async def test_text_only_subscribe_create_sets_subscribe_intent(self):
        """050-1: a subscribe-create request whose turn returned TEXT-ONLY (the
        LLM answered «канал enotek не найден…» instead of calling the tool) must
        arm NO ClarifyFlow but SET a non-stale ``subscribe_intent`` carrying the
        parsed schedule (RED on main: no subscribe_intent concept)."""
        state = _make_state()
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text=(
                    'Извините, канал "enotek" не найден. Возможно вы имели в виду "Genotek"?'
                )
            )
        )
        msg = _make_message("Создай подписку на канал enotek, каждый час в :00")
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        agent.process_message.assert_called_once()
        # No deterministic FSM armed (the LLM bypassed the tool / G2 clarify).
        assert await state.get_state() is None
        data = await state.get_data()
        si = data.get("subscribe_intent")
        assert si is not None, "subscribe_intent must be SET on the text-only subscribe-create turn"
        # Non-stale + parsed schedule preserved for the resume.
        age = (datetime.now(UTC) - datetime.fromisoformat(si["created_at"])).total_seconds()
        assert 0 <= age < READ_CONTEXT_TTL_SECONDS
        assert si["partial_args"]["cron_expression"] == FULL_CRON
        assert si.get("requested_channel") == TYPO_CHANNEL

    async def test_subscribe_create_with_preview_does_not_set_intent(self):
        """Guard: when the LLM DID call subscribe_digest and the turn armed a
        preview (deterministic flow), the post-agent detector must NOT also set a
        subscribe_intent (no double-arming)."""
        state = _make_state()
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="Preview…",
                preview_pending={
                    "tool_name": "subscribe_digest",
                    "args": {"name": "Дайджест genotek", "channel_ids": [GOOD_CHANNEL]},
                },
                preview_message="Preview: создать подписку… Подтвердите [да/нет].",
            )
        )
        msg = _make_message("подпиши на дайджест genotek")
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        assert (await state.get_data()).get("subscribe_intent") is None


# ===========================================================================
# 050-2 — bare-channel follow-up resumes the subscribe
# ===========================================================================


@pytest.mark.asyncio
class TestBareChannelResume:
    async def test_bare_channel_resumes_subscribe_not_list_topics(self):
        """050-2: with a non-stale subscribe_intent active, a bare «genotek» must
        re-run subscribe_digest (channel substituted) — NEVER list_topics — and
        arm the ConfirmFlow preview; the agent is never consulted (RED on main:
        no router → falls to the agent, subscribe_digest never called)."""
        state = _make_state()
        await state.update_data(subscribe_intent=_subscribe_intent())
        msg = _make_message(GOOD_CHANNEL)
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        invoked: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            invoked.append((name, dict(args)))
            return {
                "preview": True,
                "tool": name,
                "message": "Preview: создать подписку… Подтвердите [да/нет].",
            }

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await handle_text(msg, agent=agent, state=state, current_user=_admin())

        assert [n for n, _ in invoked] == ["subscribe_digest"]
        assert "list_topics" not in [n for n, _ in invoked]
        assert invoked[0][1]["channel_ids"] == [GOOD_CHANNEL]
        assert "confirm" not in invoked[0][1]
        # Re-run produced a preview → ConfirmFlow armed, intent consumed.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        assert (await state.get_data()).get("subscribe_intent") is None
        agent.process_message.assert_not_called()

    async def test_bare_channel_resume_arms_clarify_when_still_not_found(self):
        """050-2b: if the resumed channel is ALSO not-found WITH a suggestion
        (G2), the router arms ClarifyFlow with the fresh suggestion and drops the
        subscribe_intent (handed off to the deterministic clarify)."""
        state = _make_state()
        await state.update_data(subscribe_intent=_subscribe_intent())
        msg = _make_message("enotek")  # bare, but still a typo
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        with (
            patch(
                "tg_parser.bot.tools.verify_channel_exists",
                new=AsyncMock(side_effect=_verify_channel),
            ),
            patch(
                "tg_parser.services.db_context.ingestion_state_repo",
                new=_state_repo_ctx([GOOD_CHANNEL, "durov"]),
            ),
            patch("tg_parser.bot.handlers.execute_tool", new=execute_tool),
        ):
            await handle_text(msg, agent=agent, state=state, current_user=_admin())

        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        data = await state.get_data()
        assert data["clarify_action"]["kind"] == "subscribe"
        assert data["clarify_action"]["suggestion"] == GOOD_CHANNEL
        assert data.get("subscribe_intent") is None
        agent.process_message.assert_not_called()


# ===========================================================================
# 050-3 — regression: tool-called G2 path unchanged
# ===========================================================================


@pytest.mark.asyncio
class TestG2ExecutorUnchanged:
    async def test_exec_subscribe_digest_typo_returns_subscribe_clarify(self):
        """050-3: when subscribe_digest IS actually called with a typo channel,
        the executor still returns a kind="subscribe" clarify_pending naming the
        fuzzy suggestion (existing G2 behaviour — green on both)."""
        with (
            patch(
                "tg_parser.bot.tools.verify_channel_exists",
                new=AsyncMock(side_effect=_verify_channel),
            ),
            patch(
                "tg_parser.services.db_context.ingestion_state_repo",
                new=_state_repo_ctx([GOOD_CHANNEL, "durov"]),
            ),
        ):
            result = await _exec_subscribe_digest(
                {
                    "name": "Ежечасный дайджест",
                    "channel_ids": [TYPO_CHANNEL],
                    "cron_expression": FULL_CRON,
                    "timezone": "Europe/Moscow",
                },
                current_user=_admin(),
                bot=None,
                chat_id=DM_CHAT_ID,
            )

        assert result.get("preview") is not True
        assert result["error_class"] == "ChannelNotFound"
        clarify = result["clarify_pending"]
        assert clarify["kind"] == "subscribe"
        assert clarify["suggestion"] == GOOD_CHANNEL
        assert clarify["args"]["channel_ids"] == [TYPO_CHANNEL]


# ===========================================================================
# 050-4 — regression: line-initial show verb is a new intent (not a resume)
# ===========================================================================


@pytest.mark.asyncio
class TestShowVerbIsNewIntent:
    async def test_show_topics_while_subscribe_intent_routes_to_agent(self):
        """050-4: «покажи темы канала genotek» while a subscribe_intent is active
        is a line-initial show verb (a new intent) — the subscribe router must
        NOT handle it (no subscribe_digest), it falls through to the agent (which
        invokes list_topics) and the subscribe_intent is cleared."""
        state = _make_state()
        await state.update_data(subscribe_intent=_subscribe_intent())
        msg = _make_message("покажи темы канала genotek")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="Показываю топ-20 тем канала genotek:",
                read_tools_called=[("list_topics", {"channel_id": GOOD_CHANNEL})],
            )
        )

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {"preview": True, "tool": name, "message": "x"}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await handle_text(msg, agent=agent, state=state, current_user=_admin())

        agent.process_message.assert_called_once()
        assert "subscribe_digest" not in invoked
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state
        assert (await state.get_data()).get("subscribe_intent") is None


# ===========================================================================
# 050-5 — regression: bare channel in an armed G2 clarify still completes
#         subscribe (BUG-048 bare-channel-in-clarify guard)
# ===========================================================================


@pytest.mark.asyncio
class TestBareChannelInArmedClarify:
    async def test_bare_channel_in_subscribe_clarify_reruns_subscribe(self):
        """050-5: an ALREADY-armed subscribe ClarifyFlow + a bare correction
        «profendocrinologist» is handled by _handle_clarification_response →
        subscribe_digest; the agent is NOT consulted (BUG-040/048 preserved)."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action={
                "kind": "subscribe",
                "tool_name": "subscribe_digest",
                "args": {
                    "name": "Ежечасный дайджест",
                    "channel_ids": ["pro fendocrinologist"],
                    "cron_expression": FULL_CRON,
                    "timezone": "Europe/Moscow",
                },
                "channel_index": 0,
                "suggestion": "profendocrinologist",
                "message": "Канал «pro fendocrinologist» не найден. Возможно, …?",
            },
            created_at=_now_iso(),
        )
        msg = _make_message("profendocrinologist")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {"preview": True, "tool": name, "message": "Подтвердите [да/нет]."}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch("tg_parser.bot.handlers.verify_channel_exists", new=AsyncMock(return_value=True)),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert invoked == ["subscribe_digest"]
        agent.process_message.assert_not_called()


# ===========================================================================
# 050-6 — regression: delete_intent precedence over subscribe_intent
# ===========================================================================


@pytest.mark.asyncio
class TestDeletePrecedence:
    async def test_delete_intent_wins_over_subscribe_intent_for_bare_name(self):
        """050-6: with BOTH delete_intent and subscribe_intent active, a bare
        «genotek» routes to a DELETE (the delete-intent router runs first) — NO
        subscribe is created."""
        digest_repo = _FakeDigestSubscriptionRepo()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, "Genotek")
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()

        state = _make_state()
        await state.update_data(
            delete_intent={"created_at": _now_iso()},
            subscribe_intent=_subscribe_intent(),
        )
        msg = _make_message(GOOD_CHANNEL)
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        patches = [
            patch(
                "tg_parser.services.db_context.digest_subscription_repo",
                lambda: _digest_repo_ctx(digest_repo),
            ),
            patch(
                "tg_parser.services.db_context.watchlist_repos",
                lambda: _watchlist_repos_ctx(ir, mr),
            ),
            patch("tg_parser.bot.handlers.execute_tool", new=execute_tool),
        ]
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"]["tool_name"] == "unsubscribe_digest"
        assert data["pending_action"]["args"]["subscription_id"] == SUB_ID
        # Nothing created; the digest still exists (no delete executed yet).
        assert SUB_ID in digest_repo.store


# ===========================================================================
# 050-7 — intent-break: a new command clears subscribe_intent
# ===========================================================================


@pytest.mark.asyncio
class TestIntentBreak:
    async def test_show_channels_clears_subscribe_intent(self):
        """050-7: mid subscribe_intent, «покажи каналы» is an explicit new intent
        — the intent is CLEARED and the turn is routed to the agent (RED on main:
        no router → subscribe_intent never cleared)."""
        state = _make_state()
        await state.update_data(subscribe_intent=_subscribe_intent())
        msg = _make_message("покажи каналы")
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        agent.process_message.assert_called_once()
        assert (await state.get_data()).get("subscribe_intent") is None
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state


# ===========================================================================
# 050-8 — TTL expiry: a stale subscribe_intent falls through to the agent
# ===========================================================================


@pytest.mark.asyncio
class TestTTLExpiry:
    async def test_stale_subscribe_intent_bare_channel_falls_through(self):
        """050-8: a STALE subscribe_intent (older than the TTL) must NOT resume —
        a bare «genotek» falls through to the agent (no subscribe_digest)."""
        state = _make_state()
        await state.update_data(subscribe_intent=_subscribe_intent(created_at=_stale_iso()))
        msg = _make_message(GOOD_CHANNEL)
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {"preview": True, "tool": name, "message": "x"}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await handle_text(msg, agent=agent, state=state, current_user=_admin())

        agent.process_message.assert_called_once()
        assert "subscribe_digest" not in invoked
        assert await state.get_state() != ConfirmFlow.awaiting_confirmation.state
