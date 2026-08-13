"""Watchlist service (F11 Topic Watchlist).

Persistent user-defined interests scored by a hybrid keyword+semantic model.
The scheduler hook calls :meth:`WatchlistService.check_interests` once per
source per tick after :func:`run_incremental_topicization` returns; matches
above ``interest.threshold`` are persisted in ``watch_matches`` and, when a
``Bot`` is passed in, immediately dispatched via :meth:`WatchlistService.notify`.

Karpathy-like invariants:

- **Persistent entities:** ``WatchInterest`` is the long-lived "page of
  attention"; ``WatchMatch`` is the append-only evidence log.
- **Idempotency:** ``WatchMatchRepo.upsert_many`` uses
  ``ON CONFLICT (interest_id, source_ref) DO NOTHING RETURNING``, so a
  re-run of the pipeline never duplicates matches or notifications.
- **Cheap retrieval cycles:** lazy embedding cache on the interest, single
  ``list_active_for_channel`` per tick, no LLM calls in the hot path.
- **Graceful degradation:** if the document has no embedding (e.g. RAG
  pipeline failed), scoring falls back to the keyword component only.
- **Observability:** :class:`WatchScore` keeps the keyword/semantic
  components separate; :func:`tg_parser.api.metrics.record_watchlist_match`
  emits ``tg_watchlist_matches_total{result}`` plus the
  ``tg_watchlist_score`` histogram per (interest, doc) candidate, and
  :func:`tg_parser.api.metrics.record_watchlist_delivery` emits
  ``tg_watchlist_delivery_total{outcome}`` per push attempt — see
  ``docs/runbooks/F5C_DEPLOY_AND_WATCH.md`` § F11 watchlist health for
  PromQL recipes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import IntegrityError

from tg_parser.api.metrics import (
    record_watchlist_delivery,
    record_watchlist_match,
    record_watchlist_semantic_unavailable,
    set_watchlist_active,
)
from tg_parser.auth.ownership import WorkspaceNotFound
from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    TargetChannel,
    TargetChat,
    WatchInterest,
    WatchMatch,
    resolve_subscription_target,
    storage_fields_from_target,
)
from tg_parser.services.watchlist_tokenizer import normalize_token
from tg_parser.storage.ports import (
    EmbeddingRepo,
    ProcessedDocumentRepo,
    WatchInterestRepo,
    WatchMatchRepo,
    WorkspaceRepo,
)
from tg_parser.utils.channel_id import normalize_channel_id

if TYPE_CHECKING:
    from aiogram import Bot

    from tg_parser.services.embedding_service import EmbeddingClient


logger = structlog.get_logger(__name__)


# ----------------------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------------------

#: Combined-score formula: ``combined = KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem``.
#: Sum is exactly 1.0 so the result stays in ``[0, 1]``.
KEYWORD_WEIGHT: float = 0.4
SEMANTIC_WEIGHT: float = 0.6

#: Keyword-aggregation scheme (ADR 0010). ``"mean"`` is the original
#: ``matched_phrases / total_phrases`` recall; ``"topk"`` caps the denominator
#: at ``min(KEYWORD_TOPK_DEFAULT, n_phrases)`` so keywords beyond the top K add
#: no "denominator penalty". ``"topk"`` is the default and is a strict no-op for
#: interests naming ``<= KEYWORD_TOPK_DEFAULT`` keywords. The env knob
#: ``watchlist_keyword_aggregation`` is the production rollback to ``"mean"``.
KEYWORD_AGGREGATION_DEFAULT: str = "topk"

#: The K in the top-k keyword aggregation (ADR 0010).
KEYWORD_TOPK_DEFAULT: int = 3

#: Minimum token length used by :func:`_tokenize`. Mirrors the topicization
#: tokenizer (``MIN_TOKEN_LENGTH = 2``) so short medical/regulatory abbreviations
#: such as "MiCA", "ETF", "ЦБ" are not dropped.
MIN_TOKEN_LENGTH: int = 2

#: Hard cap on the number of new documents scored in a single tick. Protects
#: the scheduler from a back-filled channel producing thousands of new
#: ``new_doc_refs`` at once (notification flood / OpenAI rate-limit risk).
MAX_DOCS_PER_TICK: int = 100

#: ADR-0011 retired the historical ``MAX_BACKFILL_DOCS`` scoring cap. Backfill
#: now scores the whole matched corpus in one batched pass (the embedding fetch
#: is chunked inside ``EmbeddingRepo.get_many_by_source_refs``); an explicit
#: ``limit`` argument is still honoured for callers that want a newest-first
#: preview, but there is no implicit truncation.

#: Max number of per-match preview lines included in a single instant
#: notification. The remaining matches are still saved (and visible via
#: ``get_watchlist_matches``) but collapsed into a "+N more" footer so the
#: Telegram message stays under the 4096-char limit (gotcha #8: avoid flooding
#: a chat with N separate pushes when one tick produced many matches).
MAX_PREVIEWS_PER_NOTIFICATION: int = 5

#: Max characters of ``summary`` / ``text_clean`` shown per preview line.
#: Telegram MarkdownV2 escaping inflates the byte count, so this conservative
#: cap keeps every notification well under ``MESSAGE_HARD_LIMIT``.
PREVIEW_TEXT_CHARS: int = 220

#: Hard ceiling we never exceed when composing a single ``send_message``
#: payload. Telegram's documented limit is 4096; we leave ~96 chars of slack
#: for the trailing footer / unicode multi-byte expansion.
MESSAGE_HARD_LIMIT: int = 4000

#: Substring fragments that ``Bot.send_message`` raises when the user has
#: blocked the bot or deleted the private chat. Detecting them lets us
#: gracefully soft-delete the orphaned interest instead of retrying forever
#: (gotcha #5).
_BOT_PERMANENT_FAILURE_FRAGMENTS: tuple[str, ...] = (
    "chat not found",
    "bot was blocked",
    "user is deactivated",
    "forbidden",
)


# ----------------------------------------------------------------------------
# Score model
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ThresholdCalibration:
    """Outcome of corpus-based threshold suggestion (ADR 0012 / S2).

    Returned when a new interest is created without an explicit threshold and
    calibration is enabled. ``suggested_threshold`` is applied automatically on
    create (auto-set when omitted); callers surface ``confidence`` / ``reason``
    for operator transparency.
    """

    suggested_threshold: float
    scored_docs: int
    max_combined: float
    would_match: int
    target_matches: int
    confidence: str
    strategy: str
    fallback_used: bool
    reason: str
    #: ADR 0013 advisory metadata. ``floor_applied`` is True when the absolute
    #: precision floor (``min_threshold``) — not the volume target — set the
    #: returned cutoff; ``pre_floor_threshold`` is the volume-target threshold
    #: before the floor was applied (None when no floor was in effect). They let
    #: operators see *why* the cutoff is what it is (volume vs floor).
    floor_applied: bool = False
    pre_floor_threshold: float | None = None


@dataclass(frozen=True)
class SubscribeResult:
    """Outcome of a :meth:`WatchlistService.subscribe` call.

    Wave 1 step 3 / BUG-022: returned by the service-layer upsert so
    every surface (MCP, Bot, CLI, HTTP) can render the locked
    ``{watchlist_id, created, changed_fields}`` shape without
    duplicating the diff logic. ``changed_fields`` is a list of
    Pydantic field names that differ between the stored row and the
    payload (empty on a true no-op replay, populated on
    same-key/different-args).

    ``threshold_calibration`` is populated on **new** creates when the caller
    omitted ``threshold`` and ADR-0012 calibration ran (``None`` on updates,
    explicit thresholds, or when calibration is disabled).
    """

    interest: WatchInterest
    created: bool
    changed_fields: list[str]
    threshold_calibration: ThresholdCalibration | None = None


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of a :meth:`WatchlistService.backfill_interest` run.

    DIAG 2026-06-07 (hypothesis B2): the scheduler only ever scores documents
    that become *new* ``processed_documents`` within a tick, so a corpus
    backfilled before an interest existed is never evaluated. This result type
    reports what a one-shot retroactive rescoring pass found / persisted.

    ``would_match`` is the count of (doc) candidates at or above the threshold;
    on a ``dry_run`` it is the headline number an operator inspects before
    applying. ``inserted`` is the number of *new* ``watch_matches`` rows written
    (always 0 on a dry run; bounded below ``would_match`` on a real run because
    idempotent ``upsert_many`` skips refs already matched).
    """

    interest_id: str
    scored_docs: int
    candidates: int
    inserted: int
    max_combined: float
    would_match: int
    dry_run: bool
    error: str | None = None


@dataclass(frozen=True)
class WatchScore:
    """Decomposed match score for a single (interest, document) pair.

    ``combined`` is the headline value compared against ``interest.threshold``.
    ``keyword`` and ``semantic`` are kept for telemetry and tuning.
    ``excluded`` is set when an ``exclude_keywords`` token matched the doc;
    in that case ``combined`` is forced to ``0.0`` regardless of the other
    components (negative filter wins).
    ``semantic_available`` reports whether both embeddings were present;
    when False the formula collapses to pure keyword scoring.
    ``keyword_hits`` / ``keyword_total`` are the raw phrase counts behind the
    keyword component (ADR 0010): ``keyword_total`` is the number of non-empty
    keyword phrases, ``keyword_hits`` how many of them are present in the doc.
    They are diagnostics only (never persisted to a contract surface) and let
    operators see *how many* keywords matched independently of the aggregation
    scheme that produced ``keyword``. Default to ``0`` so any partial
    construction stays valid.
    """

    keyword: float
    semantic: float
    combined: float
    excluded: bool
    semantic_available: bool
    keyword_hits: int = 0
    keyword_total: int = 0


# ----------------------------------------------------------------------------
# Pure scoring helpers (no I/O — easy to unit-test)
# ----------------------------------------------------------------------------


_TOKEN_RE = re.compile(rf"[a-zA-Zа-яА-ЯёЁ0-9]{{{MIN_TOKEN_LENGTH},}}")

#: Fallback default threshold when settings cannot be loaded (matches the
#: ``WatchInterest.threshold`` model default so behaviour is unchanged).
_FALLBACK_DEFAULT_THRESHOLD: float = 0.6


def _resolve_default_threshold(threshold: float | None) -> float:
    """Resolve an explicit threshold or fall back to the configured default.

    Callers (MCP / bot / CLI) pass ``None`` to mean "use the operator default"
    so the cutoff for new interests lives in a single place
    (``settings.watchlist_default_threshold``) rather than being duplicated as a
    literal across every surface. Explicit values are returned unchanged.

    On **new** interest creation, ``None`` is handled by
    :meth:`WatchlistService._resolve_threshold_for_new_interest` which may run
    ADR-0012 calibration instead of this fallback.
    """
    if threshold is not None:
        return threshold
    try:
        from tg_parser.config import settings as app_settings

        return float(app_settings.watchlist_default_threshold)
    except Exception:
        return _FALLBACK_DEFAULT_THRESHOLD


