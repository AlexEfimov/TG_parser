"""
Tests for F5-A Phase 1: Hybrid Search (FTS + pgvector + RRF).

Commit 1 coverage:
- TestRRFFusion           : pure unit tests for rrf_fuse (no DB).
- TestKeywordSearchRepo   : SAEmbeddingRepo.keyword_search against live Postgres.
- TestMigrationIdempotency: _ensure_fts_columns and GIN-index idempotency.
"""

import os

import pytest

from tg_parser.services._ranking import rrf_fuse
from tg_parser.storage.ports import SimilarityResult


# ---------------------------------------------------------------------------
# 1. TestRRFFusion — pure unit tests for rrf_fuse
# ---------------------------------------------------------------------------


def _sim(source_ref: str, score: float = 1.0, entry_type: str = "message", topic_id: str | None = None) -> SimilarityResult:
    return SimilarityResult(
        source_ref=source_ref,
        score=score,
        entry_type=entry_type,
        topic_id=topic_id,
    )


class TestRRFFusion:
    def test_empty_inputs_return_empty(self):
        assert rrf_fuse() == []
        assert rrf_fuse([], []) == []

    def test_single_list_preserves_order(self):
        semantic = [_sim("a", 0.9), _sim("b", 0.7), _sim("c", 0.5)]
        fused = rrf_fuse(semantic)
        assert [r.source_ref for r in fused] == ["a", "b", "c"]
        k = 60
        assert fused[0].score == pytest.approx(1 / (k + 1))
        assert fused[1].score == pytest.approx(1 / (k + 2))
        assert fused[2].score == pytest.approx(1 / (k + 3))

    def test_one_list_empty_other_non_empty_does_not_crash(self):
        kw = [_sim("x"), _sim("y")]
        fused = rrf_fuse([], kw)
        assert [r.source_ref for r in fused] == ["x", "y"]

    def test_duplicates_aggregate_across_lists(self):
        semantic = [_sim("shared"), _sim("only_sem")]
        keyword = [_sim("shared"), _sim("only_kw")]
        fused = rrf_fuse(semantic, keyword)
        scores = {r.source_ref: r.score for r in fused}
        k = 60
        expected_shared = 1 / (k + 1) + 1 / (k + 1)
        expected_only_sem = 1 / (k + 2)
        expected_only_kw = 1 / (k + 2)
        assert scores["shared"] == pytest.approx(expected_shared)
        assert scores["only_sem"] == pytest.approx(expected_only_sem)
        assert scores["only_kw"] == pytest.approx(expected_only_kw)
        assert fused[0].source_ref == "shared"

    def test_rank_is_one_indexed(self):
        first = [_sim("top")]
        k = 60
        fused = rrf_fuse(first)
        assert fused[0].score == pytest.approx(1 / (k + 1))

    def test_different_k_changes_discrimination(self):
        semantic = [_sim("a"), _sim("b")]
        low_k = rrf_fuse(semantic, k=1)
        high_k = rrf_fuse(semantic, k=1000)
        gap_low = low_k[0].score - low_k[1].score
        gap_high = high_k[0].score - high_k[1].score
        assert gap_low > gap_high

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError):
            rrf_fuse([_sim("a")], k=0)

    def test_entry_type_and_topic_id_preserved_from_first_seen(self):
        semantic = [_sim("doc1", entry_type="message"),
                    _sim("topic1", entry_type="topic", topic_id="topic1")]
        keyword = [_sim("topic1", entry_type="topic", topic_id="topic1"),
                   _sim("doc1", entry_type="message")]
        fused = rrf_fuse(semantic, keyword)
        mapping = {r.source_ref: r for r in fused}
        assert mapping["doc1"].entry_type == "message"
        assert mapping["topic1"].entry_type == "topic"
        assert mapping["topic1"].topic_id == "topic1"

    def test_more_than_two_lists_supported(self):
        a = [_sim("x"), _sim("y")]
        b = [_sim("y"), _sim("z")]
        c = [_sim("z"), _sim("x")]
        fused = rrf_fuse(a, b, c)
        refs = {r.source_ref for r in fused}
        assert refs == {"x", "y", "z"}
        for result in fused:
            assert result.score > 0

    def test_stable_ordering_on_tie(self):
        a = [_sim("first"), _sim("second")]
        b = [_sim("third"), _sim("fourth")]
        fused = rrf_fuse(a, b)
        refs = [r.source_ref for r in fused]
        assert refs.index("first") < refs.index("third")
        assert refs.index("second") < refs.index("fourth")

    def test_return_type_and_score_replaces_original(self):
        semantic = [_sim("a", score=0.99)]
        fused = rrf_fuse(semantic)
        assert isinstance(fused, list)
        assert all(isinstance(r, SimilarityResult) for r in fused)
        k = 60
        assert fused[0].score == pytest.approx(1 / (k + 1))
        assert fused[0].score != 0.99


