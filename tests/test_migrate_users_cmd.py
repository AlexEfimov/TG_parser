"""
Regression tests for DI-11, DI-12, DI-13 — migrate-users / add-source cluster.

DI-11: migrate-users creates a SECOND admin user (alongside the one seeded
       by migration b2c3d4e5f6a7) because resolve_auth via api_key returns
       None on a fresh DB (no mappings yet).

DI-12: migrate-users silently skips mcp_token / telegram mappings while
       api_key mapping works. Direct call of repo.add_auth_mapping inside
       the same container succeeds — proves the bug is in the orchestration
       layer, not in the repository.

DI-13: add-source creates a Source with owner_id=NULL because the CLI
       command does not accept --owner-id and run_add_source does not
       resolve a default admin owner.

These tests run against a real PostgreSQL — DI-12 in particular is a
session-state interaction issue that mocks cannot reproduce.
"""

import os
from typing import Any

import pytest
from sqlalchemy import text

from tg_parser.config.settings import Settings
from tg_parser.storage.sqlalchemy import (
    Database,
    init_ingestion_state_schema,
)


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
async def clean_users_db():
    """
    Real PostgreSQL with users / user_auth_mappings / sources tables fresh.

    Truncates these tables on entry AND exit to avoid cross-test pollution.
    Also resets Database singleton — migrate_users_cmd uses Database.get_instance()
    which would otherwise pick up settings from a previous test/import.
    """
    Database.reset_instance()
    s = _test_settings()
    db = Database.get_instance(s)
    await db.init()

    await init_ingestion_state_schema(db.ingestion_state_engine)

    async with db.ingestion_state_engine.begin() as conn:
        # CASCADE handles user_auth_mappings + nullify FK in sources
        await conn.execute(text("TRUNCATE TABLE user_auth_mappings CASCADE"))
        await conn.execute(text("TRUNCATE TABLE users CASCADE"))
        await conn.execute(text("DELETE FROM sources WHERE source_id LIKE 'di_test_%'"))

    yield db

    async with db.ingestion_state_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE user_auth_mappings CASCADE"))
        await conn.execute(text("TRUNCATE TABLE users CASCADE"))
        await conn.execute(text("DELETE FROM sources WHERE source_id LIKE 'di_test_%'"))

    await db.close()
    Database.reset_instance()


def _patch_settings_credentials(monkeypatch, **overrides: Any) -> None:
    """
    Patch the global settings singleton used by migrate_users_cmd.

    migrate_users_cmd imports `from tg_parser.config import settings` —
    this is the global instance. We patch its attributes directly.
    """
    from tg_parser.config import settings

    defaults: dict[str, Any] = {
        "api_keys": {"test-api-key-12345": "test-api-client"},
        "mcp_auth_tokens": {"test-mcp-token-67890": "test-mcp-client"},
        "bot_allowed_users": "111111,222222",
    }
    defaults.update(overrides)

    monkeypatch.setattr(settings, "api_keys", defaults["api_keys"])
    monkeypatch.setattr(settings, "mcp_auth_tokens", defaults["mcp_auth_tokens"])
    monkeypatch.setattr(settings, "bot_allowed_users", defaults["bot_allowed_users"])


async def _count_mappings(db: Database, auth_type: str) -> int:
    async with db.ingestion_state_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM user_auth_mappings WHERE auth_type = :t"),
            {"t": auth_type},
        )
        return int(result.scalar() or 0)


async def _count_admins(db: Database) -> int:
    async with db.ingestion_state_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'"))
        return int(result.scalar() or 0)


# ============================================================================
# DI-12 root cause: silent JSON parse failure in settings layer
# ============================================================================


