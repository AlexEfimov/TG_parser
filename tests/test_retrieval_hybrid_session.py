"""
Regression tests for DI-15: SQLAlchemy IllegalStateChangeError in hybrid search.

Root cause (pre-fix): `retrieval_service.search()` called
`asyncio.gather(sem_task, kw_task)` with both tasks bound to the same
`AsyncSession` (via the single `embedding_repos()` context). SQLAlchemy
AsyncSession forbids concurrent operations on a shared session — the two
parallel calls raced on `_connection_for_bind()` and surfaced as
`IllegalStateChangeError` at session-close time.

Fix: hybrid mode now opens TWO independent `embedding_repos()` contexts so
the parallel branches each have their own session.

These tests require a real PostgreSQL with pgvector — they reproduce the
bug at the SQLAlchemy session-state level which mocks cannot capture.
"""

import asyncio
import math
import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from tg_parser.config.settings import Settings
from tg_parser.domain.ids import make_processed_document_id, make_source_ref
from tg_parser.domain.models import ProcessedDocument
from tg_parser.storage.sqlalchemy import (
    Database,
    SAEmbeddingRepo,
    SAProcessedDocumentRepo,
    init_processing_storage_schema,
)


def _fake_embedding(dim: int = 1536, seed: float = 0.1) -> list[float]:
    """Deterministic fake 1536-d embedding (matches default embedding_dimension)."""
    return [math.sin(seed * (i + 1)) for i in range(dim)]


async def _pgvector_available(engine) -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except Exception:
        return False


@pytest.fixture
async def hybrid_seed_db():
    """
    Real PostgreSQL DB seeded with 2 processed_documents + 2 message embeddings
    on a shared channel. Used to verify hybrid search runs without
    IllegalStateChangeError under both single-call and concurrent-call patterns.
    """
    s = Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=os.environ.get("DB_NAME", "tg_parser_test"),
        db_user=os.environ.get("DB_USER", "tg_parser_user"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_pool_size=4,
        db_max_overflow=4,
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
        openai_api_key="sk-test-key",
    )

    Database.reset_instance()
    db = Database.get_instance(s)
    await db.init()

    if not await _pgvector_available(db.processing_storage_engine):
        await db.close()
        Database.reset_instance()
        pytest.skip("pgvector extension not available in PostgreSQL")

    await init_processing_storage_schema(db.processing_storage_engine)

    channel_id = "di15_test_ch"

    async with db.processing_storage_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM document_embeddings WHERE source_ref LIKE :pattern"),
            {"pattern": f"tg:{channel_id}:%"},
        )
        await conn.execute(
            text("DELETE FROM processed_documents WHERE channel_id = :ch"),
            {"ch": channel_id},
        )

    docs = []
    for idx, (text_clean, summary) in enumerate(
        [
            ("Анализ крови показывает уровень гемоглобина в норме", "Гемоглобин"),
            ("Генетика наследственных заболеваний и риски", "Генетика"),
        ],
        start=1,
    ):
        ref = make_source_ref(channel_id, "post", str(700 + idx))
        session = db.processing_storage_session()
        try:
            proc_repo = SAProcessedDocumentRepo(session)
            doc = ProcessedDocument(
                id=make_processed_document_id(ref),
                source_ref=ref,
                source_message_id=str(700 + idx),
                channel_id=channel_id,
                processed_at=datetime(2025, 12, 14, 12, idx, 0),
                text_clean=text_clean,
                summary=summary,
            )
            await proc_repo.upsert(doc)
            docs.append(doc)
        finally:
            await session.close()

    session = db.processing_storage_session()
    try:
        emb_repo = SAEmbeddingRepo(session)
        for idx, doc in enumerate(docs, start=1):
            await emb_repo.save(
                source_ref=doc.source_ref,
                embedding=_fake_embedding(seed=float(idx)),
                model="test-model",
                metadata={"tokens": 10},
                entry_type="message",
                channel_ids=[channel_id],
            )
    finally:
        await session.close()

    yield db, channel_id

    async with db.processing_storage_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM document_embeddings WHERE source_ref LIKE :pattern"),
            {"pattern": f"tg:{channel_id}:%"},
        )
        await conn.execute(
            text("DELETE FROM processed_documents WHERE channel_id = :ch"),
            {"ch": channel_id},
        )

    await db.close()
    Database.reset_instance()


