"""Service-layer tests for BUG-022 subscribe-idempotency (Wave 1 step 3 commit 1/4).

Closes BUG-022 by exercising the new ``subscribe()`` upsert path on both
:class:`WatchlistService` and :class:`DigestService`. Pure in-memory fakes
(no Postgres). Race-condition tests use ``asyncio.gather`` against a fake
that raises :class:`IntegrityError` from the first concurrent ``create()`` —
the same shape the new DB ``UNIQUE`` constraint would emit.

Canonical scenarios (per sprint prompt §5):

1. ``test_subscribe_watchlist_idempotent_same_args``                — no-op replay
2. ``test_subscribe_watchlist_upsert_different_args``               — diff
3. ``test_subscribe_watchlist_different_titles_different_rows``     — disjoint keys
4. ``test_subscribe_watchlist_race_condition``                      — concurrent INSERTs
5. ``test_subscribe_watchlist_resurrects_soft_deleted_row``         — Edge 6 (soft-delete)
6. ``test_subscribe_digest_idempotent_same_args``                   — Scenario 5 mirror
7. ``test_subscribe_digest_upsert_different_args``
8. ``test_subscribe_digest_race_condition``
9. ``test_subscribe_digest_resurrects_inactive_row``                — Edge 6 mirror

Sprint prompt §5 Edge 7 (whitespace / case-sensitivity on natural-key
fields) is intentionally not exercised here — the domain models
(``WatchInterest.title`` / ``DigestSubscription.name``) do not normalise
their values, the DB ``UNIQUE`` constraint compares exact strings, and
adding a pin for non-normalisation would freeze a behaviour we expect
to evolve when locale-aware indexing lands.

Backward-compat regression guards live in ``tests/test_f11_watchlist.py``
and ``tests/test_f6_scheduled_digests.py``; this file only adds the new
behaviour-level assertions.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeEmbeddingClient,
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
)

from tg_parser.domain.models import (  # noqa: E402
    DigestFormat,
    DigestSubscription,
    NotifyMode,
)
from tg_parser.services.digest_service import DigestService  # noqa: E402
from tg_parser.services.digest_service import (  # noqa: E402
    SubscribeResult as DigestSubscribeResult,
)
from tg_parser.services.watchlist_service import (  # noqa: E402
    SubscribeResult as WatchSubscribeResult,
)
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# ---------------------------------------------------------------------------
# In-memory DigestSubscriptionRepo fake (BUG-022)
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for ``AsyncSession`` exposing only ``rollback`` (BUG-029)."""

    def __init__(self) -> None:
        self.rollback_calls: int = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


@dataclass
class _FakeDigestSubscriptionRepo:
    """Minimal in-memory repo with ``find_by_owner_and_name`` and a race
    toggle that mimics the new ``UNIQUE (owner_id, name)`` DB constraint.

    The ``simulate_race_on_create`` flag fires exactly once: on its first
    invocation the repo writes the racing row under a synthetic id (so
    a follow-up ``find_by_owner_and_name`` returns it) and raises
    :class:`IntegrityError`. Subsequent calls behave normally — this
    matches the worst-case shape the service must collapse to a single
    row.
    """

    store: dict[str, DigestSubscription] = field(default_factory=dict)
    simulate_race_on_create: bool = False
    _race_fired: bool = False
    # BUG-029: the real SA repo exposes ``.session`` so the service can
    # ``rollback()`` an aborted transaction before the race-retry. The fake
    # mirrors that surface with a no-op rollback counter.
    session: _FakeSession = field(default_factory=lambda: _FakeSession())

    async def create(self, sub: DigestSubscription) -> DigestSubscription:
        if self.simulate_race_on_create:
            collision = next(
                (
                    existing
                    for existing in self.store.values()
                    if existing.owner_id == sub.owner_id and existing.name == sub.name
                ),
                None,
            )
            if collision is not None:
                raise IntegrityError(
                    "duplicate key value violates unique constraint",
                    params=None,
                    orig=Exception("uq_digest_subscriptions_owner_name"),
                )
            if not self._race_fired:
                self._race_fired = True
        new_id = sub.id or str(uuid.uuid4())
        stored = sub.model_copy(update={"id": new_id})
        self.store[new_id] = stored
        return stored

    async def get(self, sub_id: str) -> DigestSubscription | None:
        return self.store.get(sub_id)

    async def find_by_owner_and_name(self, owner_id: str, name: str) -> DigestSubscription | None:
        for sub in self.store.values():
            if sub.owner_id == owner_id and sub.name == name:
                return sub
        return None

    async def update(self, sub_id: str, **fields: Any) -> DigestSubscription | None:
        existing = self.store.get(sub_id)
        if existing is None:
            return None
        clean: dict[str, Any] = {}
        for k, v in fields.items():
            if k == "unset_workspace_id":
                if v:
                    clean["workspace_id"] = None
                continue
            if v is not None:
                clean[k] = v
        if not clean:
            return existing
        clean["updated_at"] = datetime.now(UTC)
        new_row = existing.model_copy(update=clean)
        self.store[sub_id] = new_row
        return new_row

    async def delete(self, sub_id: str) -> bool:
        return self.store.pop(sub_id, None) is not None

    async def list_by_owner(self, owner_id: str) -> list[DigestSubscription]:
        return [s for s in self.store.values() if s.owner_id == owner_id]

    async def list_all(self) -> list[DigestSubscription]:
        return list(self.store.values())

    async def list_active(self) -> list[DigestSubscription]:
        return [s for s in self.store.values() if s.is_active]


