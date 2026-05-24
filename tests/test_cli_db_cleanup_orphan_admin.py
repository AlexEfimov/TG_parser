"""
Tests for `tg-parser db cleanup-orphan-admin` (DI-19, follow-up to DI-11/§3).

Covers `tg_parser/cli/cleanup_orphan_admin_cmd.py::run_cleanup_orphan_admin`
plus the typer wrapper in `tg_parser/cli/db_cmd.py::cleanup_orphan_admin`.

Real PostgreSQL is required (same fixture pattern as
`tests/test_migrate_users_cmd.py`): the cleanup logic depends on FK
behaviour (`user_auth_mappings.user_id` CASCADE, `sources.owner_id`
RESTRICT, `digest_subscriptions.owner_id` CASCADE) which mocks cannot
faithfully reproduce.
"""

import os

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from tg_parser.cli.cleanup_orphan_admin_cmd import (
    OrphanAdminCleanupError,
    run_cleanup_orphan_admin,
)
from tg_parser.cli.db_cmd import app as db_app
from tg_parser.config.settings import Settings
from tg_parser.storage.sqlalchemy import Database

# Click 8.2+ CliRunner separates stdout/stderr by default; use result.stderr
# to assert on typer.echo(..., err=True) messages and result.stdout for the
# normal status output.
runner = CliRunner()


def _test_settings() -> Settings:
    return Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=os.environ.get("DB_NAME", "tg_parser_test"),
        db_user=os.environ.get("DB_USER", "tg_parser_user"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_pool_size=2,
        db_max_overflow=3,
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
        openai_api_key="sk-test-key",
    )


@pytest.fixture
async def clean_users_db(_alembic_initialized_test_db):
    """Real PostgreSQL with users / mappings / sources / digests fresh.

    Mirrors the fixture from test_migrate_users_cmd.py — full reset on
    entry and exit, plus Database singleton reset.

    DI-19 (Sprint A.7): schema is alembic-managed via the session-scoped
    ``_alembic_initialized_test_db`` fixture in conftest.py.
    """
    Database.reset_instance()
    s = _test_settings()
    db = Database.get_instance(s)
    await db.init()

    async with db.ingestion_state_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE digest_subscriptions CASCADE"))
        await conn.execute(text("TRUNCATE TABLE user_auth_mappings CASCADE"))
        await conn.execute(text("DELETE FROM sources WHERE source_id LIKE 'cleanup_test_%'"))
        await conn.execute(text("TRUNCATE TABLE users CASCADE"))

    yield db

    async with db.ingestion_state_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE digest_subscriptions CASCADE"))
        await conn.execute(text("TRUNCATE TABLE user_auth_mappings CASCADE"))
        await conn.execute(text("DELETE FROM sources WHERE source_id LIKE 'cleanup_test_%'"))
        await conn.execute(text("TRUNCATE TABLE users CASCADE"))

    await db.close()
    Database.reset_instance()


async def _seed_admin(db: Database, name: str) -> str:
    """Insert a fresh admin user, return its UUID."""
    async with db.ingestion_state_engine.begin() as conn:
        row = (
            await conn.execute(
                text("INSERT INTO users (name, role) VALUES (:name, 'admin') RETURNING id"),
                {"name": name},
            )
        ).fetchone()
    return str(row.id)


async def _seed_user(db: Database, name: str, role: str = "user") -> str:
    async with db.ingestion_state_engine.begin() as conn:
        row = (
            await conn.execute(
                text("INSERT INTO users (name, role) VALUES (:name, :role) RETURNING id"),
                {"name": name, "role": role},
            )
        ).fetchone()
    return str(row.id)


async def _insert_source(db: Database, source_id: str, channel_id: str, owner_id: str) -> None:
    """Insert a minimal valid sources row (status / include_comments / timestamps NOT NULL)."""
    async with db.ingestion_state_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO sources ("
                "source_id, channel_id, status, include_comments, "
                "fail_count, comments_unavailable, created_at, updated_at, owner_id"
                ") VALUES ("
                ":source_id, :channel_id, 'active', false, "
                "0, false, NOW()::text, NOW()::text, :owner_id"
                ")"
            ),
            {"source_id": source_id, "channel_id": channel_id, "owner_id": owner_id},
        )


async def _user_exists(db: Database, user_id: str) -> bool:
    async with db.ingestion_state_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT 1 FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).fetchone()
    return row is not None


# ============================================================================
# Pure-Python (CliRunner-only) tests — UUID validation, no DB needed
# ============================================================================


class TestUuidValidation:
    """Invalid UUIDs are caught BEFORE any DB connection."""

    def test_invalid_uuid_format_via_cli(self):
        result = runner.invoke(
            db_app,
            ["cleanup-orphan-admin", "--orphan-uuid", "not-a-uuid", "--yes"],
        )
        assert result.exit_code == 1
        assert "Invalid UUID format" in result.stderr, (
            f"expected UUID validation error on stderr, got: stderr={result.stderr!r}, "
            f"stdout={result.stdout!r}"
        )


