"""F4-B Core — :class:`SAWorkspaceRepo` CRUD + idempotency suite (Phase 2)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


@pytest.fixture
async def workspace_repo(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield SAWorkspaceRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def user_repo_for_ws(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


async def _create_source(test_db, source_id: str, channel_id: str, owner_id: str) -> None:
    """Insert a row into ``sources`` for FK-aware workspace_sources tests."""
    session = test_db.ingestion_state_session()
    try:
        from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo

        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=source_id,
                channel_id=channel_id,
                status="active",
                include_comments=False,
                fail_count=0,
                comments_unavailable=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                owner_id=owner_id,
            )
        )
    finally:
        await session.close()


@pg_only
class TestSAWorkspaceRepoCRUD:
    async def test_create_returns_workspace_with_server_defaults(
        self, workspace_repo, user_repo_for_ws
    ):
        owner = await user_repo_for_ws.create_user("alice")
        ws = await workspace_repo.create(
            owner_id=owner.id,
            name="AI/ML",
            description="Anthropic + OpenAI",
        )
        assert ws.id
        assert ws.owner_id == owner.id
        assert ws.name == "AI/ML"
        assert ws.description == "Anthropic + OpenAI"
        assert ws.created_at is not None
        assert ws.updated_at is not None

    async def test_get_returns_none_for_unknown(self, workspace_repo):
        result = await workspace_repo.get(str(uuid.uuid4()))
        assert result is None

    async def test_unique_owner_name_blocks_duplicate(self, workspace_repo, user_repo_for_ws):
        owner = await user_repo_for_ws.create_user("alice2")
        await workspace_repo.create(owner_id=owner.id, name="dup")
        with pytest.raises(Exception):  # noqa: B017
            await workspace_repo.create(owner_id=owner.id, name="dup")

    async def test_two_users_can_share_workspace_name(self, workspace_repo, user_repo_for_ws):
        alice = await user_repo_for_ws.create_user("alice_share")
        bob = await user_repo_for_ws.create_user("bob_share")
        await workspace_repo.create(owner_id=alice.id, name="AI/ML")
        await workspace_repo.create(owner_id=bob.id, name="AI/ML")
        alice_ws = await workspace_repo.list_by_owner(alice.id)
        bob_ws = await workspace_repo.list_by_owner(bob.id)
        assert len(alice_ws) == 1
        assert len(bob_ws) == 1

    async def test_list_by_owner_filters_foreign_workspaces(self, workspace_repo, user_repo_for_ws):
        alice = await user_repo_for_ws.create_user("alice_filter")
        bob = await user_repo_for_ws.create_user("bob_filter")
        await workspace_repo.create(owner_id=alice.id, name="alice_ws_1")
        await workspace_repo.create(owner_id=alice.id, name="alice_ws_2")
        await workspace_repo.create(owner_id=bob.id, name="bob_ws")
        alice_ws = await workspace_repo.list_by_owner(alice.id)
        assert {ws.name for ws in alice_ws} == {"alice_ws_1", "alice_ws_2"}

    async def test_list_all_admin_returns_every_workspace(self, workspace_repo, user_repo_for_ws):
        alice = await user_repo_for_ws.create_user("alice_all")
        bob = await user_repo_for_ws.create_user("bob_all")
        await workspace_repo.create(owner_id=alice.id, name="a")
        await workspace_repo.create(owner_id=bob.id, name="b")
        all_ws = await workspace_repo.list_all()
        assert len(all_ws) >= 2

    async def test_list_all_with_owner_filter(self, workspace_repo, user_repo_for_ws):
        alice = await user_repo_for_ws.create_user("alice_lo")
        bob = await user_repo_for_ws.create_user("bob_lo")
        await workspace_repo.create(owner_id=alice.id, name="a1")
        await workspace_repo.create(owner_id=alice.id, name="a2")
        await workspace_repo.create(owner_id=bob.id, name="b1")
        alice_only = await workspace_repo.list_all(owner_id=alice.id)
        assert {ws.name for ws in alice_only} == {"a1", "a2"}

    async def test_rename_returns_updated_row(self, workspace_repo, user_repo_for_ws):
        owner = await user_repo_for_ws.create_user("alice_rn")
        ws = await workspace_repo.create(owner_id=owner.id, name="old_name")
        renamed = await workspace_repo.rename(ws.id, "new_name")
        assert renamed is not None
        assert renamed.id == ws.id
        assert renamed.name == "new_name"

    async def test_rename_unknown_returns_none(self, workspace_repo):
        result = await workspace_repo.rename(str(uuid.uuid4()), "whatever")
        assert result is None

    async def test_delete_returns_true_if_existed(self, workspace_repo, user_repo_for_ws):
        owner = await user_repo_for_ws.create_user("alice_del")
        ws = await workspace_repo.create(owner_id=owner.id, name="trash")
        existed = await workspace_repo.delete(ws.id)
        assert existed is True
        existed_again = await workspace_repo.delete(ws.id)
        assert existed_again is False


@pg_only
class TestSAWorkspaceRepoMembership:
    async def test_add_source_idempotent_returns_false_on_duplicate(
        self, workspace_repo, user_repo_for_ws, test_db
    ):
        owner = await user_repo_for_ws.create_user("alice_add")
        ws = await workspace_repo.create(owner_id=owner.id, name="add_ws")
        await _create_source(test_db, "tg:src_add_1", "ch_add_1", owner.id)
        inserted = await workspace_repo.add_source(ws.id, "tg:src_add_1")
        assert inserted is True
        again = await workspace_repo.add_source(ws.id, "tg:src_add_1")
        assert again is False

    async def test_remove_source_returns_true_if_existed(
        self, workspace_repo, user_repo_for_ws, test_db
    ):
        owner = await user_repo_for_ws.create_user("alice_rm")
        ws = await workspace_repo.create(owner_id=owner.id, name="rm_ws")
        await _create_source(test_db, "tg:src_rm_1", "ch_rm_1", owner.id)
        await workspace_repo.add_source(ws.id, "tg:src_rm_1")
        removed = await workspace_repo.remove_source(ws.id, "tg:src_rm_1")
        assert removed is True
        again = await workspace_repo.remove_source(ws.id, "tg:src_rm_1")
        assert again is False

    async def test_list_source_ids_returns_sorted_set(
        self, workspace_repo, user_repo_for_ws, test_db
    ):
        owner = await user_repo_for_ws.create_user("alice_ls")
        ws = await workspace_repo.create(owner_id=owner.id, name="ls_ws")
        await _create_source(test_db, "tg:b_src", "chB", owner.id)
        await _create_source(test_db, "tg:a_src", "chA", owner.id)
        await workspace_repo.add_source(ws.id, "tg:b_src")
        await workspace_repo.add_source(ws.id, "tg:a_src")
        sources = await workspace_repo.list_source_ids(ws.id)
        assert sources == ["tg:a_src", "tg:b_src"]

    async def test_list_channel_ids_joins_sources_and_skips_soft_deleted(
        self, workspace_repo, user_repo_for_ws, test_db
    ):
        owner = await user_repo_for_ws.create_user("alice_ch")
        ws = await workspace_repo.create(owner_id=owner.id, name="ch_ws")
        await _create_source(test_db, "tg:src_active", "ch_active", owner.id)
        await _create_source(test_db, "tg:src_dead", "ch_dead", owner.id)
        await workspace_repo.add_source(ws.id, "tg:src_active")
        await workspace_repo.add_source(ws.id, "tg:src_dead")

        session = test_db.ingestion_state_session()
        try:
            await session.execute(
                text("UPDATE sources SET deleted_at = NOW() WHERE source_id = :sid"),
                {"sid": "tg:src_dead"},
            )
            await session.commit()
        finally:
            await session.close()

        channels = await workspace_repo.list_channel_ids(ws.id)
        assert channels == ["ch_active"]

    async def test_same_source_in_multiple_workspaces_of_one_owner(
        self, workspace_repo, user_repo_for_ws, test_db
    ):
        """Q5 = A: M2M shared inside one owner."""
        owner = await user_repo_for_ws.create_user("alice_q5")
        ws_a = await workspace_repo.create(owner_id=owner.id, name="AI")
        ws_b = await workspace_repo.create(owner_id=owner.id, name="Product")
        await _create_source(test_db, "tg:src_shared", "ch_shared", owner.id)
        await workspace_repo.add_source(ws_a.id, "tg:src_shared")
        await workspace_repo.add_source(ws_b.id, "tg:src_shared")
        assert await workspace_repo.list_source_ids(ws_a.id) == ["tg:src_shared"]
        assert await workspace_repo.list_source_ids(ws_b.id) == ["tg:src_shared"]
