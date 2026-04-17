"""
Tests for P5 RAG: embedding repo, embedding service, retrieval service.

Covers:
- EmbeddingRepo CRUD and similarity search
- EmbeddingService batch embedding with mocked OpenAI
- RetrievalService search and Q&A with mocked LLM
"""

import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.config.settings import Settings
from tg_parser.domain.ids import make_processed_document_id, make_source_ref
from tg_parser.domain.models import ProcessedDocument
from tg_parser.storage.sqlalchemy import (
    Database,
    SAEmbeddingRepo,
    SAProcessedDocumentRepo,
    init_processing_storage_schema,
)


def _make_fake_embedding(dim: int = 1536, seed: float = 0.1) -> list[float]:
    """Create a deterministic fake embedding vector."""
    import math

    return [math.sin(seed * (i + 1)) for i in range(dim)]


async def _pgvector_available(engine) -> bool:
    """Check if pgvector extension can be created/exists."""
    from sqlalchemy import text

    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except Exception:
        return False


requires_pgvector = pytest.mark.skipif(
    os.environ.get("SKIP_PGVECTOR_TESTS", "0") == "1",
    reason="pgvector extension not available",
)


@pytest.fixture
async def rag_db():
    """Create a test DB with pgvector extension + clean tables for RAG tests.

    Skips the entire test if pgvector extension is unavailable.
    """
    from sqlalchemy import text

    s = Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name="tg_parser_test",
        db_user=os.environ.get("DB_USER", "tg_parser_user"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_pool_size=2,
        db_max_overflow=3,
    )

    db = Database.from_settings(s)
    await db.init()

    if not await _pgvector_available(db.processing_storage_engine):
        await db.close()
        pytest.skip("pgvector extension not available in PostgreSQL")

    await init_processing_storage_schema(db.processing_storage_engine)

    async with db.processing_storage_engine.begin() as conn:
        await conn.execute(text("DELETE FROM document_embeddings"))
        await conn.execute(text("DELETE FROM processed_documents"))

    yield db

    await db.close()


async def _insert_processed_doc(
    db: Database,
    source_ref: str,
    channel_id: str = "test_ch",
    text_clean: str = "Test text",
    summary: str | None = None,
) -> ProcessedDocument:
    """Helper: insert a processed document."""
    session = db.processing_storage_session()
    repo = SAProcessedDocumentRepo(session)
    doc = ProcessedDocument(
        id=make_processed_document_id(source_ref),
        source_ref=source_ref,
        source_message_id=source_ref.split(":")[-1],
        channel_id=channel_id,
        processed_at=datetime(2025, 12, 14, 12, 0, 0),
        text_clean=text_clean,
        summary=summary,
    )
    await repo.upsert(doc)
    await session.close()
    return doc


# ============================================================================
# EmbeddingRepo Tests
# ============================================================================


