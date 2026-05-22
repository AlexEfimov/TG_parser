"""
HTTP API tests for the digest surface (Wave 1 step 3 commit 3/4 / P-2).

Covers the four endpoints under ``/api/v1/digests`` introduced in this
commit:

* ``POST   /api/v1/digests``               — subscribe.
* ``GET    /api/v1/digests``               — list.
* ``GET    /api/v1/digests/{id}``          — get single.
* ``DELETE /api/v1/digests/{id}``          — HARD delete.

Test split mirrors ``tests/test_api_watchlists.py``:

* Auth gate tests (no DB) — verify 401 / 403 via the same
  ``X-API-Key`` machinery used elsewhere on the API.
* Functional tests (PG-gated) — exercise the full request/response
  contract end-to-end against the real ingestion DB. They mirror the
  scenarios listed in the sprint prompt §5 test plan.

Key asymmetries vs ``test_api_watchlists.py``:

* The label field is ``name`` (not ``title``) per Q6.
* The response shape uses ``digest_id`` (not ``watchlist_id``) per Q7.
* **DELETE is HARD**: the second DELETE on the same id returns 404,
  not 204 (Q8 digest variant + parent Q-OPEN-8 REST-strict lock).
* No ``/matches`` sub-resource (digest "matches" are scheduled sends).

The PG-backed tests piggyback on ``test_db`` from ``tests/conftest.py``
and the ``TEST_POSTGRES`` env gate (same shape as ``test_f6_*`` and
``test_api_watchlists``). Auth dependency is overridden via
``app.dependency_overrides[resolve_current_user]`` so each test can
inject the exact ``CurrentUser`` it needs without standing up the
``X-API-Key`` → user-resolver chain.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.domain.models import DigestFormat, DigestSubscription
from tg_parser.storage.sqlalchemy.digest_subscription_repo import SADigestSubscriptionRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _user(user_id: str, *, name: str = "alice", role: str = "user") -> CurrentUser:
    """Build a :class:`CurrentUser` mirroring the watchlist test helper.

    Non-admin roles get an empty ``allowed_channel_ids`` so the
    F4-A channel-scope guard does not interfere — the digest HTTP
    surface (like the watchlist one) does not run
    ``assert_channel_access`` itself; channel ownership is enforced
    at the MCP / Bot surfaces, the HTTP layer is intentionally a
    thinner wrapper so the same idempotent upsert is reachable from
    any client.
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
    """Fresh FastAPI app per test (mirrors ``test_api_watchlists.py``)."""
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def _digest_db(test_db):
    """Truncate F4 + F6 + users tables for a clean per-test slate."""
    session = test_db.ingestion_state_session()
    try:
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
async def user_repo(_digest_db):
    session = _digest_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def workspace_repo(_digest_db):
    session = _digest_db.ingestion_state_session()
    try:
        yield SAWorkspaceRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def subscription_repo(_digest_db):
    session = _digest_db.ingestion_state_session()
    try:
        yield SADigestSubscriptionRepo(session)
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
    """Auth contract tests for POST /api/v1/digests (Q1).

    These are the only digest tests that do NOT use the dependency
    override — we deliberately let the real ``resolve_current_user``
    run so the X-API-Key dependency chain is exercised end-to-end.
    """

    async def test_create_digest_missing_api_key_returns_401(self, app):
        """No X-API-Key header + api_key_required=True → 401 from the resolver."""
        transport = ASGITransport(app=app)
        with patch("tg_parser.api.auth.settings") as mock:
            mock.api_key_required = True
            mock.api_keys = {"valid-key": "tester"}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/digests",
                    json={
                        "name": "Morning brief",
                        "channel_ids": ["durov"],
                        "chat_id": 42,
                    },
                )
        assert response.status_code == 401, response.text

    async def test_create_digest_invalid_api_key_returns_403(self, app):
        """Wrong X-API-Key value + api_key_required=True → 403."""
        transport = ASGITransport(app=app)
        with patch("tg_parser.api.auth.settings") as mock:
            mock.api_key_required = True
            mock.api_keys = {"valid-key": "tester"}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/digests",
                    headers={"X-API-Key": "totally-wrong-key"},
                    json={
                        "name": "Morning brief",
                        "channel_ids": ["durov"],
                        "chat_id": 42,
                    },
                )
        assert response.status_code == 403, response.text


