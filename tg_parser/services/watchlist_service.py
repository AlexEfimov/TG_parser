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

#: Minimum token length used by :func:`_tokenize`. Mirrors the topicization
#: tokenizer (``MIN_TOKEN_LENGTH = 2``) so short medical/regulatory abbreviations
#: such as "MiCA", "ETF", "ЦБ" are not dropped.
MIN_TOKEN_LENGTH: int = 2

#: Hard cap on the number of new documents scored in a single tick. Protects
#: the scheduler from a back-filled channel producing thousands of new
#: ``new_doc_refs`` at once (notification flood / OpenAI rate-limit risk).
MAX_DOCS_PER_TICK: int = 100

#: Hard cap on the number of historical documents scored by a single
#: :meth:`WatchlistService.backfill_interest` run (DIAG 2026-06-07 B2 fix).
#: A backfill walks every ``processed_documents`` row for the interest's
#: channels since the cutoff, so this bounds the cost of one operator-triggered
#: rescoring pass. Callers may pass a smaller ``limit``; values above the cap
#: are clamped. The newest documents (by ``processed_at``) are scored first.
MAX_BACKFILL_DOCS: int = 2000

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
class SubscribeResult:
    """Outcome of a :meth:`WatchlistService.subscribe` call.

    Wave 1 step 3 / BUG-022: returned by the service-layer upsert so
    every surface (MCP, Bot, CLI, HTTP) can render the locked
    ``{watchlist_id, created, changed_fields}`` shape without
    duplicating the diff logic. ``changed_fields`` is a list of
    Pydantic field names that differ between the stored row and the
    payload (empty on a true no-op replay, populated on
    same-key/different-args).
    """

    interest: WatchInterest
    created: bool
    changed_fields: list[str]


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
    """

    keyword: float
    semantic: float
    combined: float
    excluded: bool
    semantic_available: bool


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
    """
    if threshold is not None:
        return threshold
    try:
        from tg_parser.config import settings as app_settings

        return float(app_settings.watchlist_default_threshold)
    except Exception:
        return _FALLBACK_DEFAULT_THRESHOLD


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


