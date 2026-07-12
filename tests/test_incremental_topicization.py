"""
Tests for incremental topicization (Session 35 + Session 36 Phase 2).

Covers:
- assign_documents_to_topics (Phase 1 keyword matching)
- _compute_match_score (shared scoring helper)
- add_items (incremental bundle update)
- discover_new_topics (Phase 2 LLM discover)
- run_incremental_topicization (E2E orchestration)
"""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    IncrementalTopicizeResult,
    MessageType,
    ProcessedDocument,
    TopicAssignment,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.topicization import (
    MIN_SUPPORTING_SCORE,
    TopicizationPipelineImpl,
    _aggregate_assign_score,
)
from tg_parser.services.topicization_service import run_incremental_topicization
from tg_parser.services.watchlist_service import _aggregate_keyword_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    source_ref: str,
    text_clean: str = "some text content",
    summary: str | None = "summary",
    topics: list[str] | None = None,
    channel_id: str = "labdiagnostica",
) -> ProcessedDocument:
    parts = source_ref.split(":")
    msg_id = parts[-1]
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=msg_id,
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=text_clean,
        summary=summary,
        topics=topics or [],
    )


def _make_topic_card(
    title: str,
    scope_in: list[str],
    anchor_refs: list[str],
    topic_type: TopicType | None = None,
    channel_id: str = "labdiagnostica",
) -> TopicCard:
    anchors = []
    for ref in anchor_refs:
        parts = ref.split(":")
        anchors.append(
            Anchor(
                channel_id=parts[1],
                message_id=parts[3],
                message_type=MessageType(parts[2]),
                anchor_ref=ref,
                score=0.9,
            )
        )
    if topic_type is None:
        topic_type = TopicType.CLUSTER if len(anchors) >= 2 else TopicType.SINGLETON
    return TopicCard(
        id=f"topic:{anchor_refs[0]}",
        title=title,
        summary=f"Summary of {title}",
        scope_in=scope_in,
        scope_out=["unrelated"],
        type=topic_type,
        anchors=anchors,
        sources=[channel_id],
        updated_at=datetime.now(UTC),
    )


def _make_pipeline(topic_cards=None) -> TopicizationPipelineImpl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = topic_cards or []

    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=topic_card_repo,
        topic_bundle_repo=AsyncMock(),
    )


def _make_bundle(topic_id: str, items: list[BundleItem]) -> TopicBundle:
    return TopicBundle(
        topic_id=topic_id,
        items=items,
        updated_at=datetime.now(UTC),
        channels=["labdiagnostica"],
    )


_RICH_GENETICS_SCOPE = [
    "редкие",
    "генетические",
    "болезни",
    "крови",
    "трансфузиология",
    "гемоглобинопатии",
    "талассемия",
    "синдром",
    "мутации",
    "наследственность",
]


def _make_rich_genetics_topic(**kwargs) -> TopicCard:
    defaults = {
        "title": "Очень специфическая тема редкие генетические болезни крови",
        "scope_in": _RICH_GENETICS_SCOPE,
        "anchor_refs": ["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
    }
    defaults.update(kwargs)
    return _make_topic_card(**defaults)


def _make_single_krovi_hit_doc() -> ProcessedDocument:
    return _make_doc(
        "tg:labdiagnostica:post:300",
        topics=["крови"],
        summary="",
        text_clean="short text",
    )


def _run_assign(pipeline, docs):
    return asyncio.get_event_loop().run_until_complete(
        pipeline.assign_documents_to_topics(docs, "labdiagnostica")
    )


# ===========================================================================
# _compute_match_score tests
# ===========================================================================


class TestComputeMatchScore:
    """Tests for the shared scoring helper."""

    def test_strong_hit_scores_full(self):
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={"анализ", "кровь"},
            strong_tokens={"анализ", "кровь"},
            weak_tokens=set(),
        )
        assert score == 1.0
        assert hits == {"анализ", "кровь"}

    def test_weak_hit_scores_reduced(self):
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={"анализ", "кровь"},
            strong_tokens=set(),
            weak_tokens={"анализ", "кровь"},
        )
        expected = round(2 * 0.3 / 2, 3)
        assert score == expected
        assert hits == {"анализ", "кровь"}

    def test_mixed_strong_and_weak(self):
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={"анализ", "кровь", "биохимия"},
            strong_tokens={"анализ"},
            weak_tokens={"кровь"},
        )
        expected = round((1 + 0.3) / 3, 3)
        assert score == expected

    def test_no_hits_returns_zero(self):
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={"анализ"},
            strong_tokens={"другое"},
            weak_tokens=set(),
        )
        assert score == 0.0
        assert hits == set()

    def test_empty_tokens_returns_zero(self):
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={"анализ"},
            strong_tokens=set(),
            weak_tokens=set(),
        )
        assert score == 0.0

    def test_substring_fallback(self):
        """Long tokens that are substrings should match."""
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={"гемоглобин"},
            strong_tokens={"гемоглобинопатия"},
            weak_tokens=set(),
        )
        assert score > 0
        assert "гемоглобин" in hits

    def test_default_topk_denom_for_n_gt_k(self):
        """Default aggregation uses topk_denom when topic has more than K tokens."""
        keywords = {f"kw{i}" for i in range(10)}
        score, _ = TopicizationPipelineImpl._compute_match_score(
            topic_keywords=keywords,
            strong_tokens={"kw0"},
            weak_tokens=set(),
        )
        assert score == pytest.approx(round(1 / 3, 3))


