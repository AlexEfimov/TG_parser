"""BUG-087 — redact secret-bearing tool args at INFO on both bot log sites.

Pins:
1. Privacy — raw ``add_user_auth.identifier`` absent from BOTH
   ``agent_tool_call`` and ``fsm_confirm_execute``; key retained redacted.
2. Half-fix trap — suite must cover both event names.
3. Forensic — non-secret tools keep arg VALUES (deny-list, not allow-list).
4. Executor — ``execute_tool`` still receives the raw secret.
5. Declaration tripwire — parameter descriptions mentioning
   ``Raw credential`` / ``hashed automatically`` must be registered.
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

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import GeminiAgent
from tg_parser.bot.handlers import _handle_confirmation_response
from tg_parser.bot.log_redaction import (
    _SECRET_ARGS_BY_TOOL,
    _redacted_secret_token,
    redact_tool_args,
)
from tg_parser.bot.states import ConfirmFlow
from tg_parser.bot.tools import TOOL_DECLARATIONS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUG087_EVENTS = frozenset({"agent_tool_call", "fsm_confirm_execute"})
_SECRET = "s3cr3t-raw-api-key-value"
_DM_CHAT_ID = 700_087_001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin() -> CurrentUser:
    return CurrentUser(
        id="user-bug087",
        name="bug087",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


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


def _fresh_iso() -> str:
    return datetime.now(UTC).isoformat()


def _assert_secret_absent_from_event(records: list[dict[str, Any]], event: str) -> dict[str, Any]:
    matching = [r for r in records if r.get("event") == event]
    assert matching, f"expected at least one {event!r} record"
    record = matching[-1]
    blob = json.dumps(record, ensure_ascii=False, default=str)
    assert _SECRET not in blob, f"raw secret leaked into {event}"
    args = record.get("args")
    assert isinstance(args, dict), f"{event} must log args dict"
    assert "identifier" in args, f"{event} must retain identifier key"
    assert args["identifier"] == _redacted_secret_token(_SECRET)
    assert args["identifier"] != _SECRET
    return record


# ---------------------------------------------------------------------------
# Helper unit pins
# ---------------------------------------------------------------------------


class TestRedactToolArgsHelper:
    def test_add_user_auth_identifier_is_redacted(self) -> None:
        raw = {
            "user_id": "u1",
            "auth_type": "api_key",
            "identifier": _SECRET,
            "confirm": False,
        }
        out = redact_tool_args("add_user_auth", raw)
        assert out["identifier"] == "s3cr****"
        assert out["user_id"] == "u1"
        assert out["auth_type"] == "api_key"
        assert out["confirm"] is False
        # Shallow copy — original untouched.
        assert raw["identifier"] == _SECRET

    def test_short_secret_becomes_stars(self) -> None:
        out = redact_tool_args("add_user_auth", {"identifier": "short"})
        assert out["identifier"] == "****"

    def test_remove_channel_forensic_values_preserved(self) -> None:
        """Deny-list must not become an allow-list (BUG-002/004 forensics)."""
        out = redact_tool_args(
            "remove_channel",
            {"channel_id": "ch_x", "confirm": True},
        )
        assert out == {"channel_id": "ch_x", "confirm": True}

    def test_unknown_tool_passthrough(self) -> None:
        args = {"token": "looks-secret-but-unregistered"}
        assert redact_tool_args("whoami", args) == args


# ---------------------------------------------------------------------------
# Privacy pins — both INFO sites
# ---------------------------------------------------------------------------


class TestBug087LogPrivacy:
    """Privacy pin scoped to the two BUG-087 INFO events."""

    # Half-fix trap: deleting either privacy method must fail this map.
    _EVENT_TEST_METHODS = {
        "agent_tool_call": "test_agent_tool_call_redacts_identifier",
        "fsm_confirm_execute": "test_fsm_confirm_execute_redacts_identifier",
    }

    def test_suite_covers_both_bug087_events(self) -> None:
        """One green site must not close BUG-087 alone."""
        assert set(self._EVENT_TEST_METHODS) == _BUG087_EVENTS
        for event, method_name in self._EVENT_TEST_METHODS.items():
            assert hasattr(self, method_name), (
                f"missing privacy test method for {event}: {method_name}"
            )

    async def test_agent_tool_call_redacts_identifier(self) -> None:
        agent = GeminiAgent(api_key="test-key")
        secret_args = {
            "user_id": "u1",
            "auth_type": "api_key",
            "identifier": _SECRET,
        }
        gemini_responses = [
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "add_user_auth",
                                        "args": secret_args,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "preview ready"}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        ]
        captured_exec_args: list[dict[str, Any]] = []

        async def _fake_execute(tool_name, tool_args, **kwargs):
            captured_exec_args.append(dict(tool_args))
            return {
                "preview": True,
                "tool": tool_name,
                "message": "Подтвердите добавление api_key для u1 [да/нет].",
                "user_facing_message": "Подтвердите добавление api_key для u1 [да/нет].",
            }

        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch("tg_parser.bot.agent.execute_tool", side_effect=_fake_execute),
            capture_logs() as logs,
        ):
            await agent.process_message(
                "добавь api key пользователю u1",
                current_user=_admin(),
            )

        record = _assert_secret_absent_from_event(logs, "agent_tool_call")
        assert record["tool"] == "add_user_auth"
        assert captured_exec_args, "execute_tool must run after the log"
        assert captured_exec_args[0]["identifier"] == _SECRET

    async def test_fsm_confirm_execute_redacts_identifier(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "add_user_auth",
                "args": {
                    "user_id": "u1",
                    "auth_type": "api_key",
                    "identifier": _SECRET,
                },
            },
            created_at=_fresh_iso(),
        )
        agent = MagicMock(spec=GeminiAgent)
        msg = _make_message("да")
        captured_exec_args: list[dict[str, Any]] = []

        async def _fake_execute(tool_name, tool_args, **kwargs):
            captured_exec_args.append(dict(tool_args))
            return {"message": "ok", "preview": False}

        with (
            patch(
                "tg_parser.bot.handlers.execute_tool",
                new=AsyncMock(side_effect=_fake_execute),
            ),
            capture_logs() as logs,
        ):
            await _handle_confirmation_response(
                msg, agent=agent, state=state, current_user=_admin()
            )

        record = _assert_secret_absent_from_event(logs, "fsm_confirm_execute")
        assert record["tool"] == "add_user_auth"
        assert captured_exec_args, "execute_tool must run after the log"
        assert captured_exec_args[0]["identifier"] == _SECRET
        assert captured_exec_args[0]["confirm"] is True


# ---------------------------------------------------------------------------
# Call-site import pin (single shared helper, not two copies)
# ---------------------------------------------------------------------------


class TestSharedHelperCallSites:
    def test_both_modules_import_same_helper(self) -> None:
        agent_src = Path("tg_parser/bot/agent.py").read_text(encoding="utf-8")
        handlers_src = Path("tg_parser/bot/handlers.py").read_text(encoding="utf-8")
        assert "from tg_parser.bot.log_redaction import redact_tool_args" in agent_src
        assert "from tg_parser.bot.log_redaction import redact_tool_args" in handlers_src
        assert "redact_tool_args(tool_name, tool_args)" in agent_src
        assert "redact_tool_args(tool_name, confirmed_args)" in handlers_src
        # Do not resurrect the b0dcef3 DEBUG dump of raw args.
        assert "agent_tool_call_args" not in agent_src


# ---------------------------------------------------------------------------
# Declaration tripwire
# ---------------------------------------------------------------------------


class TestSecretArgsRegistryIsComplete:
    """Tripwire: a new secret-bearing parameter description must be registered."""

    _SECRET_DESC_MARKERS = ("Raw credential", "hashed automatically")

    def test_registry_is_not_vacuous(self) -> None:
        assert "identifier" in _SECRET_ARGS_BY_TOOL["add_user_auth"]

    def test_credential_parameter_descriptions_are_registered(self) -> None:
        unregistered: list[str] = []
        for decl in TOOL_DECLARATIONS:
            tool_name = decl["name"]
            props = decl.get("parameters", {}).get("properties", {}) or {}
            for param, spec in props.items():
                description = spec.get("description") or ""
                if any(marker in description for marker in self._SECRET_DESC_MARKERS):
                    registered = _SECRET_ARGS_BY_TOOL.get(tool_name, frozenset())
                    if param not in registered:
                        unregistered.append(f"{tool_name}.{param}")
        assert not unregistered, (
            "secret-bearing parameter descriptions must be listed in "
            f"log_redaction._SECRET_ARGS_BY_TOOL (BUG-087): {unregistered}"
        )