def _patched_embedding_client():
    """Mock create_embedding_client() to skip real OpenAI calls."""
    mock_client = AsyncMock()
    mock_client.embed = AsyncMock(return_value=[_fake_embedding(seed=1.0)])
    mock_client.close = AsyncMock()
    return patch(
        "tg_parser.services.retrieval_service.create_embedding_client",
        return_value=mock_client,
    )


class TestHybridSessionSafety:
    """DI-15 regression: hybrid search must not raise IllegalStateChangeError."""

    async def test_semantic_mode_works(self, hybrid_seed_db):
        """Baseline: semantic-only path (no concurrency) should always work."""
        from tg_parser.services.retrieval_service import search

        _db, channel_id = hybrid_seed_db
        with _patched_embedding_client():
            results = await search(
                query="генетика",
                channel_id=channel_id,
                limit=5,
                mode="semantic",
                include_topics=False,
            )

        assert isinstance(results, list)
        assert len(results) >= 1, "Expected at least 1 semantic match from seeded data"

    async def test_keyword_mode_works(self, hybrid_seed_db):
        """Baseline: keyword-only path (no concurrency, no embedding call)."""
        from tg_parser.services.retrieval_service import search

        _db, channel_id = hybrid_seed_db
        results = await search(
            query="гемоглобин",
            channel_id=channel_id,
            limit=5,
            mode="keyword",
            include_topics=False,
        )

        assert isinstance(results, list)
        assert len(results) >= 1, "Expected at least 1 keyword match from seeded data"

    async def test_hybrid_mode_no_session_error(self, hybrid_seed_db):
        """
        DI-15 regression: hybrid mode must NOT raise IllegalStateChangeError.

        Pre-fix this raised:
            sqlalchemy.exc.IllegalStateChangeError: Method 'close()' can't be
            called here; method '_connection_for_bind()' is already in progress
        """
        from tg_parser.services.retrieval_service import search

        _db, channel_id = hybrid_seed_db
        with _patched_embedding_client():
            results = await search(
                query="генетика анализ",
                channel_id=channel_id,
                limit=5,
                mode="hybrid",
                include_topics=False,
            )

        assert isinstance(results, list)
        assert len(results) >= 1, "Expected hybrid search to fuse semantic+keyword hits"

    async def test_hybrid_mode_concurrent_calls(self, hybrid_seed_db):
        """
        Stress: 3 hybrid searches in parallel must all complete without
        session-state corruption. Verifies pool sizing + that each call
        owns its own pair of sessions (no shared global state).
        """
        from tg_parser.services.retrieval_service import search

        _db, channel_id = hybrid_seed_db
        with _patched_embedding_client():
            results = await asyncio.gather(
                search(
                    query="генетика",
                    channel_id=channel_id,
                    limit=3,
                    mode="hybrid",
                    include_topics=False,
                ),
                search(
                    query="гемоглобин",
                    channel_id=channel_id,
                    limit=3,
                    mode="hybrid",
                    include_topics=False,
                ),
                search(
                    query="анализ",
                    channel_id=channel_id,
                    limit=3,
                    mode="hybrid",
                    include_topics=False,
                ),
            )

        assert len(results) == 3
        for r in results:
            assert isinstance(r, list)

    async def test_hybrid_di_raises_value_error(self, hybrid_seed_db):
        """
        Guard: hybrid + DI(emb_repo/proc_repo) is unsupported (would force
        shared session) → must raise ValueError, not IllegalStateChangeError.
        """
        from tg_parser.services.db_context import embedding_repos
        from tg_parser.services.retrieval_service import search

        async with embedding_repos() as (emb_repo, proc_repo, _db):
            with _patched_embedding_client(), pytest.raises(ValueError, match="Hybrid mode"):
                await search(
                    query="test",
                    limit=3,
                    mode="hybrid",
                    emb_repo=emb_repo,
                    proc_repo=proc_repo,
                )
