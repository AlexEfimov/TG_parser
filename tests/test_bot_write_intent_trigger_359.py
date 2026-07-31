"""#359 / ADR-0020 — the deterministic affirmative-token confirm trigger.

BUG-086 closed the «the LLM hand-wrote «Подтвердите … [да/нет]» after a
preview-LESS write call» dead-end by PREDICTING that ask from the LLM's prose
(three regexes, five precision passes). Prose is an open class: two
false-positive vectors were structurally out of reach of any regex — free Russian
word order in the disclaimer veto, and FOREIGN text (a knowledge-base post the
LLM quotes back) carrying the ask markers.

The replacement inverts the question. The framework no longer asks «did the LLM
ask for confirmation?» (prose) but «did the USER say «да»?» (a closed
vocabulary the handler has classified deterministically since BUG-032):

* T1 — a confirm-gated write tool ran and armed no preview ⇒ the agent hands the
  handler a small ``write_intent_pending`` snapshot (``tool_name`` + args with
  ``confirm`` / ``dry_run`` already stripped). The turn's TEXT is never read.
* T2 — if the very next message is a BARE affirmative token, the deterministic
  router re-issues the same tool in its preview shape and arms ``ConfirmFlow``.
  A bare negative cancels; anything else (including a compound «да, покажи темы
  X») drops the snapshot and falls through to the agent.
* T3 — the real mutation still needs the user's SECOND «да» on top of the
  framework's own preview text (the BUG-047 ``delete_suggest`` shape).

Written failing-first against ``eca35c7``: every class here is RED on main
(``AgentResult`` has no ``write_intent_pending``, and a T2 «да» falls through to
the stateless agent).

Fakes for the ``force_resummarize`` surface are imported from
``tests/test_f5c_bot_force_resummarize.py``; the FSM/message fakes mirror
``tests/test_bot_subscribe_channel_resume_bug050.py``.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from structlog.testing import capture_logs

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_f5c_bot_force_resummarize import (  # type: ignore[import-not-found]  # noqa: E402
    _PROD_SELF_AUTHORED_CONFIRM,
    TOPIC_ID,
    _admin,
    _fake_repos,
    _FakeBundle,
    _FakeBundleRepo,
    _FakeCardRepo,
    _FakeService,
    _gemini_function_call,
    _gemini_text,
    _make_card,
)

from tg_parser.auth.models import CurrentUser  # noqa: E402
from tg_parser.bot.agent import AgentResult, GeminiAgent  # noqa: E402
from tg_parser.bot.handlers import (  # noqa: E402
    AFFIRMATIVE_TOKENS,
    ANAPHORA_PATTERN,
    COMMAND_VERB_PATTERN,
    DELETE_VERB_PATTERN,
    NEGATIVE_TOKENS,
    PENDING_TTL_SECONDS,
    READ_CONTEXT_TTL_SECONDS,
    _classify_bare_confirmation_token,
    handle_text,
)
from tg_parser.bot.states import ConfirmFlow, PaginationFlow  # noqa: E402

DM_CHAT_ID: int = 700_500_359


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _make_state(bot_id: int = 42, chat_id: int = DM_CHAT_ID, user_id: int = 359) -> FSMContext:
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


def _plain_user(user_id: str = "user-359") -> CurrentUser:
    """A NON-admin — ``force_resummarize`` is admin-only (``assert_admin``)."""
    return CurrentUser(
        id=user_id,
        name="359",
        role="user",
        allowed_channel_ids=None,
        max_channels=10,
    )


def _agent_returning(result: AgentResult) -> MagicMock:
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value=result)
    return agent


def _write_intent_result(
    response_text: str = "…",
    *,
    tool_name: str = "force_resummarize",
    args: dict[str, Any] | None = None,
    **kwargs: Any,
) -> AgentResult:
    """An ``AgentResult`` shaped like a preview-LESS confirm-gated write turn."""
    return AgentResult(
        response_text=response_text,
        write_intent_pending={
            "tool_name": tool_name,
            "args": dict(args if args is not None else {"topic_id": TOPIC_ID}),
        },
        **kwargs,
    )


def _preview_executor(calls: list[tuple[str, dict[str, Any]]], *, message: str | None = None):
    async def _executor(name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        calls.append((name, dict(args)))
        return {
            "preview": True,
            "tool": name,
            "message": message or "Тема «…» будет пересуммаризирована. Подтвердите [да/нет].",
            "user_facing_message": True,
        }

    return _executor


async def _t1_then(
    state: FSMContext,
    reply: str,
    *,
    result: AgentResult | None = None,
    current_user: CurrentUser | None = None,
    execute: Any = None,
    t1_text: str = "пере-суммаризируй тему " + TOPIC_ID,
) -> tuple[MagicMock, MagicMock, list[tuple[str, dict[str, Any]]]]:
    """Run T1 (a preview-less write turn) then T2 (``reply``) on ``state``.

    Returns the two messages plus the executor call log of T2.
    """
    user = current_user if current_user is not None else _admin()
    t1 = _make_message(t1_text)
    await handle_text(
        t1,
        agent=_agent_returning(result if result is not None else _write_intent_result()),
        state=state,
        current_user=user,
    )

    calls: list[tuple[str, dict[str, Any]]] = []
    t2 = _make_message(reply)
    t2_agent = _agent_returning(AgentResult(response_text="агент ответил"))
    with patch(
        "tg_parser.bot.handlers.execute_tool",
        new=execute if execute is not None else _preview_executor(calls),
    ):
        await handle_text(t2, agent=t2_agent, state=state, current_user=user)
    t2.agent = t2_agent  # type: ignore[attr-defined]
    return t1, t2, calls


# ===========================================================================
# The corpus of the five precision passes — now a SINGLE invariant
# ===========================================================================

# A knowledge-base post the LLM quotes back at the user: vector (b) of #359,
# structurally unreachable for a prose detector (the markers are in text NOBODY
# wrote as an ask).
_QUOTED_FOREIGN_ASK = (
    "Нашёл в канале пост: «Коллеги, запускаем опрос по новой рубрике. "
    "Подтвердите участие [да/нет]». Это цитата из базы знаний."
)

# Every phrasing the detector was tightened for, across all five passes, plus
# the prod signature and the quoted-foreign-text vector. Under the old design
# the first group ARMED a mutation preview from prose and the second did not;
# under ADR-0020 the distinction is meaningless — none of them arms anything.
_PROSE_CORPUS: tuple[str, ...] = (
    # The prod trace (2026-07-25) — the strongest ask marker.
    _PROD_SELF_AUTHORED_CONFIRM,
    # Fourth pass — imperative / interrogative asks (the detector's TRUE positives).
    "Подтвердите, пожалуйста, пере-суммаризацию темы",
    "Подтвердите [да/нет]",
    "Подтверди операцию",
    "Подтвердить пере-суммаризацию?",
    "Подтвердить?",
    "Подтвердить запуск для темы topic:tg:c1:post:1?",
    # Fourth pass — declarative infinitives paraphrasing the payload's next_step.
    "Это только отчёт. Чтобы подтвердить реальный запуск, попросите меня ещё раз",
    "Отчёт сформирован. Вам нужно будет подтвердить запуск отдельно",
    "Пользователь должен подтвердить операцию перед запуском",
    "Реальный запуск потребуется подтвердить отдельно.",
    "Чтобы действительно пере-суммаризировать, нужно будет подтвердить операцию.",
    "Пользователь должен подтвердить операцию перед запуском. Что показать дальше?",
    "Чтобы подтвердить реальный запуск, попросите отдельно. Нужен ли ещё отчёт?",
    # Fifth pass — clause separators.
    "Нужно подтвердить запуск — показать ещё раз?",
    "Нужно подтвердить запуск – показать ещё раз?",
    "Нужно подтвердить запуск - показать ещё раз?",
    "Нужно подтвердить запуск, показать ещё раз?",
    "Нужно подтвердить запуск: показать ещё раз?",
    "Нужно подтвердить запуск; показать ещё раз?",
    # First / second pass — argument literals and declarative confirm verbs.
    "Вызовите force_resummarize с confirm=false и без dry_run.",
    "Подтверждаю, что это только отчёт: версия 8, новых элементов 0.",
    "Подтверждая отчёт, LLM не вызывался и версия не записывалась.",
    # The accepted false negative of the fifth pass — no longer a trade-off.
    "Подтвердить, пожалуйста, запуск?",
    # Vector (b) — foreign text.
    _QUOTED_FOREIGN_ASK,
)


@pytest.mark.asyncio
class TestFinalTextNeverArmsConfirmFlow:
    """The single invariant that replaces five precision passes.

    ``ConfirmFlow`` is armed when — and only when — the USER typed a bare
    affirmative token. The turn's own text decides NOTHING, so the whole
    morphological defect class (person, finiteness, mood, clause boundaries) and
    both structurally-unreachable vectors of #359 (free word order in the veto,
    quoted foreign text) cease to exist rather than being approximated.
    """

    @staticmethod
    async def _agent_turn(prose: str) -> AgentResult:
        """One real agent turn: dry-run write call, then ``prose`` as the answer."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                _gemini_text(prose),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(
                    _FakeCardRepo(_make_card(summary_version=8, new_items=0)),
                    _FakeBundleRepo(_FakeBundle([{"i": 1}])),
                ),
            ),
        ):
            return await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

    @pytest.mark.parametrize("prose", _PROSE_CORPUS)
    async def test_no_prose_arms_a_preview(self, prose: str) -> None:
        """Not one of the phrasings the detector was tuned on (in EITHER
        direction) reaches control flow: the turn keeps its text and hands over
        the SAME snapshot regardless of what the LLM wrote."""
        result = await self._agent_turn(prose)

        assert result.preview_pending is None
        assert result.preview_message is None
        assert result.response_text == prose
        # Prose-independent: the snapshot is a function of the CALL, not the text.
        assert result.write_intent_pending == {
            "tool_name": "force_resummarize",
            "args": {"topic_id": TOPIC_ID},
        }

    @pytest.mark.parametrize("prose", (_PROD_SELF_AUTHORED_CONFIRM, _QUOTED_FOREIGN_ASK))
    async def test_the_users_da_is_what_arms_it(self, prose: str) -> None:
        """…and the user's own «да» arms it — including on the quoted-foreign-ask
        turn, which the prose detector armed with nobody having asked."""
        state = _make_state()
        calls: list[tuple[str, dict[str, Any]]] = []
        _, t2, calls = await _t1_then(
            state,
            "да",
            result=_write_intent_result(prose),
        )

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        assert calls == [("force_resummarize", {"topic_id": TOPIC_ID})], calls
        assert "Подтвердите [да/нет]" in _sent_text(t2)


