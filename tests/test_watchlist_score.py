"""Pure-unit tests for the F11 scoring helpers (no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
)
from tg_parser.services.watchlist_service import (
    KEYWORD_WEIGHT,
    SEMANTIC_WEIGHT,
    WatchScore,
    _build_doc_tokens,
    _cosine,
    _keyword_score,
    _tokenize,
    build_canonical_interest_text,
    compute_watch_score,
)

# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


def _make_interest(
    *,
    keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    embedding: list[float] | None = None,
    threshold: float = 0.6,
    description: str | None = "Watch for crypto regulation news",
) -> WatchInterest:
    return WatchInterest(
        id="00000000-0000-0000-0000-000000000010",
        user_id="00000000-0000-0000-0000-000000000001",
        chat_id=12345,
        title="MiCA / EU crypto regulation",
        description=description,
        keywords=list(keywords or []),
        exclude_keywords=list(exclude_keywords or []),
        channel_ids=["@crypto_news"],
        threshold=threshold,
        notify_mode=NotifyMode.INSTANT,
        is_active=True,
        embedding=embedding,
    )


def _make_doc(
    *,
    text: str,
    summary: str | None = None,
    topics: list[str] | None = None,
    source_ref: str = "tg:crypto_news:post:1",
    channel_id: str = "crypto_news",
) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id="1",
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=text,
        summary=summary,
        topics=list(topics or []),
    )


# ----------------------------------------------------------------------------
# Tokenizer
# ----------------------------------------------------------------------------


class TestTokenize:
    def test_basic_lowercases_and_splits(self):
        assert _tokenize("Hello World") == {"hello", "world"}

    def test_keeps_short_abbreviations(self):
        # MIN_TOKEN_LENGTH=2 — must keep MiCA, ETF, ЦБ.
        tokens = _tokenize("MiCA ETF ЦБ Foo")
        assert "mica" in tokens
        assert "etf" in tokens
        assert "цб" in tokens
        assert "foo" in tokens

    def test_keeps_digits(self):
        tokens = _tokenize("PSD3 NIS2 Basel3")
        assert "psd3" in tokens
        assert "nis2" in tokens
        assert "basel3" in tokens

    def test_drops_single_char_tokens(self):
        # MIN_TOKEN_LENGTH=2 → "I" is dropped.
        assert _tokenize("I am") == {"am"}

    def test_empty_input(self):
        assert _tokenize("") == set()
        assert _tokenize(None) == set()

    def test_strips_punctuation(self):
        assert _tokenize("hello, world!") == {"hello", "world"}


# ----------------------------------------------------------------------------
# Doc-token builder (graceful degradation)
# ----------------------------------------------------------------------------


class TestBuildDocTokens:
    def test_combines_topics_summary_text(self):
        doc = _make_doc(
            text="MiCA enters into force in EU",
            summary="EU crypto law update",
            topics=["regulation", "europe"],
        )
        tokens = _build_doc_tokens(doc)
        # From topics
        assert "regulation" in tokens
        # From summary
        assert "update" in tokens
        # From text_clean
        assert "mica" in tokens
        assert "force" in tokens

    def test_works_without_summary_or_topics(self):
        # gotcha #10 graceful degradation: topicization may not have run.
        doc = _make_doc(text="Some pure raw text", summary=None, topics=[])
        tokens = _build_doc_tokens(doc)
        assert tokens == {"some", "pure", "raw", "text"}


# ----------------------------------------------------------------------------
# Keyword scorer
# ----------------------------------------------------------------------------


class TestKeywordScore:
    def test_full_match_returns_one(self):
        assert _keyword_score({"a", "b", "c"}, {"a", "b", "c", "d"}) == 1.0

    def test_partial_match_recall_like(self):
        # 2 of 4 interest keywords present → 0.5
        assert _keyword_score({"a", "b", "c", "d"}, {"a", "b", "x"}) == 0.5

    def test_no_overlap(self):
        assert _keyword_score({"a", "b"}, {"x", "y"}) == 0.0

    def test_empty_interest_returns_zero(self):
        assert _keyword_score(set(), {"a", "b"}) == 0.0

    def test_extra_doc_tokens_do_not_dilute(self):
        # Recall-like (not Jaccard): doc with many extra tokens still scores 1.0
        # when all interest keywords are present.
        score = _keyword_score({"a"}, {"a", "b", "c", "d", "e", "f", "g"})
        assert score == 1.0


# ----------------------------------------------------------------------------
# Cosine
# ----------------------------------------------------------------------------


class TestCosine:
    def test_identical_vectors(self):
        v = [0.5, 0.5, 0.5, 0.5]
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_negative_clipped_to_zero(self):
        # Anti-parallel → -1.0 → clipped to 0.
        assert _cosine([1.0, 0.0], [-1.0, 0.0]) == 0.0

    def test_mismatched_length_returns_zero(self):
        assert _cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0

    def test_empty_vector_returns_zero(self):
        assert _cosine([], [1.0]) == 0.0
        assert _cosine([1.0], []) == 0.0

    def test_zero_norm_returns_zero(self):
        assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# ----------------------------------------------------------------------------
# compute_watch_score (the headline function)
# ----------------------------------------------------------------------------


class TestComputeWatchScore:
    def test_pure_keyword_when_no_embeddings(self):
        interest = _make_interest(keywords=["mica", "regulation"], embedding=None)
        doc = _make_doc(text="MiCA regulation in EU", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=None)
        assert score.semantic_available is False
        assert score.keyword == pytest.approx(1.0)
        assert score.semantic == 0.0
        assert score.combined == pytest.approx(1.0)
        assert score.excluded is False

    def test_combined_formula_uses_weights(self):
        # interest embedding identical to doc embedding → semantic = 1.0
        # keywords: 1 of 2 hit → keyword = 0.5
        # combined = 0.4 * 0.5 + 0.6 * 1.0 = 0.8
        emb = [0.1] * 1536
        interest = _make_interest(
            keywords=["mica", "psd3"],
            embedding=emb,
        )
        doc = _make_doc(text="MiCA discussion in EU", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=emb)
        expected = KEYWORD_WEIGHT * 0.5 + SEMANTIC_WEIGHT * 1.0
        assert score.combined == pytest.approx(expected)
        assert score.semantic_available is True

    def test_excluded_zeroes_combined_even_when_keywords_match(self):
        interest = _make_interest(
            keywords=["mica"],
            exclude_keywords=["meme"],
            embedding=[0.1] * 1536,
        )
        doc = _make_doc(text="MiCA meme news", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=[0.1] * 1536)
        assert score.excluded is True
        assert score.combined == 0.0
        # keyword/semantic components are still reported for telemetry
        assert score.keyword > 0.0

    def test_below_threshold_when_only_partial_keyword(self):
        # 1 of 4 interest keywords matches → 0.25 combined
        # (no embeddings so combined == keyword == 0.25 < default 0.6)
        interest = _make_interest(keywords=["mica", "psd3", "nis2", "dora"], embedding=None)
        doc = _make_doc(text="MiCA only update", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=None)
        assert score.keyword == pytest.approx(0.25)
        assert score.combined == pytest.approx(0.25)
        assert score.combined < interest.threshold

    def test_combined_capped_to_one(self):
        # Construct a degenerate case: keyword > 1 is impossible but defend
        # against rounding above 1.0 from float math.
        interest = _make_interest(keywords=["a"], embedding=[1.0])
        doc = _make_doc(text="A b c d e f g", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=[1.0])
        assert 0.0 <= score.combined <= 1.0


# ----------------------------------------------------------------------------
# Canonical interest text
# ----------------------------------------------------------------------------


class TestBuildCanonicalInterestText:
    def test_uses_description_first(self):
        interest = _make_interest(
            description="Long-form intent",
            keywords=["a", "b"],
        )
        result = build_canonical_interest_text(interest)
        assert result.startswith("Long-form intent")
        assert "MiCA" in result  # title
        assert "a b" in result  # keywords joined

    def test_falls_back_to_title_and_keywords_when_description_missing(self):
        interest = _make_interest(
            description=None,
            keywords=["mica"],
        )
        result = build_canonical_interest_text(interest)
        assert "MiCA" in result
        assert "mica" in result

    def test_never_returns_empty_even_without_keywords_or_description(self):
        interest = _make_interest(description=None, keywords=[])
        result = build_canonical_interest_text(interest)
        assert result.strip() != ""
        assert "MiCA" in result

    def test_strips_blank_keywords(self):
        interest = _make_interest(
            description=None,
            keywords=["a", "   ", "b"],
        )
        result = build_canonical_interest_text(interest)
        # The two non-blank keywords should be present without the blank
        assert "a b" in result


# ----------------------------------------------------------------------------
# WatchScore dataclass invariants
# ----------------------------------------------------------------------------


class TestWatchScoreDataclass:
    def test_is_frozen(self):
        score = WatchScore(
            keyword=0.5,
            semantic=0.6,
            combined=0.56,
            excluded=False,
            semantic_available=True,
        )
        with pytest.raises((AttributeError, TypeError)):
            score.combined = 1.0  # type: ignore[misc]