def _percentile_value(sorted_scores: list[float], percentile: float) -> float:
    """Linear-interpolation percentile on a pre-sorted score list."""
    if not sorted_scores:
        return 0.0
    if percentile <= 0.0:
        return sorted_scores[0]
    if percentile >= 100.0:
        return sorted_scores[-1]
    k = (len(sorted_scores) - 1) * (percentile / 100.0)
    floor_k = math.floor(k)
    ceil_k = math.ceil(k)
    if floor_k == ceil_k:
        return sorted_scores[int(k)]
    low = sorted_scores[floor_k]
    high = sorted_scores[ceil_k]
    return low + (high - low) * (k - floor_k)


def suggest_threshold_from_scores(
    scores: list[float],
    *,
    strategy: str = "target_fraction",
    target_fraction: float = 0.03,
    target_min_matches: int = 10,
    target_max_matches: int = 150,
    min_corpus_size: int = 20,
    percentile: float = 97.0,
    min_threshold: float = 0.0,
    default_threshold: float = _FALLBACK_DEFAULT_THRESHOLD,
) -> ThresholdCalibration:
    """Pick a combined-score cutoff from a corpus score distribution (ADR 0012).

    Pure function — no I/O. ``scores`` should be non-excluded combined scores
    from a full-corpus scoring pass (same ``compute_watch_score`` path as
    backfill / scheduler).

    Strategies:

    - ``target_fraction``: target ~``fraction`` of the corpus (clamped by
      min/max match counts), threshold = Nth-highest score.
    - ``percentile``: threshold at the configured percentile of the distribution.

    ADR 0013 — absolute precision floor: after the strategy picks a volume-target
    threshold, the final cutoff is ``max(threshold, min_threshold)``. A NARROW
    interest whose thin tail sits below ``min_threshold`` would otherwise drag
    the target-fraction cutoff down into the noise band (worst observed overshoot
    7.9x too many matches); the floor caps that. ``target_matches`` stays the
    PRE-floor volume target for transparency, while ``would_match`` is recomputed
    against the floored threshold. **Floor wins over ``target_min_matches``**
    (precision-first): if the floor pulls ``would_match`` below the min-match
    target, the threshold is NOT lowered back to satisfy the volume floor —
    a few precise matches beat many noisy ones.

    Fallbacks (``fallback_used=True``): empty corpus → ``default_threshold``.
    """
    cleaned = [s for s in scores if 0.0 <= s <= 1.0]
    n = len(cleaned)
    if n == 0:
        return ThresholdCalibration(
            suggested_threshold=default_threshold,
            scored_docs=0,
            max_combined=0.0,
            would_match=0,
            target_matches=0,
            confidence="low",
            strategy=strategy,
            fallback_used=True,
            reason="empty_corpus",
        )

    max_combined = max(cleaned)
    if n < min_corpus_size:
        confidence = "low"
    elif n < 100:
        confidence = "medium"
    else:
        confidence = "high"

    sorted_desc = sorted(cleaned, reverse=True)
    if strategy == "percentile":
        sorted_asc = sorted(cleaned)
        threshold = _percentile_value(sorted_asc, percentile)
        target_matches = sum(1 for s in cleaned if s >= threshold)
        reason = f"percentile_{percentile}"
    else:
        raw_target = round(n * target_fraction)
        target_matches = max(target_min_matches, min(target_max_matches, raw_target))
        target_matches = min(target_matches, n)
        threshold = sorted_desc[target_matches - 1]
        reason = f"target_fraction_{target_fraction}"

    threshold = max(0.0, min(1.0, threshold))

    # ADR 0013 — absolute precision floor. Apply AFTER both strategy branches so
    # the cutoff is never below ``min_threshold``. ``target_matches`` is left as
    # the PRE-floor volume target; ``would_match`` is recomputed against the
    # floored threshold. Floor wins over ``target_min_matches`` (precision-first):
    # we deliberately do NOT lower the threshold back to recover lost matches.
    pre_floor_threshold = threshold
    floor_applied = False
    if min_threshold > threshold:
        threshold = min_threshold
        floor_applied = True

    would_match = sum(1 for s in cleaned if s >= threshold)

    return ThresholdCalibration(
        suggested_threshold=round(threshold, 4),
        scored_docs=n,
        max_combined=round(max_combined, 4),
        would_match=would_match,
        target_matches=target_matches,
        confidence=confidence,
        strategy=strategy,
        fallback_used=False,
        reason=reason,
        floor_applied=floor_applied,
        pre_floor_threshold=round(pre_floor_threshold, 4) if floor_applied else None,
    )


def _tokenize(value: str | None) -> set[str]:
    """Lowercase word tokens of length >= ``MIN_TOKEN_LENGTH``.

    Digits are included because regulatory keywords frequently embed numbers
    (``"MiCA2"``, ``"PSD3"``, ``"NIS2"``).
    """
    if not value:
        return set()
    return {normalize_token(match.lower()) for match in _TOKEN_RE.findall(value)}


def _build_doc_tokens(doc: ProcessedDocument) -> set[str]:
    """Tokens used by the keyword scorer.

    Combines structured signal (``topics``, ``summary``) with the cleaned text.
    Topicization may not have run yet (gotcha #10) — falling back to
    ``text_clean`` keeps the watchlist usable in degraded mode.
    """
    tokens: set[str] = set()
    for topic in doc.topics or []:
        tokens |= _tokenize(topic)
    tokens |= _tokenize(doc.summary)
    tokens |= _tokenize(doc.text_clean)
    return tokens


def _keyword_hits_total(interest_keywords: list[str], doc_tokens: set[str]) -> tuple[int, int]:
    """Raw phrase counts ``(hits, total)`` behind the keyword component.

    Each keyword is an atomic phrase that counts as a *hit* only when **every**
    token it tokenises into appears in ``doc_tokens`` (phrase subset). ``total``
    is the number of non-empty phrases. Empty phrases (keywords that tokenise to
    nothing — e.g. a blank string) are dropped from both counts.

    DIAG 2026-06-07 fix: a multi-word keyword such as ``"агонисты дофамина"`` is
    one phrase (denominator += 1), not two tokens, so a partial overlap no
    longer silently depresses the score. Single-token keywords behave
    identically to the old token-set overlap.
    """
    phrases = [tokens for tokens in (_tokenize(kw) for kw in interest_keywords) if tokens]
    total = len(phrases)
    hits = sum(1 for phrase in phrases if phrase <= doc_tokens)
    return hits, total


def _aggregate_keyword_score(
    hits: int,
    total: int,
    *,
    aggregation: str = KEYWORD_AGGREGATION_DEFAULT,
    topk: int = KEYWORD_TOPK_DEFAULT,
) -> float:
    """Aggregate phrase ``hits`` / ``total`` into a ``[0, 1]`` keyword score.

    Schemes (ADR 0010); ``k = min(topk, total)``:

    - ``"mean"``: ``hits / total`` — the original recall fraction. Adding a
      rare/multi-word keyword dilutes the score for on-topic docs (the
      "denominator penalty").
    - ``"topk"``: ``min(hits, k) / k`` — caps the denominator at ``k`` so
      keywords beyond the top ``K`` add no penalty. Because phrase hits are
      binary, the top-k *mean* collapses to this closed form (the ``k`` highest
      per-phrase scores are exactly ``min(hits, k)`` ones and ``k - min(hits, k)``
      zeros). For ``total <= topk`` this is **identical** to ``"mean"`` (INV-1).

    ``total == 0`` → ``0.0`` for every scheme.
    """
    if total <= 0:
        return 0.0
    if aggregation == "mean":
        return hits / total
    # "topk" (default): cap the denominator at k = min(topk, total).
    k = min(topk, total)
    if k <= 0:
        return 0.0
    return min(hits, k) / k


def _keyword_score(
    interest_keywords: list[str],
    doc_tokens: set[str],
    *,
    aggregation: str = KEYWORD_AGGREGATION_DEFAULT,
    topk: int = KEYWORD_TOPK_DEFAULT,
) -> float:
    """Phrase-level keyword recall, aggregated per ``aggregation`` (ADR 0010).

    Thin convenience wrapper over :func:`_keyword_hits_total` +
    :func:`_aggregate_keyword_score`. Pure function (no I/O), easy to unit-test.
    """
    hits, total = _keyword_hits_total(interest_keywords, doc_tokens)
    return _aggregate_keyword_score(hits, total, aggregation=aggregation, topk=topk)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity clipped to ``[0.0, 1.0]``.

    OpenAI ``text-embedding-3-small`` vectors are L2-normalised at the API
    boundary, but the explicit norms keep the formula correct for any client
    (and for the tests, where embeddings are arbitrary fixtures).
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for ai, bi in zip(a, b, strict=True):
        dot += ai * bi
        norm_a += ai * ai
        norm_b += bi * bi
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    sim = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    if sim < 0.0:
        return 0.0
    if sim > 1.0:
        return 1.0
    return sim


def compute_watch_score(
    interest: WatchInterest,
    doc: ProcessedDocument,
    doc_embedding: list[float] | None,
    *,
    keyword_weight: float = KEYWORD_WEIGHT,
    semantic_weight: float = SEMANTIC_WEIGHT,
    aggregation: str = KEYWORD_AGGREGATION_DEFAULT,
    topk: int = KEYWORD_TOPK_DEFAULT,
    doc_tokens: set[str] | None = None,
) -> WatchScore:
    """Score a single ``(interest, document)`` pair.

    Returns a :class:`WatchScore` with the full breakdown. The caller compares
    ``score.combined >= interest.threshold`` to decide whether to materialise
    a :class:`WatchMatch`.

    ``keyword_weight`` / ``semantic_weight`` default to the module constants but
    can be overridden (the service injects values from settings) so operators
    can rebalance the hybrid mix without a code change when the embedding model
    under-scores the corpus language.

    ``aggregation`` / ``topk`` select the keyword-aggregation scheme (ADR 0010);
    they likewise default to the module constants and are injected from settings
    by the service. The returned :class:`WatchScore` also carries the raw
    ``keyword_hits`` / ``keyword_total`` phrase counts for diagnostics.

    F-08 (O-7): ``doc_tokens`` lets the caller pass the pre-lemmatised token set
    for ``doc`` so the pymorphy3 pass runs once per document per tick instead of
    once per (interest, document) pair. When ``None`` (every legacy call site)
    it falls back to ``_build_doc_tokens(doc)`` — byte-for-byte the previous
    behaviour, since the precomputed set is built by the same pure function.
    """
    if doc_tokens is None:
        doc_tokens = _build_doc_tokens(doc)

    exclude_tokens: set[str] = set()
    for kw in interest.exclude_keywords:
        exclude_tokens |= _tokenize(kw)
    excluded = bool(exclude_tokens & doc_tokens)

    keyword_hits, keyword_total = _keyword_hits_total(interest.keywords, doc_tokens)
    keyword = _aggregate_keyword_score(
        keyword_hits, keyword_total, aggregation=aggregation, topk=topk
    )

    semantic_available = bool(interest.embedding) and bool(doc_embedding)
    semantic = _cosine(interest.embedding or [], doc_embedding or []) if semantic_available else 0.0

    if not semantic_available:
        # D1 / Wave-2 T6 — observability-ONLY side-effect. Record why the score
        # degrades to keyword-only (combined = keyword below). Precedence when
        # BOTH embeddings are missing: interest first (the interest-embedding
        # backfill is the operator-actionable root cause). This does NOT alter
        # the combined formula — graceful keyword-only stays by-design
        # (ADR-0010/0011); we only measure the keyword-only share so the T6
        # alert can gate on it.
        record_watchlist_semantic_unavailable(
            reason="interest_no_embedding" if not interest.embedding else "doc_no_embedding"
        )

    if excluded:
        combined = 0.0
    elif semantic_available:
        combined = keyword_weight * keyword + semantic_weight * semantic
    else:
        combined = keyword

    if combined < 0.0:
        combined = 0.0
    if combined > 1.0:
        combined = 1.0

    return WatchScore(
        keyword=keyword,
        semantic=semantic,
        combined=combined,
        excluded=excluded,
        semantic_available=semantic_available,
        keyword_hits=keyword_hits,
        keyword_total=keyword_total,
    )


