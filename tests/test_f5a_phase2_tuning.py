"""
Tests for F5-A Phase 2: Relevance tuning & topic-weighted RAG context.

Structure (Commit 1 — quotas + min_rank pipeline):
- TestSettingsPhase2       : Pydantic settings (fts_min_rank, rag_topic_quota,
                             rag_search_overfetch_factor).
- TestApplyTypeQuotas      : pure unit tests for _apply_type_quotas (no DB).
- TestFtsMinRankPipeline   : fts_min_rank forwarded to emb_repo.keyword_search.
- TestAnswerQuotas         : answer() overfetch + quota application (mocked search).

Structure (Commit 2 — structured context + MCP mode passthrough):
- TestStructuredContext    : new _build_context two-section format.
- TestMcpModePassthrough   : MCP tools accept mode= and forward to service.
- TestRagPromptV12         : prompts/rag.yaml v1.2.0 metadata.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from tg_parser.domain.models import Anchor, ProcessedDocument, TopicCard, TopicType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    source_ref: str = "tg:ch1:post:1",
    channel_id: str = "ch1",
    text_clean: str = "Message body",
    summary: str | None = "Msg summary",
    topics: list[str] | None = None,
) -> ProcessedDocument:
    return ProcessedDocument(
        id=source_ref,
        source_ref=source_ref,
        source_message_id=source_ref.rsplit(":", 1)[-1],
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=text_clean,
        summary=summary,
        topics=topics or [],
    )


def _make_topic_card(
    topic_id: str = "topic:ch1:post:1",
    title: str = "Topic Title",
    summary: str = "Topic summary",
    scope_in: list[str] | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary=summary,
        scope_in=scope_in or ["anchor_a", "anchor_b"],
        scope_out=["excluded"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=(sources or ["ch1"])[0],
                message_id="1",
                message_type="post",
                anchor_ref="tg:ch1:post:1",
                score=1.0,
            )
        ],
        sources=sources or ["ch1"],
        updated_at=datetime.now(UTC),
        tags=tags,
    )


def _msg_result(
    source_ref: str = "tg:ch1:post:1",
    score: float = 0.9,
    channel_id: str = "ch1",
    topics: list[str] | None = None,
):
    from tg_parser.services.retrieval_service import SearchResult

    return SearchResult(
        source_ref=source_ref,
        score=score,
        document=_make_doc(source_ref=source_ref, channel_id=channel_id, topics=topics),
        entry_type="message",
    )


def _topic_result(
    topic_id: str = "topic:ch1:post:1",
    score: float = 0.85,
    title: str = "T",
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    scope_in: list[str] | None = None,
):
    from tg_parser.services.retrieval_service import SearchResult

    return SearchResult(
        source_ref=topic_id,
        score=score,
        entry_type="topic",
        topic_card=_make_topic_card(
            topic_id=topic_id, title=title, sources=sources, tags=tags, scope_in=scope_in
        ),
    )


class _FakeEmbClient:
    async def embed(self, texts):
        return [[0.1] * 1536 for _ in texts]

    async def close(self):
        return None


@pytest.fixture
def patch_embedding_client(monkeypatch):
    def _factory():
        return _FakeEmbClient()

    monkeypatch.setattr(
        "tg_parser.services.retrieval_service.create_embedding_client",
        _factory,
    )


# ===========================================================================
# Commit 1 — Settings + Quotas + FTS min_rank pipeline + answer() wiring
# ===========================================================================


# ---------------------------------------------------------------------------
# TestSettingsPhase2
# ---------------------------------------------------------------------------


class TestSettingsPhase2:
    def test_defaults(self):
        from tg_parser.config.settings import Settings

        s = Settings(
            telegram_api_id=1,
            telegram_api_hash="h",
            telegram_phone="+1",
            openai_api_key="sk-x",
        )
        assert s.fts_min_rank == 0.0
        assert s.rag_topic_quota == 2
        assert s.rag_search_overfetch_factor == 2

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("FTS_MIN_RANK", "0.05")
        monkeypatch.setenv("RAG_TOPIC_QUOTA", "4")
        monkeypatch.setenv("RAG_SEARCH_OVERFETCH_FACTOR", "3")

        from tg_parser.config.settings import Settings

        s = Settings(
            telegram_api_id=1,
            telegram_api_hash="h",
            telegram_phone="+1",
            openai_api_key="sk-x",
        )
        assert s.fts_min_rank == pytest.approx(0.05)
        assert s.rag_topic_quota == 4
        assert s.rag_search_overfetch_factor == 3

    def test_rejects_negative_fts_min_rank(self):
        from pydantic import ValidationError

        from tg_parser.config.settings import Settings

        with pytest.raises(ValidationError):
            Settings(
                telegram_api_id=1,
                telegram_api_hash="h",
                telegram_phone="+1",
                openai_api_key="sk-x",
                fts_min_rank=-0.1,
            )

    def test_rejects_negative_topic_quota(self):
        from pydantic import ValidationError

        from tg_parser.config.settings import Settings

        with pytest.raises(ValidationError):
            Settings(
                telegram_api_id=1,
                telegram_api_hash="h",
                telegram_phone="+1",
                openai_api_key="sk-x",
                rag_topic_quota=-1,
            )

    def test_rejects_zero_overfetch_factor(self):
        from pydantic import ValidationError

        from tg_parser.config.settings import Settings

        with pytest.raises(ValidationError):
            Settings(
                telegram_api_id=1,
                telegram_api_hash="h",
                telegram_phone="+1",
                openai_api_key="sk-x",
                rag_search_overfetch_factor=0,
            )


# ---------------------------------------------------------------------------
# TestApplyTypeQuotas  (pure function, no DB, no mocks)
# ---------------------------------------------------------------------------


class TestApplyTypeQuotas:
    def test_empty_results_returns_empty(self):
        from tg_parser.services.retrieval_service import _apply_type_quotas

        assert _apply_type_quotas([], limit=5, topic_quota=2) == []

    def test_topics_within_quota_fill_exact(self):
        from tg_parser.services.retrieval_service import _apply_type_quotas

        t1 = _topic_result(topic_id="topic:1", score=0.9)
        t2 = _topic_result(topic_id="topic:2", score=0.8)
        m1 = _msg_result(source_ref="tg:ch1:post:1", score=0.7)
        m2 = _msg_result(source_ref="tg:ch1:post:2", score=0.6)
        m3 = _msg_result(source_ref="tg:ch1:post:3", score=0.5)

        got = _apply_type_quotas([t1, t2, m1, m2, m3], limit=5, topic_quota=2)

        assert [r.source_ref for r in got] == [
            "topic:1",
            "topic:2",
            "tg:ch1:post:1",
            "tg:ch1:post:2",
            "tg:ch1:post:3",
        ]

    def test_messages_fill_remainder(self):
        from tg_parser.services.retrieval_service import _apply_type_quotas

        t1 = _topic_result(topic_id="topic:1", score=0.9)
        t2 = _topic_result(topic_id="topic:2", score=0.8)
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5 - i * 0.01) for i in range(10)]

        got = _apply_type_quotas([t1, t2, *msgs], limit=5, topic_quota=2)

        assert len(got) == 5
        assert [r.entry_type for r in got] == ["topic", "topic", "message", "message", "message"]

    def test_topic_underflow_backfills_with_messages(self):
        """Only 1 topic exists, quota is 2; pick 1 topic + fill with messages to limit."""
        from tg_parser.services.retrieval_service import _apply_type_quotas

        t1 = _topic_result(topic_id="topic:1", score=0.9)
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5 - i * 0.01) for i in range(5)]

        got = _apply_type_quotas([t1, *msgs], limit=5, topic_quota=2)

        assert len(got) == 5
        assert sum(1 for r in got if r.entry_type == "topic") == 1
        assert sum(1 for r in got if r.entry_type == "message") == 4

    def test_message_underflow_backfills_with_topics(self):
        """Zero messages, many topics; topic_quota=2 but limit=5 → backfill with extra topics."""
        from tg_parser.services.retrieval_service import _apply_type_quotas

        topics = [_topic_result(topic_id=f"topic:{i}", score=0.9 - i * 0.01) for i in range(6)]

        got = _apply_type_quotas(topics, limit=5, topic_quota=2)

        assert len(got) == 5
        assert all(r.entry_type == "topic" for r in got)
        assert [r.source_ref for r in got] == [f"topic:{i}" for i in range(5)]

    def test_both_types_sparse_returns_all_available(self):
        from tg_parser.services.retrieval_service import _apply_type_quotas

        t1 = _topic_result(topic_id="topic:1", score=0.9)
        m1 = _msg_result(source_ref="tg:ch1:post:1", score=0.7)

        got = _apply_type_quotas([t1, m1], limit=5, topic_quota=2)

        assert len(got) == 2
        assert got[0].source_ref == "topic:1"
        assert got[1].source_ref == "tg:ch1:post:1"

    def test_topic_quota_zero_returns_only_messages(self):
        from tg_parser.services.retrieval_service import _apply_type_quotas

        topics = [_topic_result(topic_id=f"topic:{i}", score=0.9) for i in range(3)]
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5) for i in range(4)]

        got = _apply_type_quotas([*topics, *msgs], limit=3, topic_quota=0)

        assert all(r.entry_type == "message" for r in got)
        assert len(got) == 3

    def test_topic_quota_equals_limit_returns_only_topics(self):
        """topic_quota==limit and enough topics present → messages ignored."""
        from tg_parser.services.retrieval_service import _apply_type_quotas

        topics = [_topic_result(topic_id=f"topic:{i}", score=0.9) for i in range(5)]
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5) for i in range(3)]

        got = _apply_type_quotas([*topics, *msgs], limit=3, topic_quota=3)

        assert len(got) == 3
        assert all(r.entry_type == "topic" for r in got)

    def test_order_within_type_preserved(self):
        from tg_parser.services.retrieval_service import _apply_type_quotas

        t_hi = _topic_result(topic_id="topic:hi", score=0.95)
        t_lo = _topic_result(topic_id="topic:lo", score=0.40)
        m_hi = _msg_result(source_ref="tg:ch1:post:hi", score=0.80)
        m_lo = _msg_result(source_ref="tg:ch1:post:lo", score=0.20)

        got = _apply_type_quotas([t_hi, m_hi, t_lo, m_lo], limit=4, topic_quota=2)

        assert [r.source_ref for r in got] == [
            "topic:hi",
            "topic:lo",
            "tg:ch1:post:hi",
            "tg:ch1:post:lo",
        ]


# ---------------------------------------------------------------------------
# TestFtsMinRankPipeline  (service → repo.keyword_search(min_rank=...))
# ---------------------------------------------------------------------------


class TestFtsMinRankPipeline:
    async def test_keyword_mode_uses_settings_default_min_rank(
        self, patch_embedding_client, monkeypatch
    ):
        """search(mode='keyword') forwards settings.fts_min_rank to repo by default."""
        from tg_parser.services import retrieval_service
        from tg_parser.services.retrieval_service import search

        monkeypatch.setattr(retrieval_service.settings, "fts_min_rank", 0.01)

        emb_repo = AsyncMock()
        emb_repo.keyword_search = AsyncMock(return_value=[])
        emb_repo.similarity_search = AsyncMock(return_value=[])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        await search(
            "q",
            mode="keyword",
            emb_repo=emb_repo,
            proc_repo=proc_repo,
            topic_card_repo=AsyncMock(),
        )
        assert emb_repo.keyword_search.call_args.kwargs["min_rank"] == pytest.approx(0.01)

    async def test_explicit_fts_min_rank_overrides_settings(
        self, patch_embedding_client, monkeypatch
    ):
        from tg_parser.services import retrieval_service
        from tg_parser.services.retrieval_service import search

        monkeypatch.setattr(retrieval_service.settings, "fts_min_rank", 0.01)

        emb_repo = AsyncMock()
        emb_repo.keyword_search = AsyncMock(return_value=[])
        emb_repo.similarity_search = AsyncMock(return_value=[])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        await search(
            "q",
            mode="hybrid",
            fts_min_rank=0.07,
            emb_repo=emb_repo,
            proc_repo=proc_repo,
            topic_card_repo=AsyncMock(),
        )
        assert emb_repo.keyword_search.call_args.kwargs["min_rank"] == pytest.approx(0.07)
        assert "min_rank" not in emb_repo.similarity_search.call_args.kwargs

    async def test_semantic_mode_does_not_forward_fts_min_rank(
        self, patch_embedding_client, monkeypatch
    ):
        from tg_parser.services import retrieval_service
        from tg_parser.services.retrieval_service import search

        monkeypatch.setattr(retrieval_service.settings, "fts_min_rank", 0.01)

        emb_repo = AsyncMock()
        emb_repo.keyword_search = AsyncMock(return_value=[])
        emb_repo.similarity_search = AsyncMock(return_value=[])
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={})

        await search(
            "q",
            mode="semantic",
            fts_min_rank=0.9,
            emb_repo=emb_repo,
            proc_repo=proc_repo,
            topic_card_repo=AsyncMock(),
        )
        assert not emb_repo.keyword_search.called


# ---------------------------------------------------------------------------
# TestAnswerQuotas  (answer() overfetch + quota application, mocked search)
# ---------------------------------------------------------------------------


class TestAnswerQuotas:
    async def test_answer_default_topic_quota_is_2(self, patch_embedding_client, monkeypatch):
        """answer() without explicit topic_quota uses settings.rag_topic_quota (default 2)."""
        from tg_parser.services import retrieval_service

        monkeypatch.setattr(retrieval_service.settings, "rag_topic_quota", 2)
        monkeypatch.setattr(retrieval_service.settings, "rag_search_overfetch_factor", 2)

        topics = [_topic_result(topic_id=f"topic:{i}", score=0.9 - i * 0.01) for i in range(3)]
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5) for i in range(5)]

        captured: dict = {}

        async def _fake_search(query, **kwargs):
            captured["limit"] = kwargs.get("limit")
            return [*topics, *msgs]

        monkeypatch.setattr(retrieval_service, "search", _fake_search)

        async def _fake_call_llm(*args, **kwargs):
            return ("answer", "test-model")

        monkeypatch.setattr(retrieval_service, "_call_llm", _fake_call_llm)

        result = await retrieval_service.answer(
            "q?",
            limit=5,
            emb_repo=AsyncMock(),
            proc_repo=AsyncMock(),
        )

        assert sum(1 for r in result.sources if r.entry_type == "topic") == 2
        assert sum(1 for r in result.sources if r.entry_type == "message") == 3
        assert len(result.sources) == 5

    async def test_explicit_topic_quota_overrides_settings(
        self, patch_embedding_client, monkeypatch
    ):
        from tg_parser.services import retrieval_service

        monkeypatch.setattr(retrieval_service.settings, "rag_topic_quota", 2)
        monkeypatch.setattr(retrieval_service.settings, "rag_search_overfetch_factor", 2)

        topics = [_topic_result(topic_id=f"topic:{i}", score=0.9 - i * 0.01) for i in range(5)]
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5) for i in range(5)]

        async def _fake_search(query, **kwargs):
            return [*topics, *msgs]

        monkeypatch.setattr(retrieval_service, "search", _fake_search)

        async def _fake_call_llm(*args, **kwargs):
            return ("answer", "test-model")

        monkeypatch.setattr(retrieval_service, "_call_llm", _fake_call_llm)

        result = await retrieval_service.answer(
            "q?",
            limit=5,
            topic_quota=4,
            emb_repo=AsyncMock(),
            proc_repo=AsyncMock(),
        )

        assert sum(1 for r in result.sources if r.entry_type == "topic") == 4
        assert sum(1 for r in result.sources if r.entry_type == "message") == 1
        assert len(result.sources) == 5

    async def test_answer_overfetches_for_quota_headroom(self, patch_embedding_client, monkeypatch):
        """answer() must call search(limit=limit * overfetch_factor) for headroom."""
        from tg_parser.services import retrieval_service

        monkeypatch.setattr(retrieval_service.settings, "rag_topic_quota", 2)
        monkeypatch.setattr(retrieval_service.settings, "rag_search_overfetch_factor", 3)

        captured: dict = {}

        async def _fake_search(query, **kwargs):
            captured["limit"] = kwargs.get("limit")
            return []

        monkeypatch.setattr(retrieval_service, "search", _fake_search)

        await retrieval_service.answer(
            "q?",
            limit=5,
            emb_repo=AsyncMock(),
            proc_repo=AsyncMock(),
        )
        assert captured["limit"] == 15

    async def test_answer_returns_at_most_limit_sources_after_quotas(
        self, patch_embedding_client, monkeypatch
    ):
        from tg_parser.services import retrieval_service

        monkeypatch.setattr(retrieval_service.settings, "rag_topic_quota", 2)
        monkeypatch.setattr(retrieval_service.settings, "rag_search_overfetch_factor", 4)

        topics = [_topic_result(topic_id=f"topic:{i}", score=0.9) for i in range(10)]
        msgs = [_msg_result(source_ref=f"tg:ch1:post:{i}", score=0.5) for i in range(20)]

        async def _fake_search(query, **kwargs):
            return [*topics, *msgs]

        monkeypatch.setattr(retrieval_service, "search", _fake_search)

        async def _fake_call_llm(*args, **kwargs):
            return ("answer", "test-model")

        monkeypatch.setattr(retrieval_service, "_call_llm", _fake_call_llm)

        result = await retrieval_service.answer(
            "q?",
            limit=3,
            emb_repo=AsyncMock(),
            proc_repo=AsyncMock(),
        )
        assert len(result.sources) <= 3

    async def test_answer_empty_results_returns_no_results_message(
        self, patch_embedding_client, monkeypatch
    ):
        from tg_parser.services import retrieval_service

        async def _fake_search(query, **kwargs):
            return []

        monkeypatch.setattr(retrieval_service, "search", _fake_search)

        result = await retrieval_service.answer(
            "q?",
            limit=5,
            emb_repo=AsyncMock(),
            proc_repo=AsyncMock(),
        )
        assert result.sources == []
        assert result.answer  # non-empty "no results" message


# ===========================================================================
# Commit 2 — Structured context + MCP mode passthrough + rag.yaml v1.2.0
# ===========================================================================

# (Added in Commit 2 — see plan §2.5)

# Placeholder to keep single-file organization explicit; actual classes
# (TestStructuredContext, TestMcpModePassthrough, TestRagPromptV12) will be
# appended in Commit 2 of the Phase 2 work.


# Marker to ensure both commits share a consistent module header
_PHASE2_TEST_MODULE_VERSION = "commit1"