@pytest.mark.asyncio
class TestProdTraceTakesThreeTurns:
    """The 2026-07-25 prod trace, end to end through the REAL agent loop.

    T1 the LLM picks the ``dry_run`` shape on a mutation request and hand-writes
    its own confirmation; T2 the user's «да» buys a REAL preview (nothing is
    mutated — the ``delete_suggest`` «acceptance turn» shape of BUG-047); T3 the
    second «да» executes. Pre-fix T2 dead-ended on «Я не совсем понимаю ваш
    ответ»; under the BUG-086 guard T2 was the mutation confirm itself.
    """

    async def test_dry_run_shape_recovers_in_three_turns(self) -> None:
        state = _make_state()
        card_repo = _FakeCardRepo(_make_card(summary_version=8, new_items=0))
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                _gemini_text(_PROD_SELF_AUTHORED_CONFIRM),
            ]
        )
        repos = _fake_repos(card_repo, _FakeBundleRepo(_FakeBundle([{"i": 1}])))

        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch("tg_parser.services.db_context.resummarization_repos", repos),
        ):
            # T1 — the report plus the LLM's invented ask; snapshot, no FSM.
            t1 = _make_message("пере-суммаризируй тему " + TOPIC_ID)
            await handle_text(t1, agent=agent, state=state, current_user=_admin())
            assert await state.get_state() is None
            assert (await state.get_data())["pending_write_intent"]["tool_name"] == (
                "force_resummarize"
            )

            # T2 — «да» buys the framework's OWN preview. Nothing is mutated.
            t2 = _make_message("да")
            with capture_logs() as t2_logs:
                await handle_text(t2, agent=agent, state=state, current_user=_admin())

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        preview_text = _sent_text(t2)
        assert "Подтвердите [да/нет]" in preview_text
        assert "пересуммаризирована" in preview_text
        events = [r["event"] for r in t2_logs]
        assert "write_intent_router_resume" in events
        assert "fsm_confirm_armed" in events
        # The pending action is the SANITIZED snapshot — ``confirm`` is added by
        # the confirm-turn alone (BUG-009), and args must match bit-for-bit so
        # ``_check_confirm_flow_match`` accepts T3.
        assert (await state.get_data())["pending_action"] == {
            "tool_name": "force_resummarize",
            "args": {"topic_id": TOPIC_ID},
        }

        # T3 — the SECOND «да» is what finally mutates.
        svc = _FakeService(outcome={"status": "ok"})
        t3 = _make_message("да")
        with (
            patch("tg_parser.services.db_context.resummarization_repos", repos),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
            capture_logs() as t3_logs,
        ):
            await handle_text(t3, agent=agent, state=state, current_user=_admin())

        executed = [r for r in t3_logs if r["event"] == "fsm_confirm_execute"]
        assert executed and executed[0]["args"]["confirm"] is True
        assert svc.calls == [TOPIC_ID], svc.calls
        assert await state.get_state() is None


