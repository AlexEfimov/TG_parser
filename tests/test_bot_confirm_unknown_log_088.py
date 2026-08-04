"""BUG-088 — ``fsm_confirm_unknown_token`` must log the shape, never the reply.

Pins:
1. Privacy, through the REAL handler — a secret-shaped reply on an armed
   ConfirmFlow leaves no byte of itself in the captured record, and no
   ``normalized`` / ``text`` / ``message`` key survives.
2. Event still EXISTS with a usable payload. «Just drop the field» would empty
   the record and read as a privacy pass while destroying the BUG-032
   diagnostic, so an absence-only suite is not enough.
3. Literal key set — a future field must be added deliberately.
4. Source tripwire — the exact defect expression cannot come back.
5. Diagnosability — the verdict table, and near-miss computed against the LIVE
   whitelists in ``handlers`` rather than a copy of them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from structlog.testing import capture_logs

from tg_parser.bot.confirm_unknown_log import (
    UNKNOWN_CONFIRM_LOG_KEYS,
    UNKNOWN_CONFIRM_VERDICTS,
    classify_unknown_confirm_verdict,
    normalize_confirm_reply,
    unknown_confirm_log_fields,
)
from tg_parser.bot.handlers import (
    AFFIRMATIVE_TOKENS,
    NEGATIVE_TOKENS,
    _handle_confirmation_response,
    classify_confirmation_token,
)
from tg_parser.bot.states import ConfirmFlow

_EVENT = "fsm_confirm_unknown_token"
# Secret-shaped: no line-initial command verb and no question marker, so
# ``_looks_like_new_intent`` does NOT reroute it — a credential paste is among
# the replies MOST likely to reach this branch.
_SECRET = "sk-live-ABCDEFGHijklmnop123456"
_DM_CHAT_ID = 700_088_001
# structlog's LogCapture adds these two to every record it collects.
_CAPTURE_KEYS = frozenset({"event", "log_level"})


def _make_state(chat_id: int = _DM_CHAT_ID) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=42, chat_id=chat_id, user_id=67890)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = _DM_CHAT_ID) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


async def _capture_unknown_token_turn(
    reply: str,
    *,
    tool_name: str = "remove_channel",
) -> tuple[dict[str, Any], list[dict[str, Any]], MagicMock]:
    """Drive one armed ConfirmFlow turn and return its captured INFO record."""
    state = _make_state()
    await state.set_state(ConfirmFlow.awaiting_confirmation)
    await state.update_data(
        pending_action={"tool_name": tool_name, "args": {"channel_id": "X"}},
        created_at=datetime.now(UTC).isoformat(),
    )
    msg = _make_message(reply)
    agent = MagicMock()
    agent.process_message = AsyncMock()

    async def _fake_execute(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("unknown token must not execute a tool")

    with (
        patch("tg_parser.bot.handlers.execute_tool", new=_fake_execute),
        capture_logs() as logs,
    ):
        await _handle_confirmation_response(msg, agent, state, current_user=None)

    matching = [record for record in logs if record.get("event") == _EVENT]
    assert len(matching) == 1, f"expected exactly one {_EVENT!r} record, got {len(matching)}"
    # The FSM contract this event documents (BUG-032) must still hold.
    assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
    return matching[0], logs, msg


class TestUnknownConfirmTokenLogPrivacy:
    """The reply's own bytes must not reach the log pipeline."""

    async def test_secret_shaped_reply_is_absent_from_captured_logs(self) -> None:
        record, logs, msg = await _capture_unknown_token_turn(_SECRET)

        blob = json.dumps(logs, ensure_ascii=False, default=str)
        # Compare FOLDED: the pre-fix site normalized with ``.casefold()``, so a
        # mixed-case credential leaked in folded form and a plain substring
        # check would have missed the very defect this pins.
        assert _SECRET.casefold() not in blob.casefold(), (
            f"raw user reply leaked into {_EVENT} (BUG-088): {record}"
        )
        assert _SECRET not in blob
        # Not even a prefix — shape (b) truncation was a rejected fix.
        assert _SECRET[:8].casefold() not in blob.casefold()

        for forbidden in ("normalized", "text", "message", "raw", "reply"):
            assert forbidden not in record, f"{forbidden!r} must not be a field of {_EVENT}"

        # And the user-facing prompt is not an echo either.
        answered = " ".join(str(call.args) for call in msg.answer.call_args_list)
        assert _SECRET not in answered

    async def test_event_still_carries_the_bug032_diagnostic(self) -> None:
        """Absence is not enough: an empty event would read as a false pass."""
        record, _logs, _msg = await _capture_unknown_token_turn(_SECRET)

        assert record["verdict"] == "single_token_unlisted"
        assert record["length"] == len(_SECRET)
        assert record["token_count"] == 1
        assert record["is_single_token"] is True
        assert record["has_digits"] is True
        assert record["has_punct"] is True
        assert record["chat_id"] == _DM_CHAT_ID

    async def test_record_key_set_is_exactly_the_declared_set(self) -> None:
        record, _logs, _msg = await _capture_unknown_token_turn(_SECRET)

        assert set(record) - _CAPTURE_KEYS == UNKNOWN_CONFIRM_LOG_KEYS
        assert record["log_level"] == "info"

    async def test_pending_tool_is_logged(self) -> None:
        """The field this event never had: WHICH action went unanswered."""
        record, _logs, _msg = await _capture_unknown_token_turn(
            "ладно потом", tool_name="add_user_auth"
        )

        assert record["tool"] == "add_user_auth"
        assert record["verdict"] == "multi_token_free_text"

    async def test_missing_pending_tool_logs_none_not_a_crash(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"args": {}},
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("асдф")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        with capture_logs() as logs:
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        record = next(r for r in logs if r.get("event") == _EVENT)
        assert record["tool"] is None


