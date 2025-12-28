"""
Prometheus metrics instrumentation.

Phase 3D: Prometheus-compatible metrics endpoint for monitoring.
"""

import logging
from typing import Callable

from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info

logger = logging.getLogger(__name__)

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

