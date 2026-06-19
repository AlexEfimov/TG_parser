"""Pure-unit tests for the F11 scoring helpers (no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tg_parser.api.metrics import WATCHLIST_SEMANTIC_UNAVAILABLE
from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
)
from tg_parser.services.watchlist_service import (
    KEYWORD_AGGREGATION_DEFAULT,
    KEYWORD_TOPK_DEFAULT,
    KEYWORD_WEIGHT,
    SEMANTIC_WEIGHT,
    WatchScore,
    _aggregate_keyword_score,
    _build_doc_tokens,
    _cosine,
    _keyword_hits_total,
    _keyword_score,
    _tokenize,
    build_canonical_interest_text,
    compute_watch_score,
)
from tg_parser.services.watchlist_tokenizer import normalize_token, normalize_tokens

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
    # DIAG 2026-06-07: ``_keyword_score`` now takes the raw keyword *phrases*
    # (list[str]) and tokenises each internally, rather than a pre-tokenised
    # set. Each keyword is an atomic phrase; the denominator is the phrase
    # count. Tokens shorter than MIN_TOKEN_LENGTH (2) are dropped, so these
    # tests use realistic >=2-char keywords.
    def test_full_match_returns_one(self):
        assert _keyword_score(["mica", "psd3", "dora"], {"mica", "psd3", "dora", "etf"}) == 1.0

    def test_partial_match_recall_like(self):
        # Mean-math verification (ADR 0010): 2 of 4 keyword phrases present →
        # 0.5. The default scheme is now "topk" (which would give 2/3 here), so
        # this test pins aggregation="mean" to keep asserting the recall
        # fraction directly.
        assert (
            _keyword_score(
                ["mica", "psd3", "nis2", "dora"],
                {"mica", "psd3", "etf"},
                aggregation="mean",
            )
            == 0.5
        )

    def test_no_overlap(self):
        assert _keyword_score(["mica", "psd3"], {"etf", "swap"}) == 0.0

    def test_empty_interest_returns_zero(self):
        assert _keyword_score([], {"mica", "psd3"}) == 0.0

    def test_extra_doc_tokens_do_not_dilute(self):
        # Recall-like (not Jaccard): doc with many extra tokens still scores 1.0
        # when all interest keywords are present.
        score = _keyword_score(["mica"], {"mica", "etf", "swap", "dora", "psd3", "nis2"})
        assert score == 1.0

    def test_multiword_phrase_requires_all_tokens(self):
        # "agonisti dofamina" only matches when BOTH tokens are present; the
        # denominator stays at the phrase count (1), not the token count (2).
        assert _keyword_score(["agonisti dofamina"], {"agonisti", "retseptorov"}) == 0.0
        assert _keyword_score(["agonisti dofamina"], {"agonisti", "dofamina"}) == 1.0
        # One single-word keyword matched out of two phrases → 0.5 (not 1/3).
        # n=2 <= K=3, so topk == mean here (INV-1).
        assert _keyword_score(["agonisti dofamina", "semaglutid"], {"semaglutid"}) == 0.5


# ----------------------------------------------------------------------------
# Keyword aggregation (ADR 0010: top-k capped recall)
# ----------------------------------------------------------------------------


class TestKeywordAggregation:
    """The exact aggregation contract pinned by ADR 0010 (INV-1/2/3)."""

    def test_default_scheme_is_topk(self):
        # The code default (and the global Settings default) is "topk".
        assert KEYWORD_AGGREGATION_DEFAULT == "topk"
        assert KEYWORD_TOPK_DEFAULT == 3

    def test_global_settings_default_is_topk(self):
        # The env-overridable knob defaults to "topk" with K=3 out of the box.
        from tg_parser.config.settings import Settings

        s = Settings()
        assert s.watchlist_keyword_aggregation == "topk"
        assert s.watchlist_keyword_topk == 3

    def test_empty_phrases_zero_both_schemes(self):
        # len(phrases) == 0 -> 0.0 for both schemes.
        assert _aggregate_keyword_score(0, 0, aggregation="mean", topk=3) == 0.0
        assert _aggregate_keyword_score(0, 0, aggregation="topk", topk=3) == 0.0
        assert _keyword_score([], {"mica"}, aggregation="topk") == 0.0
        assert _keyword_score(["   "], {"mica"}, aggregation="topk") == 0.0

    # ---- INV-1: safety / no-op for n <= K (topk == mean exactly) ----

    @pytest.mark.parametrize("n", [1, 2, 3])
    @pytest.mark.parametrize("hits", [0, 1, 2, 3])
    def test_inv1_topk_equals_mean_for_small_packs(self, n: int, hits: int):
        # For len(phrases) <= K, topk is byte-identical to mean (so atomic and
        # <=3-keyword interests keep their exact scores / thresholds).
        h = min(hits, n)
        mean = _aggregate_keyword_score(h, n, aggregation="mean", topk=3)
        topk = _aggregate_keyword_score(h, n, aggregation="topk", topk=3)
        assert topk == mean
        assert topk == pytest.approx(h / n)

    def test_inv1_phrase_level_n_equals_k(self):
        # n=3, k=min(3,3)=3 -> topk == mean even through the public helper.
        kws = ["mica", "psd3", "dora"]
        doc = {"mica", "psd3"}  # 2 of 3
        assert _keyword_score(kws, doc, aggregation="topk") == pytest.approx(2 / 3)
        assert _keyword_score(kws, doc, aggregation="mean") == pytest.approx(2 / 3)

    # ---- INV-2: anti-max / precision ----

    def test_inv2_one_of_ten_scores_one_third_not_one(self):
        # A doc hitting 1 of 10 keywords scores 1/3 under topk (K=3), NOT 1.0.
        topk = _aggregate_keyword_score(1, 10, aggregation="topk", topk=3)
        assert topk == pytest.approx(1 / 3)
        # Explicitly assert topk is NOT the "max" (presence) scheme value.
        max_score = 1.0  # max == 1.0 whenever hits > 0
        assert topk != max_score
        assert topk < max_score

    def test_inv2_three_of_ten_caps_at_one(self):
        # Once hits reaches K the capped recall is 1.0 (substantively matched).
        assert _aggregate_keyword_score(3, 10, aggregation="topk", topk=3) == pytest.approx(1.0)
        assert _aggregate_keyword_score(7, 10, aggregation="topk", topk=3) == pytest.approx(1.0)

    # ---- INV-3: monotonicity, bounds, exclude hard-zero ----

    def test_inv3_monotonic_non_decreasing_in_hits(self):
        n = 10
        prev = -1.0
        for hits in range(0, n + 1):
            score = _aggregate_keyword_score(hits, n, aggregation="topk", topk=3)
            assert score >= prev
            assert 0.0 <= score <= 1.0
            prev = score

    def test_inv3_bounds_for_topk_and_mean(self):
        for hits in range(0, 6):
            for total in range(1, 6):
                h = min(hits, total)
                for scheme in ("mean", "topk"):
                    score = _aggregate_keyword_score(h, total, aggregation=scheme, topk=3)
                    assert 0.0 <= score <= 1.0

    def test_inv3_exclude_hard_zeroes_combined_under_topk(self):
        # The exclude path is unchanged by aggregation: an excluded doc forces
        # combined to 0.0 even though keyword (topk) would be high.
        interest = _make_interest(
            keywords=["mica", "psd3", "nis2", "dora", "etf"],
            exclude_keywords=["meme"],
            embedding=None,
        )
        doc = _make_doc(text="MiCA PSD3 NIS2 meme", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=None)
        assert score.excluded is True
        assert score.combined == 0.0
        # keyword (topk) still reported for telemetry: 3 of 5 hit, k=3 -> 1.0
        assert score.keyword == pytest.approx(1.0)
        assert score.keyword_hits == 3
        assert score.keyword_total == 5

    # ---- mean rollback reproduces the old fractions for n >= 4 ----

    def test_mean_rollback_reproduces_old_fractions(self):
        # With aggregation="mean" the n>=4 packs score exactly hits/total (the
        # pre-ADR-0010 behaviour) — this is the production rollback knob.
        kws = ["mica", "psd3", "nis2", "dora", "etf"]  # n=5
        doc = {"mica", "psd3"}  # 2 hits
        assert _keyword_score(kws, doc, aggregation="mean") == pytest.approx(2 / 5)
        # …and topk recovers it to min(2,3)/3 = 2/3.
        assert _keyword_score(kws, doc, aggregation="topk") == pytest.approx(2 / 3)

    def test_keyword_hits_total_counts_phrases(self):
        # Raw counts: 2 hits out of 3 non-empty phrases (blank dropped).
        hits, total = _keyword_hits_total(["mica", "psd3", "   "], {"mica", "psd3"})
        assert (hits, total) == (2, 2)
        hits, total = _keyword_hits_total(["mica", "psd3", "dora"], {"mica", "psd3"})
        assert (hits, total) == (2, 3)


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
        # Behavioural test (ADR 0010): 1 of 4 interest keywords matches. Under
        # the default "topk" scheme (K=3) keyword = min(1, 3)/3 = 1/3, not the
        # old mean 1/4 = 0.25. With no embeddings combined == keyword == 1/3,
        # still well below the default 0.6 threshold (the behaviour under test).
        interest = _make_interest(keywords=["mica", "psd3", "nis2", "dora"], embedding=None)
        doc = _make_doc(text="MiCA only update", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=None)
        assert score.keyword == pytest.approx(1 / 3)
        assert score.combined == pytest.approx(1 / 3)
        assert score.combined < interest.threshold
        # Diagnostics expose the raw recall counts regardless of scheme.
        assert score.keyword_hits == 1
        assert score.keyword_total == 4

    def test_combined_capped_to_one(self):
        # Construct a degenerate case: keyword > 1 is impossible but defend
        # against rounding above 1.0 from float math.
        interest = _make_interest(keywords=["a"], embedding=[1.0])
        doc = _make_doc(text="A b c d e f g", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=[1.0])
        assert 0.0 <= score.combined <= 1.0


# ----------------------------------------------------------------------------
# D1 / Wave-2 T6 — semantic-unavailable observability counter
# ----------------------------------------------------------------------------


def _semantic_unavailable_value(reason: str) -> float:
    return WATCHLIST_SEMANTIC_UNAVAILABLE.labels(reason=reason)._value.get()


class TestSemanticUnavailableCounter:
    """compute_watch_score increments the keyword-only counter with the right
    ``reason`` in the ``semantic_available=False`` branch, without changing the
    combined score (observability-only side-effect)."""

    def test_interest_missing_embedding_increments_interest_reason(self):
        before = _semantic_unavailable_value("interest_no_embedding")
        interest = _make_interest(keywords=["mica"], embedding=None)
        doc = _make_doc(text="MiCA regulation in EU", summary=None, topics=[])
        # Doc HAS an embedding; only the interest is missing one.
        score = compute_watch_score(interest, doc, doc_embedding=[0.1] * 4)
        after = _semantic_unavailable_value("interest_no_embedding")
        assert after == pytest.approx(before + 1.0)
        assert score.semantic_available is False

    def test_doc_missing_embedding_increments_doc_reason(self):
        before = _semantic_unavailable_value("doc_no_embedding")
        interest = _make_interest(keywords=["mica"], embedding=[0.1] * 4)
        doc = _make_doc(text="MiCA regulation in EU", summary=None, topics=[])
        # Interest HAS an embedding; only the doc is missing one.
        score = compute_watch_score(interest, doc, doc_embedding=None)
        after = _semantic_unavailable_value("doc_no_embedding")
        assert after == pytest.approx(before + 1.0)
        assert score.semantic_available is False

    def test_both_missing_uses_interest_precedence(self):
        before_interest = _semantic_unavailable_value("interest_no_embedding")
        before_doc = _semantic_unavailable_value("doc_no_embedding")
        interest = _make_interest(keywords=["mica"], embedding=None)
        doc = _make_doc(text="MiCA regulation in EU", summary=None, topics=[])
        compute_watch_score(interest, doc, doc_embedding=None)
        # interest-first precedence: only the interest_no_embedding series moves.
        assert _semantic_unavailable_value("interest_no_embedding") == pytest.approx(
            before_interest + 1.0
        )
        assert _semantic_unavailable_value("doc_no_embedding") == pytest.approx(before_doc)

    def test_semantic_available_does_not_increment(self):
        before_interest = _semantic_unavailable_value("interest_no_embedding")
        before_doc = _semantic_unavailable_value("doc_no_embedding")
        emb = [0.1] * 4
        interest = _make_interest(keywords=["mica"], embedding=emb)
        doc = _make_doc(text="MiCA regulation in EU", summary=None, topics=[])
        score = compute_watch_score(interest, doc, doc_embedding=emb)
        assert score.semantic_available is True
        assert _semantic_unavailable_value("interest_no_embedding") == pytest.approx(
            before_interest
        )
        assert _semantic_unavailable_value("doc_no_embedding") == pytest.approx(before_doc)


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

    def test_keyword_hits_total_default_to_zero(self):
        # ADR 0010: new diagnostic fields are safe-defaulted so any partial
        # construction (e.g. legacy call sites) stays valid.
        score = WatchScore(
            keyword=0.5,
            semantic=0.6,
            combined=0.56,
            excluded=False,
            semantic_available=True,
        )
        assert score.keyword_hits == 0
        assert score.keyword_total == 0


# ----------------------------------------------------------------------------
# Multilang tokenizer (F11 keyword morphology)
# ----------------------------------------------------------------------------


class TestNormalizeToken:
    """Unit tests for script-routing branches in ``normalize_token()``."""

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            pytest.param("glp-1", "glp-1", id="hyphen-identity"),
            pytest.param("psd3", "psd3", id="digit-identity"),
            pytest.param("basel3", "basel3", id="mixed-alnum-identity"),
        ],
    )
    def test_identity_branch(self, token: str, expected: str) -> None:
        assert normalize_token(token) == expected

    @pytest.mark.parametrize(
        ("inflected", "lemma"),
        [
            pytest.param("пролактина", "пролактин", id="ru-genitive"),
            pytest.param("пролактином", "пролактин", id="ru-instrumental"),
            pytest.param("рапамицина", "рапамицин", id="ru-rapamycin-genitive"),
            pytest.param("агонистов", "агонист", id="ru-agonist-genitive-plural"),
            pytest.param("агонисты", "агонист", id="ru-agonist-nominative-plural"),
            pytest.param("дофамина", "дофамин", id="ru-dopamine-genitive"),
        ],
    )
    def test_russian_lemmatization(self, inflected: str, lemma: str) -> None:
        assert normalize_token(inflected) == lemma

    @pytest.mark.parametrize(
        ("inflected", "lemma"),
        [
            pytest.param("inhibitors", "inhibitor", id="en-plural"),
            pytest.param("inhibitor", "inhibitor", id="en-base"),
        ],
    )
    def test_english_lemmatization(self, inflected: str, lemma: str) -> None:
        assert normalize_token(inflected) == lemma

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param("mica", id="brand-mica"),
            pytest.param("mtor", id="abbrev-mtor"),
            pytest.param("etf", id="abbrev-etf"),
            pytest.param("цб", id="abbrev-cyrillic-cb"),
        ],
    )
    def test_unknown_or_abbrev_stays_unchanged(self, token: str) -> None:
        # simplemma/pymorphy3 have no lemma → token must not be degraded.
        assert normalize_token(token) == token

    def test_normalize_tokens_batch(self) -> None:
        # Inputs are expected already lowercased (as produced by _tokenize).
        assert normalize_tokens(["пролактина", "psd3", "inhibitors"]) == {
            "пролактин",
            "psd3",
            "inhibitor",
        }

    def test_tokenize_applies_normalization(self) -> None:
        # Full _tokenize path (regex extract → lower → normalize_token).
        tokens = _tokenize("PSD3 inhibitors пролактина")
        assert tokens == {"psd3", "inhibitor", "пролактин"}


class TestMultilangKeywordScore:
    """Integration: phrase-level keyword_score after token normalization."""

    def test_ru_prolactin_genitive(self) -> None:
        doc_tokens = _tokenize("уровень пролактина повышен")
        assert "пролактин" in doc_tokens
        assert _keyword_score(["пролактин"], doc_tokens) == pytest.approx(1.0)

    def test_ru_prolactin_instrumental(self) -> None:
        doc_tokens = _tokenize("терапия пролактином")
        assert _keyword_score(["пролактин"], doc_tokens) == pytest.approx(1.0)

    def test_ru_rapamycin_genitive(self) -> None:
        doc_tokens = _tokenize("доза рапамицина")
        assert _keyword_score(["рапамицин"], doc_tokens) == pytest.approx(1.0)

    def test_ru_multiword_phrase_inflected(self) -> None:
        # Keyword «агонисты дофамина» → {агонист, дофамин}; doc inflection must
        # lemmatize to the same set (phrase-level recall, not substring).
        doc_tokens = _tokenize("назначены агонистов дофамина")
        assert {"агонист", "дофамин"} <= doc_tokens
        assert _keyword_score(["агонисты дофамина"], doc_tokens) == pytest.approx(1.0)

    def test_ru_multiword_phrase_partial_is_zero(self) -> None:
        # Only «агонист» present; «дофамин» missing → phrase miss → 0.0.
        doc_tokens = _tokenize("новость про агонисты рецепторов")
        assert "агонист" in doc_tokens
        assert "дофамин" not in doc_tokens
        assert _keyword_score(["агонисты дофамина"], doc_tokens) == pytest.approx(0.0)

    def test_en_inhibitor_plural(self) -> None:
        doc_tokens = _tokenize("GLP-1 receptor inhibitors approved")
        assert "inhibitor" in doc_tokens
        assert _keyword_score(["inhibitor"], doc_tokens) == pytest.approx(1.0)

    def test_exclude_keywords_use_morphology(self) -> None:
        # exclude path shares _tokenize; «мемы» must hit exclude «мем».
        interest = _make_interest(
            keywords=["пролактин"],
            exclude_keywords=["мем"],
            embedding=None,
        )
        doc = _make_doc(text="уровень пролактина и мемы")
        score = compute_watch_score(interest, doc, doc_embedding=None)
        assert score.keyword == pytest.approx(1.0)
        assert score.excluded is True
        assert score.combined == pytest.approx(0.0)

    def test_unseeded_translit_does_not_match_cyrillic_keyword(self) -> None:
        # Documenting the still-accepted limitation: for terms NOT in the
        # curated alias map, different scripts do not cross-match on the keyword
        # path (the semantic component may still compensate). Seeded drugs DO
        # cross-match now — see TestAliasCanonicalization.
        doc_tokens = _tokenize("Prolactin level elevated")
        assert "prolactin" in doc_tokens
        assert _keyword_score(["пролактин"], doc_tokens) == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# Alias / brand canonicalization (backlog item B — seed-first)
# ----------------------------------------------------------------------------


class TestAliasCanonicalization:
    """``normalize_token`` collapses curated drug aliases onto one canonical."""

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            # semaglutide family (brand + spelling + cross-language)
            pytest.param("semaglutide", "semaglutide", id="en-canonical"),
            pytest.param("ozempic", "semaglutide", id="en-brand-ozempic"),
            pytest.param("wegovy", "semaglutide", id="en-brand-wegovy"),
            pytest.param("rybelsus", "semaglutide", id="en-brand-rybelsus"),
            pytest.param("семаглутид", "semaglutide", id="ru-canonical"),
            pytest.param("семаглутида", "semaglutide", id="ru-genitive-via-lemma"),
            pytest.param("оземпик", "semaglutide", id="ru-brand-ozempic"),
            # tirzepatide family — distinct canonical (no merge with semaglutide)
            pytest.param("tirzepatide", "tirzepatide", id="en-tirzepatide"),
            pytest.param("mounjaro", "tirzepatide", id="en-brand-mounjaro"),
            pytest.param("тирзепатид", "tirzepatide", id="ru-tirzepatide"),
            # GLP-1 drug class — cross-language abbreviations (identity-routed)
            pytest.param("glp-1", "glp-1", id="class-en"),
            pytest.param("гпп-1", "glp-1", id="class-ru-gpp"),
            pytest.param("агпп-1", "glp-1", id="class-ru-agpp"),
        ],
    )
    def test_alias_maps_to_canonical(self, alias: str, canonical: str) -> None:
        assert normalize_token(alias) == canonical

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param("metformin", id="unrelated-en-drug"),
            pytest.param("метформин", id="unrelated-ru-drug"),
            pytest.param("aspirin", id="unrelated-en-aspirin"),
        ],
    )
    def test_unrelated_drug_is_not_canonicalized(self, token: str) -> None:
        # Negative: terms outside the seed map must NOT collapse to a seeded
        # canonical (no over-matching). They normalize to their own lemma and
        # stay distinct from "semaglutide" / "tirzepatide".
        normalized = normalize_token(token)
        assert normalized not in {"semaglutide", "tirzepatide"}

    def test_interest_keyword_matches_brand_in_doc(self) -> None:
        # Headline item-B case: an interest keyworded the molecule name matches
        # a document that only mentions a brand name.
        doc_tokens = _tokenize("New study on Ozempic for weight loss")
        assert "semaglutide" in doc_tokens
        assert _keyword_score(["semaglutide"], doc_tokens) == pytest.approx(1.0)

    def test_cross_language_brand_matches_cyrillic_keyword(self) -> None:
        # RU interest keyword (inflected) matches an EN brand mention in the doc.
        doc_tokens = _tokenize("Ozempic одобрен регулятором")
        assert _keyword_score(["семаглутида"], doc_tokens) == pytest.approx(1.0)

    def test_distinct_molecules_do_not_cross_match(self) -> None:
        # Negative: a semaglutide interest must NOT match a tirzepatide-only doc.
        doc_tokens = _tokenize("Mounjaro trial results published")
        assert "tirzepatide" in doc_tokens
        assert _keyword_score(["semaglutide"], doc_tokens) == pytest.approx(0.0)

    def test_canonicalization_via_compute_watch_score(self) -> None:
        # End-to-end through the scoring path (keyword-only, no embeddings):
        # interest "wegovy" matches a doc mentioning "семаглутида".
        interest = _make_interest(keywords=["wegovy"], embedding=None)
        doc = _make_doc(text="Пациентам назначили семаглутида курс")
        score = compute_watch_score(interest, doc, doc_embedding=None)
        assert score.keyword == pytest.approx(1.0)
        assert score.combined == pytest.approx(1.0)