class TestSettingsJsonParseObservability:
    """DI-12 root cause regression: parse_json_dict/parse_json_list must NOT
    silently swallow JSON errors. Otherwise a malformed MCP_AUTH_TOKENS in
    .env makes mcp_auth_tokens={} and migrate-users maps nothing without any
    warning — exactly the symptom hit on the VPS during Dev Resurrection."""

    def test_parse_json_dict_logs_warning_on_malformed(self, monkeypatch):
        import importlib
        from unittest.mock import MagicMock

        settings_mod = importlib.import_module("tg_parser.config.settings")

        warn_spy = MagicMock()
        monkeypatch.setattr(settings_mod.logger, "warning", warn_spy)

        result = settings_mod.parse_json_dict('{"missing_quote: "value"}')

        assert result == {}, "must still return empty dict for backward compat"
        warn_spy.assert_called_once()
        event_arg = warn_spy.call_args.args[0]
        assert event_arg == "json_dict_parse_failed", (
            f"DI-12 root cause: expected json_dict_parse_failed warning, got: {warn_spy.call_args}"
        )

    def test_parse_json_dict_no_warning_on_valid(self, monkeypatch):
        import importlib
        from unittest.mock import MagicMock

        settings_mod = importlib.import_module("tg_parser.config.settings")

        warn_spy = MagicMock()
        monkeypatch.setattr(settings_mod.logger, "warning", warn_spy)

        result = settings_mod.parse_json_dict('{"key": "value"}')

        assert result == {"key": "value"}
        warn_spy.assert_not_called()

    def test_parse_json_dict_no_warning_on_none(self, monkeypatch):
        import importlib
        from unittest.mock import MagicMock

        settings_mod = importlib.import_module("tg_parser.config.settings")

        warn_spy = MagicMock()
        monkeypatch.setattr(settings_mod.logger, "warning", warn_spy)

        result = settings_mod.parse_json_dict(None)

        assert result == {}
        warn_spy.assert_not_called()


# ============================================================================
# DI-12: silent mapping failure for mcp_token and telegram
# ============================================================================


class TestMigrateUsersDI12:
    async def test_maps_all_credential_types(self, clean_users_db, monkeypatch):
        """DI-12 regression: mcp_token AND telegram must be mapped, not just api_key."""
        from tg_parser.cli.migrate_users_cmd import run_migrate_users

        _patch_settings_credentials(monkeypatch)

        stats = await run_migrate_users(dry_run=False)

        assert stats["api_keys_mapped"] == 1, (
            f"api_keys_mapped expected 1, got {stats['api_keys_mapped']}"
        )
        assert stats["mcp_tokens_mapped"] == 1, (
            f"DI-12: mcp_tokens_mapped expected 1, got {stats['mcp_tokens_mapped']}. "
            f"Full stats: {stats}"
        )
        assert stats["telegram_users_mapped"] == 2, (
            f"DI-12: telegram_users_mapped expected 2, got {stats['telegram_users_mapped']}. "
            f"Full stats: {stats}"
        )

        # Re-open DB for verification (run_migrate_users closes the singleton)
        Database.reset_instance()
        s = _test_settings()
        db_check = Database.get_instance(s)
        await db_check.init()
        try:
            assert await _count_mappings(db_check, "api_key") == 1
            assert await _count_mappings(db_check, "mcp_token") == 1
            assert await _count_mappings(db_check, "telegram") == 2
        finally:
            await db_check.close()
            Database.reset_instance()

    async def test_warns_when_settings_collections_empty(self, clean_users_db, monkeypatch, caplog):
        """DI-12 observability: empty settings must produce explicit WARN logs
        AND total_*_in_settings=0 in stats so the operator knows why mapped=0."""
        from tg_parser.cli.migrate_users_cmd import run_migrate_users

        _patch_settings_credentials(
            monkeypatch,
            api_keys={},
            mcp_auth_tokens={},
            bot_allowed_users="",
        )

        stats = await run_migrate_users(dry_run=False)

        assert stats["api_keys_in_settings"] == 0
        assert stats["mcp_tokens_in_settings"] == 0
        assert stats["telegram_users_in_settings"] == 0
        assert stats["api_keys_mapped"] == 0
        assert stats["mcp_tokens_mapped"] == 0
        assert stats["telegram_users_mapped"] == 0

        msgs = [r.getMessage() for r in caplog.records]
        assert any("migrate_users_no_api_keys_in_settings" in m for m in msgs)
        assert any("migrate_users_no_mcp_tokens_in_settings" in m for m in msgs)
        assert any("migrate_users_no_telegram_users_in_settings" in m for m in msgs)

    async def test_idempotent_second_run_skips_existing(self, clean_users_db, monkeypatch):
        """Running migrate-users twice must be a no-op for existing mappings."""
        from tg_parser.cli.migrate_users_cmd import run_migrate_users

        _patch_settings_credentials(monkeypatch)

        first = await run_migrate_users(dry_run=False)
        assert first["api_keys_mapped"] == 1
        assert first["mcp_tokens_mapped"] == 1
        assert first["telegram_users_mapped"] == 2

        second = await run_migrate_users(dry_run=False)
        assert second["api_keys_mapped"] == 0, "second run must not re-create api_key mapping"
        assert second["mcp_tokens_mapped"] == 0
        assert second["telegram_users_mapped"] == 0
        assert second["skipped_existing"] >= 4  # 1 api + 1 mcp + 2 telegram