# ===========================================================================
# Snapshot lifecycle
# ===========================================================================


@pytest.mark.asyncio
class TestWriteIntentSnapshotLifecycle:
    async def test_t1_sets_the_snapshot_without_arming_anything(self) -> None:
        state = _make_state()
        msg = _make_message("пере-суммаризируй тему " + TOPIC_ID)
        with capture_logs() as logs:
            await handle_text(
                msg,
                agent=_agent_returning(_write_intent_result(_PROD_SELF_AUTHORED_CONFIRM)),
                state=state,
                current_user=_admin(),
            )

        # No FSM armed — the framework does not pre-empt the user.
        assert await state.get_state() is None
        wi = (await state.get_data()).get("pending_write_intent")
        assert wi is not None
        assert wi["tool_name"] == "force_resummarize"
        assert wi["args"] == {"topic_id": TOPIC_ID}
        age = (datetime.now(UTC) - datetime.fromisoformat(wi["created_at"])).total_seconds()
        assert 0 <= age < PENDING_TTL_SECONDS
        # The LLM's own text is relayed untouched (no framework-added nudge —
        # a nudge would push a user who asked for a REPORT towards a mutation).
        sent = _sent_text(msg)
        for fragment in _PROD_SELF_AUTHORED_CONFIRM.splitlines():
            assert fragment in sent
        assert [r for r in logs if r["event"] == "write_intent_set"]

    async def test_snapshot_never_carries_confirm_or_dry_run(self) -> None:
        """Sanitized at CREATION, so the mutating shape cannot be reconstructed
        from FSM storage even by accident (BUG-009 / preview-suppressing args)."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call(
                    "force_resummarize",
                    {"topic_id": TOPIC_ID, "dry_run": True, "confirm": True},
                ),
                _gemini_text("Отчёт готов."),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
        ):
            result = await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.write_intent_pending is not None
        assert result.write_intent_pending["args"] == {"topic_id": TOPIC_ID}

        state = _make_state()
        msg = _make_message("пере-суммаризируй тему " + TOPIC_ID)
        await handle_text(msg, agent=_agent_returning(result), state=state, current_user=_admin())
        stored = (await state.get_data())["pending_write_intent"]["args"]
        assert "confirm" not in stored
        assert "dry_run" not in stored

    async def test_expired_snapshot_is_not_resumable(self) -> None:
        """TTL is ConfirmFlow's 5 min, not read-context's 15."""
        state = _make_state()
        await state.update_data(
            pending_write_intent={
                "created_at": (
                    datetime.now(UTC) - timedelta(seconds=PENDING_TTL_SECONDS + 60)
                ).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            }
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        msg = _make_message("да")
        agent = _agent_returning(AgentResult(response_text="агент ответил"))
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(msg, agent=agent, state=state, current_user=_admin())

        assert calls == []
        assert await state.get_state() is None
        agent.process_message.assert_called_once()

    async def test_snapshot_with_a_broken_created_at_is_stale_fail_safe(self) -> None:
        """``_is_stale`` (fail-SAFE), never ``_is_pending_expired`` (fail-OPEN):
        a missing / unparseable anchor must not resume a mutation preview."""
        for anchor in (None, "", "not-a-timestamp"):
            state = _make_state()
            snapshot: dict[str, Any] = {
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            }
            if anchor is not None:
                snapshot["created_at"] = anchor
            await state.update_data(pending_write_intent=snapshot)
            calls: list[tuple[str, dict[str, Any]]] = []
            agent = _agent_returning(AgentResult(response_text="агент ответил"))
            with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
                await handle_text(
                    _make_message("да"), agent=agent, state=state, current_user=_admin()
                )
            assert calls == [], anchor
            assert await state.get_state() is None, anchor

    async def test_negative_token_declines(self) -> None:
        state = _make_state()
        with capture_logs() as logs:
            _, t2, calls = await _t1_then(state, "нет")

        assert calls == []
        assert await state.get_state() is None
        assert "❌ Отменено." in _sent_text(t2)
        assert [r for r in logs if r["event"] == "write_intent_declined"]

    async def test_unrelated_message_drops_the_snapshot_silently(self) -> None:
        state = _make_state()
        with capture_logs() as logs:
            _, t2, calls = await _t1_then(state, "покажи каналы")

        assert calls == []
        assert await state.get_state() is None
        assert (await state.get_data()).get("pending_write_intent") is None
        # The turn went to the agent as usual — nothing was said about the drop.
        t2.agent.process_message.assert_called_once()  # type: ignore[attr-defined]
        dropped = [r for r in logs if r["event"] == "write_intent_dropped"]
        assert dropped and dropped[-1]["reason"] == "unrelated"

    async def test_adjacency_a_later_da_no_longer_resumes(self) -> None:
        """The snapshot is consumed or dropped on the NEXT message — a «да» two
        turns later is exactly the false positive this design removed, only
        displaced in time."""
        state = _make_state()
        await _t1_then(state, "спасибо")

        calls: list[tuple[str, dict[str, Any]]] = []
        agent = _agent_returning(AgentResult(response_text="агент ответил"))
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(_make_message("да"), agent=agent, state=state, current_user=_admin())

        assert calls == []
        assert await state.get_state() is None

    async def test_preview_turn_sets_no_snapshot(self) -> None:
        """The happy path is untouched: a real preview arms ConfirmFlow directly
        and no snapshot is created (one confirmation, not two)."""
        state = _make_state()
        msg = _make_message("пере-суммаризируй тему " + TOPIC_ID)
        await handle_text(
            msg,
            agent=_agent_returning(
                AgentResult(
                    response_text="…",
                    preview_pending={
                        "tool_name": "force_resummarize",
                        "args": {"topic_id": TOPIC_ID},
                    },
                    preview_message="Тема будет пересуммаризирована. Подтвердите [да/нет].",
                )
            ),
            state=state,
            current_user=_admin(),
        )

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        assert (await state.get_data()).get("pending_write_intent") is None

    async def test_failed_preview_is_never_silent(self) -> None:
        """The user TYPED «да» and is waiting: a silent give-up would be a
        self-made dead-end of exactly the BUG-032 / BUG-046 class."""
        state = _make_state()

        async def _no_preview(name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            return {"error": "Topic not found", "error_class": "NotFound"}

        with capture_logs() as logs:
            _, t2, _ = await _t1_then(state, "да", execute=_no_preview)

        assert await state.get_state() is None
        sent = _sent_text(t2)
        assert "Topic not found" in sent
        assert "Не удалось подготовить подтверждение" in sent
        assert [r for r in logs if r["event"] == "write_intent_router_failed"]


# ===========================================================================
# Mutual exclusion + structural adjacency
# ===========================================================================


@pytest.mark.asyncio
class TestWriteIntentAndConfirmFlowAreMutuallyExclusive:
    async def test_armed_confirm_flow_owns_the_affirmative(self) -> None:
        """«да» with ConfirmFlow armed EXECUTES the pending action (the L637
        gate wins) — the router must not steal it."""
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": "remove_channel", "args": {"channel_id": "c1"}},
            created_at=datetime.now(UTC).isoformat(),
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            },
        )
        calls: list[tuple[str, dict[str, Any]]] = []

        async def _exec(name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            calls.append((name, dict(args)))
            return {"ok": True}

        with patch("tg_parser.bot.handlers.execute_tool", new=_exec):
            await handle_text(
                _make_message("да"),
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )

        assert [n for n, _ in calls] == ["remove_channel"]
        assert (await state.get_data()).get("pending_write_intent") is None

    async def test_a_turn_that_arms_an_fsm_sets_no_snapshot(self) -> None:
        """Syntactic exclusion: the set-site is a BRANCH of the arm chain, so a
        turn carrying both a pagination hint and a preview-less write call arms
        pagination only."""
        state = _make_state()
        await handle_text(
            _make_message("покажи темы канала genotek"),
            agent=_agent_returning(
                _write_intent_result(
                    pagination_pending={
                        "tool_name": "list_topics",
                        "args": {"channel_id": "genotek"},
                        "total": 40,
                        "offset": 20,
                        "limit": 20,
                    },
                )
            ),
            state=state,
            current_user=_admin(),
        )

        assert await state.get_state() == PaginationFlow.has_active_list.state
        assert (await state.get_data()).get("pending_write_intent") is None

    async def test_resume_clears_a_coexisting_subscribe_intent(self) -> None:
        """BUG-050 parity with the agent-preview / clarify arm sites.

        ONE turn can set both detectors (their triggers are disjoint but not
        mutually exclusive), and the confirm-execute path deliberately RESTORES
        ``subscribe_intent`` for any non-subscribe tool — so if the resume armed
        ConfirmFlow without clearing it, the stale intent would outlive the whole
        double-confirm and a later bare channel name would resume a subscribe the
        user had moved on from.
        """
        state = _make_state()
        await state.update_data(
            subscribe_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "subscribe_digest",
                "requested_channel": "genotek",
                "partial_args": {},
            },
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            },
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(
                _make_message("да"),
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        assert (await state.get_data()).get("subscribe_intent") is None

    async def test_resume_of_an_unsubscribe_records_last_subscription(self) -> None:
        """BUG-047 B-2 parity with the agent-preview arm site: an ``unsubscribe_*``
        preview armed BY ID must record its target, so a later anaphora («удали эту
        подписку») still resolves — e.g. after the user declines this confirmation.
        """
        state = _make_state()
        await state.update_data(
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "unsubscribe_digest",
                "args": {"subscription_id": "sub-42"},
            }
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(
                _make_message("да"),
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        ls = (await state.get_data()).get("last_subscription")
        assert ls is not None and ls["id"] == "sub-42" and ls["kind"] == "digest"


@pytest.mark.asyncio
class TestWriteIntentSurvivesNoTurn:
    """Pop-at-top: the snapshot cannot outlive a message down ANY path of
    ``handle_text``. Adjacency is structural, not a list of clear-sites that a
    future arm-site could forget to update (there are eight ``set_state`` calls
    outside the arm chain)."""

    @staticmethod
    async def _seed(state: FSMContext) -> None:
        await state.update_data(
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            }
        )

    async def _assert_gone(self, state: FSMContext) -> None:
        assert (await state.get_data()).get("pending_write_intent") is None

    async def test_pagination_reply_drops_it(self) -> None:
        state = _make_state()
        await state.set_state(PaginationFlow.has_active_list)
        await state.update_data(
            pagination={
                "tool_name": "list_topics",
                "args": {"channel_id": "genotek"},
                "total": 40,
                "offset": 20,
                "limit": 20,
            },
            items_shown=20,
            created_at=datetime.now(UTC).isoformat(),
        )
        await self._seed(state)

        async def _exec(name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            return {"items": [], "total": 40, "offset": 40, "limit": 20}

        with patch("tg_parser.bot.handlers.execute_tool", new=_exec):
            await handle_text(
                _make_message("ещё"),
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )
        await self._assert_gone(state)

    async def test_confirm_flow_gate_drops_it(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": "remove_channel", "args": {"channel_id": "c1"}},
            created_at=datetime.now(UTC).isoformat(),
        )
        await self._seed(state)
        with patch(
            "tg_parser.bot.handlers.execute_tool",
            new=AsyncMock(return_value={"ok": True}),
        ):
            await handle_text(
                _make_message("да"),
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )
        await self._assert_gone(state)

    async def test_delete_prerouter_drops_it(self) -> None:
        """A pre-router that returns ``True`` returns BEFORE the write-intent
        router — the snapshot must already be gone by then."""
        state = _make_state()
        await state.update_data(
            last_subscription={
                "id": "sub-1",
                "kind": "digest",
                "name": "Дайджест",
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        await self._seed(state)

        async def _exec(name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            return {
                "preview": True,
                "tool": name,
                "message": "Подписка «Дайджест» будет удалена. Подтвердите [да/нет].",
                "user_facing_message": True,
            }

        with patch("tg_parser.bot.handlers.execute_tool", new=_exec):
            await handle_text(
                _make_message("удали эту подписку"),
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )
        await self._assert_gone(state)

    async def test_whitespace_only_message_drops_it(self) -> None:
        """``F.text`` admits a whitespace-only message and ``handle_text`` returns
        on its blank-text guard without reaching a single router. The pop sits
        ABOVE that guard, so such a message still consumes the snapshot — popping
        below it would let a "   " turn carry the intent forward and a later «да»
        arm a preview from two messages back."""
        state = _make_state()
        await self._seed(state)
        agent = _agent_returning(AgentResult(response_text="…"))
        await handle_text(_make_message("   "), agent=agent, state=state, current_user=_admin())

        await self._assert_gone(state)
        agent.process_message.assert_not_called()


# ===========================================================================
# Trigger width: tier-1 only
# ===========================================================================


@pytest.mark.asyncio
class TestCompoundAffirmativeIsNotATrigger:
    """A DELIBERATE divergence from ``_handle_confirmation_response``, not an
    oversight. There the user has just been shown the framework's «Подтвердите
    [да/нет]», so «да, давай» unambiguously answers it. Here T1 may have been an
    HONEST read-only report and the framework adds no nudge, so consuming
    «да, покажи темы канала X» would show a MUTATION preview and silently lose
    the user's actual request. Missing a compound costs one rephrase."""

    @pytest.mark.parametrize(
        "reply",
        (
            "да, давай",
            "да genotek",
            "да, покажи темы канала genotek",
            "нет, покажи другое",
            "ок, только сначала список каналов",
        ),
    )
    async def test_compound_falls_through_to_the_agent(self, reply: str) -> None:
        state = _make_state()
        _, t2, calls = await _t1_then(state, reply)

        assert calls == [], calls
        assert await state.get_state() is None
        # The user's real request is NOT lost: the agent got the turn.
        t2.agent.process_message.assert_called_once()  # type: ignore[attr-defined]
        assert "❌ Отменено." not in _sent_text(t2)

    async def test_classifier_takes_the_whole_form_only(self) -> None:
        for token in sorted(AFFIRMATIVE_TOKENS):
            assert _classify_bare_confirmation_token(token) == "affirmative", token
            assert _classify_bare_confirmation_token(token.upper()) == "affirmative", token
        for token in sorted(NEGATIVE_TOKENS):
            assert _classify_bare_confirmation_token(token) == "negative", token
        for compound in ("да, давай", "да genotek", "нет, спасибо", "", "  ", "может быть"):
            assert _classify_bare_confirmation_token(compound) == "unknown", compound
        assert _classify_bare_confirmation_token(None) == "unknown"
        # Whitespace / case normalization still applies to the full form.
        assert _classify_bare_confirmation_token("  ДА \n") == "affirmative"

    async def test_trailing_punctuation_does_not_make_a_token_unrelated(self) -> None:
        """«да.» is the same BARE answer as «да» — the ConfirmFlow classifier
        accepts it, and dropping it here would dead-end the user on the very turn
        this mechanism exists to rescue. Safe because no whitelisted token
        contains punctuation, and what makes a compound dangerous is the content
        AFTER the separator, which survives the strip."""
        for text in ("да.", "да!", "да,", "ок.", "нет.", "нет!", "не надо."):
            verdict = _classify_bare_confirmation_token(text)
            assert verdict in {"affirmative", "negative"}, text
        # Punctuation alone is not a confirmation, and a compound stays unrelated
        # however it is punctuated.
        for text in (".", "...", "!?", "да, покажи темы канала X", "нет, покажи другое"):
            assert _classify_bare_confirmation_token(text) == "unknown", text


