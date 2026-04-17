"""
Tests for cross-channel incremental topicization (Session 48).

Covers:
- Settings defaults
- IncrementalTopicizeResult.cross_channel_links_created field
- build_incremental_discover_prompt with cross_channel_topics
- _load_cross_channel_topics helper
- _collect_touched_topic_ids helper
- _run_cross_channel_linking integration (mocked DB)
- discover_new_topics passes cross_channel_topics through
- run_incremental_topicization orchestrator with cross_channel=True/False/None
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


from tg_parser.domain.models import (
    Anchor,
    IncrementalTopicizeResult,
    MessageType,
    ProcessedDocument,
    TopicAssignment,
    TopicCard,
    TopicType,
)
from tg_parser.processing.topicization_prompts import build_incremental_discover_prompt
from tg_parser.services.topicization_service import (
    _collect_touched_topic_ids,
    _load_cross_channel_topics,
    _run_cross_channel_linking,
    run_incremental_topicization,
)
from tg_parser.storage.ports import DocumentEmbedding

NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


def _make_topic_card(
    topic_id: str,
    channel_id: str,
    title: str = "Test Topic",
    tags: list[str] | None = None,
    scope_in: list[str] | None = None,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary="Summary",
        scope_in=scope_in or ["генетика", "днк-тесты"],
        scope_out=["не относится"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=channel_id,
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref=f"tg:{channel_id}:post:1",
                score=1.0,
            )
        ],
        sources=[channel_id],
        updated_at=NOW,
        tags=tags,
    )


def _make_embedding(source_ref: str, vector: list[float]) -> DocumentEmbedding:
    return DocumentEmbedding(
        source_ref=source_ref,
        embedding=vector,
        model="text-embedding-3-small",
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------


class TestSettings:
    def test_cross_channel_defaults(self):
        from tg_parser.config.settings import Settings

        s = Settings(
            db_password="test",
            _env_file=None,
        )
        assert s.cross_channel_topicization is True
        assert s.cross_channel_link_threshold == 0.3

    def test_cross_channel_override(self):
        from tg_parser.config.settings import Settings

        s = Settings(
            db_password="test",
            cross_channel_topicization=False,
            cross_channel_link_threshold=0.5,
            _env_file=None,
        )
        assert s.cross_channel_topicization is False
        assert s.cross_channel_link_threshold == 0.5


# ---------------------------------------------------------------------------
# Domain model tests
# ---------------------------------------------------------------------------


class TestIncrementalTopicizeResult:
    def test_cross_channel_links_field_default(self):
        result = IncrementalTopicizeResult()
        assert result.cross_channel_links_created == 0

    def test_cross_channel_links_field_set(self):
        result = IncrementalTopicizeResult(cross_channel_links_created=5)
        assert result.cross_channel_links_created == 5


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class TestBuildIncrementalDiscoverPromptCrossChannel:
    def test_without_cross_channel_topics(self):
        prompt = build_incremental_discover_prompt(
            existing_topics=[{"id": "t:1", "title": "Topic 1", "scope_in": ["scope"]}],
            unassigned_docs=[{
                "source_ref": "tg:ch1:post:100",
                "summary": "A doc",
                "topics": [],
                "text_clean": "Some text",
            }],
        )
        assert "Topic 1" in prompt
        assert "OTHER channels" not in prompt

    def test_with_cross_channel_topics(self):
        prompt = build_incremental_discover_prompt(
            existing_topics=[{"id": "t:1", "title": "Topic 1", "scope_in": ["scope"]}],
            unassigned_docs=[{
                "source_ref": "tg:ch1:post:100",
                "summary": "A doc",
                "topics": [],
                "text_clean": "Some text",
            }],
            cross_channel_topics=[
                {"id": "t:2", "title": "Cross Topic", "scope_in": ["genetics"], "channel_id": "ch2"},
            ],
        )
        assert "Topic 1" in prompt
        assert "OTHER channels" in prompt
        assert "Cross Topic" in prompt
        assert "ch2" in prompt

    def test_empty_cross_channel_topics(self):
        prompt = build_incremental_discover_prompt(
            existing_topics=[{"id": "t:1", "title": "Topic 1", "scope_in": ["scope"]}],
            unassigned_docs=[{
                "source_ref": "tg:ch1:post:100",
                "summary": "A doc",
                "topics": [],
                "text_clean": "Some text",
            }],
            cross_channel_topics=[],
        )
        assert "OTHER channels" not in prompt


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestCollectTouchedTopicIds:
    def test_collects_all_sources(self):
        kw_assign = [
            TopicAssignment(source_ref="tg:ch1:post:1", topic_id="t:1", score=0.5, method="keyword"),
            TopicAssignment(source_ref="tg:ch1:post:2", topic_id="t:2", score=0.6, method="keyword"),
        ]
        llm_assign = [
            TopicAssignment(source_ref="tg:ch1:post:3", topic_id="t:1", score=0.8, method="llm"),
            TopicAssignment(source_ref="tg:ch1:post:4", topic_id="t:3", score=0.7, method="llm"),
        ]
        new_cards = [_make_topic_card("t:4", "ch1")]

        result = _collect_touched_topic_ids(kw_assign, llm_assign, new_cards)
        assert result == {"t:1", "t:2", "t:3", "t:4"}

    def test_empty_inputs(self):
        result = _collect_touched_topic_ids([], [], [])
        assert result == set()


class TestLoadCrossChannelTopics:
    async def test_loads_only_other_channels(self):
        cards = [
            _make_topic_card("t:1", "ch1", title="Own Topic"),
            _make_topic_card("t:2", "ch2", title="Other Topic A"),
            _make_topic_card("t:3", "ch3", title="Other Topic B"),
        ]
        topic_card_repo = AsyncMock()
        topic_card_repo.list_all.return_value = cards

        result = await _load_cross_channel_topics("ch1", topic_card_repo)

        assert result is not None
        assert len(result) == 2
        titles = {t["title"] for t in result}
        assert "Own Topic" not in titles
        assert "Other Topic A" in titles
        assert "Other Topic B" in titles
        assert all(t.get("channel_id") for t in result)

    async def test_returns_none_when_no_other_channels(self):
        cards = [_make_topic_card("t:1", "ch1", title="Own Topic")]
        topic_card_repo = AsyncMock()
        topic_card_repo.list_all.return_value = cards

        result = await _load_cross_channel_topics("ch1", topic_card_repo)
        assert result is None


# ---------------------------------------------------------------------------
# Phase 3: cross-channel linking integration (mocked DB)
# ---------------------------------------------------------------------------


class TestRunCrossChannelLinking:
    async def test_creates_links_for_similar_topics(self):
        touched_card = _make_topic_card(
            "t:own", "ch1", title="Генетика",
            tags=["генетика", "днк"], scope_in=["генетика", "днк-тесты"],
        )
        other_card = _make_topic_card(
            "t:other", "ch2", title="ДНК тесты",
            tags=["генетика", "тесты"], scope_in=["генетика", "днк-тесты"],
        )
        unrelated_card = _make_topic_card(
            "t:unrelated", "ch3", title="Спорт",
            tags=["бег", "фитнес"], scope_in=["бег", "фитнес"],
        )

        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id.side_effect = lambda tid: {
            "t:own": touched_card,
            "t:other": other_card,
            "t:unrelated": unrelated_card,
        }.get(tid)
        topic_card_repo.list_all.return_value = [touched_card, other_card, unrelated_card]

        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        topic_link_repo.upsert_batch.return_value = 1
        embedding_repo = AsyncMock()
        embedding_repo.get_by_source_ref.return_value = None
        db = MagicMock()

        @asynccontextmanager
        async def mock_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topicization_service.topic_linking_repos",
            mock_repos,
        ):
            count = await _run_cross_channel_linking(
                channel_id="ch1",
                touched_topic_ids={"t:own"},
                threshold=0.1,
            )

        assert count >= 1
        topic_link_repo.upsert_batch.assert_called_once()
        saved_links = topic_link_repo.upsert_batch.call_args[0][0]
        link_pairs = {(l.topic_id_a, l.topic_id_b) for l in saved_links}
        assert ("t:own", "t:other") in link_pairs

    async def test_no_links_when_no_other_channels(self):
        touched_card = _make_topic_card("t:own", "ch1")

        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id.return_value = touched_card
        topic_card_repo.list_all.return_value = [touched_card]

        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        embedding_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topicization_service.topic_linking_repos",
            mock_repos,
        ):
            count = await _run_cross_channel_linking(
                channel_id="ch1",
                touched_topic_ids={"t:own"},
                threshold=0.3,
            )

        assert count == 0
        topic_link_repo.upsert_batch.assert_not_called()

    async def test_respects_threshold(self):
        touched_card = _make_topic_card(
            "t:own", "ch1", tags=["генетика"], scope_in=["генетика", "днк"],
        )
        other_card = _make_topic_card(
            "t:other", "ch2", tags=["спорт"], scope_in=["бег", "фитнес"],
        )

        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id.return_value = touched_card
        topic_card_repo.list_all.return_value = [touched_card, other_card]

        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        embedding_repo = AsyncMock()
        embedding_repo.get_by_source_ref.return_value = None
        db = MagicMock()

        @asynccontextmanager
        async def mock_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topicization_service.topic_linking_repos",
            mock_repos,
        ):
            count = await _run_cross_channel_linking(
                channel_id="ch1",
                touched_topic_ids={"t:own"},
                threshold=0.9,
            )

        assert count == 0
        topic_link_repo.upsert_batch.assert_not_called()

    async def test_uses_embeddings_when_available(self):
        touched_card = _make_topic_card(
            "t:own", "ch1", tags=["генетика"], scope_in=["генетика"],
        )
        other_card = _make_topic_card(
            "t:other", "ch2", tags=["генетика"], scope_in=["генетика"],
        )

        emb_own = _make_embedding("tg:ch1:post:1", [1.0, 0.0, 0.0])
        emb_other = _make_embedding("tg:ch2:post:1", [0.95, 0.05, 0.0])

        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id.return_value = touched_card
        topic_card_repo.list_all.return_value = [touched_card, other_card]

        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        topic_link_repo.upsert_batch.return_value = 1

        embedding_repo = AsyncMock()
        embedding_repo.get_by_source_ref.side_effect = lambda ref: {
            "tg:ch1:post:1": emb_own,
            "tg:ch2:post:1": emb_other,
        }.get(ref)

        db = MagicMock()

        @asynccontextmanager
        async def mock_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topicization_service.topic_linking_repos",
            mock_repos,
        ):
            count = await _run_cross_channel_linking(
                channel_id="ch1",
                touched_topic_ids={"t:own"},
                threshold=0.1,
            )

        assert count >= 1
        saved_links = topic_link_repo.upsert_batch.call_args[0][0]
        assert saved_links[0].similarity_score > 0.3


# ---------------------------------------------------------------------------
# Orchestrator: run_incremental_topicization with cross_channel flag
# ---------------------------------------------------------------------------


def _make_processed_doc(source_ref: str, channel_id: str) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref.split(":")[-1],
        channel_id=channel_id,
        processed_at=NOW,
        text_clean="Some substantial text about genetics and DNA testing " * 10,
        summary="About genetics",
        topics=["генетика"],
    )


_SVC = "tg_parser.services.topicization_service"


def _build_orchestrator_mocks(channel_id: str = "ch1"):
    """Build mocked repos with two docs for orchestrator tests.

    Returns (processed_repo, topic_card_repo, topic_bundle_repo, doc_refs).
    """
    doc_refs = [f"tg:{channel_id}:post:100", f"tg:{channel_id}:post:101"]
    docs = [_make_processed_doc(ref, channel_id) for ref in doc_refs]

    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda ref: next(
        (d for d in docs if d.source_ref == ref), None,
    )
    processed_repo.list_by_channel.return_value = docs

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [
        _make_topic_card("t:own", channel_id, title="Own Topic"),
    ]

    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    topic_bundle_repo.add_items = AsyncMock()

    return processed_repo, topic_card_repo, topic_bundle_repo, doc_refs


@asynccontextmanager
async def _orchestrator_patches(
    cross_channel_load_result=None,
    cross_channel_link_count=0,
    assign_returns_unassigned=True,
):
    """Context manager that patches all external deps of run_incremental_topicization.

    Patches: TopicizationPipelineImpl.assign_documents_to_topics,
    TopicizationPipelineImpl.discover_new_topics, _load_cross_channel_topics,
    _run_cross_channel_linking, _compute_coverage, _update_bundles_for_assignments,
    resolve_llm_config, create_llm_client.
    """
    from tg_parser.processing.topicization import TopicizationPipelineImpl

    async def fake_assign(self, new_docs, channel_id):
        refs = [d.source_ref for d in new_docs]
        if assign_returns_unassigned:
            return [], refs
        assignments = [
            TopicAssignment(
                source_ref=r, topic_id="t:own", score=0.8, method="keyword",
            )
            for r in refs
        ]
        return assignments, []

    async def fake_discover(
        self, channel_id, unassigned_docs, batch_size=50, cross_channel_topics=None,
    ):
        assignments = [
            TopicAssignment(
                source_ref=d.source_ref, topic_id="t:own", score=0.7, method="llm",
            )
            for d in unassigned_docs
        ]
        return assignments, [], [], 100

    coverage = {"total_documents": 2, "covered_documents": 1, "coverage_pct": 50.0, "uncovered_documents": 1}

    with patch.object(TopicizationPipelineImpl, "assign_documents_to_topics", fake_assign), \
         patch.object(TopicizationPipelineImpl, "discover_new_topics", fake_discover), \
         patch(f"{_SVC}._load_cross_channel_topics", new_callable=AsyncMock) as mock_load, \
         patch(f"{_SVC}._run_cross_channel_linking", new_callable=AsyncMock) as mock_link, \
         patch(f"{_SVC}._compute_coverage", new_callable=AsyncMock, return_value=coverage), \
         patch(f"{_SVC}._update_bundles_for_assignments", new_callable=AsyncMock), \
         patch(f"{_SVC}.resolve_llm_config", return_value=("openai", "key", "gpt-4o")), \
         patch(f"{_SVC}.create_llm_client") as mock_llm_factory:

        mock_load.return_value = cross_channel_load_result
        mock_link.return_value = cross_channel_link_count

        mock_llm = MagicMock()
        mock_llm.close = AsyncMock()
        mock_llm_factory.return_value = mock_llm

        yield {
            "mock_load": mock_load,
            "mock_link": mock_link,
        }


class TestRunIncrementalTopicizationOrchestration:
    """Test the full orchestrator with cross_channel=True/False/None."""

    async def test_cross_channel_true_calls_load_and_linking(self):
        processed_repo, topic_card_repo, topic_bundle_repo, doc_refs = (
            _build_orchestrator_mocks()
        )

        async with _orchestrator_patches(
            cross_channel_load_result=[
                {"id": "t:other", "title": "Other", "scope_in": ["scope"], "channel_id": "ch2"},
            ],
            cross_channel_link_count=3,
        ) as mocks:
            result = await run_incremental_topicization(
                channel_id="ch1",
                new_doc_refs=doc_refs,
                cross_channel=True,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

        mocks["mock_load"].assert_called_once()
        mocks["mock_link"].assert_called_once()
        assert result.cross_channel_links_created == 3

    async def test_cross_channel_false_skips_load_and_linking(self):
        processed_repo, topic_card_repo, topic_bundle_repo, doc_refs = (
            _build_orchestrator_mocks()
        )

        async with _orchestrator_patches() as mocks:
            result = await run_incremental_topicization(
                channel_id="ch1",
                new_doc_refs=doc_refs,
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

        mocks["mock_load"].assert_not_called()
        mocks["mock_link"].assert_not_called()
        assert result.cross_channel_links_created == 0

    async def test_cross_channel_none_uses_settings_default(self):
        processed_repo, topic_card_repo, topic_bundle_repo, doc_refs = (
            _build_orchestrator_mocks()
        )

        async with _orchestrator_patches(
            cross_channel_load_result=None,
            cross_channel_link_count=0,
        ) as mocks:
            with patch("tg_parser.config.settings") as mock_settings:
                mock_settings.cross_channel_topicization = True
                mock_settings.cross_channel_link_threshold = 0.3
                mock_settings.topicization_batch_size = 50

                result = await run_incremental_topicization(
                    channel_id="ch1",
                    new_doc_refs=doc_refs,
                    cross_channel=None,
                    processed_repo=processed_repo,
                    topic_card_repo=topic_card_repo,
                    topic_bundle_repo=topic_bundle_repo,
                )

        mocks["mock_load"].assert_called_once()
        mocks["mock_link"].assert_called_once()


# ---------------------------------------------------------------------------
# Prompt size stress test
# ---------------------------------------------------------------------------


class TestPromptSizeWithManyCrossChannelTopics:
    """Verify prompt stays within reasonable bounds with 400+ cross-channel topics."""

    MAX_PROMPT_CHARS = 200_000

    def test_prompt_size_with_400_cross_channel_topics(self):
        existing_topics = [
            {"id": f"t:{i}", "title": f"Topic {i}", "scope_in": [f"scope_{i}", f"keyword_{i}"]}
            for i in range(20)
        ]
        unassigned_docs = [
            {
                "source_ref": f"tg:ch1:post:{i}",
                "summary": f"Document about genetics and testing {i}",
                "topics": [],
                "text_clean": f"Substantial text content about genetics {i} " * 20,
            }
            for i in range(50)
        ]
        cross_channel_topics = [
            {
                "id": f"t:cross:{i}",
                "title": f"Cross Channel Topic {i} about health and longevity",
                "scope_in": [f"health_{i}", f"longevity_{i}", f"genetics_{i}"],
                "channel_id": f"ch{(i % 5) + 2}",
            }
            for i in range(400)
        ]

        prompt = build_incremental_discover_prompt(
            existing_topics=existing_topics,
            unassigned_docs=unassigned_docs,
            cross_channel_topics=cross_channel_topics,
        )

        prompt_len = len(prompt)
        assert prompt_len < self.MAX_PROMPT_CHARS, (
            f"Prompt too large: {prompt_len:,} chars (limit {self.MAX_PROMPT_CHARS:,})"
        )
        assert "OTHER channels" in prompt
        assert "Cross Channel Topic 0" in prompt
        assert "Cross Channel Topic 399" in prompt

    def test_prompt_size_with_1000_cross_channel_topics(self):
        """Even with 1000 topics, prompt should stay under 200K chars."""
        existing_topics = [
            {"id": f"t:{i}", "title": f"Topic {i}", "scope_in": [f"scope_{i}"]}
            for i in range(10)
        ]
        unassigned_docs = [
            {
                "source_ref": f"tg:ch1:post:{i}",
                "summary": f"Doc {i}",
                "topics": [],
                "text_clean": f"Text {i}",
            }
            for i in range(10)
        ]
        cross_channel_topics = [
            {
                "id": f"t:cross:{i}",
                "title": f"Cross Topic {i}",
                "scope_in": [f"s{i}a", f"s{i}b", f"s{i}c"],
                "channel_id": f"ch{(i % 10) + 2}",
            }
            for i in range(1000)
        ]

        prompt = build_incremental_discover_prompt(
            existing_topics=existing_topics,
            unassigned_docs=unassigned_docs,
            cross_channel_topics=cross_channel_topics,
        )

        prompt_len = len(prompt)
        assert prompt_len < self.MAX_PROMPT_CHARS, (
            f"Prompt too large with 1000 topics: {prompt_len:,} chars"
        )