class TestEmbeddingRepo:
    """Unit / integration tests for SAEmbeddingRepo."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, rag_db):
        """Save an embedding and retrieve it by source_ref."""
        source_ref = make_source_ref("test_ch", "post", "100")
        await _insert_processed_doc(rag_db, source_ref)

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)

        emb = _make_fake_embedding(seed=0.5)
        await repo.save(source_ref, emb, "test-model", {"tokens": 42})

        result = await repo.get_by_source_ref(source_ref)
        assert result is not None
        assert result.source_ref == source_ref
        assert result.model == "test-model"
        assert len(result.embedding) == 1536
        assert abs(result.embedding[0] - emb[0]) < 1e-4

        await session.close()

    @pytest.mark.asyncio
    async def test_save_upsert(self, rag_db):
        """Upsert overwrites existing embedding."""
        source_ref = make_source_ref("test_ch", "post", "101")
        await _insert_processed_doc(rag_db, source_ref)

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)

        await repo.save(source_ref, _make_fake_embedding(seed=1.0), "model-v1")
        await repo.save(source_ref, _make_fake_embedding(seed=2.0), "model-v2")

        result = await repo.get_by_source_ref(source_ref)
        assert result is not None
        assert result.model == "model-v2"

        await session.close()

    @pytest.mark.asyncio
    async def test_count(self, rag_db):
        """Count returns total embeddings."""
        for i in range(3):
            ref = make_source_ref("test_ch", "post", str(200 + i))
            await _insert_processed_doc(rag_db, ref)
            session = rag_db.processing_storage_session()
            repo = SAEmbeddingRepo(session)
            await repo.save(ref, _make_fake_embedding(seed=float(i)), "model")
            await session.close()

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)
        count = await repo.count()
        assert count >= 3
        await session.close()

    @pytest.mark.asyncio
    async def test_list_missing(self, rag_db):
        """list_missing returns source_refs without embeddings."""
        ref1 = make_source_ref("test_ch", "post", "300")
        ref2 = make_source_ref("test_ch", "post", "301")
        ref3 = make_source_ref("test_ch", "post", "302")

        await _insert_processed_doc(rag_db, ref1)
        await _insert_processed_doc(rag_db, ref2)
        await _insert_processed_doc(rag_db, ref3)

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)
        await repo.save(ref1, _make_fake_embedding(seed=1.0), "model")

        missing = await repo.list_missing("test_ch")
        assert ref2 in missing
        assert ref3 in missing
        assert ref1 not in missing
        await session.close()

    @pytest.mark.asyncio
    async def test_similarity_search(self, rag_db):
        """Similarity search returns ranked results."""
        refs = []
        for i in range(5):
            ref = make_source_ref("test_ch", "post", str(400 + i))
            await _insert_processed_doc(rag_db, ref)
            refs.append(ref)

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)

        for i, ref in enumerate(refs):
            await repo.save(ref, _make_fake_embedding(seed=float(i + 1)), "model")

        query_vec = _make_fake_embedding(seed=1.0)
        results = await repo.similarity_search(query_vec, limit=3)

        assert len(results) <= 3
        assert results[0].score >= results[-1].score
        assert results[0].source_ref == refs[0]

        await session.close()

    @pytest.mark.asyncio
    async def test_save_batch(self, rag_db):
        """save_batch inserts multiple embeddings at once."""
        items = []
        for i in range(5):
            ref = make_source_ref("test_ch", "post", str(500 + i))
            await _insert_processed_doc(rag_db, ref)
            items.append((ref, _make_fake_embedding(seed=float(i)), "model", None))

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)
        saved = await repo.save_batch(items)
        assert saved == 5

        count = await repo.count()
        assert count >= 5
        await session.close()

    @pytest.mark.asyncio
    async def test_similarity_search_with_threshold(self, rag_db):
        """Threshold filters out low-score results."""
        ref = make_source_ref("test_ch", "post", "600")
        await _insert_processed_doc(rag_db, ref)

        session = rag_db.processing_storage_session()
        repo = SAEmbeddingRepo(session)
        await repo.save(ref, _make_fake_embedding(seed=1.0), "model")

        query_vec = _make_fake_embedding(seed=100.0)
        results = await repo.similarity_search(query_vec, limit=10, threshold=0.99)
        assert len(results) == 0 or all(r.score >= 0.99 for r in results)

        await session.close()


# ============================================================================
# EmbeddingService Tests (mocked OpenAI)
# ============================================================================


class TestEmbeddingService:
    """Tests for embedding_service with mocked embedding client."""

    @pytest.mark.asyncio
    async def test_prepare_text(self):
        """_prepare_text combines summary + truncated text_clean."""
        from tg_parser.services.embedding_service import _prepare_text

        result = _prepare_text("Long text here", "Summary")
        assert "Summary" in result
        assert "Long text here" in result

    @pytest.mark.asyncio
    async def test_prepare_text_no_summary(self):
        from tg_parser.services.embedding_service import _prepare_text

        result = _prepare_text("Clean text only", None)
        assert result == "Clean text only"

    @pytest.mark.asyncio
    async def test_prepare_text_truncation(self):
        from tg_parser.services.embedding_service import _prepare_text

        long_text = "x" * 1000
        result = _prepare_text(long_text, None)
        assert len(result) == 500

    @pytest.mark.asyncio
    async def test_run_embedding_no_docs(self, rag_db):
        """run_embedding with no docs returns zeros."""
        from tg_parser.services.embedding_service import run_embedding

        with patch("tg_parser.services.embedding_service.create_embedding_client") as mock_factory:
            mock_client = AsyncMock()
            mock_client.embed = AsyncMock(return_value=[])
            mock_client.close = AsyncMock()
            mock_factory.return_value = mock_client

            with patch("tg_parser.services.embedding_service.embedding_repos") as mock_repos:
                emb_repo = AsyncMock()
                proc_repo = AsyncMock()
                proc_repo.list_by_channel = AsyncMock(return_value=[])
                emb_repo.list_missing = AsyncMock(return_value=[])

                async def fake_cm():
                    yield (emb_repo, proc_repo, None)

                from contextlib import asynccontextmanager

                mock_repos.return_value = asynccontextmanager(fake_cm)()

                stats = await run_embedding("empty_channel")
                assert stats["embedded_count"] == 0
                assert stats["total_count"] == 0


# ============================================================================
# RetrievalService Tests (mocked)
# ============================================================================


class TestRetrievalService:
    """Tests for retrieval_service with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_search_result_dataclass(self):
        """SearchResult holds expected fields."""
        from tg_parser.services.retrieval_service import SearchResult

        r = SearchResult(source_ref="tg:ch:post:1", score=0.95)
        assert r.source_ref == "tg:ch:post:1"
        assert r.score == 0.95
        assert r.document is None

    @pytest.mark.asyncio
    async def test_answer_result_dataclass(self):
        """AnswerResult holds answer + sources."""
        from tg_parser.services.retrieval_service import AnswerResult, SearchResult

        r = AnswerResult(
            answer="Test answer",
            sources=[SearchResult(source_ref="ref", score=0.8)],
            model="gpt-4o-mini",
        )
        assert r.answer == "Test answer"
        assert len(r.sources) == 1
        assert r.model == "gpt-4o-mini"


