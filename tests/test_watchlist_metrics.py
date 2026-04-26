"""Unit tests for F11 watchlist Prometheus metrics surface (TD-02).

Covers:

- :func:`tg_parser.api.metrics.record_watchlist_match` increments the right
  ``tg_watchlist_matches_total{result}`` series and observes into
  ``tg_watchlist_score``.
- :func:`tg_parser.api.metrics.record_watchlist_delivery` increments the
  right ``tg_watchlist_delivery_total{outcome}`` series.
- :func:`tg_parser.api.metrics.set_watchlist_active` updates the gauge.
- Scoring boundary clamps in ``record_watchlist_match`` keep the histogram
  observation in [0, 1].
- :class:`tg_parser.services.watchlist_service.WatchlistService.check_interests`
  emits at least one match metric for a real (interest, doc) pair.

These tests intentionally probe the global Prometheus singletons; they read
counter values before and after the action under test to be robust against
other tests in the suite touching the same series.
"""

from __future__ import annotations

import math

import pytest

from tg_parser.api.metrics import (
    WATCHLIST_ACTIVE_INTERESTS,
    WATCHLIST_DELIVERY,
    WATCHLIST_MATCHES,
    WATCHLIST_SCORE,
    record_watchlist_delivery,
    record_watchlist_match,
    set_watchlist_active,
)