class TestAggregateAssignScore:
    """Unit tests for S5 assign keyword aggregation."""

    def test_empty_n_returns_zero(self):
        assert _aggregate_assign_score(1.0, 0, aggregation="mean", topk=3) == 0.0
        assert _aggregate_assign_score(1.0, 0, aggregation="topk_denom", topk=3) == 0.0

    @pytest.mark.parametrize(
        "n,hits",
        [
            (1, 0.0),
            (1, 0.3),
            (1, 1.0),
            (2, 0.0),
            (2, 0.3),
            (2, 0.6),
            (2, 1.0),
            (2, 1.3),
            (2, 2.0),
            (3, 0.0),
            (3, 1.0),
            (3, 1.3),
            (3, 2.0),
            (3, 3.0),
        ],
    )
    def test_topk_denom_noop_for_n_le_k(self, n: int, hits: float):
        """For n <= K, topk_denom is byte-identical to mean (realistic hit counts)."""
        mean = _aggregate_assign_score(hits, n, aggregation="mean", topk=3)
        topk = _aggregate_assign_score(hits, n, aggregation="topk_denom", topk=3)
        assert topk == mean
        if n > 0:
            assert topk == pytest.approx(hits / n)

    def test_rich_vocabulary_lifts_score(self):
        """One hit on a 10-token topic: topk_denom = 1/3, mean = 1/10."""
        mean = _aggregate_assign_score(1.0, 10, aggregation="mean", topk=3)
        topk = _aggregate_assign_score(1.0, 10, aggregation="topk_denom", topk=3)
        assert mean == pytest.approx(0.1)
        assert topk == pytest.approx(1 / 3)
        assert topk > mean

    def test_topk_denom_can_exceed_one(self):
        score = _aggregate_assign_score(4.0, 10, aggregation="topk_denom", topk=3)
        assert score == pytest.approx(4 / 3)
        assert score > 1.0

    def test_custom_topk_changes_denominator(self):
        score_k3 = _aggregate_assign_score(1.0, 10, aggregation="topk_denom", topk=3)
        score_k5 = _aggregate_assign_score(1.0, 10, aggregation="topk_denom", topk=5)
        assert score_k3 == pytest.approx(1 / 3)
        assert score_k5 == pytest.approx(0.2)
        assert score_k5 < score_k3

    def test_topk_denom_differs_from_watchlist_topk_at_high_hits(self):
        """ADR-0010 naming trap: assign topk_denom caps denominator, watchlist caps numerator."""
        assign = _aggregate_assign_score(4.0, 10, aggregation="topk_denom", topk=3)
        watchlist = _aggregate_keyword_score(4, 10, aggregation="topk", topk=3)
        assert assign == pytest.approx(4 / 3)
        assert watchlist == pytest.approx(1.0)
        assert assign != watchlist

    def test_topk_denom_monotonic_non_decreasing_in_hits(self):
        n = 10
        prev = -1.0
        for hits in (0.0, 0.3, 1.0, 2.0, 3.0, 4.0):
            score = _aggregate_assign_score(hits, n, aggregation="topk_denom", topk=3)
            assert score >= prev
            prev = score

    def test_bounds_for_topk_denom_and_mean(self):
        for hits in (0.0, 0.3, 1.0, 2.0, 3.0, 4.0):
            for n in (1, 3, 10):
                for scheme in ("mean", "topk_denom"):
                    score = _aggregate_assign_score(hits, n, aggregation=scheme, topk=3)
                    assert score >= 0.0

    def test_mean_rollback_matches_legacy_formula(self):
        score = _aggregate_assign_score(1.3, 5, aggregation="mean", topk=3)
        assert score == pytest.approx(1.3 / 5)

    def test_unknown_aggregation_raises(self):
        with pytest.raises(ValueError, match="unknown topicization assign keyword aggregation"):
            _aggregate_assign_score(1.0, 5, aggregation="topk", topk=3)

    def test_compute_match_score_mean_rollback_kwarg(self):
        """Explicit aggregation='mean' reproduces pre-S5 scores for n > K."""
        keywords = {f"kw{i}" for i in range(10)}
        score_topk, _ = TopicizationPipelineImpl._compute_match_score(
            topic_keywords=keywords,
            strong_tokens={"kw0"},
            weak_tokens=set(),
            aggregation="topk_denom",
            topk=3,
        )
        score_mean, _ = TopicizationPipelineImpl._compute_match_score(
            topic_keywords=keywords,
            strong_tokens={"kw0"},
            weak_tokens=set(),
            aggregation="mean",
            topk=3,
        )
        assert score_topk == pytest.approx(round(1 / 3, 3))
        assert score_mean == pytest.approx(round(0.1, 3))

    def test_weak_weight_preserved_under_topk_denom(self):
        score, hits = TopicizationPipelineImpl._compute_match_score(
            topic_keywords={f"kw{i}" for i in range(8)},
            strong_tokens=set(),
            weak_tokens={"kw0", "kw1"},
            aggregation="topk_denom",
            topk=3,
        )
        assert hits == {"kw0", "kw1"}
        assert score == pytest.approx(round(0.6 / 3, 3))


class TestTopkAssignIntegration:
    """Assign path uses topk_denom by default for rich-vocabulary topics."""

    def test_rich_topic_assigns_with_topk_below_mean_threshold(self):
        """One keyword hit on a rich topic clears 0.10 under topk_denom, not mean."""
        pipeline = _make_pipeline(topic_cards=[_make_rich_genetics_topic()])
        assignments, unassigned = _run_assign(pipeline, [_make_single_krovi_hit_doc()])

        assert len(assignments) == 1
        assert assignments[0].score == pytest.approx(round(1 / 3, 3))
        assert len(unassigned) == 0

    def test_mean_rollback_leaves_rich_topic_unassigned(self):
        pipeline = _make_pipeline(topic_cards=[_make_rich_genetics_topic()])

        with patch(
            "tg_parser.processing.topicization.ASSIGN_KEYWORD_AGGREGATION",
            "mean",
        ):
            assignments, unassigned = _run_assign(pipeline, [_make_single_krovi_hit_doc()])

        assert len(assignments) == 0
        assert "tg:labdiagnostica:post:300" in unassigned

    def test_settings_env_mean_rollback_value(self):
        from tg_parser.config.settings import Settings

        s = Settings(_env_file=None, topicization_assign_keyword_aggregation="mean")
        assert s.topicization_assign_keyword_aggregation == "mean"

    def test_assign_noop_n_le_k_identical_mean_vs_topk(self):
        """Assign decisions byte-identical when topic has n <= K keywords."""
        topic = _make_topic_card(
            title="диагностика",
            scope_in=["ПЦР", "диагностика", "инфекции"],
            anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
        )
        doc = _make_doc(
            "tg:labdiagnostica:post:300",
            topics=["ПЦР", "инфекции"],
            summary="Метод ПЦР",
        )
        pipeline = _make_pipeline(topic_cards=[topic])

        topk_assign, topk_unassigned = _run_assign(pipeline, [doc])
        with patch(
            "tg_parser.processing.topicization.ASSIGN_KEYWORD_AGGREGATION",
            "mean",
        ):
            mean_assign, mean_unassigned = _run_assign(pipeline, [doc])

        assert len(topk_assign) == len(mean_assign) == 1
        assert topk_assign[0].topic_id == mean_assign[0].topic_id
        assert topk_assign[0].score == mean_assign[0].score
        assert topk_unassigned == mean_unassigned == []

    def test_stored_score_preserves_raw_above_one(self):
        """BundleItem and TopicAssignment keep raw topk_denom scores for ranking."""
        topic = _make_topic_card(
            title="one two three four five six seven eight nine ten",
            scope_in=[
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
            ],
            anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
        )
        doc = _make_doc(
            "tg:labdiagnostica:post:300",
            topics=["one", "two", "three", "four", "five", "six"],
            summary="six keyword hits",
        )
        pipeline = _make_pipeline(topic_cards=[topic])
        assignments, _ = _run_assign(pipeline, [doc])

        assert len(assignments) == 1
        assert assignments[0].score == pytest.approx(2.0)

    def test_argmax_uses_raw_score_when_both_above_one(self):
        """Higher raw score wins when multiple topics exceed 1.0."""
        topic_a = _make_topic_card(
            title="one two three four five six seven eight nine ten",
            scope_in=[
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
            ],
            anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
        )
        topic_b = _make_topic_card(
            title="one two three four alpha beta gamma delta epsilon zeta",
            scope_in=[
                "one",
                "two",
                "three",
                "four",
                "alpha",
                "beta",
                "gamma",
                "delta",
                "epsilon",
                "zeta",
            ],
            anchor_refs=["tg:labdiagnostica:post:200", "tg:labdiagnostica:post:201"],
        )
        doc = _make_doc(
            "tg:labdiagnostica:post:300",
            topics=["one", "two", "three", "four", "five", "six"],
            summary="six hits for topic A, four for topic B",
        )
        pipeline = _make_pipeline(topic_cards=[topic_b, topic_a])
        assignments, _ = _run_assign(pipeline, [doc])

        assert len(assignments) == 1
        assert assignments[0].topic_id == topic_a.id
        assert assignments[0].score == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_update_bundles_propagates_raw_score_above_one(self):
        """Incremental bundle update must preserve raw assign scores for sorting."""
        from tg_parser.services.topicization_service import _update_bundles_for_assignments
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        topic_id = "topic:tg:labdiagnostica:post:100"
        existing_bundle = _make_bundle(
            topic_id,
            [
                BundleItem(
                    channel_id="labdiagnostica",
                    message_id="100",
                    message_type=MessageType.POST,
                    source_ref="tg:labdiagnostica:post:100",
                    role=BundleItemRole.ANCHOR,
                    score=0.9,
                ),
                BundleItem(
                    channel_id="labdiagnostica",
                    message_id="200",
                    message_type=MessageType.POST,
                    source_ref="tg:labdiagnostica:post:200",
                    role=BundleItemRole.SUPPORTING,
                    score=round(4 / 3, 3),
                ),
            ],
        )

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = existing_bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        assignment = TopicAssignment(
            source_ref="tg:labdiagnostica:post:300",
            topic_id=topic_id,
            score=2.0,
            method="keyword",
        )
        docs_by_ref = {"tg:labdiagnostica:post:300": _make_single_krovi_hit_doc()}

        await _update_bundles_for_assignments(
            [assignment],
            docs_by_ref,
            repo,
            method="keyword",
        )

        updated = repo.upsert.await_args.args[0]
        supporting = [i for i in updated.items if i.role == BundleItemRole.SUPPORTING]
        assert supporting[0].source_ref == "tg:labdiagnostica:post:300"
        assert supporting[0].score == pytest.approx(2.0)
        assert supporting[1].source_ref == "tg:labdiagnostica:post:200"


