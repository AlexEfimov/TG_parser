"""
BUG-011 regression suite — bot read-context preservation across turns
(Session H, 2026-05-03).

Six test classes, one per area:

* Class A — ``_refresh_read_context`` update logic (guard correctness)
* Class B — ``_read_context_for_agent`` resolution + TTL
* Class C — Agent injection (``process_message`` + ``_call_gemini``)
* Class D — Integration / end-to-end (direct BUG-011 regression)
* Class E — FSM-state interaction (preserve across state.clear())
* Class F — Prompt content contracts (version + section + D-6 wording)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.bot.agent import AgentResult, GeminiAgent
from tg_parser.bot.handlers import (
    READ_CONTEXT_TTL_SECONDS,
    _handle_confirmation_response,
    _handle_pagination_response,
    _read_context_for_agent,
    _refresh_read_context,
    cmd_start,
    handle_text,
)
from tg_parser.bot.states import ConfirmFlow, PaginationFlow, ReadContextData
from tg_parser.bot.tools import _READ_TOOLS_TRACKED_FOR_CONTEXT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(bot_id: int = 42, chat_id: int = 12345, user_id: int = 67890) -> FSMContext:
    """Real FSMContext backed by an in-memory storage — no aiogram bot required."""
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


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stale_iso(seconds: int = READ_CONTEXT_TTL_SECONDS + 1) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _fresh_iso() -> str:
    return (datetime.now(UTC) - timedelta(seconds=30)).isoformat()


def _make_read_context(
    channel_id: str = "AgeManagment",
    tool: str = "list_topics",
    *,
    stale: bool = False,
) -> ReadContextData:
    return ReadContextData(
        last_channel_id=channel_id,
        last_tool=tool,
        created_at=_stale_iso() if stale else _fresh_iso(),
    )


# ---------------------------------------------------------------------------
# Class A — _refresh_read_context guard logic
# ---------------------------------------------------------------------------


class TestRefreshReadContext:
    """A-class: ensure the update site writes only when it should."""

    async def test_a1_tracked_tool_with_channel_id_writes_context(self):
        """A1: tracked tool + channel_id → data updated."""
        state = _make_state()
        await _refresh_read_context(state, "list_topics", {"channel_id": "AgeManagment"})
        data = await state.get_data()
        rc = data.get("read_context")
        assert rc is not None
        assert rc["last_channel_id"] == "AgeManagment"
        assert rc["last_tool"] == "list_topics"
        assert "created_at" in rc

    async def test_a2_tracked_tool_without_channel_id_is_noop(self):
        """A2: tracked tool + channel_id missing → no-op."""
        state = _make_state()
        await _refresh_read_context(state, "list_topics", {})
        data = await state.get_data()
        assert data.get("read_context") is None

    async def test_a3_untracked_write_tool_is_noop(self):
        """A3: write-tool with channel_id → no-op (D-6 immunity)."""
        state = _make_state()
        await _refresh_read_context(state, "add_channel", {"channel_id": "AgeManagment"})
        data = await state.get_data()
        assert data.get("read_context") is None

    async def test_a4_tracked_tool_with_empty_string_channel_id_is_noop(self):
        """A4: tracked tool + empty-string channel_id → no-op."""
        state = _make_state()
        await _refresh_read_context(state, "ask_question", {"channel_id": ""})
        data = await state.get_data()
        assert data.get("read_context") is None

    async def test_a5_idempotent_refresh_updates_created_at(self):
        """A5: calling twice with same args refreshes created_at (no infinite loop)."""
        state = _make_state()
        await _refresh_read_context(state, "list_topics", {"channel_id": "AgeManagment"})
        data1 = await state.get_data()
        ts1 = data1["read_context"]["created_at"]

        await _refresh_read_context(state, "list_topics", {"channel_id": "AgeManagment"})
        data2 = await state.get_data()
        ts2 = data2["read_context"]["created_at"]

        # Both writes succeed; channel_id is stable
        assert data2["read_context"]["last_channel_id"] == "AgeManagment"
        # created_at is re-written (may be equal if < 1s elapsed, but not missing)
        assert ts2 >= ts1

    @pytest.mark.parametrize("tool", sorted(_READ_TOOLS_TRACKED_FOR_CONTEXT))
    async def test_a_r1_every_tracked_tool_has_channel_id_in_tool_declarations(self, tool: str):
        """R-1 contract: every tool in _READ_TOOLS_TRACKED_FOR_CONTEXT declares
        a channel_id parameter in TOOL_DECLARATIONS."""
        from tg_parser.bot.tools import TOOL_DECLARATIONS

        decl = next((d for d in TOOL_DECLARATIONS if d["name"] == tool), None)
        assert decl is not None, f"{tool} missing from TOOL_DECLARATIONS"
        props = decl.get("parameters", {}).get("properties", {})
        assert "channel_id" in props, (
            f"{tool} in _READ_TOOLS_TRACKED_FOR_CONTEXT but its TOOL_DECLARATIONS "
            f"schema has no channel_id property — D-2 contract violated"
        )


# ---------------------------------------------------------------------------
# Class B — _read_context_for_agent resolution + TTL
# ---------------------------------------------------------------------------


class TestReadContextForAgent:
    """B-class: resolver returns fresh context or None appropriately."""

    async def test_b1_no_data_returns_none(self):
        """B1: no data → None."""
        state = _make_state()
        result = await _read_context_for_agent(state)
        assert result is None

    async def test_b2_fresh_data_returns_context(self):
        """B2: fresh data → ReadContextData."""
        state = _make_state()
        rc = _make_read_context()
        await state.update_data(read_context=rc)
        result = await _read_context_for_agent(state)
        assert result is not None
        assert result["last_channel_id"] == "AgeManagment"

    async def test_b3_stale_data_returns_none(self):
        """B3: stale data (created_at > 15 min ago) → None."""
        state = _make_state()
        rc = _make_read_context(stale=True)
        await state.update_data(read_context=rc)
        result = await _read_context_for_agent(state)
        assert result is None

    async def test_b4_data_without_created_at_returns_none(self):
        """B4: data without created_at → defensive None (don't crash)."""
        state = _make_state()
        await state.update_data(read_context={"last_channel_id": "X", "last_tool": "list_topics"})
        result = await _read_context_for_agent(state)
        assert result is None

    async def test_b5_non_dict_read_context_returns_none(self):
        """B5: non-dict read_context (corrupted data) → None."""
        state = _make_state()
        await state.update_data(read_context="not-a-dict")
        result = await _read_context_for_agent(state)
        assert result is None


# ---------------------------------------------------------------------------
# Class C — Agent injection
# ---------------------------------------------------------------------------


class TestAgentReadContextInjection:
    """C-class: process_message passes read_context to _call_gemini correctly."""

    def _make_agent(self) -> GeminiAgent:
        return GeminiAgent(api_key="test-key")

    def _gemini_text_response(self, text: str) -> dict:
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": text}]},
                    "finishReason": "STOP",
                }
            ]
        }

    def _gemini_function_call(self, name: str, args: dict) -> dict:
        return {
            "candidates": [
                {
                    "content": {"parts": [{"functionCall": {"name": name, "args": args}}]},
                }
            ]
        }

    async def test_c1_no_read_context_does_not_inject_dynamic_block(self):
        """C1: process_message with read_context=None → runtime injection block absent.

        The static prompt text (bot.yaml) now mentions «Implicit channel context»
        as a section heading, so we check for the *dynamic* injection marker
        «The user has been reading from channel» which only appears when
        read_context is supplied programmatically.
        """
        agent = self._make_agent()
        captured_payloads: list[dict] = []

        async def _fake_post(url, *, json, params):
            captured_payloads.append(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = self._gemini_text_response("ok")
            return resp

        agent._client.post = _fake_post
        await agent.process_message("покажи темы", read_context=None)

        assert captured_payloads, "No Gemini call was made"
        system_text = captured_payloads[0]["systemInstruction"]["parts"][0]["text"]
        # The dynamic injection block is uniquely identified by the code-internal tag
        # "(read-side, BUG-011, Session H)" which is NOT in the static bot.yaml text.
        assert "(read-side, BUG-011, Session H)" not in system_text

    async def test_c2_with_read_context_injects_channel(self):
        """C2: process_message with read_context={...} → dynamic injection block present."""
        agent = self._make_agent()
        rc = _make_read_context("AgeManagment")
        captured_payloads: list[dict] = []

        async def _fake_post(url, *, json, params):
            captured_payloads.append(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = self._gemini_text_response("ok")
            return resp

        agent._client.post = _fake_post
        await agent.process_message("покажи темы", read_context=rc)

        assert captured_payloads
        system_text = captured_payloads[0]["systemInstruction"]["parts"][0]["text"]
        # Dynamic injection block must include channel name + code-internal tag
        assert "AgeManagment" in system_text
        assert "(read-side, BUG-011, Session H)" in system_text

    async def test_c3_agent_returns_read_tools_called_for_tracked_tool(self):
        """C3: when LLM calls list_topics(channel_id=X), result.read_tools_called is populated."""
        agent = self._make_agent()
        call_count = 0

        async def _fake_post(url, *, json, params):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count == 1:
                resp.json.return_value = self._gemini_function_call(
                    "list_topics", {"channel_id": "AgeManagment", "limit": 5}
                )
            else:
                resp.json.return_value = self._gemini_text_response("Показываю темы AgeManagment")
            return resp

        agent._client.post = _fake_post

        with patch(
            "tg_parser.bot.agent.execute_tool",
            new_callable=AsyncMock,
            return_value={
                "total": 5,
                "items": [],
                "offset": 0,
                "limit": 5,
                "has_more": False,
            },
        ):
            result = await agent.process_message("5 главных тем")

        assert len(result.read_tools_called) == 1
        tool_name, tool_args = result.read_tools_called[0]
        assert tool_name == "list_topics"
        assert tool_args["channel_id"] == "AgeManagment"

    async def test_c4_write_tool_not_in_read_tools_called(self):
        """C4: write-tool calls do NOT appear in read_tools_called (D-6)."""
        agent = self._make_agent()
        call_count = 0

        async def _fake_post(url, *, json, params):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count == 1:
                resp.json.return_value = self._gemini_function_call(
                    "add_channel", {"channel_id": "newchan", "confirm": False}
                )
            else:
                resp.json.return_value = self._gemini_text_response("preview done")
            return resp

        agent._client.post = _fake_post

        with patch(
            "tg_parser.bot.agent.execute_tool",
            new_callable=AsyncMock,
            return_value={"preview": True, "message": "preview"},
        ):
            result = await agent.process_message("добавь канал newchan")

        assert result.read_tools_called == []


# ---------------------------------------------------------------------------
# Class D — Integration / end-to-end
# ---------------------------------------------------------------------------


class TestBug011ReadContextPreservation:
    """D-class: direct BUG-011 regression + override + write-tool immunity."""

    async def test_d1_implicit_channel_context_preserved_across_read_turns(self):
        """D1: direct BUG-011 regression — turn 1 sets context, turn 2 agent receives it.

        Mock GeminiAgent: turn 1 emits list_topics(AgeManagment) → handler
        persists read_context. Turn 2 «покажи 5 главных тем» → agent must
        be called with read_context.last_channel_id == "AgeManagment".
        """
        state = _make_state()
        agent = MagicMock(spec=GeminiAgent)

        # Turn 1: LLM called list_topics with channel_id
        turn1_result = AgentResult(
            response_text="Темы канала AgeManagment (1-10 из 75): ...",
            read_tools_called=[("list_topics", {"channel_id": "AgeManagment", "limit": 10})],
        )
        agent.process_message = AsyncMock(return_value=turn1_result)

        msg1 = _make_message("темы канала AgeManagment")
        await handle_text(msg1, agent=agent, state=state, current_user=None)

        # FSMContext must now hold read_context
        data = await state.get_data()
        assert data.get("read_context") is not None
        assert data["read_context"]["last_channel_id"] == "AgeManagment"

        # Turn 2: ambiguous follow-up — agent must be called WITH read_context
        turn2_result = AgentResult(
            response_text="Топ-5 тем канала AgeManagment: ...",
            read_tools_called=[("list_topics", {"channel_id": "AgeManagment", "limit": 5})],
        )
        agent.process_message = AsyncMock(return_value=turn2_result)

        msg2 = _make_message("покажи 5 главных тем")
        await handle_text(msg2, agent=agent, state=state, current_user=None)

        # Assert agent was called with the preserved read_context
        call_kwargs = agent.process_message.call_args
        assert call_kwargs.kwargs.get("read_context") is not None, (
            "BUG-011 regression: handle_text did not pass read_context to agent on turn 2"
        )
        assert call_kwargs.kwargs["read_context"]["last_channel_id"] == "AgeManagment"

    async def test_d2_explicit_channel_context_is_not_blocked_by_stale_implicit(self):
        """D2: stale implicit context does not interfere — agent receives None read_context."""
        state = _make_state()
        stale_rc = _make_read_context("OldChannel", stale=True)
        await state.update_data(read_context=stale_rc)

        agent = MagicMock(spec=GeminiAgent)
        agent.process_message = AsyncMock(
            return_value=AgentResult(response_text="ok", read_tools_called=[])
        )

        msg = _make_message("темы канала Lab4health")
        await handle_text(msg, agent=agent, state=state, current_user=None)

        call_kwargs = agent.process_message.call_args
        assert call_kwargs.kwargs.get("read_context") is None, (
            "Stale read_context must not be injected — agent should receive None"
        )

    async def test_d3_write_tool_call_with_active_read_context_does_not_auto_fill(self):
        """D3: D-6 immunity — active read_context must NOT appear in read_tools_called
        after a write-tool call (write tools use explicit channel_id only)."""
        state = _make_state()
        # Pre-seed a fresh read_context
        await state.update_data(read_context=_make_read_context("AgeManagment"))

        agent = MagicMock(spec=GeminiAgent)
        # Agent returns a write-tool preview (add_channel), no read_tools_called
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="preview: удалить канал AgeManagment?",
                preview_pending={
                    "tool_name": "remove_channel",
                    "args": {"channel_id": "AgeManagment"},
                },
                read_tools_called=[],
            )
        )

        msg = _make_message("удали канал")
        await handle_text(msg, agent=agent, state=state, current_user=None)

        # read_context should be UNCHANGED (still AgeManagment from before)
        data = await state.get_data()
        assert data.get("read_context") is not None
        assert data["read_context"]["last_channel_id"] == "AgeManagment"
        # pending_action should exist for ConfirmFlow
        assert data.get("pending_action") is not None
        assert data["pending_action"]["tool_name"] == "remove_channel"


