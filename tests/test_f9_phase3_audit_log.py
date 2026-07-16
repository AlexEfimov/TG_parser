"""F9 Phase 3 M2 — audit_log wiring + migration smoke."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tg_parser.api.main import create_app
from tg_parser.auth.audit import (
    ACTION_AUTH_API_KEY_REJECTED,
    ACTION_CHANNEL_ADD,
    ACTION_LLM_CONFIG_SET,
    OUTCOME_DENIED,
    OUTCOME_SUCCESS,
    record_audit_event,
)
from tg_parser.auth.models import CurrentUser

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

pytest_plugins = ("_testcontainer_fixtures",)

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_record_audit_event_swallows_insert_errors() -> None:
    """Auth-reject path must not change HTTP outcome if audit insert fails."""
    mock_repo = MagicMock()
    mock_repo.insert = AsyncMock(side_effect=RuntimeError("db down"))

    class _Ctx:
        async def __aenter__(self):
            return mock_repo, MagicMock()

        async def __aexit__(self, *args):
            return False

    with patch("tg_parser.services.db_context.audit_log_repo", return_value=_Ctx()):
        await record_audit_event(
            action=ACTION_AUTH_API_KEY_REJECTED,
            outcome=OUTCOME_DENIED,
            meta={"key_prefix": "abcd****"},
        )

    mock_repo.insert.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_auth_reject_records_audit_without_raw_secret() -> None:
    """Invalid X-API-Key → 403 and audit meta has key_prefix only."""
    app = create_app()
    transport = ASGITransport(app=app)
    raw_secret = "super-secret-api-key-value"
    recorded: list[dict] = []

    async def _capture(**kwargs):
        recorded.append(kwargs)

    with (
        patch("tg_parser.api.auth.settings") as mock_settings,
        patch("tg_parser.api.auth.resolve_user_by_auth", new_callable=AsyncMock) as mock_resolve,
        patch("tg_parser.auth.audit.record_audit_event", side_effect=_capture),
    ):
        mock_settings.api_key_required = True
        mock_settings.api_keys = {"valid-key": "tester"}
        mock_resolve.return_value = None
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/pipeline/trigger",
                headers={"X-API-Key": raw_secret},
                json={"channel_id": "ch1", "job": "full_pipeline"},
            )

    assert resp.status_code == 403
    assert recorded, "expected audit event"
    event = recorded[0]
    assert event["action"] == ACTION_AUTH_API_KEY_REJECTED
    assert event["outcome"] == OUTCOME_DENIED
    assert raw_secret not in str(event.get("meta"))
    assert event["meta"]["key_prefix"] == raw_secret[:4] + "****"


@pytest.mark.asyncio
async def test_api_auth_reject_still_403_when_audit_db_fails() -> None:
    """record_audit_event swallows DB errors; HTTP stays 403."""
    app = create_app()
    transport = ASGITransport(app=app)

    mock_repo = MagicMock()
    mock_repo.insert = AsyncMock(side_effect=RuntimeError("db down"))

    class _Ctx:
        async def __aenter__(self):
            return mock_repo, MagicMock()

        async def __aexit__(self, *args):
            return False

    with (
        patch("tg_parser.api.auth.settings") as mock_settings,
        patch("tg_parser.api.auth.resolve_user_by_auth", new_callable=AsyncMock) as mock_resolve,
        patch("tg_parser.services.db_context.audit_log_repo", return_value=_Ctx()),
    ):
        mock_settings.api_key_required = True
        mock_settings.api_keys = {"valid-key": "tester"}
        mock_resolve.return_value = None
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/pipeline/trigger",
                headers={"X-API-Key": "wrong-key-zzzz"},
                json={"channel_id": "ch1", "job": "full_pipeline"},
            )

    assert resp.status_code == 403
    mock_repo.insert.assert_awaited()


@pytest.mark.asyncio
async def test_llm_config_set_records_audit() -> None:
    from tg_parser.api.auth import resolve_current_user

    app = create_app()
    admin = CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )
    app.dependency_overrides[resolve_current_user] = lambda: admin
    recorded: list[dict] = []

    async def _capture(**kwargs):
        recorded.append(kwargs)

    with (
        patch("tg_parser.config.llm_config.set", return_value={"global": {}}),
        patch("tg_parser.auth.audit.record_audit_event", side_effect=_capture),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/llm/config",
                json={"scope": "global", "provider": "openai", "model": "gpt-4o-mini"},
            )

    assert resp.status_code == 200
    assert recorded
    assert recorded[0]["action"] == ACTION_LLM_CONFIG_SET
    assert recorded[0]["meta"]["provider"] == "openai"
    assert recorded[0]["meta"]["scope"] == "global"


@pytest.mark.asyncio
async def test_channel_add_records_audit() -> None:
    from tg_parser.bot.tools import _exec_add_channel

    user = CurrentUser(
        id="00000000-0000-0000-0000-000000000002",
        name="alice",
        role="user",
        allowed_channel_ids=[],
        max_channels=10,
    )
    recorded: list[dict] = []

    async def _capture(**kwargs):
        recorded.append(kwargs)

    mock_repo = MagicMock()
    mock_repo.list_sources = AsyncMock(return_value=[])
    mock_repo.upsert_source = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return mock_repo, MagicMock()

        async def __aexit__(self, *args):
            return False

    with (
        patch("tg_parser.bot.tools._resolve_source", new_callable=AsyncMock, return_value=None),
        patch("tg_parser.services.db_context.ingestion_state_repo", return_value=_Ctx()),
        patch("tg_parser.auth.ownership.check_channel_limit"),
        patch("tg_parser.auth.audit.audit_channel_event", side_effect=_capture),
    ):
        result = await _exec_add_channel(
            {"channel_id": "durov", "confirm": True},
            current_user=user,
        )

    assert result.get("created") is True
    assert recorded
    assert recorded[0]["action"] == ACTION_CHANNEL_ADD
    assert recorded[0]["channel_id"] == "durov"


@pg_only
@pytest.mark.asyncio
async def test_audit_log_insert_round_trip(test_db) -> None:
    from tg_parser.storage.sqlalchemy.audit_log_repo import SAAuditLogRepo

    session = test_db.ingestion_state_session()
    try:
        repo = SAAuditLogRepo(session)
        row_id = await repo.insert(
            action=ACTION_LLM_CONFIG_SET,
            outcome=OUTCOME_SUCCESS,
            actor_user_id=None,
            resource_type="llm_config",
            resource_id="global",
            meta={"scope": "global", "provider": "openai", "key_prefix": "abcd****"},
        )
        result = await session.execute(
            text("SELECT action, outcome, meta FROM audit_log WHERE id = :id"),
            {"id": str(row_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert row.action == ACTION_LLM_CONFIG_SET
        assert row.outcome == OUTCOME_SUCCESS
        assert "sk-" not in str(row.meta)
        assert row.meta["key_prefix"] == "abcd****"
    finally:
        await session.execute(text("DELETE FROM audit_log"))
        await session.commit()
        await session.close()


try:
    from _testcontainer_fixtures import (
        alembic_upgrade_for_branch,
        create_database,
        requires_testcontainers,
        sync_url_for_db,
    )
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    @requires_testcontainers
    def test_audit_log_migration_creates_table(pgvector_container) -> None:
        db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
        engine = create_engine(sync_url_for_db(pgvector_container, db))
        try:
            with engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log'")
                ).scalar()
                assert exists == 1
                conn.execute(
                    text(
                        "INSERT INTO audit_log (action, outcome, meta) "
                        "VALUES ('channel.add', 'success', '{\"channel_id\": \"x\"}'::jsonb)"
                    )
                )
                conn.commit()
        finally:
            engine.dispose()

    @requires_testcontainers
    def test_audit_log_migration_from_previous_head(pgvector_container) -> None:
        db = "alembic_audit_log_step"
        create_database(pgvector_container, db)
        cfg = Config(str(_REPO_ROOT / "migrations" / "alembic_ingestion.ini"))
        cfg.set_main_option(
            "sqlalchemy.url",
            sync_url_for_db(pgvector_container, db).replace(
                "postgresql://", "postgresql+asyncpg://", 1
            ),
        )
        cfg.set_main_option("db_name", "ingestion")
        command.upgrade(cfg, "b9c8d7e6f5a4")
        command.upgrade(cfg, "head")
        engine = create_engine(sync_url_for_db(pgvector_container, db))
        try:
            with engine.connect() as conn:
                assert (
                    conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log'"
                        )
                    ).scalar()
                    == 1
                )
        finally:
            engine.dispose()

except ImportError:
    pass