# ============================================================================
# Happy path
# ============================================================================


class TestHappyPath:
    async def test_orphan_with_no_fk_is_deleted(self, clean_users_db):
        keeper_id = await _seed_admin(clean_users_db, "keeper")
        orphan_id = await _seed_admin(clean_users_db, "orphan")

        result = await run_cleanup_orphan_admin(orphan_id, dry_run=False)

        assert result.deleted is True
        assert result.dry_run is False
        assert result.fk_report.is_clean
        assert result.admins_before == 2
        assert result.admins_after == 1
        assert result.user_name == "orphan"

        # Re-open singleton to verify (run_cleanup_orphan_admin closes it).
        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, orphan_id) is False
            assert await _user_exists(db_check, keeper_id) is True
        finally:
            await db_check.close()
            Database.reset_instance()


# ============================================================================
# Reject paths — FK present
# ============================================================================


class TestRejectsWhenFKPresent:
    async def test_reject_when_user_auth_mappings_present(self, clean_users_db):
        await _seed_admin(clean_users_db, "keeper")
        orphan_id = await _seed_admin(clean_users_db, "orphan")

        async with clean_users_db.ingestion_state_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO user_auth_mappings (user_id, auth_type, auth_identifier) "
                    "VALUES (:uid, 'api_key', 'cleanup_test_hash')"
                ),
                {"uid": orphan_id},
            )

        with pytest.raises(OrphanAdminCleanupError) as exc_info:
            await run_cleanup_orphan_admin(orphan_id, dry_run=False)

        msg = str(exc_info.value)
        assert "user_auth_mappings=1" in msg, (
            f"expected user_auth_mappings count in error, got: {msg!r}"
        )
        assert "NOT orphan" in msg

        # Re-open to verify orphan still exists (no DELETE happened).
        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, orphan_id) is True
        finally:
            await db_check.close()
            Database.reset_instance()

    async def test_reject_when_sources_owner_present(self, clean_users_db):
        await _seed_admin(clean_users_db, "keeper")
        orphan_id = await _seed_admin(clean_users_db, "orphan")

        await _insert_source(clean_users_db, "cleanup_test_src", "cleanup_test_ch", orphan_id)

        with pytest.raises(OrphanAdminCleanupError) as exc_info:
            await run_cleanup_orphan_admin(orphan_id, dry_run=False)

        msg = str(exc_info.value)
        assert "sources=1" in msg
        assert "UPDATE sources" in msg, (
            f"expected manual-SQL hint with UPDATE sources, got: {msg!r}"
        )

        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, orphan_id) is True
        finally:
            await db_check.close()
            Database.reset_instance()

    async def test_reject_when_digest_subscriptions_present(self, clean_users_db):
        await _seed_admin(clean_users_db, "keeper")
        orphan_id = await _seed_admin(clean_users_db, "orphan")

        async with clean_users_db.ingestion_state_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO digest_subscriptions "
                    "(owner_id, target_kind, chat_id, name, channel_ids, cron_expression) "
                    "VALUES (:uid, 'chat', 100, 'test_sub', ARRAY['cleanup_test_ch'], '0 9 * * *')"
                ),
                {"uid": orphan_id},
            )

        with pytest.raises(OrphanAdminCleanupError) as exc_info:
            await run_cleanup_orphan_admin(orphan_id, dry_run=False)

        msg = str(exc_info.value)
        assert "digest_subscriptions=1" in msg

        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, orphan_id) is True
        finally:
            await db_check.close()
            Database.reset_instance()


# ============================================================================
# Safety invariants
# ============================================================================


class TestSafetyInvariants:
    async def test_refuses_to_delete_last_admin(self, clean_users_db):
        # Only ONE admin in DB
        only_admin_id = await _seed_admin(clean_users_db, "only_admin")

        with pytest.raises(OrphanAdminCleanupError) as exc_info:
            await run_cleanup_orphan_admin(only_admin_id, dry_run=False)

        msg = str(exc_info.value)
        assert "last admin" in msg.lower(), f"expected 'last admin' guard, got: {msg!r}"

        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, only_admin_id) is True
        finally:
            await db_check.close()
            Database.reset_instance()

    async def test_rejects_non_admin_user(self, clean_users_db):
        await _seed_admin(clean_users_db, "keeper")
        regular_id = await _seed_user(clean_users_db, "alice", role="user")

        with pytest.raises(OrphanAdminCleanupError) as exc_info:
            await run_cleanup_orphan_admin(regular_id, dry_run=False)

        msg = str(exc_info.value)
        assert "not 'admin'" in msg or "role=" in msg

        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, regular_id) is True
        finally:
            await db_check.close()
            Database.reset_instance()

    async def test_user_not_found(self, clean_users_db):
        # Seed at least one admin so the "last admin" guard doesn't fire.
        await _seed_admin(clean_users_db, "keeper")

        # Random valid UUID that doesn't exist.
        missing_uuid = "00000000-0000-0000-0000-000000000001"

        with pytest.raises(OrphanAdminCleanupError) as exc_info:
            await run_cleanup_orphan_admin(missing_uuid, dry_run=False)

        msg = str(exc_info.value)
        assert "not found" in msg.lower()