# ============================================================================
# DI-11: duplicate admin user
# ============================================================================


class TestMigrateUsersDI11:
    async def test_does_not_create_duplicate_admin_when_seeded(self, clean_users_db, monkeypatch):
        """
        DI-11 regression: migration b2c3d4e5f6a7 seeds an admin user.
        migrate-users must REUSE that admin, not create a second one.
        """
        from tg_parser.cli.migrate_users_cmd import run_migrate_users

        # Simulate the seed done by migration b2c3d4e5f6a7
        async with clean_users_db.ingestion_state_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (name, role) "
                    "SELECT 'admin', 'admin' "
                    "WHERE NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin')"
                )
            )

        _patch_settings_credentials(monkeypatch)

        stats = await run_migrate_users(dry_run=False)

        # Re-open DB to verify
        Database.reset_instance()
        s = _test_settings()
        db_check = Database.get_instance(s)
        await db_check.init()
        try:
            admin_count = await _count_admins(db_check)
        finally:
            await db_check.close()
            Database.reset_instance()

        assert admin_count == 1, (
            f"DI-11: expected exactly 1 admin user after migrate-users on a "
            f"pre-seeded DB, got {admin_count}. Stats: {stats}"
        )
        assert stats["admin_created"] is False, (
            "DI-11: admin_created must be False when admin was reused from seed"
        )


# ============================================================================
# DI-13: add-source --owner-id
# ============================================================================


class TestAddSourceOwnership:
    async def test_add_source_assigns_admin_owner_by_default(self, clean_users_db, monkeypatch):
        """DI-13 regression: add-source without --owner-id must default to admin."""
        from tg_parser.cli.add_source_cmd import run_add_source

        # Pre-seed admin
        async with clean_users_db.ingestion_state_engine.begin() as conn:
            await conn.execute(text("INSERT INTO users (name, role) VALUES ('admin', 'admin')"))
            row = (
                await conn.execute(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
            ).fetchone()
            admin_id = str(row.id)

        await run_add_source(
            source_id="di_test_default_owner",
            channel_id="di_test_ch_default",
        )

        async with clean_users_db.ingestion_state_engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT owner_id FROM sources WHERE source_id = :sid"),
                    {"sid": "di_test_default_owner"},
                )
            ).fetchone()

        assert row is not None, "source not created"
        assert row.owner_id is not None, "DI-13: owner_id must be auto-assigned to admin, got NULL"
        assert str(row.owner_id) == admin_id, (
            f"DI-13: owner_id={row.owner_id} expected admin_id={admin_id}"
        )

    async def test_add_source_explicit_owner_id(self, clean_users_db, monkeypatch):
        """DI-13: explicit --owner-id wins over auto-resolved admin."""
        from tg_parser.cli.add_source_cmd import run_add_source

        async with clean_users_db.ingestion_state_engine.begin() as conn:
            await conn.execute(text("INSERT INTO users (name, role) VALUES ('admin', 'admin')"))
            await conn.execute(text("INSERT INTO users (name, role) VALUES ('alice', 'user')"))
            row = (await conn.execute(text("SELECT id FROM users WHERE name = 'alice'"))).fetchone()
            alice_id = str(row.id)

        await run_add_source(
            source_id="di_test_explicit_owner",
            channel_id="di_test_ch_explicit",
            owner_id=alice_id,
        )

        async with clean_users_db.ingestion_state_engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT owner_id FROM sources WHERE source_id = :sid"),
                    {"sid": "di_test_explicit_owner"},
                )
            ).fetchone()

        assert row is not None
        assert str(row.owner_id) == alice_id

    async def test_add_source_fails_loud_without_admin(self, clean_users_db, monkeypatch):
        """DI-13: if no admin exists and no --owner-id given, fail loudly."""
        from tg_parser.cli.add_source_cmd import run_add_source

        # No users in DB at all
        with pytest.raises(Exception) as exc_info:
            await run_add_source(
                source_id="di_test_no_admin",
                channel_id="di_test_ch_no_admin",
            )

        msg = str(exc_info.value).lower()
        assert "admin" in msg or "owner" in msg, (
            f"DI-13: error message should mention admin/owner, got: {exc_info.value}"
        )