# ---------------------------------------------------------------------------
# Class E — FSM-state interaction
# ---------------------------------------------------------------------------


class TestReadContextFsmInteraction:
    """E-class: read_context persists across ConfirmFlow / PaginationFlow clear()."""

    async def test_e1_read_context_preserved_across_confirm_flow_yes(self):
        """E1: read sets context, write-preview triggers ConfirmFlow, user says «да»,
        confirm executes, read_context still in data after state.clear()."""
        state = _make_state()
        rc = _make_read_context("AgeManagment")
        await state.update_data(read_context=rc)

        # Arm ConfirmFlow
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": "remove_channel", "args": {"channel_id": "AgeManagment"}},
            created_at=_fresh_iso(),
            read_context=rc,
        )

        agent = MagicMock(spec=GeminiAgent)
        msg = _make_message("да")

        with patch(
            "tg_parser.bot.handlers.execute_tool",
            new_callable=AsyncMock,
            return_value={"message": "канал удалён", "preview": False},
        ):
            await _handle_confirmation_response(msg, agent=agent, state=state, current_user=None)

        data = await state.get_data()
        assert data.get("read_context") is not None, (
            "read_context must survive state.clear() in _handle_confirmation_response"
        )
        assert data["read_context"]["last_channel_id"] == "AgeManagment"

    async def test_e2_read_context_preserved_across_confirm_flow_reject(self):
        """E2: user says «нет» in ConfirmFlow → state cleared but read_context kept."""
        state = _make_state()
        rc = _make_read_context("AgeManagment")

        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": "remove_channel", "args": {"channel_id": "AgeManagment"}},
            created_at=_fresh_iso(),
            read_context=rc,
        )

        agent = MagicMock(spec=GeminiAgent)
        msg = _make_message("нет")
        await _handle_confirmation_response(msg, agent=agent, state=state, current_user=None)

        data = await state.get_data()
        assert data.get("read_context") is not None
        assert data["read_context"]["last_channel_id"] == "AgeManagment"

    async def test_e3_read_context_preserved_across_pagination_stop(self):
        """E3: user says «стоп» in PaginationFlow → state cleared but read_context kept."""
        state = _make_state()
        rc = _make_read_context("AgeManagment")

        await state.set_state(PaginationFlow.has_active_list)
        await state.update_data(
            pagination={
                "tool_name": "list_topics",
                "args": {"channel_id": "AgeManagment", "limit": 10, "offset": 10},
                "total": 75,
                "offset": 10,
                "limit": 10,
            },
            items_shown=10,
            created_at=_fresh_iso(),
            read_context=rc,
        )

        agent = MagicMock(spec=GeminiAgent)
        msg = _make_message("стоп")
        await _handle_pagination_response(msg, agent=agent, state=state, current_user=None)

        data = await state.get_data()
        assert data.get("read_context") is not None
        assert data["read_context"]["last_channel_id"] == "AgeManagment"

    async def test_e4_read_context_cleared_on_cmd_start(self):
        """E4: /start clears read_context (D-7 Альт A)."""
        state = _make_state()
        rc = _make_read_context("AgeManagment")
        await state.update_data(read_context=rc)

        msg = _make_message("/start")
        # Simulate a registered user so we don't exit early
        from tg_parser.auth.models import CurrentUser

        fake_user = MagicMock(spec=CurrentUser)
        fake_user.id = "real-user-uuid"
        fake_user.name = "Alice"
        fake_user.role = "admin"
        fake_user.allowed_channel_ids = None

        await cmd_start(msg, state=state, current_user=fake_user)

        data = await state.get_data()
        assert data.get("read_context") is None, "/start must clear read_context (D-7 Альт A)"

    async def test_e5_read_context_preserved_across_pagination_last_page(self):
        """E5: pagination reaches last page → state.clear() but read_context kept."""
        state = _make_state()
        rc = _make_read_context("AgeManagment")

        await state.set_state(PaginationFlow.has_active_list)
        await state.update_data(
            pagination={
                "tool_name": "list_topics",
                "args": {"channel_id": "AgeManagment", "limit": 10, "offset": 10},
                "total": 15,
                "offset": 10,
                "limit": 10,
            },
            items_shown=10,
            created_at=_fresh_iso(),
            read_context=rc,
        )

        agent = MagicMock(spec=GeminiAgent)
        msg = _make_message("ещё")

        # Return a result with no pagination_pending (last page)
        with patch(
            "tg_parser.bot.handlers.execute_tool",
            new_callable=AsyncMock,
            return_value={
                "total": 15,
                "items": [{"n": 11, "title": "Topic 11"}],
                "offset": 10,
                "limit": 10,
                "has_more": False,
            },
        ):
            await _handle_pagination_response(msg, agent=agent, state=state, current_user=None)

        data = await state.get_data()
        assert data.get("read_context") is not None
        assert data["read_context"]["last_channel_id"] == "AgeManagment"


