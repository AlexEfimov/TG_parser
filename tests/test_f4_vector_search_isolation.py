"""
Tests for F4 Multi-Tenancy Phase 4: Vector Search Isolation.

Tests SQL-level channel_ids filtering and IVFFlat probes behavior.
Requires TEST_POSTGRES=1 for integration tests.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import PermissionDenied


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin",
        allowed_channel_ids=None, max_channels=100,
    )


def _user(channels: list[str]) -> CurrentUser:
    return CurrentUser(
        id="user-1", name="alice", role="user",
        allowed_channel_ids=channels, max_channels=5,
    )


# ---------------------------------------------------------------------------
# SQL-level channel_ids && ARRAY[...] filter
# ---------------------------------------------------------------------------

class TestSimilaritySearchChannelFilter:
    async def test_channel_ids_filter_passed_to_sql(self):
        """Verify that channel_ids parameter is forwarded to similarity_search."""
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = []
        mock_proc_repo = AsyncMock()

        from tg_parser.services.retrieval_service import search

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            await search(
                query="test",
                allowed_channel_ids=["ch1", "ch2"],
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                include_topics=False,
            )

        call_kwargs = mock_emb_repo.similarity_search.call_args.kwargs
        assert call_kwargs["channel_ids"] == ["ch1", "ch2"]

    async def test_empty_channel_ids_returns_nothing(self):
        from tg_parser.services.retrieval_service import search
        results = await search(query="test", allowed_channel_ids=[])
        assert results == []

    async def test_none_channel_ids_no_filter(self):
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = []
        mock_proc_repo = AsyncMock()

        from tg_parser.services.retrieval_service import search

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            await search(
                query="test",
                allowed_channel_ids=None,
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                include_topics=False,
            )

        call_kwargs = mock_emb_repo.similarity_search.call_args.kwargs
        assert call_kwargs["channel_ids"] is None


# ---------------------------------------------------------------------------
# Intersection of channel_id + allowed_channel_ids
# ---------------------------------------------------------------------------

class TestChannelIdIntersection:
    async def test_single_channel_in_allowed(self):
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = []
        mock_proc_repo = AsyncMock()

        from tg_parser.services.retrieval_service import search

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            await search(
                query="test",
                channel_id="ch1",
                allowed_channel_ids=["ch1", "ch2"],
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                include_topics=False,
            )

        call_kwargs = mock_emb_repo.similarity_search.call_args.kwargs
        assert call_kwargs["channel_ids"] == ["ch1"]

    async def test_single_channel_not_in_allowed_raises(self):
        from tg_parser.services.retrieval_service import search
        with pytest.raises(PermissionDenied):
            await search(
                query="test",
                channel_id="ch3",
                allowed_channel_ids=["ch1", "ch2"],
            )


# ---------------------------------------------------------------------------
# IVFFlat probes tuning
# ---------------------------------------------------------------------------

class TestIVFFlatProbes:
    async def test_probes_set_when_channel_ids_provided(self):
        """Verify SET ivfflat.probes = 20 is called when channel_ids is set."""
        from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        repo = SAEmbeddingRepo(mock_session)
        await repo.similarity_search(
            query_embedding=[0.1] * 1536,
            channel_ids=["ch1"],
        )

        sql_texts = [
            c.args[0].text if hasattr(c.args[0], "text") else str(c.args[0])
            for c in mock_session.execute.call_args_list
        ]
        probes_called = any("ivfflat.probes" in t for t in sql_texts)
        assert probes_called, f"Expected SET ivfflat.probes = 20; got SQL calls: {sql_texts}"

    async def test_probes_not_set_when_no_channel_ids(self):
        from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        repo = SAEmbeddingRepo(mock_session)
        await repo.similarity_search(
            query_embedding=[0.1] * 1536,
            channel_ids=None,
        )

        sql_texts = [
            c.args[0].text if hasattr(c.args[0], "text") else str(c.args[0])
            for c in mock_session.execute.call_args_list
        ]
        probes_called = any("ivfflat.probes" in t for t in sql_texts)
        assert not probes_called, "Should not SET ivfflat.probes when channel_ids is None"


# ---------------------------------------------------------------------------
# Cross-channel topic embedding found by either channel filter
# ---------------------------------------------------------------------------

class TestCrossChannelTopicEmbedding:
    async def test_topic_visible_if_any_source_in_allowed(self):
        """A topic card with sources=[ch1,ch2] should be visible to user with ch1."""
        from datetime import UTC, datetime

        from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType
        from tg_parser.services.retrieval_service import SearchResult, search
        from tg_parser.storage.ports import SimilarityResult

        mock_emb_repo = AsyncMock()
        sim_result = SimilarityResult(
            source_ref="topic:cross", score=0.9,
            entry_type="topic", topic_id="t-cross",
        )
        mock_emb_repo.similarity_search.return_value = [sim_result]

        anchor1 = Anchor(
            channel_id="ch1", message_id="1",
            message_type=MessageType.POST, anchor_ref="tg:ch1:post:1",
            score=0.9,
        )
        anchor2 = Anchor(
            channel_id="ch2", message_id="2",
            message_type=MessageType.POST, anchor_ref="tg:ch2:post:2",
            score=0.8,
        )
        card = TopicCard(
            id="t-cross", title="Cross-channel topic", summary="desc",
            scope_in=["in"], scope_out=["out"], type=TopicType.CLUSTER,
            anchors=[anchor1, anchor2], sources=["ch1", "ch2"],
            updated_at=datetime.now(UTC),
        )

        mock_tc_repo = AsyncMock()
        mock_tc_repo.get_by_id.return_value = card

        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_refs.return_value = {}

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            results = await search(
                query="test",
                allowed_channel_ids=["ch1"],
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                topic_card_repo=mock_tc_repo,
            )

        assert len(results) == 1
        assert results[0].topic_card.id == "t-cross"

    async def test_topic_hidden_if_no_source_in_allowed(self):
        """A topic card with sources=[ch3] should be hidden from user with ch1."""
        from datetime import UTC, datetime

        from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        mock_emb_repo = AsyncMock()
        sim_result = SimilarityResult(
            source_ref="topic:hidden", score=0.9,
            entry_type="topic", topic_id="t-hidden",
        )
        mock_emb_repo.similarity_search.return_value = [sim_result]

        anchor = Anchor(
            channel_id="ch3", message_id="1",
            message_type=MessageType.POST, anchor_ref="tg:ch3:post:1",
        )
        card = TopicCard(
            id="t-hidden", title="Hidden topic", summary="desc",
            scope_in=["in"], scope_out=["out"], type=TopicType.SINGLETON,
            anchors=[anchor], sources=["ch3"], updated_at=datetime.now(UTC),
        )

        mock_tc_repo = AsyncMock()
        mock_tc_repo.get_by_id.return_value = card

        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_refs.return_value = {}

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            results = await search(
                query="test",
                allowed_channel_ids=["ch1"],
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                topic_card_repo=mock_tc_repo,
            )

        assert len(results) == 0
