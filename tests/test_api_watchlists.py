"""
HTTP API tests for the watchlist surface (Wave 1 step 3 commit 2/4 / P-1).

Covers the five endpoints under ``/api/v1/watchlists`` introduced in
this commit:

* ``POST   /api/v1/watchlists``                       — subscribe.
* ``GET    /api/v1/watchlists``                       — list.
* ``GET    /api/v1/watchlists/{id}``                  — get single.
* ``DELETE /api/v1/watchlists/{id}``                  — soft-delete.
* ``GET    /api/v1/watchlists/{id}/matches``          — match history.

Test split:

* Auth gate tests (no DB) — verify 401 / 403 via the same
  ``X-API-Key`` machinery used elsewhere on the API.
* Functional tests (PG-gated) — exercise the full request/response
  contract end-to-end against the real ingestion DB. They mirror the
  scenarios listed in the sprint prompt §5 test plan.

The PG-backed tests piggyback on ``test_db`` from ``tests/conftest.py``
and the ``TEST_POSTGRES`` env gate (same shape as ``test_f11_*`` and
``test_f4b_*``). Auth dependency is overridden via
``app.dependency_overrides[resolve_current_user]`` so each test can
inject the exact ``CurrentUser`` it needs without standing up the
``X-API-Key`` → user-resolver chain.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.domain.models import WatchMatch
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.watch_interest_repo import SAWatchInterestRepo
from tg_parser.storage.sqlalchemy.watch_match_repo import SAWatchMatchRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _user(user_id: str, *, name: str = "alice", role: str = "user") -> CurrentUser:
    """Build a :class:`CurrentUser` with admin-like field defaults.

    Non-admin roles get an empty ``allowed_channel_ids`` so the
    F4-A channel-scope guard does not interfere — the watchlist
    surface does not run ``assert_channel_access`` itself (callers
    are free to subscribe to channels they don't own at the HTTP
    layer; the scheduler hook is the one that enforces visibility).
    """
    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=None if role == "admin" else [],
        max_channels=100,
    )


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Fresh FastAPI app per test (mirrors ``test_api_security.py``)."""
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def _watchlist_db(test_db):
    """Truncate F4 + F11 + workspace tables for a clean per-test slate."""
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM watch_matches"))
        await session.execute(text("DELETE FROM watch_interests"))
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
async def user_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def workspace_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAWorkspaceRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def interest_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAWatchInterestRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def match_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAWatchMatchRepo(session)
    finally:
        await session.close()


def _override_user(app, user: CurrentUser) -> None:
    """Install / replace the auth dependency override for the current test."""

    async def _resolver() -> CurrentUser:
        return user

    app.dependency_overrides[resolve_current_user] = _resolver


# ============================================================================
# Auth gate tests — no DB, just verify the X-API-Key contract is reachable.
# ============================================================================


class TestAuthGates:
    """Auth contract tests for POST /api/v1/watchlists (Q1).

    These are the only watchlist tests that do NOT use the dependency
    override — we deliberately let the real ``resolve_current_user``
    run so the X-API-Key dependency chain is exercised end-to-end.
    """

    async def test_create_watchlist_missing_api_key_returns_401(self, app):
        """No X-API-Key header + api_key_required=True → 401 from the resolver."""
        transport = ASGITransport(app=app)
        with patch("tg_parser.api.auth.settings") as mock:
            mock.api_key_required = True
            mock.api_keys = {"valid-key": "tester"}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/watchlists",
                    json={
                        "title": "MiCA",
                        "channel_ids": ["crypto_news"],
                        "chat_id": 42,
                    },
                )
        assert response.status_code == 401, response.text

    async def test_create_watchlist_invalid_api_key_returns_403(self, app):
        """Wrong X-API-Key value + api_key_required=True → 403."""
        transport = ASGITransport(app=app)
        with patch("tg_parser.api.auth.settings") as mock:
            mock.api_key_required = True
            mock.api_keys = {"valid-key": "tester"}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/watchlists",
                    headers={"X-API-Key": "totally-wrong-key"},
                    json={
                        "title": "MiCA",
                        "channel_ids": ["crypto_news"],
                        "chat_id": 42,
                    },
                )
        assert response.status_code == 403, response.text


# ============================================================================
# Functional tests (PG-gated).
# ============================================================================


