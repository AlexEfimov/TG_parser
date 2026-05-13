"""F4-B Core — Phase 5 deferred-feature surface guards.

The start prompt locks Q3 (Bot tools), Q7 (F11 watchlist), Q8 (F6 digest) as
**deferred**: no ``workspace_id`` parameter on those subscription / tool
signatures in this sprint. These tests fail loudly if a future commit
accidentally promotes one of them — at which point the contract should be
re-evaluated through a planning round-trip, not silently absorbed.

Cheap, signature-only inspections (no DB, no fixtures, no PG gate) so they
run in the default ``pytest`` mode too.
"""

from __future__ import annotations

import inspect


def _parameter_names(fn) -> list[str]:
    return list(inspect.signature(fn).parameters.keys())


class TestQ3BotToolsNoWorkspaceParam:
    """Q3 = skip-Bot-MVP — bot tool exec functions must not accept
    ``workspace_id`` in this sprint (would imply Bot UX work that's
    deferred until UX-signal accumulates)."""

    def test_bot_exec_functions_do_not_take_workspace_id(self):
        from tg_parser.bot import tools as bot_tools

        offenders: list[str] = []
        for name in dir(bot_tools):
            if not name.startswith("_exec_"):
                continue
            fn = getattr(bot_tools, name)
            if not callable(fn):
                continue
            params = _parameter_names(fn)
            if "workspace_id" in params:
                offenders.append(f"{name}({', '.join(params)})")
        assert offenders == [], (
            "Q3 was locked = skip-Bot-MVP but the following bot exec fns "
            f"now accept workspace_id: {offenders}. Re-check planning before "
            "promoting."
        )


class TestQ7WatchlistSignatureUnchanged:
    """Q7 = C — ``subscribe_watchlist`` MCP tool and ``WatchInterest`` schema
    must NOT have ``workspace_id`` in F4-B Core."""

    def test_subscribe_watchlist_mcp_tool_has_no_workspace_id(self):
        from tg_parser.mcp_server import subscribe_watchlist

        params = _parameter_names(subscribe_watchlist)
        assert "workspace_id" not in params, (
            "Q7 locked = defer F11 + workspace_id integration; "
            f"subscribe_watchlist now has params {params}"
        )

    def test_watch_interest_model_has_no_workspace_id(self):
        from tg_parser.domain.models import WatchInterest

        fields = set(WatchInterest.model_fields.keys())
        assert "workspace_id" not in fields, (
            "Q7 locked = WatchInterest schema must stay workspace-free in F4-B Core; "
            f"current fields = {sorted(fields)}"
        )


class TestQ8DigestSignatureUnchanged:
    """Q8 = C — ``subscribe_digest`` MCP tool and ``DigestSubscription``
    schema keep F4-A shape."""

    def test_subscribe_digest_mcp_tool_has_no_workspace_id(self):
        from tg_parser.mcp_server import subscribe_digest

        params = _parameter_names(subscribe_digest)
        assert "workspace_id" not in params, (
            "Q8 locked = defer F6 + workspace_id integration; "
            f"subscribe_digest now has params {params}"
        )

    def test_digest_subscription_model_has_no_workspace_id(self):
        from tg_parser.domain.models import DigestSubscription

        fields = set(DigestSubscription.model_fields.keys())
        assert "workspace_id" not in fields, (
            "Q8 locked = DigestSubscription schema must stay workspace-free in "
            f"F4-B Core; current fields = {sorted(fields)}"
        )


class TestScopedReadToolsAcceptWorkspaceId:
    """Positive mirror — Phase 4 promised the 8 scoped read-tools all gain
    an optional ``workspace_id`` parameter. Pin that surface so a future
    refactor that drops the parameter from any of them is caught here."""

    SCOPED_TOOLS = (
        "list_channels",
        "list_topics",
        "get_topic_details",
        "search_knowledge_base",
        "ask_question",
        "get_document",
        "get_cross_channel_stats",
        "get_related_topics",
    )

    def test_all_eight_scoped_tools_accept_workspace_id(self):
        from tg_parser import mcp_server

        missing: list[str] = []
        for name in self.SCOPED_TOOLS:
            fn = getattr(mcp_server, name)
            params = _parameter_names(fn)
            if "workspace_id" not in params:
                missing.append(name)
        assert missing == [], (
            f"Phase 4 promised workspace_id on every scoped read-tool; missing on: {missing}"
        )

    def test_workspace_id_parameter_defaults_to_none(self):
        """The default must be ``None`` so that legacy callers (without the
        parameter) get bit-for-bit F4-A behaviour (hidden gotcha § 1)."""
        from tg_parser import mcp_server

        wrong_default: list[str] = []
        for name in self.SCOPED_TOOLS:
            fn = getattr(mcp_server, name)
            sig = inspect.signature(fn)
            default = sig.parameters["workspace_id"].default
            if default is not None:
                wrong_default.append(f"{name}={default!r}")
        assert wrong_default == [], (
            f"workspace_id default must be None (F4-A bit-for-bit). Offenders: {wrong_default}"
        )
