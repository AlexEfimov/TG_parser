"""
Tests for topicization pipeline (Session 33).

Covers: _tokenize, _find_supporting_items_programmatic, settings wiring, coverage metric.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.domain.models import (
    Anchor,
    BundleItemRole,
    MessageType,
    ProcessedDocument,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.topicization import (
    MAX_ANCHORS_PER_CLUSTER,
    MAX_SUPPORTING_ITEMS,
    MIN_CLUSTER_SCORE,
    MIN_SINGLETON_LENGTH,
    MIN_SINGLETON_SCORE,
    MIN_SUPPORTING_SCORE,
    MIN_TOKEN_LENGTH,
    TEXT_CLEAN_MATCH_CHARS,
    TopicizationPipelineImpl,
)


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
) -> TopicCard:
    anchors = []
    for ref in anchor_refs:
        parts = ref.split(":")
        anchors.append(Anchor(
            channel_id=parts[1],
            message_id=parts[3],
            message_type=MessageType(parts[2]),
            anchor_ref=ref,
            score=0.9,
        ))
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
        sources=["labdiagnostica"],
        updated_at=datetime.now(UTC),
    )


def _make_pipeline() -> TopicizationPipelineImpl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=AsyncMock(),
        topic_bundle_repo=AsyncMock(),
    )


# ===========================================================================
# _tokenize tests
# ===========================================================================

class TestTokenize:
    """Tests for TopicizationPipelineImpl._tokenize."""

    def test_short_medical_terms_captured(self):
        """Short medical abbreviations (2-3 chars) must be captured."""
        tokens = TopicizationPipelineImpl._tokenize("СОЭ повышен, ТТГ в норме")
        assert "соэ" in tokens
        assert "ттг" in tokens

    def test_latin_short_terms(self):
        """Latin abbreviations like IgE, IgG must be captured."""
        tokens = TopicizationPipelineImpl._tokenize("Повышен IgE и IgG")
        assert "ige" in tokens
        assert "igg" in tokens

    def test_long_words_still_captured(self):
        """Regular long words must still be captured."""
        tokens = TopicizationPipelineImpl._tokenize("Гематология анализ крови")
        assert "гематология" in tokens
        assert "анализ" in tokens
        assert "крови" in tokens

    def test_numbers_excluded(self):
        """Numeric strings should not appear in tokens."""
        tokens = TopicizationPipelineImpl._tokenize("123 мг/дл уровень 5.5")
        assert not any(t.isdigit() for t in tokens)

    def test_empty_string(self):
        tokens = TopicizationPipelineImpl._tokenize("")
        assert tokens == set()

    def test_min_token_length_respected(self):
        """All returned tokens must be >= MIN_TOKEN_LENGTH chars."""
        tokens = TopicizationPipelineImpl._tokenize("а б слово ДНК IgE test")
        for t in tokens:
            assert len(t) >= MIN_TOKEN_LENGTH

    def test_mixed_cyrillic_latin(self):
        """Cyrillic and Latin tokens extracted separately."""
        tokens = TopicizationPipelineImpl._tokenize("ПЦР тест PCR test")
        assert "пцр" in tokens
        assert "pcr" in tokens
        assert "тест" in tokens
        assert "test" in tokens


# ===========================================================================
# Settings wiring tests
# ===========================================================================

class TestSettingsWiring:
    """Verify constants are read from settings, not hardcoded."""

    def test_min_supporting_score_from_settings(self):
        from tg_parser.config.settings import settings
        assert MIN_SUPPORTING_SCORE == settings.topicization_supporting_min_score

    def test_max_supporting_items_from_settings(self):
        from tg_parser.config.settings import settings
        assert MAX_SUPPORTING_ITEMS == settings.topicization_max_supporting_items

    def test_max_anchors_from_settings(self):
        from tg_parser.config.settings import settings
        assert MAX_ANCHORS_PER_CLUSTER == settings.topicization_top_n_anchors

    def test_min_singleton_score_from_settings(self):
        from tg_parser.config.settings import settings
        assert MIN_SINGLETON_SCORE == settings.topicization_singleton_min_score

    def test_min_singleton_length_from_settings(self):
        from tg_parser.config.settings import settings
        assert MIN_SINGLETON_LENGTH == settings.topicization_singleton_min_len

    def test_min_cluster_score_from_settings(self):
        from tg_parser.config.settings import settings
        assert MIN_CLUSTER_SCORE == settings.topicization_cluster_min_anchor_score

    def test_min_token_length_from_settings(self):
        from tg_parser.config.settings import settings
        assert MIN_TOKEN_LENGTH == settings.topicization_min_token_length

    def test_text_clean_match_chars_from_settings(self):
        from tg_parser.config.settings import settings
        assert TEXT_CLEAN_MATCH_CHARS == settings.topicization_text_clean_match_chars


# ===========================================================================
# _find_supporting_items_programmatic tests
# ===========================================================================

class TestFindSupportingItems:
    """Tests for programmatic keyword matching."""

    def test_text_clean_matching_finds_documents(self):
        """Documents with matching keywords only in text_clean should be found."""
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="ПЦР-диагностика инфекций",
            scope_in=["ПЦР", "диагностика", "инфекции"],
            anchor_refs=["tg:labdiagnostica:post:100"],
        )

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:100",
                text_clean="Anchor post about ПЦР",
            ),
            _make_doc(
                "tg:labdiagnostica:post:200",
                text_clean="В этом посте рассматривается ПЦР диагностика различных инфекций",
                summary="Общий обзор",
                topics=[],
            ),
        ]

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:100"},
            documents=docs,
        )

        refs = {item.source_ref for item in items}
        assert "tg:labdiagnostica:post:200" in refs

    def test_anchor_excluded_from_supporting(self):
        """Anchor documents must not appear in supporting items."""
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="Гематология",
            scope_in=["гематология", "кровь"],
            anchor_refs=["tg:labdiagnostica:post:1"],
        )

        docs = [
            _make_doc(
                "tg:labdiagnostica:post:1",
                text_clean="гематология и анализ крови",
                topics=["гематология"],
            ),
        ]

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:1"},
            documents=docs,
        )
        assert len(items) == 0

    def test_max_supporting_items_limit(self):
        """Number of supporting items must not exceed MAX_SUPPORTING_ITEMS."""
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="Анализ крови",
            scope_in=["анализ", "кровь"],
            anchor_refs=["tg:labdiagnostica:post:1"],
        )

        docs = [_make_doc("tg:labdiagnostica:post:1", topics=["анализ"])]
        for i in range(2, 102):
            docs.append(_make_doc(
                f"tg:labdiagnostica:post:{i}",
                text_clean="подробный анализ крови пациента",
                topics=["анализ", "кровь"],
            ))

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:1"},
            documents=docs,
        )
        assert len(items) <= MAX_SUPPORTING_ITEMS

    def test_supporting_items_sorted_by_score_desc(self):
        """Supporting items must be sorted by score descending."""
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="Биохимия крови витамин гормон ферменты",
            scope_in=["биохимия", "кровь", "витамин", "гормон", "ферменты"],
            anchor_refs=["tg:labdiagnostica:post:1"],
        )

        docs = [_make_doc("tg:labdiagnostica:post:1")]
        docs.append(_make_doc(
            "tg:labdiagnostica:post:2",
            topics=["биохимия"],
        ))
        docs.append(_make_doc(
            "tg:labdiagnostica:post:3",
            topics=["биохимия", "кровь", "витамин"],
        ))

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:1"},
            documents=docs,
        )

        if len(items) >= 2:
            scores = [item.score for item in items]
            assert scores == sorted(scores, reverse=True)

    def test_low_score_below_threshold_excluded(self):
        """Documents with score below MIN_SUPPORTING_SCORE should be excluded."""
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="Очень специфическая длинная тема про редкие болезни крови",
            scope_in=[
                "редкие", "болезни", "крови", "генетика",
                "мутации", "наследственность", "синдром",
                "трансфузиология", "гемоглобинопатии", "талассемия",
            ],
            anchor_refs=["tg:labdiagnostica:post:1"],
        )

        docs = [
            _make_doc("tg:labdiagnostica:post:1"),
            _make_doc(
                "tg:labdiagnostica:post:2",
                topics=["крови"],
                summary="",
                text_clean="short",
            ),
        ]

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:1"},
            documents=docs,
        )

        for item in items:
            assert item.score >= MIN_SUPPORTING_SCORE

    def test_supporting_items_have_justification(self):
        """Each supporting item must include a keyword overlap justification."""
        pipeline = _make_pipeline()

        topic = _make_topic_card(
            title="Анализ крови",
            scope_in=["анализ", "кровь"],
            anchor_refs=["tg:labdiagnostica:post:1"],
        )

        docs = [
            _make_doc("tg:labdiagnostica:post:1"),
            _make_doc(
                "tg:labdiagnostica:post:2",
                topics=["анализ", "кровь"],
            ),
        ]

        items = pipeline._find_supporting_items_programmatic(
            topic_card=topic,
            anchor_refs={"tg:labdiagnostica:post:1"},
            documents=docs,
        )

        for item in items:
            assert item.justification is not None
            assert "keyword overlap" in item.justification


# ===========================================================================
# Coverage metric test
# ===========================================================================

class TestCoverageMetric:
    """Tests for _compute_coverage from topicization_service."""

    def test_coverage_computation(self):
        from tg_parser.services.topicization_service import _compute_coverage

        doc1 = _make_doc("tg:ch:post:1")
        doc2 = _make_doc("tg:ch:post:2")
        doc3 = _make_doc("tg:ch:post:3")

        from tg_parser.domain.models import BundleItem

        bundle = TopicBundle(
            topic_id="topic:tg:ch:post:1",
            items=[
                BundleItem(
                    channel_id="ch", message_id="1",
                    message_type=MessageType.POST,
                    source_ref="tg:ch:post:1",
                    role=BundleItemRole.ANCHOR, score=1.0,
                ),
                BundleItem(
                    channel_id="ch", message_id="2",
                    message_type=MessageType.POST,
                    source_ref="tg:ch:post:2",
                    role=BundleItemRole.SUPPORTING, score=0.5,
                ),
            ],
            updated_at=datetime.now(UTC),
        )

        processed_repo = AsyncMock()
        processed_repo.list_by_channel.return_value = [doc1, doc2, doc3]

        bundle_repo = AsyncMock()
        bundle_repo.list_by_channel.return_value = [bundle]

        result = asyncio.get_event_loop().run_until_complete(
            _compute_coverage(processed_repo, bundle_repo, "ch")
        )

        assert result["total_documents"] == 3
        assert result["covered_documents"] == 2
        assert result["uncovered_documents"] == 1
        assert abs(result["coverage_pct"] - 66.7) < 0.1

    def test_coverage_empty_channel(self):
        from tg_parser.services.topicization_service import _compute_coverage

        processed_repo = AsyncMock()
        processed_repo.list_by_channel.return_value = []

        bundle_repo = AsyncMock()
        bundle_repo.list_by_channel.return_value = []

        result = asyncio.get_event_loop().run_until_complete(
            _compute_coverage(processed_repo, bundle_repo, "ch")
        )

        assert result["total_documents"] == 0
        assert result["coverage_pct"] == 0.0

    def test_coverage_full(self):
        from tg_parser.services.topicization_service import _compute_coverage
        from tg_parser.domain.models import BundleItem

        docs = [_make_doc(f"tg:ch:post:{i}") for i in range(1, 4)]

        bundle = TopicBundle(
            topic_id="topic:tg:ch:post:1",
            items=[
                BundleItem(
                    channel_id="ch", message_id=str(i),
                    message_type=MessageType.POST,
                    source_ref=f"tg:ch:post:{i}",
                    role=BundleItemRole.SUPPORTING, score=0.5,
                )
                for i in range(1, 4)
            ],
            updated_at=datetime.now(UTC),
        )

        processed_repo = AsyncMock()
        processed_repo.list_by_channel.return_value = docs

        bundle_repo = AsyncMock()
        bundle_repo.list_by_channel.return_value = [bundle]

        result = asyncio.get_event_loop().run_until_complete(
            _compute_coverage(processed_repo, bundle_repo, "ch")
        )

        assert result["total_documents"] == 3
        assert result["covered_documents"] == 3
        assert result["coverage_pct"] == 100.0
        assert result["uncovered_documents"] == 0