@pg_only
class TestCreateWatchlist:
    async def test_happy_path(self, app, client, user_repo):
        owner = await user_repo.create_user("alice_create")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
                "keywords": ["mica"],
                "description": "EU crypto rules",
                "threshold": 0.55,
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        # Q-OPEN-1 shape: {watchlist_id, created, changed_fields}.
        assert set(body.keys()) == {"watchlist_id", "created", "changed_fields"}
        assert isinstance(body["watchlist_id"], str) and body["watchlist_id"]
        assert body["created"] is True
        assert body["changed_fields"] == []

    async def test_idempotent_same_args_returns_existing_id(self, app, client, user_repo):
        owner = await user_repo.create_user("alice_idem_same")
        _override_user(app, _user(owner.id))

        payload = {
            "title": "MiCA",
            "channel_ids": ["crypto_news"],
            "chat_id": 12345,
            "keywords": ["mica"],
            "threshold": 0.6,
        }
        first = await client.post("/api/v1/watchlists", json=payload)
        second = await client.post("/api/v1/watchlists", json=payload)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["watchlist_id"] == second.json()["watchlist_id"]
        assert second.json()["created"] is False
        assert second.json()["changed_fields"] == []

    async def test_idempotency_key_replay_created_false(self, app, client, user_repo):
        """Idempotency-Key HTTP replay must not report created=true (BUG-022 HTTP arm)."""
        owner = await user_repo.create_user("alice_idem_key")
        _override_user(app, _user(owner.id))

        payload = {
            "title": "MiCA-key",
            "channel_ids": ["crypto_news"],
            "chat_id": 12345,
        }
        headers = {"Idempotency-Key": "wl-replay-key"}
        first = await client.post("/api/v1/watchlists", json=payload, headers=headers)
        second = await client.post("/api/v1/watchlists", json=payload, headers=headers)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["created"] is True
        assert second.json()["watchlist_id"] == first.json()["watchlist_id"]
        assert second.json()["created"] is False

    async def test_upsert_different_args_lists_changed_fields(self, app, client, user_repo):
        owner = await user_repo.create_user("alice_idem_diff")
        _override_user(app, _user(owner.id))

        first = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
                "keywords": ["mica"],
                "threshold": 0.6,
            },
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
                "keywords": ["mica", "psd3"],
                "threshold": 0.6,
            },
        )

        assert second.status_code == 201
        assert second.json()["watchlist_id"] == first.json()["watchlist_id"]
        assert second.json()["created"] is False
        assert "keywords" in second.json()["changed_fields"]

    async def test_workspace_id_valid_attaches_fk(self, app, client, user_repo, workspace_repo):
        owner = await user_repo.create_user("alice_ws_ok")
        ws = await workspace_repo.create(owner_id=owner.id, name="EU reg")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
                "workspace_id": ws.id,
            },
        )
        assert response.status_code == 201, response.text

        # Verify by reading back through the GET single endpoint so the
        # ``workspace_name`` JOIN (Q-OPEN-3) is exercised in the same test.
        get_response = await client.get(f"/api/v1/watchlists/{response.json()['watchlist_id']}")
        assert get_response.status_code == 200, get_response.text
        body = get_response.json()
        assert body["workspace_id"] == ws.id
        assert body["workspace_name"] == "EU reg"

    async def test_workspace_id_foreign_returns_404_workspace_not_found(
        self, app, client, user_repo, workspace_repo
    ):
        alice = await user_repo.create_user("alice_ws_foreign")
        bob = await user_repo.create_user("bob_ws_owner")
        foreign_ws = await workspace_repo.create(owner_id=bob.id, name="other")
        _override_user(app, _user(alice.id))

        response = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
                "workspace_id": foreign_ws.id,
            },
        )

        assert response.status_code == 404, response.text
        body = response.json()
        assert body["error_class"] == "WorkspaceNotFound"
        assert "not found" in body["detail"].lower()

    async def test_workspace_id_unknown_uuid_returns_404_workspace_not_found(
        self, app, client, user_repo
    ):
        """Unknown (well-formed but non-existent) workspace_id → same 404 / error_class.

        Mirrors :meth:`test_workspace_id_foreign_returns_404_workspace_not_found`
        but with a UUID that has *never* existed in the workspaces table.
        Both unknown and foreign collapse to the same
        ``WorkspaceNotFound`` per Q-OPEN-3 + the F4-B EC2 contract —
        existence of a foreign workspace must not be leaked via a
        distinguishable error code.
        """
        owner = await user_repo.create_user("alice_ws_unknown")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "MiCA",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
                "workspace_id": "00000000-0000-0000-0000-000000000999",
            },
        )

        assert response.status_code == 404, response.text
        body = response.json()
        assert body["error_class"] == "WorkspaceNotFound"
        assert "not found" in body["detail"].lower()

    async def test_validation_empty_title_returns_422(self, app, client, user_repo):
        """Title violates ``min_length=1`` → Pydantic 422 before the service runs.

        Guards against future schema regression where the
        ``WatchlistCreateRequest.title`` constraint gets relaxed and
        an empty title leaks all the way to the service-layer
        ``WatchInterest`` validator (which would surface as 500
        instead of the locked 422 contract).
        """
        owner = await user_repo.create_user("alice_validation_title")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/watchlists",
            json={
                "title": "",
                "channel_ids": ["crypto_news"],
                "chat_id": 12345,
            },
        )
        assert response.status_code == 422, response.text


