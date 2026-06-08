"""F11 MCP tools — pure-mock tests (no Postgres required).

We mock the three external surfaces:

- ``resolve_mcp_user`` → returns a synthetic ``CurrentUser`` (admin or scoped).
- ``watchlist_repos`` → an asynccontextmanager yielding fake repos.
- ``make_watchlist_service`` → returns the in-memory ``WatchlistService``
  built around the same fakes already exercised in
  ``test_watchlist_service.py``.

Goal: lock in the user-visible contract (ownership, validation, response
shape) without spinning up the real DB. Postgres-level wiring is covered by
``test_f11_watchlist_repo.py``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
    _make_doc,
    _make_interest,
    _make_match,
)

from tg_parser.auth.models import CurrentUser  # noqa: E402
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _admin(user_id: str = "user-admin") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _scoped(user_id: str, *, allowed: set[str]) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="user",
        role="user",
        allowed_channel_ids=list(allowed),
        max_channels=10,
    )


@asynccontextmanager
async def _fake_watchlist_repos(
    interest_repo: _FakeInterestRepo,
    match_repo: _FakeMatchRepo,
    docs: list = None,
):
    yield (
        interest_repo,
        match_repo,
        _FakeProcessedDocRepo(docs or []),
        _FakeEmbeddingRepo(),
        None,
    )


def _service_factory(svc: WatchlistService):
    def _make(**_kwargs):
        return svc

    return _make


def _patch_mcp(
    svc: WatchlistService, ir: _FakeInterestRepo, mr: _FakeMatchRepo, *, user: CurrentUser
):
    """Build the ``with`` chain for patching the MCP module under test."""
    return [
        patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _fake_watchlist_repos(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            _service_factory(svc),
        ),
    ]


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


# ----------------------------------------------------------------------------
# subscribe_watchlist
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscribeWatchlist:
    async def test_creates_interest_and_returns_success(self):
        from tg_parser.mcp_server import subscribe_watchlist

        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        user = _admin("user-1")

        patches = _patch_mcp(svc, ir, mr, user=user)
        _enter_all(patches)
        try:
            result = await subscribe_watchlist(
                title="MiCA crypto regulation",
                channel_ids=["@crypto_news"],
                chat_id=12345,
                keywords=["mica"],
                threshold=0.6,
            )
        finally:
            _exit_all(patches)

        assert result.success is True
        assert result.interest is not None
        assert result.interest.title == "MiCA crypto regulation"
        assert "crypto_news" in result.interest.channel_ids
        assert result.interest.user_id == "user-1"
        # The interest is persisted to the (fake) repo.
        assert len(ir.store) == 1

    async def test_rejects_empty_title(self):
        from tg_parser.mcp_server import subscribe_watchlist

        ir = _FakeInterestRepo()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = await subscribe_watchlist(
                title="   ",
                channel_ids=["@x"],
                chat_id=1,
            )
        finally:
            _exit_all(patches)
        assert result.success is False
        assert "title" in result.message.lower()

    async def test_rejects_empty_channel_list(self):
        from tg_parser.mcp_server import subscribe_watchlist

        ir = _FakeInterestRepo()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = await subscribe_watchlist(
                title="MiCA",
                channel_ids=[],
                chat_id=1,
            )
        finally:
            _exit_all(patches)
        assert result.success is False
        assert "channel" in result.message.lower()

    async def test_rejects_threshold_outside_range(self):
        from tg_parser.mcp_server import subscribe_watchlist

        ir = _FakeInterestRepo()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = await subscribe_watchlist(
                title="MiCA",
                channel_ids=["@x"],
                chat_id=1,
                threshold=1.5,
            )
        finally:
            _exit_all(patches)
        assert result.success is False
        assert "threshold" in result.message.lower()

    async def test_enforces_channel_access_for_scoped_user(self):
        from tg_parser.mcp_server import subscribe_watchlist

        ir = _FakeInterestRepo()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        # Scoped user only has access to "owned", not "forbidden".
        user = _scoped("user-2", allowed={"owned"})
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=user)
        _enter_all(patches)
        try:
            result = await subscribe_watchlist(
                title="MiCA",
                channel_ids=["@forbidden"],
                chat_id=1,
            )
        finally:
            _exit_all(patches)
        assert result.success is False
        assert "forbidden" in result.message.lower() or "no access" in result.message.lower()
        assert len(ir.store) == 0


# ----------------------------------------------------------------------------
# list_watchlists
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListWatchlists:
    async def test_admin_sees_all_interests(self):
        from tg_parser.mcp_server import list_watchlists

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-alice"))
        await ir.create(
            _make_interest(interest_id="i-bob").model_copy(update={"user_id": "user-bob"})
        )
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        # Admin's id doesn't match either owner — but still sees all.
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin("user-admin"))

        # `list_watchlists` doesn't use `make_watchlist_service` so we can rely
        # on the (still patched) `watchlist_repos`.
        _enter_all(patches)
        try:
            result = await list_watchlists()
        finally:
            _exit_all(patches)

        assert result.count == 2
        ids = {i.id for i in result.interests}
        assert ids == {"i-alice", "i-bob"}

    async def test_non_admin_sees_only_own(self):
        from tg_parser.mcp_server import list_watchlists

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-alice"))
        await ir.create(
            _make_interest(interest_id="i-bob").model_copy(update={"user_id": "user-bob"})
        )
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        # Bob queries.
        patches = _patch_mcp(
            svc, ir, _FakeMatchRepo(), user=_scoped("user-bob", allowed={"crypto_news"})
        )
        _enter_all(patches)
        try:
            result = await list_watchlists()
        finally:
            _exit_all(patches)

        assert result.count == 1
        assert result.interests[0].id == "i-bob"


# ----------------------------------------------------------------------------
# unsubscribe_watchlist
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUnsubscribeWatchlist:
    async def test_owner_can_delete(self):
        from tg_parser.mcp_server import unsubscribe_watchlist

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(
            svc, ir, _FakeMatchRepo(), user=_scoped("user-1", allowed={"crypto_news"})
        )
        _enter_all(patches)
        try:
            result = await unsubscribe_watchlist(interest_id="i-1")
        finally:
            _exit_all(patches)
        assert result.success is True
        stored = await ir.get("i-1")
        assert stored is not None
        assert stored.is_active is False

    async def test_non_owner_blocked(self):
        from tg_parser.mcp_server import unsubscribe_watchlist

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(
            svc,
            ir,
            _FakeMatchRepo(),
            user=_scoped("intruder", allowed={"crypto_news"}),
        )
        _enter_all(patches)
        try:
            result = await unsubscribe_watchlist(interest_id="i-1")
        finally:
            _exit_all(patches)
        assert result.success is False
        assert "permission" in result.message.lower()
        stored = await ir.get("i-1")
        assert stored is not None
        assert stored.is_active is True

    async def test_admin_can_delete_others(self):
        from tg_parser.mcp_server import unsubscribe_watchlist

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin("user-admin"))
        _enter_all(patches)
        try:
            result = await unsubscribe_watchlist(interest_id="i-1")
        finally:
            _exit_all(patches)
        assert result.success is True

    async def test_returns_error_for_unknown_id(self):
        from tg_parser.mcp_server import unsubscribe_watchlist

        ir = _FakeInterestRepo()
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = await unsubscribe_watchlist(interest_id="ghost")
        finally:
            _exit_all(patches)
        assert result.success is False
        assert "not found" in result.message.lower()


# ----------------------------------------------------------------------------
# get_watchlist_matches
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetWatchlistMatches:
    async def test_owner_receives_matches_filtered_by_since(self):
        from tg_parser.domain.models import WatchMatch
        from tg_parser.mcp_server import get_watchlist_matches

        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        old = WatchMatch(
            id=1,
            interest_id="i-1",
            source_ref="tg:c:post:1",
            channel_id="c",
            keyword_score=0.5,
            semantic_score=0.0,
            combined_score=0.5,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            notified=True,
        )
        recent = WatchMatch(
            id=2,
            interest_id="i-1",
            source_ref="tg:c:post:2",
            channel_id="c",
            keyword_score=0.5,
            semantic_score=0.0,
            combined_score=0.5,
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
            notified=False,
        )
        await mr.upsert_many([old, recent])

        svc = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, mr, user=_scoped("user-1", allowed={"crypto_news"}))
        _enter_all(patches)
        try:
            result = await get_watchlist_matches(
                interest_id="i-1",
                since_iso="2026-04-01T00:00:00+00:00",
            )
        finally:
            _exit_all(patches)
        assert result.count == 1
        assert result.matches[0].source_ref == "tg:c:post:2"

    async def test_non_owner_gets_empty_silently(self):
        from tg_parser.mcp_server import get_watchlist_matches

        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        await mr.upsert_many(
            [
                _make_match(
                    interest_id="i-1",
                    source_ref="tg:c:post:1",
                    match_id=10,
                    channel_id="c",
                ),
            ]
        )
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, mr, user=_scoped("intruder", allowed={"crypto_news"}))
        _enter_all(patches)
        try:
            result = await get_watchlist_matches(interest_id="i-1")
        finally:
            _exit_all(patches)
        assert result.count == 0
        assert result.matches == []

    async def test_returns_empty_for_invalid_since(self):
        from tg_parser.mcp_server import get_watchlist_matches

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        patches = _patch_mcp(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = await get_watchlist_matches(
                interest_id="i-1",
                since_iso="not-a-date",
            )
        finally:
            _exit_all(patches)
        assert result.count == 0
        assert result.matches == []


# ----------------------------------------------------------------------------
# backfill_watchlist (ADR-0011 S3)
# ----------------------------------------------------------------------------


def _backfill_svc(ir: _FakeInterestRepo, mr: _FakeMatchRepo, docs: list) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo(docs),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


@pytest.mark.asyncio
class TestBackfillWatchlist:
    async def test_apply_without_confirm_is_rejected(self):
        # ADR-0011 Part C: a mutating apply (dry_run=False) without confirm=true
        # must be rejected and write nothing.
        from tg_parser.mcp_server import backfill_watchlist

        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.1))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _backfill_svc(ir, mr, [doc])
        patches = _patch_mcp(svc, ir, mr, user=_admin("user-1"))
        _enter_all(patches)
        try:
            result = await backfill_watchlist(interest_id="i-1", dry_run=False)
        finally:
            _exit_all(patches)
        assert "confirmation required" in (result.get("error") or "").lower()
        assert len(mr.store) == 0

    async def test_apply_with_confirm_materializes_silently(self):
        # ADR-0011: confirm=true persists ALL matches with notified=True (silent).
        from tg_parser.mcp_server import backfill_watchlist

        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.1))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _backfill_svc(ir, mr, [doc])
        patches = _patch_mcp(svc, ir, mr, user=_admin("user-1"))
        _enter_all(patches)
        try:
            result = await backfill_watchlist(
                interest_id="i-1", dry_run=False, confirm=True
            )
        finally:
            _exit_all(patches)
        assert result.get("error") is None
        assert result["dry_run"] is False
        assert result["inserted"] == 1
        assert len(mr.store) == 1
        assert all(m.notified is True for m in mr.store.values())

    async def test_dry_run_default_full_corpus_no_write(self):
        # ADR-0011 Problem A: since_iso default = full corpus, so a fresh
        # interest still scores its history; dry-run writes nothing.
        from tg_parser.mcp_server import backfill_watchlist

        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.1))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _backfill_svc(ir, mr, [doc])
        patches = _patch_mcp(svc, ir, mr, user=_admin("user-1"))
        _enter_all(patches)
        try:
            result = await backfill_watchlist(interest_id="i-1")
        finally:
            _exit_all(patches)
        assert result.get("error") is None
        assert result["dry_run"] is True
        assert result["scored_docs"] == 1
        assert result["would_match"] == 1
        assert len(mr.store) == 0