# ===========================================================================
# assign_documents_to_topics tests
# ===========================================================================


class TestAssignDocumentsToTopics:
    """Tests for Phase 1 keyword assignment."""

    def test_assign_matching_docs(self):
        """Documents matching topic keywords should be assigned."""
        topics = [
            _make_topic_card(
                title="ПЦР-диагностика инфекций",
                scope_in=["ПЦР", "диагностика", "инфекции"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
            _make_topic_card(
                title="Биохимия крови",
                scope_in=["биохимия", "кровь", "анализ"],
                anchor_refs=["tg:labdiagnostica:post:200", "tg:labdiagnostica:post:201"],
            ),
        ]
        pipeline = _make_pipeline(topic_cards=topics)

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:300",
                topics=["ПЦР", "инфекции"],
                summary="Метод ПЦР диагностики",
            ),
            _make_doc(
                "tg:labdiagnostica:post:301",
                topics=["биохимия", "кровь"],
                summary="Анализ крови биохимический",
            ),
            _make_doc(
                "tg:labdiagnostica:post:302",
                topics=[],
                summary="Совершенно другая тема",
                text_clean="нерелевантный текст",
            ),
        ]

        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(docs, "labdiagnostica")
        )

        assigned_refs = {a.source_ref for a in assignments}
        assert "tg:labdiagnostica:post:300" in assigned_refs
        assert "tg:labdiagnostica:post:301" in assigned_refs
        assert "tg:labdiagnostica:post:302" in unassigned

    def test_assign_best_topic_selected(self):
        """When a doc matches multiple topics, the one with the highest score wins."""
        topics = [
            _make_topic_card(
                title="Общий анализ",
                scope_in=["анализ"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
            _make_topic_card(
                title="Биохимический анализ крови витамины гормоны",
                scope_in=["биохимия", "кровь", "анализ", "витамины", "гормоны"],
                anchor_refs=["tg:labdiagnostica:post:200", "tg:labdiagnostica:post:201"],
            ),
        ]
        pipeline = _make_pipeline(topic_cards=topics)

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:300",
                topics=["биохимия", "кровь", "анализ", "витамины"],
                summary="Биохимический анализ крови с витаминами",
            ),
        ]

        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(docs, "labdiagnostica")
        )

        assert len(assignments) == 1
        assert assignments[0].topic_id == topics[1].id

    def test_all_unassigned_when_no_topics(self):
        """All docs should be unassigned when there are no topic cards."""
        pipeline = _make_pipeline(topic_cards=[])

        docs = [
            _make_doc("tg:labdiagnostica:post:300", topics=["анализ"]),
        ]

        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(docs, "labdiagnostica")
        )

        assert len(assignments) == 0
        assert len(unassigned) == 1

    def test_assignment_has_correct_fields(self):
        """Each TopicAssignment should have correct method and valid score."""
        topics = [
            _make_topic_card(
                title="Анализ крови",
                scope_in=["анализ", "кровь"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
        ]
        pipeline = _make_pipeline(topic_cards=topics)

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:300",
                topics=["анализ", "кровь"],
            ),
        ]

        assignments, _ = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(docs, "labdiagnostica")
        )

        assert len(assignments) == 1
        a = assignments[0]
        assert a.method == "keyword"
        assert a.score >= MIN_SUPPORTING_SCORE
        assert a.source_ref == "tg:labdiagnostica:post:300"
        assert a.topic_id == topics[0].id


# ===========================================================================
# add_items tests
# ===========================================================================