@pg_only
class TestListWatchlists:
    async def test_scoped_to_user(self, app, client, user_repo, interest_repo):
        alice = await user_repo.create_user("alice_list_scope")
        bob = await user_repo.create_user("bob_list_scope")

        # Seed one interest per user via the repo (bypass the HTTP layer).
        from tg_parser.domain.models import NotifyMode, WatchInterest

        for owner_id, title in ((alice.id, "alice-MiCA"), (bob.id, "bob-MiCA")):
            await interest_repo.create(
                WatchInterest(
                    id="",
                    user_id=owner_id,
                    chat_id=42,
                    title=title,
                    description=None,
                    keywords=["mica"],
                    exclude_keywords=[],
                    channel_ids=["crypto_news"],
                    threshold=0.6,
                    notify_mode=NotifyMode.INSTANT,
                    is_active=True,
                    embedding=None,
                )
            )

        _override_user(app, _user(alice.id))
        response = await client.get("/api/v1/watchlists")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert [i["title"] for i in body["items"]] == ["alice-MiCA"]
        assert body["items"][0]["user_id"] == alice.id

    async def test_pagination_offset_limit(self, app, client, user_repo, interest_repo):
        owner = await user_repo.create_user("alice_list_pagi")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        for n in range(5):
            await interest_repo.create(
                WatchInterest(
                    id="",
                    user_id=owner.id,
                    chat_id=100 + n,
                    title=f"watch-{n}",
                    description=None,
                    keywords=["x"],
                    exclude_keywords=[],
                    channel_ids=["chan"],
                    threshold=0.6,
                    notify_mode=NotifyMode.INSTANT,
                    is_active=True,
                    embedding=None,
                )
            )

        _override_user(app, _user(owner.id))
        response = await client.get("/api/v1/watchlists", params={"offset": 1, "limit": 2})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

    async def test_empty_list_returns_zero_total(self, app, client, user_repo):
        """Caller with zero interests → ``{items: [], total: 0}``.

        Sanity check for the Q7 envelope shape under the empty-row
        case — guards against accidental "return None / 204" drift.
        """
        owner = await user_repo.create_user("alice_list_empty")
        _override_user(app, _user(owner.id))

        response = await client.get("/api/v1/watchlists")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {"items": [], "total": 0}

    async def test_workspace_name_resolved_in_list(
        self, app, client, user_repo, interest_repo, workspace_repo
    ):
        """List endpoint joins ``workspaces.name`` for items with ``workspace_id``.

        Verifies the Q-OPEN-3 single-JOIN contract on the *list*
        path (the single-GET path is covered by
        :meth:`TestCreateWatchlist.test_workspace_id_valid_attaches_fk`).
        Items without ``workspace_id`` carry ``workspace_name=None``
        on the same response so the field is always present.
        """
        owner = await user_repo.create_user("alice_list_wsname")
        ws = await workspace_repo.create(owner_id=owner.id, name="EU reg")

        from tg_parser.domain.models import NotifyMode, WatchInterest

        await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=42,
                title="with-ws",
                description=None,
                keywords=["x"],
                exclude_keywords=[],
                channel_ids=["chan"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
                workspace_id=ws.id,
            )
        )
        await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=43,
                title="no-ws",
                description=None,
                keywords=["x"],
                exclude_keywords=[],
                channel_ids=["chan"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )

        _override_user(app, _user(owner.id))
        response = await client.get("/api/v1/watchlists")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        by_title = {item["title"]: item for item in body["items"]}
        assert by_title["with-ws"]["workspace_id"] == ws.id
        assert by_title["with-ws"]["workspace_name"] == "EU reg"
        assert by_title["no-ws"]["workspace_id"] is None
        assert by_title["no-ws"]["workspace_name"] is None


