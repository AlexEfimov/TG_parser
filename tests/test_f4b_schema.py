"""F4-B Core — schema + migration smoke tests (Phase 1).

Verifies that the additive ``e9f0a1b2c3d5`` migration creates the
``workspaces`` and ``workspace_sources`` tables with all expected
constraints / indexes / FK semantics, and that the matching Pydantic
domain models enforce the same invariants on the application side.

Postgres-backed tests reuse the ``test_db`` fixture from ``conftest.py``
(alembic-managed schema, DI-19). They are gated by the same
``TEST_POSTGRES=1`` mechanism F6 / F11 tests use.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from tg_parser.domain.models import Workspace, WorkspaceSource

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ============================================================================
# Pure Pydantic — no DB
# ============================================================================


class TestWorkspacePydantic:
    def test_workspace_strips_whitespace_name(self) -> None:
        ws = Workspace(
            id=str(uuid.uuid4()),
            owner_id=str(uuid.uuid4()),
            name="  AI/ML research  ",
        )
        assert ws.name == "AI/ML research"

    def test_workspace_rejects_blank_name(self) -> None:
        with pytest.raises(ValueError):
            Workspace(
                id=str(uuid.uuid4()),
                owner_id=str(uuid.uuid4()),
                name="   ",
            )

    def test_workspace_rejects_overlong_name(self) -> None:
        with pytest.raises(ValueError):
            Workspace(
                id=str(uuid.uuid4()),
                owner_id=str(uuid.uuid4()),
                name="a" * 201,
            )

    def test_workspace_source_minimal(self) -> None:
        ws_id = str(uuid.uuid4())
        ws_source = WorkspaceSource(workspace_id=ws_id, source_id="tg:durov")
        assert ws_source.workspace_id == ws_id
        assert ws_source.source_id == "tg:durov"


# ============================================================================
# Schema constraints — Postgres
# ============================================================================


@pg_only
class TestWorkspacesSchema:
    async def test_workspaces_table_exists_with_indexes(self, test_db) -> None:
        async with test_db.ingestion_state_engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname='public' AND tablename='workspaces'"
                )
            )
            assert row.fetchone() is not None
            row = await conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname='public' AND tablename='workspaces' "
                    "ORDER BY indexname"
                )
            )
            idx_names = {r[0] for r in row.fetchall()}
            assert "idx_workspaces_owner_id" in idx_names
            assert "uq_workspaces_owner_name" in idx_names
            assert "workspaces_pkey" in idx_names

    async def test_workspace_sources_table_exists_with_composite_pk(self, test_db) -> None:
        async with test_db.ingestion_state_engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname='public' AND tablename='workspace_sources' "
                    "ORDER BY indexname"
                )
            )
            idx_names = {r[0] for r in row.fetchall()}
            assert "pk_workspace_sources" in idx_names
            assert "idx_workspace_sources_source_id" in idx_names

    async def test_workspaces_unique_owner_name(self, test_db) -> None:
        session = test_db.ingestion_state_session()
        try:
            owner_id = str(uuid.uuid4())
            await session.execute(
                text("INSERT INTO users(id, name, role) VALUES (:id, :name, 'user')"),
                {"id": owner_id, "name": "alice"},
            )
            await session.execute(
                text("INSERT INTO workspaces(owner_id, name) VALUES (:owner_id, :name)"),
                {"owner_id": owner_id, "name": "AI/ML"},
            )
            await session.commit()

            with pytest.raises(Exception):  # noqa: B017 - asyncpg integrity errors
                await session.execute(
                    text("INSERT INTO workspaces(owner_id, name) VALUES (:owner_id, :name)"),
                    {"owner_id": owner_id, "name": "AI/ML"},
                )
                await session.commit()
            await session.rollback()
        finally:
            await session.close()

    async def test_workspaces_name_nonempty_check(self, test_db) -> None:
        session = test_db.ingestion_state_session()
        try:
            owner_id = str(uuid.uuid4())
            await session.execute(
                text("INSERT INTO users(id, name, role) VALUES (:id, :name, 'user')"),
                {"id": owner_id, "name": "bob"},
            )
            await session.commit()

            with pytest.raises(Exception):  # noqa: B017
                await session.execute(
                    text("INSERT INTO workspaces(owner_id, name) VALUES (:owner_id, :name)"),
                    {"owner_id": owner_id, "name": "   "},
                )
                await session.commit()
            await session.rollback()
        finally:
            await session.close()

    async def test_workspace_sources_cascade_on_workspace_delete(self, test_db) -> None:
        session = test_db.ingestion_state_session()
        try:
            owner_id = str(uuid.uuid4())
            source_id = "tg:carol_test_chan"
            await session.execute(
                text("INSERT INTO users(id, name, role) VALUES (:id, :name, 'user')"),
                {"id": owner_id, "name": "carol"},
            )
            await session.execute(
                text(
                    "INSERT INTO sources(source_id, channel_id, status, include_comments, "
                    "fail_count, comments_unavailable, created_at, updated_at, owner_id) "
                    "VALUES (:sid, :sid, 'active', false, 0, false, "
                    "now()::text, now()::text, :owner)"
                ),
                {"sid": source_id, "owner": owner_id},
            )
            result = await session.execute(
                text(
                    "INSERT INTO workspaces(owner_id, name) VALUES (:owner_id, :name) RETURNING id"
                ),
                {"owner_id": owner_id, "name": "Workspace1"},
            )
            ws_id = str(result.fetchone()[0])
            await session.execute(
                text(
                    "INSERT INTO workspace_sources(workspace_id, source_id) "
                    "VALUES (:ws_id, :source_id)"
                ),
                {"ws_id": ws_id, "source_id": source_id},
            )
            await session.commit()

            cnt = await session.execute(
                text("SELECT COUNT(*) FROM workspace_sources WHERE workspace_id = :ws"),
                {"ws": ws_id},
            )
            assert cnt.scalar() == 1

            await session.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": ws_id})
            await session.commit()

            cnt = await session.execute(
                text("SELECT COUNT(*) FROM workspace_sources WHERE workspace_id = :ws"),
                {"ws": ws_id},
            )
            assert cnt.scalar() == 0
        finally:
            await session.close()

    async def test_workspace_sources_composite_pk_idempotent_insert(self, test_db) -> None:
        session = test_db.ingestion_state_session()
        try:
            owner_id = str(uuid.uuid4())
            source_id = "tg:idem_test_chan"
            await session.execute(
                text("INSERT INTO users(id, name, role) VALUES (:id, :name, 'user')"),
                {"id": owner_id, "name": "dora"},
            )
            await session.execute(
                text(
                    "INSERT INTO sources(source_id, channel_id, status, include_comments, "
                    "fail_count, comments_unavailable, created_at, updated_at, owner_id) "
                    "VALUES (:sid, :sid, 'active', false, 0, false, "
                    "now()::text, now()::text, :owner)"
                ),
                {"sid": source_id, "owner": owner_id},
            )
            result = await session.execute(
                text(
                    "INSERT INTO workspaces(owner_id, name) VALUES (:owner_id, :name) RETURNING id"
                ),
                {"owner_id": owner_id, "name": "Workspace_dora"},
            )
            ws_id = str(result.fetchone()[0])
            await session.execute(
                text(
                    "INSERT INTO workspace_sources(workspace_id, source_id) "
                    "VALUES (:ws_id, :source_id) ON CONFLICT DO NOTHING"
                ),
                {"ws_id": ws_id, "source_id": source_id},
            )
            await session.execute(
                text(
                    "INSERT INTO workspace_sources(workspace_id, source_id) "
                    "VALUES (:ws_id, :source_id) ON CONFLICT DO NOTHING"
                ),
                {"ws_id": ws_id, "source_id": source_id},
            )
            await session.commit()
            cnt = await session.execute(
                text("SELECT COUNT(*) FROM workspace_sources WHERE workspace_id = :ws"),
                {"ws": ws_id},
            )
            assert cnt.scalar() == 1
        finally:
            await session.close()