def _keyword_score(interest_keywords: list[str], doc_tokens: set[str]) -> float:
    """Phrase-level recall: fraction of keyword *phrases* present in the doc.

    Each keyword is treated as an atomic phrase that counts as a hit only when
    **every** token it tokenises into appears in ``doc_tokens``. Score is
    ``matched_phrases / total_phrases``.

    DIAG 2026-06-07 fix: the previous implementation tokenised every keyword
    and unioned the tokens into a single set, so a multi-word keyword such as
    ``"агонисты дофамина"`` contributed two tokens to the denominator and a
    partial overlap (only one of the two tokens present) silently depressed the
    keyword component below where the operator expected it. Treating each
    keyword as a phrase keeps the denominator equal to the number of keywords
    the user actually named. Single-token keywords behave identically to the
    old token-set overlap, so existing thresholds are preserved.
    """
    phrases = [tokens for tokens in (_tokenize(kw) for kw in interest_keywords) if tokens]
    if not phrases:
        return 0.0
    matched = sum(1 for phrase in phrases if phrase <= doc_tokens)
    return matched / len(phrases)


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
) -> WatchScore:
    """Score a single ``(interest, document)`` pair.

    Returns a :class:`WatchScore` with the full breakdown. The caller compares
    ``score.combined >= interest.threshold`` to decide whether to materialise
    a :class:`WatchMatch`.

    ``keyword_weight`` / ``semantic_weight`` default to the module constants but
    can be overridden (the service injects values from settings) so operators
    can rebalance the hybrid mix without a code change when the embedding model
    under-scores the corpus language.
    """
    doc_tokens = _build_doc_tokens(doc)

    exclude_tokens: set[str] = set()
    for kw in interest.exclude_keywords:
        exclude_tokens |= _tokenize(kw)
    excluded = bool(exclude_tokens & doc_tokens)

    keyword = _keyword_score(interest.keywords, doc_tokens)

    semantic_available = bool(interest.embedding) and bool(doc_embedding)
    semantic = _cosine(interest.embedding or [], doc_embedding or []) if semantic_available else 0.0

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
    ) -> None:
        self.interest_repo = interest_repo
        self.match_repo = match_repo
        self.processed_doc_repo = processed_doc_repo
        self.embedding_repo = embedding_repo
        self.embedding_client = embedding_client
        self.workspace_repo = workspace_repo
        self._keyword_weight = keyword_weight
        self._semantic_weight = semantic_weight

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
            threshold=_resolve_default_threshold(threshold),
            notify_mode=notify_mode,
            is_active=True,
            embedding=None,
        )
        stored = await self.interest_repo.create(draft)

        embedding = await self._embed_interest(stored)
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
        threshold = _resolve_default_threshold(threshold)
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
            threshold=threshold,
            notify_mode=notify_mode,
            is_active=True,
            embedding=None,
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

        embedding = await self._embed_interest(stored)
        if embedding is not None:
            await self.interest_repo.update_embedding(stored.id, embedding)
            stored = stored.model_copy(update={"embedding": embedding})

        return SubscribeResult(interest=stored, created=True, changed_fields=[])

    async def _apply_upsert(
        self,
        *,
        existing: WatchInterest,
        target_storage: dict[str, object],
        description: str | None,
        keywords: list[str] | None,
        exclude_keywords: list[str] | None,
        channel_ids: list[str],
        threshold: float,
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
        if abs(existing.threshold - threshold) > 1e-9:
            update_kwargs["threshold"] = threshold
            changed_fields.append("threshold")
        if existing.notify_mode != notify_mode:
            update_kwargs["notify_mode"] = notify_mode
            changed_fields.append("notify_mode")
        if not existing.is_active:
            update_kwargs["is_active"] = True
            changed_fields.append("is_active")
        if workspace_id is not None and existing.workspace_id != workspace_id:
            update_kwargs["workspace_id"] = workspace_id
            changed_fields.append("workspace_id")

        if not update_kwargs:
            return SubscribeResult(interest=existing, created=False, changed_fields=[])

        updated = await self.interest_repo.update_subscribe_fields(existing.id, **update_kwargs)
        if updated is None:
            updated = existing
        return SubscribeResult(interest=updated, created=False, changed_fields=changed_fields)

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
        deleted = await self.interest_repo.soft_delete(interest_id)
        if not deleted:
            return False, "delete failed (already inactive?)"
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

        embeddings_by_ref: dict[str, list[float] | None] = {}
        for ref in docs_by_ref:
            stored = await self.embedding_repo.get_by_source_ref(ref)
            embeddings_by_ref[ref] = stored.embedding if stored else None

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
                all_candidates.append(
                    WatchMatch(
                        id=0,
                        interest_id=interest.id,
                        source_ref=ref,
                        channel_id=doc.channel_id,
                        keyword_score=score.keyword,
                        semantic_score=score.semantic,
                        combined_score=score.combined,
                        notified=False,
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

        if bot is not None and inserted:
            try:
                await self.notify(inserted, bot, docs_by_ref=docs_by_ref)
            except Exception as exc:
                logger.exception(
                    "watchlist.notify_failed",
                    channel_id=channel_id,
                    inserted=len(inserted),
                    error=str(exc),
                )

        return inserted

    # ---- Retroactive backfill (DIAG 2026-06-07 hypothesis B2) ----

    async def backfill_interest(
        self,
        interest_id: str,
        *,
        since: datetime | None = None,
        limit: int = MAX_BACKFILL_DOCS,
        dry_run: bool = True,
        bot: Bot | None = None,
    ) -> BackfillResult:
        """Score historical ``processed_documents`` against one interest.

        Closes the retroactive gap (B2): the scheduler only scores per-tick
        ``new_doc_refs``, so a corpus ingested *before* an interest was created
        is never evaluated. This walks every watched channel's documents since
        ``since`` (defaults to ``interest.created_at``), scores them, and — when
        ``dry_run`` is False — persists matches via the same idempotent
        ``upsert_many`` path the scheduler uses.

        Safety:

        - ``dry_run=True`` (default) performs scoring only: no ``watch_matches``
          rows, no ``last_*_at`` writes, no notifications. The returned
          ``would_match`` / ``max_combined`` let an operator preview the impact
          before committing.
        - The newest ``limit`` documents (by ``processed_at``) are scored; the
          cap is clamped to :data:`MAX_BACKFILL_DOCS`.
        - Idempotent on re-run via ``UNIQUE (interest_id, source_ref)``.
        - Notifications collapse to one grouped push per interest (see
          :meth:`notify`), so a large backfill never floods the chat.
        """
        effective_limit = max(1, min(limit, MAX_BACKFILL_DOCS))

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

        cutoff = since or interest.created_at

        docs_by_ref: dict[str, ProcessedDocument] = {}
        for channel_id in interest.channel_ids:
            channel_docs = await self.processed_doc_repo.list_by_channel(
                channel_id, from_date=cutoff
            )
            for doc in channel_docs:
                docs_by_ref[doc.source_ref] = doc

        ordered = sorted(docs_by_ref.values(), key=lambda d: d.processed_at, reverse=True)
        ordered = ordered[:effective_limit]
        scored_docs = {doc.source_ref: doc for doc in ordered}

        embeddings_by_ref: dict[str, list[float] | None] = {}
        for ref in scored_docs:
            stored = await self.embedding_repo.get_by_source_ref(ref)
            embeddings_by_ref[ref] = stored.embedding if stored else None

        candidates: list[WatchMatch] = []
        max_combined = 0.0
        for ref, doc in scored_docs.items():
            score = compute_watch_score(
                interest,
                doc,
                embeddings_by_ref.get(ref),
                keyword_weight=self._keyword_weight,
                semantic_weight=self._semantic_weight,
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
                    notified=False,
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

        if bot is not None and inserted:
            try:
                await self.notify(inserted, bot, docs_by_ref=scored_docs)
            except Exception as exc:
                logger.exception(
                    "watchlist.backfill_notify_failed",
                    interest_id=interest.id,
                    inserted=len(inserted),
                    error=str(exc),
                )

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
        from aiogram.enums import ParseMode

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

            text = compose_match_notification(interest, group_matches, docs_by_ref)
            try:
                await bot.send_message(
                    chat_id=interest.chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception as exc:
                error_text = str(exc).lower()
                permanent = any(
                    fragment in error_text for fragment in _BOT_PERMANENT_FAILURE_FRAGMENTS
                )
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
                outcomes[interest_id] = "send_failed"
                continue

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
            outcomes[interest_id] = "sent"

        return outcomes

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
    try:
        from tg_parser.config import settings as app_settings

        keyword_weight = app_settings.watchlist_keyword_weight
        semantic_weight = app_settings.watchlist_semantic_weight
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
    )