@pg_only
class TestGetWatchlist:
    async def test_owner_gets_full_payload(
        self, app, client, user_repo, interest_repo, workspace_repo
    ):
        owner = await user_repo.create_user("alice_get")
        ws = await workspace_repo.create(owner_id=owner.id, name="EU reg")

        from tg_parser.domain.models import NotifyMode, WatchInterest

        stored = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=12345,
                title="MiCA",
                description="EU regulation",
                keywords=["mica"],
                exclude_keywords=[],
                channel_ids=["crypto_news"],
                threshold=0.65,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
                workspace_id=ws.id,
            )
        )

        _override_user(app, _user(owner.id))
        response = await client.get(f"/api/v1/watchlists/{stored.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == stored.id
        assert body["workspace_id"] == ws.id
        assert body["workspace_name"] == "EU reg"
        assert body["threshold"] == pytest.approx(0.65)
        assert body["keywords"] == ["mica"]
        assert "embedding" not in body  # explicitly elided per WatchlistResponse contract

    async def test_foreign_interest_returns_404_not_403(
        self, app, client, user_repo, interest_repo
    ):
        alice = await user_repo.create_user("alice_get_foreign")
        bob = await user_repo.create_user("bob_get_foreign")

        from tg_parser.domain.models import NotifyMode, WatchInterest

        bob_interest = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=bob.id,
                chat_id=42,
                title="bob-only",
                description=None,
                keywords=["x"],
                exclude_keywords=[],
                channel_ids=["chan"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )

        _override_user(app, _user(alice.id))
        response = await client.get(f"/api/v1/watchlists/{bob_interest.id}")

        assert response.status_code == 404, response.text
        body = response.json()
        assert body["error_class"] == "NotFound"

    async def test_unknown_uuid_returns_404(self, app, client, user_repo):
        """Well-formed but non-existent watchlist UUID → 404 ``NotFound``.

        Distinct from the foreign-ownership case (a row exists but
        belongs to someone else): here no row exists at all. Both
        collapse to ``error_class=NotFound`` so a caller cannot infer
        whether a UUID is "free" or "taken by another tenant".
        """
        owner = await user_repo.create_user("alice_get_unknown")
        _override_user(app, _user(owner.id))

        response = await client.get("/api/v1/watchlists/00000000-0000-0000-0000-000000000999")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"


@pg_only
class TestDeleteWatchlist:
    async def test_soft_delete_preserves_matches(
        self, app, client, user_repo, interest_repo, match_repo
    ):
        owner = await user_repo.create_user("alice_delete_soft")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        stored = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=42,
                title="MiCA",
                description=None,
                keywords=["mica"],
                exclude_keywords=[],
                channel_ids=["crypto_news"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )
        # Seed a match so we can verify history survives.
        await match_repo.upsert_many(
            [
                WatchMatch(
                    id=0,
                    interest_id=stored.id,
                    source_ref="tg:crypto_news:post:1",
                    channel_id="crypto_news",
                    keyword_score=0.7,
                    semantic_score=0.0,
                    combined_score=0.7,
                    notified=False,
                )
            ]
        )

        _override_user(app, _user(owner.id))
        response = await client.delete(f"/api/v1/watchlists/{stored.id}")
        assert response.status_code == 204, response.text
        assert response.content == b""  # 204 must be body-less

        # Matches endpoint still serves history (Q8 watchlist variant).
        matches_resp = await client.get(f"/api/v1/watchlists/{stored.id}/matches")
        assert matches_resp.status_code == 200, matches_resp.text
        body = matches_resp.json()
        assert body["total"] == 1
        assert body["items"][0]["source_ref"] == "tg:crypto_news:post:1"

    async def test_idempotent_second_call_also_204(self, app, client, user_repo, interest_repo):
        owner = await user_repo.create_user("alice_delete_idem")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        stored = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=42,
                title="MiCA",
                description=None,
                keywords=["mica"],
                exclude_keywords=[],
                channel_ids=["crypto_news"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )

        _override_user(app, _user(owner.id))
        first = await client.delete(f"/api/v1/watchlists/{stored.id}")
        second = await client.delete(f"/api/v1/watchlists/{stored.id}")

        assert first.status_code == 204
        assert second.status_code == 204  # REST-strict per parent Q-OPEN-8 lock.

    async def test_foreign_interest_returns_404(self, app, client, user_repo, interest_repo):
        alice = await user_repo.create_user("alice_delete_foreign")
        bob = await user_repo.create_user("bob_delete_foreign")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        bob_interest = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=bob.id,
                chat_id=42,
                title="bob-only",
                description=None,
                keywords=["x"],
                exclude_keywords=[],
                channel_ids=["chan"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )
        _override_user(app, _user(alice.id))
        response = await client.delete(f"/api/v1/watchlists/{bob_interest.id}")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"

    async def test_unknown_uuid_returns_404(self, app, client, user_repo):
        """DELETE on a never-existed UUID → 404 ``NotFound`` (not 204).

        REST-strict idempotency per Q-OPEN-8 collapses repeated
        DELETEs on an existing row to 204 — but for an id that has
        never been written we still want a 404 so clients can
        distinguish "deleted-by-someone" from "your id never
        existed". The ``NotFound`` error_class matches the GET single
        contract.
        """
        owner = await user_repo.create_user("alice_delete_unknown")
        _override_user(app, _user(owner.id))

        response = await client.delete("/api/v1/watchlists/00000000-0000-0000-0000-000000000999")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"


@pg_only
class TestGetMatches:
    async def test_filtered_by_since(self, app, client, user_repo, interest_repo, match_repo):
        owner = await user_repo.create_user("alice_matches_since")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        stored = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=42,
                title="MiCA",
                description=None,
                keywords=["mica"],
                exclude_keywords=[],
                channel_ids=["crypto_news"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )
        await match_repo.upsert_many(
            [
                WatchMatch(
                    id=0,
                    interest_id=stored.id,
                    source_ref=f"tg:crypto_news:post:{n}",
                    channel_id="crypto_news",
                    keyword_score=0.7,
                    semantic_score=0.0,
                    combined_score=0.7,
                    notified=False,
                )
                for n in range(3)
            ]
        )

        _override_user(app, _user(owner.id))
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = await client.get(
            f"/api/v1/watchlists/{stored.id}/matches",
            params={"since": future},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 0  # strict-`>` filter drops every row with created_at <= since.
        assert body["items"] == []

    async def test_pagination_offset_limit(self, app, client, user_repo, interest_repo, match_repo):
        owner = await user_repo.create_user("alice_matches_pagi")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        stored = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=owner.id,
                chat_id=42,
                title="MiCA",
                description=None,
                keywords=["mica"],
                exclude_keywords=[],
                channel_ids=["crypto_news"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )
        await match_repo.upsert_many(
            [
                WatchMatch(
                    id=0,
                    interest_id=stored.id,
                    source_ref=f"tg:crypto_news:post:{n}",
                    channel_id="crypto_news",
                    keyword_score=0.7,
                    semantic_score=0.0,
                    combined_score=0.7,
                    notified=False,
                )
                for n in range(5)
            ]
        )

        _override_user(app, _user(owner.id))
        response = await client.get(
            f"/api/v1/watchlists/{stored.id}/matches",
            params={"offset": 2, "limit": 2},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

    async def test_foreign_interest_returns_404_not_403(
        self, app, client, user_repo, interest_repo
    ):
        """Match-history visibility tracks owner-only just like GET single.

        Bob owns the interest; alice asks for ``/{bob_id}/matches``.
        Mirrors :meth:`TestGetWatchlist.test_foreign_interest_returns_404_not_403`
        but on the sub-resource path — the cross-tenant guard must
        apply to every endpoint that exposes interest data, not just
        the top-level GET.
        """
        alice = await user_repo.create_user("alice_matches_foreign")
        bob = await user_repo.create_user("bob_matches_foreign")
        from tg_parser.domain.models import NotifyMode, WatchInterest

        bob_interest = await interest_repo.create(
            WatchInterest(
                id="",
                user_id=bob.id,
                chat_id=42,
                title="bob-only",
                description=None,
                keywords=["x"],
                exclude_keywords=[],
                channel_ids=["chan"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                is_active=True,
                embedding=None,
            )
        )
        _override_user(app, _user(alice.id))
        response = await client.get(f"/api/v1/watchlists/{bob_interest.id}/matches")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"
