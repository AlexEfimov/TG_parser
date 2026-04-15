"""
Tests for F4 Multi-Tenancy Phase 1: User model + UserRepo CRUD.

Requires PostgreSQL (TEST_POSTGRES=1).
"""

import hashlib
import os

import pytest

from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.ports import Source

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


@pytest.fixture(autouse=True)
async def _cleanup_f4_tables(test_db):
    """Truncate F4 tables before each test to avoid stale data conflicts."""
    session = test_db.ingestion_state_session()
    try:
        from sqlalchemy import text
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    yield


@pytest.fixture
async def user_repo(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def state_repo(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield SAIngestionStateRepo(session)
    finally:
        await session.close()


class TestUserCRUD:
    async def test_create_user(self, user_repo):
        user = await user_repo.create_user("alice", role="user", max_channels=5)
        assert user.name == "alice"
        assert user.role == "user"
        assert user.max_channels == 5
        assert user.id

    async def test_get_by_id(self, user_repo):
        user = await user_repo.create_user("bob")
        fetched = await user_repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.name == "bob"

    async def test_get_by_id_not_found(self, user_repo):
        result = await user_repo.get_by_id("00000000-0000-0000-0000-000000000000")
        assert result is None

    async def test_list_users(self, user_repo):
        await user_repo.create_user("charlie")
        await user_repo.create_user("diana")
        users = await user_repo.list_users()
        names = {u.name for u in users}
        assert "charlie" in names
        assert "diana" in names

    async def test_update_user(self, user_repo):
        user = await user_repo.create_user("eve")
        updated = await user_repo.update_user(user.id, name="eve_updated", role="admin")
        assert updated is not None
        assert updated.name == "eve_updated"
        assert updated.role == "admin"

    async def test_update_user_max_channels_to_none(self, user_repo):
        user = await user_repo.create_user("frank", max_channels=10)
        updated = await user_repo.update_user(user.id, max_channels=None)
        assert updated is not None
        assert updated.max_channels is None

    async def test_delete_user(self, user_repo):
        user = await user_repo.create_user("grace")
        assert await user_repo.delete_user(user.id) is True
        assert await user_repo.get_by_id(user.id) is None

    async def test_delete_user_not_found(self, user_repo):
        assert await user_repo.delete_user("00000000-0000-0000-0000-000000000000") is False

    async def test_create_admin(self, user_repo):
        admin = await user_repo.create_user("super_admin", role="admin")
        assert admin.role == "admin"
        assert admin.max_channels is None


class TestAuthMapping:
    async def test_add_and_resolve_auth(self, user_repo):
        user = await user_repo.create_user("api_user")
        hashed = hashlib.sha256("sk-test-key-123".encode()).hexdigest()
        mapping = await user_repo.add_auth_mapping(
            user.id, "api_key", hashed, client_name="test_client",
        )
        assert mapping.auth_type == "api_key"
        assert mapping.auth_identifier == hashed

        resolved = await user_repo.resolve_auth("api_key", hashed)
        assert resolved is not None
        assert resolved.id == user.id

    async def test_resolve_auth_telegram(self, user_repo):
        user = await user_repo.create_user("tg_user")
        await user_repo.add_auth_mapping(user.id, "telegram", "123456789")
        resolved = await user_repo.resolve_auth("telegram", "123456789")
        assert resolved is not None
        assert resolved.name == "tg_user"

    async def test_resolve_auth_not_found(self, user_repo):
        result = await user_repo.resolve_auth("api_key", "nonexistent")
        assert result is None

    async def test_remove_auth_mapping(self, user_repo):
        user = await user_repo.create_user("rm_user")
        mapping = await user_repo.add_auth_mapping(user.id, "telegram", "999")
        assert await user_repo.remove_auth_mapping(mapping.id) is True
        assert await user_repo.resolve_auth("telegram", "999") is None

    async def test_cascade_delete_removes_mappings(self, user_repo):
        user = await user_repo.create_user("cascade_user")
        await user_repo.add_auth_mapping(user.id, "telegram", "777")
        await user_repo.delete_user(user.id)
        assert await user_repo.resolve_auth("telegram", "777") is None


class TestUserCRUDEdgeCases:
    async def test_update_user_no_changes(self, user_repo):
        user = await user_repo.create_user("unchanged", role="user", max_channels=7)
        result = await user_repo.update_user(user.id)
        assert result is not None
        assert result.name == "unchanged"
        assert result.max_channels == 7

    async def test_multiple_auth_mappings_same_user(self, user_repo):
        user = await user_repo.create_user("multi_auth")
        await user_repo.add_auth_mapping(user.id, "api_key", "hash_a")
        await user_repo.add_auth_mapping(user.id, "telegram", "112233")
        await user_repo.add_auth_mapping(user.id, "mcp_token", "hash_b")

        assert (await user_repo.resolve_auth("api_key", "hash_a")).id == user.id
        assert (await user_repo.resolve_auth("telegram", "112233")).id == user.id
        assert (await user_repo.resolve_auth("mcp_token", "hash_b")).id == user.id

    async def test_duplicate_auth_mapping_raises(self, user_repo):
        from sqlalchemy.exc import IntegrityError

        user = await user_repo.create_user("dup_user")
        await user_repo.add_auth_mapping(user.id, "telegram", "444555")
        with pytest.raises(IntegrityError):
            await user_repo.add_auth_mapping(user.id, "telegram", "444555")

    async def test_remove_nonexistent_mapping(self, user_repo):
        result = await user_repo.remove_auth_mapping("00000000-0000-0000-0000-000000000000")
        assert result is False


class TestOwnership:
    async def test_get_owned_channel_ids(self, user_repo, state_repo):
        user = await user_repo.create_user("owner")
        source = Source(
            source_id="ch_owned",
            channel_id="ch_owned",
            status="active",
            include_comments=False,
            owner_id=user.id,
        )
        await state_repo.upsert_source(source)

        channels = await user_repo.get_owned_channel_ids(user.id)
        assert "ch_owned" in channels

    async def test_get_owned_channel_ids_empty(self, user_repo):
        user = await user_repo.create_user("no_channels")
        channels = await user_repo.get_owned_channel_ids(user.id)
        assert channels == []

    async def test_source_owner_id_roundtrip(self, state_repo, user_repo):
        user = await user_repo.create_user("roundtrip_owner")
        source = Source(
            source_id="ch_roundtrip",
            channel_id="ch_roundtrip",
            status="active",
            include_comments=False,
            owner_id=user.id,
        )
        await state_repo.upsert_source(source)
        fetched = await state_repo.get_source("ch_roundtrip")
        assert fetched is not None
        assert fetched.owner_id == user.id

    async def test_list_sources_by_owner(self, state_repo, user_repo):
        user = await user_repo.create_user("list_owner")
        s1 = Source(source_id="ch_a", channel_id="ch_a", status="active", include_comments=False, owner_id=user.id)
        s2 = Source(source_id="ch_b", channel_id="ch_b", status="active", include_comments=False)
        await state_repo.upsert_source(s1)
        await state_repo.upsert_source(s2)

        owned = await state_repo.list_sources(owner_id=user.id)
        owned_ids = {s.source_id for s in owned}
        assert "ch_a" in owned_ids
        assert "ch_b" not in owned_ids

    async def test_source_null_owner_roundtrip(self, state_repo):
        source = Source(source_id="ch_noowner", channel_id="ch_noowner", status="active", include_comments=False)
        await state_repo.upsert_source(source)
        fetched = await state_repo.get_source("ch_noowner")
        assert fetched is not None
        assert fetched.owner_id is None

    async def test_list_sources_combined_status_and_owner(self, state_repo, user_repo):
        user = await user_repo.create_user("combo_owner")
        s1 = Source(source_id="ch_act", channel_id="ch_act", status="active", include_comments=False, owner_id=user.id)
        s2 = Source(source_id="ch_pau", channel_id="ch_pau", status="paused", include_comments=False, owner_id=user.id)
        s3 = Source(source_id="ch_other", channel_id="ch_other", status="active", include_comments=False)
        await state_repo.upsert_source(s1)
        await state_repo.upsert_source(s2)
        await state_repo.upsert_source(s3)

        result = await state_repo.list_sources(status="active", owner_id=user.id)
        ids = {s.source_id for s in result}
        assert ids == {"ch_act"}

    async def test_multiple_sources_same_owner(self, state_repo, user_repo):
        user = await user_repo.create_user("multi_owner")
        for i in range(3):
            s = Source(source_id=f"ch_m{i}", channel_id=f"ch_m{i}", status="active", include_comments=False, owner_id=user.id)
            await state_repo.upsert_source(s)

        channels = await user_repo.get_owned_channel_ids(user.id)
        assert len(channels) == 3