class TestUnknownConfirmTokenCallSite:
    """Source-level tripwire on the one call site (BUG-088)."""

    _SOURCE = Path("tg_parser/bot/handlers.py").read_text(encoding="utf-8")

    def test_defect_expression_is_gone(self) -> None:
        assert 'normalized=" ".join(text.split()).casefold()' not in self._SOURCE
        assert "normalized=" not in self._SOURCE

    def test_call_site_uses_the_shared_helper(self) -> None:
        assert (
            "from tg_parser.bot.confirm_unknown_log import unknown_confirm_log_fields"
            in self._SOURCE
        )
        assert "unknown_confirm_log_fields(" in self._SOURCE

    def test_raw_text_is_not_dumped_at_debug_instead(self) -> None:
        """The b0dcef3 DEBUG-split was reverted by 8332aa3 — do not resurrect it."""
        assert "logger.debug" not in self._SOURCE


class TestUnknownConfirmVerdicts:
    """Diagnosability table (plan §3.1) — closed vocabulary, no user bytes."""

    def test_verdicts_are_a_closed_vocabulary(self) -> None:
        for reply in ("", "🚀", "дя", "неа", "ладно потом", _SECRET, "12345", "?" * 4096):
            verdict = classify_unknown_confirm_verdict(normalize_confirm_reply(reply))
            assert verdict in UNKNOWN_CONFIRM_VERDICTS

    def test_typo_of_affirmative_is_a_near_miss(self) -> None:
        assert classify_unknown_confirm_verdict("дя") == "near_miss_affirmative"

    def test_typo_of_negative_is_a_near_miss(self) -> None:
        assert classify_unknown_confirm_verdict("неа") == "near_miss_negative"

    def test_multi_token_free_text(self) -> None:
        assert classify_unknown_confirm_verdict("ладно потом") == "multi_token_free_text"

    def test_emoji_only_is_non_text(self) -> None:
        assert classify_unknown_confirm_verdict(normalize_confirm_reply("🚀")) == "non_text"
        assert classify_unknown_confirm_verdict("") == "non_text"
        assert classify_unknown_confirm_verdict("...") == "non_text"

    def test_decorated_whitelist_token_is_a_near_miss(self) -> None:
        """Only trailing ``,.;:!?`` on the first token is stripped upstream."""
        assert classify_unknown_confirm_verdict("(да)") == "near_miss_affirmative"

    def test_paste_shape_is_distinguishable_from_a_synonym(self) -> None:
        paste = unknown_confirm_log_fields(_SECRET, chat_id=1, tool="remove_channel")
        typo = unknown_confirm_log_fields("хорошоо", chat_id=1, tool="remove_channel")

        assert paste["verdict"] == "single_token_unlisted"
        assert paste["length"] >= 20
        assert paste["has_digits"] is True
        assert typo["verdict"] == "near_miss_affirmative"
        assert typo["length"] == 7
        assert typo["has_digits"] is False

    def test_normalization_matches_the_classifier(self) -> None:
        assert normalize_confirm_reply("  ДА\tЛАДНО \n") == "да ладно"
        assert normalize_confirm_reply(None) == ""

    def test_fields_key_set_is_the_declared_set(self) -> None:
        fields = unknown_confirm_log_fields("что?", chat_id=7, tool=None)
        assert set(fields) == UNKNOWN_CONFIRM_LOG_KEYS


class TestNearMissUsesLiveWhitelists:
    """The near-miss verdict must read the whitelists the classifier uses.

    A local copy of the token sets would pass while drifting from production
    the moment either whitelist gains an entry.
    """

    @staticmethod
    def _one_edit_mutations(tokens: frozenset[str]) -> list[str]:
        # Doubling the first character is one insertion, keeps the token count
        # at 1, and keeps at least one alphanumeric character.
        return [
            token[0] + token
            for token in tokens
            if " " not in token and any(ch.isalnum() for ch in token)
        ]

    def test_every_affirmative_token_has_a_near_miss_neighbour(self) -> None:
        mutations = self._one_edit_mutations(AFFIRMATIVE_TOKENS)
        assert len(mutations) >= 10, "whitelist unexpectedly small — pin is vacuous"
        for mutation in mutations:
            if classify_confirmation_token(mutation) != "unknown":
                continue  # would never reach the unknown branch
            assert classify_unknown_confirm_verdict(mutation) == "near_miss_affirmative", (
                f"{mutation!r} is one edit from an AFFIRMATIVE_TOKENS entry"
            )

    def test_every_negative_token_has_a_near_miss_neighbour(self) -> None:
        for mutation in self._one_edit_mutations(NEGATIVE_TOKENS):
            if classify_confirmation_token(mutation) != "unknown":
                continue
            assert classify_unknown_confirm_verdict(mutation) in {
                "near_miss_negative",
                # Affirmative is checked first and wins a rare collision.
                "near_miss_affirmative",
            }, f"{mutation!r} is one edit from a NEGATIVE_TOKENS entry"

    def test_listed_tokens_never_reach_this_code_path(self) -> None:
        """Sanity: the whitelists themselves classify, so no verdict is needed."""
        for token in AFFIRMATIVE_TOKENS | NEGATIVE_TOKENS:
            assert classify_confirmation_token(token) != "unknown"
