"""
Topicization pipeline implementation.

Реализует TopicizationPipeline: кластеризация ProcessedDocument → TopicCard + TopicBundle.
Требования: TR-27..TR-37, TR-IF-4 (детерминизм anchors).
"""

import asyncio
import contextlib
import json
import re
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.config import settings
from tg_parser.domain.ids import make_topic_id
from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicAssignment,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.llm.errors import AnthropicBillingError, LLMCallTimeoutError
from tg_parser.processing.pipeline import (
    apply_json_retry_hint,
    extract_json_from_response,
    repair_json,
)
from tg_parser.processing.ports import LLMClient, TopicizationPipeline
from tg_parser.processing.prompt_loader import get_prompt_loader
from tg_parser.processing.topicization_checkpoint import (
    FULL_CHECKPOINT_ERROR_CLASS,
    FullCheckpointReadError,
    FullRunCheckpoint,
    full_checkpoint_marker_ref,
    noprogress_circuit_open,
    parse_checkpoint,
    planned_ref_hash,
    planned_refs_from_documents,
)
from tg_parser.processing.topicization_prompts import (
    INCREMENTAL_DISCOVER_SYSTEM_PROMPT,
    TOPICIZATION_SYSTEM_PROMPT,
    build_incremental_discover_prompt,
    build_topicization_prompt,
    get_incremental_discover_prompt_name,
    get_supporting_items_prompt_name,
    get_topicization_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, TopicBundleRepo, TopicCardRepo

logger = structlog.get_logger(__name__)

# BUG-071 (Fix 1): hard ceiling when auto-scaling ``max_tokens`` after a
# ``max_tokens`` truncation. Without a cap the scale-up loop could chase an
# ever-larger (and ever more expensive) output budget; 32768 is 4x the
# topicization default (8192) and 2x the merge default (16384) — past this we
# stop scaling and fall back to the loop's existing failure contract.
_TRUNCATION_MAX_TOKENS_CAP = 32768

# BUG-074 (F2): large-prompt topicization stages re-issue the ENTIRE prompt up
# to ``max_json_retries`` times on an HTTP-200 invalid-JSON reply (the BUG-065
# class: unescaped inner quotes / trailing commas), re-burning the full batch
# without ever attempting the cheap deterministic ``repair_json`` the per-message
# path already uses (``pipeline.py``). Lowered from 3 → 2 because the repair pass
# now handles the dominant invalid-JSON case on the FIRST attempt, so at most one
# corrective re-issue is warranted before giving up. (Truncation —
# ``stop_reason == "max_tokens"`` — is handled separately and is unaffected.)
_TOPICIZATION_MAX_JSON_RETRIES = 2


def _loads_topicization_json_with_repair(cleaned: str, *, stage: str) -> dict:
    """Parse LLM JSON, applying :func:`repair_json` BEFORE counting a parse fail.

    BUG-074 (F2): mirrors the per-message path in ``pipeline.py`` — a provider-
    agnostic, dependency-free repair pass (escape unescaped inner quotes + strip
    trailing commas) is attempted the moment ``json.loads`` raises, and only if
    the REPAIRED text also fails to parse does the :class:`json.JSONDecodeError`
    propagate to the caller's retry/fallback handler. This recovers the common
    unescaped-quote reply on the FIRST attempt instead of re-issuing the whole
    large prompt up to ``max_json_retries`` times.
    """
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = repair_json(cleaned)
        if repaired != cleaned:
            result = json.loads(repaired)  # may raise → caller handles as before
            logger.info("recovered_topicization_json_via_repair", stage=stage)
            return result
        raise


class TopicizationBatchTruncatedError(Exception):
    """BUG-071 (Bugbot follow-up): a generation batch was abandoned because every
    request in the shrink/scale ladder hit the ``max_tokens`` output cap.

    Raised by :meth:`_generate_topics_batch_after_truncation` when a batch yields
    NOTHING after splitting/scaling. It is surfaced (not swallowed as an empty
    list) so ``topicize_channel`` counts it as a failed batch exactly like a
    raised-exception batch — otherwise a channel-wide run that truncation-drops
    most batches would finish with ``failed_batches == 0`` and regress BUG-018's
    systemic-fail exit-code-2 semantics into the misleading "insufficient data"
    hint. Deliberately a direct ``Exception`` subclass (NOT ``RuntimeError``) so
    it is neither wrapped by ``_generate_topics_batch``'s ``except (RuntimeError,
    ValueError, OSError)`` clause nor confused with a genuine LLM error.
    """

    def __init__(self, candidate_count: int) -> None:
        self.candidate_count = candidate_count
        super().__init__(
            f"topicization batch of {candidate_count} candidate(s) dropped after "
            "exhausting the max_tokens shrink/scale ladder (reply truncated at the "
            "output cap on every attempt)"
        )


def _scaled_max_tokens(current: int) -> int | None:
    """Return the next (doubled, capped) ``max_tokens`` budget, or ``None`` at the cap.

    BUG-071 (Fix 1): used to grow the output budget once when a request is
    truncated and cannot be split further (a single oversized item). ``None``
    signals "already at the cap — stop scaling" so the caller falls back.
    """
    if current >= _TRUNCATION_MAX_TOKENS_CAP:
        return None
    return min(current * 2, _TRUNCATION_MAX_TOKENS_CAP)


def _coerce_merge_member_id(member_id: object) -> int | None:
    """Coerce one merge-LLM member ID, skipping malformed values."""
    if isinstance(member_id, bool):
        return None
    if isinstance(member_id, int):
        return member_id
    if not isinstance(member_id, str):
        return None
    try:
        return int(member_id)
    except (ValueError, OverflowError):
        return None


# Quality criteria (TR-35) — wired from settings (Session 33)
MIN_SINGLETON_SCORE = settings.topicization_singleton_min_score
MIN_SINGLETON_LENGTH = settings.topicization_singleton_min_len
MIN_CLUSTER_ANCHORS = 2
MIN_CLUSTER_SCORE = settings.topicization_cluster_min_anchor_score
MIN_SUPPORTING_SCORE = settings.topicization_supporting_min_score
MAX_SUPPORTING_ITEMS = settings.topicization_max_supporting_items
MAX_ANCHORS_PER_CLUSTER = settings.topicization_top_n_anchors
MIN_TOKEN_LENGTH = settings.topicization_min_token_length
TEXT_CLEAN_MATCH_CHARS = settings.topicization_text_clean_match_chars
ASSIGN_KEYWORD_AGGREGATION = settings.topicization_assign_keyword_aggregation
ASSIGN_KEYWORD_TOPK = settings.topicization_assign_keyword_topk


def _aggregate_assign_score(
    weighted_hits: float,
    n: int,
    *,
    aggregation: str = ASSIGN_KEYWORD_AGGREGATION,
    topk: int = ASSIGN_KEYWORD_TOPK,
) -> float:
    """Aggregate weighted token hits into an assign score.

    Schemes (S5 / F-10); ``n = len(topic_keywords)``:

    - ``"mean"``: ``weighted_hits / n`` — the original recall fraction.
      Rich ``scope_in`` vocabularies dilute on-topic docs (the denominator
      penalty that pushes them toward LLM discover).
    - ``"topk_denom"`` (default): ``weighted_hits / min(n, K)`` — caps the
      denominator at ``K`` so keywords beyond the top ``K`` add no penalty.
      **Not** the watchlist ADR-0010 ``"topk"`` scheme
      (``min(hits, k) / k`` caps the numerator). For ``n <= K`` this is
      **byte-identical** to ``"mean"``.

    ``n == 0`` → ``0.0`` for every scheme.
    """
    if n <= 0:
        return 0.0
    if aggregation == "mean":
        return weighted_hits / n
    if aggregation == "topk_denom":
        denom = min(n, topk)
        if denom <= 0:
            return 0.0
        return weighted_hits / denom
    raise ValueError(
        f"unknown topicization assign keyword aggregation: {aggregation!r}; "
        "expected 'mean' or 'topk_denom'"
    )


class TopicizationPipelineImpl(TopicizationPipeline):
    """
    Реализация pipeline тематизации.

    Требования:
    - TR-27..TR-37: формирование TopicCard и TopicBundle
    - TR-IF-4: детерminизм anchors (sort by score desc, anchor_ref asc)
    - TR-35: критерии качества тем
    - TR-32: детерминизм тематизации
    """

    def __init__(
        self,
        llm_client: LLMClient | None,
        processed_doc_repo: ProcessedDocumentRepo,
        topic_card_repo: TopicCardRepo,
        topic_bundle_repo: TopicBundleRepo,
        pipeline_version: str | None = None,
        model_id: str | None = None,
        batch_concurrency: int = 5,
        batch_size: int = 50,
        processing_failure_repo=None,
    ):
        """
        Args:
            llm_client: LLM клиент для тематизации
            processed_doc_repo: Репозиторий processed документов
            topic_card_repo: Репозиторий topic cards
            topic_bundle_repo: Репозиторий topic bundles
            pipeline_version: Версия pipeline (default: "v1.0")
            model_id: Идентификатор модели (default из OpenAI client)
            batch_concurrency: Max concurrent LLM batches in topicize_channel
            batch_size: Max docs per LLM batch in the full topicize_channel path
        """
        self.llm_client = llm_client
        self.processed_doc_repo = processed_doc_repo
        self.topic_card_repo = topic_card_repo
        self.topic_bundle_repo = topic_bundle_repo
        # BUG-076: repo hosting the synthetic resumable-run checkpoint row. When
        # provided AND it shares the same session as ``topic_card_repo`` /
        # ``topic_bundle_repo`` (production path), the per-chunk card + bundle
        # upserts co-commit atomically with the checkpoint advance. Optional so
        # legacy / unit callers (and the incremental path) are unaffected.
        self.processing_failure_repo = processing_failure_repo
        self._db_lock = asyncio.Lock()
        self.pipeline_version = pipeline_version or "v1.0"
        self.batch_concurrency = batch_concurrency
        self.batch_size = batch_size

        # BUG-076: resumable full-run status (reset per ``topicize_channel``).
        # ``full_run_active`` tells the service wrapper the chunked path ran, so
        # it SKIPS its own per-card ``record_topic_created`` emit (per-chunk emit
        # already fired — no double-count) and its post-hoc bundle build (the
        # chunked path builds bundles inside the atomic commit).
        self.full_run_active: bool = False
        self.full_run_chunks_total: int = 0
        self.full_run_chunks_done: int = 0
        self.full_run_halted: bool = False
        self.full_run_all_chunks_done: bool = False
        # BUG-077 (F3, Bugbot round-3 MEDIUM follow-up): True iff THIS
        # invocation hit the F3 checkpoint-READ-error abort — a ZERO-cost,
        # ZERO-chunks-attempted internal no-op (see ``_topicize_channel_chunked``
        # below), distinct from a genuine chunk-generation no-progress halt.
        # The service driver reads this back (forwarded through the
        # ``run_topicization`` summary dict) so it does NOT mistake a
        # transient checkpoint-read blip for a costly stalled resume and
        # pollute the F1 breaker with a cost-free event.
        self.full_run_checkpoint_read_aborted: bool = False

        # Token usage accumulators
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # BUG-018: batch failure tracking — surfaced via run_topicization stats
        # so the CLI can exit non-zero on systemic LLM-batch failures (e.g.
        # billing / auth / quota class errors that swallow every batch).
        self.total_batches: int = 0
        self.failed_batches: int = 0
        self.last_batch_error: str | None = None

        # BUG-023: aggregate per-reason rejection counter — populated by
        # ``_build_topic_card`` so the CLI summary can show
        # «Quality filter rejected X topics: 4 by min_items, 2 by ...»
        # instead of leaving operators with a silent run.
        self.rejection_breakdown: dict[str, int] = {}

        if model_id:
            self.model_id = model_id
        elif hasattr(llm_client, "model"):
            self.model_id = llm_client.model
        else:
            self.model_id = "unknown"

        # Вычисляем prompt_id (TR-40)
        topic_config = get_prompt_loader().load("topicization")
        _system = topic_config.get("system", {}).get("prompt") or TOPICIZATION_SYSTEM_PROMPT
        if hasattr(llm_client, "compute_prompt_id"):
            self.prompt_id = llm_client.compute_prompt_id(
                _system,
                build_topicization_prompt(
                    [
                        {
                            "source_ref": "tg:ch:post:1",
                            "text_clean": "test",
                            "summary": "test",
                            "topics": [],
                        }
                    ]
                ),
            )
        else:
            self.prompt_id = "unknown"

        self.prompt_name = get_topicization_prompt_name()
        self.supporting_prompt_name = get_supporting_items_prompt_name()

    async def topicize_channel(
        self,
        channel_id: str,
        force: bool = False,
        resume: bool = False,
    ) -> list[TopicCard]:
        """
        Сформировать темы для канала.

        TR-30: все ProcessedDocument канала используются для тематизации.
        TR-32: детерминизм (при одинаковых входных данных результат стабилен).

        Алгоритм (docs/pipeline.md строки 114-163):
        1. Подготовка корпуса - все ProcessedDocument канала
        2. Выбор кандидатов в якоря
        3. Генерация тем через LLM
        4. Нормализация и детерминизация anchors (TR-IF-4)
        5. Применение критериев качества (TR-35)
        6. Сохранение TopicCard в репозиторий
        """
        logger.info("Starting topicization for channel_id=%s, force=%s", channel_id, force)

        # BUG-018 / BUG-023: reset per-invocation counters so multiple runs
        # on the same pipeline instance don't leak state across channels.
        self.total_batches = 0
        self.failed_batches = 0
        self.last_batch_error = None
        self.rejection_breakdown = {}
        # BUG-076: reset resumable full-run status per invocation.
        self.full_run_active = False
        self.full_run_chunks_total = 0
        self.full_run_chunks_done = 0
        self.full_run_halted = False
        self.full_run_all_chunks_done = False
        self.full_run_checkpoint_read_aborted = False

        if force:
            deleted_bundles = await self.topic_bundle_repo.delete_by_channel(channel_id)
            deleted_cards = await self.topic_card_repo.delete_by_channel(channel_id)
            logger.info(
                "Force mode: deleted %d old topic cards and %d bundles for channel_id=%s",
                deleted_cards,
                deleted_bundles,
                channel_id,
            )

        # Step 1: Подготовка корпуса (TR-30)
        documents = await self.processed_doc_repo.list_by_channel(channel_id)

        if not documents:
            logger.warning("No processed documents found for channel_id=%s", channel_id)
            return []

        logger.info("Found %d processed documents for channel_id=%s", len(documents), channel_id)

        # Step 2: Выбор кандидатов в якоря
        candidates = [
            {
                "source_ref": doc.source_ref,
                "text_clean": doc.text_clean,
                "summary": doc.summary,
                "topics": doc.topics or [],
                "channel_id": doc.channel_id,
                "message_id": doc.source_message_id,
            }
            for doc in documents
        ]

        # BUG-076: crash-safe / resumable / budget-aware chunked full run.
        # Gated behind the master switch AND the presence of a checkpoint repo
        # (so the atomic co-commit can persist the checkpoint). When either is
        # absent this branch is skipped and the legacy monolithic path below
        # runs byte-for-byte unchanged.
        if settings.topicization_full_resume_enabled and self.processing_failure_repo is not None:
            return await self._topicize_channel_chunked(
                channel_id=channel_id,
                documents=documents,
                force=force,
                resume=resume,
            )

        # Step 3: Генерация тем через LLM (параллельный батчинг)
        BATCH_SIZE = self.batch_size
        batch_concurrency = self.batch_concurrency
        raw_topics = []

        if len(candidates) <= BATCH_SIZE:
            self.total_batches = 1
            try:
                raw_topics = await self._generate_topics_batch(candidates)
            except TopicizationBatchTruncatedError as e:
                # BUG-071 (Bugbot follow-up / BUG-018): a single-batch
                # truncation-drop is NOT a crash — record it as a failed batch
                # and continue with 0 topics. With failed_batches=1 /
                # total_batches=1 the CLI sees a 100% fail ratio and exits 2
                # (systemic fail), instead of the misleading "insufficient
                # data" hint that an empty list + failed_batches=0 would give.
                self.failed_batches = 1
                self.last_batch_error = f"{type(e).__name__}: {e}"
                self._record_failed_batch("topicization_generate", channel_id)
                logger.error("Single batch dropped at the max_tokens cap (truncation): %s", e)
                raw_topics = []
            except Exception as e:
                # BUG-018: in the single-batch path other exceptions still
                # propagate to the CLI (which exits 1); we record the
                # failure so callers/tests can introspect the state.
                self.failed_batches = 1
                self.last_batch_error = f"{type(e).__name__}: {e}"
                self._record_failed_batch("topicization_generate", channel_id)
                raise
        else:
            batches = [
                candidates[i : i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)
            ]
            self.total_batches = len(batches)
            logger.info(
                "Large channel (%d docs), %d batches of %d (concurrency=%d)",
                len(candidates),
                len(batches),
                BATCH_SIZE,
                batch_concurrency,
            )

            semaphore = asyncio.Semaphore(batch_concurrency)

            async def _gen_batch(idx: int, batch: list[dict]) -> list[dict]:
                async with semaphore:
                    logger.info(
                        "Processing batch %d/%d (%d candidates)", idx + 1, len(batches), len(batch)
                    )
                    topics = await self._generate_topics_batch(batch)
                    logger.info(
                        "Batch %d/%d generated %d topics", idx + 1, len(batches), len(topics)
                    )
                    return topics

            batch_results = await asyncio.gather(
                *(_gen_batch(i, b) for i, b in enumerate(batches)),
                return_exceptions=True,
            )

            all_batch_topics = []
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    # BUG-018: count systemic-fail batches so the caller can
                    # distinguish «0 topics, no data» from «0 topics, all
                    # batches errored» and exit non-zero accordingly.
                    self.failed_batches += 1
                    self._record_failed_batch("topicization_generate", channel_id)
                    if self.last_batch_error is None:
                        self.last_batch_error = f"{type(result).__name__}: {result}"
                    logger.error("Batch %d/%d failed: %s", i + 1, len(batches), result)
                else:
                    all_batch_topics.extend(result)

            if all_batch_topics:
                raw_topics = await self._merge_topics(all_batch_topics, candidates)
                logger.info(
                    "Merged %d batch topics into %d final topics",
                    len(all_batch_topics),
                    len(raw_topics),
                )

        # Step 4 & 5: Нормализация, детерминизация и применение критериев качества
        topic_cards = []

        for raw_topic in raw_topics:
            try:
                topic_card = self._build_topic_card(
                    raw_topic=raw_topic,
                    channel_id=channel_id,
                    documents=documents,
                )

                if topic_card:
                    topic_cards.append(topic_card)

            except (ValueError, KeyError, AttributeError) as e:
                logger.error("Failed to build topic card from raw_topic: %s", e, exc_info=True)
                continue

        logger.info(
            "topicization_complete",
            topic_cards=len(topic_cards),
            channel_id=channel_id,
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            total_tokens=self.total_input_tokens + self.total_output_tokens,
        )

        # Step 6: Сохранение TopicCard
        for card in topic_cards:
            try:
                await self.topic_card_repo.upsert(card)
                logger.info("Saved topic card: %s", card.id)
            except SQLAlchemyError as e:
                logger.error("Failed to save topic card %s: %s", card.id, e, exc_info=True)

        # BUG-077 (F7): a COMPLETED legacy monolithic run (>=1 card built)
        # supersedes any leftover resumable checkpoint from a prior enabled
        # period — clear the marker so a future flag re-enable cannot resume a
        # stale plan on top of this run's result (re-spend / duplicate cards /
        # stale-restart wipe of good legacy cards). Best-effort + dark-safe:
        # only the synthetic BUG-076 marker row is touched, and only after a
        # successful full run; a 0-card run leaves the marker for a future
        # resume. No-op when no failure repo is bound.
        if topic_cards and self.processing_failure_repo is not None:
            await self._delete_full_checkpoint(channel_id)

        return topic_cards

    # ------------------------------------------------------------------
    # BUG-076: chunked / resumable / budget-aware full topicization
    # ------------------------------------------------------------------

    async def _read_full_checkpoint(self, channel_id: str) -> FullRunCheckpoint | None:
        """Read the synthetic full-run checkpoint row (BUG-076).

        BUG-077 (F3): a TRANSPORT error (DB down / transient read failure) is
        no longer swallowed to ``None`` — that used to be indistinguishable
        from "no checkpoint" and made the caller start a FRESH pinned run
        (re-burning chunk 0+, overwriting the real checkpoint and minting
        duplicate cards). It now raises :class:`FullCheckpointReadError` so the
        caller aborts the invocation at 0 token cost and retries next tick. A
        present-but-malformed row still degrades to ``None`` inside
        ``parse_checkpoint`` (that genuinely IS "no usable checkpoint").
        """
        if self.processing_failure_repo is None:
            return None
        ref = full_checkpoint_marker_ref(channel_id)
        try:
            for f in await self.processing_failure_repo.list_failures(channel_id=channel_id):
                if f.get("source_ref") == ref:
                    return parse_checkpoint(f)
        except Exception as e:
            logger.warning("full_checkpoint_read_failed channel=%s: %s", channel_id, e)
            raise FullCheckpointReadError(str(e)) from e
        return None

    async def _record_noprogress_resume(
        self,
        channel_id: str,
        *,
        run_id: str,
        planned_refs: list[str],
        planned_ref_hash_value: str,
        planned_doc_count: int,
        chunk_batches: int,
        chunks_total: int,
        chunks_done: int,
        batches_done: int,
        tokens_spent_before: int,
        last_chunk_at: str | None,
        consecutive_noprogress_resumes: int,
        cards_stamped: bool,
    ) -> None:
        """BUG-077 (F1, Bugbot HIGH follow-up) — the F1 no-progress counter's
        SOLE writer, executed HERE inside the chunked pipeline itself.

        This is the single choke point BOTH callers of a resumable full-run
        attempt funnel through: the ``should_reescalate`` escalation branch
        (a direct ``run_topicization`` call, gated only by ``force=False``)
        AND the scheduler's ``run_full_topicization_resume_for_channel``
        driver. The original implementation wrote this counter ONLY from the
        driver's post-invocation bookkeeping — so an escalation-triggered
        attempt that failed without advancing left the checkpoint row
        untouched, and the driver's SAME-TICK pre-invocation breaker check
        (reading the same still-unincremented row) would fire a SECOND
        independent chunked attempt, doubling generate+merge spend per probe
        window. Writing the increment here means the FIRST caller (whichever
        it is) to attempt-and-fail closes the breaker before the SECOND
        caller even reads the checkpoint — at most one probe attempt per
        cooldown window, regardless of which entry point fires first.

        The driver's own post-invocation logic (``run_full_topicization_
        resume_for_channel``) detects that this write already happened (the
        post-read counter differs from its pre-read snapshot) and skips its
        own increment — so a driver-triggered failure is still counted
        exactly once, not twice.

        Best-effort: a failed write must never crash the halt path (worst
        case: one extra probe next tick).
        """
        if self.processing_failure_repo is None:
            return
        updated = FullRunCheckpoint(
            run_id=run_id,
            planned_refs=planned_refs,
            planned_ref_hash=planned_ref_hash_value,
            planned_doc_count=planned_doc_count,
            chunk_batches=chunk_batches,
            chunks_total=chunks_total,
            chunks_done=chunks_done,
            batches_done=batches_done,
            tokens_spent_cumulative=tokens_spent_before
            + self.total_input_tokens
            + self.total_output_tokens,
            final_merge_done=False,
            last_chunk_at=last_chunk_at,
            consecutive_noprogress_resumes=consecutive_noprogress_resumes + 1,
            last_noprogress_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            cards_stamped=cards_stamped,
        )
        try:
            await self.processing_failure_repo.record_failure(
                source_ref=full_checkpoint_marker_ref(channel_id),
                channel_id=channel_id,
                attempts=updated.chunks_done,
                error_class=FULL_CHECKPOINT_ERROR_CLASS,
                error_message="topicization full-run checkpoint",
                error_details=updated.to_details(),
            )
        except Exception as e:  # noqa: BLE001 — best-effort counter write
            logger.warning(
                "full_run_noprogress_counter_write_failed channel=%s: %s",
                channel_id,
                e,
            )

    async def _delete_full_checkpoint(self, channel_id: str) -> None:
        """Best-effort clear of the checkpoint row on full completion / stale restart."""
        if self.processing_failure_repo is None:
            return
        try:
            await self.processing_failure_repo.delete_failure(
                full_checkpoint_marker_ref(channel_id)
            )
        except Exception as e:  # noqa: BLE001 — best-effort clear
            logger.debug("full_checkpoint_clear_failed channel=%s: %s", channel_id, e)

    async def _generate_chunk(
        self, channel_id: str, chunk_batches: list[list[dict]]
    ) -> tuple[list[dict], int]:
        """Generate one chunk's batches concurrently (BUG-076).

        Reuses the unchanged BUG-071 per-batch generate (shrink/split/scale) via
        ``asyncio.gather(return_exceptions=True)`` under the same concurrency
        semaphore. A per-batch exception is counted as a failed batch (NOT a
        crash) exactly like the monolithic path. Returns
        ``(chunk_topics, failed_batches_in_chunk)``.
        """
        semaphore = asyncio.Semaphore(self.batch_concurrency)

        async def _gen(idx: int, batch: list[dict]) -> list[dict]:
            async with semaphore:
                return await self._generate_topics_batch(batch)

        results = await asyncio.gather(
            *(_gen(i, b) for i, b in enumerate(chunk_batches)),
            return_exceptions=True,
        )
        chunk_topics: list[dict] = []
        failed = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed += 1
                self.failed_batches += 1
                self._record_failed_batch("topicization_generate", channel_id)
                if self.last_batch_error is None:
                    self.last_batch_error = f"{type(result).__name__}: {result}"
                logger.error("full_run chunk batch %d failed: %s", i + 1, result)
            else:
                chunk_topics.extend(result)
        return chunk_topics, failed

    async def _commit_chunk_atomically(
        self,
        *,
        channel_id: str,
        cards: list[TopicCard],
        documents: list,
        checkpoint: FullRunCheckpoint,
    ) -> None:
        """ATOMICALLY co-commit a chunk's cards + bundles + checkpoint advance (BUG-076 §5.1).

        In ONE processing-engine transaction on the SHARED session: upsert every
        card, upsert its bundle, then advance the checkpoint — commit once.
        Atomicity is REQUIRED (not "upsert is idempotent"): card ids are
        LLM-derived (``make_topic_id(primary_anchor_ref)``) and shift on re-run,
        so a partial chunk would mint duplicate/orphan cards. Atomicity converts
        "partial chunk" into "chunk not started" — the only duplicate-free resume.
        On any error the whole chunk rolls back and propagates (committed prior
        chunks stay durable; this chunk is retried on resume).
        """
        # A genuine SQLAlchemy shared session lets us stage every write with
        # commit=False and commit ONCE (true atomicity). When absent (mock / DI
        # unit path with no shared session), fall back to per-write commits — the
        # atomicity guarantee only matters against a real crash-capable DB, which
        # is exercised via the TEST_POSTGRES integration path.
        session = getattr(self.topic_card_repo, "session", None)
        atomic = session is not None
        stage_commit = not atomic
        try:
            for card in cards:
                # BUG-077 (F5): stamp the CHECKPOINT's run_id into the card so a
                # future stale-restart wipe can be scoped to THIS run's cards.
                # ``_build_topic_card`` writes a fresh per-card ``run_<now>``
                # timestamp that matches nothing (it even varies across resume
                # invocations of the same run); overwrite it with the pinned
                # ``fullrun_*`` id here, at the single chunked persist point.
                card.metadata = {
                    **(card.metadata or {}),
                    "topicization_run_id": checkpoint.run_id,
                }
                await self.topic_card_repo.upsert(card, commit=stage_commit)
                bundle = self._compute_topic_bundle(card, channel_id, documents)
                await self.topic_bundle_repo.upsert(bundle, commit=stage_commit)
            await self.processing_failure_repo.record_failure(
                source_ref=full_checkpoint_marker_ref(channel_id),
                channel_id=channel_id,
                attempts=checkpoint.chunks_done,
                error_class=FULL_CHECKPOINT_ERROR_CLASS,
                error_message="topicization full-run checkpoint",
                error_details=checkpoint.to_details(),
                commit=stage_commit,
            )
            if atomic:
                await session.commit()
        except Exception:
            if atomic:
                with contextlib.suppress(Exception):
                    await session.rollback()
            raise

    async def _topicize_channel_chunked(
        self,
        *,
        channel_id: str,
        documents: list,
        force: bool,
        resume: bool,
    ) -> list[TopicCard]:
        """Chunked, resumable, budget-aware full topicization (BUG-076 §5.1/5.3).

        Partitions the corpus into chunks of ``topicization_full_chunk_batches``
        50-doc batches. Per chunk: generate → merge-within-chunk (billing/timeout
        = clean resumable halt) → build cards → ATOMIC co-commit of cards +
        bundles + checkpoint advance. Bounded per invocation by
        ``topicization_full_max_chunks_per_invocation`` AND the per-invocation
        ``topicization_full_run_token_budget`` (enforced at chunk boundaries).
        The cross-chunk consolidation + checkpoint clear (§5.4) is driven by the
        service AFTER ``full_run_all_chunks_done`` is set.
        """
        from tg_parser.api.metrics import (
            record_topic_created,
            record_topicization_full_run_budget_halt,
            record_topicization_full_run_chunk_failed,
            record_topicization_full_run_noprogress_skip,
            record_topicization_full_run_resume,
            record_topicization_full_run_tokens,
            set_topicization_full_run_chunks,
        )

        self.full_run_active = True

        checkpoint = None
        if force:
            await self._delete_full_checkpoint(channel_id)
        else:
            try:
                checkpoint = await self._read_full_checkpoint(channel_id)
            except FullCheckpointReadError as e:
                # BUG-077 (F3): a transient read error must NOT fall through to
                # a fresh chunk-0 run (it would re-burn tokens, overwrite the
                # real checkpoint and mint duplicate cards). Abort this
                # invocation benignly at 0 token cost; retry next tick.
                self.full_run_halted = True
                # BUG-077 (Bugbot round-3 MEDIUM follow-up): flag this as a
                # ZERO-cost, ZERO-chunks-attempted abort — distinct from a
                # genuine chunk-generation stall — so the service driver's F1
                # bookkeeping does not mistake this transient read blip for a
                # costly no-progress resume and pollute the breaker.
                self.full_run_checkpoint_read_aborted = True
                logger.warning(
                    "full_run_checkpoint_read_error channel=%s — aborting "
                    "invocation (0 cost, retry next tick): %s",
                    channel_id,
                    e,
                )
                return []

        if resume and not force and checkpoint is None:
            # BUG-077 (F3, read/clear race): the resume driver saw a live
            # checkpoint in its short-lived pre-read, but by the time this
            # invocation acquired 0x70C1 the row is gone (run completed and
            # cleared, or a stale cleanup removed it). A resume with no
            # checkpoint must be a NO-OP — starting a fresh pinned run here
            # would re-burn the whole corpus on a benign race.
            logger.info(
                "full_run_resume_checkpoint_vanished channel=%s — no-op "
                "(checkpoint cleared under the lock)",
                channel_id,
            )
            return []

        run_id = f"fullrun_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        chunks_done = 0
        batches_done = 0
        tokens_cumulative = 0

        # --- Plan pinning (round-2 F1/F3 → round-3 F1) -------------------------
        # A run PINS its plan at start: the EXACT ordered set of planned doc refs
        # (planned_refs = sorted unique source_ref) + the chunk_batches span. On
        # resume the plan is rebuilt by MEMBERSHIP-BY-REF (select exactly the
        # pinned refs, replayed in the pinned order) + the PINNED span, so:
        #   (F1) pure APPENDS (new refs) are excluded by ref-membership and can
        #        NEVER shift chunk boundaries — regardless of processed_at ties /
        #        coarse timestamps (the round-2 max(processed_at) watermark had a
        #        same-second tie flaw that reintroduced the round-1 wipe loop);
        #   (F3) a changed topicization_full_chunk_batches setting cannot
        #        re-interpret chunks_done against a different partition.
        # Only a genuine material change (a PINNED ref no longer exists in the
        # live corpus — deleted/replaced) triggers a clean stale restart.
        resuming = False
        plan_cards_stamped = True  # fresh runs are written by BUG-077 F5 code
        if checkpoint is not None:
            if checkpoint.is_complete:
                # Already fully done (all chunks + cross-chunk merge): clear the
                # checkpoint and no-op. Makes a re-run idempotent.
                await self._delete_full_checkpoint(channel_id)
                # chunks_total is unknown here without a plan; report the pinned
                # count so the gauge/flags stay coherent.
                self.full_run_chunks_total = checkpoint.chunks_total
                self.full_run_chunks_done = checkpoint.chunks_total
                self.full_run_all_chunks_done = True
                return []

            # BUG-077 (F1): no-progress circuit-breaker. Checked HERE (not only
            # in the resume driver) so EVERY entry into a live checkpointed run
            # is bounded — including the 0-card ``should_reescalate`` escalation
            # path, which is NOT cooldown-gated while a live checkpoint exists
            # (round-2 F2 deliberately skips arming) and would otherwise keep
            # re-burning the failing chunk every tick even with the driver's
            # gate open. While the breaker is open this invocation is a benign
            # 0-cost no-op; once the cooldown TTL elapses one probe runs.
            if noprogress_circuit_open(checkpoint):
                self.full_run_halted = True
                with contextlib.suppress(Exception):
                    record_topicization_full_run_noprogress_skip(channel_id=channel_id)
                logger.warning(
                    "full_run_noprogress_circuit_open channel=%s "
                    "consecutive_noprogress=%d chunks_done=%d/%d — skipping "
                    "invocation (0 cost; probe after cooldown)",
                    channel_id,
                    checkpoint.consecutive_noprogress_resumes,
                    checkpoint.chunks_done,
                    checkpoint.chunks_total,
                )
                return []

            pinned_refs = checkpoint.planned_refs
            live_by_ref = {d.source_ref: d for d in documents}
            missing_refs = [r for r in pinned_refs if r not in live_by_ref]
            if pinned_refs and not missing_refs:
                # Plan intact — every pinned ref still exists. Appends (extra refs
                # in live_by_ref) are IGNORED by membership. Replay the docs in
                # the exact pinned order (tie-proof, deterministic).
                resuming = True
                docs_ordered = [live_by_ref[r] for r in pinned_refs]
                planned_refs = list(pinned_refs)
                planned_hash = checkpoint.planned_ref_hash or planned_ref_hash(planned_refs)
                planned_doc_count = checkpoint.planned_doc_count or len(planned_refs)
                chunk_span = max(
                    1,
                    int(checkpoint.chunk_batches or 0)
                    or int(settings.topicization_full_chunk_batches),
                )
                run_id = checkpoint.run_id or run_id
                chunks_done = checkpoint.chunks_done
                batches_done = checkpoint.batches_done
                tokens_cumulative = checkpoint.tokens_spent_cumulative
                # BUG-077 (F5): carry the stamp flag forward — a run STARTED
                # before the card-stamping fix has earlier chunks whose cards
                # are NOT stamped with this run_id, so its stale wipe must stay
                # broad even if later chunks commit under the new code.
                plan_cards_stamped = checkpoint.cards_stamped
                if resume:
                    with contextlib.suppress(Exception):
                        record_topicization_full_run_resume(channel_id=channel_id)
                logger.info(
                    "full_run_resume channel=%s chunks_done=%d planned_docs=%d "
                    "chunk_batches=%d run_id=%s (appends by ref-membership ignored)",
                    channel_id,
                    chunks_done,
                    planned_doc_count,
                    chunk_span,
                    run_id,
                )
            else:
                # Material change: one or more PINNED refs no longer exist in the
                # live corpus (deleted / replaced) — or the checkpoint predates
                # ref-pinning (empty planned_refs). Resuming a stale plan is
                # unsafe, so restart cleanly from chunk 0.
                #
                # (round-1 F2): the prior partial run persisted cards + bundles
                # under the OLD plan; since ids are LLM-derived they would
                # orphan/duplicate against a fresh chunk-0 pass. Clear the prior
                # run's cards + bundles BEFORE restarting (mirrors force-mode).
                logger.info(
                    "full_run_checkpoint_stale_restart channel=%s (%d pinned ref(s) "
                    "missing from live corpus) — clearing prior partial-run cards/bundles",
                    channel_id,
                    len(missing_refs),
                )
                # BUG-077 (F5): scope the wipe to the prior run's cards. Cards
                # persisted by the chunked path carry
                # ``metadata.topicization_run_id == checkpoint.run_id`` (stamped
                # in ``_commit_chunk_atomically``), so ONLY they are deleted —
                # incremental/discover cards created by the BUG-075 reconcile
                # path on the same channel survive. A checkpoint that predates
                # the stamp (``cards_stamped=False`` — its cards carry
                # unmatchable per-card ``run_<now>`` ids) falls back to the
                # broad ``delete_by_channel`` so the duplicate-card problem the
                # wipe exists to prevent cannot return.
                if checkpoint.cards_stamped and checkpoint.run_id:
                    deleted_cards = 0
                    deleted_bundles = 0
                    for old_card in await self.topic_card_repo.list_by_channel(channel_id):
                        stamped = (old_card.metadata or {}).get("topicization_run_id")
                        if stamped == checkpoint.run_id:
                            deleted_bundles += await self.topic_bundle_repo.delete_by_topic_id(
                                old_card.id
                            )
                            deleted_cards += await self.topic_card_repo.delete_by_id(old_card.id)
                else:
                    deleted_bundles = await self.topic_bundle_repo.delete_by_channel(channel_id)
                    deleted_cards = await self.topic_card_repo.delete_by_channel(channel_id)
                logger.info(
                    "full_run_stale_restart_cleared channel=%s cards=%d bundles=%d scoped=%s",
                    channel_id,
                    deleted_cards,
                    deleted_bundles,
                    bool(checkpoint.cards_stamped and checkpoint.run_id),
                )
                await self._delete_full_checkpoint(channel_id)

        if not resuming:
            # Fresh run: pin the plan to the CURRENT corpus + CURRENT setting.
            # Deterministic order by source_ref (unique → tie-free) so the
            # partition is reproduced identically on every resume.
            docs_ordered = sorted(documents, key=lambda d: d.source_ref)
            planned_refs = planned_refs_from_documents(documents)
            planned_hash = planned_ref_hash(planned_refs)
            planned_doc_count = len(planned_refs)
            chunk_span = max(1, int(settings.topicization_full_chunk_batches))

        candidates = [
            {
                "source_ref": doc.source_ref,
                "text_clean": doc.text_clean,
                "summary": doc.summary,
                "topics": doc.topics or [],
                "channel_id": doc.channel_id,
                "message_id": doc.source_message_id,
            }
            for doc in docs_ordered
        ]

        BATCH_SIZE = self.batch_size
        batches = [candidates[i : i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]
        self.total_batches = len(batches)
        chunks = [batches[i : i + chunk_span] for i in range(0, len(batches), chunk_span)]
        chunks_total = len(chunks)
        self.full_run_chunks_total = chunks_total
        chunks_done = min(chunks_done, chunks_total)

        self.full_run_chunks_done = chunks_done
        with contextlib.suppress(Exception):
            set_topicization_full_run_chunks(
                channel_id=channel_id, done=chunks_done, total=chunks_total
            )

        budget = int(settings.topicization_full_run_token_budget or 0)
        max_chunks = int(settings.topicization_full_max_chunks_per_invocation or 0)

        persisted_this_invocation: list[TopicCard] = []
        processed_this_invocation = 0
        halted = False

        for chunk_idx in range(chunks_done, chunks_total):
            # Per-invocation chunk cap (also the missing wall-clock bound).
            if max_chunks and processed_this_invocation >= max_chunks:
                logger.info(
                    "full_run_invocation_cap channel=%s processed=%d chunks_done=%d/%d",
                    channel_id,
                    processed_this_invocation,
                    chunks_done,
                    chunks_total,
                )
                break

            # Budget kill-switch at the chunk boundary (a single gather over all
            # batches cannot be interrupted mid-flight — §5.3).
            invocation_tokens = self.total_input_tokens + self.total_output_tokens
            if budget and invocation_tokens >= budget:
                halted = True
                logger.warning(
                    "topicization_full_run_budget_halt channel=%s tokens=%d budget=%d "
                    "chunks_done=%d/%d — clean halt at durable boundary, resumable",
                    channel_id,
                    invocation_tokens,
                    budget,
                    chunks_done,
                    chunks_total,
                )
                with contextlib.suppress(Exception):
                    record_topicization_full_run_budget_halt(channel_id=channel_id)
                break

            chunk = chunks[chunk_idx]
            tokens_before = self.total_input_tokens + self.total_output_tokens

            def _record_chunk_failed(reason: str, _before: int = tokens_before) -> None:
                # BUG-077 (F9): every NON-ADVANCING chunk halt is first-class —
                # a failure counter (the F1 drip signature) plus the chunk's
                # PRE-COMMIT token spend, which tokens_total (post-commit only)
                # would otherwise never see. Best-effort: metrics must never
                # crash the halt path. A failed chunk is never ALSO committed,
                # so this cannot double-count against the post-commit emit.
                with contextlib.suppress(Exception):
                    record_topicization_full_run_chunk_failed(channel_id=channel_id, reason=reason)
                with contextlib.suppress(Exception):
                    spent = (self.total_input_tokens + self.total_output_tokens) - _before
                    if spent > 0:
                        record_topicization_full_run_tokens(channel_id=channel_id, count=spent)

            chunk_topics, chunk_failed = await self._generate_chunk(channel_id, chunk)

            raw_topics: list[dict] = []
            if chunk_topics:
                try:
                    raw_topics = await self._merge_topics(chunk_topics, candidates)
                except (AnthropicBillingError, LLMCallTimeoutError) as e:
                    # The merge is the unprotected single point of failure in the
                    # monolithic path (§2.2). Here it is a CLEAN resumable halt:
                    # the chunk is NOT committed, prior chunks stay durable, and a
                    # resume regenerates only this chunk. Record a merge-stage
                    # failed batch so the halt is visible to
                    # TopicizationFailedBatchesHigh (§6).
                    self.failed_batches += 1
                    self.last_batch_error = f"{type(e).__name__}: {e}"
                    self._record_failed_batch("topicization_merge", channel_id)
                    halted = True
                    _record_chunk_failed("merge_halt")
                    logger.warning(
                        "topicization_full_run_merge_halt channel=%s chunk=%d (%s: %s) "
                        "— clean resumable halt",
                        channel_id,
                        chunk_idx,
                        type(e).__name__,
                        e,
                    )
                    break
                except (TypeError, AttributeError) as e:
                    # BUG-077 (F2, folded into F1): a MALFORMED merge reply —
                    # after per-member ID coercion, only a structural failure
                    # elsewhere in post-processing reaches this guard. Keep it
                    # as a clean resumable halt counted as a failed merge (chunk
                    # NOT committed, checkpoint NOT advanced) that feeds the F1
                    # no-progress counter.
                    self.failed_batches += 1
                    self.last_batch_error = f"{type(e).__name__}: {e}"
                    self._record_failed_batch("topicization_merge", channel_id)
                    halted = True
                    _record_chunk_failed("malformed_merge")
                    logger.warning(
                        "topicization_full_run_malformed_merge_halt channel=%s "
                        "chunk=%d (%s: %s) — clean resumable halt",
                        channel_id,
                        chunk_idx,
                        type(e).__name__,
                        e,
                    )
                    break

            cards: list[TopicCard] = []
            for raw_topic in raw_topics:
                try:
                    card = self._build_topic_card(
                        raw_topic=raw_topic,
                        channel_id=channel_id,
                        documents=documents,
                    )
                    if card:
                        cards.append(card)
                except (ValueError, KeyError, AttributeError) as e:
                    logger.error("Failed to build topic card from raw_topic: %s", e)
                    continue

            # Finding 1 (Bugbot HIGH): a chunk that produced ZERO cards must only
            # advance the checkpoint when the emptiness is GENUINE (every batch
            # generated + merged cleanly and simply yielded no card — e.g. all
            # docs are quality-rejected / legitimately uncoverable). If ANY batch
            # in the chunk RAISED (chunk_failed > 0), the emptiness may be caused
            # by that transient failure, so advancing would permanently strand the
            # chunk's docs (a resume — and the 0-card should_reescalate path —
            # would skip an already-"done" chunk). In that case HALT cleanly
            # WITHOUT advancing so a later resume regenerates this chunk.
            #
            # Genuinely-empty chunks (chunk_failed == 0) DO advance with an empty
            # card set: this is required for cold-start convergence/termination —
            # a corpus with no topicizable content must still finish the run and
            # clear the checkpoint rather than halt-loop forever. (Card-build
            # exceptions are treated as genuine/deterministic here: retrying the
            # same malformed LLM output would not converge, so we advance and let
            # the BUG-075 reconcile hook re-cover those docs.)
            if not cards and chunk_failed > 0:
                halted = True
                _record_chunk_failed("empty_after_failure")
                logger.warning(
                    "topicization_full_run_chunk_empty_after_failure channel=%s "
                    "chunk=%d failed=%d — clean resumable halt (NOT advancing "
                    "checkpoint; a resume will regenerate this chunk)",
                    channel_id,
                    chunk_idx,
                    chunk_failed,
                )
                break

            new_chunks_done = chunk_idx + 1
            new_batches_done = batches_done + len(chunk)
            invocation_tokens_now = self.total_input_tokens + self.total_output_tokens
            checkpoint_state = FullRunCheckpoint(
                run_id=run_id,
                planned_refs=planned_refs,
                planned_ref_hash=planned_hash,
                planned_doc_count=planned_doc_count,
                chunk_batches=chunk_span,
                chunks_total=chunks_total,
                chunks_done=new_chunks_done,
                batches_done=new_batches_done,
                tokens_spent_cumulative=tokens_cumulative + invocation_tokens_now,
                final_merge_done=False,
                # F1: a durable chunk commit IS progress — the fresh default 0
                # for consecutive_noprogress_resumes resets the breaker.
                cards_stamped=plan_cards_stamped,
            )

            # ATOMIC co-commit (cards + bundles + checkpoint). On any failure the
            # chunk rolls back → no partial-chunk state, so no duplicate ids.
            # BUG-077 (F9/F1): an in-process commit failure (e.g. a built card
            # violating a DB constraint) is a CLEAN resumable halt — logged +
            # counted, never an uncaught crash retried bare every tick. The
            # transaction already rolled back inside _commit_chunk_atomically.
            try:
                await self._commit_chunk_atomically(
                    channel_id=channel_id,
                    cards=cards,
                    documents=documents,
                    checkpoint=checkpoint_state,
                )
            except Exception as e:
                self.failed_batches += 1
                self.last_batch_error = f"{type(e).__name__}: {e}"
                self._record_failed_batch("topicization_commit", channel_id)
                halted = True
                _record_chunk_failed("commit_failed")
                logger.error(
                    "topicization_full_run_commit_failed channel=%s chunk=%d "
                    "(%s: %s) — clean resumable halt (chunk rolled back)",
                    channel_id,
                    chunk_idx,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                break

            # Post-commit side-effects (metrics only — never transactional). One
            # record_topic_created per persisted card wires the full path into
            # tg_parser_topics_created_total so TopicizationBurnNoProgress stops
            # false-positiving; the service wrapper is guarded off (no double-count).
            for _ in cards:
                with contextlib.suppress(Exception):
                    record_topic_created(channel_id=channel_id)
            with contextlib.suppress(Exception):
                record_topicization_full_run_tokens(
                    channel_id=channel_id,
                    count=invocation_tokens_now - tokens_before,
                )

            chunks_done = new_chunks_done
            batches_done = new_batches_done
            processed_this_invocation += 1
            persisted_this_invocation.extend(cards)
            self.full_run_chunks_done = chunks_done
            with contextlib.suppress(Exception):
                set_topicization_full_run_chunks(
                    channel_id=channel_id, done=chunks_done, total=chunks_total
                )

            # Budget check AFTER the durable commit too, so we stop promptly once
            # the just-finished chunk pushed us over.
            if budget and invocation_tokens_now >= budget:
                halted = True
                logger.warning(
                    "topicization_full_run_budget_halt channel=%s tokens=%d budget=%d "
                    "chunks_done=%d/%d (post-chunk) — resumable",
                    channel_id,
                    invocation_tokens_now,
                    budget,
                    chunks_done,
                    chunks_total,
                )
                with contextlib.suppress(Exception):
                    record_topicization_full_run_budget_halt(channel_id=channel_id)
                break

        self.full_run_halted = halted
        self.full_run_all_chunks_done = (chunks_done >= chunks_total) and not halted

        # BUG-077 (F1, Bugbot HIGH follow-up): a halt that made ZERO durable
        # progress THIS invocation, against a checkpoint that ALREADY existed
        # (``resuming`` — i.e. this attempt continued a live pinned plan,
        # whether triggered by the escalation branch or the resume driver),
        # is exactly the "no-progress resume" the F1 breaker bounds. Bump the
        # counter HERE — see ``_record_noprogress_resume`` for why this must
        # be the sole writer. A fresh run with no prior checkpoint (or one
        # that hit a stale restart and re-pinned under a NEW run_id) is not a
        # "no-progress RESUME" and must not touch this counter.
        if halted and resuming and processed_this_invocation == 0:
            await self._record_noprogress_resume(
                channel_id,
                run_id=run_id,
                planned_refs=planned_refs,
                planned_ref_hash_value=planned_hash,
                planned_doc_count=planned_doc_count,
                chunk_batches=chunk_span,
                chunks_total=chunks_total,
                chunks_done=chunks_done,
                batches_done=batches_done,
                tokens_spent_before=tokens_cumulative,
                last_chunk_at=checkpoint.last_chunk_at if checkpoint is not None else None,
                consecutive_noprogress_resumes=(
                    checkpoint.consecutive_noprogress_resumes if checkpoint is not None else 0
                ),
                cards_stamped=plan_cards_stamped,
            )

        logger.info(
            "full_run_invocation_done channel=%s chunks_done=%d/%d halted=%s "
            "all_done=%s persisted_this_invocation=%d",
            channel_id,
            chunks_done,
            chunks_total,
            halted,
            self.full_run_all_chunks_done,
            len(persisted_this_invocation),
        )
        return persisted_this_invocation

    def _record_truncation(self, stage: str) -> None:
        """BUG-071 (Fix 3): count one ``max_tokens`` truncation for this stage.

        Records :data:`tg_parser_llm_truncation_total` labelled by provider /
        model / stage so paid-but-discarded truncated calls are alertable
        (``record_llm_request`` otherwise folds them into ``status="success"``).
        """
        from tg_parser.api.metrics import record_llm_truncation
        from tg_parser.processing.llm.factory import get_provider_from_client

        record_llm_truncation(
            provider=get_provider_from_client(self.llm_client),
            model=self.model_id,
            stage=stage,
        )

    def _record_failed_batch(self, stage: str, channel_id: str, count: int = 1) -> None:
        """BUG-071 (observability): count ``count`` failed topicization batches.

        Mirrors every :attr:`failed_batches` increment in ``topicize_channel`` onto
        the :data:`tg_parser_topicization_failed_batches_total` Prometheus counter so
        the metric stays consistent with the log/CLI number. Best-effort: a metrics
        error must never crash a topicization tick (consistent with the rest of the
        pipeline's metric side-effects).
        """
        try:
            from tg_parser.api.metrics import record_topicization_failed_batch

            record_topicization_failed_batch(stage=stage, channel_id=channel_id, count=count)
        except Exception as e:  # noqa: BLE001 — observability must never fail a tick
            logger.debug("record_topicization_failed_batch failed: %s", e)

    async def _generate_topics_batch(
        self, candidates: list[dict], *, max_tokens_override: int | None = None
    ) -> list[dict]:
        """Генерировать темы для одного батча кандидатов.

        429 retries handled by AnthropicClient rate limiter; only JSONDecodeError retried here.

        BUG-071 (Fix 1): a ``max_tokens`` truncation is NOT retried with the
        identical oversized request (which only re-burns tokens — repair_json
        cannot fix a reply cut off mid-string). Instead the request is shrunk
        (split the batch, or scale the token budget for a single candidate) and
        retried once at the smaller size via
        :meth:`_generate_topics_batch_after_truncation`.
        """
        prompt = build_topicization_prompt(candidates)
        max_json_retries = _TOPICIZATION_MAX_JSON_RETRIES

        topic_config = get_prompt_loader().load("topicization")
        system_prompt = topic_config.get("system", {}).get("prompt") or TOPICIZATION_SYSTEM_PROMPT
        model_cfg = topic_config.get("model", {})
        max_tokens = max_tokens_override or model_cfg.get("max_tokens", 8192)

        for attempt in range(1, max_json_retries + 1):
            try:
                # BUG-019: append a corrective hint on retries (attempt > 1).
                if attempt > 1:
                    from tg_parser.api.metrics import record_llm_json_parse_retry

                    record_llm_json_parse_retry(stage="topicization_generate")
                llm_response = await self.llm_client.generate_with_usage(
                    prompt=apply_json_retry_hint(prompt, attempt),
                    system_prompt=system_prompt,
                    temperature=model_cfg.get("temperature", 0.0),
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                self.total_input_tokens += llm_response.input_tokens
                self.total_output_tokens += llm_response.output_tokens

                # BUG-071 (Fix 1): truncation — do not loop on the identical
                # oversized request; shrink and retry once at the smaller size.
                if llm_response.stop_reason == "max_tokens":
                    self._record_truncation("topicization_generate")
                    logger.warning(
                        "topicization_generate_truncated",
                        candidates=len(candidates),
                        max_tokens=max_tokens,
                    )
                    return await self._generate_topics_batch_after_truncation(
                        candidates, max_tokens
                    )

                cleaned = extract_json_from_response(llm_response.text)
                llm_result = _loads_topicization_json_with_repair(
                    cleaned, stage="topicization_generate"
                )
                raw_topics = llm_result.get("topics", [])

                logger.info(
                    "LLM generated %d raw topics from batch of %d", len(raw_topics), len(candidates)
                )
                return raw_topics

            except json.JSONDecodeError as e:
                if attempt < max_json_retries:
                    logger.warning(
                        "JSON parse error (attempt %d/%d): %s, retrying",
                        attempt,
                        max_json_retries,
                        e,
                    )
                    await asyncio.sleep(settings.llm_json_retry_delay)
                else:
                    logger.error(
                        "Failed to parse topics JSON after %d attempts",
                        max_json_retries,
                        exc_info=True,
                    )
                    raise RuntimeError(f"Topicization JSON parse failed: {e}") from e
            except (RuntimeError, ValueError, OSError) as e:
                logger.error("Failed to generate topics with LLM: %s", e, exc_info=True)
                raise RuntimeError(f"Topicization LLM call failed: {e}") from e
        return []

    async def _generate_topics_batch_after_truncation(
        self, candidates: list[dict], prev_max_tokens: int
    ) -> list[dict]:
        """BUG-071 (Fix 1): recover from a ``max_tokens`` truncation by shrinking.

        Multiple candidates → split the batch in half and re-generate each half
        (each half re-enters the normal retry loop, so a half that still
        truncates is split again). A single candidate cannot be split → scale
        the token budget once (capped). If even the largest budget truncates,
        the batch is dropped.

        BUG-071 (Bugbot follow-up / BUG-018 regression): a *complete* drop —
        nothing salvaged after splitting/scaling — raises
        :class:`TopicizationBatchTruncatedError` instead of returning ``[]`` so
        ``topicize_channel`` counts it as a failed batch (restoring the
        systemic-fail exit-code-2 semantics). A *partial* drop (one half still
        yields topics) is NOT a batch failure: the salvaged topics are returned
        and the truncation is recorded only via the metric.
        """
        if len(candidates) > 1:
            mid = len(candidates) // 2
            logger.info(
                "topicization_generate_shrink_split",
                left=mid,
                right=len(candidates) - mid,
            )
            salvaged: list[dict] = []
            dropped = 0
            for sub in (candidates[:mid], candidates[mid:]):
                try:
                    salvaged.extend(await self._generate_topics_batch(sub))
                except TopicizationBatchTruncatedError:
                    dropped += 1
            if dropped and not salvaged:
                # Every split truncation-dropped → the whole batch is lost.
                raise TopicizationBatchTruncatedError(len(candidates))
            return salvaged

        scaled = _scaled_max_tokens(prev_max_tokens)
        if scaled is not None:
            logger.info(
                "topicization_generate_shrink_scale_tokens",
                prev_max_tokens=prev_max_tokens,
                max_tokens=scaled,
            )
            return await self._generate_topics_batch(candidates, max_tokens_override=scaled)

        logger.error(
            "topicization_generate truncated on a single candidate at the max_tokens cap; "
            "dropping batch as a failure (no further shrink possible)"
        )
        raise TopicizationBatchTruncatedError(len(candidates))

    async def _merge_topics(
        self, all_batch_topics: list[dict], candidates: list[dict]
    ) -> list[dict]:
        """
        Объединить темы из нескольких батчей.

        LLM возвращает только группы ID дубликатов (минимальный output).
        Метаданные (title, summary, scope, anchors) собираются программно.
        """
        logger.info("Merging %d topics from batches", len(all_batch_topics))

        topics_compact = [
            {
                "id": i,
                "title": topic.get("title", ""),
                "summary": topic.get("summary", "")[:60],
            }
            for i, topic in enumerate(all_batch_topics)
        ]

        merge_config = get_prompt_loader().load("merge")
        merge_sys = merge_config.get("system", {}).get(
            "prompt",
            "You are a topic deduplication expert. Return compact JSON with only group ID arrays.",
        )
        merge_user_tpl = merge_config.get("user", {}).get("template")
        merge_model = merge_config.get("model", {})

        if merge_user_tpl:
            merge_prompt = merge_user_tpl.format(
                topic_count=len(topics_compact),
                topics_json=json.dumps(topics_compact, ensure_ascii=False),
            )
        else:
            merge_prompt = (
                f"You have {len(topics_compact)} topics extracted from different batches of messages "
                f"from the same Telegram channel.\n"
                f"Many topics will overlap or cover the same subject — group them aggressively.\n\n"
                f"Topics:\n{json.dumps(topics_compact, ensure_ascii=False)}\n\n"
                f'Return JSON:\n{{"groups": [[0, 5, 12], [3], [1, 7]]}}\n\n'
                f"Rules:\n"
                f"- Each topic ID must appear in exactly one group\n"
                f"- Merge topics that cover the same subject even if titles differ slightly\n"
                f"- Be aggressive: prefer fewer, broader groups over many narrow ones\n"
                f"- Singletons: [3] (topic with truly no overlap)\n"
                f"- Merged: [0, 5, 12] (same or overlapping subjects grouped together)\n"
                f'- Return ONLY the "groups" array of arrays of integer IDs, nothing else'
            )

        max_merge_retries = _TOPICIZATION_MAX_JSON_RETRIES
        groups = []
        # BUG-071 (Fix 1): mutable so a max_tokens truncation can GROW the budget
        # (a bigger request, not the identical oversized one) instead of looping.
        merge_max_tokens = merge_model.get("max_tokens", 16384)

        for attempt in range(1, max_merge_retries + 1):
            try:
                # BUG-019: append a corrective hint on retries (attempt > 1).
                if attempt > 1:
                    from tg_parser.api.metrics import record_llm_json_parse_retry

                    record_llm_json_parse_retry(stage="topicization_merge")
                llm_response = await self.llm_client.generate_with_usage(
                    prompt=apply_json_retry_hint(merge_prompt, attempt),
                    system_prompt=merge_sys,
                    temperature=merge_model.get("temperature", 0.0),
                    max_tokens=merge_max_tokens,
                    response_format={"type": "json_object"},
                )
                self.total_input_tokens += llm_response.input_tokens
                self.total_output_tokens += llm_response.output_tokens

                # BUG-071 (Fix 1): the merge LLM only returns compact group ID
                # arrays, so it can't be split per-batch — instead grow the
                # token budget once (capped) and retry. If it still truncates
                # (or we're at the cap), fall back to the existing contract:
                # return all_batch_topics unmerged.
                if llm_response.stop_reason == "max_tokens":
                    self._record_truncation("topicization_merge")
                    scaled = _scaled_max_tokens(merge_max_tokens)
                    if scaled is not None and attempt < max_merge_retries:
                        logger.warning(
                            "topicization_merge_truncated_grow",
                            prev_max_tokens=merge_max_tokens,
                            max_tokens=scaled,
                        )
                        merge_max_tokens = scaled
                        continue
                    logger.warning(
                        "Merge truncated and cannot grow further, using all batch topics"
                    )
                    return all_batch_topics

                cleaned = extract_json_from_response(llm_response.text)
                result = _loads_topicization_json_with_repair(cleaned, stage="topicization_merge")
                groups = result.get("groups", [])
                break
            except json.JSONDecodeError as e:
                if attempt < max_merge_retries:
                    logger.warning(
                        "Merge JSON parse error (attempt %d/%d): %s, retrying",
                        attempt,
                        max_merge_retries,
                        e,
                    )
                    await asyncio.sleep(settings.llm_json_retry_delay)
                else:
                    logger.warning(
                        "Merge JSON parse failed after %d attempts, using all batch topics: %s",
                        max_merge_retries,
                        e,
                    )
                    return all_batch_topics
            except (RuntimeError, ValueError, OSError) as e:
                logger.warning("Failed to merge topics: %s", e, exc_info=True)
                return all_batch_topics

        if not groups:
            logger.warning("Merge returned empty groups, using all batch topics")
            return all_batch_topics

        normalized_groups: list[list[int]] = []
        claimed_ids: set[int] = set()
        for group in groups:
            if isinstance(group, list):
                member_ids = group
            else:
                member_ids = group.get("member_ids", [])
            if not isinstance(member_ids, list):
                raise TypeError("merge group member_ids must be a list")

            valid_ids = []
            for member_id in member_ids:
                coerced_id = _coerce_merge_member_id(member_id)
                if (
                    coerced_id is None
                    or coerced_id < 0
                    or coerced_id >= len(all_batch_topics)
                    or coerced_id in claimed_ids
                ):
                    continue
                valid_ids.append(coerced_id)
                claimed_ids.add(coerced_id)
            if not valid_ids:
                continue
            normalized_groups.append(valid_ids)

        normalized_groups.extend(
            [topic_id] for topic_id in range(len(all_batch_topics)) if topic_id not in claimed_ids
        )

        merged_topics = []
        for valid_ids in normalized_groups:
            primary_id = max(
                valid_ids,
                key=lambda topic_id: len(all_batch_topics[topic_id].get("anchors", [])),
            )
            primary = all_batch_topics[primary_id]

            combined_anchors = []
            seen_refs: set[str] = set()
            for mid in valid_ids:
                for anchor in all_batch_topics[mid].get("anchors", []):
                    ref = anchor.get("source_ref", "")
                    if ref and ref not in seen_refs:
                        combined_anchors.append(anchor)
                        seen_refs.add(ref)

            merged_topics.append(
                {
                    "title": primary.get("title", ""),
                    "summary": primary.get("summary", ""),
                    "type": primary.get("type", "cluster") if len(valid_ids) == 1 else "cluster",
                    "scope_in": primary.get("scope_in", []),
                    "scope_out": primary.get("scope_out", []),
                    "anchors": combined_anchors,
                }
            )

        logger.info(
            "Merged %d batch topics into %d unique topics",
            len(all_batch_topics),
            len(merged_topics),
        )
        return merged_topics

    def _build_topic_card(
        self,
        raw_topic: dict,
        channel_id: str,
        documents: list,
    ) -> TopicCard | None:
        """
        Построить и валидировать TopicCard из raw LLM output.

        TR-IF-4: детерминизация anchors (sort by score desc, anchor_ref asc).
        TR-35: критерии качества.

        Returns:
            TopicCard or None если не прошёл критерии качества
        """
        topic_type_str = raw_topic.get("type", "cluster")
        topic_type = TopicType.SINGLETON if topic_type_str == "singleton" else TopicType.CLUSTER

        proposed_title = raw_topic.get("title", "Untitled Topic")

        # Parse anchors
        raw_anchors = raw_topic.get("anchors", [])

        if not raw_anchors:
            # BUG-023: structured per-event log + aggregate counter so
            # operators can understand why coverage is below expectation.
            self._record_rejection(
                reason="no_raw_anchors",
                title=proposed_title,
                items=0,
            )
            return None

        # Build Anchor objects
        anchors = []
        for raw_anchor in raw_anchors:
            source_ref = raw_anchor.get("source_ref")
            score = raw_anchor.get("score", 0.0)

            if not source_ref:
                continue

            # Parse source_ref: tg:channel_id:message_type:message_id
            parts = source_ref.split(":")
            if len(parts) != 4:
                logger.warning("Invalid source_ref format: %s", source_ref)
                continue

            _, ch_id, msg_type, msg_id = parts

            anchors.append(
                Anchor(
                    channel_id=ch_id,
                    message_id=msg_id,
                    message_type=MessageType(msg_type),
                    anchor_ref=source_ref,
                    score=score,
                )
            )

        if not anchors:
            self._record_rejection(
                reason="no_valid_anchors_after_parsing",
                title=proposed_title,
                items=len(raw_anchors),
            )
            return None

        # Step 4: Детерminизация anchors (TR-IF-4)
        anchors = self._determinize_anchors(anchors, topic_type)

        # Step 5: Применение критериев качества (TR-35)
        valid, reason = self._validate_quality(anchors, topic_type, documents)
        if not valid:
            self._record_rejection(
                reason=reason or "unknown_quality_failure",
                title=proposed_title,
                items=len(anchors),
            )
            return None

        # Build TopicCard
        primary_anchor_ref = anchors[0].anchor_ref
        topic_id = make_topic_id(primary_anchor_ref)

        title = raw_topic.get("title", "Untitled Topic")
        summary = raw_topic.get("summary", "")
        scope_in = raw_topic.get("scope_in", [])
        scope_out = raw_topic.get("scope_out", [])
        tags = raw_topic.get("tags")

        if not scope_in:
            scope_in = ["General topic content"]
        if not scope_out:
            scope_out = ["Unrelated content"]

        metadata = {
            "topicization_run_id": f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "prompt_name": self.prompt_name,
            "algorithm": "llm_clustering",
            "parameters": {
                "temperature": 0.0,
                "min_singleton_score": MIN_SINGLETON_SCORE,
                "min_singleton_length": MIN_SINGLETON_LENGTH,
                "min_cluster_anchors": MIN_CLUSTER_ANCHORS,
                "min_cluster_score": MIN_CLUSTER_SCORE,
                "max_anchors": MAX_ANCHORS_PER_CLUSTER,
            },
            "input_scope": {
                "channel_id": channel_id,
                "mode": "full_history",
            },
        }

        topic_card = TopicCard(
            id=topic_id,
            title=title,
            summary=summary,
            scope_in=scope_in,
            scope_out=scope_out,
            type=topic_type,
            anchors=anchors,
            sources=[channel_id],
            updated_at=datetime.now(UTC),
            tags=tags,
            metadata=metadata,
        )

        return topic_card

    def _determinize_anchors(
        self,
        anchors: list[Anchor],
        topic_type: TopicType,
    ) -> list[Anchor]:
        """
        Детерминизация anchors (TR-IF-4).

        1. Удаление дубликатов по anchor_ref
        2. Сортировка по (score desc, anchor_ref asc)
        3. Top-N для cluster (N=3)
        """
        seen = set()
        unique_anchors = []
        for anchor in anchors:
            if anchor.anchor_ref not in seen:
                seen.add(anchor.anchor_ref)
                unique_anchors.append(anchor)

        sorted_anchors = sorted(
            unique_anchors,
            key=lambda a: (-a.score if a.score else 0.0, a.anchor_ref),
        )

        if topic_type == TopicType.CLUSTER:
            sorted_anchors = sorted_anchors[:MAX_ANCHORS_PER_CLUSTER]

        return sorted_anchors

    def _validate_quality(
        self,
        anchors: list[Anchor],
        topic_type: TopicType,
        documents: list,
    ) -> tuple[bool, str | None]:
        """
        Проверить критерии качества темы (TR-35).

        Singleton: length >= 300, score >= 0.75
        Cluster: min 2 anchors, score >= 0.6

        BUG-023: returns ``(valid, reason)`` so the caller can attribute the
        rejection to a specific criterion in structured logs + an aggregate
        counter (instead of the previous opaque
        ``logger.info("Topic failed quality criteria, skipping")``).
        ``reason`` is ``None`` when ``valid`` is True.
        """
        if topic_type == TopicType.SINGLETON:
            if not anchors:
                return False, "singleton_no_anchors"

            primary_anchor = anchors[0]

            if primary_anchor.score is None or primary_anchor.score < MIN_SINGLETON_SCORE:
                logger.debug("Singleton score too low: %s", primary_anchor.score)
                return False, "singleton_score_below_min"

            doc = next(
                (d for d in documents if d.source_ref == primary_anchor.anchor_ref),
                None,
            )

            if not doc:
                logger.warning("Document not found for anchor_ref: %s", primary_anchor.anchor_ref)
                return False, "singleton_doc_not_found"

            if len(doc.text_clean) < MIN_SINGLETON_LENGTH:
                logger.debug(
                    "Singleton text too short: %d < %d",
                    len(doc.text_clean),
                    MIN_SINGLETON_LENGTH,
                )
                return False, "singleton_text_too_short"

        elif topic_type == TopicType.CLUSTER:
            if len(anchors) < MIN_CLUSTER_ANCHORS:
                logger.debug("Cluster has too few anchors: %d", len(anchors))
                return False, "cluster_too_few_anchors"

            for anchor in anchors:
                if anchor.score is None or anchor.score < MIN_CLUSTER_SCORE:
                    logger.debug("Cluster anchor score too low: %s", anchor.score)
                    return False, "cluster_anchor_score_below_min"

        return True, None

    def _record_rejection(self, *, reason: str, title: str, items: int) -> None:
        """Record a single topic rejection event.

        BUG-023: emits a structured ``topic_failed_quality_criteria`` log
        event with the rejecting criterion + proposed title + items count,
        and increments ``self.rejection_breakdown[reason]`` so end-of-run
        consumers can surface an aggregate breakdown (e.g. «Quality filter
        rejected 6 topics: 4 by cluster_too_few_anchors, 2 by ...»).
        """
        self.rejection_breakdown[reason] = self.rejection_breakdown.get(reason, 0) + 1
        logger.info(
            "topic_failed_quality_criteria",
            reason=reason,
            title=title[:80] if title else "",
            items=items,
        )

    async def build_topic_bundle(
        self,
        topic_card: TopicCard,
        channel_id: str,
        documents: list | None = None,
    ) -> TopicBundle:
        """
        Сформировать подборку материалов по теме (TR-36) и сохранить её.

        Supporting items найдены программным keyword matching (без LLM).
        """
        if documents is None:
            documents = await self.processed_doc_repo.list_by_channel(channel_id)
        bundle = self._compute_topic_bundle(topic_card, channel_id, documents)
        async with self._db_lock:
            await self.topic_bundle_repo.upsert(bundle)
        logger.info("Saved topic bundle: %s with %d items", bundle.topic_id, len(bundle.items))
        return bundle

    def _compute_topic_bundle(
        self,
        topic_card: TopicCard,
        channel_id: str,
        documents: list,
    ) -> TopicBundle:
        """Build (WITHOUT persisting) the TopicBundle for a card (TR-36).

        BUG-076: extracted from :meth:`build_topic_bundle` so the chunked full
        path can upsert the bundle inside the per-chunk ATOMIC transaction
        (``topic_bundle_repo.upsert(bundle, commit=False)``) rather than as a
        separate commit — keeping cards + bundles + checkpoint consistent on a
        crash. ``documents`` is the (already-loaded) channel corpus; this is a
        pure keyword-matching computation with no LLM calls and no DB writes.
        """
        logger.info(
            "Building topic bundle for topic_id=%s, channel_id=%s", topic_card.id, channel_id
        )

        items = []

        for anchor in topic_card.anchors:
            items.append(
                BundleItem(
                    channel_id=anchor.channel_id,
                    message_id=anchor.message_id,
                    message_type=anchor.message_type,
                    source_ref=anchor.anchor_ref,
                    role=BundleItemRole.ANCHOR,
                    parent_message_id=anchor.parent_message_id,
                    thread_id=anchor.thread_id,
                    score=anchor.score,
                )
            )

        anchor_refs = {anchor.anchor_ref for anchor in topic_card.anchors}

        if len(documents) > len(anchor_refs):
            supporting_items = self._find_supporting_items_programmatic(
                topic_card=topic_card,
                anchor_refs=anchor_refs,
                documents=documents,
            )
            items.extend(supporting_items)

        # Дедупликация по source_ref (TR-36)
        seen = set()
        unique_items = []
        for item in items:
            if item.source_ref not in seen:
                seen.add(item.source_ref)
                unique_items.append(item)

        # Детерминированная сортировка (TR-63)
        unique_items.sort(
            key=lambda item: (
                0 if item.role == BundleItemRole.ANCHOR else 1,
                -(item.score if item.score else 0.0),
                item.source_ref,
            )
        )

        metadata = {
            "topicization_run_id": topic_card.metadata.get("topicization_run_id")
            if topic_card.metadata
            else None,
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": "keyword_matching_v2",
            "prompt_name": self.supporting_prompt_name,
            "algorithm": "keyword_matching",
            "parameters": {
                "min_supporting_score": MIN_SUPPORTING_SCORE,
                "max_supporting_items": MAX_SUPPORTING_ITEMS,
                "min_token_length": MIN_TOKEN_LENGTH,
                "text_clean_match_chars": TEXT_CLEAN_MATCH_CHARS,
            },
            "input_scope": {
                "channel_id": channel_id,
                "mode": "full_history",
            },
        }

        return TopicBundle(
            topic_id=topic_card.id,
            items=unique_items,
            updated_at=datetime.now(UTC),
            channels=[channel_id],
            metadata=metadata,
        )

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Extract lowercase word tokens (MIN_TOKEN_LENGTH+ chars) for keyword matching.

        Session 33: lowered from 4 to 2 (configurable) to capture short medical
        abbreviations like СОЭ, ТТГ, ПЦР, IgE, IgG, ЛДГ, АЛТ, ДНК, РНК.
        """
        return set(
            re.findall(
                rf"[a-zA-Zа-яА-ЯёЁ]{{{MIN_TOKEN_LENGTH},}}",
                text.lower(),
            )
        )

    @classmethod
    def _tokenize_topic_card(cls, topic_card: TopicCard) -> set[str]:
        """Build keyword token set from a TopicCard's title and scope_in."""
        tokens: set[str] = set()
        for kw in topic_card.scope_in:
            tokens |= cls._tokenize(kw)
        tokens |= cls._tokenize(topic_card.title)
        tokens.discard("")
        return tokens

    @classmethod
    def _tokenize_document(cls, doc) -> tuple[set[str], set[str]]:
        """Build strong (topics+summary) and weak (text_clean) token sets from a doc.

        Returns (strong_tokens, weak_tokens) where weak = text_clean-only tokens.
        """
        strong: set[str] = set()
        for t in doc.topics or []:
            strong |= cls._tokenize(t)
        if doc.summary:
            strong |= cls._tokenize(doc.summary)

        weak: set[str] = set()
        if TEXT_CLEAN_MATCH_CHARS and doc.text_clean:
            weak = cls._tokenize(doc.text_clean[:TEXT_CLEAN_MATCH_CHARS]) - strong

        return strong, weak

    @staticmethod
    def _compute_match_score(
        topic_keywords: set[str],
        strong_tokens: set[str],
        weak_tokens: set[str],
        *,
        aggregation: str | None = None,
        topk: int | None = None,
    ) -> tuple[float, set[str]]:
        """Compute weighted keyword-overlap score between topic keywords and doc tokens.

        Strong tokens (topics/summary) count at 1.0x, weak tokens (text_clean) at 0.3x.
        Includes substring fallback for long tokens (>=5 chars).
        Aggregation via :func:`_aggregate_assign_score` (S5: mean or topk_denom).

        Returns (score, hit_keywords).
        """
        doc_tokens = strong_tokens | weak_tokens
        if not doc_tokens or not topic_keywords:
            return 0.0, set()

        hits = topic_keywords & doc_tokens
        if not hits:
            for kw in topic_keywords:
                for dt in doc_tokens:
                    if len(kw) >= 5 and len(dt) >= 5 and (kw in dt or dt in kw):
                        hits.add(kw)
                        break

        if not hits:
            return 0.0, set()

        strong_hits = hits & strong_tokens
        weak_hits = hits - strong_tokens
        weighted_hits = len(strong_hits) + len(weak_hits) * 0.3

        score = _aggregate_assign_score(
            weighted_hits,
            len(topic_keywords),
            aggregation=aggregation or ASSIGN_KEYWORD_AGGREGATION,
            topk=topk if topk is not None else ASSIGN_KEYWORD_TOPK,
        )
        return round(score, 3), hits

    def _find_supporting_items_programmatic(
        self,
        topic_card: TopicCard,
        anchor_refs: set[str],
        documents: list,
    ) -> list[BundleItem]:
        """
        Find supporting items by keyword matching against ProcessedDocument.topics.

        Uses scope_in keywords + title tokens to match against each document's
        pre-extracted topics list. No LLM calls — O(topics * docs) string comparisons.
        """
        topic_keywords = self._tokenize_topic_card(topic_card)
        if not topic_keywords:
            return []

        supporting_items: list[BundleItem] = []

        for doc in documents:
            if doc.source_ref in anchor_refs:
                continue

            strong_tokens, weak_tokens = self._tokenize_document(doc)
            score, hits = self._compute_match_score(topic_keywords, strong_tokens, weak_tokens)

            if score < MIN_SUPPORTING_SCORE:
                continue

            parts = doc.source_ref.split(":")
            if len(parts) != 4:
                continue

            _, ch_id, msg_type, msg_id = parts
            supporting_items.append(
                BundleItem(
                    channel_id=ch_id,
                    message_id=msg_id,
                    message_type=MessageType(msg_type),
                    source_ref=doc.source_ref,
                    role=BundleItemRole.SUPPORTING,
                    score=score,
                    justification=f"keyword overlap: {', '.join(sorted(hits)[:5])}",
                )
            )

        supporting_items.sort(key=lambda x: -(x.score or 0))
        supporting_items = supporting_items[:MAX_SUPPORTING_ITEMS]

        logger.info(
            "Programmatic matching found %d supporting items for topic '%s'",
            len(supporting_items),
            topic_card.title[:50],
        )
        return supporting_items

    async def assign_documents_to_topics(
        self,
        new_docs: list,
        channel_id: str,
    ) -> tuple[list[TopicAssignment], list[str]]:
        """
        Phase 1: Programmatic assignment of documents to existing topics.

        For each doc: tokenize fields -> match against topic keywords ->
        assign to best topic if score >= threshold.

        Returns:
            (assignments, unassigned_source_refs)
        """
        topic_cards = await self.topic_card_repo.list_by_channel(channel_id)
        if not topic_cards:
            logger.warning("No topic cards found for channel %s — all docs unassigned", channel_id)
            return [], [doc.source_ref for doc in new_docs]

        topic_keyword_sets: list[tuple[TopicCard, set[str]]] = [
            (card, self._tokenize_topic_card(card)) for card in topic_cards
        ]
        topic_keyword_sets = [(card, kws) for card, kws in topic_keyword_sets if kws]

        assignments: list[TopicAssignment] = []
        unassigned: list[str] = []

        for doc in new_docs:
            strong_tokens, weak_tokens = self._tokenize_document(doc)

            best_score = 0.0
            best_topic_id: str | None = None

            for card, topic_keywords in topic_keyword_sets:
                score, _hits = self._compute_match_score(topic_keywords, strong_tokens, weak_tokens)
                if score > best_score:
                    best_score = score
                    best_topic_id = card.id

            if best_topic_id is not None and best_score >= MIN_SUPPORTING_SCORE:
                assignments.append(
                    TopicAssignment(
                        source_ref=doc.source_ref,
                        topic_id=best_topic_id,
                        score=best_score,
                        method="keyword",
                    )
                )
            else:
                unassigned.append(doc.source_ref)

        logger.info(
            "Phase 1 assign: %d assigned, %d unassigned out of %d new docs (channel=%s)",
            len(assignments),
            len(unassigned),
            len(new_docs),
            channel_id,
        )
        return assignments, unassigned

    async def discover_new_topics(
        self,
        channel_id: str,
        unassigned_docs: list,
        batch_size: int = 50,
        cross_channel_topics: list[dict] | None = None,
    ) -> tuple[list[TopicAssignment], list[TopicCard], list[str], int]:
        """Phase 2: LLM discover — assign unassigned docs to existing topics or create new ones.

        When len(unassigned_docs) > batch_size the documents are split into
        sequential batches.  New topics discovered in batch N are added to the
        existing-topics context for batch N+1 to avoid duplicates.

        Args:
            cross_channel_topics: [{id, title, scope_in, channel_id}] from other channels,
                passed to LLM as dedup context (Phase 2 Enhancement).

        Returns:
            (llm_assignments, new_topic_cards, unassignable_refs, tokens_used)
        """
        if not unassigned_docs:
            return [], [], [], 0

        topic_cards = await self.topic_card_repo.list_by_channel(channel_id)
        existing_topics = [
            {"id": card.id, "title": card.title, "scope_in": card.scope_in} for card in topic_cards
        ]
        existing_topic_ids = {card.id for card in topic_cards}

        if len(unassigned_docs) <= batch_size:
            return await self._discover_single_batch(
                channel_id,
                unassigned_docs,
                existing_topics,
                existing_topic_ids,
                cross_channel_topics=cross_channel_topics,
            )

        all_assignments: list[TopicAssignment] = []
        all_new_cards: list[TopicCard] = []
        all_unassignable: list[str] = []
        total_tokens = 0
        total_batches = (len(unassigned_docs) + batch_size - 1) // batch_size

        for i in range(0, len(unassigned_docs), batch_size):
            batch_docs = unassigned_docs[i : i + batch_size]
            batch_num = i // batch_size + 1

            logger.info(
                "discover_new_topics batch %d/%d (%d docs, channel=%s)",
                batch_num,
                total_batches,
                len(batch_docs),
                channel_id,
            )

            assignments, new_cards, unassignable, tokens = await self._discover_single_batch(
                channel_id,
                batch_docs,
                existing_topics,
                existing_topic_ids,
                cross_channel_topics=cross_channel_topics,
            )

            all_assignments.extend(assignments)
            all_new_cards.extend(new_cards)
            all_unassignable.extend(unassignable)
            total_tokens += tokens

            for card in new_cards:
                existing_topics.append(
                    {"id": card.id, "title": card.title, "scope_in": card.scope_in}
                )
                existing_topic_ids.add(card.id)

        logger.info(
            "Phase 2 discover: %d batches, %d assigned, %d new topics, "
            "%d unassignable (channel=%s)",
            total_batches,
            len(all_assignments),
            len(all_new_cards),
            len(all_unassignable),
            channel_id,
        )

        return all_assignments, all_new_cards, all_unassignable, total_tokens

    async def _discover_single_batch(
        self,
        channel_id: str,
        batch_docs: list,
        existing_topics: list[dict],
        existing_topic_ids: set[str],
        cross_channel_topics: list[dict] | None = None,
    ) -> tuple[list[TopicAssignment], list[TopicCard], list[str], int]:
        """Run a single LLM discover call for a batch of documents."""
        docs_payload = [
            {
                "source_ref": doc.source_ref,
                "summary": doc.summary or "",
                "topics": doc.topics or [],
                "text_clean": doc.text_clean,
            }
            for doc in batch_docs
        ]

        prompt = build_incremental_discover_prompt(
            existing_topics,
            docs_payload,
            cross_channel_topics=cross_channel_topics,
        )

        max_json_retries = _TOPICIZATION_MAX_JSON_RETRIES
        llm_result: dict | None = None
        tokens_used = 0

        for attempt in range(1, max_json_retries + 1):
            try:
                discover_config = get_prompt_loader().load("incremental_discover")
                discover_sys = (
                    discover_config.get("system", {}).get("prompt")
                    or INCREMENTAL_DISCOVER_SYSTEM_PROMPT
                )
                discover_model = discover_config.get("model", {})

                # BUG-019: append a corrective hint on retries (attempt > 1).
                if attempt > 1:
                    from tg_parser.api.metrics import record_llm_json_parse_retry

                    record_llm_json_parse_retry(stage="topicization_discover")
                llm_response = await self.llm_client.generate_with_usage(
                    prompt=apply_json_retry_hint(prompt, attempt),
                    system_prompt=discover_sys,
                    temperature=discover_model.get("temperature", 0.0),
                    max_tokens=discover_model.get("max_tokens", 8192),
                    response_format={"type": "json_object"},
                )
                tokens_used += llm_response.total_tokens

                # BUG-071 (Fix 1): truncation — split the doc batch and retry
                # each half once (the new cards from the first half are threaded
                # into the second half's context to keep dedup intact). A single
                # oversized doc that can't be split falls back to the existing
                # "mark unassignable" contract — never the 3x re-burn.
                if llm_response.stop_reason == "max_tokens":
                    self._record_truncation("topicization_discover")
                    logger.warning(
                        "topicization_discover_truncated",
                        docs=len(batch_docs),
                    )
                    return await self._discover_after_truncation(
                        channel_id,
                        batch_docs,
                        existing_topics,
                        existing_topic_ids,
                        cross_channel_topics,
                        tokens_used,
                    )

                cleaned = extract_json_from_response(llm_response.text)
                llm_result = _loads_topicization_json_with_repair(
                    cleaned, stage="topicization_discover"
                )
                break
            except json.JSONDecodeError as e:
                if attempt < max_json_retries:
                    logger.warning(
                        "Phase 2 JSON parse error (attempt %d/%d): %s, retrying",
                        attempt,
                        max_json_retries,
                        e,
                    )
                    await asyncio.sleep(settings.llm_json_retry_delay)
                else:
                    logger.error(
                        "Phase 2 JSON parse failed after %d attempts, "
                        "marking batch docs as unassignable",
                        max_json_retries,
                    )
                    return [], [], [doc.source_ref for doc in batch_docs], tokens_used
            except (RuntimeError, ValueError, OSError) as e:
                logger.error("Phase 2 LLM call failed: %s", e, exc_info=True)
                raise

        if llm_result is None:
            return [], [], [doc.source_ref for doc in batch_docs], tokens_used

        llm_assignments: list[TopicAssignment] = []
        for raw_assign in llm_result.get("assignments", []):
            topic_id = raw_assign.get("topic_id", "")
            source_ref = raw_assign.get("source_ref", "")
            confidence = raw_assign.get("confidence", 0.0)
            if topic_id in existing_topic_ids and source_ref:
                llm_assignments.append(
                    TopicAssignment(
                        source_ref=source_ref,
                        topic_id=topic_id,
                        score=min(max(confidence, 0.0), 1.0),
                        method="llm",
                    )
                )

        new_topic_cards: list[TopicCard] = []
        for raw_topic in llm_result.get("new_topics", []):
            try:
                card = self._build_topic_card(
                    raw_topic=raw_topic,
                    channel_id=channel_id,
                    documents=batch_docs,
                )
                if card:
                    card.metadata = card.metadata or {}
                    card.metadata["origin"] = "discovered"
                    card.metadata["discovered_at"] = datetime.now(UTC).isoformat()
                    card.metadata["algorithm"] = "incremental_llm_discover"
                    card.metadata["prompt_name"] = get_incremental_discover_prompt_name()
                    new_topic_cards.append(card)
            except (ValueError, KeyError, AttributeError) as e:
                logger.error("Failed to build discovered topic card: %s", e, exc_info=True)

        unassignable = llm_result.get("unassignable", [])

        logger.info(
            "Phase 2 batch: %d assigned, %d new topics, %d unassignable (channel=%s)",
            len(llm_assignments),
            len(new_topic_cards),
            len(unassignable),
            channel_id,
        )

        return llm_assignments, new_topic_cards, unassignable, tokens_used

    async def _discover_after_truncation(
        self,
        channel_id: str,
        batch_docs: list,
        existing_topics: list[dict],
        existing_topic_ids: set[str],
        cross_channel_topics: list[dict] | None,
        tokens_used: int,
    ) -> tuple[list[TopicAssignment], list[TopicCard], list[str], int]:
        """BUG-071 (Fix 1): recover from a discover ``max_tokens`` truncation.

        Splits the doc batch in half and re-runs each half (threading the first
        half's newly-discovered topics into the second half's existing-topics
        context so dedup is preserved, mirroring ``discover_new_topics``). A
        single doc that still truncates can't be split — it falls back to the
        loop's existing terminal contract (marked unassignable), WITHOUT the 3x
        identical-request token re-burn.
        """
        if len(batch_docs) <= 1:
            logger.error(
                "topicization_discover truncated on a single doc; marking unassignable "
                "(no further shrink possible)"
            )
            return [], [], [doc.source_ref for doc in batch_docs], tokens_used

        mid = len(batch_docs) // 2
        logger.info(
            "topicization_discover_shrink_split",
            left=mid,
            right=len(batch_docs) - mid,
        )
        # Local copies: the first half may discover new topics that must be
        # visible to the second half (dedup), but we must not mutate the
        # caller's lists.
        topics_ctx = list(existing_topics)
        topic_ids_ctx = set(existing_topic_ids)

        a1, c1, u1, t1 = await self._discover_single_batch(
            channel_id,
            batch_docs[:mid],
            topics_ctx,
            topic_ids_ctx,
            cross_channel_topics=cross_channel_topics,
        )
        for card in c1:
            topics_ctx.append({"id": card.id, "title": card.title, "scope_in": card.scope_in})
            topic_ids_ctx.add(card.id)

        a2, c2, u2, t2 = await self._discover_single_batch(
            channel_id,
            batch_docs[mid:],
            topics_ctx,
            topic_ids_ctx,
            cross_channel_topics=cross_channel_topics,
        )

        return a1 + a2, c1 + c2, u1 + u2, tokens_used + t1 + t2
