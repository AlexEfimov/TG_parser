"""HTTP API tests for the Idempotency-Key middleware (Wave 1 step 3 commit 4/4).

Covers the Stripe-style ``Idempotency-Key`` dependency wired on
``POST /api/v1/watchlists`` + ``POST /api/v1/digests`` per Q-OPEN-7
(opt-in per endpoint). All scenarios from §F of the sprint prompt
plus the explicit risk-mitigation tests (R-2 4xx-not-cached, R-4
canonical-hash stability) and the cross-user scope isolation.

PG-gated functional tests piggyback on ``test_db`` from
``tests/conftest.py`` (same shape as ``test_api_watchlists.py``).
Each test installs an auth-resolver override so the
``X-API-Key`` chain is bypassed and the dependency receives the
exact ``CurrentUser`` the scenario needs.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.idempotency import canonicalize_body, replay_idempotency_body
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _user(user_id: str, *, name: str = "alice", role: str = "user") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=None if role == "admin" else [],
        max_channels=100,
    )


def _override_user(app, user: CurrentUser) -> None:
    async def _resolver() -> CurrentUser:
        return user

    app.dependency_overrides[resolve_current_user] = _resolver


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def _idem_db(test_db):
    """Wipe F4 / F11 / F6 / idempotency tables for a clean per-test slate."""
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM idempotency_keys"))
        await session.execute(text("DELETE FROM watch_matches"))
        await session.execute(text("DELETE FROM watch_interests"))
        await session.execute(text("DELETE FROM digest_subscriptions"))
        await session.execute(text("DELETE FROM workspace_sources"))
        await session.execute(text("DELETE FROM workspaces"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db


@pytest.fixture
async def user_repo(_idem_db):
    session = _idem_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


# ── Pure helper tests (no DB) ───────────────────────────────────────────────


class TestCanonicalize:
    """R-4 mitigation — canonical JSON encoding must be order-stable."""

    def test_sorts_keys_for_stable_hash(self):
        a = canonicalize_body(b'{"a": 1, "b": 2}')
        b = canonicalize_body(b'{"b": 2, "a": 1}')
        assert a == b == b'{"a":1,"b":2}'

    def test_handles_empty_body(self):
        assert canonicalize_body(b"") == b""

    def test_passes_through_non_json(self):
        """Non-JSON bodies pass through verbatim (no crash)."""
        assert canonicalize_body(b"not json at all") == b"not json at all"

    def test_strips_whitespace(self):
        """Different whitespace shapes collapse to identical canonical form."""
        a = canonicalize_body(b'{ "a": 1 , "b":  2 }')
        b = canonicalize_body(b'{"a":1,"b":2}')
        assert a == b

    def test_replay_idempotency_body_forces_created_false(self):
        replay = replay_idempotency_body(
            {"watchlist_id": "wl-1", "created": True, "changed_fields": []}
        )
        assert replay["created"] is False
        assert replay["watchlist_id"] == "wl-1"


# ── Functional tests — watchlist endpoint ──────────────────────────────────


@pg_only
class TestNoHeaderPassthrough:
    """Without ``Idempotency-Key``, the endpoint runs unchanged and no cache row is written."""

    async def test_first_request_no_header_passes_through(self, app, client, user_repo, _idem_db):
        owner = await user_repo.create_user("alice_no_header")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["created"] is True

        # No header → no cache row written.
        session = _idem_db.ingestion_state_session()
        try:
            result = await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
            assert result.fetchone()[0] == 0
        finally:
            await session.close()


@pg_only
class TestCacheHit:
    """Same key + same body → cached response replayed, no second DB write."""

    async def test_same_key_same_body_returns_cached_response(
        self, app, client, user_repo, _idem_db
    ):
        owner = await user_repo.create_user("alice_cache_hit")
        _override_user(app, _user(owner.id))

        payload = {"title": "MiCA", "channel_ids": ["crypto_news"], "chat_id": 12345}
        headers = {"Idempotency-Key": "k-cache-hit"}

        first = await client.post("/api/v1/watchlists", json=payload, headers=headers)
        second = await client.post("/api/v1/watchlists", json=payload, headers=headers)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["created"] is True
        assert second.json()["watchlist_id"] == first.json()["watchlist_id"]
        assert second.json()["created"] is False
        assert second.json()["changed_fields"] == []

        # Exactly one cache row + one interest row.
        session = _idem_db.ingestion_state_session()
        try:
            keys_count = (
                await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
            ).fetchone()[0]
            interests_count = (
                await session.execute(text("SELECT COUNT(*) FROM watch_interests"))
            ).fetchone()[0]
        finally:
            await session.close()
        assert keys_count == 1
        assert interests_count == 1


@pg_only
class TestBodyHashMismatch:
    """Q-OPEN-1: same key + different body → 422 ``IdempotencyKeyMismatch``."""

    async def test_same_key_different_body_returns_422_mismatch(
        self, app, client, user_repo, _idem_db
    ):
        owner = await user_repo.create_user("alice_mismatch")
        _override_user(app, _user(owner.id))

        headers = {"Idempotency-Key": "k-mismatch"}

        first = await client.post(
            "/api/v1/watchlists",
            json={"title": "MiCA", "channel_ids": ["crypto_news"], "chat_id": 12345},
            headers=headers,
        )
        assert first.status_code == 201, first.text

        second = await client.post(
            "/api/v1/watchlists",
            json={"title": "DIFFERENT", "channel_ids": ["crypto_news"], "chat_id": 12345},
            headers=headers,
        )

        assert second.status_code == 422, second.text
        body = second.json()
        assert body["error_class"] == "IdempotencyKeyMismatch"
        assert "different request body" in body["detail"].lower()

        # No new interest row (mismatch never reached the service).
        session = _idem_db.ingestion_state_session()
        try:
            count = (
                await session.execute(text("SELECT COUNT(*) FROM watch_interests"))
            ).fetchone()[0]
        finally:
            await session.close()
        assert count == 1


@pg_only
class TestNon2xxNotCached:
    """R-2: only 2xx outcomes cached; 4xx pass through without writing a cache row."""

    async def test_4xx_validation_response_not_cached(self, app, client, user_repo, _idem_db):
        owner = await user_repo.create_user("alice_no_cache_4xx")
        _override_user(app, _user(owner.id))

        headers = {"Idempotency-Key": "k-r2"}

        # First POST: validation fails (empty title → 422 from Pydantic).
        first = await client.post(
            "/api/v1/watchlists",
            json={"title": "", "channel_ids": ["crypto_news"], "chat_id": 12345},
            headers=headers,
        )
        assert first.status_code == 422, first.text

        # No cache row should be present.
        session = _idem_db.ingestion_state_session()
        try:
            count_after_4xx = (
                await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
            ).fetchone()[0]
        finally:
            await session.close()
        assert count_after_4xx == 0

        # Second POST same key + valid body → normal 201 (cache miss).
        second = await client.post(
            "/api/v1/watchlists",
            json={"title": "MiCA", "channel_ids": ["crypto_news"], "chat_id": 12345},
            headers=headers,
        )
        assert second.status_code == 201, second.text
        assert second.json()["created"] is True


@pg_only
class TestCanonicalHashStability:
    """R-4 end-to-end: clients can re-serialize the body in different key order and still hit cache."""

    async def test_canonical_body_hash_stable_across_key_order(
        self, app, client, user_repo, _idem_db
    ):
        owner = await user_repo.create_user("alice_canonical")
        _override_user(app, _user(owner.id))

        headers = {"Idempotency-Key": "k-canonical"}

        first = await client.post(
            "/api/v1/watchlists",
            content=b'{"title":"MiCA","channel_ids":["crypto_news"],"chat_id":12345}',
            headers={**headers, "Content-Type": "application/json"},
        )
        assert first.status_code == 201, first.text

        second = await client.post(
            "/api/v1/watchlists",
            content=b'{"chat_id":12345,"channel_ids":["crypto_news"],"title":"MiCA"}',
            headers={**headers, "Content-Type": "application/json"},
        )

        assert second.status_code == 201, second.text
        assert first.json()["created"] is True
        assert first.json()["watchlist_id"] == second.json()["watchlist_id"]
        assert second.json()["created"] is False
        assert second.json()["changed_fields"] == []


@pg_only
class TestPerUserScope:
    """Keys are partitioned by ``user_id`` — Bob can never replay Alice's cached response.

    Note on the schema: ``idempotency_keys`` PK is ``(key)`` alone (locked
    by commit 1/4 migration ``f1a2b3c4d5e6``). Cross-user same-key
    collisions therefore degrade gracefully — the second user's POST
    proceeds through the normal flow (the ``find_by_key(user_id=...)``
    filter never returns Alice's row to Bob, so no incorrect cache hit
    is possible) but does not get a fresh cache row because the INSERT
    runs ``ON CONFLICT (key) DO NOTHING``. That trade-off is acceptable:
    the security-critical invariant — "Bob never gets Alice's cached
    response" — holds; only the second user loses retry-caching
    benefit, which is harmless given the service-layer natural-key
    upsert collapses duplicates anyway.
    """

    async def test_idempotency_key_scoped_to_user(self, app, client, user_repo, _idem_db):
        alice = await user_repo.create_user("alice_per_user")
        bob = await user_repo.create_user("bob_per_user")

        headers = {"Idempotency-Key": "shared-key"}

        _override_user(app, _user(alice.id))
        first = await client.post(
            "/api/v1/watchlists",
            json={"title": "alice-topic", "channel_ids": ["chan"], "chat_id": 111},
            headers=headers,
        )
        assert first.status_code == 201, first.text

        _override_user(app, _user(bob.id))
        second = await client.post(
            "/api/v1/watchlists",
            json={"title": "bob-topic", "channel_ids": ["chan"], "chat_id": 222},
            headers=headers,
        )
        # Critical: Bob's POST proceeds with HIS payload (not Alice's
        # cached response replayed). Different watchlist_id proves no
        # cross-user leakage of the cached body.
        assert second.status_code == 201, second.text
        assert second.json()["watchlist_id"] != first.json()["watchlist_id"]
        assert second.json()["created"] is True

        # The single surviving cache row belongs to Alice (the first
        # writer wins under the global ``UNIQUE(key)`` constraint). Bob
        # retains correctness without retry-caching benefit.
        session = _idem_db.ingestion_state_session()
        try:
            rows = (
                await session.execute(
                    text("SELECT user_id FROM idempotency_keys WHERE key = 'shared-key'")
                )
            ).fetchall()
        finally:
            await session.close()
        assert len(rows) == 1
        assert str(rows[0][0]) == alice.id


@pg_only
class TestDigestPropagation:
    """Q-OPEN-7: digest POST is the second opt-in endpoint."""

    async def test_idempotency_key_on_digest_endpoint(self, app, client, user_repo, _idem_db):
        owner = await user_repo.create_user("alice_digest_idem")
        _override_user(app, _user(owner.id))

        payload = {
            "name": "morning-roundup",
            "channel_ids": ["crypto_news"],
            "chat_id": 999,
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
            "format": "summary",
        }
        headers = {"Idempotency-Key": "k-digest"}

        first = await client.post("/api/v1/digests", json=payload, headers=headers)
        second = await client.post("/api/v1/digests", json=payload, headers=headers)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["digest_id"] == second.json()["digest_id"]
        assert first.json()["created"] is True
        assert second.json()["created"] is False

        session = _idem_db.ingestion_state_session()
        try:
            keys_count = (
                await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
            ).fetchone()[0]
            digests_count = (
                await session.execute(text("SELECT COUNT(*) FROM digest_subscriptions"))
            ).fetchone()[0]
        finally:
            await session.close()
        assert keys_count == 1
        assert digests_count == 1


@pg_only
class TestNonOptedInEndpointUnaffected:
    """Q-OPEN-7: other POST endpoints are NOT touched by the middleware.

    GET /api/v1/watchlists is not a POST surface; this test confirms
    sending ``Idempotency-Key`` on a non-opted-in endpoint has no effect
    and never writes to ``idempotency_keys``.
    """

    async def test_get_endpoint_with_header_does_not_write_cache_row(
        self, app, client, user_repo, _idem_db
    ):
        owner = await user_repo.create_user("alice_get_unaffected")
        _override_user(app, _user(owner.id))

        response = await client.get(
            "/api/v1/watchlists",
            headers={"Idempotency-Key": "k-on-get"},
        )
        assert response.status_code == 200, response.text

        session = _idem_db.ingestion_state_session()
        try:
            count = (
                await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
            ).fetchone()[0]
        finally:
            await session.close()
        assert count == 0
