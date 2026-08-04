"""
Prometheus metrics instrumentation.

Phase 3D: Prometheus-compatible metrics endpoint for monitoring.
"""

from collections.abc import Callable
from typing import Any

import structlog
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info

logger = structlog.get_logger(__name__)

# ============================================================================
# Custom Metrics
# ============================================================================

# Agent metrics
AGENT_TASKS_TOTAL = Counter(
    "tg_parser_agent_tasks_total",
    "Total number of agent tasks",
    ["agent_name", "task_type", "status"],
)

AGENT_TASK_DURATION_SECONDS = Histogram(
    "tg_parser_agent_task_duration_seconds",
    "Duration of agent tasks in seconds",
    ["agent_name", "task_type"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

AGENT_ACTIVE_COUNT = Gauge(
    "tg_parser_agents_active",
    "Number of active agents",
    ["agent_type"],
)

# Processing metrics
MESSAGES_PROCESSED_TOTAL = Counter(
    "tg_parser_messages_processed_total",
    "Total number of messages processed",
    ["channel_id", "status"],
)

TOPICS_CREATED_TOTAL = Counter(
    "tg_parser_topics_created_total",
    "Total number of topics created",
    ["channel_id"],
)

# F5-A Phase 3: Deduplication metric
DEDUP_DUPLICATES_DETECTED = Counter(
    "tg_dedup_duplicates_detected_total",
    "Total duplicate messages detected and skipped by content-hash (F5-A Phase 3)",
    ["channel_id"],
)

# S3 (O-2 / F-01): pre-LLM deduplication metric.
# Incremented when the processing pipeline detects an exact repost/forward by
# hashing the RAW Telegram text BEFORE any LLM call, so the duplicate is
# materialised as a provenance row WITHOUT paying for a processing call. Kept
# strictly separate from DEDUP_DUPLICATES_DETECTED (post-LLM, over text_clean)
# so the two savings can be measured independently against the S0 baseline.
PRE_LLM_DEDUP_HITS = Counter(
    "tg_dedup_pre_llm_hits_total",
    "Total exact reposts deduplicated BEFORE the LLM call by raw-text hash (S3 / O-2)",
    ["channel_id"],
)

# F5-B Phase 0: near-duplicate observation-only counter (ADR-0016).
# Incremented when a freshly-embedded ProcessedDocument has a cosine
# similarity >= the observe threshold against a sliding window of recent
# embeddings on either axis. ``dimension`` ∈ {intra, cross}: intra = same
# channel, cross = sibling channels of the same deployment. Phase 0 is
# OBSERVATION-ONLY — nothing is hidden, mutated, or deleted on either axis;
# the counter only measures the real near-duplicate rate so Phase 1 (actual
# dedup) can be gated on data instead of guesses (ADR-0006 #6).
NEAR_DUPLICATES_DETECTED = Counter(
    "tg_dedup_near_duplicates_detected_total",
    "Near-duplicate ProcessedDocuments observed post-embedding (F5-B Phase 0, observation-only).",
    ["channel_id", "method", "dimension"],
    # method ∈ {embedding_cosine}; dimension ∈ {intra, cross}.
)

NEAR_DUPLICATE_SIMILARITY = Histogram(
    "tg_dedup_near_duplicate_similarity",
    "Cosine similarity distribution of observed near-duplicate pairs (F5-B Phase 0).",
    ["dimension"],
    buckets=(0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 1.0),
)

# LLM metrics
LLM_REQUESTS_TOTAL = Counter(
    "tg_parser_llm_requests_total",
    "Total number of LLM requests",
    ["provider", "model", "status"],
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "tg_parser_llm_request_duration_seconds",
    "Duration of LLM requests in seconds",
    ["provider", "model"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
)

LLM_TOKENS_TOTAL = Counter(
    "tg_parser_llm_tokens_total",
    "Total number of LLM tokens used",
    ["provider", "model", "token_type"],  # token_type: prompt, completion
)

# BUG-084 — embedding request outcomes, classified by error.code so a transient
# rate-limit is distinguishable from a terminal quota exhaustion and neither is
# conflated with DB-pool / LLM-processing errors. Classified at the two embedding
# consumer call sites: background_scheduler (background topic/incremental embedding)
# and retrieval_service (the live semantic/hybrid RAG query embedding).
#
# outcome ∈ {ok, rate_limited, quota_exhausted, error}:
#   * ok             — embedding request(s) succeeded.
#   * rate_limited   — transient rate_limit_exceeded / 5xx exhausted the retry
#                      budget (EmbeddingRateLimitError). Self-clears; RAG degrades.
#   * quota_exhausted— terminal insufficient_quota (EmbeddingQuotaError). Billing/
#                      tier action required; code cannot restore embeddings.
#   * error          — any other failure (network, unexpected exception).
# stage ∈ {background_message, background_topic, rag_query} — fixed cardinality.
EMBEDDING_REQUESTS_TOTAL = Counter(
    "tg_embedding_requests_total",
    "Embedding API request outcomes classified by error.code (BUG-084).",
    ["outcome", "stage"],
)

# BUG-071 (Fix 3) — paid-but-wasted ``max_tokens`` truncations. ``record_llm_request``
# folds a charged-but-truncated reply into ``status="success"`` (it WAS an HTTP 200),
# so this class of wasted spend was invisible. A ``max_tokens`` stop_reason means the
# output hit its cap and the JSON body is cut off mid-token — repair_json cannot fix
# it, and historically the call was retried 3x (each a full charged Sonnet call) and
# discarded. Incremented at the topicization sites when a truncation is detected so the
# rate is alertable. ``(provider, model, stage)`` cardinality is bounded by the small
# fixed set of providers/models/stages (mirrors LLM_REQUESTS_TOTAL + the stages of
# LLM_JSON_PARSE_RETRY_TOTAL).
LLM_TRUNCATION_TOTAL = Counter(
    "tg_parser_llm_truncation_total",
    "LLM responses truncated at the output token cap (stop_reason=max_tokens) — charged but unusable.",
    ["provider", "model", "stage"],
    # stage ∈ {topicization_generate, topicization_merge, topicization_discover}.
)

# BUG-071 (post-fix observability) — direct, first-class counter for topicization
# failed batches. ``failed_batches`` was previously only on the
# ``run_topicization`` return dict / CLI exit code (BUG-018) / structured logs, so
# the "failed-batch ratio high" signal could only be proxied in Prometheus (burn
# rate + flat topics_created). This counter makes it a direct series, incremented
# at the SAME sites where ``TopicizationPipelineImpl.failed_batches`` is counted in
# ``topicize_channel`` so the metric and the log/CLI number stay consistent (no
# double-count). It is BROADER than tg_parser_llm_truncation_total: it counts BOTH
# truncation-drops (TopicizationBatchTruncatedError — so it corroborates the
# truncation counter) AND genuine non-truncation batch failures (RuntimeError /
# parse-exhaustion / billing / etc.) that the truncation counter does NOT cover.
#
# Labels (stage, channel_id):
# * ``stage`` mirrors the truncation-counter stages for symmetry. Emitted today:
#   ``topicization_generate`` (batch generate failures, all paths),
#   ``topicization_merge`` (BUG-076 chunked path: billing/timeout/malformed-merge
#   halts at the within-chunk merge) and ``topicization_commit`` (BUG-077: the
#   atomic chunk commit raised). The LEGACY monolithic ``_merge_topics`` still
#   falls back to "return unmerged" and ``_discover_single_batch`` marks docs
#   "unassignable" — neither is a counted failed batch, so they do NOT emit here.
# * ``channel_id`` is included (mirrors tg_parser_topics_created_total /
#   tg_parser_messages_processed_total, whose channel_id cardinality is already
#   accepted as bounded per tenant deployment). failed_batches is inherently a
#   per-channel-run quantity, and a per-channel breakdown answers the operator's
#   first question ("which channel is burning failed batches?"). Cardinality is
#   bounded by (#channels × #emitted-stages) ≈ #channels.
TOPICIZATION_FAILED_BATCHES_TOTAL = Counter(
    "tg_parser_topicization_failed_batches_total",
    "Topicization batches that produced 0 usable topics (dropped/errored) — mirrors "
    "TopicizationPipelineImpl.failed_batches (BUG-018/BUG-071).",
    ["stage", "channel_id"],
    # stage ∈ {topicization_generate, topicization_merge, topicization_discover};
    # only topicization_generate is emitted today (see note above).
)

# BUG-075 (R1 hardening — token-burn audit): persistent failure of the
# best-effort ``discover_attempted`` marker write. The convergent reconciliation
# hook marks every doc that consumed a Phase-2 discover call and stayed
# uncovered so it is fed to discover AT MOST ONCE. The marker write swallows
# errors (a hiccup must never mask the caller's outcome), but if it FAILS
# PERSISTENTLY while the discover LLM call SUCCEEDS, the doc stays unmarked → it
# is re-fed to Phase-2 on the next tick → bounded re-burn (capped by
# ``topicization_reconcile_max_docs`` + random sampling, so NOT a storm, but
# previously only visible at ``debug``). This counter makes that quiet
# degradation alertable. ``channel_id`` mirrors the cardinality choice of
# tg_parser_topicization_failed_batches_total / tg_parser_topics_created_total
# (bounded per tenant deployment) and answers "which channel can't persist its
# markers?".
TOPICIZATION_DISCOVER_ATTEMPTED_MARK_FAILED_TOTAL = Counter(
    "tg_parser_topicization_discover_attempted_mark_failed_total",
    "Best-effort discover_attempted marker writes that failed (BUG-075 R1). A "
    "persistent non-zero rate means docs are re-fed to Phase-2 discover → bounded "
    "token re-burn (not abandonment, not a storm).",
    ["channel_id"],
)

# BUG-075 (post-refill watch) — docs actually fed to Phase-2 LLM discover by the
# STANDING reconciliation hook specifically (the ``reconcile_only=True`` path,
# NOT the normal tick-local new-docs incremental path). The reconcile hook feeds
# ``uncovered − discover_attempted`` candidates to a cheap incremental run; the
# subset that survive Phase-1 keyword assignment (``unassigned_refs``) are the
# docs that consume a Phase-2 discover LLM call. Counting them per channel makes
# reconcile-driven discover spend directly observable.
#
# Steady-state behaviour (the convergence invariant): each uncovered doc earns a
# ``discover_attempted`` marker after a completed Phase-2, so it is fed to
# discover AT MOST ONCE — once the backlog drains the candidate set empties and
# this counter's rate settles to ~0. A TRANSIENT non-zero rate (backlog-drain
# after a refill / a newly-processed batch) is LEGITIMATE; the red flag is a
# SUSTAINED non-zero rate, which means reconcile keeps issuing discover calls
# that never stop (non-convergence / re-burn). ``channel_id`` mirrors the
# cardinality choice of the sibling BUG-075 R1 counter / failed_batches /
# topics_created (bounded per tenant deployment) and names the offending channel.
TOPICIZATION_RECONCILE_DISCOVER_DOCS_TOTAL = Counter(
    "tg_parser_topicization_reconcile_discover_docs_total",
    "Processed-but-uncovered docs fed to Phase-2 discover by the BUG-075 standing "
    "reconciliation hook (reconcile_only path). Transient backlog-drain is legitimate; "
    "a sustained non-zero rate means reconcile is not converging (re-burn).",
    ["channel_id"],
)

# BUG-076: full-topicization resumable-run observability. All four series are
# emitted only on the chunked/resumable full path (topicization_full_resume_enabled
# =True); they stay flat/absent on the legacy monolithic path (fix ships dark).
#
# tokens_total closes the TopicizationBurnNoProgress blind spot together with the
# per-chunk record_topic_created wiring: a productive full run now shows BOTH
# tokens climbing AND topics_created rising, so the alert no longer false-positives.
TOPICIZATION_FULL_RUN_TOKENS_TOTAL = Counter(
    "tg_parser_topicization_full_run_tokens_total",
    "Cumulative input+output tokens spent by resumable full topicization, per "
    "channel (BUG-076). Feeds the budget guard + cost dashboards.",
    ["channel_id"],
)

# Live progress gauge: kind ∈ {done, total}. done/total < 1 while a run is still
# draining chunks over ticks; done == total just before the checkpoint clears.
TOPICIZATION_FULL_RUN_CHUNKS = Gauge(
    "tg_parser_topicization_full_run_chunks",
    "Resumable full-topicization chunk progress (kind=done|total) per channel (BUG-076).",
    ["channel_id", "kind"],
)

# Clean per-invocation token-budget halts (benign, watchable). A sustained rate
# with no completion = a channel that keeps halting and never finishes.
TOPICIZATION_FULL_RUN_BUDGET_HALT_TOTAL = Counter(
    "tg_parser_topicization_full_run_budget_halt_total",
    "Clean per-invocation token-budget halts of resumable full topicization "
    "(BUG-076). Benign — the run is durable + resumed next tick.",
    ["channel_id"],
)

# Resume-driver invocations (the scheduler picking up a live checkpoint). A
# sustained rate with no completion signals a channel that never converges.
TOPICIZATION_FULL_RUN_RESUME_TOTAL = Counter(
    "tg_parser_topicization_full_run_resume_total",
    "Resume-driver invocations that continued a live full-topicization checkpoint (BUG-076).",
    ["channel_id"],
)

# BUG-077 (F9): non-advancing chunk halts. tokens_total fires only POST-commit,
# so the F1 drip (generate+merge spend that never commits) was invisible; this
# counter makes every non-advancing halt first-class. ``reason`` is a small
# bounded set: merge_halt (billing/timeout at the within-chunk merge),
# malformed_merge (TypeError/AttributeError from a malformed merge reply — F2),
# empty_after_failure (0 cards with >=1 failed batch), commit_failed (the
# atomic chunk commit raised, e.g. a DB constraint violation).
TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL = Counter(
    "tg_parser_topicization_full_run_chunk_failed_total",
    "Resumable full-topicization chunks that halted WITHOUT advancing the "
    "checkpoint (BUG-077 F9). Sustained non-zero = the F1 drip signature.",
    ["channel_id", "reason"],
)

# BUG-077 (F1): ticks on which the no-progress circuit-breaker held a resume
# off (skipped_reason="noprogress_circuit_open"). A sustained rate means a
# channel's full run is stuck on a deterministically-failing chunk and is being
# throttled to one probe per cooldown window — investigate the chunk failure.
TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL = Counter(
    "tg_parser_topicization_full_run_noprogress_skip_total",
    "Full-topicization resumes skipped by the open no-progress circuit-breaker (BUG-077 F1).",
    ["channel_id"],
)

# Database metrics
DB_CONNECTIONS_ACTIVE = Gauge(
    "tg_parser_db_connections_active",
    "Number of active database connections",
    ["database"],
)

# Job metrics
JOBS_TOTAL = Counter(
    "tg_parser_jobs_total",
    "Total number of jobs",
    ["status"],  # pending, running, completed, failed
)

JOBS_ACTIVE = Gauge(
    "tg_parser_jobs_active",
    "Number of currently active jobs",
)

# Scheduler metrics
SCHEDULER_TASKS_TOTAL = Counter(
    "tg_parser_scheduler_tasks_total",
    "Total number of scheduled task executions",
    ["task_name", "status"],
)

# B1 / BUG-085 — per-source outcomes of each completed incremental_pipeline tick.
# Complements SCHEDULER_TASKS_TOTAL (which only sees "job returned without raise"
# → status="success") so an all-sources-failing outage is alertable. Emitted at
# the completion-log site in run_incremental_for_all_sources; idle ticks (no
# active sources) intentionally do NOT emit.
#
# outcome ∈ {succeeded, failed, degraded, lock_contended, skipped}:
#   * succeeded      — source completed cleanly.
#   * failed         — HARD failures ONLY (excludes degraded). Aggregate
#                      sources_failed - sources_degraded at the emit site.
#   * degraded       — benign (per-post MsgIdInvalidError / temporary billing
#                      block). MUST NOT trip IncrementalIngestionAllSourcesFailing.
#   * lock_contended — sibling held the Telethon session past the wait budget.
#   * skipped        — per-source advisory lock already held (concurrent tick).
INCREMENTAL_PIPELINE_SOURCES_TOTAL = Counter(
    "tg_parser_incremental_pipeline_sources_total",
    "Per-source outcomes of each completed incremental_pipeline tick (B1). "
    "outcome ∈ {succeeded, failed, degraded, lock_contended, skipped}. "
    "'failed' is HARD failures ONLY (excludes degraded); 'degraded' is benign "
    "(per-post MsgIdInvalidError / temporary billing block) and must NOT trip "
    "the all-sources-failing alert.",
    ["outcome"],
)

ANTHROPIC_BILLING_BLOCK_TOTAL = Counter(
    "tg_parser_anthropic_billing_block_total",
    "Total Anthropic billing blocks (invalid_request_error credit balance)",
    ["stage"],
)

# BUG-019 — LLM JSON-parse retries (with corrective-hint prompt). Incremented
# once per hinted retry of a malformed-JSON LLM response, labelled by the
# pipeline stage that owns the retry loop.
LLM_JSON_PARSE_RETRY_TOTAL = Counter(
    "tg_parser_llm_json_parse_retry_total",
    "LLM JSON-parse retries that appended a corrective hint to the prompt.",
    ["stage"],
    # stage ∈ {processing, topicization_generate, topicization_merge,
    #          topicization_discover}.
)

# BUG-020 — Anthropic retryable 5xx responses (incl. 520). Incremented on each
# retryable 5xx response and once more on the terminal (retries-exhausted)
# failure, labelled by HTTP status code.
ANTHROPIC_API_5XX_TOTAL = Counter(
    "tg_parser_anthropic_api_5xx_total",
    "Anthropic API retryable 5xx responses (per attempt + terminal failure).",
    ["status"],
)

# BUG-006 (Session E) — bot Gemini agent empty-parts monitoring.
# Tracks the rate at which Gemini returns HTTP 200 with empty
# ``candidates[].content.parts``. Pre-fix this was deterministic on
# tool-disambiguation queries ("Покажи LLM конфиг" → MAX_TOKENS via
# thinking-budget exhaustion). Post-fix the rate must stay below ~1%
# of total bot-Gemini calls; sustained spikes indicate either (a)
# Option A insufficient and Option B/C follow-up needed, or (b) new
# regression in TOOL_DECLARATIONS / system prompt size.
BOT_GEMINI_EMPTY_PARTS_TOTAL = Counter(
    "tg_bot_gemini_empty_parts_total",
    "Bot Gemini API returned HTTP 200 with empty content.parts (BUG-006).",
    ["model", "finish_reason"],
    # ``model`` ∈ configured ``BOT_GEMINI_MODEL`` value; ``finish_reason`` ∈
    # {STOP, MAX_TOKENS, MALFORMED_FUNCTION_CALL, RECITATION, SAFETY,
    #  OTHER, none, no_candidates, blocked}. ``none`` = empty parts with
    # no finish_reason emitted (HG-5 / HG-7). ``no_candidates`` = the
    # outer ``candidates=[]`` branch; ``blocked`` = ``promptFeedback.blockReason``
    # was set.
)

# F5-C Evolving Topic Summaries (a4b5c6d7e8f9)
RESUMMARIZE_TOTAL = Counter(
    "tg_resummarize_total",
    "Total F5-C re-summarize attempts (one per topic, per scheduler tick or force).",
    [
        "channel_id",
        "outcome",
        "trigger",
    ],
    # outcome ∈ {ok, locked, no_card, no_bundle, empty_scope, llm_error,
    # db_error, refusal, refusal_cooldown, version_raced, unknown}.
    # channel_id is the topic's primary source channel (card.sources[0]) on
    # card-bearing paths, with a "-" fallback on
    # the early paths where the card is unknown (locked / no_card / no_bundle)
    # — F5-C P2 / #15 item #10 wired the previously-reserved label through
    # record_resummarize_outcome for per-channel cost visibility. Run-level
    # cap counters (cap_duration / cap_tokens) are NOT topic outcomes — see
    # run_for_channel breakdown.
    #
    # trigger ∈ {counter, age, "-"} (Wave 2 observability) classifies WHY the
    # topic was selected by the OR predicate in list_resummarize_candidates:
    # "counter" = new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N,
    # "age" = selected only by the time-based RESUMMARIZE_MAX_AGE_DAYS branch,
    # "-" = path where the card is unknown / trigger can't be determined
    # (locked / no_card / no_bundle, or a direct force_resummarize that
    # satisfied neither predicate). Bounded at ~3 values — cardinality safe.
)

RESUMMARIZE_TOKENS_TOTAL = Counter(
    "tg_resummarize_tokens_total",
    "Total LLM tokens consumed by F5-C re-summarize.",
    # channel_id (Wave 2 observability) is the topic's primary source channel
    # (card.sources[0]) with a "-" fallback, mirroring tg_resummarize_total —
    # enables per-channel token-cost breakdown. token_type: prompt | completion.
    ["channel_id", "provider", "model", "token_type"],
)

RESUMMARIZE_DURATION_SECONDS = Histogram(
    "tg_resummarize_duration_seconds",
    "End-to-end duration of a single F5-C re-summarize attempt in seconds.",
    ["model"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)


# F11 Topic Watchlist (TD-02 — post-Living-KB Phase 1)
WATCHLIST_MATCHES = Counter(
    "tg_watchlist_matches_total",
    "Watchlist (interest, document) candidate fates produced by WatchlistService.check_interests.",
    ["result"],
    # result ∈ {delivered, filtered_keywords, filtered_threshold}.
    # ``delivered`` = score >= interest.threshold and persisted as WatchMatch
    # (push delivery itself is tracked separately via WATCHLIST_DELIVERY).
    # ``filtered_keywords`` = exclude_keyword filter zeroed the score.
    # ``filtered_threshold`` = below interest.threshold and not excluded.
    # No interest_id label — bounded by current operator count, but unbounded
    # over time (see TD-02 cardinality note in metrics.py history). Use the
    # ``tg_watchlist_score`` histogram for distribution insight instead.
)

WATCHLIST_SCORE = Histogram(
    "tg_watchlist_score",
    "Distribution of hybrid watchlist combined scores in [0, 1].",
    buckets=(0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

WATCHLIST_DELIVERY = Counter(
    "tg_watchlist_delivery_total",
    "Watchlist push-notification outcomes per (interest, tick) group.",
    ["outcome"],
    # outcome ∈ {sent, blocked, error}.
    # ``sent`` = bot.send_message succeeded for the group.
    # ``blocked`` = permanent failure detected (chat not found / bot blocked /
    # user deactivated / forbidden) — interest is soft-deleted by the service
    # to stop retry storms; matches themselves are preserved.
    # ``error`` = transient failure (rate-limit, network); group is not retried
    # in this tick but will be retried on the next match for the same interest.
)

WATCHLIST_ACTIVE_INTERESTS = Gauge(
    "tg_watchlist_active_interests",
    "Currently active (is_active=true) watchlist interests across all tenants.",
)

# D1 / Wave-2 T6 — keyword-only / semantic-unavailable observability counter.
# Incremented inside compute_watch_score whenever ``semantic_available`` is
# False, i.e. the combined score degrades to pure keyword (combined = keyword,
# graceful keyword-only by ADR-0010/0011) WITHOUT any semantic signal. This is
# the precision blind-spot signal: a keyword-only row can take the threshold at
# combined=1.0 with semantic=0.0. The dedicated counter is deliberately chosen
# over relabelling the ``tg_watchlist_score`` histogram (PLAN_WAVE2 §4a option
# B): a per-(score-bucket × semantic_available) relabel inflates histogram
# cardinality and forces a dashboard migration, whereas this low-cardinality
# counter is directly gateable on ``reason`` for the T6 alert.
#
# reason ∈ {interest_no_embedding, doc_no_embedding} — fixed cardinality at 2.
# Precedence when BOTH are missing: interest_no_embedding (see helper docstring
# and the call site in watchlist_service.compute_watch_score).
WATCHLIST_SEMANTIC_UNAVAILABLE = Counter(
    "tg_watchlist_semantic_unavailable_total",
    "Watchlist scoring fell back to keyword-only because no semantic signal was available.",
    ["reason"],
)

# Wave 1 step 4 — ADR 0008 channel digest publish outcomes
DIGEST_CHANNEL_PUBLISH = Counter(
    "tg_digest_channel_publish_total",
    "Digest publish attempts to channel targets (kind=channel only).",
    ["result"],
    # result ∈ {success, permission_denied, failed}.
)


def record_digest_channel_publish(*, result: str) -> None:
    """Increment ``tg_digest_channel_publish_total`` for channel-target delivery."""
    DIGEST_CHANNEL_PUBLISH.labels(result=result).inc()


def record_watchlist_match(*, result: str, score: float) -> None:
    """Record one (interest, document) candidate fate plus its combined score.

    ``result`` is one of {``delivered``, ``filtered_keywords``,
    ``filtered_threshold``}. ``score`` is the combined hybrid score in [0, 1]
    and is observed in :data:`WATCHLIST_SCORE` regardless of outcome — this is
    the calibration signal for tuning the F11 default threshold (currently 0.6).

    Called from :meth:`tg_parser.services.watchlist_service.WatchlistService.check_interests`.
    """
    WATCHLIST_MATCHES.labels(result=result).inc()
    if score < 0.0:
        score = 0.0
    elif score > 1.0:
        score = 1.0
    WATCHLIST_SCORE.observe(score)


def record_watchlist_delivery(*, outcome: str) -> None:
    """Record one push-notification outcome.

    ``outcome`` is one of {``sent``, ``blocked``, ``error``}. Called from
    :meth:`tg_parser.services.watchlist_service.WatchlistService.notify`.
    """
    WATCHLIST_DELIVERY.labels(outcome=outcome).inc()


def record_watchlist_semantic_unavailable(*, reason: str) -> None:
    """Record one keyword-only / semantic-unavailable watchlist scoring event.

    ``reason`` is one of {``interest_no_embedding``, ``doc_no_embedding``}:

    * ``interest_no_embedding`` — the interest has no embedding (it has not
      been backfilled yet, or embedding failed). Takes precedence when BOTH
      the interest and the document lack an embedding.
    * ``doc_no_embedding`` — the interest is embedded but the candidate
      document has no embedding.

    Called from
    :func:`tg_parser.services.watchlist_service.compute_watch_score` in the
    ``semantic_available=False`` branch. This is a pure observability
    side-effect — it does NOT change the combined score (graceful keyword-only
    remains by-design per ADR-0010/0011); it only measures how often the score
    blend silently degrades to keyword-only so the T6 alert can gate on it.
    """
    WATCHLIST_SEMANTIC_UNAVAILABLE.labels(reason=reason).inc()


def set_watchlist_active(count: int) -> None:
    """Set the gauge of currently active watchlist interests to ``count``.

    Refreshed periodically from
    :meth:`tg_parser.services.watchlist_service.WatchlistService.check_interests`
    (once per scheduler tick) so the value tracks soft-deletes / new
    subscriptions without a dedicated background job.
    """
    WATCHLIST_ACTIVE_INTERESTS.set(max(count, 0))


def record_resummarize_outcome(
    *,
    topic_id: str,
    status: str,
    channel_id: str = "-",
    trigger: str = "-",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_s: float = 0.0,
    model: str = "",
) -> None:
    """Record a single F5-C re-summarize attempt.

    ``topic_id`` is currently logged via structlog elsewhere; we keep it
    in the signature so the call sites stay self-documenting.

    ``channel_id`` (F5-C P2 / #15 item #10) is the topic's primary source
    channel (``card.sources[0]``) on paths where the card is available, and
    falls back to ``"-"`` on the early paths (``locked`` / ``no_card`` /
    ``no_bundle``) where the channel is unknown. Cardinality stays bounded by
    the fixed set of active channels (plus the ``"-"`` fallback), so the
    per-channel cost breakdown is safe to enable (ADR-0006 #6). The same
    ``channel_id`` is threaded onto ``tg_resummarize_tokens_total`` (Wave 2)
    for the per-channel token-cost breakdown.

    ``trigger`` (Wave 2 observability) ∈ {``counter``, ``age``, ``"-"``}
    classifies why the topic was selected: ``counter`` when the new-items
    counter crossed ``RESUMMARIZE_TRIGGER_N``, ``age`` when only the
    time-based ``RESUMMARIZE_MAX_AGE_DAYS`` predicate matched, and ``"-"`` on
    paths where it can't be determined (card unknown). Empty values normalise
    to ``"-"`` so unknown paths never create unbounded series.
    """
    RESUMMARIZE_TOTAL.labels(
        channel_id=channel_id or "-",
        outcome=status,
        trigger=trigger or "-",
    ).inc()
    if status == "ok" and model:
        if input_tokens:
            RESUMMARIZE_TOKENS_TOTAL.labels(
                channel_id=channel_id or "-",
                provider=model.split("/", 1)[0],
                model=model.split("/", 1)[-1],
                token_type="prompt",
            ).inc(input_tokens)
        if output_tokens:
            RESUMMARIZE_TOKENS_TOTAL.labels(
                channel_id=channel_id or "-",
                provider=model.split("/", 1)[0],
                model=model.split("/", 1)[-1],
                token_type="completion",
            ).inc(output_tokens)
        RESUMMARIZE_DURATION_SECONDS.labels(model=model).observe(duration_s or 0.0)


# ============================================================================
# Custom Metric Functions for Instrumentator
# ============================================================================


def agent_metrics() -> Callable[[Info], None]:
    """
    Custom metric function for agent-related metrics.

    This is called per-request by the instrumentator.
    """

    def instrumentation(info: Info) -> None:
        # We don't need per-request agent metrics here
        # Agent metrics are updated by the agents themselves
        pass

    return instrumentation


# ============================================================================
# Instrumentator Setup
# ============================================================================

# Global instrumentator instance to avoid duplicate registration
_instrumentator: Instrumentator | None = None
_instrumented_apps: set[int] = set()  # Track which apps have been instrumented


def create_instrumentator(registry: CollectorRegistry | None = None) -> Instrumentator:
    """
    Create and configure Prometheus instrumentator.

    Returns singleton Instrumentator instance to avoid duplicate metric registration.

    Args:
        registry: Collector registry to build on. Default (``None``) is the
            process-global one, which is what the singleton above guards. Passing
            an explicit registry bypasses the singleton and returns a fresh
            instrumentator: tests use this to exercise THIS configuration —
            rather than a hand-copied replica of it — in isolation.

    Returns:
        Configured Instrumentator instance
    """
    global _instrumentator

    # Return existing instance to avoid duplicate metric registration
    if registry is None and _instrumentator is not None:
        return _instrumentator

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,  # We control this via settings.metrics_enabled
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/health", "/docs", "/redoc", "/openapi.json"],
        inprogress_name="tg_parser_http_requests_inprogress",
        inprogress_labels=True,
        registry=registry,
    )

    # Add default metrics.
    #
    # NO metric_subsystem="http": the library's base names already start with
    # ``http_`` (http_requests_total, http_request_duration_seconds, ...), so a
    # subsystem would expose them as tg_parser_http_http_*. The alert rule
    # (docker/prometheus/alerts.yml::HighHTTPErrorRate), the Grafana dashboards
    # and the hand-written ``inprogress_name`` above all expect the single
    # tg_parser_http_ prefix.
    #
    # The latency/request_size/response_size metric functions are NOT added
    # separately: default() already registers those exact series, and the
    # library silently drops a duplicate registration (returns None, which
    # Instrumentator.add() ignores), so their settings never took effect. The
    # latency buckets are therefore configured here. The range reaches 60s to
    # match LLM_REQUEST_DURATION_SECONDS — RAG endpoints inherit multi-second
    # LLM latency, and a 10s ceiling makes histogram_quantile(0.99) return +Inf.
    default_kwargs: dict[str, Any] = {
        "metric_namespace": "tg_parser",
        "latency_lowr_buckets": (
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
            30.0,
            60.0,
        ),
    }
    # metrics.default() defaults to the global registry object rather than to
    # None, so the kwarg is only passed when a registry was requested.
    if registry is not None:
        default_kwargs["registry"] = registry

    instrumentator.add(metrics.default(**default_kwargs))

    # Add custom agent metrics
    instrumentator.add(agent_metrics())

    if registry is None:
        _instrumentator = instrumentator
    logger.info("Prometheus instrumentator configured")

    return instrumentator


# ============================================================================
# Metric Helper Functions
# ============================================================================


def record_agent_task(
    agent_name: str,
    task_type: str,
    success: bool,
    duration_seconds: float,
) -> None:
    """
    Record an agent task execution.

    Args:
        agent_name: Name of the agent
        task_type: Type of task
        success: Whether task succeeded
        duration_seconds: Task duration in seconds
    """
    status = "success" if success else "error"
    AGENT_TASKS_TOTAL.labels(
        agent_name=agent_name,
        task_type=task_type,
        status=status,
    ).inc()

    AGENT_TASK_DURATION_SECONDS.labels(
        agent_name=agent_name,
        task_type=task_type,
    ).observe(duration_seconds)


def record_message_processed(channel_id: str, success: bool) -> None:
    """
    Record a message processing event.

    Args:
        channel_id: Channel identifier
        success: Whether processing succeeded
    """
    status = "success" if success else "error"
    MESSAGES_PROCESSED_TOTAL.labels(
        channel_id=channel_id,
        status=status,
    ).inc()


def record_dedup_duplicate_detected(*, channel_id: str) -> None:
    """F5-A Phase 3: increment the dedup counter for ``channel_id``.

    Called when the processing pipeline detects an exact-content duplicate
    and skips the upsert. ``channel_id`` is expected to be bounded per
    tenant deployment (no unbounded cardinality risk).
    """
    DEDUP_DUPLICATES_DETECTED.labels(channel_id=channel_id).inc()


def record_pre_llm_dedup_hit(*, channel_id: str) -> None:
    """S3 (O-2): increment the pre-LLM dedup counter for ``channel_id``.

    Called when the pipeline detects an exact repost by the RAW-text hash before
    the LLM call and materialises a provenance row instead of paying for a
    processing call. Distinct from :func:`record_dedup_duplicate_detected`
    (post-LLM) so the two effects are measured separately.
    """
    PRE_LLM_DEDUP_HITS.labels(channel_id=channel_id).inc()


def record_near_duplicate_observed(
    *,
    channel_id: str,
    dimension: str,
    similarity: float,
    method: str = "embedding_cosine",
) -> None:
    """F5-B Phase 0: record one observed near-duplicate pair (ADR-0016).

    ``dimension`` ∈ {``intra``, ``cross``}. ``similarity`` is the cosine
    similarity in [0, 1]; it is clamped before being observed in the
    histogram so out-of-range floats never corrupt the buckets. This is
    OBSERVATION-ONLY — the caller does not hide or mutate any document.
    """
    NEAR_DUPLICATES_DETECTED.labels(
        channel_id=channel_id,
        method=method,
        dimension=dimension,
    ).inc()
    clamped = similarity
    if clamped < 0.0:
        clamped = 0.0
    elif clamped > 1.0:
        clamped = 1.0
    NEAR_DUPLICATE_SIMILARITY.labels(dimension=dimension).observe(clamped)


def record_topic_created(channel_id: str) -> None:
    """
    Record a topic creation event.

    Args:
        channel_id: Channel identifier
    """
    TOPICS_CREATED_TOTAL.labels(channel_id=channel_id).inc()


def record_llm_request(
    provider: str,
    model: str,
    success: bool,
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """
    Record an LLM request.

    Args:
        provider: LLM provider name
        model: Model name
        success: Whether request succeeded
        duration_seconds: Request duration in seconds
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
    """
    status = "success" if success else "error"
    LLM_REQUESTS_TOTAL.labels(
        provider=provider,
        model=model,
        status=status,
    ).inc()

    LLM_REQUEST_DURATION_SECONDS.labels(
        provider=provider,
        model=model,
    ).observe(duration_seconds)

    if prompt_tokens > 0:
        LLM_TOKENS_TOTAL.labels(
            provider=provider,
            model=model,
            token_type="prompt",
        ).inc(prompt_tokens)

    if completion_tokens > 0:
        LLM_TOKENS_TOTAL.labels(
            provider=provider,
            model=model,
            token_type="completion",
        ).inc(completion_tokens)


def record_embedding_outcome(*, outcome: str, stage: str) -> None:
    """Record one embedding request outcome (BUG-084).

    ``outcome`` ∈ {``ok``, ``rate_limited``, ``quota_exhausted``, ``error``};
    ``stage`` ∈ {``background_message``, ``background_topic``, ``rag_query``}.
    Classified at the embedding consumer call sites (background_scheduler +
    retrieval_service) so a transient rate-limit (``rate_limited``) is kept
    distinct from a terminal quota exhaustion (``quota_exhausted``) and from
    generic failures (``error``) — mirrors the BUG-082 ``db_error`` pattern.
    Empty values normalise so the labelset stays bounded.
    """
    EMBEDDING_REQUESTS_TOTAL.labels(
        outcome=outcome or "error",
        stage=stage or "unknown",
    ).inc()


def update_active_agents(agent_type: str, count: int) -> None:
    """
    Update the count of active agents.

    Args:
        agent_type: Type of agent
        count: Number of active agents
    """
    AGENT_ACTIVE_COUNT.labels(agent_type=agent_type).set(count)


def record_job_status(status: str) -> None:
    """
    Record a job status change.

    Args:
        status: Job status (pending, running, completed, failed)
    """
    JOBS_TOTAL.labels(status=status).inc()


def update_active_jobs(count: int) -> None:
    """
    Update the count of active jobs.

    Args:
        count: Number of active jobs
    """
    JOBS_ACTIVE.set(count)


def record_scheduler_task(task_name: str, success: bool) -> None:
    """
    Record a scheduler task execution.

    Args:
        task_name: Name of the scheduled task
        success: Whether task succeeded
    """
    status = "success" if success else "error"
    SCHEDULER_TASKS_TOTAL.labels(
        task_name=task_name,
        status=status,
    ).inc()


def record_incremental_tick_outcomes(
    *,
    succeeded: int,
    failed: int,
    degraded: int,
    lock_contended: int,
    skipped: int = 0,
) -> None:
    """Record ONE completed incremental_pipeline tick's aggregate per-source outcomes (B1).

    ``failed`` MUST be HARD failures only (already net of ``degraded``). Every
    outcome is emitted every tick (``.inc(0)`` when zero) so the series stays
    present and the alert's ``== 0`` term on the succeeded series is never an
    empty vector during an all-sources-failing outage.
    """
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="succeeded").inc(max(succeeded, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="failed").inc(max(failed, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="degraded").inc(max(degraded, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="lock_contended").inc(max(lock_contended, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="skipped").inc(max(skipped, 0))


def record_llm_json_parse_retry(*, stage: str) -> None:
    """Increment ``tg_parser_llm_json_parse_retry_total`` for one hinted retry.

    ``stage`` ∈ {``processing``, ``topicization_generate``,
    ``topicization_merge``, ``topicization_discover``} — the pipeline site that
    owns the JSON retry loop and re-issued the LLM call with a corrective hint
    appended (BUG-019).
    """
    LLM_JSON_PARSE_RETRY_TOTAL.labels(stage=stage).inc()


def record_anthropic_5xx(*, status: int) -> None:
    """Increment ``tg_parser_anthropic_api_5xx_total`` for one retryable 5xx.

    Called per retryable 5xx response (incl. 520, BUG-020) and once more on the
    terminal retries-exhausted failure so the terminal failure is always
    countable independent of the per-attempt series.
    """
    ANTHROPIC_API_5XX_TOTAL.labels(status=str(status)).inc()


def record_anthropic_billing_block(stage: str) -> None:
    """Record a non-retryable Anthropic billing block."""
    ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage=stage).inc()


def record_llm_truncation(*, provider: str, model: str, stage: str) -> None:
    """Increment ``tg_parser_llm_truncation_total`` for one ``max_tokens`` truncation (BUG-071).

    Called from the topicization retry loops when ``LLMResponse.stop_reason ==
    "max_tokens"`` — the reply was charged (HTTP 200) but cut off at the output
    cap, so its JSON cannot be parsed. ``stage`` ∈ {``topicization_generate``,
    ``topicization_merge``, ``topicization_discover``}. Empty values normalise to
    ``"unknown"`` so the labelset stays bounded.
    """
    LLM_TRUNCATION_TOTAL.labels(
        provider=provider or "unknown",
        model=model or "unknown",
        stage=stage or "unknown",
    ).inc()


def record_topicization_failed_batch(*, stage: str, channel_id: str, count: int = 1) -> None:
    """Increment ``tg_parser_topicization_failed_batches_total`` (BUG-071 observability).

    Called from ``topicize_channel`` at every site where
    :attr:`TopicizationPipelineImpl.failed_batches` is incremented — both the
    single-batch drop (truncation or other exception) and the multi-batch
    ``asyncio.gather`` per-batch failure — so the metric tracks the same number
    surfaced on the ``run_topicization`` return dict / CLI exit code / logs.

    ``stage`` ∈ {``topicization_generate``, ``topicization_merge``,
    ``topicization_discover``} (only ``topicization_generate`` is emitted today);
    empty values normalise to ``"unknown"`` so the labelset stays bounded.
    ``count`` defaults to 1 (one failed batch per call). Non-positive counts are
    ignored.
    """
    if count <= 0:
        return
    TOPICIZATION_FAILED_BATCHES_TOTAL.labels(
        stage=stage or "unknown",
        channel_id=channel_id or "unknown",
    ).inc(count)


def record_discover_attempted_mark_failed(*, channel_id: str) -> None:
    """Increment ``tg_parser_topicization_discover_attempted_mark_failed_total`` (BUG-075 R1).

    Called from :func:`tg_parser.services.topicization_service._mark_discover_attempted`
    on the best-effort marker-write failure path. Empty values normalise to
    ``"unknown"`` so the labelset stays bounded.
    """
    TOPICIZATION_DISCOVER_ATTEMPTED_MARK_FAILED_TOTAL.labels(
        channel_id=channel_id or "unknown",
    ).inc()


def record_reconcile_discover_docs(*, channel_id: str, count: int = 1) -> None:
    """Increment ``tg_parser_topicization_reconcile_discover_docs_total`` (BUG-075).

    Called from :func:`tg_parser.services.topicization_service._run_incremental_topicization_locked`
    on the reconcile path (``reconcile_only=True``) with the number of docs that
    actually entered Phase-2 discover this run (``len(unassigned_docs)``). This
    counts the reconcile path SPECIFICALLY, not the normal new-docs incremental
    path. ``count`` defaults to 1; non-positive counts are ignored and empty
    ``channel_id`` normalises to ``"unknown"`` so the labelset stays bounded.
    """
    if count <= 0:
        return
    TOPICIZATION_RECONCILE_DISCOVER_DOCS_TOTAL.labels(
        channel_id=channel_id or "unknown",
    ).inc(count)


def record_topicization_full_run_tokens(*, channel_id: str, count: int) -> None:
    """Increment ``tg_parser_topicization_full_run_tokens_total`` (BUG-076).

    Called with the per-chunk input+output token delta as each chunk of a
    resumable full run commits. Non-positive counts are ignored; empty
    ``channel_id`` normalises to ``"unknown"`` so the labelset stays bounded.
    """
    if count <= 0:
        return
    TOPICIZATION_FULL_RUN_TOKENS_TOTAL.labels(
        channel_id=channel_id or "unknown",
    ).inc(count)


def set_topicization_full_run_chunks(*, channel_id: str, done: int, total: int) -> None:
    """Set the ``tg_parser_topicization_full_run_chunks`` progress gauge (BUG-076)."""
    cid = channel_id or "unknown"
    TOPICIZATION_FULL_RUN_CHUNKS.labels(channel_id=cid, kind="done").set(max(0, done))
    TOPICIZATION_FULL_RUN_CHUNKS.labels(channel_id=cid, kind="total").set(max(0, total))


def record_topicization_full_run_budget_halt(*, channel_id: str) -> None:
    """Increment ``tg_parser_topicization_full_run_budget_halt_total`` (BUG-076)."""
    TOPICIZATION_FULL_RUN_BUDGET_HALT_TOTAL.labels(
        channel_id=channel_id or "unknown",
    ).inc()


def record_topicization_full_run_resume(*, channel_id: str) -> None:
    """Increment ``tg_parser_topicization_full_run_resume_total`` (BUG-076)."""
    TOPICIZATION_FULL_RUN_RESUME_TOTAL.labels(
        channel_id=channel_id or "unknown",
    ).inc()


def record_topicization_full_run_chunk_failed(*, channel_id: str, reason: str) -> None:
    """Increment ``tg_parser_topicization_full_run_chunk_failed_total`` (BUG-077 F9).

    ``reason`` ∈ {merge_halt, malformed_merge, empty_after_failure,
    commit_failed} — emitted at each non-advancing chunk-halt site of the
    chunked full path. Empty values normalise to ``"unknown"`` so the labelset
    stays bounded.
    """
    TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL.labels(
        channel_id=channel_id or "unknown",
        reason=reason or "unknown",
    ).inc()


def record_topicization_full_run_noprogress_skip(*, channel_id: str) -> None:
    """Increment ``tg_parser_topicization_full_run_noprogress_skip_total`` (BUG-077 F1)."""
    TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL.labels(
        channel_id=channel_id or "unknown",
    ).inc()


def record_bot_gemini_empty_parts(*, model: str, finish_reason: str) -> None:
    """Record one bot Gemini empty-parts event (BUG-006 monitoring).

    ``finish_reason`` is the value from ``candidates[0].finishReason`` when
    available, or one of the synthetic values documented on
    :data:`BOT_GEMINI_EMPTY_PARTS_TOTAL`. Empty / unknown values are
    normalised to ``"none"`` so the labelset stays bounded.
    """
    BOT_GEMINI_EMPTY_PARTS_TOTAL.labels(
        model=model or "unknown",
        finish_reason=finish_reason or "none",
    ).inc()


# F4-B Core Workspaces — Karpathy 7-checklist principle 6 (observability)
#
# Cardinality notes:
# * ``tg_workspace_total`` is a Gauge without labels — single global
#   counter incremented on create, decremented on delete. ``owner_id``
#   is intentionally *not* used as a label (would be unbounded).
# * ``tg_workspace_query_total`` ``result`` ∈ {scoped, null_fallback,
#   not_found}; cardinality fixed at 3.
# * ``tg_workspace_tool_total`` ``tool`` ∈ the 8 scoped MCP tools +
#   8 workspace CRUD/membership tools = bounded at 16; ``result`` ∈
#   {ok, not_found, denied, validation_error}.
WORKSPACE_TOTAL = Gauge(
    "tg_workspace_total",
    "Currently existing workspaces across all tenants.",
)

WORKSPACE_SIZE = Histogram(
    "tg_workspace_size",
    "Number of channels (workspace_sources rows) per workspace at resolve time.",
    buckets=(0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144),
)

WORKSPACE_QUERY_TOTAL = Counter(
    "tg_workspace_query_total",
    "effective_channel_ids resolver outcomes.",
    ["result"],
)

WORKSPACE_EFFECTIVE_SIZE = Histogram(
    "tg_workspace_effective_size",
    "Size of the intersection (user.allowed_channel_ids ∩ workspace.channel_ids).",
    buckets=(0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144),
)

WORKSPACE_RESOLVER_SECONDS = Histogram(
    "tg_workspace_resolver_seconds",
    "End-to-end latency of WorkspaceService.effective_channel_ids in seconds.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

WORKSPACE_TOOL_TOTAL = Counter(
    "tg_workspace_tool_total",
    "Per-tool usage counter for MCP/CLI workspace surface.",
    ["tool", "result"],
)

# F9 Phase 2 — prompt-injection suspect detection (log + metric; do not block).
# surface ∈ {bot, rag, processing} — fixed low cardinality.
PROMPT_INJECTION_SUSPECT_TOTAL = Counter(
    "tg_parser_prompt_injection_suspect_total",
    "Inputs matching short-list prompt-injection suspect patterns (F9 Phase 2).",
    ["surface"],
)


def record_prompt_injection_suspect(*, surface: str) -> None:
    """Increment ``tg_parser_prompt_injection_suspect_total`` for one suspect hit."""
    PROMPT_INJECTION_SUSPECT_TOTAL.labels(surface=surface).inc()


def record_workspace_query(
    *,
    result: str,
    effective_size: int | None = None,
    workspace_size: int | None = None,
    duration_s: float | None = None,
) -> None:
    """Record one ``effective_channel_ids`` resolver outcome.

    ``result`` ∈ {``scoped``, ``null_fallback``, ``not_found``}:

    * ``scoped`` — caller passed a valid ``workspace_id``; ``effective_size``
      and ``workspace_size`` carry the intersection / membership counts.
    * ``null_fallback`` — ``workspace_id=None`` short-circuited to
      ``user.allowed_channel_ids`` (F4-A behaviour, no repo I/O).
    * ``not_found`` — workspace did not exist or was not owned by the
      caller; resolver raised ``WorkspaceNotFound``.
    """
    WORKSPACE_QUERY_TOTAL.labels(result=result).inc()
    if effective_size is not None:
        WORKSPACE_EFFECTIVE_SIZE.observe(max(effective_size, 0))
    if workspace_size is not None:
        WORKSPACE_SIZE.observe(max(workspace_size, 0))
    if duration_s is not None and duration_s >= 0:
        WORKSPACE_RESOLVER_SECONDS.observe(duration_s)


def record_workspace_tool(*, tool: str, result: str) -> None:
    """Record one MCP/CLI workspace-tool invocation outcome.

    ``tool`` is the public tool name (e.g. ``create_workspace``,
    ``search_knowledge_base``); ``result`` ∈ {``ok``, ``not_found``,
    ``denied``, ``validation_error``}.
    """
    WORKSPACE_TOOL_TOTAL.labels(tool=tool, result=result).inc()


def set_workspace_total(count: int) -> None:
    """Set the global ``tg_workspace_total`` gauge.

    Refreshed by ``WorkspaceService.list_all_workspaces`` and on every
    create / delete via :func:`bump_workspace_total`.
    """
    WORKSPACE_TOTAL.set(max(count, 0))


def bump_workspace_total(delta: int) -> None:
    """Increment / decrement the workspace gauge by ``delta``.

    Used by create / delete paths so the gauge stays in sync without a
    full refresh sweep on every mutation.
    """
    if delta > 0:
        WORKSPACE_TOTAL.inc(delta)
    elif delta < 0:
        WORKSPACE_TOTAL.dec(-delta)


# Wave 1 step 3.1 — pipeline one-shot dispatch (ADR 0007)
PIPELINE_TRIGGER_TOTAL = Counter(
    "tg_pipeline_trigger_total",
    "One-shot pipeline trigger outcomes from POST /api/v1/pipeline/trigger and proxies.",
    ["job", "result", "surface"],
    # job ∈ {full_pipeline, topicization, link_topics}
    # result ∈ {queued, success, failed, error, telethon_reauth}
    # surface ∈ {api, mcp, bot}
)


def record_pipeline_trigger(*, job: str, result: str, surface: str) -> None:
    PIPELINE_TRIGGER_TOTAL.labels(job=job, result=result, surface=surface).inc()


# ============================================================================
# Wave 1 step 3 — Idempotency-Key HTTP middleware (ADR 0009 Option C)
# ============================================================================
#
# Karpathy-7 principle 6 (observability). Two metrics:
#
# * Counter ``tg_idempotency_keys_hit_total`` — fixed cardinality on
#   ``result`` ∈ {hit, miss, mismatch}. Tracks how often clients actually
#   replay (``hit``), how often the middleware records a fresh row
#   (``miss``), and how often a re-used key with a different body
#   triggers 422 (``mismatch``). The latter is the canary for client
#   bugs (key reuse across different intents).
#
# * Gauge ``tg_idempotency_keys_table_size`` — current row count in
#   ``idempotency_keys``. Refreshed on each hourly cleanup tick so
#   operators can alert on runaway cache growth (which would indicate
#   either a TTL misconfiguration or a degenerate client retry storm).
#
# Per-user / per-key labels are intentionally OMITTED — both are
# unbounded over time and would blow up label cardinality.
IDEMPOTENCY_KEYS_HIT_TOTAL = Counter(
    "tg_idempotency_keys_hit_total",
    "HTTP Idempotency-Key middleware outcome counter (Wave 1 step 3, ADR 0009).",
    ["result"],
)

IDEMPOTENCY_KEYS_TABLE_SIZE = Gauge(
    "tg_idempotency_keys_table_size",
    "Current row count in idempotency_keys table (refreshed by hourly cleanup tick).",
)


def record_idempotency_key_result(*, result: str) -> None:
    """Record one Idempotency-Key middleware outcome.

    ``result`` ∈ {``hit``, ``miss``, ``mismatch``}:

    * ``hit`` — same ``(user_id, key)`` + matching body-hash → cached
      response replayed, no service-layer work performed.
    * ``miss`` — first request for this key OR record absent (cleaned
      out of TTL); fresh row INSERTed after the endpoint produced 2xx.
    * ``mismatch`` — same key + DIFFERENT body → 422 ``IdempotencyKeyMismatch``;
      no DB row written, no cached response served.
    """
    IDEMPOTENCY_KEYS_HIT_TOTAL.labels(result=result).inc()


def set_idempotency_keys_table_size(count: int) -> None:
    """Set the ``tg_idempotency_keys_table_size`` gauge to ``count``.

    Called by the hourly cleanup tick after each
    ``DELETE ... WHERE created_at < now() - 24h`` sweep so the gauge
    tracks the real-world cache footprint without an extra cron beat.
    """
    IDEMPOTENCY_KEYS_TABLE_SIZE.set(max(count, 0))


# F5-C #15 item #1 — topic_card_versions retention/TTL (ADR-0018). The
# append-only history table grows one row per successful re-summarize; the
# freshness bump (Track δ/T7, MAX_AGE_DAYS 14→21) accelerates that growth.
# The daily purge cron hard-DELETEs stale rows (outside keep-last-N, older
# than M days, version_no > 1) and refreshes these two series so operators
# can watch table growth and confirm the purge is actually reclaiming rows.
#
# * Gauge ``tg_topic_card_versions_rows`` — current row count, refreshed on
#   each daily purge tick (mirrors ``tg_idempotency_keys_table_size``).
# * Counter ``tg_topic_card_versions_purged_total`` — cumulative rows
#   hard-DELETEd by the retention purge.
TOPIC_CARD_VERSIONS_ROWS = Gauge(
    "tg_topic_card_versions_rows",
    "Current row count in topic_card_versions table (refreshed by daily F5-C retention purge tick).",
)

TOPIC_CARD_VERSIONS_PURGED_TOTAL = Counter(
    "tg_topic_card_versions_purged_total",
    "Cumulative topic_card_versions rows hard-DELETEd by the F5-C retention purge (ADR-0018).",
)


def set_topic_card_versions_rows(count: int) -> None:
    """Set the ``tg_topic_card_versions_rows`` gauge to ``count``.

    Called by the daily F5-C retention purge tick after each sweep so the
    gauge tracks the real-world history footprint without an extra cron beat.
    """
    TOPIC_CARD_VERSIONS_ROWS.set(max(count, 0))


def record_topic_card_versions_purged(deleted: int) -> None:
    """Increment the ``tg_topic_card_versions_purged_total`` counter.

    ``deleted`` is the number of rows removed by one purge sweep. A no-op
    sweep (0 deleted) still calls this with 0 so the counter's ``_created``
    timestamp is present from first scrape.
    """
    if deleted > 0:
        TOPIC_CARD_VERSIONS_PURGED_TOTAL.inc(deleted)


# BUG-067/B3 — per-channel processed/raw coverage gauge. Set after each
# incremental source tick (scheduler_service._process_source) so a silently
# under-covered channel — processed_documents flat while raw_messages grow
# (the BUG-067 / BUG-065 signature) — is observable on dashboards/alerts.
# ``channel_id`` cardinality is bounded per tenant deployment (mirrors the
# existing per-channel MESSAGES_PROCESSED_TOTAL / DEDUP gauges).
CHANNEL_PROCESSED_COVERAGE_RATIO = Gauge(
    "tg_channel_processed_coverage_ratio",
    "Per-channel processed/raw coverage ratio (processed_documents / raw_messages), [0, 1].",
    ["channel_id"],
)


# BUG-070 (H1) — Telethon session-lock wait observability. The in-process lock
# (telethon_client._SESSION_LOCK) serializes ingestion across concurrent
# sources; this histogram records how long each source waited to acquire it,
# labelled by ``outcome`` ∈ {acquired, contention}. ``contention`` = the wait
# budget (scheduler_session_lock_wait_timeout_s) elapsed and a benign
# SessionLockContentionError was raised (source retries next tick). Sustained
# ``contention`` or rising ``acquired`` waits indicate the session is held
# longer than expected (e.g. a slow/heavy ingestion) and should be watched.
TELETHON_SESSION_LOCK_WAIT_SECONDS = Histogram(
    "tg_telethon_session_lock_wait_seconds",
    "Time spent waiting to acquire the process-wide Telethon session lock (BUG-070 H1).",
    ["outcome"],  # outcome ∈ {acquired, contention} — fixed cardinality at 2.
    buckets=(0.01, 0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)


def record_session_lock_wait(*, waited_s: float, outcome: str) -> None:
    """Observe one Telethon session-lock wait (BUG-070 H1).

    ``outcome`` ∈ {``acquired``, ``contention``}: ``acquired`` = the lock was
    obtained after ``waited_s`` seconds; ``contention`` = the wait budget
    elapsed and a :class:`SessionLockContentionError` was raised. ``waited_s``
    is clamped to >= 0 so a clock anomaly never corrupts the buckets.
    """
    TELETHON_SESSION_LOCK_WAIT_SECONDS.labels(outcome=outcome).observe(max(waited_s, 0.0))


def set_channel_coverage(*, channel_id: str, ratio: float) -> None:
    """Set the ``tg_channel_processed_coverage_ratio`` gauge for ``channel_id``.

    ``ratio`` is processed_documents / raw_messages, clamped to [0, 1] so an
    out-of-range value (e.g. a transient over-count) never corrupts the gauge.
    """
    CHANNEL_PROCESSED_COVERAGE_RATIO.labels(channel_id=channel_id).set(min(max(ratio, 0.0), 1.0))
