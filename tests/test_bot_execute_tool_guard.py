"""BUG-009 (Session G) — server-side ConfirmFlow guard in ``execute_tool``.

The guard rejects any call to a write-tool with ``confirm=True`` that is
not paired with a matching ``confirm_flow_state`` snapshot — closing the
LLM-hallucination class structurally on top of the prompt v1.3.0/v1.4.0
hard rules (defense-in-depth).

Test layout:

* **Class A — Guard reject paths.** All five mismatch flavours
  (no state / wrong tool / extra / missing / changed args) return
  ``error_class="ConfirmFlowMismatch"`` and the executor is *never*
  invoked (witnessed via a sentinel ``executor_called`` flag).
* **Class B — Guard pass paths.** The three legitimate paths
  (matching state, read-tools, ``confirm=False`` previews) reach the
  executor and return its payload unchanged.
* **Class C — Edge cases.** Unknown-tool errors keep the
  ``UnknownTool`` class (the guard runs only for known write-tools)
  and dict-ordering does not falsify the match.
* **Class D — Bidirectional contract (R-1 mitigation).** Asserts
  ``forall tool t: t has confirm BOOLEAN parameter in its Gemini
  declaration ⇔ t ∈ _WRITE_TOOLS_REQUIRING_CONFIRM``. Forward direction
  catches new write-tools added without registering in the guard set;
  reverse direction catches accidental over-trim during refactors.

See ``docs/notes/BUG_LOG.md`` § BUG-009 for the production trace and
``docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md``
§ 3.4 for the test-plan rationale.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from tg_parser.bot.tools import (
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    TOOL_DECLARATIONS,
    execute_tool,
)


def _record_executor() -> tuple[list[dict[str, Any]], Any]:
    """Build a fake executor that records its invocation args.

    Returns ``(invocations, executor)`` so tests can assert on whether
    the guard let the call through.
    """
    invocations: list[dict[str, Any]] = []

    async def _fake(args, **_kw):
        invocations.append(dict(args))
        return {"ok": True}

    return invocations, _fake


# ---------------------------------------------------------------------------
# Class A — Guard reject paths (BUG-009 closure)
# ---------------------------------------------------------------------------


class TestGuardRejectPaths:
    async def test_llm_issued_confirm_true_without_state_rejected(self) -> None:
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"add_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "X", "confirm": True},
            )

        assert result["error_class"] == "ConfirmFlowMismatch"
        assert "without an active ConfirmFlow FSM state" in result["error"]
        assert "BUG-009" in result["error"]
        assert invocations == [], "executor must not run when guard rejects"

    async def test_tool_name_mismatch_rejected(self) -> None:
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"remove_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "remove_channel",
                {"channel_id": "X", "confirm": True},
                confirm_flow_state={
                    "tool_name": "add_channel",
                    "args": {"channel_id": "X"},
                },
            )

        assert result["error_class"] == "ConfirmFlowMismatch"
        assert "tool mismatch" in result["error"]
        assert "add_channel" in result["error"]
        assert "remove_channel" in result["error"]
        assert invocations == []

    async def test_args_mismatch_rejected_extra_keys(self) -> None:
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"add_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "X", "confirm": True, "extra": "injected"},
                confirm_flow_state={
                    "tool_name": "add_channel",
                    "args": {"channel_id": "X"},
                },
            )

        assert result["error_class"] == "ConfirmFlowMismatch"
        assert "args mismatch" in result["error"]
        assert "extra=" in result["error"]
        assert "'extra'" in result["error"]
        assert invocations == []

    async def test_args_mismatch_rejected_missing_keys(self) -> None:
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"add_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "add_channel",
                {"confirm": True},
                confirm_flow_state={
                    "tool_name": "add_channel",
                    "args": {"channel_id": "X"},
                },
            )

        assert result["error_class"] == "ConfirmFlowMismatch"
        assert "args mismatch" in result["error"]
        assert "missing=" in result["error"]
        assert "'channel_id'" in result["error"]
        assert invocations == []

    async def test_args_mismatch_rejected_changed_value(self) -> None:
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"add_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "DIFFERENT", "confirm": True},
                confirm_flow_state={
                    "tool_name": "add_channel",
                    "args": {"channel_id": "X"},
                },
            )

        assert result["error_class"] == "ConfirmFlowMismatch"
        assert "args mismatch" in result["error"]
        assert "changed=" in result["error"]
        assert "'channel_id'" in result["error"]
        assert invocations == []


# ---------------------------------------------------------------------------
# Class B — Guard pass paths (Session D legitimate paths preserved)
# ---------------------------------------------------------------------------


class TestGuardPassPaths:
    async def test_legitimate_confirm_via_handler_executes(self) -> None:
        """Direct regression for ``handlers._handle_confirmation_response``.

        The handler passes ``confirm_flow_state`` whose ``tool_name`` and
        original ``args`` match the call → guard passes, executor runs."""
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"add_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "X", "confirm": True},
                confirm_flow_state={
                    "tool_name": "add_channel",
                    "args": {"channel_id": "X"},
                },
            )

        assert result == {"ok": True}
        assert invocations == [{"channel_id": "X", "confirm": True}]

    async def test_read_tool_with_confirm_true_passthrough(self) -> None:
        """Read-tools are not in ``_WRITE_TOOLS_REQUIRING_CONFIRM`` —
        the guard does not apply, the executor runs as usual."""
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"list_topics": fake},
            clear=False,
        ):
            result = await execute_tool(
                "list_topics",
                {"channel_id": "X", "confirm": True},
            )

        assert result == {"ok": True}
        assert invocations == [{"channel_id": "X", "confirm": True}]

    async def test_write_tool_with_confirm_false_passthrough(self) -> None:
        """``confirm=False`` is a preview — guard does not apply, executor runs."""
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"add_channel": fake},
            clear=False,
        ):
            result = await execute_tool(
                "add_channel",
                {"channel_id": "X", "confirm": False},
            )

        assert result == {"ok": True}
        assert invocations == [{"channel_id": "X", "confirm": False}]


# ---------------------------------------------------------------------------
# Class C — Edge cases
# ---------------------------------------------------------------------------


class TestGuardEdgeCases:
    async def test_unknown_tool_with_confirm_true_returns_unknown_tool(self) -> None:
        """Guard runs only for tools in ``_WRITE_TOOLS_REQUIRING_CONFIRM``;
        unknown tools fall through to the existing ``UnknownTool`` branch.
        """
        result = await execute_tool(
            "definitely_not_a_real_tool",
            {"confirm": True},
        )

        assert result["error_class"] == "UnknownTool"
        assert "Unknown tool" in result["error"]
        assert "ConfirmFlow" not in result["error"]

    async def test_state_match_passes_regardless_of_dict_ordering(self) -> None:
        """``==`` on dicts is order-insensitive — multi-arg calls still
        match when the snapshot args were stored with a different
        insertion order. Guards against R-2 (dict-ordering false negative).
        """
        invocations, fake = _record_executor()
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"set_llm_config": fake},
            clear=False,
        ):
            # Snapshot args ordering: scope, provider, model
            snapshot = {"scope": "global", "provider": "openai", "model": "gpt-4o"}
            # Call args ordering: model, scope, provider, confirm — dict ordering differs
            call_args = {
                "model": "gpt-4o",
                "scope": "global",
                "provider": "openai",
                "confirm": True,
            }
            result = await execute_tool(
                "set_llm_config",
                call_args,
                confirm_flow_state={
                    "tool_name": "set_llm_config",
                    "args": snapshot,
                },
            )

        assert result == {"ok": True}
        assert len(invocations) == 1


# ---------------------------------------------------------------------------
# Class D — Bidirectional contract (R-1 mitigation)
# ---------------------------------------------------------------------------


def _tools_with_confirm_param() -> set[str]:
    """Tools whose Gemini declaration carries a ``confirm: BOOLEAN`` parameter."""
    matched: set[str] = set()
    for decl in TOOL_DECLARATIONS:
        params = decl.get("parameters", {}) or {}
        properties = params.get("properties", {}) or {}
        confirm = properties.get("confirm")
        if isinstance(confirm, dict) and confirm.get("type") == "BOOLEAN":
            matched.add(decl["name"])
    return matched


class TestWriteToolsContract:
    """Forward + reverse equivalence between declared confirm-param and guard set.

    R-1 mitigation per Session G runbook § 7. A failure here means the
    guard set drifted out of sync with ``TOOL_DECLARATIONS``:

    * Forward (``declared ⊆ set``) — a new write-tool was added with a
      ``confirm`` parameter but not registered in
      ``_WRITE_TOOLS_REQUIRING_CONFIRM``: the guard would silently skip
      it and BUG-009 reopens for that tool.
    * Reverse (``set ⊆ declared``) — the guard set still contains a
      tool whose ``confirm`` parameter was removed: dead-code that may
      fool reviewers about the actual contract surface.
    """

    def test_forward_every_declared_confirm_tool_is_in_guard_set(self) -> None:
        declared = _tools_with_confirm_param()
        missing = declared - _WRITE_TOOLS_REQUIRING_CONFIRM
        assert not missing, (
            f"Tools have a confirm BOOLEAN parameter but are NOT in "
            f"_WRITE_TOOLS_REQUIRING_CONFIRM: {sorted(missing)}. "
            "Add them to the guard set in tg_parser/bot/tools.py — see "
            "BUG_LOG.md § BUG-009 for the rationale."
        )

    def test_reverse_every_guard_set_tool_has_declared_confirm_param(self) -> None:
        declared = _tools_with_confirm_param()
        extra = _WRITE_TOOLS_REQUIRING_CONFIRM - declared
        assert not extra, (
            f"Tools are in _WRITE_TOOLS_REQUIRING_CONFIRM but lack a "
            f"confirm BOOLEAN parameter in TOOL_DECLARATIONS: {sorted(extra)}. "
            "Either restore the parameter or remove from the guard set."
        )

    def test_guard_set_matches_known_session_g_baseline(self) -> None:
        """Belt-and-braces: pin the canonical 7-tool baseline so a
        future drift produces an explicit diff in CI rather than
        silently widening / narrowing the guard scope.
        """
        assert _WRITE_TOOLS_REQUIRING_CONFIRM == frozenset(
            {
                "add_channel",
                "remove_channel",
                "pause_channel",
                "resume_channel",
                "trigger_pipeline",
                "set_llm_config",
                "reset_llm_config",
            }
        )