# ============================================================================
# Settings Tests
# ============================================================================


class TestEmbeddingSettings:
    """Tests for embedding-related settings."""

    def test_default_embedding_settings(self):
        s = Settings(
            db_host="localhost",
            db_port=5432,
            db_name="test",
            db_user="user",
            db_password="",
        )
        assert s.embedding_provider == "openai"
        assert s.embedding_model == "text-embedding-3-small"
        assert s.embedding_batch_size == 100
        assert s.embedding_dimension == 1536

    def test_custom_embedding_settings(self):
        s = Settings(
            db_host="localhost",
            db_port=5432,
            db_name="test",
            db_user="user",
            db_password="",
            embedding_model="text-embedding-3-large",
            embedding_batch_size=50,
            embedding_dimension=3072,
        )
        assert s.embedding_model == "text-embedding-3-large"
        assert s.embedding_batch_size == 50
        assert s.embedding_dimension == 3072


# ============================================================================
# API Schema Tests
# ============================================================================


class TestRAGSchemas:
    """Tests for RAG API request/response schemas."""

    def test_search_request_defaults(self):
        from tg_parser.api.routes.rag import SearchRequest

        req = SearchRequest(query="test query")
        assert req.query == "test query"
        assert req.channel_id is None
        assert req.limit == 10

    def test_search_request_with_channel(self):
        from tg_parser.api.routes.rag import SearchRequest

        req = SearchRequest(query="test", channel_id="ch1", limit=5)
        assert req.channel_id == "ch1"
        assert req.limit == 5

    def test_ask_request(self):
        from tg_parser.api.routes.rag import AskRequest

        req = AskRequest(question="What is X?")
        assert req.question == "What is X?"
        assert req.channel_id is None

    def test_search_response(self):
        from tg_parser.api.routes.rag import SearchResponse, SearchResultItem

        item = SearchResultItem(
            source_ref="tg:ch:post:1",
            score=0.9,
            summary="Test",
            text_preview="Preview text",
            channel_id="ch",
        )
        resp = SearchResponse(results=[item], query="test", total=1)
        assert resp.total == 1
        assert resp.results[0].score == 0.9

    def test_ask_response(self):
        from tg_parser.api.routes.rag import AskResponse, SearchResultItem

        resp = AskResponse(
            answer="The answer is 42",
            sources=[SearchResultItem(source_ref="ref", score=0.8)],
            model="gpt-4o-mini",
        )
        assert resp.answer == "The answer is 42"
        assert resp.model == "gpt-4o-mini"


# ============================================================================
# db_context Tests
# ============================================================================


class TestEmbeddingDbContext:
    """Tests for embedding_repos context manager."""

    @pytest.mark.asyncio
    async def test_embedding_repos_cm(self, rag_db):
        """embedding_repos() yields working repos and closes cleanly."""
        from tg_parser.services.db_context import embedding_repos

        async with embedding_repos() as (emb_repo, proc_repo, db):
            assert emb_repo is not None
            assert proc_repo is not None
            assert db is not None
            count = await emb_repo.count()
            assert isinstance(count, int)