# ---------------------------------------------------------------------------
# Service factories
# ---------------------------------------------------------------------------


def _make_watchlist_service(
    *,
    interest_repo: _FakeInterestRepo | None = None,
    match_repo: _FakeMatchRepo | None = None,
) -> tuple[WatchlistService, _FakeInterestRepo, _FakeMatchRepo]:
    ir = interest_repo or _FakeInterestRepo()
    mr = match_repo or _FakeMatchRepo()
    svc = WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )
    return svc, ir, mr


def _make_digest_service(
    *,
    sub_repo: _FakeDigestSubscriptionRepo | None = None,
) -> tuple[DigestService, _FakeDigestSubscriptionRepo]:
    repo = sub_repo or _FakeDigestSubscriptionRepo()
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
        workspace_repo=None,
    )
    return svc, repo


# ---------------------------------------------------------------------------
# Watchlist idempotency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscribeWatchlistIdempotency:
    async def test_subscribe_watchlist_idempotent_same_args(self) -> None:
        svc, ir, _ = _make_watchlist_service()
        kwargs: dict[str, Any] = {
            "user_id": "user-1",
            "chat_id": 12345,
            "title": "MiCA / EU crypto regulation",
            "channel_ids": ["crypto_news"],
            "keywords": ["mica"],
            "threshold": 0.6,
            "notify_mode": NotifyMode.INSTANT,
        }

        first = await svc.subscribe(**kwargs)
        second = await svc.subscribe(**kwargs)

        assert isinstance(first, WatchSubscribeResult)
        assert isinstance(second, WatchSubscribeResult)
        assert first.created is True
        assert first.changed_fields == []
        assert second.created is False
        assert second.changed_fields == []
        # Same row — single insert by natural key.
        assert first.interest.id == second.interest.id
        assert len(ir.store) == 1

    async def test_subscribe_watchlist_upsert_different_args(self) -> None:
        svc, ir, _ = _make_watchlist_service()
        base: dict[str, Any] = {
            "user_id": "user-1",
            "chat_id": 12345,
            "title": "MiCA / EU crypto regulation",
            "channel_ids": ["crypto_news"],
            "keywords": ["mica"],
            "threshold": 0.6,
            "notify_mode": NotifyMode.INSTANT,
        }

        first = await svc.subscribe(**base)
        second = await svc.subscribe(
            **{
                **base,
                "keywords": ["mica", "dora"],
                "description": "Watch MiCA + DORA",
            }
        )

        assert first.created is True
        assert second.created is False
        assert first.interest.id == second.interest.id
        assert set(second.changed_fields) == {"keywords", "description"}
        # Repo state reflects the new payload, not the old one.
        stored = await ir.get(second.interest.id)
        assert stored is not None
        assert stored.keywords == ["mica", "dora"]
        assert stored.description == "Watch MiCA + DORA"

    async def test_subscribe_watchlist_different_titles_different_rows(self) -> None:
        svc, ir, _ = _make_watchlist_service()
        base: dict[str, Any] = {
            "user_id": "user-1",
            "chat_id": 12345,
            "channel_ids": ["crypto_news"],
            "keywords": ["mica"],
            "threshold": 0.6,
            "notify_mode": NotifyMode.INSTANT,
        }

        first = await svc.subscribe(title="MiCA", **base)
        second = await svc.subscribe(title="DORA", **base)

        assert first.created is True
        assert second.created is True
        assert first.interest.id != second.interest.id
        assert len(ir.store) == 2

    async def test_subscribe_watchlist_race_condition(self) -> None:
        """Concurrent INSERTs collapse to a single row via IntegrityError retry."""
        ir = _FakeInterestRepo()
        ir.simulate_race_on_create = True
        svc, ir, _ = _make_watchlist_service(interest_repo=ir)

        kwargs: dict[str, Any] = {
            "user_id": "user-race",
            "chat_id": 42,
            "title": "Race target",
            "channel_ids": ["crypto_news"],
            "keywords": ["mica"],
            "threshold": 0.6,
            "notify_mode": NotifyMode.INSTANT,
        }

        results = await asyncio.gather(
            *[svc.subscribe(**kwargs) for _ in range(10)],
            return_exceptions=True,
        )

        # No exceptions leaked — every loser must have retried as UPDATE.
        for r in results:
            assert not isinstance(r, Exception), r

        unique_ids = {r.interest.id for r in results}  # type: ignore[union-attr]
        assert len(unique_ids) == 1, "race must collapse to a single row"
        # Exactly one create-winner.
        created_flags = [r.created for r in results]  # type: ignore[union-attr]
        assert created_flags.count(True) == 1
        assert created_flags.count(False) == len(results) - 1
        # And the fake store holds exactly one row under that id.
        assert len(ir.store) == 1

    async def test_subscribe_watchlist_text_field_update_calls_embedding_client(self) -> None:
        """BUG-054 / ADR 0015: a text-field update re-embeds via the client."""
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=client,
        )
        kwargs: dict[str, Any] = {
            "user_id": "user-1",
            "chat_id": 12345,
            "title": "MiCA / EU crypto regulation",
            "channel_ids": ["crypto_news"],
            "keywords": ["mica"],
            "threshold": 0.6,
            "notify_mode": NotifyMode.INSTANT,
        }

        await svc.subscribe(**kwargs)
        calls_before = len(client.calls)

        await svc.subscribe(**{**kwargs, "keywords": ["mica", "dora"]})

        assert len(client.calls) == calls_before + 1, (
            "text-field update must invoke the embedding client to re-embed"
        )

    async def test_subscribe_watchlist_resurrects_soft_deleted_row(self) -> None:
        """Soft-deleted (is_active=False) row + same (user_id, title) → resurrect.

        Sprint prompt §5 Edge 6 — BUG-022 must preserve the row through
        unsubscribe → subscribe cycle. The watch_matches history stays
        attached (same id), is_active flips back to True, and ``is_active``
        appears in ``changed_fields`` so the surface can render
        "resurrected" rather than "no-op".
        """
        svc, ir, _ = _make_watchlist_service()
        kwargs: dict[str, Any] = {
            "user_id": "user-1",
            "chat_id": 12345,
            "title": "MiCA / EU crypto regulation",
            "channel_ids": ["crypto_news"],
            "keywords": ["mica"],
            "threshold": 0.6,
            "notify_mode": NotifyMode.INSTANT,
        }

        first = await svc.subscribe(**kwargs)
        assert first.created is True
        # Soft-delete the row (mirror unsubscribe).
        deleted = await ir.soft_delete(first.interest.id)
        assert deleted is True
        soft_deleted = await ir.get(first.interest.id)
        assert soft_deleted is not None
        assert soft_deleted.is_active is False

        second = await svc.subscribe(**kwargs)

        assert second.created is False, (
            "row must be reused, not re-CREATEd (preserves watch_matches FK)"
        )
        assert second.interest.id == first.interest.id
        assert "is_active" in second.changed_fields, (
            "is_active must surface in changed_fields so callers can render resurrection"
        )
        # The row is back to active state.
        resurrected = await ir.get(first.interest.id)
        assert resurrected is not None
        assert resurrected.is_active is True
        # And only one row exists for the natural key.
        assert len(ir.store) == 1


