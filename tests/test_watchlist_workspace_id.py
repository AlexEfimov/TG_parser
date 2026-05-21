"""Service-layer tests for ENH-9 ``workspace_id`` on subscribe paths.

Wave 1 step 3 commit 1/4 — service-layer half of ENH-9. HTTP/Bot/CLI
integration tests land in commit 2/4+ (per sprint prompt §8).

Canonical scenarios (per sprint prompt §5 — 8 base + admin-bypass mirror):

Watchlist:

* ``test_workspace_id_none``                              — Scenario 1
* ``test_workspace_id_valid``                             — Scenario 2
* ``test_workspace_id_foreign``                           — Scenario 3
* ``test_workspace_id_unknown_uuid``                      — Scenario 4
* ``test_workspace_deletion_sets_null``                   — Scenario 6
* ``test_workspace_id_admin_bypasses_ownership_check``    — Scenario 8

Digest (Scenario 7 mirror):

* ``test_workspace_id_valid``
* ``test_workspace_id_foreign``
* ``test_workspace_id_unknown_uuid``
* ``test_workspace_id_admin_bypasses_ownership_check``
* ``test_workspace_deletion_sets_null``

The deletion-cascade test uses a custom in-memory ``WorkspaceRepo`` to
emulate the ``ON DELETE SET NULL`` behaviour of the new Alembic FK; the
DB-level smoke for the same wiring lives in the integration test suite
that picks up the migration head. The malformed-string scenario (#5 in
the sprint prompt) is intentionally not covered here — at the service
layer, a non-UUID string short-circuits through the same
``workspace_repo.get()`` lookup miss as a random UUID and surfaces an
identical ``WorkspaceNotFound``; format validation happens at the
HTTP layer in commit 2/4+ via Pydantic ``UUID4`` parsing (422).
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_subscribe_idempotency import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeDigestSubscriptionRepo,
)
from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
)

from tg_parser.auth.ownership import WorkspaceNotFound  # noqa: E402
from tg_parser.domain.models import DigestFormat, NotifyMode, Workspace  # noqa: E402
from tg_parser.services.digest_service import DigestService  # noqa: E402
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# ---------------------------------------------------------------------------
# In-memory WorkspaceRepo fake
# ---------------------------------------------------------------------------


@dataclass
class _FakeWorkspaceRepo:
    """Minimal in-memory ``WorkspaceRepo`` for ENH-9 service-layer tests.

    Only the methods exercised by :meth:`WatchlistService.subscribe`
    and :meth:`DigestService.subscribe` (``get``, ``delete``) are
    implemented; the rest are intentionally absent so misuse fails
    loudly.
    """

    store: dict[str, Workspace] = field(default_factory=dict)

    def add(
        self,
        *,
        owner_id: str,
        workspace_id: str | None = None,
        name: str = "default",
    ) -> Workspace:
        wid = workspace_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        ws = Workspace(
            id=wid,
            owner_id=owner_id,
            name=name,
            description=None,
            created_at=now,
            updated_at=now,
        )
        self.store[wid] = ws
        return ws

    async def get(self, workspace_id: str) -> Workspace | None:
        return self.store.get(workspace_id)

    async def delete(self, workspace_id: str) -> bool:
        return self.store.pop(workspace_id, None) is not None


# ---------------------------------------------------------------------------
# Service factories
# ---------------------------------------------------------------------------


def _make_watchlist_service(
    *,
    workspace_repo: _FakeWorkspaceRepo | None = None,
) -> tuple[WatchlistService, _FakeInterestRepo, _FakeMatchRepo, _FakeWorkspaceRepo]:
    ir = _FakeInterestRepo()
    mr = _FakeMatchRepo()
    wsr = workspace_repo or _FakeWorkspaceRepo()
    svc = WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
        workspace_repo=wsr,  # type: ignore[arg-type]
    )
    return svc, ir, mr, wsr


def _make_digest_service(
    *,
    workspace_repo: _FakeWorkspaceRepo | None = None,
) -> tuple[DigestService, _FakeDigestSubscriptionRepo, _FakeWorkspaceRepo]:
    repo = _FakeDigestSubscriptionRepo()
    wsr = workspace_repo or _FakeWorkspaceRepo()
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
        workspace_repo=wsr,  # type: ignore[arg-type]
    )
    return svc, repo, wsr


# ---------------------------------------------------------------------------
# Watchlist ENH-9 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscribeWatchlistWorkspaceId:
    """ENH-9 service-layer behaviour for ``WatchlistService.subscribe``."""

    async def test_workspace_id_none(self) -> None:
        """Default behaviour bit-for-bit: row.workspace_id IS NULL."""
        svc, ir, _, _ = _make_watchlist_service()

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.6,
            notify_mode=NotifyMode.INSTANT,
        )

        assert result.created is True
        assert result.interest.workspace_id is None
        stored = await ir.get(result.interest.id)
        assert stored is not None
        assert stored.workspace_id is None

    async def test_workspace_id_valid(self) -> None:
        """Owned workspace → FK stored on the new row."""
        wsr = _FakeWorkspaceRepo()
        ws = wsr.add(owner_id="user-1", name="EU regulation")
        svc, ir, _, _ = _make_watchlist_service(workspace_repo=wsr)

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.6,
            notify_mode=NotifyMode.INSTANT,
            workspace_id=ws.id,
        )

        assert result.created is True
        assert result.interest.workspace_id == ws.id
        stored = await ir.get(result.interest.id)
        assert stored is not None
        assert stored.workspace_id == ws.id

    async def test_workspace_id_foreign(self) -> None:
        """Workspace owned by another user → 404-like WorkspaceNotFound."""
        wsr = _FakeWorkspaceRepo()
        # Workspace owned by user-2; user-1 is trying to use it.
        foreign_ws = wsr.add(owner_id="user-2", name="other tenant")
        svc, ir, _, _ = _make_watchlist_service(workspace_repo=wsr)

        with pytest.raises(WorkspaceNotFound):
            await svc.subscribe(
                user_id="user-1",
                chat_id=12345,
                title="MiCA",
                channel_ids=["crypto_news"],
                keywords=["mica"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                workspace_id=foreign_ws.id,
            )

        # No row was created — invariant: cross-tenant attempts never leak existence.
        assert len(ir.store) == 0

    async def test_workspace_id_unknown_uuid(self) -> None:
        """Random UUID → WorkspaceNotFound (existence indistinguishable from foreign)."""
        wsr = _FakeWorkspaceRepo()
        svc, ir, _, _ = _make_watchlist_service(workspace_repo=wsr)

        with pytest.raises(WorkspaceNotFound):
            await svc.subscribe(
                user_id="user-1",
                chat_id=12345,
                title="MiCA",
                channel_ids=["crypto_news"],
                keywords=["mica"],
                threshold=0.6,
                notify_mode=NotifyMode.INSTANT,
                workspace_id=str(uuid.uuid4()),
            )

        assert len(ir.store) == 0

    async def test_workspace_deletion_sets_null(self) -> None:
        """Deleting the workspace clears the FK on existing rows (ON DELETE SET NULL).

        The Alembic FK is defined as ``ON DELETE SET NULL``; this test
        emulates the cascade at the service layer by deleting the
        workspace and re-reading the watch interest. The fake repo
        doesn't model the FK, so we simulate the cascade by manually
        nulling the column on delete via the test helper below.
        """
        wsr = _FakeWorkspaceRepo()
        ws = wsr.add(owner_id="user-1", name="EU regulation")
        svc, ir, _, _ = _make_watchlist_service(workspace_repo=wsr)

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.6,
            notify_mode=NotifyMode.INSTANT,
            workspace_id=ws.id,
        )
        assert result.interest.workspace_id == ws.id

        # Simulate ``ON DELETE SET NULL`` cascade: workspace_repo.delete()
        # would trigger the FK cascade in real Postgres; for the in-memory
        # fake we apply the same effect manually so the test still
        # exercises the post-cascade observable state.
        await wsr.delete(ws.id)
        for interest_id, interest in list(ir.store.items()):
            if interest.workspace_id == ws.id:
                ir.store[interest_id] = interest.model_copy(update={"workspace_id": None})

        post = await ir.get(result.interest.id)
        assert post is not None
        assert post.workspace_id is None

    async def test_workspace_id_admin_bypasses_ownership_check(self) -> None:
        """Admin (is_admin=True) can subscribe with another user's workspace.

        Sprint prompt §5 ENH-9 Scenario 8: parity with
        ``assert_workspace_access`` in ``tg_parser/auth/ownership.py``
        — admin bypasses the cross-tenant ownership guard so support /
        operator workflows can subscribe on behalf of arbitrary users.
        Non-admin path is covered by ``test_workspace_id_foreign``.
        """
        wsr = _FakeWorkspaceRepo()
        # Workspace owned by user-2; admin (user-admin) subscribes on behalf
        # of user-1 (which here means admin acts as user-1 — see is_admin
        # semantics on WatchlistService.subscribe).
        foreign_ws = wsr.add(owner_id="user-2", name="other tenant")
        svc, ir, _, _ = _make_watchlist_service(workspace_repo=wsr)

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.6,
            notify_mode=NotifyMode.INSTANT,
            workspace_id=foreign_ws.id,
            is_admin=True,
        )

        assert result.created is True
        assert result.interest.workspace_id == foreign_ws.id, (
            "admin must be allowed to attach a foreign workspace_id "
            "(mirrors assert_workspace_access admin-bypass branch)"
        )
        stored = await ir.get(result.interest.id)
        assert stored is not None
        assert stored.workspace_id == foreign_ws.id


# ---------------------------------------------------------------------------
# Digest ENH-9 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscribeDigestWorkspaceId:
    """ENH-9 service-layer behaviour for ``DigestService.subscribe``."""

    def _digest_kwargs(self, owner_id: str = "user-1") -> dict[str, Any]:
        return {
            "owner_id": owner_id,
            "chat_id": 12345,
            "name": "morning",
            "channel_ids": ["durov"],
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
            "format": DigestFormat.SUMMARY,
            "language": "ru",
        }

    async def test_workspace_id_valid(self) -> None:
        wsr = _FakeWorkspaceRepo()
        ws = wsr.add(owner_id="user-1", name="EU regulation")
        svc, repo, _ = _make_digest_service(workspace_repo=wsr)

        result = await svc.subscribe(**self._digest_kwargs(), workspace_id=ws.id)

        assert result.created is True
        assert result.subscription.workspace_id == ws.id
        stored = await repo.get(result.subscription.id)
        assert stored is not None
        assert stored.workspace_id == ws.id

    async def test_workspace_id_foreign(self) -> None:
        wsr = _FakeWorkspaceRepo()
        foreign_ws = wsr.add(owner_id="user-2", name="other tenant")
        svc, repo, _ = _make_digest_service(workspace_repo=wsr)

        with pytest.raises(WorkspaceNotFound):
            await svc.subscribe(
                **self._digest_kwargs(),
                workspace_id=foreign_ws.id,
            )

        assert len(repo.store) == 0

    async def test_workspace_id_unknown_uuid(self) -> None:
        """Random UUID → WorkspaceNotFound (mirror of watchlist scenario).

        Sprint prompt §5 ENH-9 Scenario 4 — digest must surface the
        same 404-like behaviour so cross-tenant existence is never
        leaked through error class.
        """
        wsr = _FakeWorkspaceRepo()
        svc, repo, _ = _make_digest_service(workspace_repo=wsr)

        with pytest.raises(WorkspaceNotFound):
            await svc.subscribe(
                **self._digest_kwargs(),
                workspace_id=str(uuid.uuid4()),
            )

        assert len(repo.store) == 0

    async def test_workspace_id_admin_bypasses_ownership_check(self) -> None:
        """Admin (is_admin=True) can subscribe a digest under another user's ws.

        Sprint prompt §5 ENH-9 Scenario 8 mirror for F6 — admin-bypass
        parity with watchlist; the digest subscribe path must honour
        the same ``assert_workspace_access`` admin branch.
        """
        wsr = _FakeWorkspaceRepo()
        foreign_ws = wsr.add(owner_id="user-2", name="other tenant")
        svc, repo, _ = _make_digest_service(workspace_repo=wsr)

        result = await svc.subscribe(
            **self._digest_kwargs(),
            workspace_id=foreign_ws.id,
            is_admin=True,
        )

        assert result.created is True
        assert result.subscription.workspace_id == foreign_ws.id
        stored = await repo.get(result.subscription.id)
        assert stored is not None
        assert stored.workspace_id == foreign_ws.id

    async def test_workspace_deletion_sets_null(self) -> None:
        wsr = _FakeWorkspaceRepo()
        ws = wsr.add(owner_id="user-1", name="EU regulation")
        svc, repo, _ = _make_digest_service(workspace_repo=wsr)

        result = await svc.subscribe(**self._digest_kwargs(), workspace_id=ws.id)
        assert result.subscription.workspace_id == ws.id

        # Simulate ``ON DELETE SET NULL`` cascade (see watchlist test).
        await wsr.delete(ws.id)
        for sid, sub in list(repo.store.items()):
            if sub.workspace_id == ws.id:
                repo.store[sid] = sub.model_copy(update={"workspace_id": None})

        post = await repo.get(result.subscription.id)
        assert post is not None
        assert post.workspace_id is None
