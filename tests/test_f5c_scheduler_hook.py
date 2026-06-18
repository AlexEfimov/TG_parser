"""Tests for the F5-C scheduler hook (run_resummarize_for_channel + _process_source wiring).

We mirror the F11 hook test pattern (``tests/test_f11_scheduler_hook.py``):

1. ``run_resummarize_for_channel`` builds a ``ResummarizationService`` from
   the ``resummarization_repos`` context, awaits ``run_for_channel``, and
   guarantees ``service.aclose()`` runs even when ``run_for_channel``
   raises (no leaked LLM connections / DB sessions).
2. The non-billing failure path mirrors F11's silent log: the *outer*
   ``_process_source`` block catches everything except billing into a
   ``logger.exception`` and the source-attempt success bit is unaffected.
3. ``AnthropicBillingError`` propagates up through
   ``run_resummarize_for_channel`` so the scheduler can register it in
   ``stage_errors`` and trigger ``_pause_source_for_billing`` (Decision
   #13 + Gotcha #16).
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeService:
    """Stand-in for :class:`ResummarizationService` in scheduler hook tests."""

    def __init__(
        self,
        *,
        result: dict[str, Any] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.result = (
            result
            if result is not None
            else {
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "skipped_breakdown": {},
                "tokens": 0,
            }
        )
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def run_for_channel(self, *, channel_id: str) -> dict[str, Any]:
        self.calls.append({"channel_id": channel_id})
        if self.raises is not None:
            raise self.raises
        return self.result

    async def aclose(self) -> None:
        self.closed = True


class _ReposCtx:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0
        self.last_exc: BaseException | None = None

    async def __aenter__(self):
        self.entered += 1
        return ("card_repo", "bundle_repo", "version_repo", "db")

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1
        self.last_exc = exc


def _patch_hook(monkeypatch, *, service: _FakeService):
    from tg_parser.services import scheduler_service

    repos_ctx = _ReposCtx()

    def _resummarization_repos():
        return repos_ctx

    def _service_factory(**_kwargs):
        return service

    db_context_module = __import__(
        "tg_parser.services.db_context", fromlist=["resummarization_repos"]
    )
    rs_module = __import__(
        "tg_parser.services.resummarization_service",
        fromlist=["ResummarizationService"],
    )

    monkeypatch.setattr(db_context_module, "resummarization_repos", _resummarization_repos)
    monkeypatch.setattr(rs_module, "ResummarizationService", _service_factory)
    return scheduler_service, repos_ctx


@pytest.mark.asyncio
async def test_happy_path_invokes_run_for_channel_and_closes(monkeypatch):
    fake = _FakeService(
        result={
            "candidates": 3,
            "resummarized": 2,
            "skipped": 1,
            "skipped_breakdown": {"locked": 1},
            "tokens": 4711,
        }
    )
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=fake)

    result = await scheduler_service.run_resummarize_for_channel(channel_id="crypto_news")

    assert result["candidates"] == 3
    assert result["resummarized"] == 2
    assert result["skipped"] == 1
    assert result["tokens"] == 4711
    assert repos_ctx.entered == 1
    assert repos_ctx.exited == 1
    assert fake.closed is True
    assert fake.calls == [{"channel_id": "crypto_news"}]


@pytest.mark.asyncio
async def test_aclose_called_even_when_run_for_channel_raises(monkeypatch):
    fake = _FakeService(raises=RuntimeError("llm down"))
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=fake)

    with pytest.raises(RuntimeError, match="llm down"):
        await scheduler_service.run_resummarize_for_channel(channel_id="crypto_news")

    assert repos_ctx.entered == 1
    assert repos_ctx.exited == 1
    assert fake.closed is True


@pytest.mark.asyncio
async def test_anthropic_billing_error_propagates(monkeypatch):
    """Gotcha #16: AnthropicBillingError must propagate, not be swallowed.

    The scheduler hook caller (``_process_source``) catches it separately
    and adds it to ``stage_errors`` so ``_pause_source_for_billing`` runs.
    A generic ``except Exception`` in the hook would silently log it and
    every subsequent tick would re-incur a billing error.
    """
    from tg_parser.processing.llm.errors import AnthropicBillingError

    billing = AnthropicBillingError("credit balance is too low")
    fake = _FakeService(raises=billing)
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=fake)

    with pytest.raises(AnthropicBillingError):
        await scheduler_service.run_resummarize_for_channel(channel_id="crypto_news")

    assert repos_ctx.exited == 1
    assert fake.closed is True


def _scheduler_module_source() -> str:
    import inspect

    from tg_parser.services import scheduler_service

    return inspect.getsource(scheduler_service)


def test_hook_runs_every_tick_decoupled_from_new_doc_refs():
    """The F5-C hook must run on EVERY tick, NOT gated by ``if new_doc_refs:``.

    NEW CONTRACT (age/freshness decoupling): the resummarize hook was
    moved OUT of the ``if new_doc_refs:`` block — mirroring how ENH-001
    placed the F11 watchlist check — so the age-based trigger
    (``RESUMMARIZE_MAX_AGE_DAYS``) can fire on quiet channels that never
    cross the counter threshold. Structurally that means the hook's
    ``try:`` sits at the outer (16-space) indentation of ``_process_source``,
    NOT nested one level deeper inside the ``if new_doc_refs:`` block.

    Ordering is still pinned (see
    ``test_hook_is_ordered_before_watchlist``): when there ARE new docs,
    topicization/embedding run first and resummarize still precedes the
    F11 watchlist so the matcher scores against the freshest summary.

    NB: ``_process_source`` is a closure inside
    ``run_incremental_for_all_sources``, so we inspect the module-level
    source rather than the function object — ``inspect.getsource`` on a
    nested ``async def`` is not reliable across Python versions.
    """
    src = _scheduler_module_source()

    # Decoupled placement: 16-space ``try:`` wrapping a 20-space call.
    decoupled = "\n                try:\n                    rs_summary = await run_resummarize_for_channel(channel_id=channel_id)\n"
    assert decoupled in src, (
        "F5-C hook must run on every tick at the outer (16-space) indentation "
        "of _process_source, decoupled from `if new_doc_refs:` so the "
        "age/freshness trigger fires on quiet channels."
    )

    # Guard against regressing to the old gated placement (24-space call
    # inside the deeper `if new_doc_refs:` block).
    gated = "                        rs_summary = await run_resummarize_for_channel("
    assert gated not in src, (
        "F5-C hook is gated inside `if new_doc_refs:` again — that re-couples "
        "the age trigger to new-doc ticks and starves quiet channels."
    )


def test_hook_is_ordered_before_watchlist():
    """The hook must run BETWEEN run_topic_embedding and watchlist_check_for_channel.

    This is a structural / source-level check: F11 watchlist scores
    against the freshest summary, so F5-C must precede the watchlist
    call. We check the source ordering rather than diffing line numbers
    so the test stays robust to refactors that don't change the order.

    NB: ``_process_source`` is a closure inside
    ``run_incremental_for_all_sources``, so we inspect the module-level
    source rather than the function object — ``inspect.getsource`` on a
    nested ``async def`` is not reliable across Python versions.
    """
    src = _scheduler_module_source()

    # We pin to the FIRST occurrence inside _process_source to keep
    # ordering checks unambiguous. The module also defines a top-level
    # `run_resummarize_for_channel` helper — that's expected and shows up
    # in `find` after the call site.
    embed_idx = src.find("await run_topic_embedding(channel_id=channel_id, force=False)")
    f5c_idx = src.find("rs_summary = await run_resummarize_for_channel(")
    watchlist_idx = src.find("wl_summary = await run_watchlist_check_for_channel(")

    assert embed_idx > 0, "run_topic_embedding missing — scheduler refactored?"
    assert f5c_idx > 0, "F5-C hook (rs_summary = ...) missing in _process_source"
    assert watchlist_idx > 0, "F11 watchlist call (wl_summary = ...) missing"
    assert embed_idx < f5c_idx < watchlist_idx, (
        "F5-C hook MUST run between run_topic_embedding and "
        "run_watchlist_check_for_channel so F11 scores against the freshest "
        "summary (Decision #8). Found ordering: "
        f"embed={embed_idx}, f5c={f5c_idx}, watchlist={watchlist_idx}"
    )


def test_stages_ok_only_appended_when_resummarized_positive():
    """Decision #13 detail: ``stages_ok.append("resummarize")`` must be
    guarded by ``rs_summary["resummarized"] > 0``.  A 0-result tick (no
    candidates, all locked, etc.) is a *non-event* — it shouldn't pad the
    per-source success log.  This is a source-level guard so it survives
    refactors that move the block around but keep the contract intact."""
    src = _scheduler_module_source()

    f5c_anchor = src.find("rs_summary = await run_resummarize_for_channel(")
    assert f5c_anchor > 0, "F5-C hook anchor missing"
    next_block = src.find("wl_summary = await run_watchlist_check_for_channel(", f5c_anchor)
    f5c_block = src[f5c_anchor:next_block]

    assert 'rs_summary["resummarized"] > 0' in f5c_block, (
        "Decision #13: stages_ok must be conditional on resummarized > 0; "
        "appending unconditionally turns every tick (even no-op ticks) "
        "into a 'resummarize' stage hit and obscures real activity."
    )
    # The append for resummarize must live inside the > 0 conditional.
    cond_idx = f5c_block.find('rs_summary["resummarized"] > 0')
    append_idx = f5c_block.find('stages_ok.append("resummarize")')
    assert append_idx > cond_idx, "stages_ok.append must follow the > 0 check"


def test_silent_log_not_in_stage_errors_for_generic_exception():
    """Decision #13: F5-C generic Exception → logger.exception, NOT stage_errors.

    Source-level invariant: the F5-C ``except Exception`` clause in
    ``_process_source`` must NOT call ``stage_errors.append``. Only the
    ``except AnthropicBillingError`` clause may do so.
    """
    src = _scheduler_module_source()

    f5c_anchor = src.find("rs_summary = await run_resummarize_for_channel(")
    assert f5c_anchor > 0, "F5-C hook anchor missing"
    next_block = src.find("wl_summary = await run_watchlist_check_for_channel(", f5c_anchor)
    assert next_block > 0, "F11 watchlist block missing"
    f5c_block = src[f5c_anchor:next_block]

    assert "except AnthropicBillingError" in f5c_block, (
        "AnthropicBillingError must be caught explicitly so billing-pause fires"
    )
    assert "except Exception" in f5c_block, "generic Exception clause missing"

    billing_idx = f5c_block.find("except AnthropicBillingError")
    generic_idx = f5c_block.find("except Exception")
    assert billing_idx < generic_idx, "billing clause must precede generic Exception"

    generic_block = f5c_block[generic_idx:]
    assert "stage_errors.append" not in generic_block, (
        "Decision #13 violated: F5-C generic Exception block must NOT add to "
        "stage_errors (silent log). Putting it there would mark the entire "
        "source-attempt as FAILED via `success = not stage_errors`."
    )
    assert "logger.exception" in generic_block, (
        "F5-C generic failure must be logged via logger.exception (F11-style silent log)."
    )