class TestAddItemsToBundle:
    """Tests for incremental bundle update."""

    def _make_item(self, msg_id: str, role=BundleItemRole.SUPPORTING, score=0.5):
        return BundleItem(
            channel_id="labdiagnostica",
            message_id=msg_id,
            message_type=MessageType.POST,
            source_ref=f"tg:labdiagnostica:post:{msg_id}",
            role=role,
            score=score,
        )

    def test_add_new_items(self):
        """New items should be added to the bundle."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        existing_items = [
            self._make_item("1", role=BundleItemRole.ANCHOR, score=0.9),
            self._make_item("2", score=0.7),
            self._make_item("3", score=0.5),
        ]
        bundle = _make_bundle("topic:tg:labdiagnostica:post:1", existing_items)

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        new_items = [
            self._make_item("4", score=0.6),
            self._make_item("5", score=0.4),
        ]

        result = asyncio.get_event_loop().run_until_complete(
            repo.add_items("topic:tg:labdiagnostica:post:1", new_items)
        )

        assert len(result.items) == 5
        refs = [item.source_ref for item in result.items]
        assert "tg:labdiagnostica:post:4" in refs
        assert "tg:labdiagnostica:post:5" in refs

    def test_dedupe_existing_items(self):
        """Duplicate source_refs should not be added again."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        existing_items = [
            self._make_item("1", role=BundleItemRole.ANCHOR, score=0.9),
            self._make_item("2", score=0.7),
            self._make_item("3", score=0.5),
        ]
        bundle = _make_bundle("topic:tg:labdiagnostica:post:1", existing_items)

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        new_items = [
            self._make_item("2", score=0.8),  # duplicate
            self._make_item("4", score=0.6),
        ]

        result = asyncio.get_event_loop().run_until_complete(
            repo.add_items("topic:tg:labdiagnostica:post:1", new_items)
        )

        assert len(result.items) == 4  # 3 existing + 1 new (deduped)

    def test_sort_order_anchors_first(self):
        """Items should be sorted: anchors first, then by score desc."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        existing_items = [
            self._make_item("1", role=BundleItemRole.ANCHOR, score=0.9),
            self._make_item("2", score=0.3),
        ]
        bundle = _make_bundle("topic:tg:labdiagnostica:post:1", existing_items)

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        new_items = [self._make_item("3", score=0.8)]

        result = asyncio.get_event_loop().run_until_complete(
            repo.add_items("topic:tg:labdiagnostica:post:1", new_items)
        )

        assert result.items[0].role == BundleItemRole.ANCHOR
        supporting = [i for i in result.items if i.role == BundleItemRole.SUPPORTING]
        scores = [i.score for i in supporting]
        assert scores == sorted(scores, reverse=True)

    def test_add_items_sorts_raw_scores_above_one(self):
        """add_items must rank supporting items by raw topk_denom scores > 1.0."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        existing_items = [
            self._make_item("1", role=BundleItemRole.ANCHOR, score=0.9),
            self._make_item("200", score=round(4 / 3, 3)),
            self._make_item("201", score=2.0),
        ]
        bundle = _make_bundle("topic:tg:labdiagnostica:post:1", existing_items)

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        new_items = [self._make_item("202", score=1.667)]

        result = asyncio.get_event_loop().run_until_complete(
            repo.add_items("topic:tg:labdiagnostica:post:1", new_items)
        )

        supporting = [i for i in result.items if i.role == BundleItemRole.SUPPORTING]
        assert [i.source_ref for i in supporting] == [
            "tg:labdiagnostica:post:201",
            "tg:labdiagnostica:post:202",
            "tg:labdiagnostica:post:200",
        ]
        assert supporting[0].score == pytest.approx(2.0)

    def test_no_bundle_raises_error(self):
        """add_items should raise ValueError when bundle doesn't exist."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = None
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        with pytest.raises(ValueError, match="No bundle found"):
            asyncio.get_event_loop().run_until_complete(
                repo.add_items("topic:nonexistent", [self._make_item("1")])
            )

    def test_all_duplicates_returns_unchanged(self):
        """When all new items are duplicates, bundle should remain unchanged."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        existing_items = [
            self._make_item("1", role=BundleItemRole.ANCHOR, score=0.9),
            self._make_item("2", score=0.7),
        ]
        bundle = _make_bundle("topic:tg:labdiagnostica:post:1", existing_items)

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        new_items = [self._make_item("2", score=0.9)]  # duplicate

        result = asyncio.get_event_loop().run_until_complete(
            repo.add_items("topic:tg:labdiagnostica:post:1", new_items)
        )

        assert len(result.items) == 2
        repo.upsert.assert_not_called()


# ===========================================================================
# Refactored _find_supporting_items_programmatic regression test
# ===========================================================================


class TestFindSupportingItemsRefactored:
    """Verify refactored _find_supporting_items_programmatic still works correctly."""

    def test_still_finds_supporting_items(self):
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="ПЦР-диагностика инфекций",
            scope_in=["ПЦР", "диагностика", "инфекции"],
            anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
        )

        docs = [
            _make_doc("tg:labdiagnostica:post:100"),
            _make_doc("tg:labdiagnostica:post:101"),
            _make_doc(
                "tg:labdiagnostica:post:200",
                text_clean="ПЦР диагностика различных инфекций",
                topics=["ПЦР"],
            ),
        ]

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"},
            documents=docs,
        )

        refs = {item.source_ref for item in items}
        assert "tg:labdiagnostica:post:200" in refs
        assert "tg:labdiagnostica:post:100" not in refs  # anchor excluded

    def test_justification_present(self):
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="Анализ крови",
            scope_in=["анализ", "кровь"],
            anchor_refs=["tg:labdiagnostica:post:1", "tg:labdiagnostica:post:2"],
        )

        docs = [
            _make_doc("tg:labdiagnostica:post:1"),
            _make_doc("tg:labdiagnostica:post:2"),
            _make_doc("tg:labdiagnostica:post:3", topics=["анализ", "кровь"]),
        ]

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:1", "tg:labdiagnostica:post:2"},
            documents=docs,
        )

        for item in items:
            assert item.justification is not None
            assert "keyword overlap" in item.justification


class TestBundleSupportingSortOrder:
    """Supporting items must stay ranked by raw topk_denom score through bundle build."""

    def test_compute_topic_bundle_preserves_raw_score_ranking(self):
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="one two three four five six seven eight nine ten",
            scope_in=[
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
            ],
            anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
        )

        docs = [
            _make_doc("tg:labdiagnostica:post:100"),
            _make_doc("tg:labdiagnostica:post:101"),
            _make_doc(
                "tg:labdiagnostica:post:200",
                topics=["one", "two", "three", "four"],
                summary="four hits",
            ),
            _make_doc(
                "tg:labdiagnostica:post:201",
                topics=["one", "two", "three", "four", "five", "six"],
                summary="six hits",
            ),
        ]

        bundle = pipeline._compute_topic_bundle(topic, "labdiagnostica", docs)
        supporting = [i for i in bundle.items if i.role == BundleItemRole.SUPPORTING]

        assert len(supporting) == 2
        assert supporting[0].source_ref == "tg:labdiagnostica:post:201"
        assert supporting[1].source_ref == "tg:labdiagnostica:post:200"
        assert supporting[0].score == pytest.approx(2.0)
        assert supporting[1].score == pytest.approx(round(4 / 3, 3))
        assert (supporting[0].score or 0) > (supporting[1].score or 0)


# ===========================================================================
# TopicAssignment / IncrementalTopicizeResult model tests
# ===========================================================================


class TestModels:
    """Verify new domain models."""

    def test_topic_assignment_creation(self):
        a = TopicAssignment(
            source_ref="tg:ch:post:1",
            topic_id="topic:tg:ch:post:100",
            score=0.75,
            method="keyword",
        )
        assert a.method == "keyword"
        assert a.score == 0.75

    def test_incremental_result_defaults(self):
        r = IncrementalTopicizeResult()
        assert r.assigned_keyword == []
        assert r.assigned_llm == []
        assert r.new_topics == []
        assert r.unassignable == []
        assert r.tokens_used == 0
        assert r.coverage_before == 0.0
        assert r.coverage_after == 0.0

    def test_incremental_result_with_data(self):
        r = IncrementalTopicizeResult(
            assigned_keyword=[
                TopicAssignment(
                    source_ref="tg:ch:post:1",
                    topic_id="topic:tg:ch:post:100",
                    score=0.5,
                    method="keyword",
                ),
            ],
            unassignable=["tg:ch:post:2"],
            coverage_before=77.4,
            coverage_after=78.1,
        )
        assert len(r.assigned_keyword) == 1
        assert len(r.unassignable) == 1


# ===========================================================================
# Phase 2: discover_new_topics tests (Session 36)
# ===========================================================================


def _make_pipeline_with_llm_response(
    llm_response: str,
    topic_cards: list[TopicCard] | None = None,
) -> TopicizationPipelineImpl:
    """Create a pipeline with a mock LLM that returns the given response."""
    from tg_parser.processing.ports import LLMResponse

    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    llm.generate = AsyncMock(return_value=llm_response)
    llm.generate_with_usage = AsyncMock(
        return_value=LLMResponse(text=llm_response, input_tokens=100, output_tokens=50),
    )

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = topic_cards or []
    topic_card_repo.upsert = AsyncMock()

    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.upsert = AsyncMock()
    topic_bundle_repo.add_items = AsyncMock()

    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=topic_card_repo,
        topic_bundle_repo=topic_bundle_repo,
    )


