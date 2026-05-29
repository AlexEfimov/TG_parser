"""ENH-001 — ``last_checked_at`` honest matcher-liveness telemetry.

Background (see ``docs/notes/BUG_LOG.md`` § ENH-001 + the OBS-001 closure
block above it): ``last_checked_at`` used to mean "last hourly tick that
found NEW docs for a watched channel", which read to operators as "last time
this interest was evaluated". It stayed null/stale for new interests and
quiet channels even though the matcher was healthy (the OBS-001 symptom).

Fix (option (b)): ``WatchlistService.check_interests`` now stamps
``last_checked_at`` on EVERY active interest on EVERY tick — including quiet
ticks with an empty ``new_doc_refs`` — so the field honestly reflects
evaluation cadence. Matching behaviour is unchanged (scoring still requires
new docs).

These tests pin both halves of the decision:

1. ``test_check_interests_touches_last_checked_at_on_empty_tick`` (PG-gated):
   the regression the operator mandated — a ``candidates=0`` /
   empty-``new_doc_refs`` tick MUST advance ``last_checked_at`` for active
   interests (and must leave inactive ones untouched). This FAILS before the
   fix (the old early-return skipped the stamp).
2. ``test_trigger_pipeline_path_does_not_wire_matcher``: pins the chosen
   behaviour that the manual ``trigger_pipeline`` path (``run_full_pipeline``)
   does NOT run the watchlist matcher and therefore does NOT advance
   ``last_checked_at``. If someone later wires the matcher into the pipeline,
   this test fails and forces a conscious decision (+ doc update).
"""

from __future__ import annotations

import inspect
import os
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from tg_parser.domain.models import NotifyMode, WatchInterest
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.watch_interest_repo import SAWatchInterestRepo
from tg_parser.storage.sqlalchemy.watch_match_repo import SAWatchMatchRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ----------------------------------------------------------------------------
# Fixtures (mirror tests/test_f11_watchlist_repo.py)
# ----------------------------------------------------------------------------


@pytest.fixture
async def _watchlist_db(test_db):
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM watch_matches"))
        await session.execute(text("DELETE FROM watch_interests"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db


@pytest.fixture
async def interest_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAWatchInterestRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def user_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


def _make_interest(
    *,
    owner_id: str,
    title: str,
    channel_ids: list[str],
    is_active: bool = True,
) -> WatchInterest:
    return WatchInterest(
        id="",
        user_id=owner_id,
        chat_id=12345,
        title=title,
        description="ENH-001 telemetry fixture",
        keywords=["regulation"],
        exclude_keywords=[],
        channel_ids=list(channel_ids),
        threshold=0.6,
        notify_mode=NotifyMode.INSTANT,
        is_active=is_active,
        embedding=None,
    )


# ----------------------------------------------------------------------------
# 1. Regression — empty tick still stamps last_checked_at (PG-gated)
# ----------------------------------------------------------------------------


@pg_only
@pytest.mark.asyncio
async def test_check_interests_touches_last_checked_at_on_empty_tick(
    interest_repo, user_repo
):
    """A quiet tick (``new_doc_refs=[]``, candidates=0) advances
    ``last_checked_at`` for every ACTIVE interest of the channel, and leaves
    inactive interests untouched. Pre-ENH-001 this returned early without any
    stamp → the misleading-telemetry bug.
    """
    from tg_parser.services.watchlist_service import WatchlistService

    owner = await user_repo.create_user("enh001_owner")
    channel = "enh001_ch"

    active_a = await interest_repo.create(
        _make_interest(owner_id=owner.id, title="active-a", channel_ids=[channel])
    )
    active_b = await interest_repo.create(
        _make_interest(owner_id=owner.id, title="active-b", channel_ids=[channel])
    )
    inactive = await interest_repo.create(
        _make_interest(owner_id=owner.id, title="inactive", channel_ids=[channel])
    )
    await interest_repo.soft_delete(inactive.id)

    # Precondition: brand-new interests have never been evaluated.
    assert (await interest_repo.get(active_a.id)).last_checked_at is None
    assert (await interest_repo.get(active_b.id)).last_checked_at is None

    service = WatchlistService(
        interest_repo=interest_repo,
        match_repo=SAWatchMatchRepo(interest_repo.session),
        processed_doc_repo=MagicMock(),  # unused on the empty-tick path
        embedding_repo=MagicMock(),  # unused on the empty-tick path
        embedding_client=None,
    )

    # The empty / quiet tick: no new docs, so nothing to score.
    inserted = await service.check_interests(channel, [])
    assert inserted == []

    # Both ACTIVE interests must now show a fresh evaluation timestamp.
    refreshed_a = await interest_repo.get(active_a.id)
    refreshed_b = await interest_repo.get(active_b.id)
    assert refreshed_a.last_checked_at is not None, "active-a must be stamped on a quiet tick"
    assert refreshed_b.last_checked_at is not None, "active-b must be stamped on a quiet tick"

    # last_match_at stays null — we evaluated but matched nothing.
    assert refreshed_a.last_match_at is None
    assert refreshed_b.last_match_at is None

    # Inactive interests are NOT evaluated and must not be stamped.
    refreshed_inactive = await interest_repo.get(inactive.id)
    assert refreshed_inactive.last_checked_at is None


# ----------------------------------------------------------------------------
# 2. Pin — trigger_pipeline path does NOT advance last_checked_at
# ----------------------------------------------------------------------------


def test_trigger_pipeline_path_does_not_wire_matcher():
    """ENH-001 decision pin: the manual ``trigger_pipeline`` path executes
    ``run_full_pipeline`` (+ embeddings) and intentionally does NOT run the
    watchlist matcher — so it does NOT advance ``last_checked_at``. The matcher
    is wired ONLY into the hourly scheduler tick (``_process_source``).

    We pin this structurally: the pipeline-execution module must not reference
    the matcher entrypoints. If a future change wires the matcher into the
    pipeline, this test fails on purpose, forcing the author to update the
    documented ``last_checked_at`` semantics (domain model + MCP tool
    description) along with the behaviour change.
    """
    from tg_parser.services import pipeline_service

    source = inspect.getsource(pipeline_service)

    for forbidden in (
        "check_interests",
        "run_watchlist_check_for_channel",
        "touch_checked",
    ):
        assert forbidden not in source, (
            f"pipeline_service references {forbidden!r}: the trigger_pipeline path "
            "would now advance last_checked_at — update ENH-001 docs/tests if intended."
        )

    # Sanity: the matcher IS wired into the scheduler tick (the path that
    # legitimately advances last_checked_at).
    from tg_parser.services import scheduler_service

    assert "run_watchlist_check_for_channel" in inspect.getsource(scheduler_service)