# ---------------------------------------------------------------------------
# Digest idempotency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscribeDigestIdempotency:
    async def test_subscribe_digest_idempotent_same_args(self) -> None:
        svc, repo = _make_digest_service()
        kwargs: dict[str, Any] = {
            "owner_id": "user-1",
            "chat_id": 12345,
            "name": "morning",
            "channel_ids": ["durov"],
            "cron_expression": "0 9 * * *",
            "timezone": "Europe/Moscow",
            "format": DigestFormat.SUMMARY,
            "language": "ru",
        }

        first = await svc.subscribe(**kwargs)
        second = await svc.subscribe(**kwargs)

        assert isinstance(first, DigestSubscribeResult)
        assert isinstance(second, DigestSubscribeResult)
        assert first.created is True
        assert first.changed_fields == []
        assert second.created is False
        assert second.changed_fields == []
        assert first.subscription.id == second.subscription.id
        assert len(repo.store) == 1

    async def test_subscribe_digest_upsert_different_args(self) -> None:
        svc, repo = _make_digest_service()
        base: dict[str, Any] = {
            "owner_id": "user-1",
            "chat_id": 12345,
            "name": "morning",
            "channel_ids": ["durov"],
            "cron_expression": "0 9 * * *",
            "timezone": "Europe/Moscow",
            "format": DigestFormat.SUMMARY,
            "language": "ru",
        }

        first = await svc.subscribe(**base)
        second = await svc.subscribe(
            **{
                **base,
                "cron_expression": "0 18 * * *",
                "channel_ids": ["durov", "tginfo"],
            }
        )

        assert first.created is True
        assert second.created is False
        assert first.subscription.id == second.subscription.id
        assert set(second.changed_fields) == {"cron_expression", "channel_ids"}
        stored = await repo.get(second.subscription.id)
        assert stored is not None
        assert stored.cron_expression == "0 18 * * *"
        assert stored.channel_ids == ["durov", "tginfo"]

    async def test_subscribe_digest_race_condition(self) -> None:
        """Concurrent INSERTs collapse to a single row via IntegrityError retry."""
        repo = _FakeDigestSubscriptionRepo()
        repo.simulate_race_on_create = True
        svc, repo = _make_digest_service(sub_repo=repo)

        kwargs: dict[str, Any] = {
            "owner_id": "user-race",
            "chat_id": 42,
            "name": "race-digest",
            "channel_ids": ["durov"],
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
            "format": DigestFormat.SUMMARY,
            "language": "ru",
        }

        results = await asyncio.gather(
            *[svc.subscribe(**kwargs) for _ in range(10)],
            return_exceptions=True,
        )

        for r in results:
            assert not isinstance(r, Exception), r

        unique_ids = {r.subscription.id for r in results}  # type: ignore[union-attr]
        assert len(unique_ids) == 1
        created_flags = [r.created for r in results]  # type: ignore[union-attr]
        assert created_flags.count(True) == 1
        assert created_flags.count(False) == len(results) - 1
        assert len(repo.store) == 1

    async def test_subscribe_digest_resurrects_inactive_row(self) -> None:
        """is_active=False digest row + same (owner_id, name) → resurrect.

        Sprint prompt §5 Edge 6 mirror for F6 — DELETE on a digest is hard
        (Q8 = A) in the HTTP/MCP surface, but the service layer must still
        handle the case where an existing row was flipped to ``is_active
        = False`` directly (e.g. orphaned-bot-block path mirroring F11).
        Resurrection must surface ``is_active`` in ``changed_fields``.
        """
        svc, repo = _make_digest_service()
        kwargs: dict[str, Any] = {
            "owner_id": "user-1",
            "chat_id": 12345,
            "name": "morning",
            "channel_ids": ["durov"],
            "cron_expression": "0 9 * * *",
            "timezone": "Europe/Moscow",
            "format": DigestFormat.SUMMARY,
            "language": "ru",
        }

        first = await svc.subscribe(**kwargs)
        assert first.created is True

        # Simulate the existing row going inactive (no public soft_delete
        # on the digest repo — update is_active directly).
        inactive = await repo.update(first.subscription.id, is_active=False)
        assert inactive is not None
        assert inactive.is_active is False

        second = await svc.subscribe(**kwargs)

        assert second.created is False
        assert second.subscription.id == first.subscription.id
        assert "is_active" in second.changed_fields, (
            "is_active must surface in changed_fields so callers can render resurrection"
        )
        resurrected = await repo.get(first.subscription.id)
        assert resurrected is not None
        assert resurrected.is_active is True
        assert len(repo.store) == 1