def _counter_value(counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()


def _histogram_count(histogram) -> float:
    return histogram._sum.get()


# ----------------------------------------------------------------------------
# record_watchlist_match
# ----------------------------------------------------------------------------


def test_record_watchlist_match_increments_delivered_counter() -> None:
    before = _counter_value(WATCHLIST_MATCHES, result="delivered")
    record_watchlist_match(result="delivered", score=0.85)
    after = _counter_value(WATCHLIST_MATCHES, result="delivered")
    assert after == pytest.approx(before + 1.0)


def test_record_watchlist_match_increments_filtered_counters() -> None:
    before_kw = _counter_value(WATCHLIST_MATCHES, result="filtered_keywords")
    before_th = _counter_value(WATCHLIST_MATCHES, result="filtered_threshold")
    record_watchlist_match(result="filtered_keywords", score=0.0)
    record_watchlist_match(result="filtered_threshold", score=0.45)
    assert _counter_value(WATCHLIST_MATCHES, result="filtered_keywords") == pytest.approx(
        before_kw + 1.0
    )
    assert _counter_value(WATCHLIST_MATCHES, result="filtered_threshold") == pytest.approx(
        before_th + 1.0
    )


def test_record_watchlist_match_observes_score_histogram() -> None:
    sum_before = _histogram_count(WATCHLIST_SCORE)
    record_watchlist_match(result="delivered", score=0.7)
    record_watchlist_match(result="filtered_threshold", score=0.5)
    sum_after = _histogram_count(WATCHLIST_SCORE)
    assert math.isclose(sum_after - sum_before, 1.2, abs_tol=1e-6)


def test_record_watchlist_match_clamps_score_into_unit_interval() -> None:
    sum_before = _histogram_count(WATCHLIST_SCORE)
    record_watchlist_match(result="delivered", score=1.5)
    record_watchlist_match(result="filtered_threshold", score=-0.3)
    sum_after = _histogram_count(WATCHLIST_SCORE)
    # 1.5 clamps to 1.0; -0.3 clamps to 0.0 → total observed = 1.0
    assert math.isclose(sum_after - sum_before, 1.0, abs_tol=1e-6)


# ----------------------------------------------------------------------------
# record_watchlist_delivery
# ----------------------------------------------------------------------------


def test_record_watchlist_delivery_increments_outcomes() -> None:
    before_sent = _counter_value(WATCHLIST_DELIVERY, outcome="sent")
    before_blocked = _counter_value(WATCHLIST_DELIVERY, outcome="blocked")
    before_error = _counter_value(WATCHLIST_DELIVERY, outcome="error")

    record_watchlist_delivery(outcome="sent")
    record_watchlist_delivery(outcome="blocked")
    record_watchlist_delivery(outcome="error")

    assert _counter_value(WATCHLIST_DELIVERY, outcome="sent") == pytest.approx(before_sent + 1.0)
    assert _counter_value(WATCHLIST_DELIVERY, outcome="blocked") == pytest.approx(
        before_blocked + 1.0
    )
    assert _counter_value(WATCHLIST_DELIVERY, outcome="error") == pytest.approx(before_error + 1.0)


# ----------------------------------------------------------------------------
# set_watchlist_active
# ----------------------------------------------------------------------------


def test_set_watchlist_active_sets_gauge() -> None:
    set_watchlist_active(7)
    assert WATCHLIST_ACTIVE_INTERESTS._value.get() == pytest.approx(7.0)
    set_watchlist_active(0)
    assert WATCHLIST_ACTIVE_INTERESTS._value.get() == pytest.approx(0.0)


def test_set_watchlist_active_clamps_negative_to_zero() -> None:
    set_watchlist_active(-5)
    assert WATCHLIST_ACTIVE_INTERESTS._value.get() == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# Service-level smoke test — check_interests emits match metrics
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_interests_records_match_metric_for_real_pair(
    service_with_interest_and_doc,
) -> None:
    """End-to-end: at least one ``record_watchlist_match`` call fires when
    the service scores a candidate pair. We don't assert the exact result
    label here (the test fixture chooses the score), only that *some*
    label was incremented.
    """
    service, channel_id, source_ref = service_with_interest_and_doc

    delivered_before = _counter_value(WATCHLIST_MATCHES, result="delivered")
    filt_kw_before = _counter_value(WATCHLIST_MATCHES, result="filtered_keywords")
    filt_th_before = _counter_value(WATCHLIST_MATCHES, result="filtered_threshold")

    await service.check_interests(channel_id, [source_ref])

    delivered_after = _counter_value(WATCHLIST_MATCHES, result="delivered")
    filt_kw_after = _counter_value(WATCHLIST_MATCHES, result="filtered_keywords")
    filt_th_after = _counter_value(WATCHLIST_MATCHES, result="filtered_threshold")

    total_delta = (
        (delivered_after - delivered_before)
        + (filt_kw_after - filt_kw_before)
        + (filt_th_after - filt_th_before)
    )
    assert total_delta >= 1.0, (
        "expected at least one tg_watchlist_matches_total increment for a "
        f"real (interest, doc) pair, got delta={total_delta}"
    )


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest.fixture
def service_with_interest_and_doc():
    """Build a :class:`WatchlistService` with in-memory fakes and one interest +
    one matching document. Returns ``(service, channel_id, source_ref)``.

    Both the interest and the document are populated directly into the in-memory
    fake stores (no awaits) so the fixture is sync and pytest-asyncio agnostic.
    """
    from datetime import UTC, datetime

    from tg_parser.domain.models import (
        NotifyMode,
        ProcessedDocument,
        WatchInterest,
    )
    from tg_parser.services.watchlist_service import WatchlistService

    class _FakeInterestRepo:
        def __init__(self) -> None:
            self.store: dict[str, WatchInterest] = {}

        async def get(self, interest_id: str) -> WatchInterest | None:
            return self.store.get(interest_id)

        async def list_all(self) -> list[WatchInterest]:
            return list(self.store.values())

        async def list_active_for_channel(self, channel_id: str) -> list[WatchInterest]:
            return [i for i in self.store.values() if i.is_active and channel_id in i.channel_ids]

        async def update_embedding(self, interest_id: str, embedding: list[float]) -> None:
            if interest_id in self.store:
                self.store[interest_id] = self.store[interest_id].model_copy(
                    update={"embedding": list(embedding)}
                )

        async def touch_checked(self, interest_id: str, at: datetime) -> None:
            if interest_id in self.store:
                self.store[interest_id] = self.store[interest_id].model_copy(
                    update={"last_checked_at": at}
                )

        async def touch_match(self, interest_id: str, at: datetime) -> None:
            if interest_id in self.store:
                self.store[interest_id] = self.store[interest_id].model_copy(
                    update={"last_match_at": at}
                )

    class _FakeMatchRepo:
        def __init__(self) -> None:
            self.store: dict[tuple[str, str], object] = {}

        async def upsert_many(self, matches):
            inserted = []
            for match in matches:
                key = (match.interest_id, match.source_ref)
                if key in self.store:
                    continue
                self.store[key] = match
                inserted.append(match)
            return inserted

    class _FakeProcDocRepo:
        def __init__(self) -> None:
            self.store: dict[str, ProcessedDocument] = {}

        async def get_by_source_refs(self, refs):
            return {ref: self.store[ref] for ref in refs if ref in self.store}

    class _FakeEmbeddingRepo:
        async def get_by_source_ref(self, ref):
            return None

    interest_repo = _FakeInterestRepo()
    match_repo = _FakeMatchRepo()
    doc_repo = _FakeProcDocRepo()
    embedding_repo = _FakeEmbeddingRepo()

    channel_id = "ch-watchlist-metrics"
    source_ref = "tg:metrics_test:post:1"

    interest_id = "int-1"
    interest_repo.store[interest_id] = WatchInterest(
        id=interest_id,
        user_id="user-1",
        chat_id=12345,
        title="Crypto regulations",
        description=None,
        keywords=["mica", "regulation", "crypto"],
        exclude_keywords=[],
        channel_ids=[channel_id],
        threshold=0.3,
        notify_mode=NotifyMode.INSTANT,
        is_active=True,
        embedding=None,
    )

    doc_repo.store[source_ref] = ProcessedDocument(
        id="doc:" + source_ref,
        source_ref=source_ref,
        source_message_id="msg-1",
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean="MiCA regulation update for crypto exchanges in 2026",
        summary="MiCA crypto regulation",
        topics=["crypto", "regulation"],
        entities=[],
    )

    service = WatchlistService(
        interest_repo=interest_repo,
        match_repo=match_repo,
        processed_doc_repo=doc_repo,
        embedding_repo=embedding_repo,
        embedding_client=None,
    )

    return service, channel_id, source_ref
