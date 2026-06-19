"""F11 CLI ``tg-parser watchlist {add,list,remove,matches}`` — pure-mock tests.

Uses Typer's ``CliRunner`` to invoke the registered subcommands. The DB
context, service factory, ``get_default_admin``, and ``Database`` singleton
are patched so the tests run without Postgres.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

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
from tg_parser.cli.watchlist_cmd import app as watchlist_app  # noqa: E402
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

runner = CliRunner()


def _admin(user_id: str = "admin-1") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


@asynccontextmanager
async def _fake_repos(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


def _patch_cli(
    svc: WatchlistService,
    ir: _FakeInterestRepo,
    mr: _FakeMatchRepo,
    *,
    user: CurrentUser,
):
    """Patch service factory + repo context + admin resolver + DB.close."""

    async def _fake_admin():
        return user

    async def _fake_close():
        return None

    return [
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _fake_repos(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            lambda **_kwargs: svc,
        ),
        patch("tg_parser.auth.resolvers.get_default_admin", _fake_admin),
        patch(
            "tg_parser.storage.sqlalchemy.database.Database.close_instance",
            classmethod(lambda cls: _fake_close()),
        ),
    ]


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


def _make_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestWatchlistAddCli:
    def test_creates_interest(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin("admin-1"))
        _enter_all(patches)
        try:
            result = runner.invoke(
                watchlist_app,
                [
                    "add",
                    "--title",
                    "MiCA crypto",
                    "--chat-id",
                    "999",
                    "--channels",
                    "@crypto_news,@eth_news",
                    "--keywords",
                    "mica,etf",
                    "--threshold",
                    "0.55",
                ],
            )
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        assert "создан" in result.stdout.lower() or "create" in result.stdout.lower()
        assert len(ir.store) == 1
        stored = next(iter(ir.store.values()))
        assert stored.title == "MiCA crypto"
        assert stored.chat_id == 999
        assert stored.channel_ids == ["crypto_news", "eth_news"]
        assert stored.keywords == ["mica", "etf"]
        assert stored.threshold == pytest.approx(0.55)
        assert stored.user_id == "admin-1"

    def test_rejects_invalid_threshold(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(
                watchlist_app,
                [
                    "add",
                    "--title",
                    "MiCA",
                    "--chat-id",
                    "1",
                    "--channels",
                    "@x",
                    "--threshold",
                    "1.5",
                ],
            )
        finally:
            _exit_all(patches)
        assert result.exit_code != 0
        combined = (result.stdout or "") + (getattr(result, "stderr", "") or "")
        assert "threshold" in combined.lower()
        assert len(ir.store) == 0

    def test_rejects_empty_channels(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(
                watchlist_app,
                [
                    "add",
                    "--title",
                    "MiCA",
                    "--chat-id",
                    "1",
                    "--channels",
                    "",
                ],
            )
        finally:
            _exit_all(patches)
        assert result.exit_code != 0
        combined = (result.stdout or "") + (getattr(result, "stderr", "") or "")
        assert "channels" in combined.lower() or "channel" in combined.lower()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestWatchlistListCli:
    def test_admin_lists_all(self):
        ir = _FakeInterestRepo()

        async def _seed():
            await ir.create(_make_interest(interest_id="a"))
            await ir.create(
                _make_interest(interest_id="b").model_copy(update={"user_id": "user-bob"})
            )

        import asyncio

        asyncio.run(_seed())
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_cli(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["list"])
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        assert "Watchlists" in result.stdout
        assert "a" in result.stdout
        assert "b" in result.stdout

    def test_empty_listing_warns(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["list"])
        finally:
            _exit_all(patches)
        assert result.exit_code == 0
        assert "не найдены" in result.stdout.lower() or "not" in result.stdout.lower()


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestWatchlistRemoveCli:
    def test_admin_can_delete(self):
        ir = _FakeInterestRepo()

        import asyncio

        asyncio.run(ir.create(_make_interest(interest_id="i-1")))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_cli(svc, ir, _FakeMatchRepo(), user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["remove", "i-1"])
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        stored = asyncio.run(ir.get("i-1"))
        assert stored is not None
        assert stored.is_active is False

    def test_unknown_id_exits_non_zero(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["remove", "ghost"])
        finally:
            _exit_all(patches)
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# matches
# ---------------------------------------------------------------------------


class TestWatchlistMatchesCli:
    def test_prints_matches_for_existing_interest(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()

        import asyncio

        async def _seed():
            await ir.create(_make_interest(interest_id="i-1"))
            await mr.upsert_many(
                [
                    _make_match(
                        interest_id="i-1",
                        source_ref="tg:c:post:1",
                        match_id=10,
                        channel_id="c",
                    ),
                    _make_match(
                        interest_id="i-1",
                        source_ref="tg:c:post:2",
                        match_id=11,
                        channel_id="c",
                    ),
                ]
            )

        asyncio.run(_seed())
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["matches", "i-1"])
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        assert "tg:c:post:1" in result.stdout
        assert "tg:c:post:2" in result.stdout
        assert "найдено: 2" in result.stdout.lower() or "2" in result.stdout

    def test_invalid_since_exits_non_zero(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()

        import asyncio

        asyncio.run(ir.create(_make_interest(interest_id="i-1")))
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["matches", "i-1", "--since", "not-a-date"])
        finally:
            _exit_all(patches)
        assert result.exit_code != 0

    def test_unknown_interest_exits_non_zero(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["matches", "ghost"])
        finally:
            _exit_all(patches)
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# backfill (ADR-0011 S3)
# ---------------------------------------------------------------------------


def _backfill_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo, docs: list) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo(docs),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


class TestWatchlistBackfillCli:
    def test_apply_without_confirmation_aborts_and_writes_nothing(self):
        # ADR-0011 Part C: --apply is gated; declining the prompt mutates nothing.
        import asyncio

        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        asyncio.run(ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.1)))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _backfill_service(ir, mr, [doc])
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["backfill", "i-1", "--apply"], input="n\n")
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        assert "отменено" in result.stdout.lower()
        assert len(mr.store) == 0

    def test_apply_with_yes_persists_silently(self):
        # ADR-0011: --apply --yes materializes matches with notified=True (silent).
        import asyncio

        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        asyncio.run(ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.1)))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _backfill_service(ir, mr, [doc])
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["backfill", "i-1", "--apply", "--yes"])
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        assert "примен" in result.stdout.lower()
        assert len(mr.store) == 1
        assert all(m.notified is True for m in mr.store.values())

    def test_dry_run_is_default_and_writes_nothing(self):
        import asyncio

        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        asyncio.run(ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.1)))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _backfill_service(ir, mr, [doc])
        patches = _patch_cli(svc, ir, mr, user=_admin())
        _enter_all(patches)
        try:
            result = runner.invoke(watchlist_app, ["backfill", "i-1"])
        finally:
            _exit_all(patches)
        assert result.exit_code == 0, result.stdout
        assert "dry-run" in result.stdout.lower()
        assert len(mr.store) == 0
