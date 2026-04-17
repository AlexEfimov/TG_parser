"""
Tests for F5-A: Persistent KB + Topic RAG.

1. Schema DDL: new columns in EMBEDDING_DDL
2. Ports: entry_type / topic_id on DocumentEmbedding, SimilarityResult
3. SAEmbeddingRepo: save, save_batch, similarity_search, list_missing, delete
4. Topic embedding: run_topic_embedding
5. Hybrid RAG: retrieval_service.search + _build_context
6. Pipeline integration hooks
7. Edge cases
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Schema DDL
# ---------------------------------------------------------------------------

class TestEmbeddingDDL:
    def test_ddl_contains_entry_type(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import EMBEDDING_DDL
        assert "entry_type" in EMBEDDING_DDL

    def test_ddl_contains_topic_id(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import EMBEDDING_DDL
        assert "topic_id" in EMBEDDING_DDL

    def test_ddl_no_fk_reference(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import EMBEDDING_DDL
        assert "REFERENCES processed_documents" not in EMBEDDING_DDL

    def test_ddl_has_entry_type_index(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import EMBEDDING_DDL
        assert "idx_de_entry_type" in EMBEDDING_DDL

    def test_ddl_default_message(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import EMBEDDING_DDL
        assert "DEFAULT 'message'" in EMBEDDING_DDL


# ---------------------------------------------------------------------------
# 2. Ports: domain objects
# ---------------------------------------------------------------------------

class TestPortsEntryType:
    def test_document_embedding_defaults(self):
        from tg_parser.storage.ports import DocumentEmbedding
        de = DocumentEmbedding(
            source_ref="ref1",
            embedding=[0.1],
            model="m",
            created_at=datetime.now(UTC),
        )
        assert de.entry_type == "message"
        assert de.topic_id is None

    def test_document_embedding_topic(self):
        from tg_parser.storage.ports import DocumentEmbedding
        de = DocumentEmbedding(
            source_ref="topic:abc",
            embedding=[0.2],
            model="m",
            created_at=datetime.now(UTC),
            entry_type="topic",
            topic_id="topic:abc",
        )
        assert de.entry_type == "topic"
        assert de.topic_id == "topic:abc"

    def test_similarity_result_defaults(self):
        from tg_parser.storage.ports import SimilarityResult
        sr = SimilarityResult(source_ref="ref1", score=0.9)
        assert sr.entry_type == "message"
        assert sr.topic_id is None

    def test_similarity_result_topic(self):
        from tg_parser.storage.ports import SimilarityResult
        sr = SimilarityResult(
            source_ref="topic:abc", score=0.85,
            entry_type="topic", topic_id="topic:abc",
        )
        assert sr.entry_type == "topic"
        assert sr.topic_id == "topic:abc"


# ---------------------------------------------------------------------------
# 3. SAEmbeddingRepo: entry_type awareness
# ---------------------------------------------------------------------------

def _make_repo():
    from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
    session = AsyncMock()
    return SAEmbeddingRepo(session), session


class TestSAEmbeddingRepoSave:
    async def test_save_includes_entry_type(self):
        repo, session = _make_repo()
        await repo.save("ref1", [0.1], "model", entry_type="message")
        call_args = session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("parameters", {})
        assert params["entry_type"] == "message"
        assert params["topic_id"] is None

    async def test_save_topic(self):
        repo, session = _make_repo()
        await repo.save(
            "topic:123", [0.2], "model",
            entry_type="topic", topic_id="topic:123",
        )
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["entry_type"] == "topic"
        assert params["topic_id"] == "topic:123"


class TestSAEmbeddingRepoSaveBatch:
    async def test_save_batch_entry_type(self):
        repo, session = _make_repo()
        items = [("ref1", [0.1], "m", None), ("ref2", [0.2], "m", None)]
        await repo.save_batch(items, entry_type="message")
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["et0"] == "message"
        assert params["et1"] == "message"

    async def test_save_batch_topic(self):
        repo, session = _make_repo()
        items = [("topic:1", [0.1], "m", None)]
        await repo.save_batch(items, entry_type="topic", topic_id=None)
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["et0"] == "topic"

    async def test_save_batch_empty(self):
        repo, session = _make_repo()
        result = await repo.save_batch([])
        assert result == 0
        session.execute.assert_not_called()


class TestSAEmbeddingRepoSimilaritySearch:
    async def test_search_no_filter(self):
        repo, session = _make_repo()
        mock_row = Mock(source_ref="ref1", score=0.9, entry_type="message", topic_id=None)
        session.execute.return_value = Mock(fetchall=Mock(return_value=[mock_row]))

        results = await repo.similarity_search([0.1], limit=5)
        sql_str = str(session.execute.call_args[0][0].text)
        assert "entry_type IN" not in sql_str
        assert len(results) == 1
        assert results[0].entry_type == "message"

    async def test_search_with_entry_types(self):
        repo, session = _make_repo()
        msg_row = Mock(source_ref="ref1", score=0.9, entry_type="message", topic_id=None)
        topic_row = Mock(source_ref="topic:abc", score=0.85, entry_type="topic", topic_id="topic:abc")
        session.execute.return_value = Mock(fetchall=Mock(return_value=[msg_row, topic_row]))

        results = await repo.similarity_search(
            [0.1], limit=10, entry_types=["message", "topic"],
        )
        sql_str = str(session.execute.call_args[0][0].text)
        assert "entry_type IN" in sql_str
        assert len(results) == 2
        assert results[0].entry_type == "message"
        assert results[1].entry_type == "topic"
        assert results[1].topic_id == "topic:abc"

    async def test_search_message_only(self):
        repo, session = _make_repo()
        session.execute.return_value = Mock(fetchall=Mock(return_value=[]))
        await repo.similarity_search([0.1], entry_types=["message"])
        sql_str = str(session.execute.call_args[0][0].text)
        assert "entry_type IN" in sql_str
        params = session.execute.call_args[0][1]
        assert params["et0"] == "message"

    async def test_search_threshold_filter(self):
        repo, session = _make_repo()
        low = Mock(source_ref="low", score=0.1, entry_type="message", topic_id=None)
        high = Mock(source_ref="high", score=0.9, entry_type="message", topic_id=None)
        session.execute.return_value = Mock(fetchall=Mock(return_value=[high, low]))

        results = await repo.similarity_search([0.1], threshold=0.5)
        assert len(results) == 1
        assert results[0].source_ref == "high"


class TestSAEmbeddingRepoListMissing:
    async def test_list_missing_filters_message_type(self):
        repo, session = _make_repo()
        session.execute.return_value = Mock(fetchall=Mock(return_value=[]))
        await repo.list_missing("ch1")
        sql_str = str(session.execute.call_args[0][0].text)
        assert "entry_type = 'message'" in sql_str


class TestSAEmbeddingRepoDeleteByChannel:
    async def test_delete_two_queries(self):
        repo, session = _make_repo()
        r1 = Mock(rowcount=3)
        r2 = Mock(rowcount=1)
        session.execute.side_effect = [r1, r2]
        total = await repo.delete_by_channel("ch1")
        assert total == 4
        assert session.execute.call_count == 2


class TestSAEmbeddingRepoRowToModel:
    def test_row_to_model_with_entry_type(self):
        from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
        row = Mock()
        row.__getitem__ = lambda self, idx: "[0.1,0.2]" if idx == 1 else None
        row.source_ref = "ref1"
        row.model = "m"
        row.created_at = "2025-01-01T00:00:00Z"
        row.metadata_json = None
        row.entry_type = "topic"
        row.topic_id = "topic:abc"

        result = SAEmbeddingRepo._row_to_model(row)
        assert result.entry_type == "topic"
        assert result.topic_id == "topic:abc"

    def test_row_to_model_defaults(self):
        from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
        row = Mock()
        row.__getitem__ = lambda self, idx: "[0.3]" if idx == 1 else None
        row.source_ref = "ref2"
        row.model = "m"
        row.created_at = "2025-01-01T00:00:00Z"
        row.metadata_json = None
        del row.entry_type
        del row.topic_id

        result = SAEmbeddingRepo._row_to_model(row)
        assert result.entry_type == "message"
        assert result.topic_id is None


# ---------------------------------------------------------------------------
# 4. Topic embedding: run_topic_embedding
# ---------------------------------------------------------------------------

def _make_topic_card(topic_id="topic:ch1:post:1", summary="Test summary", scope_in=None):
    from tg_parser.domain.models import Anchor, TopicCard, TopicType
    return TopicCard(
        id=topic_id,
        title="Test Topic",
        summary=summary,
        scope_in=scope_in or ["scope1", "scope2"],
        scope_out=["out1"],
        type=TopicType.SINGLETON,
        anchors=[Anchor(
            channel_id="ch1",
            message_id="1",
            message_type="post",
            anchor_ref="tg:ch1:post:1",
            score=1.0,
        )],
        sources=["ch1"],
        updated_at=datetime.now(UTC),
    )


class TestPrepareTopicText:
    def test_prepare_topic_text(self):
        from tg_parser.services.embedding_service import _prepare_topic_text
        result = _prepare_topic_text("Summary here", ["A", "B"])
        assert result == "Summary here | A | B"

    def test_prepare_topic_text_empty_scope(self):
        from tg_parser.services.embedding_service import _prepare_topic_text
        result = _prepare_topic_text("Only summary", [])
        assert result == "Only summary"


class TestRunTopicEmbedding:
    async def test_embeds_topics(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        card = _make_topic_card()
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=None)
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[card])

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1, 0.2]])

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 1
        assert stats["total_count"] == 1
        emb_repo.save.assert_awaited_once()
        call_kwargs = emb_repo.save.call_args[1]
        assert call_kwargs["entry_type"] == "topic"
        assert call_kwargs["topic_id"] == card.id

    async def test_skips_existing(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        card = _make_topic_card()
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=Mock())
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[card])

        mock_client = AsyncMock()
        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 0
        assert stats["total_count"] == 0
        mock_client.embed.assert_not_awaited()

    async def test_force_reembeds(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        card = _make_topic_card()
        emb_repo = AsyncMock()
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[card])

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.3]])

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", force=True,
                emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 1
        emb_repo.get_by_source_ref.assert_not_awaited()

    async def test_specific_topic_ids(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        card = _make_topic_card(topic_id="topic:ch1:post:42")
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=None)
        topic_repo = AsyncMock()
        topic_repo.get_by_id = AsyncMock(return_value=card)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.5]])

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", topic_ids=["topic:ch1:post:42"],
                emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 1
        topic_repo.get_by_id.assert_awaited_once_with("topic:ch1:post:42")
        topic_repo.list_by_channel.assert_not_awaited()

    async def test_no_topics(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        emb_repo = AsyncMock()
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 0
        assert stats["total_count"] == 0

    async def test_client_closed(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        emb_repo = AsyncMock()
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )
        mock_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. Hybrid RAG: retrieval_service
# ---------------------------------------------------------------------------

class TestHybridSearch:
    async def test_search_hybrid(self):
        from tg_parser.domain.models import ProcessedDocument
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        msg_sim = SimilarityResult(source_ref="tg:ch1:post:1", score=0.9, entry_type="message")
        topic_sim = SimilarityResult(
            source_ref="topic:ch1:post:2", score=0.85,
            entry_type="topic", topic_id="topic:ch1:post:2",
        )

        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=[msg_sim, topic_sim])

        doc = ProcessedDocument(
            source_ref="tg:ch1:post:1",
            id="1",
            source_message_id="1",
            channel_id="ch1",
            processed_at=datetime.now(UTC),
            text_clean="Hello world",
        )
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={"tg:ch1:post:1": doc})

        card = _make_topic_card(topic_id="topic:ch1:post:2")
        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id = AsyncMock(return_value=card)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            results = await search(
                "test query",
                emb_repo=emb_repo,
                proc_repo=proc_repo,
                topic_card_repo=topic_card_repo,
            )

        assert len(results) == 2
        assert results[0].entry_type == "message"
        assert results[0].document == doc
        assert results[1].entry_type == "topic"
        assert results[1].topic_card == card

        emb_repo.similarity_search.assert_awaited_once()
        call_kwargs = emb_repo.similarity_search.call_args[1]
        assert "message" in call_kwargs["entry_types"]
        assert "topic" in call_kwargs["entry_types"]

    async def test_search_messages_only(self):
        from tg_parser.services.retrieval_service import search

        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=[])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            await search(
                "test", include_topics=False,
                emb_repo=emb_repo, proc_repo=proc_repo,
            )

        call_kwargs = emb_repo.similarity_search.call_args[1]
        assert call_kwargs["entry_types"] == ["message"]

    async def test_search_channel_filter_topic(self):
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        topic_sim = SimilarityResult(
            source_ref="topic:other:post:1", score=0.9,
            entry_type="topic", topic_id="topic:other:post:1",
        )
        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=[topic_sim])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        card = _make_topic_card(topic_id="topic:other:post:1")
        card.sources = ["other_channel"]
        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id = AsyncMock(return_value=card)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            results = await search(
                "test", channel_id="my_channel",
                emb_repo=emb_repo, proc_repo=proc_repo,
                topic_card_repo=topic_card_repo,
            )

        assert len(results) == 0


class TestBuildContext:
    def test_build_context_message(self):
        from tg_parser.domain.models import ProcessedDocument
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = ProcessedDocument(
            source_ref="tg:ch1:post:1", id="1", source_message_id="1",
            channel_id="ch1", processed_at=datetime.now(UTC),
            text_clean="Hello world", summary="Summary",
            topics=["topic1"],
        )
        results = [SearchResult(source_ref="tg:ch1:post:1", score=0.9, document=doc)]
        ctx = _build_context(results, 1000)
        assert "[1] channel: ch1" in ctx
        assert "Hello world" in ctx
        assert "Topics: topic1" in ctx

    def test_build_context_topic(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        card = _make_topic_card()
        results = [SearchResult(
            source_ref=card.id, score=0.85,
            entry_type="topic", topic_card=card,
        )]
        ctx = _build_context(results, 1000)
        assert "[TOPIC]" in ctx
        assert "Test Topic" in ctx
        assert "Test summary" in ctx
        assert "Scope:" in ctx

    def test_build_context_mixed(self):
        from tg_parser.domain.models import ProcessedDocument
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = ProcessedDocument(
            source_ref="tg:ch1:post:1", id="1", source_message_id="1",
            channel_id="ch1", processed_at=datetime.now(UTC),
            text_clean="Doc text",
        )
        card = _make_topic_card()

        results = [
            SearchResult(source_ref="tg:ch1:post:1", score=0.9, document=doc),
            SearchResult(
                source_ref=card.id, score=0.85,
                entry_type="topic", topic_card=card,
            ),
        ]
        ctx = _build_context(results, 1000)
        assert "[1] channel:" in ctx
        assert "[2] [TOPIC]" in ctx
        assert "---" in ctx

    def test_build_context_topic_with_tags(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        card = _make_topic_card()
        card.tags = ["tag1", "tag2"]
        results = [SearchResult(
            source_ref=card.id, score=0.8,
            entry_type="topic", topic_card=card,
        )]
        ctx = _build_context(results, 1000)
        assert "Tags: tag1, tag2" in ctx

    def test_build_context_no_document_no_card(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context
        results = [SearchResult(source_ref="ref1", score=0.9)]
        ctx = _build_context(results, 1000)
        assert ctx == ""

    def test_build_context_topic_no_card(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context
        results = [SearchResult(
            source_ref="topic:x", score=0.8, entry_type="topic",
        )]
        ctx = _build_context(results, 1000)
        assert ctx == ""


# ---------------------------------------------------------------------------
# 6. Pipeline integration hooks
# ---------------------------------------------------------------------------

class TestPipelineTopicEmbeddingHook:
    async def test_pipeline_calls_topic_embedding(self):
        with patch("tg_parser.services.pipeline_service.run_ingestion", new=AsyncMock(return_value={
            "posts_collected": 5, "comments_collected": 0,
        })), \
        patch("tg_parser.services.pipeline_service.run_processing", new=AsyncMock(return_value={
            "processed_count": 5, "failed_count": 0, "total_tokens": 100,
        })), \
        patch("tg_parser.services.pipeline_service.run_topicization", new=AsyncMock(return_value={
            "topics_count": 2, "bundles_count": 2, "total_tokens": 50,
        })), \
        patch("tg_parser.services.pipeline_service.run_export", new=AsyncMock(return_value={
            "kb_entries_count": 5, "topics_count": 2,
        })), \
        patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new=AsyncMock(return_value="ch1")), \
        patch("tg_parser.services.embedding_service.run_topic_embedding", new=AsyncMock(return_value={
            "embedded_count": 2, "skipped_count": 0, "total_count": 2,
        })) as mock_topic_emb:
            from tg_parser.services.pipeline_service import run_full_pipeline
            await run_full_pipeline(
                source_id="src1",
                output_dir="/tmp/test",
            )

            mock_topic_emb.assert_awaited_once()
            call_kwargs = mock_topic_emb.call_args[1]
            assert call_kwargs["channel_id"] == "ch1"

    async def test_pipeline_topic_embedding_failure_nonfatal(self):
        with patch("tg_parser.services.pipeline_service.run_ingestion", new=AsyncMock(return_value={
            "posts_collected": 1, "comments_collected": 0,
        })), \
        patch("tg_parser.services.pipeline_service.run_processing", new=AsyncMock(return_value={
            "processed_count": 1, "failed_count": 0, "total_tokens": 10,
        })), \
        patch("tg_parser.services.pipeline_service.run_topicization", new=AsyncMock(return_value={
            "topics_count": 1, "bundles_count": 1, "total_tokens": 5,
        })), \
        patch("tg_parser.services.pipeline_service.run_export", new=AsyncMock(return_value={
            "kb_entries_count": 1, "topics_count": 1,
        })), \
        patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new=AsyncMock(return_value="ch1")), \
        patch("tg_parser.services.embedding_service.run_topic_embedding", new=AsyncMock(side_effect=RuntimeError("embed fail"))):
            from tg_parser.services.pipeline_service import run_full_pipeline
            stats = await run_full_pipeline(source_id="src1", output_dir="/tmp/test")
            assert stats["last_successful_stage"] == "export"


class TestBackgroundSchedulerTopicEmbedding:
    async def test_incremental_embedding_task_calls_topic(self):
        from tg_parser.storage.ports import Source

        source = Source(
            source_id="src1", channel_id="ch1",
            status="active", include_comments=False,
        )

        mock_state_repo = AsyncMock()
        mock_state_repo.list_sources = AsyncMock(return_value=[source])
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_state_repo, Mock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            return_value=mock_cm,
        ), patch(
            "tg_parser.services.embedding_service.run_embedding",
            new=AsyncMock(return_value={"embedded_count": 0}),
        ), patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new=AsyncMock(return_value={"embedded_count": 1}),
        ) as mock_topic:
            from tg_parser.services.background_scheduler import _incremental_embedding_task
            await _incremental_embedding_task()

            mock_topic.assert_awaited_once()
            assert mock_topic.call_args[1]["channel_id"] == "ch1"


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    async def test_topic_card_with_empty_summary(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        card = _make_topic_card(summary="")
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=None)
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[card])

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 1
        called_texts = mock_client.embed.call_args[0][0]
        assert "scope1" in called_texts[0]

    async def test_topic_id_not_found(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=None)
        topic_repo = AsyncMock()
        topic_repo.get_by_id = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", topic_ids=["nonexistent"],
                emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 0
        assert stats["total_count"] == 0

    async def test_multiple_topics_batching(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        cards = [
            _make_topic_card(topic_id=f"topic:ch1:post:{i}")
            for i in range(3)
        ]
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=None)
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=cards)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1], [0.2], [0.3]])

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ), patch("tg_parser.services.embedding_service.settings") as mock_settings:
            mock_settings.embedding_batch_size = 2
            mock_settings.embedding_model = "test-model"
            mock_settings.openai_api_key = "test"
            mock_settings.openai_base_url = "http://test"

            mock_client.embed = AsyncMock(side_effect=[
                [[0.1], [0.2]],
                [[0.3]],
            ])

            stats = await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 3
        assert mock_client.embed.call_count == 2

    def test_alembic_migration_file_exists(self):
        from pathlib import Path
        migration = Path(
            "/Users/alexanderefimov/TG_parser/migrations/versions/processing/"
            "20260415_add_entry_type_to_embeddings.py"
        )
        assert migration.exists()

    def test_alembic_migration_revision_chain(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration",
            "/Users/alexanderefimov/TG_parser/migrations/versions/processing/"
            "20260415_add_entry_type_to_embeddings.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.down_revision == "f40d85317f03"
        assert mod.revision == "a1b2c3d4e5f6"


# ---------------------------------------------------------------------------
# 8. Additional coverage: repo edge cases
# ---------------------------------------------------------------------------

class TestSAEmbeddingRepoGetBySourceRef:
    async def test_get_by_source_ref_selects_new_columns(self):
        repo, session = _make_repo()
        row = Mock()
        row.__getitem__ = lambda self, idx: "[0.1]" if idx == 1 else None
        row.source_ref = "topic:ch1:post:1"
        row.model = "m"
        row.created_at = "2025-01-01T00:00:00Z"
        row.metadata_json = None
        row.entry_type = "topic"
        row.topic_id = "topic:ch1:post:1"
        session.execute.return_value = Mock(fetchone=Mock(return_value=row))

        result = await repo.get_by_source_ref("topic:ch1:post:1")
        sql_str = str(session.execute.call_args[0][0].text)
        assert "entry_type" in sql_str
        assert "topic_id" in sql_str
        assert result is not None
        assert result.entry_type == "topic"
        assert result.topic_id == "topic:ch1:post:1"

    async def test_get_by_source_ref_not_found(self):
        repo, session = _make_repo()
        session.execute.return_value = Mock(fetchone=Mock(return_value=None))
        result = await repo.get_by_source_ref("nonexistent")
        assert result is None


class TestSAEmbeddingRepoSaveWithMetadata:
    async def test_save_with_metadata_and_topic(self):
        repo, session = _make_repo()
        await repo.save(
            "topic:1", [0.1], "m",
            metadata={"key": "val"},
            entry_type="topic", topic_id="topic:1",
        )
        params = session.execute.call_args[0][1]
        assert params["entry_type"] == "topic"
        assert params["topic_id"] == "topic:1"
        assert '"key"' in params["metadata_json"]


class TestSAEmbeddingRepoSaveBatchSQL:
    async def test_save_batch_sql_includes_new_columns(self):
        repo, session = _make_repo()
        items = [("ref1", [0.1], "m", None)]
        await repo.save_batch(items, entry_type="message")
        sql_str = str(session.execute.call_args[0][0].text)
        assert "entry_type" in sql_str
        assert "topic_id" in sql_str
        assert "entry_type = excluded.entry_type" in sql_str


class TestSAEmbeddingRepoDeleteEdgeCases:
    async def test_delete_zero_messages_some_topics(self):
        repo, session = _make_repo()
        session.execute.side_effect = [Mock(rowcount=0), Mock(rowcount=5)]
        total = await repo.delete_by_channel("ch1")
        assert total == 5

    async def test_delete_some_messages_zero_topics(self):
        repo, session = _make_repo()
        session.execute.side_effect = [Mock(rowcount=4), Mock(rowcount=0)]
        total = await repo.delete_by_channel("ch1")
        assert total == 4

    async def test_delete_none_rowcount(self):
        repo, session = _make_repo()
        session.execute.side_effect = [Mock(rowcount=None), Mock(rowcount=None)]
        total = await repo.delete_by_channel("ch1")
        assert total == 0

    async def test_delete_pattern_contains_channel_id(self):
        repo, session = _make_repo()
        session.execute.side_effect = [Mock(rowcount=0), Mock(rowcount=0)]
        await repo.delete_by_channel("my_channel")
        second_call_params = session.execute.call_args_list[1][0][1]
        assert "%my_channel%" in second_call_params["pattern"]


class TestSAEmbeddingRepoSimilaritySearchEdge:
    async def test_search_null_entry_type_fallback(self):
        repo, session = _make_repo()
        row = Mock(source_ref="ref1", score=0.8, entry_type=None, topic_id=None)
        session.execute.return_value = Mock(fetchall=Mock(return_value=[row]))
        results = await repo.similarity_search([0.1])
        assert results[0].entry_type == "message"

    async def test_search_topic_only_filter(self):
        repo, session = _make_repo()
        row = Mock(source_ref="topic:1", score=0.9, entry_type="topic", topic_id="topic:1")
        session.execute.return_value = Mock(fetchall=Mock(return_value=[row]))
        results = await repo.similarity_search([0.1], entry_types=["topic"])
        params = session.execute.call_args[0][1]
        assert params["et0"] == "topic"
        assert len(results) == 1
        assert results[0].entry_type == "topic"


# ---------------------------------------------------------------------------
# 9. Additional coverage: embedding service edge cases
# ---------------------------------------------------------------------------

class TestRunTopicEmbeddingEdge:
    async def test_client_closed_on_embed_error(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        card = _make_topic_card()
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(return_value=None)
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=[card])

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(side_effect=RuntimeError("API down"))

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="API down"):
                await run_topic_embedding(
                    "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
                )

        mock_client.close.assert_awaited_once()

    async def test_skipped_count_correct(self):
        from tg_parser.services.embedding_service import run_topic_embedding

        cards = [
            _make_topic_card(topic_id="topic:ch1:post:1"),
            _make_topic_card(topic_id="topic:ch1:post:2"),
        ]
        emb_repo = AsyncMock()
        emb_repo.get_by_source_ref = AsyncMock(
            side_effect=[None, Mock()]
        )
        topic_repo = AsyncMock()
        topic_repo.list_by_channel = AsyncMock(return_value=cards)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            return_value=mock_client,
        ):
            stats = await run_topic_embedding(
                "ch1", emb_repo=emb_repo, topic_card_repo=topic_repo,
            )

        assert stats["embedded_count"] == 1
        assert stats["skipped_count"] == 0
        assert stats["total_count"] == 1


class TestPrepareTopicTextEdge:
    def test_prepare_empty_summary_and_scope(self):
        from tg_parser.services.embedding_service import _prepare_topic_text
        result = _prepare_topic_text("", [])
        assert result == ""

    def test_prepare_single_scope_item(self):
        from tg_parser.services.embedding_service import _prepare_topic_text
        result = _prepare_topic_text("Sum", ["One"])
        assert result == "Sum | One"


# ---------------------------------------------------------------------------
# 10. Additional coverage: retrieval service edge cases
# ---------------------------------------------------------------------------

class TestHybridSearchEdge:
    async def test_search_all_topics_no_messages(self):
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        t1 = SimilarityResult(source_ref="topic:1", score=0.9, entry_type="topic", topic_id="topic:1")
        t2 = SimilarityResult(source_ref="topic:2", score=0.8, entry_type="topic", topic_id="topic:2")

        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=[t1, t2])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        card1 = _make_topic_card(topic_id="topic:1")
        card2 = _make_topic_card(topic_id="topic:2")
        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id = AsyncMock(side_effect=[card1, card2])

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            results = await search(
                "query", emb_repo=emb_repo, proc_repo=proc_repo,
                topic_card_repo=topic_card_repo,
            )

        assert len(results) == 2
        assert all(r.entry_type == "topic" for r in results)
        proc_repo.get_by_source_refs.assert_not_awaited()

    async def test_search_limit_enforcement(self):
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        sims = [
            SimilarityResult(source_ref=f"tg:ch1:post:{i}", score=0.9 - i * 0.01, entry_type="message")
            for i in range(5)
        ]
        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=sims)
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={
            s.source_ref: Mock(channel_id="ch1") for s in sims
        })

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            results = await search(
                "query", limit=2, include_topics=False,
                emb_repo=emb_repo, proc_repo=proc_repo,
            )

        assert len(results) == 2

    async def test_search_empty_results(self):
        from tg_parser.services.retrieval_service import search

        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=[])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            results = await search(
                "query", emb_repo=emb_repo, proc_repo=proc_repo,
            )

        assert results == []

    async def test_search_topic_with_null_topic_id(self):
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        sim = SimilarityResult(
            source_ref="topic:orphan", score=0.7,
            entry_type="topic", topic_id=None,
        )
        emb_repo = AsyncMock()
        emb_repo.similarity_search = AsyncMock(return_value=[sim])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})
        topic_card_repo = AsyncMock()

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1]])

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            return_value=mock_client,
        ):
            results = await search(
                "query", emb_repo=emb_repo, proc_repo=proc_repo,
                topic_card_repo=topic_card_repo,
            )

        assert len(results) == 1
        assert results[0].topic_card is None
        topic_card_repo.get_by_id.assert_not_awaited()


class TestBuildContextEdge:
    def test_build_context_topic_tags_none(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        card = _make_topic_card()
        card.tags = None
        results = [SearchResult(
            source_ref=card.id, score=0.8,
            entry_type="topic", topic_card=card,
        )]
        ctx = _build_context(results, 1000)
        assert "Tags:" not in ctx
        assert "[TOPIC]" in ctx

    def test_build_context_topic_empty_scope(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        card = _make_topic_card(scope_in=["only_scope"])
        card.scope_in = []
        results = [SearchResult(
            source_ref=card.id, score=0.8,
            entry_type="topic", topic_card=card,
        )]
        ctx = _build_context(results, 1000)
        assert "Scope:" not in ctx
        assert "Test summary" in ctx

    def test_build_context_message_no_summary_no_topics(self):
        from tg_parser.domain.models import ProcessedDocument
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = ProcessedDocument(
            source_ref="tg:ch1:post:1", id="1", source_message_id="1",
            channel_id="ch1", processed_at=datetime.now(UTC),
            text_clean="Plain text only, no summary at all",
        )
        results = [SearchResult(source_ref="tg:ch1:post:1", score=0.7, document=doc)]
        ctx = _build_context(results, 1000)
        assert "Plain text only" in ctx
        assert "Topics:" not in ctx


# ---------------------------------------------------------------------------
# 11. Additional coverage: pipeline integration edge cases
# ---------------------------------------------------------------------------

class TestPipelineSkipTopicize:
    async def test_skip_topicize_no_topic_embedding(self):
        with patch("tg_parser.services.pipeline_service.run_ingestion", new=AsyncMock(return_value={
            "posts_collected": 1, "comments_collected": 0,
        })), \
        patch("tg_parser.services.pipeline_service.run_processing", new=AsyncMock(return_value={
            "processed_count": 1, "failed_count": 0, "total_tokens": 10,
        })), \
        patch("tg_parser.services.pipeline_service.run_export", new=AsyncMock(return_value={
            "kb_entries_count": 1, "topics_count": 0,
        })), \
        patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new=AsyncMock(return_value="ch1")), \
        patch("tg_parser.services.embedding_service.run_topic_embedding", new=AsyncMock(return_value={
            "embedded_count": 0, "skipped_count": 0, "total_count": 0,
        })) as mock_topic_emb:
            from tg_parser.services.pipeline_service import run_full_pipeline
            await run_full_pipeline(
                source_id="src1", output_dir="/tmp/test", skip_topicize=True,
            )
            mock_topic_emb.assert_not_awaited()


class TestBackgroundSchedulerEdge:
    async def test_topic_embedding_failure_continues_next_source(self):
        from tg_parser.storage.ports import Source

        src1 = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
        src2 = Source(source_id="s2", channel_id="ch2", status="active", include_comments=False)

        mock_state_repo = AsyncMock()
        mock_state_repo.list_sources = AsyncMock(return_value=[src1, src2])
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_state_repo, Mock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        call_log = []

        async def track_run_emb(**kw):
            call_log.append(("emb", kw["channel_id"]))
            return {"embedded_count": 0}

        async def track_topic_emb(**kw):
            call_log.append(("topic", kw["channel_id"]))
            if kw["channel_id"] == "ch1":
                raise RuntimeError("fail ch1")
            return {"embedded_count": 1}

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            return_value=mock_cm,
        ), patch(
            "tg_parser.services.embedding_service.run_embedding",
            side_effect=track_run_emb,
        ), patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            side_effect=track_topic_emb,
        ):
            from tg_parser.services.background_scheduler import _incremental_embedding_task
            await _incremental_embedding_task()

        assert ("emb", "ch1") in call_log
        assert ("topic", "ch1") in call_log
        assert ("emb", "ch2") in call_log
        assert ("topic", "ch2") in call_log


# ---------------------------------------------------------------------------
# 12. Additional coverage: db_context, _ensure_embedding_columns
# ---------------------------------------------------------------------------

class TestEnsureEmbeddingColumns:
    async def test_ensure_adds_columns_when_missing(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            _ensure_embedding_columns,
        )

        mock_engine = AsyncMock()
        mock_conn = AsyncMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            ("source_ref",), ("embedding",), ("model",), ("created_at",), ("metadata_json",),
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin = Mock(return_value=mock_cm)

        await _ensure_embedding_columns(mock_engine)

        sql_strs = [str(call[0][0].text) for call in mock_conn.execute.call_args_list]
        alter_strs = [s for s in sql_strs if "ALTER TABLE" in s or "ADD COLUMN" in s]
        assert any("entry_type" in s for s in alter_strs)
        assert any("topic_id" in s for s in alter_strs)

    async def test_ensure_skips_when_columns_exist(self):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            _ensure_embedding_columns,
        )

        mock_engine = AsyncMock()
        mock_conn = AsyncMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            ("source_ref",), ("embedding",), ("model",), ("created_at",),
            ("metadata_json",), ("entry_type",), ("topic_id",), ("channel_ids",),
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin = Mock(return_value=mock_cm)

        await _ensure_embedding_columns(mock_engine)

        sql_strs = [str(call[0][0].text) for call in mock_conn.execute.call_args_list]
        add_col_strs = [s for s in sql_strs if "ADD COLUMN" in s]
        assert len(add_col_strs) == 0


class TestTopicEmbeddingReposContext:
    async def test_topic_embedding_repos_yields_correct_types(self):
        from tg_parser.storage.sqlalchemy import Database
        from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
        from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

        mock_db = AsyncMock(spec=Database)
        mock_session = AsyncMock()
        mock_db.processing_storage_session = Mock(return_value=mock_session)

        with patch("tg_parser.services.db_context._get_db", new=AsyncMock(return_value=mock_db)):
            from tg_parser.services.db_context import topic_embedding_repos
            async with topic_embedding_repos() as (emb_repo, tc_repo, db):
                assert isinstance(emb_repo, SAEmbeddingRepo)
                assert isinstance(tc_repo, SATopicCardRepo)

        mock_session.close.assert_awaited_once()