# ============================================================================
# --dry-run
# ============================================================================


class TestDryRun:
    async def test_dry_run_returns_clean_report_without_delete(self, clean_users_db):
        await _seed_admin(clean_users_db, "keeper")
        orphan_id = await _seed_admin(clean_users_db, "orphan")

        result = await run_cleanup_orphan_admin(orphan_id, dry_run=True)

        assert result.dry_run is True
        assert result.deleted is False
        assert result.fk_report.is_clean
        assert result.admins_before == 2
        assert result.admins_after == 2  # unchanged

        Database.reset_instance()
        db_check = Database.get_instance(_test_settings())
        await db_check.init()
        try:
            assert await _user_exists(db_check, orphan_id) is True, (
                "dry-run must NOT delete the orphan"
            )
        finally:
            await db_check.close()
            Database.reset_instance()


# ============================================================================
# Typer wrapper — --yes bypasses typer.confirm; --dry-run flag wired
#
# These are sync CliRunner tests with `run_cleanup_orphan_admin` mocked.
# Asserting on the live DB inside an async test method clashes with
# `asyncio.run(...)` in the typer wrapper (no nested event loops in
# pytest-asyncio AUTO mode). The behavioural coverage that needs the
# live DB is in the async classes above.
# ============================================================================


class TestTyperWrapperFlags:
    def test_cli_yes_skips_confirm_and_invokes_business_logic(self):
        from tg_parser.cli.cleanup_orphan_admin_cmd import CleanupResult, FKReport

        valid_uuid = "11111111-2222-3333-4444-555555555555"
        fake_result = CleanupResult(
            orphan_uuid=valid_uuid,
            deleted=True,
            dry_run=False,
            fk_report=FKReport(0, 0, 0),
            admins_before=2,
            admins_after=1,
            user_name="orphan",
        )

        from unittest.mock import AsyncMock, patch

        with patch(
            "tg_parser.cli.cleanup_orphan_admin_cmd.run_cleanup_orphan_admin",
            new=AsyncMock(return_value=fake_result),
        ) as mock_fn:
            # Empty stdin proves --yes really bypasses typer.confirm
            # (otherwise CliRunner would raise EOFError on the prompt).
            result = runner.invoke(
                db_app,
                ["cleanup-orphan-admin", "--orphan-uuid", valid_uuid, "--yes"],
                input="",
            )

        assert result.exit_code == 0, (
            f"--yes CLI should exit 0, got {result.exit_code}. "
            f"stdout={result.stdout!r}, exception={result.exception!r}"
        )
        mock_fn.assert_awaited_once_with(valid_uuid, dry_run=False)
        assert "удалён" in result.stdout

    def test_cli_dry_run_passes_flag_through_and_does_not_prompt(self):
        from tg_parser.cli.cleanup_orphan_admin_cmd import CleanupResult, FKReport

        valid_uuid = "11111111-2222-3333-4444-555555555555"
        fake_result = CleanupResult(
            orphan_uuid=valid_uuid,
            deleted=False,
            dry_run=True,
            fk_report=FKReport(0, 0, 0),
            admins_before=2,
            admins_after=2,
            user_name="orphan",
        )

        from unittest.mock import AsyncMock, patch

        with patch(
            "tg_parser.cli.cleanup_orphan_admin_cmd.run_cleanup_orphan_admin",
            new=AsyncMock(return_value=fake_result),
        ) as mock_fn:
            # Empty stdin: --dry-run must skip the confirm prompt too
            # (no DELETE → no point asking).
            result = runner.invoke(
                db_app,
                ["cleanup-orphan-admin", "--orphan-uuid", valid_uuid, "--dry-run"],
                input="",
            )

        assert result.exit_code == 0, (
            f"--dry-run CLI should exit 0, got {result.exit_code}. "
            f"stdout={result.stdout!r}, exception={result.exception!r}"
        )
        mock_fn.assert_awaited_once_with(valid_uuid, dry_run=True)
        assert "Dry-run OK" in result.stdout

    def test_cli_default_prompts_and_aborts_on_no(self):
        from unittest.mock import AsyncMock, patch

        valid_uuid = "11111111-2222-3333-4444-555555555555"

        with patch(
            "tg_parser.cli.cleanup_orphan_admin_cmd.run_cleanup_orphan_admin",
            new=AsyncMock(),
        ) as mock_fn:
            result = runner.invoke(
                db_app,
                ["cleanup-orphan-admin", "--orphan-uuid", valid_uuid],
                input="n\n",
            )

        assert result.exit_code == 0
        assert "Отменено" in result.stdout
        assert not mock_fn.await_count, (
            "business logic must NOT run when user declines confirmation"
        )