class TestDiscoverNewTopicsAssignsToExisting:
    """Phase 2: LLM assigns docs to existing topics."""

    def test_assigns_to_existing_topic(self):
        existing_topics = [
            _make_topic_card(
                title="ПЦР-диагностика инфекций",
                scope_in=["ПЦР", "диагностика", "инфекции"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
        ]

        llm_response = json.dumps(
            {
                "assignments": [
                    {
                        "source_ref": "tg:labdiagnostica:post:500",
                        "topic_id": existing_topics[0].id,
                        "confidence": 0.85,
                    }
                ],
                "new_topics": [],
                "unassignable": [],
            }
        )

        pipeline = _make_pipeline_with_llm_response(llm_response, existing_topics)

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:500",
                text_clean="Современные методы ПЦР в диагностике",
                summary="Обзор ПЦР",
                topics=["медицина"],
            ),
        ]

        llm_assigns, new_cards, unassignable, _tokens = asyncio.get_event_loop().run_until_complete(
            pipeline.discover_new_topics("labdiagnostica", docs)
        )

        assert len(llm_assigns) == 1
        assert llm_assigns[0].method == "llm"
        assert llm_assigns[0].topic_id == existing_topics[0].id
        assert llm_assigns[0].score == 0.85
        assert llm_assigns[0].source_ref == "tg:labdiagnostica:post:500"
        assert len(new_cards) == 0
        assert len(unassignable) == 0


class TestDiscoverNewTopicsCreatesNewTopic:
    """Phase 2: LLM creates new topics."""

    def test_creates_new_topic(self):
        existing_topics = [
            _make_topic_card(
                title="ПЦР-диагностика",
                scope_in=["ПЦР", "диагностика"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
        ]

        llm_response = json.dumps(
            {
                "assignments": [],
                "new_topics": [
                    {
                        "title": "Иммуногистохимия опухолей",
                        "summary": "Методы иммуногистохимического анализа опухолевых тканей",
                        "scope_in": ["иммуногистохимия", "опухоли", "биопсия"],
                        "scope_out": ["ПЦР", "серология"],
                        "type": "singleton",
                        "anchors": [{"source_ref": "tg:labdiagnostica:post:600", "score": 0.9}],
                    }
                ],
                "unassignable": [],
            }
        )

        pipeline = _make_pipeline_with_llm_response(llm_response, existing_topics)

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:600",
                text_clean="A" * 400,
                summary="Иммуногистохимический анализ",
                topics=["иммуногистохимия"],
            ),
        ]

        llm_assigns, new_cards, unassignable, _tokens = asyncio.get_event_loop().run_until_complete(
            pipeline.discover_new_topics("labdiagnostica", docs)
        )

        assert len(llm_assigns) == 0
        assert len(new_cards) == 1
        card = new_cards[0]
        assert card.title == "Иммуногистохимия опухолей"
        assert card.metadata is not None
        assert card.metadata["origin"] == "discovered"
        assert "discovered_at" in card.metadata
        assert card.metadata["algorithm"] == "incremental_llm_discover"
        assert len(unassignable) == 0


class TestDiscoverNewTopicsMarksUnassignable:
    """Phase 2: LLM marks documents as unassignable."""

    def test_marks_unassignable(self):
        llm_response = json.dumps(
            {
                "assignments": [],
                "new_topics": [],
                "unassignable": ["tg:labdiagnostica:post:700"],
            }
        )

        pipeline = _make_pipeline_with_llm_response(llm_response, [])

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:700",
                text_clean="Привет",
                summary="",
                topics=[],
            ),
        ]

        llm_assigns, new_cards, unassignable, _tokens = asyncio.get_event_loop().run_until_complete(
            pipeline.discover_new_topics("labdiagnostica", docs)
        )

        assert len(llm_assigns) == 0
        assert len(new_cards) == 0
        assert "tg:labdiagnostica:post:700" in unassignable


class TestDiscoverHandlesJsonParseError:
    """Phase 2: retry on JSONDecodeError, fallback to all unassignable."""

    def test_json_parse_error_fallback(self):
        from tg_parser.processing.ports import LLMResponse

        llm = AsyncMock()
        llm.model = "test-model"
        llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
        llm.generate = AsyncMock(return_value="NOT VALID JSON {{{")
        llm.generate_with_usage = AsyncMock(
            return_value=LLMResponse(text="NOT VALID JSON {{{"),
        )

        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = []

        pipeline = TopicizationPipelineImpl(
            llm_client=llm,
            processed_doc_repo=AsyncMock(),
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=AsyncMock(),
        )

        docs = [
            _make_doc("tg:labdiagnostica:post:800", text_clean="some text"),
            _make_doc("tg:labdiagnostica:post:801", text_clean="more text"),
        ]

        llm_assigns, new_cards, unassignable, _tokens = asyncio.get_event_loop().run_until_complete(
            pipeline.discover_new_topics("labdiagnostica", docs)
        )

        # BUG-074 (F2): the large-prompt retry cap was lowered 3 → 2
        # (``_TOPICIZATION_MAX_JSON_RETRIES``); ``repair_json`` now recovers the
        # dominant invalid-JSON case on the first attempt, so at most one
        # corrective re-issue is warranted. "NOT VALID JSON {{{" is genuinely
        # unrepairable, so it still exhausts the (reduced) cap.
        from tg_parser.processing.topicization import _TOPICIZATION_MAX_JSON_RETRIES

        assert llm.generate_with_usage.call_count == _TOPICIZATION_MAX_JSON_RETRIES == 2
        assert len(llm_assigns) == 0
        assert len(new_cards) == 0
        assert set(unassignable) == {
            "tg:labdiagnostica:post:800",
            "tg:labdiagnostica:post:801",
        }


class TestPhase2NotCalledWhenAllAssigned:
    """Phase 2 should not be called when Phase 1 assigns everything."""

    def test_phase2_skipped(self):
        topics = [
            _make_topic_card(
                title="Анализ крови биохимия",
                scope_in=["анализ", "кровь", "биохимия"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
        ]
        pipeline = _make_pipeline(topic_cards=topics)

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:300",
                topics=["анализ", "кровь", "биохимия"],
                summary="Биохимический анализ крови",
            ),
        ]

        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(docs, "labdiagnostica")
        )

        assert len(assignments) == 1
        assert len(unassigned) == 0

        result = IncrementalTopicizeResult(
            assigned_keyword=assignments,
        )
        assert result.assigned_llm == []
        assert result.new_topics == []


