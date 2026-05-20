"""
Regression test for BUG-017 — misleading scheduler log "[3/4]
Topicization skipped (--skip-topicize)".

Bug history: surfaced 2026-05-15 by the Claude MCP testing session
(Phase 4). The original literal `Topicization skipped (--skip-topicize)`
reads as if a runtime CLI flag was passed and could be unset — but the
scheduler hardcodes `skip_topicize=True` at
`tg_parser/services/scheduler_service.py:186` because topicization is
intentionally a separate manual workflow via
`tg-parser topicize <channel>`. The misleading wording cost the session
operator ~2h of wrong-hypothesis investigation.

Closure contract:

1. The log line must clearly communicate that topicization is
   intentionally skipped «by design» and that operators should run
   `tg-parser topicize <channel>` manually.
2. The `(--skip-topicize)` literal (which looks like a runtime flag) is
   removed so future log readers do not chase a non-existent CLI flag.

This is a pinning test — it locks the message wording so future
refactors cannot silently regress the fix.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.services import pipeline_service


@pytest.mark.asyncio
async def test_topicization_skipped_log_no_longer_mentions_runtime_flag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``run_full_pipeline`` is invoked with ``skip_topicize=True``
    (which is the scheduler's only mode of invocation), the emitted log
    line must NOT carry the misleading ``(--skip-topicize)`` literal and
    MUST explain that this is by-design + how to topicize manually."""

    async def _fake_ingestion_state_repo(*_a: object, **_kw: object):
        repo = AsyncMock()
        repo.get_source = AsyncMock(return_value=None)
        return repo, AsyncMock()

    async def _fake_export(**_kwargs: object) -> dict:
        return {"kb_entries_count": 0, "topics_count": 0}

    with (
        patch.object(
            pipeline_service,
            "_get_channel_id_from_source",
            AsyncMock(return_value="test_channel"),
        ),
        patch.object(
            pipeline_service,
            "run_export",
            side_effect=_fake_export,
        ),
        caplog.at_level(logging.INFO, logger="tg_parser.services.pipeline_service"),
    ):
        await pipeline_service.run_full_pipeline(
            source_id="test_source",
            output_dir="/tmp/_bug017_unused",
            mode="incremental",
            skip_ingest=True,
            skip_process=True,
            skip_topicize=True,
        )

    topicize_messages = [
        rec.getMessage()
        for rec in caplog.records
        if "[3/4] Topicization skipped" in rec.getMessage()
    ]

    assert topicize_messages, (
        "expected a `[3/4] Topicization skipped` log line on the skip_topicize=True path"
    )

    msg = topicize_messages[0]

    assert "--skip-topicize" not in msg, (
        "log message must not mention the misleading ``(--skip-topicize)`` "
        "literal (BUG-017 — it reads as a runtime CLI flag but is hardcoded "
        "in scheduler_service)"
    )
    assert "by design" in msg, "log message must communicate that the skip is by-design"
    assert "tg-parser topicize" in msg, (
        "log message must point operators at the manual topicize command"
    )