# ============================================================================
# Functional tests (PG-gated).
# ============================================================================


@pg_only
class TestCreateDigest:
    async def test_happy_path(self, app, client, user_repo):
        owner = await user_repo.create_user("alice_create")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "cron_expression": "0 9 * * *",
                "timezone": "UTC",
                "format": "summary",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        # Q-OPEN-1 shape: {digest_id, created, changed_fields}.
        assert set(body.keys()) == {"digest_id", "created", "changed_fields"}
        assert isinstance(body["digest_id"], str) and body["digest_id"]
        assert body["created"] is True
        assert body["changed_fields"] == []

    async def test_idempotent_same_args_returns_existing_id(self, app, client, user_repo):
        owner = await user_repo.create_user("alice_idem_same")
        _override_user(app, _user(owner.id))

        payload = {
            "name": "Daily brief",
            "channel_ids": ["durov"],
            "chat_id": 12345,
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
            "format": "summary",
        }
        first = await client.post("/api/v1/digests", json=payload)
        second = await client.post("/api/v1/digests", json=payload)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["digest_id"] == second.json()["digest_id"]
        assert second.json()["created"] is False
        assert second.json()["changed_fields"] == []

    async def test_upsert_different_cron_lists_changed_fields(self, app, client, user_repo):
        """Same name + different cron → ``changed_fields=["cron_expression"]``."""
        owner = await user_repo.create_user("alice_idem_diff")
        _override_user(app, _user(owner.id))

        first = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "cron_expression": "0 9 * * *",
                "timezone": "UTC",
                "format": "summary",
            },
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "cron_expression": "30 8 * * *",  # changed
                "timezone": "UTC",
                "format": "summary",
            },
        )

        assert second.status_code == 201
        assert second.json()["digest_id"] == first.json()["digest_id"]
        assert second.json()["created"] is False
        assert "cron_expression" in second.json()["changed_fields"]

    async def test_workspace_id_valid_attaches_fk_and_returns_workspace_name(
        self, app, client, user_repo, workspace_repo
    ):
        """ENH-9 + Q-OPEN-3 in one test: valid ``workspace_id`` is stored
        on POST and the follow-up GET single emits both ``workspace_id``
        and the JOIN-resolved ``workspace_name``.
        """
        owner = await user_repo.create_user("alice_ws_ok")
        ws = await workspace_repo.create(owner_id=owner.id, name="EU reg")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "EU brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "workspace_id": ws.id,
            },
        )
        assert response.status_code == 201, response.text

        get_response = await client.get(f"/api/v1/digests/{response.json()['digest_id']}")
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
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
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

        Parity with the P-1 watchlist surface: unknown and foreign
        collapse to the same ``WorkspaceNotFound`` so existence of a
        foreign workspace cannot be inferred from a distinguishable
        error code (F4-B EC2).
        """
        owner = await user_repo.create_user("alice_ws_unknown")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "workspace_id": "00000000-0000-0000-0000-000000000999",
            },
        )

        assert response.status_code == 404, response.text
        body = response.json()
        assert body["error_class"] == "WorkspaceNotFound"
        assert "not found" in body["detail"].lower()

    async def test_validation_empty_name_returns_422(self, app, client, user_repo):
        """``name`` violates ``min_length=1`` → Pydantic 422 before the service runs.

        Guards against future schema regression where the
        ``DigestCreateRequest.name`` constraint gets relaxed and an
        empty name leaks all the way to the service-layer
        ``DigestSubscription`` validator (which would surface as 500
        instead of the locked 422 contract).
        """
        owner = await user_repo.create_user("alice_validation_name")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "",
                "channel_ids": ["durov"],
                "chat_id": 12345,
            },
        )
        assert response.status_code == 422, response.text

    async def test_invalid_cron_returns_422_invalid_cron(self, app, client, user_repo):
        """Malformed cron → 422 with ``error_class="InvalidCron"`` AND no row written.

        The router pre-validates ``cron_expression`` + ``timezone``
        (mirror of the MCP path) so an invalid spec is rejected
        *before* the upsert runs and never leaves a half-written row.
        The follow-up GET list assertion is the §3 H.2 guard: it
        proves the pre-validation aborted before any INSERT, not just
        that the 422 was emitted with a stale row left behind.
        """
        owner = await user_repo.create_user("alice_cron_bad")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "cron_expression": "not a valid cron",
                "timezone": "UTC",
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["error_class"] == "InvalidCron"

        # No row was written — the pre-validation aborted before the upsert.
        list_resp = await client.get("/api/v1/digests")
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json() == {"items": [], "total": 0}

    async def test_invalid_timezone_returns_422_invalid_cron(self, app, client, user_repo):
        """Unknown IANA timezone → 422 with ``error_class="InvalidCron"``.

        The cron / timezone pre-validation pair lives in the same
        helper, so an unknown ``ZoneInfo`` name surfaces under the
        same ``error_class`` as a malformed cron. Mirrors the
        :func:`mcp_server.subscribe_digest` rejection shape so HTTP
        and MCP clients see parity. The unrelated cron field is
        deliberately valid here to isolate the timezone failure path.
        """
        owner = await user_repo.create_user("alice_tz_bad")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "cron_expression": "0 9 * * *",
                "timezone": "Mars/Olympus",
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error_class"] == "InvalidCron"

    async def test_invalid_format_returns_422(self, app, client, user_repo):
        """``format`` outside the Pydantic ``Literal`` → 422 before the service runs.

        Guards :class:`DigestCreateRequest.format` against silent
        widening (Literal-Enum drift): an unknown value must surface
        as a Pydantic validation error, not reach
        ``DigestFormat(...)`` which would raise ``ValueError`` and
        bubble to a 500 via the global exception handler.
        """
        owner = await user_repo.create_user("alice_format_bad")
        _override_user(app, _user(owner.id))

        response = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "format": "novella",  # not in Literal[summary, bullets, detailed]
            },
        )
        assert response.status_code == 422, response.text

    async def test_upsert_different_format_language_lists_changed_fields(
        self, app, client, user_repo
    ):
        """Same name + different format AND language → both fields surface
        on ``changed_fields`` and the row keeps the same id.

        Pairs with :meth:`test_upsert_different_cron_lists_changed_fields`
        to cover the non-cron mutable columns flagged by
        :meth:`DigestService._apply_digest_upsert`. Using a *set*
        comparison so future re-ordering inside the service does not
        flip this test (the contract is "exact set of fields", not
        "exact list order").
        """
        owner = await user_repo.create_user("alice_idem_fmt_lang")
        _override_user(app, _user(owner.id))

        first = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "format": "summary",
                "language": "ru",
            },
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/digests",
            json={
                "name": "Daily brief",
                "channel_ids": ["durov"],
                "chat_id": 12345,
                "format": "bullets",
                "language": "en",
            },
        )

        assert second.status_code == 201
        assert second.json()["digest_id"] == first.json()["digest_id"]
        assert second.json()["created"] is False
        assert set(second.json()["changed_fields"]) == {"format", "language"}


@pg_only
class TestListDigests:
    async def test_scoped_to_user(self, app, client, user_repo, subscription_repo):
        """List endpoint only returns rows owned by ``user.id`` (non-admin)."""
        alice = await user_repo.create_user("alice_list_scope")
        bob = await user_repo.create_user("bob_list_scope")

        # Seed one subscription per user via the repo (bypass the HTTP layer).
        for owner_id, name in ((alice.id, "alice-brief"), (bob.id, "bob-brief")):
            await subscription_repo.create(
                DigestSubscription(
                    id="",
                    owner_id=owner_id,
                    chat_id=42,
                    name=name,
                    channel_ids=["durov"],
                    cron_expression="0 9 * * *",
                    timezone="UTC",
                    format=DigestFormat.SUMMARY,
                    language="ru",
                    is_active=True,
                )
            )

        _override_user(app, _user(alice.id))
        response = await client.get("/api/v1/digests")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert [i["name"] for i in body["items"]] == ["alice-brief"]
        assert body["items"][0]["owner_id"] == alice.id

    async def test_pagination_offset_limit(self, app, client, user_repo, subscription_repo):
        owner = await user_repo.create_user("alice_list_pagi")

        for n in range(5):
            await subscription_repo.create(
                DigestSubscription(
                    id="",
                    owner_id=owner.id,
                    chat_id=100 + n,
                    name=f"brief-{n}",
                    channel_ids=["durov"],
                    cron_expression="0 9 * * *",
                    timezone="UTC",
                    format=DigestFormat.SUMMARY,
                    language="ru",
                    is_active=True,
                )
            )

        _override_user(app, _user(owner.id))
        response = await client.get("/api/v1/digests", params={"offset": 1, "limit": 2})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

    async def test_empty_list_returns_zero_total(self, app, client, user_repo):
        """Caller with zero subscriptions → ``{items: [], total: 0}``.

        Sanity check for the Q7 envelope shape under the empty-row
        case — guards against accidental "return None / 204" drift.
        """
        owner = await user_repo.create_user("alice_list_empty")
        _override_user(app, _user(owner.id))

        response = await client.get("/api/v1/digests")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {"items": [], "total": 0}

    async def test_workspace_name_resolved_in_list(
        self, app, client, user_repo, subscription_repo, workspace_repo
    ):
        """List endpoint joins ``workspaces.name`` for items with ``workspace_id``.

        Verifies the Q-OPEN-3 single-JOIN contract on the *list*
        path (the single-GET path is covered by
        :meth:`TestCreateDigest.test_workspace_id_valid_attaches_fk_and_returns_workspace_name`).
        Items without ``workspace_id`` carry ``workspace_name=None``
        on the same response so the field is always present.
        """
        owner = await user_repo.create_user("alice_list_wsname")
        ws = await workspace_repo.create(owner_id=owner.id, name="EU reg")

        await subscription_repo.create(
            DigestSubscription(
                id="",
                owner_id=owner.id,
                chat_id=42,
                name="with-ws",
                channel_ids=["durov"],
                cron_expression="0 9 * * *",
                timezone="UTC",
                format=DigestFormat.SUMMARY,
                language="ru",
                is_active=True,
                workspace_id=ws.id,
            )
        )
        await subscription_repo.create(
            DigestSubscription(
                id="",
                owner_id=owner.id,
                chat_id=43,
                name="no-ws",
                channel_ids=["durov"],
                cron_expression="0 9 * * *",
                timezone="UTC",
                format=DigestFormat.SUMMARY,
                language="ru",
                is_active=True,
            )
        )

        _override_user(app, _user(owner.id))
        response = await client.get("/api/v1/digests")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        by_name = {item["name"]: item for item in body["items"]}
        assert by_name["with-ws"]["workspace_id"] == ws.id
        assert by_name["with-ws"]["workspace_name"] == "EU reg"
        assert by_name["no-ws"]["workspace_id"] is None
        assert by_name["no-ws"]["workspace_name"] is None


@pg_only
class TestGetDigest:
    async def test_owner_gets_full_payload_without_workspace(
        self, app, client, user_repo, subscription_repo
    ):
        """Single GET for a row WITHOUT ``workspace_id`` returns a full
        :class:`DigestResponse` body with ``workspace_id=None`` and
        ``workspace_name=None``.

        Pairs with
        :meth:`TestCreateDigest.test_workspace_id_valid_attaches_fk_and_returns_workspace_name`
        which exercises the *with-workspace* branch; together they
        prove that ``_resolve_workspace_names`` returns the correct
        empty / populated dict and the renderer always emits the
        ``workspace_name`` field (Q-OPEN-3: never an absent key).
        Also covers the §A.GET happy-path slot — the workspace test
        bundles two contracts in one assertion, so this is the
        dedicated single-GET sanity check.
        """
        owner = await user_repo.create_user("alice_get_happy")
        stored = await subscription_repo.create(
            DigestSubscription(
                id="",
                owner_id=owner.id,
                chat_id=12345,
                name="Daily brief",
                channel_ids=["durov"],
                cron_expression="0 9 * * *",
                timezone="UTC",
                format=DigestFormat.BULLETS,
                language="en",
                is_active=True,
            )
        )
        _override_user(app, _user(owner.id))

        response = await client.get(f"/api/v1/digests/{stored.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == stored.id
        assert body["owner_id"] == owner.id
        assert body["name"] == "Daily brief"
        assert body["channel_ids"] == ["durov"]
        assert body["cron_expression"] == "0 9 * * *"
        assert body["timezone"] == "UTC"
        assert body["format"] == "bullets"
        assert body["language"] == "en"
        assert body["is_active"] is True
        assert body["workspace_id"] is None
        assert body["workspace_name"] is None

    async def test_foreign_subscription_returns_404_not_403(
        self, app, client, user_repo, subscription_repo
    ):
        alice = await user_repo.create_user("alice_get_foreign")
        bob = await user_repo.create_user("bob_get_foreign")

        bob_sub = await subscription_repo.create(
            DigestSubscription(
                id="",
                owner_id=bob.id,
                chat_id=42,
                name="bob-only",
                channel_ids=["durov"],
                cron_expression="0 9 * * *",
                timezone="UTC",
                format=DigestFormat.SUMMARY,
                language="ru",
                is_active=True,
            )
        )

        _override_user(app, _user(alice.id))
        response = await client.get(f"/api/v1/digests/{bob_sub.id}")

        assert response.status_code == 404, response.text
        body = response.json()
        assert body["error_class"] == "NotFound"

    async def test_unknown_uuid_returns_404(self, app, client, user_repo):
        """Well-formed but non-existent digest UUID → 404 ``NotFound``.

        Distinct from the foreign-ownership case (a row exists but
        belongs to someone else): here no row exists at all. Both
        collapse to ``error_class=NotFound`` so a caller cannot infer
        whether a UUID is "free" or "taken by another tenant".
        """
        owner = await user_repo.create_user("alice_get_unknown")
        _override_user(app, _user(owner.id))

        response = await client.get("/api/v1/digests/00000000-0000-0000-0000-000000000999")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"


@pg_only
class TestDeleteDigest:
    async def test_hard_delete_first_call_204_then_404(
        self, app, client, user_repo, subscription_repo
    ):
        """First DELETE on own row → 204; row hard-deleted (verify via
        follow-up GET → 404); second DELETE on the same id → **404**
        (REST-strict per parent Q-OPEN-8 lock; ASYMMETRIC vs the
        watchlist soft-delete 204+204 pattern).
        """
        owner = await user_repo.create_user("alice_delete_hard")
        stored = await subscription_repo.create(
            DigestSubscription(
                id="",
                owner_id=owner.id,
                chat_id=42,
                name="Daily brief",
                channel_ids=["durov"],
                cron_expression="0 9 * * *",
                timezone="UTC",
                format=DigestFormat.SUMMARY,
                language="ru",
                is_active=True,
            )
        )

        _override_user(app, _user(owner.id))
        first = await client.delete(f"/api/v1/digests/{stored.id}")
        assert first.status_code == 204, first.text
        assert first.content == b""  # 204 must be body-less.

        # Hard-delete: follow-up GET on the same id returns 404.
        get_resp = await client.get(f"/api/v1/digests/{stored.id}")
        assert get_resp.status_code == 404, get_resp.text
        assert get_resp.json()["error_class"] == "NotFound"

        # Second DELETE on the same id → 404 (HARD DELETE asymmetry).
        second = await client.delete(f"/api/v1/digests/{stored.id}")
        assert second.status_code == 404, second.text
        assert second.json()["error_class"] == "NotFound"

    async def test_foreign_subscription_returns_404(
        self, app, client, user_repo, subscription_repo
    ):
        alice = await user_repo.create_user("alice_delete_foreign")
        bob = await user_repo.create_user("bob_delete_foreign")

        bob_sub = await subscription_repo.create(
            DigestSubscription(
                id="",
                owner_id=bob.id,
                chat_id=42,
                name="bob-only",
                channel_ids=["durov"],
                cron_expression="0 9 * * *",
                timezone="UTC",
                format=DigestFormat.SUMMARY,
                language="ru",
                is_active=True,
            )
        )
        _override_user(app, _user(alice.id))
        response = await client.delete(f"/api/v1/digests/{bob_sub.id}")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"

    async def test_unknown_uuid_returns_404(self, app, client, user_repo):
        """DELETE on a never-existed UUID → 404 ``NotFound``.

        Distinct from :meth:`test_hard_delete_first_call_204_then_404`
        (which deletes an existing row and then re-DELETEs the now-gone
        id) and from :meth:`test_foreign_subscription_returns_404`
        (which targets a row owned by someone else). Here we send
        DELETE for a UUID that has never been written: the response
        must still be a 404 ``NotFound`` so a caller cannot tell
        "free UUID" apart from "another tenant's UUID".
        """
        owner = await user_repo.create_user("alice_delete_unknown")
        _override_user(app, _user(owner.id))

        response = await client.delete("/api/v1/digests/00000000-0000-0000-0000-000000000999")
        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "NotFound"