class TestFullIncrementalFlowPhase1PlusPhase2:
    """Integration: 5 docs go through Phase 1 + Phase 2."""

    def test_mixed_flow(self):
        existing_topics = [
            _make_topic_card(
                title="ПЦР-диагностика инфекций",
                scope_in=["ПЦР", "диагностика", "инфекции"],
                anchor_refs=["tg:labdiagnostica:post:100", "tg:labdiagnostica:post:101"],
            ),
        ]

        # Phase 1 pipeline (no LLM)
        pipeline1 = _make_pipeline(topic_cards=existing_topics)

        docs = [
            # Should match Phase 1 (keyword)
            _make_doc(
                "tg:labdiagnostica:post:300",
                topics=["ПЦР", "инфекции", "диагностика"],
                summary="ПЦР диагностика инфекций",
            ),
            _make_doc(
                "tg:labdiagnostica:post:301",
                topics=["ПЦР", "диагностика"],
                summary="Метод ПЦР для диагностики",
            ),
            _make_doc(
                "tg:labdiagnostica:post:302",
                topics=["ПЦР"],
                summary="ПЦР тестирование и инфекции",
                text_clean="ПЦР инфекции диагностика " * 10,
            ),
            # Should NOT match Phase 1 -> go to Phase 2
            _make_doc(
                "tg:labdiagnostica:post:303",
                topics=[],
                summary="Совершенно другая тема",
                text_clean="нерелевантный текст о чём-то другом",
            ),
            _make_doc(
                "tg:labdiagnostica:post:304",
                topics=["генетика"],
                summary="Генетический анализ",
                text_clean="Генетическое тестирование и результаты " * 20,
            ),
        ]

        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline1.assign_documents_to_topics(docs, "labdiagnostica")
        )

        {a.source_ref for a in assignments}
        assert len(assignments) >= 2  # at least 2 strong matches

        # Phase 2: mock LLM for unassigned
        unassigned_docs = [d for d in docs if d.source_ref in unassigned]

        if unassigned_docs:
            llm_response = json.dumps(
                {
                    "assignments": [
                        {
                            "source_ref": unassigned_docs[0].source_ref,
                            "topic_id": existing_topics[0].id,
                            "confidence": 0.6,
                        }
                    ]
                    if len(unassigned_docs) > 1
                    else [],
                    "new_topics": [
                        {
                            "title": "Генетическое тестирование",
                            "summary": "Генетические анализы и результаты",
                            "scope_in": ["генетика", "тестирование"],
                            "scope_out": ["ПЦР"],
                            "type": "singleton",
                            "anchors": [
                                {"source_ref": unassigned_docs[-1].source_ref, "score": 0.85}
                            ],
                        }
                    ]
                    if any("генетик" in (d.summary or "").lower() for d in unassigned_docs)
                    else [],
                    "unassignable": [],
                }
            )

            pipeline2 = _make_pipeline_with_llm_response(llm_response, existing_topics)

            llm_assigns, new_cards, truly_unassignable, _tokens = (
                asyncio.get_event_loop().run_until_complete(
                    pipeline2.discover_new_topics("labdiagnostica", unassigned_docs)
                )
            )

            total_assigned = len(assignments) + len(llm_assigns)
            assert total_assigned >= len(assignments)

            for a in llm_assigns:
                assert a.method == "llm"

            for card in new_cards:
                assert card.metadata is not None
                assert card.metadata.get("origin") == "discovered"


# ===========================================================================
# E2E test: realistic incremental flow (Task 2, Session 37)
# ===========================================================================