# ---------------------------------------------------------------------------
# 2. TestKeywordSearchRepo — live Postgres FTS
# ---------------------------------------------------------------------------

_SKIP_PG = not os.environ.get("TEST_POSTGRES")


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestKeywordSearchRepo:
    """FTS (ts_rank_cd) over processed_documents and topic_cards."""

    @pytest.fixture
    async def emb_repo(self, test_db):
        from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)

        session = test_db.processing_storage_session()
        try:
            yield SAEmbeddingRepo(session)
        finally:
            await session.close()

    async def _insert_processed(self, test_db, source_ref: str, channel_id: str,
                                text_clean: str, summary: str | None = None):
        from sqlalchemy import text
        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO processed_documents "
                    "(source_ref, id, source_message_id, channel_id, processed_at, "
                    " text_clean, summary, topics_json, entities_json, language, metadata_json) "
                    "VALUES (:sr, :id, :smid, :ch, :ts, :tc, :sum, '[]', '[]', 'ru', NULL) "
                    "ON CONFLICT (source_ref) DO UPDATE SET text_clean=EXCLUDED.text_clean, summary=EXCLUDED.summary"
                ),
                {"sr": source_ref, "id": source_ref, "smid": source_ref.split(":")[-1],
                 "ch": channel_id, "ts": "2026-04-17T00:00:00Z",
                 "tc": text_clean, "sum": summary},
            )

    async def _insert_topic(self, test_db, tid: str, title: str, summary: str, scope_in: str):
        from sqlalchemy import text
        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO topic_cards "
                    "(id, title, summary, scope_in_json, scope_out_json, type, anchors_json, sources_json, updated_at) "
                    "VALUES (:id, :t, :s, :si, '[]', 'singleton', '[]', '[]', :ts) "
                    "ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, summary=EXCLUDED.summary"
                ),
                {"id": tid, "t": title, "s": summary, "si": scope_in,
                 "ts": "2026-04-17T00:00:00Z"},
            )

    async def _cleanup(self, test_db):
        from sqlalchemy import text
        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_kw:%'"))
            await conn.execute(text("DELETE FROM topic_cards WHERE id LIKE 'f5a_kw_topic:%'"))

    async def test_keyword_search_on_processed_documents_ru(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_processed(test_db, "tg:f5a_kw:post:1", "f5a_kw",
                                     "Анализ крови показывает повышенный холестерин",
                                     summary="Холестерин и анализ крови")
        results = await emb_repo.keyword_search(query="холестерин", limit=10)
        refs = [r.source_ref for r in results]
        assert "tg:f5a_kw:post:1" in refs
        match = next(r for r in results if r.source_ref == "tg:f5a_kw:post:1")
        assert match.entry_type == "message"
        assert match.score > 0
        await self._cleanup(test_db)

    async def test_keyword_search_on_topic_cards(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_topic(test_db, "f5a_kw_topic:t1",
                                 title="Кардиология",
                                 summary="Сердечно-сосудистая система, давление, пульс",
                                 scope_in='["heart","pressure"]')
        results = await emb_repo.keyword_search(query="давление", limit=10)
        refs = [r.source_ref for r in results]
        assert "f5a_kw_topic:t1" in refs
        match = next(r for r in results if r.source_ref == "f5a_kw_topic:t1")
        assert match.entry_type == "topic"
        assert match.topic_id == "f5a_kw_topic:t1"
        await self._cleanup(test_db)

    async def test_keyword_search_union_returns_both_types(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_processed(test_db, "tg:f5a_kw:post:2", "f5a_kw",
                                     "кофеин влияет на давление", summary="кофе и давление")
        await self._insert_topic(test_db, "f5a_kw_topic:t2",
                                 title="Напитки и давление",
                                 summary="Кофе, чай и артериальное давление",
                                 scope_in='["coffee"]')
        results = await emb_repo.keyword_search(query="давление", limit=10)
        types = {r.entry_type for r in results}
        assert "message" in types
        assert "topic" in types
        await self._cleanup(test_db)

    async def test_keyword_search_channel_filter_scopes_messages(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_processed(test_db, "tg:f5a_kw:post:3", "f5a_kw_a",
                                     "редкоеслово_alpha важное", summary=None)
        await self._insert_processed(test_db, "tg:f5a_kw:post:4", "f5a_kw_b",
                                     "редкоеслово_alpha другое", summary=None)
        results = await emb_repo.keyword_search(
            query="редкоеслово_alpha", limit=10, channel_ids=["f5a_kw_a"]
        )
        refs = {r.source_ref for r in results if r.entry_type == "message"}
        assert "tg:f5a_kw:post:3" in refs
        assert "tg:f5a_kw:post:4" not in refs
        await self._cleanup(test_db)

    async def test_keyword_search_min_rank_cutoff(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_processed(test_db, "tg:f5a_kw:post:5", "f5a_kw",
                                     "уникальное слово_beta встречается однажды", summary=None)
        loose = await emb_repo.keyword_search(query="слово_beta", limit=10, min_rank=0.0)
        assert any(r.source_ref == "tg:f5a_kw:post:5" for r in loose)
        strict = await emb_repo.keyword_search(query="слово_beta", limit=10, min_rank=10.0)
        assert all(r.source_ref != "tg:f5a_kw:post:5" for r in strict)
        await self._cleanup(test_db)

    async def test_keyword_search_mixed_ru_en_corpus(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_processed(test_db, "tg:f5a_kw:post:6", "f5a_kw",
                                     "Machine learning pipeline for anomaly detection",
                                     summary="ML anomaly detection")
        await self._insert_processed(test_db, "tg:f5a_kw:post:7", "f5a_kw",
                                     "Обнаружение аномалий в данных с помощью машинного обучения",
                                     summary="Аномалии в данных")
        en = await emb_repo.keyword_search(query="anomaly detection", limit=10)
        ru = await emb_repo.keyword_search(query="аномалий", limit=10)
        en_refs = {r.source_ref for r in en}
        ru_refs = {r.source_ref for r in ru}
        assert "tg:f5a_kw:post:6" in en_refs
        assert "tg:f5a_kw:post:7" in ru_refs
        await self._cleanup(test_db)

    async def test_keyword_search_entry_types_filter(self, test_db, emb_repo):
        await self._cleanup(test_db)
        await self._insert_processed(test_db, "tg:f5a_kw:post:8", "f5a_kw",
                                     "редкое_gamma термин", summary=None)
        await self._insert_topic(test_db, "f5a_kw_topic:t3",
                                 title="редкое_gamma",
                                 summary="про редкое_gamma", scope_in="[]")
        only_msgs = await emb_repo.keyword_search(
            query="редкое_gamma", limit=10, entry_types=["message"]
        )
        assert all(r.entry_type == "message" for r in only_msgs)
        assert any(r.source_ref == "tg:f5a_kw:post:8" for r in only_msgs)
        only_topics = await emb_repo.keyword_search(
            query="редкое_gamma", limit=10, entry_types=["topic"]
        )
        assert all(r.entry_type == "topic" for r in only_topics)
        await self._cleanup(test_db)


# ---------------------------------------------------------------------------
# 3. TestMigrationIdempotency
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestMigrationIdempotency:
    async def test_ensure_fts_columns_is_idempotent(self, test_db):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            _ensure_fts_columns,
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)
        await _ensure_fts_columns(test_db.processing_storage_engine)
        await _ensure_fts_columns(test_db.processing_storage_engine)
        await _ensure_fts_columns(test_db.processing_storage_engine)

    async def test_fts_gin_indexes_exist(self, test_db):
        from sqlalchemy import text

        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)

        async with test_db.processing_storage_engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT indexname FROM pg_indexes "
                "WHERE indexname IN ('idx_pd_search_vector', 'idx_tc_search_vector')"
            ))
            names = {row[0] for row in result.fetchall()}
        assert "idx_pd_search_vector" in names
        assert "idx_tc_search_vector" in names