# ----------------------------------------------------------------------------
# Notification composition (pure helpers — no I/O)
# ----------------------------------------------------------------------------


_MD_V2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"
_MD_V2_PATTERN = re.compile("[" + re.escape(_MD_V2_SPECIAL) + "]")


def escape_markdown_v2(text: str) -> str:
    """Escape every Telegram MarkdownV2 special char in ``text``.

    Mirrors :func:`tg_parser.services.digest_service.escape_markdown_v2` but
    is duplicated locally so the watchlist module does not depend on the
    digest service (different feature, different test surface).
    """
    if not text:
        return ""
    return _MD_V2_PATTERN.sub(r"\\\g<0>", text)


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _post_url(source_ref: str) -> str | None:
    """Best-effort permalink for ``source_ref`` of the shape ``tg:<channel>:<kind>:<id>``.

    Telegram only exposes ``t.me/<username>/<message_id>`` for *public*
    channels; for private channels we return ``None`` and the caller falls
    back to plain text. We do not currently distinguish — the URL is offered
    optimistically and Telegram clients render unreachable links gracefully.
    """
    parts = source_ref.split(":")
    if len(parts) < 4 or parts[0] != "tg":
        return None
    channel, _kind, msg_id = parts[1], parts[2], parts[3]
    channel = normalize_channel_id(channel)
    if not channel or not msg_id.isdigit():
        return None
    return f"https://t.me/{channel}/{msg_id}"


def compose_match_notification(
    interest: WatchInterest,
    matches: list[WatchMatch],
    docs_by_ref: dict[str, ProcessedDocument],
    *,
    max_previews: int = MAX_PREVIEWS_PER_NOTIFICATION,
    preview_chars: int = PREVIEW_TEXT_CHARS,
    hard_limit: int = MESSAGE_HARD_LIMIT,
) -> str:
    """Compose a single MarkdownV2 message for one ``(interest, matches)`` group.

    Pure function so the test suite can pin the exact rendered output. The
    runtime caller is :meth:`WatchlistService.notify`.
    """
    title = escape_markdown_v2(interest.title)
    header = f"🔔 *{title}* — {len(matches)} new"
    lines: list[str] = [header]

    sorted_matches = sorted(matches, key=lambda m: m.combined_score, reverse=True)
    shown = sorted_matches[:max_previews]

    for match in shown:
        doc = docs_by_ref.get(match.source_ref)
        body_source = ""
        if doc is not None:
            body_source = doc.summary or doc.text_clean or ""
        body = _truncate(body_source, preview_chars)
        body_md = escape_markdown_v2(body) if body else escape_markdown_v2(match.source_ref)
        score_md = escape_markdown_v2(f"{match.combined_score:.2f}")
        url = _post_url(match.source_ref)
        if url:
            url_md = url.replace(")", r"\)").replace("\\", r"\\")
            line = f"\n• [{body_md}]({url_md})  _\\(score {score_md}\\)_"
        else:
            line = f"\n• {body_md}  _\\(score {score_md}\\)_"
        if sum(len(p) for p in lines) + len(line) > hard_limit:
            break
        lines.append(line)

    overflow = len(sorted_matches) - len(shown)
    if overflow > 0:
        footer = f"\n\\+{overflow} more — use `get_watchlist_matches` to see all"
        lines.append(footer)

    return "".join(lines)


@dataclass
class BacklogEntry:
    """One interest's share of the undelivered backlog (BUG-095 §3.3)."""

    interest_id: str
    title: str
    missed: int
    oldest: datetime
    newest: datetime


@dataclass
class BacklogSummary:
    """One chat's backlog summary: what it would receive, and whether it did."""

    chat_id: int
    entries: list[BacklogEntry]
    match_count: int
    text: str
    sent: bool


def _backlog_entries(
    matches: list[WatchMatch],
    interests_by_id: dict[str, WatchInterest],
) -> list[BacklogEntry]:
    """Fold one chat's undelivered matches into per-interest counts and spans."""
    grouped: dict[str, list[WatchMatch]] = {}
    for match in matches:
        grouped.setdefault(match.interest_id, []).append(match)

    entries: list[BacklogEntry] = []
    for interest_id, group in grouped.items():
        stamps = [m.created_at for m in group if m.created_at is not None]
        if not stamps:
            continue
        interest = interests_by_id.get(interest_id)
        entries.append(
            BacklogEntry(
                interest_id=interest_id,
                title=interest.title if interest is not None else interest_id,
                missed=len(group),
                oldest=min(stamps),
                newest=max(stamps),
            )
        )
    return sorted(entries, key=lambda e: e.missed, reverse=True)


def compose_backlog_summary(entries: list[BacklogEntry]) -> str:
    """Compose one chat's MarkdownV2 backlog summary (BUG-095 §3.3).

    Reports how much was missed per interest and over what period, and points
    at ``get_watchlist_matches`` for the content. Deliberately NOT a list of
    posts: the alternative considered and rejected was replaying the last N
    matches per interest, which at N=1 is up to sixteen notifications about
    posts as much as two months old — the value of a watchlist is hearing in
    time, and that time has passed. Nothing is lost by summarising: every match
    is still in the database.

    Pure function so the exact rendered output can be pinned by tests.
    """
    total = sum(entry.missed for entry in entries)
    header = f"⚠️ *Watchlist alerts were not delivered* — {total} missed"
    lines: list[str] = [
        header,
        "\n\nA delivery fault \\(BUG\\-095\\) kept these matches from reaching you\\. "
        "They are all saved; delivery is restored\\.",
    ]

    for entry in entries:
        title = escape_markdown_v2(_truncate(entry.title, 80))
        period = escape_markdown_v2(
            f"{entry.oldest.strftime('%Y-%m-%d')} — {entry.newest.strftime('%Y-%m-%d')}"
        )
        lines.append(f"\n\n• *{title}* — {entry.missed} missed, {period}")

    lines.append(
        "\n\nUse `get_watchlist_matches(interest_id, since_iso=…)` to read what was missed\\."
    )
    return "".join(lines)


def build_canonical_interest_text(interest: WatchInterest) -> str:
    """Canonical text used to embed an interest.

    Always non-empty — never embed an empty string (gotcha #1: OpenAI 400).
    Order: ``description`` (free-form intent) → ``title`` (short label) →
    keywords joined by spaces. Falls back to ``title + keywords`` if
    description is missing.
    """
    parts: list[str] = []
    if interest.description and interest.description.strip():
        parts.append(interest.description.strip())
    if interest.title and interest.title.strip():
        parts.append(interest.title.strip())
    if interest.keywords:
        parts.append(" ".join(kw for kw in interest.keywords if kw.strip()))
    text = " ".join(part for part in parts if part).strip()
    if not text:
        text = interest.title or "watch interest"
    return text


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------