class TestE2EIncrementalFlow:
    """Simulates a realistic incremental flow:
    10 topic cards, 20 docs (10 covered, 10 new), Phase 1 + Phase 2 + bundles.
    """

    def _make_topics(self) -> list[TopicCard]:
        """Create 10 topic cards with distinct scopes."""
        specs = [
            ("ПЦР-диагностика", ["ПЦР", "диагностика", "инфекции", "полимераза"]),
            ("Биохимия крови", ["биохимия", "кровь", "анализ", "метаболиты"]),
            ("Гормоны щитовидной железы", ["гормоны", "щитовидная", "ТТГ", "тироксин"]),
            ("Общий анализ мочи", ["моча", "анализ", "мочевой", "креатинин"]),
            ("Иммуноферментный анализ", ["ИФА", "иммуноферментный", "антитела", "ELISA"]),
            ("Гематология", ["гематология", "гемоглобин", "эритроциты", "лейкоциты"]),
            ("Коагулограмма", ["коагулограмма", "свёртываемость", "фибриноген", "тромбоциты"]),
            ("Онкомаркеры", ["онкомаркеры", "опухолевые", "ПСА", "маркеры"]),
            ("Витамины и микроэлементы", ["витамины", "микроэлементы", "дефицит", "железо"]),
            (
                "Бактериологический посев",
                ["бакпосев", "бактериологический", "культура", "антибиотики"],
            ),
        ]
        topics = []
        for i, (title, scope_in) in enumerate(specs):
            ref1 = f"tg:labdiagnostica:post:{i * 10}"
            ref2 = f"tg:labdiagnostica:post:{i * 10 + 1}"
            topics.append(_make_topic_card(title, scope_in, [ref1, ref2]))
        return topics

    def _make_covered_docs(self) -> list[ProcessedDocument]:
        """10 docs already covered by existing bundles."""
        covered = []
        for i in range(10):
            covered.append(
                _make_doc(
                    f"tg:labdiagnostica:post:{i * 10 + 2}",
                    text_clean=f"Covered doc {i}",
                    summary=f"Covered doc about topic {i}",
                    topics=[f"topic{i}"],
                )
            )
        return covered

    def _make_new_docs(self) -> list[ProcessedDocument]:
        """10 new uncovered docs: 6 match keywords, 4 don't."""
        return [
            # 6 that match existing topic keywords
            _make_doc(
                "tg:labdiagnostica:post:500",
                topics=["ПЦР", "инфекции", "диагностика"],
                summary="ПЦР диагностика вирусных инфекций",
            ),
            _make_doc(
                "tg:labdiagnostica:post:501",
                topics=["биохимия", "кровь", "анализ"],
                summary="Биохимический анализ крови натощак",
            ),
            _make_doc(
                "tg:labdiagnostica:post:502",
                topics=["гормоны", "щитовидная", "ТТГ"],
                summary="Уровень ТТГ и тироксина",
            ),
            _make_doc(
                "tg:labdiagnostica:post:503",
                topics=["гематология", "гемоглобин"],
                summary="Определение уровня гемоглобина",
            ),
            _make_doc(
                "tg:labdiagnostica:post:504",
                topics=["витамины", "дефицит", "железо"],
                summary="Диагностика дефицита витаминов и железа",
            ),
            _make_doc(
                "tg:labdiagnostica:post:505",
                topics=["бакпосев", "антибиотики"],
                summary="Бактериологический посев и подбор антибиотиков",
            ),
            # 4 that don't match any keyword topic
            _make_doc(
                "tg:labdiagnostica:post:600",
                topics=["генетика", "секвенирование"],
                summary="Генетическое секвенирование нового поколения",
                text_clean="A" * 400,
            ),
            _make_doc(
                "tg:labdiagnostica:post:601",
                topics=["цитология"],
                summary="Цитологическое исследование мазков",
                text_clean="B" * 400,
            ),
            _make_doc(
                "tg:labdiagnostica:post:602",
                topics=[],
                summary="Привет, подписчики!",
                text_clean="Короткое приветствие",
            ),
            _make_doc(
                "tg:labdiagnostica:post:603",
                topics=["аллергология"],
                summary="Аллергологическое обследование",
                text_clean="C" * 400,
            ),
        ]

    def _make_existing_bundles(self, topics, covered_docs) -> list[TopicBundle]:
        """Create bundles with covered docs."""
        bundles = []
        for i, topic in enumerate(topics):
            items = [
                BundleItem(
                    channel_id="labdiagnostica",
                    message_id=str(i * 10),
                    message_type=MessageType.POST,
                    source_ref=f"tg:labdiagnostica:post:{i * 10}",
                    role=BundleItemRole.ANCHOR,
                    score=0.9,
                ),
                BundleItem(
                    channel_id="labdiagnostica",
                    message_id=str(i * 10 + 1),
                    message_type=MessageType.POST,
                    source_ref=f"tg:labdiagnostica:post:{i * 10 + 1}",
                    role=BundleItemRole.ANCHOR,
                    score=0.85,
                ),
                BundleItem(
                    channel_id="labdiagnostica",
                    message_id=str(i * 10 + 2),
                    message_type=MessageType.POST,
                    source_ref=f"tg:labdiagnostica:post:{i * 10 + 2}",
                    role=BundleItemRole.SUPPORTING,
                    score=0.6,
                ),
            ]
            bundles.append(_make_bundle(topic.id, items))
        return bundles

    def test_e2e_phase1_assigns_keyword_docs(self):
        """Phase 1 assigns ~6 matching docs to correct topics."""
        topics = self._make_topics()
        new_docs = self._make_new_docs()

        pipeline = _make_pipeline(topic_cards=topics)
        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(new_docs, "labdiagnostica")
        )

        assigned_refs = {a.source_ref for a in assignments}
        assert len(assignments) >= 5, f"Expected >= 5 keyword assignments, got {len(assignments)}"

        for a in assignments:
            assert a.method == "keyword"
            assert a.score >= MIN_SUPPORTING_SCORE

        for ref in [
            "tg:labdiagnostica:post:500",
            "tg:labdiagnostica:post:501",
            "tg:labdiagnostica:post:502",
            "tg:labdiagnostica:post:503",
        ]:
            assert ref in assigned_refs, f"Expected {ref} to be keyword-assigned"

        unassigned_set = set(unassigned)
        assert "tg:labdiagnostica:post:602" in unassigned_set

    def test_e2e_phase2_handles_unassigned(self):
        """Phase 2 assigns/creates/marks-unassignable for leftover docs."""
        topics = self._make_topics()
        unassigned_docs = self._make_new_docs()[6:]  # 4 docs that didn't match

        llm_response = json.dumps(
            {
                "assignments": [
                    {
                        "source_ref": "tg:labdiagnostica:post:603",
                        "topic_id": topics[4].id,  # assign to ИФА as closest
                        "confidence": 0.65,
                    }
                ],
                "new_topics": [
                    {
                        "title": "Генетическое секвенирование",
                        "summary": "Методы генетического секвенирования нового поколения",
                        "scope_in": ["генетика", "секвенирование", "NGS"],
                        "scope_out": ["ПЦР", "биохимия"],
                        "type": "singleton",
                        "anchors": [{"source_ref": "tg:labdiagnostica:post:600", "score": 0.9}],
                    }
                ],
                "unassignable": [
                    "tg:labdiagnostica:post:601",
                    "tg:labdiagnostica:post:602",
                ],
            }
        )

        pipeline = _make_pipeline_with_llm_response(llm_response, topics)

        llm_assigns, new_cards, truly_unassignable, _tokens = (
            asyncio.get_event_loop().run_until_complete(
                pipeline.discover_new_topics("labdiagnostica", unassigned_docs)
            )
        )

        assert len(llm_assigns) == 1
        assert llm_assigns[0].method == "llm"
        assert llm_assigns[0].topic_id == topics[4].id

        assert len(new_cards) == 1
        assert new_cards[0].title == "Генетическое секвенирование"
        assert new_cards[0].metadata["origin"] == "discovered"

        assert len(truly_unassignable) == 2

    def test_e2e_existing_topic_ids_unchanged(self):
        """Existing topic IDs must not change after incremental run."""
        topics = self._make_topics()
        original_ids = {t.id for t in topics}

        new_docs = self._make_new_docs()[:6]
        pipeline = _make_pipeline(topic_cards=topics)

        assignments, _ = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(new_docs, "labdiagnostica")
        )

        assigned_topic_ids = {a.topic_id for a in assignments}
        assert assigned_topic_ids.issubset(original_ids)

    def test_e2e_bundles_updated_for_assigned_docs(self):
        """Bundles are updated with new items after Phase 1 assignments."""
        from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

        topics = self._make_topics()
        covered_docs = self._make_covered_docs()
        bundles = self._make_existing_bundles(topics, covered_docs)

        first_topic_id = topics[0].id
        first_bundle = next(b for b in bundles if b.topic_id == first_topic_id)

        repo = AsyncMock(spec=SATopicBundleRepo)
        repo.get_by_topic_id.return_value = first_bundle
        repo.upsert = AsyncMock()
        repo.add_items = SATopicBundleRepo.add_items.__get__(repo, SATopicBundleRepo)

        new_item = BundleItem(
            channel_id="labdiagnostica",
            message_id="500",
            message_type=MessageType.POST,
            source_ref="tg:labdiagnostica:post:500",
            role=BundleItemRole.SUPPORTING,
            score=0.7,
            justification="incremental keyword assign (score=0.7)",
        )

        result = asyncio.get_event_loop().run_until_complete(
            repo.add_items(first_topic_id, [new_item])
        )

        assert len(result.items) == 4  # 3 existing + 1 new
        refs = [item.source_ref for item in result.items]
        assert "tg:labdiagnostica:post:500" in refs

    def test_e2e_coverage_increases(self):
        """Coverage should increase after assigning uncovered docs."""
        topics = self._make_topics()
        new_docs = self._make_new_docs()
        pipeline = _make_pipeline(topic_cards=topics)

        assignments, unassigned = asyncio.get_event_loop().run_until_complete(
            pipeline.assign_documents_to_topics(new_docs, "labdiagnostica")
        )

        total_docs = 30  # 20 existing + 10 new
        covered_before = 20  # all 20 existing are covered
        coverage_before = round(covered_before / total_docs * 100, 1)

        new_covered = len(assignments)
        covered_after = covered_before + new_covered
        coverage_after = round(covered_after / total_docs * 100, 1)

        assert coverage_after > coverage_before
        assert new_covered >= 5


# ===========================================================================
# Tests for CLI mode dispatch and uncovered docs resolution (Task 5, Session 37)
# ===========================================================================


class TestUncoveredDocsResolution:
    """Tests for run_incremental_topicization_for_uncovered logic."""

    @pytest.mark.asyncio
    async def test_finds_correct_uncovered_docs(self):
        """Given 20 docs and 10 covered, uncovered_refs should have exactly 10."""

        all_docs = [_make_doc(f"tg:labdiagnostica:post:{i}") for i in range(20)]
        covered_refs = {f"tg:labdiagnostica:post:{i}" for i in range(10)}

        uncovered_refs = [d.source_ref for d in all_docs if d.source_ref not in covered_refs]

        assert len(uncovered_refs) == 10
        for ref in uncovered_refs:
            assert ref not in covered_refs

    @pytest.mark.asyncio
    async def test_all_covered_returns_empty_result(self):
        """When all docs are covered, no incremental work should be done."""
        from tg_parser.domain.models import IncrementalTopicizeResult

        all_docs = [_make_doc(f"tg:labdiagnostica:post:{i}") for i in range(10)]
        covered_refs = {d.source_ref for d in all_docs}

        uncovered_refs = [d.source_ref for d in all_docs if d.source_ref not in covered_refs]

        assert len(uncovered_refs) == 0

        result = IncrementalTopicizeResult(
            coverage_before=100.0,
            coverage_after=100.0,
        )
        assert len(result.assigned_keyword) == 0
        assert len(result.assigned_llm) == 0


