"""Single-channel stats aggregation (``channel_service.get_channel_stats``).

`technical-debt-roadmap.md` § 6 named this one specifically, and the reason it
qualified is worth stating: ``get_channel_stats`` *is* referenced from a dozen
test files — every one of them as a ``patch`` target. It was mocked everywhere
and executed nowhere, so its own arithmetic had no coverage at all while looking
well-tested by grep.

The sibling ``get_all_channel_stats`` is a different implementation (BUG-008 H1
replaced the per-channel fan-out with set-based aggregates), so tests for one say
nothing about the other. What is pinned here is the arithmetic that differs
between them and the two guards that are easy to regress:

* coverage counts only refs that belong to THIS channel — the intersection with
  ``processed_refs`` is what stops a bundle referencing another channel from
  inflating the number;
* ``coverage_percent`` divides by zero documents without raising;
* ``embeddings_count`` is clamped at zero rather than going negative when the
  missing-embeddings list outruns the processed count.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.services.channel_service import _compute_coverage, get_channel_stats


def _bundle(*source_refs: str) -> SimpleNamespace:
    return SimpleNamespace(items=[SimpleNamespace(source_ref=r) for r in source_refs])


def _stats_repos_stub(
    *,
    source,
    raw_count: int = 0,
    processed_count: int = 0,
    topic_cards: list | None = None,
    processed_refs: list[str] | None = None,
    bundles: list | None = None,
    missing_refs: list[str] | None = None,
):
    """Stand in for the eight-tuple ``stats_repos`` context manager."""
    state_repo = MagicMock()
    state_repo.get_source = AsyncMock(return_value=source)

    raw_repo = MagicMock()
    raw_repo.count_by_channel = AsyncMock(return_value=raw_count)

    proc_repo = MagicMock()
    proc_repo.count_by_channel = AsyncMock(return_value=processed_count)
    proc_repo.list_source_refs_by_channel = AsyncMock(return_value=processed_refs or [])

    topic_card_repo = MagicMock()
    topic_card_repo.list_by_channel = AsyncMock(return_value=topic_cards or [])

    topic_bundle_repo = MagicMock()
    topic_bundle_repo.list_by_channel = AsyncMock(return_value=bundles or [])

    emb_repo = MagicMock()
    emb_repo.list_missing = AsyncMock(return_value=missing_refs or [])

    @contextlib.asynccontextmanager
    async def _cm():
        yield (
            state_repo,
            raw_repo,
            proc_repo,
            topic_card_repo,
            topic_bundle_repo,
            emb_repo,
            MagicMock(),  # topic_link_repo — unused by this function
            MagicMock(),  # db
        )

    return _cm


class TestComputeCoverage:
    def test_counts_only_refs_that_belong_to_this_channel(self):
        """The intersection is the guard: a bundle may legitimately reference
        documents from another channel, and those must not inflate coverage."""
        bundles = [_bundle("a", "b", "foreign-1"), _bundle("b", "foreign-2")]
        covered, percent = _compute_coverage(bundles, {"a", "b", "c"}, processed_count=4)
        assert covered == 2  # "a" and "b"; the foreign refs are excluded
        assert percent == 50.0

    def test_duplicate_refs_across_bundles_count_once(self):
        bundles = [_bundle("a"), _bundle("a"), _bundle("a")]
        covered, _ = _compute_coverage(bundles, {"a"}, processed_count=1)
        assert covered == 1

    def test_zero_processed_documents_yields_zero_percent_not_zerodivision(self):
        covered, percent = _compute_coverage([_bundle("a")], set(), processed_count=0)
        assert (covered, percent) == (0, 0.0)

    def test_no_bundles_is_zero_coverage(self):
        assert _compute_coverage([], {"a", "b"}, processed_count=2) == (0, 0.0)


class TestGetChannelStats:
    @pytest.mark.asyncio
    async def test_unknown_channel_raises_value_error(self, monkeypatch):
        monkeypatch.setattr(
            "tg_parser.services.channel_service.stats_repos",
            _stats_repos_stub(source=None),
        )
        with pytest.raises(ValueError, match="Channel not found: tg:nope"):
            await get_channel_stats("tg:nope")

    @pytest.mark.asyncio
    async def test_aggregates_every_field(self, monkeypatch):
        monkeypatch.setattr(
            "tg_parser.services.channel_service.stats_repos",
            _stats_repos_stub(
                source=SimpleNamespace(channel_username="@chan"),
                raw_count=100,
                processed_count=80,
                topic_cards=[object(), object(), object()],
                processed_refs=["r1", "r2", "r3"],
                bundles=[_bundle("r1", "r2")],
                missing_refs=["r3"],
            ),
        )
        stats = await get_channel_stats("tg:chan")

        assert stats == {
            "channel_id": "tg:chan",
            "channel_username": "@chan",
            "raw_messages": 100,
            "processed_documents": 80,
            "topics_count": 3,
            "covered_documents": 2,
            "coverage_percent": 2.5,  # 2/80
            "embeddings_count": 79,  # 80 processed − 1 missing
            "missing_embeddings": 1,
        }

    @pytest.mark.asyncio
    async def test_embeddings_count_is_clamped_at_zero(self, monkeypatch):
        """``max(0, processed − missing)``. The inputs come from two different
        databases read in separate sessions, so a mid-flight write can leave
        missing > processed; a negative count would surface in the API."""
        monkeypatch.setattr(
            "tg_parser.services.channel_service.stats_repos",
            _stats_repos_stub(
                source=SimpleNamespace(channel_username="@chan"),
                processed_count=2,
                missing_refs=["a", "b", "c", "d"],
            ),
        )
        stats = await get_channel_stats("tg:chan")
        assert stats["embeddings_count"] == 0
        assert stats["missing_embeddings"] == 4

    @pytest.mark.asyncio
    async def test_coverage_percent_is_rounded_to_two_places(self, monkeypatch):
        monkeypatch.setattr(
            "tg_parser.services.channel_service.stats_repos",
            _stats_repos_stub(
                source=SimpleNamespace(channel_username="@chan"),
                processed_count=3,
                processed_refs=["r1", "r2", "r3"],
                bundles=[_bundle("r1")],
            ),
        )
        stats = await get_channel_stats("tg:chan")
        assert stats["coverage_percent"] == 33.33  # 1/3 → 33.333… rounded

    @pytest.mark.asyncio
    async def test_empty_channel_reports_zeros_rather_than_failing(self, monkeypatch):
        monkeypatch.setattr(
            "tg_parser.services.channel_service.stats_repos",
            _stats_repos_stub(source=SimpleNamespace(channel_username=None)),
        )
        stats = await get_channel_stats("tg:fresh")
        assert stats["channel_username"] is None
        assert stats["coverage_percent"] == 0.0
        assert stats["embeddings_count"] == 0
