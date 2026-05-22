"""F4-B Core — Phase 5 surface guards (Q3 / Q7 / Q8 / scoped read-tools).

Originally locked Q3/Q7/Q8 as deferred (no ``workspace_id`` on those
signatures). Wave 1 step 3 commit 1/4 (ENH-9 + BUG-022 service-layer
foundation) explicitly lifts Q7 + Q8 — see
``docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`` §3 (Q-OPEN-3)
and §8 PR shape table commit 1/4. The Q7/Q8 sections are inverted here:
they now PIN ``workspace_id`` as part of the new contract so a future
commit cannot drop the parameter silently. Q3 (bot exec fn Python
signature) stays deferred — bot wrappers still take a single ``args``
dict, and ``workspace_id`` is read from that dict rather than from the
Python signature (per Q-OPEN-6).

Cheap, signature-only inspections (no DB, no fixtures, no PG gate) so they
run in the default ``pytest`` mode too.
"""

from __future__ import annotations

import inspect


def _parameter_names(fn) -> list[str]:
    return list(inspect.signature(fn).parameters.keys())


class TestQ3BotToolsNoWorkspaceParam:
    """Q3 = skip-Bot-MVP — bot tool exec **Python signatures** must not
    accept ``workspace_id`` directly.

    Wave 1 step 3 reads ``workspace_id`` from the JSON ``args`` dict
    that bot wrappers already receive — this guard still holds because
    no exec fn promotes the parameter to its own argument list.
    """

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
            "Q3 was locked = skip-Bot-MVP and bot exec fns still must read "
            "workspace_id from the args-dict (see Q-OPEN-6 in "
            "docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md); "
            f"offenders: {offenders}."
        )


class TestQ7WatchlistSignatureHasWorkspaceId:
    """Q7 LIFTED in Wave 1 step 3 commit 1/4 (ENH-9).

    Pins ``workspace_id`` as part of the new contract for the F11
    ``subscribe_watchlist`` MCP tool and the ``WatchInterest`` Pydantic
    model. Default must remain ``None`` so legacy callers (no kwarg)
    preserve bit-for-bit F4-A behaviour (NULL column).
    """

    def test_subscribe_watchlist_mcp_tool_accepts_workspace_id(self):
        from tg_parser.mcp_server import subscribe_watchlist

        params = _parameter_names(subscribe_watchlist)
        assert "workspace_id" in params, (
            "ENH-9 contract requires workspace_id on subscribe_watchlist; "
            f"current params = {params}"
        )
        default = inspect.signature(subscribe_watchlist).parameters["workspace_id"].default
        assert default is None, (
            "workspace_id default must be None on subscribe_watchlist "
            f"(legacy callers must keep bit-for-bit behaviour); got {default!r}"
        )

    def test_watch_interest_model_has_workspace_id(self):
        from tg_parser.domain.models import WatchInterest

        fields = set(WatchInterest.model_fields.keys())
        assert "workspace_id" in fields, (
            "ENH-9 contract requires workspace_id field on WatchInterest; "
            f"current fields = {sorted(fields)}"
        )
        default = WatchInterest.model_fields["workspace_id"].default
        assert default is None, (
            "WatchInterest.workspace_id must default to None so legacy "
            f"INSERTs leave the column NULL; got {default!r}"
        )


class TestQ8DigestSignatureHasWorkspaceId:
    """Q8 LIFTED in Wave 1 step 3 commit 1/4 (ENH-9).

    Mirrors ``TestQ7WatchlistSignatureHasWorkspaceId`` for the F6
    ``subscribe_digest`` MCP tool and the ``DigestSubscription`` model.
    """

    def test_subscribe_digest_mcp_tool_accepts_workspace_id(self):
        from tg_parser.mcp_server import subscribe_digest

        params = _parameter_names(subscribe_digest)
        assert "workspace_id" in params, (
            f"ENH-9 contract requires workspace_id on subscribe_digest; current params = {params}"
        )
        default = inspect.signature(subscribe_digest).parameters["workspace_id"].default
        assert default is None, (
            f"workspace_id default must be None on subscribe_digest; got {default!r}"
        )

    def test_digest_subscription_model_has_workspace_id(self):
        from tg_parser.domain.models import DigestSubscription

        fields = set(DigestSubscription.model_fields.keys())
        assert "workspace_id" in fields, (
            "ENH-9 contract requires workspace_id field on DigestSubscription; "
            f"current fields = {sorted(fields)}"
        )
        default = DigestSubscription.model_fields["workspace_id"].default
        assert default is None, (
            f"DigestSubscription.workspace_id must default to None; got {default!r}"
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
