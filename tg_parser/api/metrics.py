"""
Prometheus metrics instrumentation.

Phase 3D: Prometheus-compatible metrics endpoint for monitoring.
"""

from collections.abc import Callable

import structlog
from prometheus_client import Counter, Gauge, Histogram
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

ANTHROPIC_BILLING_BLOCK_TOTAL = Counter(
    "tg_parser_anthropic_billing_block_total",
    "Total Anthropic billing blocks (invalid_request_error credit balance)",
    ["stage"],
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
    ],
    # outcome ∈ {ok, locked, no_card, no_bundle, empty_scope, llm_error,
    # version_raced, unknown}; channel_id currently always "-" — kept as a
    # label so per-channel breakdown can be added in Phase 2 without a
    # cardinality migration. Run-level cap counters (cap_duration /
    # cap_tokens) are NOT topic outcomes — see run_for_channel breakdown.
)

RESUMMARIZE_TOKENS_TOTAL = Counter(
    "tg_resummarize_tokens_total",
    "Total LLM tokens consumed by F5-C re-summarize.",
    ["provider", "model", "token_type"],  # token_type: prompt | completion
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
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_s: float = 0.0,
    model: str = "",
) -> None:
    """Record a single F5-C re-summarize attempt.

    ``topic_id`` is currently logged via structlog elsewhere; we keep it
    in the signature so the call sites stay self-documenting if we add a
    high-cardinality channel-id label later.
    """
    RESUMMARIZE_TOTAL.labels(channel_id="-", outcome=status).inc()
    if status == "ok" and model:
        if input_tokens:
            RESUMMARIZE_TOKENS_TOTAL.labels(
                provider=model.split("/", 1)[0],
                model=model.split("/", 1)[-1],
                token_type="prompt",
            ).inc(input_tokens)
        if output_tokens:
            RESUMMARIZE_TOKENS_TOTAL.labels(
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


def create_instrumentator() -> Instrumentator:
    """
    Create and configure Prometheus instrumentator.

    Returns singleton Instrumentator instance to avoid duplicate metric registration.

    Returns:
        Configured Instrumentator instance
    """
    global _instrumentator

    # Return existing instance to avoid duplicate metric registration
    if _instrumentator is not None:
        return _instrumentator

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,  # We control this via settings.metrics_enabled
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/health", "/docs", "/redoc", "/openapi.json"],
        inprogress_name="tg_parser_http_requests_inprogress",
        inprogress_labels=True,
    )

    # Add default metrics
    instrumentator.add(
        metrics.default(
            metric_namespace="tg_parser",
            metric_subsystem="http",
        )
    )

    # Add latency histogram
    instrumentator.add(
        metrics.latency(
            metric_namespace="tg_parser",
            metric_subsystem="http",
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
    )

    # Add request size
    instrumentator.add(
        metrics.request_size(
            metric_namespace="tg_parser",
            metric_subsystem="http",
        )
    )

    # Add response size
    instrumentator.add(
        metrics.response_size(
            metric_namespace="tg_parser",
            metric_subsystem="http",
        )
    )

    # Add custom agent metrics
    instrumentator.add(agent_metrics())

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


def record_anthropic_billing_block(stage: str) -> None:
    """Record a non-retryable Anthropic billing block."""
    ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage=stage).inc()


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