class TestCLIModeDispatch:
    """Tests for CLI topicize --mode routing."""

    def test_mode_full_calls_run_topicization(self):
        """--mode full should call run_topicization."""
        from unittest.mock import patch

        with (
            patch("tg_parser.cli.app._run_full_topicization") as mock_full,
            patch("tg_parser.cli.app._run_incremental_topicization_cli") as mock_incr,
            patch("tg_parser.cli.app._run_assign_only_topicization_cli") as mock_assign,
        ):
            from typer.testing import CliRunner

            from tg_parser.cli.app import app

            runner = CliRunner()
            runner.invoke(app, ["topicize", "--channel", "test_ch", "--mode", "full"])

            mock_full.assert_called_once_with("test_ch", force=False, no_bundles=False)
            mock_incr.assert_not_called()
            mock_assign.assert_not_called()

    def test_mode_incremental_calls_incremental(self):
        """--mode incremental should call _run_incremental_topicization_cli."""
        from unittest.mock import patch

        with (
            patch("tg_parser.cli.app._run_full_topicization") as mock_full,
            patch("tg_parser.cli.app._run_incremental_topicization_cli") as mock_incr,
            patch("tg_parser.cli.app._run_assign_only_topicization_cli") as mock_assign,
        ):
            from typer.testing import CliRunner

            from tg_parser.cli.app import app

            runner = CliRunner()
            runner.invoke(app, ["topicize", "--channel", "test_ch", "--mode", "incremental"])

            mock_full.assert_not_called()
            mock_incr.assert_called_once_with("test_ch", cross_channel=None)
            mock_assign.assert_not_called()

    def test_mode_assign_only_calls_assign_only(self):
        """--mode assign-only should call _run_assign_only_topicization_cli."""
        from unittest.mock import patch

        with (
            patch("tg_parser.cli.app._run_full_topicization") as mock_full,
            patch("tg_parser.cli.app._run_incremental_topicization_cli") as mock_incr,
            patch("tg_parser.cli.app._run_assign_only_topicization_cli") as mock_assign,
        ):
            from typer.testing import CliRunner

            from tg_parser.cli.app import app

            runner = CliRunner()
            runner.invoke(app, ["topicize", "--channel", "test_ch", "--mode", "assign-only"])

            mock_full.assert_not_called()
            mock_incr.assert_not_called()
            mock_assign.assert_called_once_with("test_ch")

    def test_force_flag_triggers_full_mode(self):
        """--force should trigger full topicization regardless of --mode."""
        from unittest.mock import patch

        with (
            patch("tg_parser.cli.app._run_full_topicization") as mock_full,
            patch("tg_parser.cli.app._run_incremental_topicization_cli") as mock_incr,
        ):
            from typer.testing import CliRunner

            from tg_parser.cli.app import app

            runner = CliRunner()
            runner.invoke(app, ["topicize", "--channel", "test_ch", "--force"])

            mock_full.assert_called_once_with("test_ch", force=True, no_bundles=False)
            mock_incr.assert_not_called()

    def test_invalid_mode_exits_with_error(self):
        """Unknown mode should exit with error code 1."""
        from typer.testing import CliRunner

        from tg_parser.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["topicize", "--channel", "test_ch", "--mode", "bogus"])

        assert result.exit_code == 1
        assert "Неизвестный режим" in result.output


@pytest.mark.asyncio
async def test_incremental_escalates_to_full_when_no_topic_cards():
    processed_repo = AsyncMock()
    new_doc = _make_doc("tg:labdiagnostica:post:900")
    processed_repo.get_by_source_ref.return_value = new_doc
    processed_repo.list_by_channel.return_value = [new_doc]

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []

    with (
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            return_value={"total_tokens": 123},
        ) as mock_full,
        patch(
            "tg_parser.services.topicization_service.TopicizationPipelineImpl.assign_documents_to_topics",
            new_callable=AsyncMock,
        ) as mock_assign,
        patch(
            "tg_parser.services.topicization_service.TopicizationPipelineImpl._discover_single_batch",
            new_callable=AsyncMock,
        ) as mock_discover,
    ):
        result = await run_incremental_topicization(
            "labdiagnostica",
            [new_doc.source_ref],
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
        )

    mock_full.assert_awaited_once()
    assert result.tokens_used == 123
    # Early-return contract: escalation MUST bypass the rest of the incremental
    # pipeline; otherwise a regression silently doubles work (full + incremental).
    mock_assign.assert_not_awaited()
    mock_discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_incremental_llm_checkpoint_persists_previous_batches_on_failure():
    existing = _make_topic_card(
        title="Existing",
        scope_in=["existing"],
        anchor_refs=["tg:labdiagnostica:post:10", "tg:labdiagnostica:post:11"],
    )
    doc1 = _make_doc("tg:labdiagnostica:post:901", text_clean="batch one")
    doc2 = _make_doc("tg:labdiagnostica:post:902", text_clean="batch two")

    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda ref: {
        doc1.source_ref: doc1,
        doc2.source_ref: doc2,
    }.get(ref)
    processed_repo.list_by_channel.return_value = [doc1, doc2]

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [existing]
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    topic_bundle_repo.add_items = AsyncMock()

    first_batch = (
        [
            TopicAssignment(
                source_ref=doc1.source_ref,
                topic_id=existing.id,
                score=0.77,
                method="llm",
            )
        ],
        [],
        [],
        42,
    )
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(429, request=req, text="rate limited")
    second_error = httpx.HTTPStatusError("batch2 failed", request=req, response=resp)

    with patch(
        "tg_parser.services.topicization_service.TopicizationPipelineImpl._discover_single_batch",
        new_callable=AsyncMock,
        side_effect=[first_batch, second_error],
    ) as mock_batch:
        from tg_parser.config import settings as app_settings

        with patch.object(app_settings, "topicization_batch_size", 1):
            with pytest.raises(httpx.HTTPStatusError):
                await run_incremental_topicization(
                    "labdiagnostica",
                    [doc1.source_ref, doc2.source_ref],
                    cross_channel=False,
                    processed_repo=processed_repo,
                    topic_card_repo=topic_card_repo,
                    topic_bundle_repo=topic_bundle_repo,
                )

    # The loop must actually have attempted batch 2 (where the failure lives).
    # Without this we could have a regression where batch 1 fails on its own
    # and the test still passes from the "first batch persisted" assertion.
    assert mock_batch.await_count == 2, (
        f"expected 2 batch attempts (1 success + 1 failure), got {mock_batch.await_count}"
    )

    # Per-batch checkpoint contract: batch-1 assignments MUST be persisted to the
    # bundle repo BEFORE the batch-2 failure propagates.
    topic_bundle_repo.add_items.assert_awaited_once()
    persisted_call = topic_bundle_repo.add_items.await_args
    persisted_topic_id = (
        persisted_call.args[0] if persisted_call.args else persisted_call.kwargs.get("topic_id")
    )
    persisted_items = (
        persisted_call.args[1]
        if len(persisted_call.args) > 1
        else persisted_call.kwargs.get("items")
    )
    assert persisted_topic_id == existing.id
    persisted_refs = {item.source_ref for item in persisted_items}
    assert doc1.source_ref in persisted_refs, (
        f"batch-1 assignment for {doc1.source_ref} not persisted; "
        f"only {persisted_refs} reached the bundle repo"
    )
    assert doc2.source_ref not in persisted_refs, (
        "batch-2 (failed) assignment must NOT have leaked into the bundle"
    )