# ---------------------------------------------------------------------------
# Class F — Prompt content contracts
# ---------------------------------------------------------------------------


class TestBotPromptBug011ReadContextDirective:
    """F-class: pin the BUG-011 prompt section so future sweeps can't silently drop it.

    Mirrors the BUG-012 TestBotPromptBug012FormatDirective pattern from
    tests/test_rag_prompt_config.py.
    """

    def _load_prompt(self) -> str:
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        return config["system"]["prompt"]

    def _load_version(self) -> str:
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        return config["metadata"]["version"]

    def test_f1_bot_yaml_version_at_least_1_6_0(self):
        """F1: bot.yaml metadata.version must be >= 1.6.0 since BUG-011 landed."""
        version = self._load_version()
        major, minor, patch = (int(p) for p in version.split("."))
        assert (major, minor, patch) >= (1, 6, 0), (
            f"bot.yaml version regressed below 1.6.0: {version!r} "
            "(BUG-011 implicit channel context section must remain)"
        )

    def test_f2_bot_yaml_mentions_bug_011_implicit_context(self):
        """F2: prompt must contain a BUG-011 section tag."""
        prompt = self._load_prompt()
        assert "BUG-011" in prompt, (
            "bot.yaml lost BUG-011 tag — implicit channel context section likely dropped"
        )
        assert "Implicit channel context" in prompt, (
            "bot.yaml must contain the 'Implicit channel context' section heading"
        )

    def test_f3_bot_yaml_d6_write_tool_immunity(self):
        """F3: prompt must explicitly prohibit write-tools from using implicit context,
        and enumerate the write-tool names (D-6 immunity rule)."""
        prompt = self._load_prompt()
        # Must mention the hard rule
        assert "NEVER apply" in prompt or "HARD RULE" in prompt, (
            "bot.yaml implicit context section must state the D-6 NEVER/HARD RULE"
        )
        # Must enumerate write-tools by name
        for write_tool in ("add_channel", "remove_channel", "pause_channel", "resume_channel"):
            assert write_tool in prompt, (
                f"bot.yaml D-6 immunity rule must enumerate {write_tool!r} by name"
            )