class WatchlistService:
    """Hybrid keyword+semantic matcher driven by the incremental scheduler.

    Constructor injection mirrors :class:`tg_parser.services.digest_service.DigestService`:
    repositories and the embedding client are passed in explicitly so the
    scheduler can wire production deps and tests can pass fakes.

    Notification dispatch (Bot push, batch grouping) is implemented in
    :meth:`notify` and called automatically from :meth:`check_interests` when
    the scheduler passes a live ``Bot``. ``notify`` is also safe to call
    standalone (e.g. from tests) — it always groups by ``interest_id`` and
    flips ``notified=True`` only after a successful ``send_message``.
    """

    def __init__(
        self,
        interest_repo: WatchInterestRepo,
        match_repo: WatchMatchRepo,
        processed_doc_repo: ProcessedDocumentRepo,
        embedding_repo: EmbeddingRepo,
        embedding_client: EmbeddingClient | None,
        workspace_repo: WorkspaceRepo | None = None,
        *,
        keyword_weight: float = KEYWORD_WEIGHT,
        semantic_weight: float = SEMANTIC_WEIGHT,
        keyword_aggregation: str = KEYWORD_AGGREGATION_DEFAULT,
        keyword_topk: int = KEYWORD_TOPK_DEFAULT,
    ) -> None:
        self.interest_repo = interest_repo
        self.match_repo = match_repo
        self.processed_doc_repo = processed_doc_repo
        self.embedding_repo = embedding_repo
        self.embedding_client = embedding_client
        self.workspace_repo = workspace_repo
        self._keyword_weight = keyword_weight
        self._semantic_weight = semantic_weight
        self._keyword_aggregation = keyword_aggregation
        self._keyword_topk = keyword_topk

    # ---- High-level CRUD helpers (used by bot/MCP/CLI in commit 2/2) ----

    async def create_interest(
        self,
        *,
        user_id: str,
        chat_id: int,
        title: str,
        channel_ids: list[str],
        description: str | None = None,
        keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        threshold: float | None = None,
        notify_mode: NotifyMode = NotifyMode.INSTANT,
        workspace_id: str | None = None,
    ) -> WatchInterest:
        """Persist a new interest and eagerly compute its embedding.

        The eager embedding keeps the first scheduler tick fast (no first-tick
        embed latency) and is safe because :func:`build_canonical_interest_text`
        guarantees a non-empty input.

        When ``threshold`` is omitted and ADR-0012 calibration is enabled, the
        cutoff is derived from the channel corpus score distribution instead of
        ``watchlist_default_threshold``.

        Kept for backward compatibility with callers that do not need the
        idempotent upsert (test fixtures, scheduler re-creation). New code
        should call :meth:`subscribe` which closes BUG-022.
        """
        draft = WatchInterest(
            id="",
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            description=description,
            keywords=list(keywords or []),
            exclude_keywords=list(exclude_keywords or []),
            channel_ids=list(channel_ids),
            workspace_id=workspace_id,
            threshold=_FALLBACK_DEFAULT_THRESHOLD,
            notify_mode=notify_mode,
            is_active=True,
            embedding=None,
        )
        embedding = await self._embed_interest(draft)
        if embedding is not None:
            draft = draft.model_copy(update={"embedding": embedding})

        resolved_threshold, _ = await self._resolve_threshold_for_new_interest(draft, threshold)
        draft = draft.model_copy(
            update={
                "threshold": resolved_threshold,
                "threshold_source": "manual" if threshold is not None else "auto",
            }
        )

        stored = await self.interest_repo.create(draft)
        if embedding is not None:
            await self.interest_repo.update_embedding(stored.id, embedding)
            stored = stored.model_copy(update={"embedding": embedding})

        return stored

    async def subscribe(
        self,
        *,
        user_id: str,
        title: str,
        channel_ids: list[str],
        chat_id: int | None = None,
        target: TargetChat | TargetChannel | None = None,
        description: str | None = None,
        keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        threshold: float | None = None,
        notify_mode: NotifyMode = NotifyMode.INSTANT,
        workspace_id: str | None = None,
        is_admin: bool = False,
    ) -> SubscribeResult:
        """Idempotent upsert on the ``(user_id, title)`` natural key (BUG-022).

        Wave 1 step 3 commit 1/4 — closes BUG-022. Behaviour:

        - Same ``(user_id, title)`` and identical payload → no-op replay;
          returns the existing row with ``created=False`` and
          ``changed_fields=[]``.
        - Same ``(user_id, title)`` but different mutable args → UPDATE
          the changed columns, return the row with ``created=False``
          and ``changed_fields=[...]`` (list of Pydantic field names).
        - Soft-deleted interest with the same key → resurrected
          (``is_active`` flipped to True) and merged with the new
          payload; ``is_active`` is included in ``changed_fields`` to
          make the resurrection observable.
        - Race condition (concurrent INSERTs from two surfaces) →
          ``IntegrityError`` from the new ``UNIQUE (user_id, title)``
          DB constraint is caught and the path retries as UPDATE.

        ``workspace_id``:

        - ``None`` (default) → identical to pre-ENH-9 behaviour
          (column stays NULL on INSERT; left untouched on UPDATE).
        - Valid UUID → validated via the injected ``workspace_repo``;
          unknown or foreign UUIDs raise :class:`WorkspaceNotFound`
          (mirror F4-B Q2 EC2). ``is_admin=True`` bypasses the
          ownership check.
        - When ``workspace_repo`` is not configured (e.g. unit tests
          that don't need workspace validation) a non-None
          ``workspace_id`` is stored as-is without validation.
        """
        resolved_target = resolve_subscription_target(chat_id=chat_id, target=target)
        target_storage = storage_fields_from_target(resolved_target)

        if workspace_id is not None and self.workspace_repo is not None:
            workspace = await self.workspace_repo.get(workspace_id)
            if workspace is None:
                raise WorkspaceNotFound(f"Workspace {workspace_id} not found")
            if not is_admin and workspace.owner_id != user_id:
                raise WorkspaceNotFound(f"Workspace {workspace_id} not found")

        existing = await self.interest_repo.find_by_user_and_title(user_id, title)
        if existing is not None:
            return await self._apply_upsert(
                existing=existing,
                target_storage=target_storage,
                description=description,
                keywords=keywords,
                exclude_keywords=exclude_keywords,
                channel_ids=channel_ids,
                threshold=threshold,
                notify_mode=notify_mode,
                workspace_id=workspace_id,
            )

        draft = WatchInterest(
            id="",
            user_id=user_id,
            target_kind=target_storage["target_kind"],
            chat_id=target_storage["chat_id"],
            channel_id=target_storage["channel_id"],
            title=title,
            description=description,
            keywords=list(keywords or []),
            exclude_keywords=list(exclude_keywords or []),
            channel_ids=list(channel_ids),
            workspace_id=workspace_id,
            threshold=_FALLBACK_DEFAULT_THRESHOLD,
            notify_mode=notify_mode,
            is_active=True,
            embedding=None,
        )
        embedding = await self._embed_interest(draft)
        if embedding is not None:
            draft = draft.model_copy(update={"embedding": embedding})

        resolved_threshold, calibration = await self._resolve_threshold_for_new_interest(
            draft, threshold
        )
        draft = draft.model_copy(
            update={
                "threshold": resolved_threshold,
                "threshold_source": "manual" if threshold is not None else "auto",
            }
        )

        try:
            stored = await self.interest_repo.create(draft)
        except IntegrityError:
            # Race: a concurrent caller won the INSERT between our
            # find_by_user_and_title and create. Reload and apply as
            # UPDATE so the result still collapses to a single row.
            logger.info(
                "watchlist.subscribe_race_retry_update",
                user_id=user_id,
                title=title,
            )
            # The failed INSERT leaves the AsyncSession in an aborted-transaction
            # state; without this rollback the subsequent SELECT/UPDATE raise
            # PendingRollbackError and the idempotent-upsert retry can never run
            # (BUG-029, symmetric with digest_service).
            await self.interest_repo.session.rollback()
            existing = await self.interest_repo.find_by_user_and_title(user_id, title)
            if existing is None:
                raise
            return await self._apply_upsert(
                existing=existing,
                target_storage=target_storage,
                description=description,
                keywords=keywords,
                exclude_keywords=exclude_keywords,
                channel_ids=channel_ids,
                threshold=threshold,
                notify_mode=notify_mode,
                workspace_id=workspace_id,
            )

        if embedding is not None:
            await self.interest_repo.update_embedding(stored.id, embedding)
            stored = stored.model_copy(update={"embedding": embedding})

        return SubscribeResult(
            interest=stored,
            created=True,
            changed_fields=[],
            threshold_calibration=calibration,
        )

    async def _apply_upsert(
        self,
        *,
        existing: WatchInterest,
        target_storage: dict[str, object],
        description: str | None,
        keywords: list[str] | None,
        exclude_keywords: list[str] | None,
        channel_ids: list[str],
        threshold: float | None,
        notify_mode: NotifyMode,
        workspace_id: str | None,
    ) -> SubscribeResult:
        """Compute the diff between ``existing`` and the new payload, then UPDATE.

        ``changed_fields`` mirrors Pydantic field names (Q-OPEN-1 from
        sprint prompt §8 — locked at execution time to ``list[str]``).
        ``workspace_id`` participates in the diff but is never
        "unset to NULL" by this path: only an explicit None-arg with
        ENH-9 semantics future-extension would do so. Today, passing
        ``workspace_id=None`` to subscribe means "leave whatever the
        row currently has" — matches the additive-only contract Q3-A.
        """
        new_keywords = list(keywords or [])
        new_exclude = list(exclude_keywords or [])
        new_channels = list(channel_ids)

        update_kwargs: dict[str, object] = {}
        changed_fields: list[str] = []

        if existing.target_kind != target_storage["target_kind"]:
            update_kwargs["target_kind"] = target_storage["target_kind"]
            changed_fields.append("target_kind")
        if existing.chat_id != target_storage["chat_id"]:
            update_kwargs["chat_id"] = target_storage["chat_id"]
            changed_fields.append("chat_id")
        if existing.channel_id != target_storage["channel_id"]:
            if target_storage["channel_id"] is None:
                update_kwargs["unset_channel_id"] = True
            else:
                update_kwargs["channel_id"] = target_storage["channel_id"]
            changed_fields.append("channel_id")
        if (existing.description or None) != (description or None):
            update_kwargs["description"] = description
            changed_fields.append("description")
        if list(existing.keywords) != new_keywords:
            update_kwargs["keywords"] = new_keywords
            changed_fields.append("keywords")
        if list(existing.exclude_keywords) != new_exclude:
            update_kwargs["exclude_keywords"] = new_exclude
            changed_fields.append("exclude_keywords")
        if list(existing.channel_ids) != new_channels:
            update_kwargs["channel_ids"] = new_channels
            changed_fields.append("channel_ids")
        if existing.notify_mode != notify_mode:
            update_kwargs["notify_mode"] = notify_mode
            changed_fields.append("notify_mode")
        if not existing.is_active:
            update_kwargs["is_active"] = True
            changed_fields.append("is_active")
        if workspace_id is not None and existing.workspace_id != workspace_id:
            update_kwargs["workspace_id"] = workspace_id
            changed_fields.append("workspace_id")

        # BUG-054 / ADR 0015: a change to a scoring-relevant text field
        # (description / keywords / channel_ids) re-embeds the interest and
        # re-runs ADR-0012 calibration. ``exclude_keywords`` / target /
        # notify_mode / workspace changes are NOT in the embedding text, so
        # they never trigger this path. ``title`` is the natural key, not
        # upsert-mutable, so it is never in the delta.
        advisory: ThresholdCalibration | None = None
        text_delta = {"description", "keywords", "channel_ids"} & set(changed_fields)
        if text_delta:
            merged = existing.model_copy(
                update={
                    "description": description,
                    "keywords": new_keywords,
                    "channel_ids": new_channels,
                }
            )
            embedding = await self._embed_interest(merged)
            if embedding is not None:
                await self.interest_repo.update_embedding(existing.id, embedding)
                merged = merged.model_copy(update={"embedding": embedding})
            calibration = await self.calibrate_threshold(merged)
            if existing.threshold_source == "auto":
                update_kwargs["threshold"] = calibration.suggested_threshold
                if "threshold" not in changed_fields:
                    changed_fields.append("threshold")
            else:
                # manual / legacy / NULL → never overwrite an operator-pinned or
                # unknown-provenance cutoff; surface the suggestion as advisory.
                advisory = calibration

        # An explicit threshold on update always wins: persist it and (re)mark
        # the provenance manual, overriding any auto-recalibration above.
        if threshold is not None and abs(existing.threshold - threshold) > 1e-9:
            update_kwargs["threshold"] = threshold
            update_kwargs["threshold_source"] = "manual"
            if "threshold" not in changed_fields:
                changed_fields.append("threshold")
            advisory = None

        if not update_kwargs:
            return SubscribeResult(interest=existing, created=False, changed_fields=[])

        updated = await self.interest_repo.update_subscribe_fields(existing.id, **update_kwargs)
        if updated is None:
            updated = existing
        return SubscribeResult(
            interest=updated,
            created=False,
            changed_fields=changed_fields,
            threshold_calibration=advisory,
        )

    async def soft_delete_interest(self, interest_id: str) -> bool:
        """Mark an interest inactive while preserving its match history."""
        return await self.interest_repo.soft_delete(interest_id)

    async def list_user_interests(self, user_id: str) -> list[WatchInterest]:
        """Return all (active or paused) interests owned by ``user_id``."""
        return await self.interest_repo.list_for_user(user_id)

    async def get_interest(self, interest_id: str) -> WatchInterest | None:
        """Fetch a single interest by id."""
        return await self.interest_repo.get(interest_id)

    async def delete_interest_for_user(
        self,
        interest_id: str,
        *,
        requesting_user_id: str,
        is_admin: bool,
    ) -> tuple[bool, str | None]:
        """Soft-delete ``interest_id`` enforcing ownership.

        Returns ``(deleted, error_message)``. ``error_message`` is ``None`` on
        success and a short, human-friendly reason otherwise (used by MCP / bot
        / CLI to surface a clean error). Permission check mirrors the F6
        digest-tools model: admin bypasses owner check.
        """
        existing = await self.interest_repo.get(interest_id)
        if existing is None:
            return False, "interest not found"
        if not is_admin and existing.user_id != requesting_user_id:
            return False, "permission denied (owner-only)"
        # BUG-027: explicit is_active guard so the caller receives a typed
        # "already_inactive" sentinel instead of the ambiguous
        # "delete failed (already inactive?)" question that was returned
        # when soft_delete's WHERE … AND is_active = TRUE matched 0 rows.
        if not existing.is_active:
            return False, "already_inactive"
        deleted = await self.interest_repo.soft_delete(interest_id)
        if not deleted:
            # Structurally unreachable after the is_active guard above, but
            # kept as a defence-in-depth fallback (no longer a question).
            return False, "delete failed"
        return True, None

    async def get_matches(
        self,
        interest_id: str,
        *,
        since: datetime | None = None,
    ) -> list[WatchMatch]:
        """Return matches for ``interest_id`` (optionally filtered by ``since``)."""
        return await self.match_repo.list_for_interest(interest_id, since=since)

    # ---- Scheduler hook ----

    async def check_interests(
        self,
        channel_id: str,
        new_doc_refs: list[str],
        *,
        bot: Bot | None = None,
    ) -> list[WatchMatch]:
        """Score ``new_doc_refs`` against active interests for ``channel_id``.

        Returns the freshly inserted matches (idempotent on re-run thanks to
        the unique constraint). Side-effects:

        - Persists matches via ``WatchMatchRepo.upsert_many``.
        - Updates ``last_checked_at`` on **every active interest of the
          channel, on EVERY tick** — including quiet ticks with an empty
          ``new_doc_refs``. ``last_checked_at`` is a matcher-liveness /
          "last evaluated" signal, NOT "last tick that carried new docs"
          (ENH-001). Matching itself is still gated on new docs below; only
          the freshness stamp fires unconditionally.
        - Updates ``last_match_at`` on interests that produced at least one
          new match this tick.
        """
        active = await self.interest_repo.list_active_for_channel(channel_id)
        await self._refresh_active_gauge()
        if not active:
            logger.debug("watchlist.no_active_interests", channel_id=channel_id)
            return []

        # ENH-001: quiet tick (no new docs) — still stamp ``last_checked_at``
        # on every active interest so the field honestly reflects evaluation
        # cadence, then short-circuit (nothing to score). Without this the
        # field stays null/stale for newly-created interests and quiet
        # channels even though the matcher is healthy (the OBS-001 symptom).
        if not new_doc_refs:
            now = datetime.now(UTC)
            for interest in active:
                await self.interest_repo.touch_checked(interest.id, now)
            logger.info(
                "watchlist.check_interests",
                channel_id=channel_id,
                interests=len(active),
                docs=0,
                candidates=0,
                inserted=0,
            )
            return []

        capped_refs = new_doc_refs[:MAX_DOCS_PER_TICK]
        if len(new_doc_refs) > MAX_DOCS_PER_TICK:
            logger.warning(
                "watchlist.docs_capped",
                channel_id=channel_id,
                seen=len(new_doc_refs),
                cap=MAX_DOCS_PER_TICK,
            )

        docs_by_ref = await self.processed_doc_repo.get_by_source_refs(capped_refs)
        if not docs_by_ref:
            logger.debug(
                "watchlist.no_processed_docs",
                channel_id=channel_id,
                refs=len(capped_refs),
            )
            now = datetime.now(UTC)
            for interest in active:
                await self.interest_repo.touch_checked(interest.id, now)
            return []

        # BUG-055: one batched fetch instead of a per-ref N+1 round-trip,
        # mirroring backfill_interest / _collect_corpus_combined_scores. Refs
        # with no stored embedding are absent from the dict → mapped to None.
        stored_embeddings = await self.embedding_repo.get_many_by_source_refs(list(docs_by_ref))
        embeddings_by_ref: dict[str, list[float] | None] = {
            ref: (stored_embeddings[ref].embedding if ref in stored_embeddings else None)
            for ref in docs_by_ref
        }

        # F-08 (O-7): lemmatise each document ONCE per tick. The nested loop
        # below is O(interests × docs); building the token set inside
        # compute_watch_score would re-run pymorphy3 on the same doc for every
        # interest (O(I×D) lemmatisations). Precompute it here (O(D)) and inject
        # the cached set — scores stay byte-for-byte identical because the same
        # pure _build_doc_tokens produces them.
        doc_tokens_by_ref: dict[str, set[str]] = {
            ref: _build_doc_tokens(doc) for ref, doc in docs_by_ref.items()
        }

        all_candidates: list[WatchMatch] = []
        match_count_by_interest: dict[str, int] = {}
        # DIAG 2026-06-07 (Tier 0 observability): sub-threshold scores are
        # otherwise only visible in the Prometheus histogram. Track the best
        # (highest combined) score seen per interest this tick so operators can
        # read the real score ceiling vs the configured threshold straight from
        # the logs — the signal needed to tune thresholds (hypothesis C).
        ceiling_by_interest: list[dict[str, object]] = []

        for interest in active:
            if interest.embedding is None:
                lazy = await self._embed_interest(interest)
                if lazy is not None:
                    await self.interest_repo.update_embedding(interest.id, lazy)
                    interest = interest.model_copy(update={"embedding": lazy})

            best: WatchScore | None = None
            for ref, doc in docs_by_ref.items():
                doc_emb = embeddings_by_ref.get(ref)
                score = compute_watch_score(
                    interest,
                    doc,
                    doc_emb,
                    keyword_weight=self._keyword_weight,
                    semantic_weight=self._semantic_weight,
                    aggregation=self._keyword_aggregation,
                    topk=self._keyword_topk,
                    doc_tokens=doc_tokens_by_ref.get(ref),
                )
                if best is None or score.combined > best.combined:
                    best = score
                if score.excluded:
                    record_watchlist_match(result="filtered_keywords", score=score.combined)
                    continue
                if score.combined < interest.threshold:
                    record_watchlist_match(result="filtered_threshold", score=score.combined)
                    continue
                record_watchlist_match(result="delivered", score=score.combined)
                # F11 P2 (ADR-0014, Fork 3 = journal): SILENT interests record
                # the match in history with ``notified=True`` at creation time
                # (mirrors the backfill convention). Such a row is never pushed
                # by the instant ``notify`` path (it is skipped as non-instant)
                # AND is never picked up by the batch flush (the flush selects
                # ``notified=False`` only) — it is journal-only, visible via
                # ``get_watchlist_matches`` / ``list_for_interest``.
                silent = interest.notify_mode == NotifyMode.SILENT
                all_candidates.append(
                    WatchMatch(
                        id=0,
                        interest_id=interest.id,
                        source_ref=ref,
                        channel_id=doc.channel_id,
                        keyword_score=score.keyword,
                        semantic_score=score.semantic,
                        combined_score=score.combined,
                        notified=silent,
                    )
                )
                match_count_by_interest[interest.id] = (
                    match_count_by_interest.get(interest.id, 0) + 1
                )

            if best is not None:
                ceiling_by_interest.append(
                    {
                        "interest_id": interest.id,
                        "title": interest.title,
                        "threshold": round(interest.threshold, 4),
                        "max_combined": round(best.combined, 4),
                        "max_keyword": round(best.keyword, 4),
                        "max_semantic": round(best.semantic, 4),
                    }
                )

        inserted = await self.match_repo.upsert_many(all_candidates)

        now = datetime.now(UTC)
        for interest in active:
            await self.interest_repo.touch_checked(interest.id, now)
        for interest_id in match_count_by_interest:
            await self.interest_repo.touch_match(interest_id, now)

        logger.info(
            "watchlist.check_interests",
            channel_id=channel_id,
            interests=len(active),
            docs=len(docs_by_ref),
            candidates=len(all_candidates),
            inserted=len(inserted),
        )
        if not all_candidates and ceiling_by_interest:
            # No matches this tick — surface the per-interest score ceiling so a
            # persistent zero is diagnosable without a DB round-trip.
            logger.info(
                "watchlist.score_ceiling",
                channel_id=channel_id,
                ceilings=ceiling_by_interest,
            )

        if inserted:
            if bot is not None:
                try:
                    # BUG-055: pass the already-loaded active interests so notify()
                    # need not re-fetch each one via interest_repo.get() (N+1).
                    interests_by_id = {interest.id: interest for interest in active}
                    await self.notify(
                        inserted,
                        bot,
                        docs_by_ref=docs_by_ref,
                        interests_by_id=interests_by_id,
                    )
                except Exception as exc:
                    logger.exception(
                        "watchlist.notify_failed",
                        channel_id=channel_id,
                        inserted=len(inserted),
                        error=str(exc),
                    )
            else:
                self._log_delivery_deferred(channel_id, inserted, active)

        return inserted

    def _log_delivery_deferred(
        self,
        channel_id: str,
        inserted: list[WatchMatch],
        active: list[WatchInterest],
    ) -> None:
        """Say out loud that this process cannot deliver (BUG-095).

        The batch neighbour has logged ``watchlist_batch_flush_skipped
        reason="no_bot"`` since 2026-06-11; the instant path had the same
        condition behind a bare ``if bot is not None`` and said nothing, which
        is why two months of undelivered matches looked like silence rather
        than like a failure. Delivery is not lost here — the matches keep
        ``notified=False`` and the bot-process instant flush claims them — so
        this is INFO, the same level as its batch counterpart.

        Only INSTANT matches are counted. SILENT ones are journal-only by design
        (ADR-0014, born ``notified=True``) and BATCH ones are waiting for their
        own daily cron, so reporting either as deferred would make the line fire
        on a healthy system.
        """
        modes = {interest.id: interest.notify_mode for interest in active}
        pending = [m for m in inserted if modes.get(m.interest_id) == NotifyMode.INSTANT]
        if not pending:
            return
        logger.info(
            "watchlist.instant_delivery_deferred",
            channel_id=channel_id,
            pending=len(pending),
            reason="no_bot",
            handoff="watchlist_instant_flush",
        )

    # ---- Retroactive backfill (DIAG 2026-06-07 hypothesis B2) ----

    async def backfill_interest(
        self,
        interest_id: str,
        *,
        since: datetime | None = None,
        limit: int | None = None,
        dry_run: bool = True,
    ) -> BackfillResult:
        """Score historical ``processed_documents`` against one interest (ADR-0011).

        Closes the retroactive gap (B2): the scheduler only scores per-tick
        ``new_doc_refs``, so a corpus ingested *before* an interest was created
        is never evaluated. This walks every watched channel's documents since
        ``since`` and scores the whole matched corpus in a single batched pass;
        when ``dry_run`` is False it persists matches via the same idempotent
        ``upsert_many`` path the scheduler uses.

        ADR-0011 reworks three previously-conflated concerns:

        - **Default cutoff = full corpus.** ``since=None`` now means *no lower
          date bound* (the whole corpus), NOT ``interest.created_at``. A freshly
          created interest had ``created_at ≈ now`` → an empty window → 0
          candidates (Problem A). Pass an explicit ``since`` to keep the old
          windowed behaviour.
        - **Scoring budget = whole matched corpus.** The historical
          ``MAX_BACKFILL_DOCS=2000`` newest-first cap hid old on-topic docs from
          calibration (Problem B) and is retired as a scoring cap. The N+1
          per-ref embedding fetch is replaced by one batched
          :meth:`EmbeddingRepo.get_many_by_source_refs`. ``limit`` is optional
          and only honoured when a caller explicitly asks for a newest-first
          preview — scoring is never silently truncated.
        - **Materialization = silent + idempotent.** On ``dry_run=False`` ALL
          matches are materialized (no arbitrary cap) with ``notified=True`` so
          they appear in match history but are NOT retroactively pushed (the
          flood risk is notification, not row count). Go-forward per-tick
          matches (see :meth:`check_interests`) keep ``notified=False`` and
          notify normally — unchanged.

        Safety:

        - ``dry_run=True`` (default) performs scoring only: no ``watch_matches``
          rows, no ``last_*_at`` writes. The returned ``would_match`` /
          ``max_combined`` let an operator preview the impact before committing.
        - Idempotent on re-run via ``UNIQUE (interest_id, source_ref)``.
        - Backfill never notifies; the explicit-confirmation gate for the
          mutating apply path lives in the CLI / MCP entrypoints.
        """
        effective_limit = max(1, limit) if limit is not None else None

        interest = await self.interest_repo.get(interest_id)
        if interest is None:
            return BackfillResult(
                interest_id=interest_id,
                scored_docs=0,
                candidates=0,
                inserted=0,
                max_combined=0.0,
                would_match=0,
                dry_run=dry_run,
                error="interest not found",
            )
        if not interest.is_active:
            return BackfillResult(
                interest_id=interest_id,
                scored_docs=0,
                candidates=0,
                inserted=0,
                max_combined=0.0,
                would_match=0,
                dry_run=dry_run,
                error="interest is inactive",
            )

        if interest.embedding is None:
            lazy = await self._embed_interest(interest)
            if lazy is not None:
                if not dry_run:
                    await self.interest_repo.update_embedding(interest.id, lazy)
                interest = interest.model_copy(update={"embedding": lazy})

        # ADR-0011: ``since=None`` → no lower date bound (full corpus), so a
        # freshly created interest is no longer scored against an empty window.
        cutoff = since

        docs_by_ref: dict[str, ProcessedDocument] = {}
        for channel_id in interest.channel_ids:
            channel_docs = await self.processed_doc_repo.list_by_channel(
                channel_id, from_date=cutoff
            )
            for doc in channel_docs:
                docs_by_ref[doc.source_ref] = doc

        # ADR-0011: no implicit scoring cap. ``effective_limit`` is only set
        # when a caller explicitly asks for a newest-first preview; otherwise
        # the whole matched corpus is scored.
        if effective_limit is not None:
            ordered = sorted(docs_by_ref.values(), key=lambda d: d.processed_at, reverse=True)
            ordered = ordered[:effective_limit]
            scored_docs = {doc.source_ref: doc for doc in ordered}
        else:
            scored_docs = dict(docs_by_ref)

        # ADR-0011: batched embedding fetch kills the per-ref N+1 round-trip.
        stored_embeddings = await self.embedding_repo.get_many_by_source_refs(list(scored_docs))
        embeddings_by_ref: dict[str, list[float] | None] = {
            ref: (stored_embeddings[ref].embedding if ref in stored_embeddings else None)
            for ref in scored_docs
        }

        candidates: list[WatchMatch] = []
        max_combined = 0.0
        for ref, doc in scored_docs.items():
            score = compute_watch_score(
                interest,
                doc,
                embeddings_by_ref.get(ref),
                keyword_weight=self._keyword_weight,
                semantic_weight=self._semantic_weight,
                aggregation=self._keyword_aggregation,
                topk=self._keyword_topk,
            )
            if score.combined > max_combined:
                max_combined = score.combined
            if score.excluded:
                record_watchlist_match(result="filtered_keywords", score=score.combined)
                continue
            if score.combined < interest.threshold:
                record_watchlist_match(result="filtered_threshold", score=score.combined)
                continue
            record_watchlist_match(result="delivered", score=score.combined)
            candidates.append(
                WatchMatch(
                    id=0,
                    interest_id=interest.id,
                    source_ref=ref,
                    channel_id=doc.channel_id,
                    keyword_score=score.keyword,
                    semantic_score=score.semantic,
                    combined_score=score.combined,
                    # ADR-0011: backfill matches are silent ("seen") — they land
                    # in match history but must NOT trigger a retroactive push.
                    notified=True,
                )
            )

        would_match = len(candidates)

        if dry_run:
            logger.info(
                "watchlist.backfill_dry_run",
                interest_id=interest.id,
                scored=len(scored_docs),
                would_match=would_match,
                max_combined=round(max_combined, 4),
                threshold=interest.threshold,
            )
            return BackfillResult(
                interest_id=interest.id,
                scored_docs=len(scored_docs),
                candidates=would_match,
                inserted=0,
                max_combined=round(max_combined, 4),
                would_match=would_match,
                dry_run=True,
            )

        inserted = await self.match_repo.upsert_many(candidates)

        now = datetime.now(UTC)
        await self.interest_repo.touch_checked(interest.id, now)
        if inserted:
            await self.interest_repo.touch_match(interest.id, now)

        logger.info(
            "watchlist.backfill",
            interest_id=interest.id,
            scored=len(scored_docs),
            candidates=would_match,
            inserted=len(inserted),
            max_combined=round(max_combined, 4),
            threshold=interest.threshold,
        )

        # ADR-0011: backfill never notifies — matches are materialized silently
        # (``notified=True``). Go-forward per-tick notification is unchanged.

        return BackfillResult(
            interest_id=interest.id,
            scored_docs=len(scored_docs),
            candidates=would_match,
            inserted=len(inserted),
            max_combined=round(max_combined, 4),
            would_match=would_match,
            dry_run=False,
        )

    # ---- Notification ----

    async def notify(
        self,
        matches: list[WatchMatch],
        bot: Bot,
        *,
        docs_by_ref: dict[str, ProcessedDocument] | None = None,
        interests_by_id: dict[str, WatchInterest] | None = None,
    ) -> dict[str, str]:
        """Group ``matches`` by ``interest_id`` and dispatch one push per group.

        Returns a status dict keyed by ``interest_id`` with values
        ``"sent" | "skipped_inactive" | "skipped_non_instant" | "interest_missing" |
        "send_failed"`` so the scheduler / tests can assert outcomes without
        scraping logs.

        Behaviour:

        - ``MAX_PREVIEWS_PER_NOTIFICATION`` matches are previewed inline; the
          remaining are summarised as ``+N more``.
        - ``mark_notified`` is invoked **only** for groups that were actually
          delivered, so a failure on one interest never poisons another.
        - If the underlying ``bot.send_message`` raises a "chat not found" /
          "blocked" error (gotcha #5), the interest is soft-deleted to stop
          retry storms; the matches themselves are preserved.
        """
        if not matches:
            return {}

        groups: dict[str, list[WatchMatch]] = {}
        for match in matches:
            groups.setdefault(match.interest_id, []).append(match)

        missing_refs: set[str] = set()
        if docs_by_ref is None:
            docs_by_ref = {}
        for group in groups.values():
            for m in group:
                if m.source_ref not in docs_by_ref:
                    missing_refs.add(m.source_ref)
        if missing_refs:
            extra = await self.processed_doc_repo.get_by_source_refs(list(missing_refs))
            docs_by_ref = {**docs_by_ref, **extra}

        outcomes: dict[str, str] = {}
        for interest_id, group_matches in groups.items():
            # BUG-055: prefer the pre-loaded map (from check_interests) to avoid
            # an interest_repo.get() per group; fall back to a fetch for callers
            # that cannot supply it.
            interest = None
            if interests_by_id is not None:
                interest = interests_by_id.get(interest_id)
            if interest is None:
                interest = await self.interest_repo.get(interest_id)
            if interest is None:
                outcomes[interest_id] = "interest_missing"
                continue
            if not interest.is_active:
                outcomes[interest_id] = "skipped_inactive"
                continue
            if interest.notify_mode != NotifyMode.INSTANT:
                outcomes[interest_id] = "skipped_non_instant"
                continue

            outcomes[interest_id] = await self._send_group(
                interest, group_matches, docs_by_ref, bot
            )

        return outcomes

    async def _send_group(
        self,
        interest: WatchInterest,
        group_matches: list[WatchMatch],
        docs_by_ref: dict[str, ProcessedDocument],
        bot: Bot,
    ) -> str:
        """Compose + dispatch one ``(interest, matches)`` group; return the outcome.

        Shared by the instant :meth:`notify` and the batch :meth:`flush_batch`
        delivery paths (ADR-0014) so both reuse exactly one send/failure/watermark
        implementation. The caller is responsible for the mode / active checks
        (instant filters ``notify_mode != INSTANT``; batch pre-selects active
        batch-mode interests) — this helper assumes the group is dispatchable.

        Returns ``"sent"`` on success or ``"send_failed"`` on a ``send_message``
        error. Failure handling mirrors the original instant path:

        - ``_BOT_PERMANENT_FAILURE_FRAGMENTS`` (blocked / chat-not-found) →
          soft-delete the orphaned interest to stop retry storms, preserve the
          matches, and ``record_watchlist_delivery(outcome="blocked")``.
        - transient error → ``record_watchlist_delivery(outcome="error")``;
          interest left intact for the next attempt.
        - ``mark_notified`` is the batch watermark and is flipped ONLY after a
          successful send, so a failed send leaves the matches pending (a later
          flush retries them). A ``mark_notified`` failure is soft (the user
          already received the message).
        """
        from aiogram.enums import ParseMode

        text = compose_match_notification(interest, group_matches, docs_by_ref)
        try:
            await bot.send_message(
                chat_id=interest.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as exc:
            error_text = str(exc).lower()
            permanent = any(fragment in error_text for fragment in _BOT_PERMANENT_FAILURE_FRAGMENTS)
            logger.warning(
                "watchlist.notify_send_failed",
                interest_id=interest.id,
                chat_id=interest.chat_id,
                permanent=permanent,
                error=str(exc),
            )
            if permanent:
                try:
                    await self.interest_repo.soft_delete(interest.id)
                except Exception:
                    logger.exception(
                        "watchlist.notify_soft_delete_failed",
                        interest_id=interest.id,
                    )
            record_watchlist_delivery(outcome="blocked" if permanent else "error")
            return "send_failed"

        try:
            ids = [m.id for m in group_matches if m.id]
            if ids:
                await self.match_repo.mark_notified(ids)
        except Exception:
            logger.exception(
                "watchlist.mark_notified_failed",
                interest_id=interest.id,
                match_count=len(group_matches),
            )
        record_watchlist_delivery(outcome="sent")
        return "sent"

    # ---- Batch flush (F11 P2 / ADR-0014) ----

    async def flush_batch(self, bot: Bot) -> dict[str, str]:
        """Deliver pending matches for active BATCH-mode interests (ADR-0014).

        Driven by ONE global cron flush task (not per-subscription, not
        per-interest — Fork 1). Per tick:

        1. Fetch every **active** ``NotifyMode.BATCH`` interest (capped by
           ``watchlist_batch_max_interests_per_tick`` as a flood guard).
        2. Select their ``notified=False`` matches in one round-trip
           (``list_unnotified_for_interests`` — the ``notified`` flag IS the
           batch watermark, Fork 4).
        3. Group by ``interest_id`` and dispatch one grouped message per
           interest via the shared :meth:`_send_group` helper (same compose /
           blocked-soft-delete / record / mark-notified-on-success path as the
           instant push, Fork 2).

        Watermark semantics: ``mark_notified`` flips ``notified=True`` ONLY on a
        successful send, so a failed send leaves the matches pending for the
        next flush (Fork 4). Paused interests are skipped by the ``is_active``
        filter, so their pending matches naturally flush on resume (Fork 5).
        SILENT matches were recorded ``notified=True`` at creation and are never
        selected here (Fork 3). An empty window (no ``notified=False`` rows) is a
        no-op that sends nothing (Fork 6 / empty window).

        Returns a per-interest outcome dict (same value vocabulary as
        :meth:`notify`) so the scheduler / tests can assert without scraping
        logs. Interests with no pending matches are omitted from the result.
        """
        all_interests = await self.interest_repo.list_all()
        batch_interests = [
            i for i in all_interests if i.is_active and i.notify_mode == NotifyMode.BATCH
        ]
        if not batch_interests:
            return {}

        max_per_tick = _load_batch_max_interests_per_tick()
        if max_per_tick > 0 and len(batch_interests) > max_per_tick:
            logger.warning(
                "watchlist.batch_interests_capped",
                seen=len(batch_interests),
                cap=max_per_tick,
            )
            batch_interests = batch_interests[:max_per_tick]

        by_id = {i.id: i for i in batch_interests}
        pending = await self.match_repo.list_unnotified_for_interests(list(by_id))
        if not pending:
            return {}

        groups: dict[str, list[WatchMatch]] = {}
        for match in pending:
            if match.interest_id in by_id:
                groups.setdefault(match.interest_id, []).append(match)
        if not groups:
            return {}

        all_refs = {m.source_ref for group in groups.values() for m in group}
        docs_by_ref = await self.processed_doc_repo.get_by_source_refs(list(all_refs))

        outcomes: dict[str, str] = {}
        for interest_id, group_matches in groups.items():
            interest = by_id[interest_id]
            outcomes[interest_id] = await self._send_group(
                interest, group_matches, docs_by_ref, bot
            )

        logger.info(
            "watchlist.flush_batch",
            interests=len(groups),
            matches=len(pending),
            sent=sum(1 for v in outcomes.values() if v == "sent"),
        )
        return outcomes

    # ---- Instant flush from the bot process (BUG-095) ----

    async def flush_instant(self, bot: Bot, *, since: datetime) -> dict[str, str]:
        """Deliver pending matches for active INSTANT interests (BUG-095).

        The instant matcher runs inside ``tg_parser``, where ``get_bot()`` is
        permanently ``None``, so :meth:`check_interests` records the match and
        cannot push it. This flush is the delivery half, and it runs where the
        batch flush already runs: the bot process, the only one holding a live
        ``Bot``. Structurally it is :meth:`flush_batch` with
        ``NotifyMode.INSTANT`` in place of ``BATCH`` — same selector, same
        grouping, same :meth:`_send_group`, so retries, blocked-chat handling
        and the ``notified`` watermark stay in exactly one implementation.

        ``since`` is mandatory and is the whole reason this is not a copy of
        ``flush_batch``: ``list_unnotified_for_interests`` has no date bound, so
        an unbounded first tick would deliver every match accumulated since the
        outage began — the fix would produce the flood that the backlog decision
        exists to prevent. Matches older than ``since`` are left alone for
        ``scripts/watchlist_backlog_summary.py`` to summarise once.

        Returns a per-interest outcome dict (same vocabulary as :meth:`notify`);
        interests with no pending matches in the window are omitted.
        """
        instant_interests = await self._active_instant_interests()
        if not instant_interests:
            return {}

        by_id = {i.id: i for i in instant_interests}
        pending = await self.match_repo.list_unnotified_for_interests(list(by_id), since=since)
        if not pending:
            return {}

        groups: dict[str, list[WatchMatch]] = {}
        for match in pending:
            if match.interest_id in by_id:
                groups.setdefault(match.interest_id, []).append(match)
        if not groups:
            return {}

        all_refs = {m.source_ref for group in groups.values() for m in group}
        docs_by_ref = await self.processed_doc_repo.get_by_source_refs(list(all_refs))

        outcomes: dict[str, str] = {}
        for interest_id, group_matches in groups.items():
            outcomes[interest_id] = await self._send_group(
                by_id[interest_id], group_matches, docs_by_ref, bot
            )

        logger.info(
            "watchlist.flush_instant",
            interests=len(groups),
            matches=len(pending),
            sent=sum(1 for v in outcomes.values() if v == "sent"),
            since=since.isoformat(),
        )
        return outcomes

    async def count_undelivered(self, *, older_than: datetime) -> int:
        """Count instant matches still undelivered past their delivery window.

        The blind spot BUG-095 lived in: an undelivered match had no metric and
        no alert, so two months of them looked exactly like two months of quiet.
        ``older_than`` excludes matches still inside the current flush interval,
        which are pending rather than missed — without it the gauge would blink
        on every ordinary tick and teach the operator to ignore it, the very
        mechanism that kept this bug alive.
        """
        instant_interests = await self._active_instant_interests()
        if not instant_interests:
            return 0
        return await self.match_repo.count_unnotified_for_interests(
            [i.id for i in instant_interests], before=older_than
        )

    async def _active_instant_interests(self) -> list[WatchInterest]:
        """Active ``NotifyMode.INSTANT`` interests, capped by the flood guard."""
        all_interests = await self.interest_repo.list_all()
        instant = [i for i in all_interests if i.is_active and i.notify_mode == NotifyMode.INSTANT]
        max_per_tick = _load_instant_max_interests_per_tick()
        if max_per_tick > 0 and len(instant) > max_per_tick:
            logger.warning(
                "watchlist.instant_interests_capped",
                seen=len(instant),
                cap=max_per_tick,
            )
            instant = instant[:max_per_tick]
        return instant

    # ---- One-off backlog reconciliation (BUG-095 §3.3) ----

    async def summarize_backlog(
        self,
        bot: Bot | None,
        *,
        before: datetime,
        dry_run: bool = True,
    ) -> list[BacklogSummary]:
        """Close out matches that were never delivered, with one summary per chat.

        The owner's decision of 2026-08-13: the ~76 matches stranded by BUG-095
        are marked handled and the user is told **once** how much was missed and
        over what period — not replayed as posts. Replaying them would deliver
        two-month-old "alerts", which reads as a broken bot rather than as
        recovered history; the posts themselves were never lost and stay
        readable through ``get_watchlist_matches``.

        One message per **chat**, not per system and not per interest: interests
        belong to different ``chat_id`` values, so a chat may only be told about
        its own. A chat owning several interests gets one message with a
        per-interest breakdown.

        Idempotency comes from the same watermark the delivery paths use rather
        than from a marker table: the working set is the ``notified=false`` rows,
        and a successful send flips them, so an immediate second run finds
        nothing and sends nothing. That also means the operation is safe to
        re-run later — it will then report only what has genuinely gone
        undelivered since.

        ``before`` must be the instant-flush watermark, which partitions the
        pending rows: the flush owns ``created_at >= watermark`` and this owns
        everything older, so neither can take the other's matches whatever order
        they run in. ``dry_run=True`` (the default) computes and returns the
        summaries without sending or marking anything, and accepts ``bot=None``
        so the preview can be run from a process that has no Telegram token.
        """
        if not dry_run and bot is None:
            raise ValueError("summarize_backlog(dry_run=False) needs a live Bot")

        instant_interests = await self._active_instant_interests()
        if not instant_interests:
            return []

        by_id = {i.id: i for i in instant_interests}
        pending = await self.match_repo.list_unnotified_for_interests(list(by_id), before=before)
        if not pending:
            return []

        by_chat: dict[int, list[WatchMatch]] = {}
        for match in pending:
            interest = by_id.get(match.interest_id)
            if interest is None or interest.chat_id is None:
                continue
            by_chat.setdefault(interest.chat_id, []).append(match)

        summaries: list[BacklogSummary] = []
        for chat_id, chat_matches in sorted(by_chat.items()):
            entries = _backlog_entries(chat_matches, by_id)
            text = compose_backlog_summary(entries)
            summary = BacklogSummary(
                chat_id=chat_id,
                entries=entries,
                match_count=len(chat_matches),
                text=text,
                sent=False,
            )
            if not dry_run:
                summary.sent = await self._send_backlog_summary(bot, chat_id, text, chat_matches)
            summaries.append(summary)

        logger.info(
            "watchlist.backlog_summary",
            chats=len(summaries),
            matches=sum(s.match_count for s in summaries),
            dry_run=dry_run,
            sent=sum(1 for s in summaries if s.sent),
        )
        return summaries

    async def _send_backlog_summary(
        self,
        bot: Bot,
        chat_id: int,
        text: str,
        matches: list[WatchMatch],
    ) -> bool:
        """Send one chat's summary and mark its matches handled on success.

        Deliberately not routed through :meth:`_send_group`: that helper is
        per-interest and pairs a message with the matches it previews, while
        this is one cross-interest message per chat. What it does share is the
        watermark rule — ``mark_notified`` only after a successful send, so a
        failed chat is retried by the next run instead of being silently closed.
        """
        from aiogram.enums import ParseMode

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as exc:
            logger.warning(
                "watchlist.backlog_summary_send_failed",
                chat_id=chat_id,
                matches=len(matches),
                error=str(exc),
            )
            return False

        ids = [m.id for m in matches if m.id]
        if ids:
            await self.match_repo.mark_notified(ids)
        return True

    # ---- Threshold calibration (ADR 0012 / S2) ----

    async def calibrate_threshold(
        self,
        interest: WatchInterest,
        *,
        since: datetime | None = None,
    ) -> ThresholdCalibration:
        """Score the interest's channel corpus and suggest a combined cutoff.

        Reuses the same scoring path as :meth:`backfill_interest` (ADR-0011
        full-corpus default, batched embeddings) but collects the full combined-
        score distribution instead of filtering at ``interest.threshold``.

        Does not persist anything. Safe to call on a draft interest before
        ``create`` (embedding should already be on the interest object).
        """
        scores, scored_docs, max_combined = await self._collect_corpus_combined_scores(
            interest, since=since
        )
        settings = _load_calibration_settings()
        base = suggest_threshold_from_scores(
            scores,
            strategy=settings["strategy"],
            target_fraction=settings["target_fraction"],
            target_min_matches=settings["target_min_matches"],
            target_max_matches=settings["target_max_matches"],
            min_corpus_size=settings["min_corpus_size"],
            percentile=settings["percentile"],
            min_threshold=settings["min_threshold"],
            default_threshold=settings["default_threshold"],
        )
        return ThresholdCalibration(
            suggested_threshold=base.suggested_threshold,
            scored_docs=scored_docs,
            max_combined=max_combined if scored_docs > 0 else base.max_combined,
            would_match=base.would_match,
            target_matches=base.target_matches,
            confidence=base.confidence,
            strategy=base.strategy,
            fallback_used=base.fallback_used,
            reason=base.reason,
            floor_applied=base.floor_applied,
            pre_floor_threshold=base.pre_floor_threshold,
        )

    async def _resolve_threshold_for_new_interest(
        self,
        draft: WatchInterest,
        explicit_threshold: float | None,
    ) -> tuple[float, ThresholdCalibration | None]:
        """Resolve the threshold for a new interest (ADR 0012).

        Explicit thresholds bypass calibration. When omitted and calibration is
        enabled, runs :meth:`calibrate_threshold` and auto-sets the suggested
        value (operator can override by passing an explicit threshold).
        """
        if explicit_threshold is not None:
            return explicit_threshold, None

        settings = _load_calibration_settings()
        if not settings["enabled"]:
            return settings["default_threshold"], None

        calibration = await self.calibrate_threshold(draft)
        return calibration.suggested_threshold, calibration

    async def _collect_corpus_combined_scores(
        self,
        interest: WatchInterest,
        *,
        since: datetime | None = None,
    ) -> tuple[list[float], int, float]:
        """Score every doc in the interest's channels; return non-excluded combined scores."""
        cutoff = since
        docs_by_ref: dict[str, ProcessedDocument] = {}
        for channel_id in interest.channel_ids:
            channel_docs = await self.processed_doc_repo.list_by_channel(
                channel_id, from_date=cutoff
            )
            for doc in channel_docs:
                docs_by_ref[doc.source_ref] = doc

        if not docs_by_ref:
            return [], 0, 0.0

        stored_embeddings = await self.embedding_repo.get_many_by_source_refs(list(docs_by_ref))
        embeddings_by_ref: dict[str, list[float] | None] = {
            ref: (stored_embeddings[ref].embedding if ref in stored_embeddings else None)
            for ref in docs_by_ref
        }

        scores: list[float] = []
        max_combined = 0.0
        for ref, doc in docs_by_ref.items():
            score = compute_watch_score(
                interest,
                doc,
                embeddings_by_ref.get(ref),
                keyword_weight=self._keyword_weight,
                semantic_weight=self._semantic_weight,
                aggregation=self._keyword_aggregation,
                topk=self._keyword_topk,
            )
            if score.combined > max_combined:
                max_combined = score.combined
            if score.excluded:
                continue
            scores.append(score.combined)

        return scores, len(docs_by_ref), round(max_combined, 4)

    # ---- Internal: embedding helpers ----

    async def _refresh_active_gauge(self) -> None:
        """Refresh ``tg_watchlist_active_interests`` from the interest repo.

        Called once per :meth:`check_interests` tick; ``list_all`` over the
        ingestion DB is cheap (one row per declared interest, bounded by
        operator count). Errors are swallowed so a metrics refresh never
        breaks the scheduler tick.
        """
        try:
            interests = await self.interest_repo.list_all()
        except Exception:
            logger.debug("watchlist.refresh_active_gauge_failed", exc_info=True)
            return
        active_count = sum(1 for i in interests if i.is_active)
        set_watchlist_active(active_count)

    async def aclose(self) -> None:
        """Best-effort close for the underlying embedding client.

        Safe to call when the client is ``None`` or already closed. Used by
        the scheduler hook so the OpenAI ``httpx`` connection is released
        between ticks instead of being leaked.
        """
        if self.embedding_client is None:
            return
        try:
            await self.embedding_client.close()
        except Exception:
            logger.debug("watchlist.embedding_client_close_failed", exc_info=True)

    async def _embed_interest(self, interest: WatchInterest) -> list[float] | None:
        """Compute an embedding for an interest using the canonical text.

        Returns ``None`` if the embedding client is not configured (e.g. tests
        that exercise pure keyword scoring) or if the client raises — caller
        keeps the interest in pure-keyword mode.
        """
        if self.embedding_client is None:
            return None
        text = build_canonical_interest_text(interest)
        try:
            vectors = await self.embedding_client.embed([text])
        except Exception as exc:
            logger.warning(
                "watchlist.embedding_failed",
                interest_id=interest.id,
                error=str(exc),
            )
            return None
        if not vectors:
            return None
        return list(vectors[0])


# ----------------------------------------------------------------------------
# Factory (used by scheduler / MCP / bot / CLI to build a service against the
# live repos + an OpenAI embedding client; tests inject fakes directly via the
# constructor instead of calling this).
# ----------------------------------------------------------------------------


def _load_calibration_settings() -> dict[str, object]:
    """Load ADR-0012 calibration knobs from settings with safe fallbacks."""
    defaults: dict[str, object] = {
        "enabled": True,
        "strategy": "target_fraction",
        "target_fraction": 0.03,
        "target_min_matches": 10,
        "target_max_matches": 150,
        "min_corpus_size": 20,
        "percentile": 97.0,
        "min_threshold": 0.45,
        "default_threshold": _FALLBACK_DEFAULT_THRESHOLD,
    }
    try:
        from tg_parser.config import settings as app_settings

        defaults["enabled"] = app_settings.watchlist_calibration_enabled
        defaults["strategy"] = app_settings.watchlist_calibration_strategy
        defaults["target_fraction"] = app_settings.watchlist_calibration_target_fraction
        defaults["target_min_matches"] = app_settings.watchlist_calibration_target_min_matches
        defaults["target_max_matches"] = app_settings.watchlist_calibration_target_max_matches
        defaults["min_corpus_size"] = app_settings.watchlist_calibration_min_corpus_size
        defaults["percentile"] = app_settings.watchlist_calibration_percentile
        defaults["min_threshold"] = app_settings.watchlist_calibration_min_threshold
        defaults["default_threshold"] = float(app_settings.watchlist_default_threshold)
    except Exception:
        logger.debug("watchlist.calibration_settings_unavailable", exc_info=True)
    return defaults


def _load_batch_max_interests_per_tick() -> int:
    """Flood guard for the F11 P2 batch flush (ADR-0014).

    Returns ``settings.watchlist_batch_max_interests_per_tick`` (the maximum
    number of batch-mode interests processed in a single flush tick) with a safe
    fallback when settings cannot be loaded (e.g. minimal test env). ``<= 0``
    means "no cap".
    """
    try:
        from tg_parser.config import settings as app_settings

        return int(app_settings.watchlist_batch_max_interests_per_tick)
    except Exception:
        logger.debug("watchlist.batch_settings_unavailable", exc_info=True)
        return 500


#: Process-local activation watermark for the instant flush (BUG-095). Set by
#: the bot process when it registers the task; ``None`` everywhere else.
_INSTANT_FLUSH_WATERMARK: datetime | None = None


def set_instant_flush_watermark(at: datetime | None = None) -> datetime:
    """Establish the instant-flush watermark for this process; return it.

    Called once, from the bot process, BEFORE the flush task is scheduled — a
    tick that fired before the watermark existed would either deliver history
    or no-op, and neither is a good first impression of a restored feature.

    An explicit ``watchlist_instant_flush_cutoff`` in settings always wins, so
    an operator can hold one stable watermark across restarts. Without it the
    watermark is "now", which is safe (history is excluded) but moves on every
    restart: matches created while the bot was down fall outside every window
    and are then reported by the undelivered gauge rather than delivered. Pin
    the setting if that window matters.
    """
    global _INSTANT_FLUSH_WATERMARK

    pinned = _load_instant_flush_cutoff()
    _INSTANT_FLUSH_WATERMARK = pinned or at or datetime.now(UTC)
    return _INSTANT_FLUSH_WATERMARK


def get_instant_flush_watermark() -> datetime | None:
    """Return this process's instant-flush watermark, or ``None`` if unset.

    ``None`` means the flush must not run. This is deliberately a hard stop
    rather than a fallback to "everything pending": the selector has no date
    bound, so a missing watermark would mean delivering every match accumulated
    since the outage began. The failure mode is a task that does nothing and
    says so — recoverable — instead of one burst of two-month-old alerts.
    """
    return _load_instant_flush_cutoff() or _INSTANT_FLUSH_WATERMARK


def _load_instant_flush_cutoff() -> datetime | None:
    """Parse ``settings.watchlist_instant_flush_cutoff``; ``None`` when unset/bad.

    A malformed value is logged and ignored rather than raised: it must not
    take the bot process down, and the in-memory watermark below it is already
    safe (it excludes all history).
    """
    try:
        from tg_parser.config import settings as app_settings

        raw = app_settings.watchlist_instant_flush_cutoff
    except Exception:
        logger.debug("watchlist.instant_settings_unavailable", exc_info=True)
        return None

    if not raw or not str(raw).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        logger.warning("watchlist.instant_flush_cutoff_invalid", value=str(raw))
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _load_instant_max_interests_per_tick() -> int:
    """Flood guard for the F11 instant flush (BUG-095).

    Mirrors :func:`_load_batch_max_interests_per_tick`; ``<= 0`` means "no cap".
    """
    try:
        from tg_parser.config import settings as app_settings

        return int(app_settings.watchlist_instant_flush_max_interests_per_tick)
    except Exception:
        logger.debug("watchlist.instant_settings_unavailable", exc_info=True)
        return 500


def make_watchlist_service(
    *,
    interest_repo: WatchInterestRepo,
    match_repo: WatchMatchRepo,
    processed_doc_repo: ProcessedDocumentRepo,
    embedding_repo: EmbeddingRepo,
    workspace_repo: WorkspaceRepo | None = None,
    with_embedding_client: bool = True,
) -> WatchlistService:
    """Construct a :class:`WatchlistService` with an optional embedding client.

    When ``with_embedding_client=True`` (the production default) we lazily
    create an :class:`tg_parser.services.embedding_service.OpenAIEmbeddingClient`
    using global settings. If ``OPENAI_API_KEY`` is missing, the factory falls
    back to keyword-only mode (``embedding_client=None``) instead of raising —
    the watchlist must keep working even on an OpenAI outage.

    ``workspace_repo`` is optional — pass it through when calling
    :meth:`WatchlistService.subscribe` with a non-None ``workspace_id``
    so the ENH-9 validation (Wave 1 step 3) can raise
    :class:`WorkspaceNotFound` for unknown / foreign workspaces.
    """
    embedding_client: EmbeddingClient | None = None
    if with_embedding_client:
        try:
            from tg_parser.services.embedding_service import create_embedding_client

            embedding_client = create_embedding_client()
        except Exception as exc:
            logger.warning(
                "watchlist.embedding_client_unavailable",
                error=str(exc),
            )
            embedding_client = None

    keyword_weight = KEYWORD_WEIGHT
    semantic_weight = SEMANTIC_WEIGHT
    keyword_aggregation = KEYWORD_AGGREGATION_DEFAULT
    keyword_topk = KEYWORD_TOPK_DEFAULT
    try:
        from tg_parser.config import settings as app_settings

        keyword_weight = app_settings.watchlist_keyword_weight
        semantic_weight = app_settings.watchlist_semantic_weight
        keyword_aggregation = app_settings.watchlist_keyword_aggregation
        keyword_topk = app_settings.watchlist_keyword_topk
    except Exception:
        # Settings unavailable (e.g. minimal test env) — keep module defaults.
        logger.debug("watchlist.weights_settings_unavailable", exc_info=True)

    return WatchlistService(
        interest_repo=interest_repo,
        match_repo=match_repo,
        processed_doc_repo=processed_doc_repo,
        embedding_repo=embedding_repo,
        embedding_client=embedding_client,
        workspace_repo=workspace_repo,
        keyword_weight=keyword_weight,
        semantic_weight=semantic_weight,
        keyword_aggregation=keyword_aggregation,
        keyword_topk=keyword_topk,
    )
