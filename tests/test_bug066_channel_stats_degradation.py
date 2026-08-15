"""BUG-066 — a single coverage-query failure must NOT zero-fill all channel stats.

Root cause (pre-fix): ``get_all_channel_stats`` ran all four aggregate queries
inside ONE shared ``try/except``. When the heavy ``coverage_counts_by_channel``
jsonb scan exceeded the read-scoped ``statement_timeout`` and raised
``SQLAlchemyError``, the shared handler discarded the already-correct
raw/processed/topics counts and returned ``_zero_stats`` for every channel —
so ``list_channels`` reported ``0 / 0 / 0 / 0.0`` for every channel while the
underlying data was fully intact.

These are pure-unit tests (no Postgres): they patch ``stats_repos`` with mocked
repos so a coverage failure can be injected deterministically and the
degradation contract asserted. The Postgres-backed parity/bounded-query tests
live in ``tests/test_bug008_channel_stats_batched.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.exc import SQLAlchemyError

from tg_parser.services import channel_service
from tg_parser.services.channel_service import get_all_channel_stats


def _source(channel_id: str, *, username: str | None = None, status: str = "active"):
    return SimpleNamespace(channel_id=channel_id, channel_username=username, status=status)


def _patch_stats_repos(
    monkeypatch,
    *,
    sources,
    raw_counts,
    processed_counts,
    topics_counts,
    coverage_counts=None,
    coverage_error: Exception | None = None,
):
    """Patch ``channel_service.stats_repos`` to yield mocked repos.

    Each aggregate is an ``AsyncMock``; ``coverage_error`` (when set) makes
    ``coverage_counts_by_channel`` raise to simulate the statement_timeout.
    """
    state_repo = SimpleNamespace(list_sources=AsyncMock(return_value=list(sources)))
    raw_repo = SimpleNamespace(
        count_all_grouped_by_channel=AsyncMock(return_value=dict(raw_counts))
    )
    proc_repo = SimpleNamespace(
        count_all_grouped_by_channel=AsyncMock(return_value=dict(processed_counts)),
        coverage_counts_by_channel=AsyncMock(
            side_effect=coverage_error,
            return_value=dict(coverage_counts or {}),
        ),
    )
    topic_card_repo = SimpleNamespace(
        count_by_channel_grouped=AsyncMock(return_value=dict(topics_counts))
    )

    @asynccontextmanager
    async def _fake_stats_repos():
        yield (
            state_repo,
            raw_repo,
            proc_repo,
            topic_card_repo,
            None,  # topic_bundle_repo (unused on this path)
            None,  # emb_repo
            None,  # topic_link_repo
            None,  # db
        )

    monkeypatch.setattr(channel_service, "stats_repos", _fake_stats_repos)
    return proc_repo


async def test_coverage_timeout_degrades_only_coverage_percent(monkeypatch):
    """A coverage-query failure must keep raw/processed/topics truthful."""
    sources = [_source("chA", username="@cha"), _source("chB", status="paused")]
    proc_repo = _patch_stats_repos(
        monkeypatch,
        sources=sources,
        raw_counts={"chA": 55882, "chB": 100},
        processed_counts={"chA": 17945, "chB": 40},
        topics_counts={"chA": 12, "chB": 3},
        coverage_error=SQLAlchemyError("statement timeout"),
    )

    result = await get_all_channel_stats()
    by_id = {r["channel_id"]: r for r in result}

    # Contract: exactly one row per channel, still.
    assert set(by_id) == {"chA", "chB"}

    # The three core counts keep their REAL values despite the coverage failure.
    assert by_id["chA"]["raw_messages"] == 55882
    assert by_id["chA"]["processed_documents"] == 17945
    assert by_id["chA"]["topics_count"] == 12
    assert by_id["chB"]["raw_messages"] == 100
    assert by_id["chB"]["processed_documents"] == 40
    assert by_id["chB"]["topics_count"] == 3

    # Only coverage_percent degrades — and the substitution is labelled.
    assert by_id["chA"]["coverage_percent"] is None
    assert by_id["chB"]["coverage_percent"] is None
    assert by_id["chA"]["coverage_degraded"] is True
    assert by_id["chB"]["coverage_degraded"] is True

    # Passthrough fields preserved.
    assert by_id["chA"]["channel_username"] == "@cha"
    assert by_id["chB"]["status"] == "paused"

    # The coverage query was actually attempted (and raised).
    proc_repo.coverage_counts_by_channel.assert_awaited_once()


async def test_success_path_computes_real_coverage(monkeypatch):
    """Success path: all four aggregates contribute, coverage_percent computed."""
    sources = [_source("chA", username="@cha")]
    _patch_stats_repos(
        monkeypatch,
        sources=sources,
        raw_counts={"chA": 10},
        processed_counts={"chA": 4},
        topics_counts={"chA": 2},
        coverage_counts={"chA": 3},
    )

    result = await get_all_channel_stats()
    by_id = {r["channel_id"]: r for r in result}

    assert by_id["chA"]["raw_messages"] == 10
    assert by_id["chA"]["processed_documents"] == 4
    assert by_id["chA"]["topics_count"] == 2
    assert by_id["chA"]["coverage_percent"] == 75.0  # 3 / 4 * 100
    assert by_id["chA"]["coverage_degraded"] is False


async def test_single_aggregate_failure_isolated_per_field(monkeypatch):
    """Defense-in-depth: a raw-count failure degrades ONLY raw_messages."""
    sources = [_source("chA")]

    async def _raise(*_a, **_k):
        raise SQLAlchemyError("raw boom")

    state_repo = SimpleNamespace(list_sources=AsyncMock(return_value=list(sources)))
    raw_repo = SimpleNamespace(count_all_grouped_by_channel=AsyncMock(side_effect=_raise))
    proc_repo = SimpleNamespace(
        count_all_grouped_by_channel=AsyncMock(return_value={"chA": 4}),
        coverage_counts_by_channel=AsyncMock(return_value={"chA": 4}),
    )
    topic_card_repo = SimpleNamespace(count_by_channel_grouped=AsyncMock(return_value={"chA": 2}))

    @asynccontextmanager
    async def _fake():
        yield (state_repo, raw_repo, proc_repo, topic_card_repo, None, None, None, None)

    monkeypatch.setattr(channel_service, "stats_repos", _fake)

    result = await get_all_channel_stats()
    row = {r["channel_id"]: r for r in result}["chA"]

    assert row["raw_messages"] == 0  # degraded (raw aggregate raised)
    assert row["processed_documents"] == 4  # intact
    assert row["topics_count"] == 2  # intact
    assert row["coverage_percent"] == 100.0  # intact (4 / 4)
