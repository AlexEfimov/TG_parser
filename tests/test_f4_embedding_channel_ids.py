"""
Tests for F4 Multi-Tenancy Phase 1: Embedding channel_ids (save, save_batch, search filtering).

Requires PostgreSQL + pgvector (TEST_POSTGRES=1).
"""

import os

import pytest

from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

FAKE_EMBEDDING = [0.1] * 1536


@pytest.fixture
async def emb_repo(test_db):
    session = test_db.processing_storage_session()
    try:
        yield SAEmbeddingRepo(session)
    finally:
        await session.close()


class TestSaveChannelIds:
    async def test_save_with_channel_ids(self, emb_repo):
        await emb_repo.save(
            source_ref="tg:ch1:post:100",
            embedding=FAKE_EMBEDDING,
            model="test-model",
            channel_ids=["ch1"],
        )
        doc = await emb_repo.get_by_source_ref("tg:ch1:post:100")
        assert doc is not None
        assert doc.channel_ids == ["ch1"]

    async def test_save_without_channel_ids(self, emb_repo):
        await emb_repo.save(
            source_ref="tg:ch2:post:200",
            embedding=FAKE_EMBEDDING,
            model="test-model",
        )
        doc = await emb_repo.get_by_source_ref("tg:ch2:post:200")
        assert doc is not None
        assert doc.channel_ids == []

    async def test_save_batch_with_channel_ids(self, emb_repo):
        items = [
            ("tg:ch3:post:1", FAKE_EMBEDDING, "test-model", None),
            ("tg:ch3:post:2", FAKE_EMBEDDING, "test-model", None),
        ]
        saved = await emb_repo.save_batch(items, channel_ids=["ch3"])
        assert saved == 2

        doc1 = await emb_repo.get_by_source_ref("tg:ch3:post:1")
        assert doc1 is not None
        assert doc1.channel_ids == ["ch3"]

    async def test_save_topic_with_multiple_channels(self, emb_repo):
        await emb_repo.save(
            source_ref="topic:cross:1",
            embedding=FAKE_EMBEDDING,
            model="test-model",
            entry_type="topic",
            topic_id="topic:cross:1",
            channel_ids=["ch1", "ch2"],
        )
        doc = await emb_repo.get_by_source_ref("topic:cross:1")
        assert doc is not None
        assert set(doc.channel_ids) == {"ch1", "ch2"}


class TestSaveChannelIdsEdgeCases:
    async def test_save_batch_without_channel_ids_defaults_empty(self, emb_repo):
        items = [("tg:ch_def:post:1", FAKE_EMBEDDING, "test-model", None)]
        await emb_repo.save_batch(items)
        doc = await emb_repo.get_by_source_ref("tg:ch_def:post:1")
        assert doc is not None
        assert doc.channel_ids == []

    async def test_upsert_overwrites_channel_ids(self, emb_repo):
        await emb_repo.save(
            source_ref="tg:upd:post:1",
            embedding=FAKE_EMBEDDING,
            model="test-model",
            channel_ids=["old_ch"],
        )
        await emb_repo.save(
            source_ref="tg:upd:post:1",
            embedding=FAKE_EMBEDDING,
            model="test-model",
            channel_ids=["new_ch"],
        )
        doc = await emb_repo.get_by_source_ref("tg:upd:post:1")
        assert doc is not None
        assert doc.channel_ids == ["new_ch"]

    async def test_save_batch_upsert_overwrites_channel_ids(self, emb_repo):
        items = [("tg:bup:post:1", FAKE_EMBEDDING, "test-model", None)]
        await emb_repo.save_batch(items, channel_ids=["v1"])
        await emb_repo.save_batch(items, channel_ids=["v2"])
        doc = await emb_repo.get_by_source_ref("tg:bup:post:1")
        assert doc.channel_ids == ["v2"]


class TestSimilaritySearchWithChannelIds:
    @pytest.fixture(autouse=True)
    async def _seed(self, emb_repo):
        await emb_repo.save(
            source_ref="tg:alpha:post:1",
            embedding=FAKE_EMBEDDING,
            model="test-model",
            channel_ids=["alpha"],
        )
        shift = list(FAKE_EMBEDDING)
        shift[0] = 0.2
        await emb_repo.save(
            source_ref="tg:beta:post:1",
            embedding=shift,
            model="test-model",
            channel_ids=["beta"],
        )

    async def test_search_no_filter_returns_all(self, emb_repo):
        results = await emb_repo.similarity_search(FAKE_EMBEDDING, limit=50)
        refs = {r.source_ref for r in results}
        assert "tg:alpha:post:1" in refs
        assert "tg:beta:post:1" in refs

    async def test_search_with_channel_filter(self, emb_repo):
        results = await emb_repo.similarity_search(
            FAKE_EMBEDDING,
            limit=10,
            channel_ids=["alpha"],
        )
        refs = {r.source_ref for r in results}
        assert "tg:alpha:post:1" in refs
        assert "tg:beta:post:1" not in refs

    async def test_search_with_multiple_channel_filter(self, emb_repo):
        results = await emb_repo.similarity_search(
            FAKE_EMBEDDING,
            limit=10,
            channel_ids=["alpha", "beta"],
        )
        refs = {r.source_ref for r in results}
        assert "tg:alpha:post:1" in refs
        assert "tg:beta:post:1" in refs

    async def test_search_channel_none_is_admin(self, emb_repo):
        """channel_ids=None should return all (admin mode)."""
        results = await emb_repo.similarity_search(
            FAKE_EMBEDDING,
            limit=10,
            channel_ids=None,
        )
        assert len(results) >= 2

    async def test_search_with_nonexistent_channel_returns_empty(self, emb_repo):
        results = await emb_repo.similarity_search(
            FAKE_EMBEDDING,
            limit=10,
            channel_ids=["nonexistent_channel"],
        )
        assert len(results) == 0

    async def test_search_combines_entry_types_and_channel_ids(self, emb_repo):
        """Both entry_types and channel_ids filters applied simultaneously."""
        await emb_repo.save(
            source_ref="topic:alpha:t1",
            embedding=FAKE_EMBEDDING,
            model="test-model",
            entry_type="topic",
            topic_id="topic:alpha:t1",
            channel_ids=["alpha"],
        )
        results = await emb_repo.similarity_search(
            FAKE_EMBEDDING,
            limit=10,
            entry_types=["topic"],
            channel_ids=["alpha"],
        )
        refs = {r.source_ref for r in results}
        assert "topic:alpha:t1" in refs
        assert "tg:alpha:post:1" not in refs  # message, not topic

    async def test_search_empty_channel_ids_list_returns_empty(self, emb_repo):
        """Empty list (not None!) means user has no channels → no results."""
        results = await emb_repo.similarity_search(
            FAKE_EMBEDDING,
            limit=10,
            channel_ids=[],
        )
        assert len(results) == 0