# ===========================================================================
# Precedence — BUG-047 D1 must keep holding
# ===========================================================================


@pytest.mark.asyncio
class TestWriteIntentRouterPrecedenceMatrix:
    async def test_stray_da_stays_inert_for_delete_intent_without_a_snapshot(self) -> None:
        """BUG-047 D1: with a delete_intent active and NO write snapshot, «да» is
        still inert and falls through to the agent (today's contract)."""
        state = _make_state()
        await state.update_data(
            delete_intent={"created_at": datetime.now(UTC).isoformat(), "requested": "Дайджест"}
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        agent = _agent_returning(AgentResult(response_text="агент ответил"))
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(_make_message("да"), agent=agent, state=state, current_user=_admin())

        assert calls == []
        assert await state.get_state() is None
        agent.process_message.assert_called_once()

    async def test_snapshot_plus_delete_intent_resumes_the_write(self) -> None:
        """Same delete_intent, but WITH a snapshot ⇒ «да» resumes the write.

        The snapshot is seeded directly rather than produced by a real T1 turn:
        the BUG-048 delete-intent router sits ahead of ours and, for any text its
        four gates let through, resolves the name against the DB and answers —
        which would swallow T1 itself and leave nothing to resume. That
        interaction belongs to BUG-048, not here; this test pins OUR contract.
        """
        state = _make_state()
        await state.update_data(
            delete_intent={"created_at": datetime.now(UTC).isoformat(), "requested": "Дайджест"},
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            },
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(
                _make_message("да"),
                agent=_agent_returning(AgentResult(response_text="агент ответил")),
                state=state,
                current_user=_admin(),
            )

        assert calls == [("force_resummarize", {"topic_id": TOPIC_ID})]
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state

    async def test_no_bare_token_looks_like_a_delete_or_command(self) -> None:
        """Router ORDER is a readability choice only because the tier-1 token
        sets are disjoint from every pre-router trigger."""
        for token in sorted(AFFIRMATIVE_TOKENS | NEGATIVE_TOKENS):
            assert not DELETE_VERB_PATTERN.match(token), token
            assert not ANAPHORA_PATTERN.search(token), token
            assert not COMMAND_VERB_PATTERN.match(token), token

    async def test_compound_anaphora_goes_to_the_delete_prerouter(self) -> None:
        """«да, последнюю» is a compound (⇒ NOT our trigger) AND a valid delete
        anaphora — with tier-1 the outcome no longer depends on router order."""
        state = _make_state()
        await state.update_data(
            last_subscription={
                "id": "sub-1",
                "kind": "digest",
                "name": "Дайджест",
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        calls: list[tuple[str, dict[str, Any]]] = []

        async def _exec(name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            calls.append((name, dict(args)))
            return {
                "preview": True,
                "tool": name,
                "message": "Подписка «Дайджест» будет удалена. Подтвердите [да/нет].",
                "user_facing_message": True,
            }

        _, _, _ = await _t1_then(state, "да, последнюю", execute=_exec)

        assert [n for n, _ in calls] == ["unsubscribe_digest"], calls


# ===========================================================================
# Authorization is re-checked on resume
# ===========================================================================


@pytest.mark.asyncio
class TestWriteIntentResumeRechecksAuthorization:
    async def test_demotion_between_t1_and_t2_denies_the_resume(self) -> None:
        """The snapshot carries NO identity and NO role, so the executor's own
        ``assert_admin`` runs against the CURRENT user on T2."""
        state = _make_state()
        await state.update_data(
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            }
        )
        msg = _make_message("да")
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
            capture_logs() as logs,
        ):
            await handle_text(
                msg,
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_plain_user(),
            )

        assert await state.get_state() is None
        assert "Не удалось подготовить подтверждение" in _sent_text(msg)
        assert [r for r in logs if r["event"] == "write_intent_router_failed"]

    async def test_snapshot_carries_no_identity(self) -> None:
        state = _make_state()
        msg = _make_message("пере-суммаризируй тему " + TOPIC_ID)
        await handle_text(
            msg,
            agent=_agent_returning(_write_intent_result()),
            state=state,
            current_user=_admin(),
        )
        wi = (await state.get_data())["pending_write_intent"]
        assert set(wi) == {"created_at", "tool_name", "args"}
        blob = json.dumps(wi, ensure_ascii=False, default=str)
        assert "admin" not in blob
        assert _admin().id not in blob

    async def test_no_current_user_never_re_issues(self) -> None:
        """``current_user=None`` must NOT reach ``execute_tool``: the executors
        fall back to ``get_default_admin()``, so a re-issue would run with
        ADMIN rights nobody granted on this turn."""
        state = _make_state()
        await state.update_data(
            pending_write_intent={
                "created_at": datetime.now(UTC).isoformat(),
                "tool_name": "force_resummarize",
                "args": {"topic_id": TOPIC_ID},
            }
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        agent = _agent_returning(AgentResult(response_text="агент ответил"))
        with patch("tg_parser.bot.handlers.execute_tool", new=_preview_executor(calls)):
            await handle_text(_make_message("да"), agent=agent, state=state, current_user=None)

        assert calls == []
        assert await state.get_state() is None


# ===========================================================================
# Observability
# ===========================================================================


@pytest.mark.asyncio
class TestCancelPathIsObservable:
    async def test_confirm_flow_decline_is_logged(self) -> None:
        """Closes the #359 § 3 gap: pre-fix the negative branch of
        ``_handle_confirmation_response`` wrote NOTHING, so «the user cancelled»
        and «the flow broke» were indistinguishable in the logs."""
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": "remove_channel", "args": {"channel_id": "c1"}},
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("нет")
        with capture_logs() as logs:
            await handle_text(
                msg,
                agent=_agent_returning(AgentResult(response_text="…")),
                state=state,
                current_user=_admin(),
            )

        assert "❌ Отменено." in _sent_text(msg)
        declined = [r for r in logs if r["event"] == "fsm_confirm_declined"]
        assert declined and declined[0]["tool"] == "remove_channel"


@pytest.mark.asyncio
class TestWriteIntentLogPrivacy:
    """Heir of the deleted shadow-mode privacy test: argument KEYS only (an
    ``add_user_auth`` arg carries a raw credential in its VALUE), and the user's
    message never reaches the log."""

    _EVENTS = {"write_intent_set", "write_intent_router_resume"}

    async def test_only_arg_keys_are_logged(self) -> None:
        state = _make_state()
        secret = "s3cr3t-credential"
        with capture_logs() as logs:
            await _t1_then(
                state,
                "да",
                result=_write_intent_result(
                    tool_name="add_user_auth",
                    # ``identifier`` is the REAL secret-bearing argument of
                    # add_user_auth (tools.py: it is what gets hash_credential'd),
                    # so the pin uses that name rather than an invented one.
                    args={"user_id": "u1", "auth_type": "api_key", "identifier": secret},
                ),
                t1_text="выдай доступ пользователю u1 по токену " + secret,
            )

        records = [r for r in logs if r["event"] in self._EVENTS]
        assert {r["event"] for r in records} == self._EVENTS
        for record in records:
            assert record["arg_keys"] == ["auth_type", "identifier", "user_id"]
            assert "args" not in record
        blob = json.dumps(records, ensure_ascii=False, default=str)
        assert secret not in blob
        assert "выдай доступ" not in blob
        assert "u1" not in blob


def test_ttl_choice_is_the_confirmation_window_not_the_read_context_one() -> None:
    """The snapshot is a PRE-confirmation, so its lifetime must match the
    confirmation window (5 min) — not ``delete_intent`` / ``subscribe_intent``'s
    15 min, whose triggers are specific NAMES rather than a general «да»."""
    assert PENDING_TTL_SECONDS == 300
    assert READ_CONTEXT_TTL_SECONDS == 900
