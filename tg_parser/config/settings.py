"""
Конфигурация TG_parser через pydantic-settings.

Реализует docs/tech-stack.md: настройки через ENV + файлы.
"""

import json
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

import structlog
from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def parse_json_dict(v: str | dict[str, str] | None) -> dict[str, str]:
    """Parse JSON string or dict for API keys.

    DI-12: Logs a WARNING on parse failure instead of silently returning {}.
    Silent swallowing previously caused migrate-users to map 0 mcp_tokens
    when MCP_AUTH_TOKENS in .env had malformed JSON — see FUTURE_FEATURES.md.
    """
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "json_dict_parse_failed",
            error=str(e),
            preview=str(v)[:80],
            hint="check .env for malformed JSON in API_KEYS / MCP_AUTH_TOKENS",
        )
        return {}


def parse_json_list(v: str | list[str] | None) -> list[str]:
    """Parse JSON string or list for CORS origins.

    DI-12: Logs a WARNING on parse failure (was previously silent).
    """
    if v is None:
        return ["*"]
    if isinstance(v, list):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "json_list_parse_failed",
            error=str(e),
            preview=str(v)[:80],
            hint="check .env for malformed JSON",
        )
        return ["*"]


def parse_comma_separated_ints(v: str | list[int] | None) -> list[int]:
    """Parse comma-separated string or list of ints for user ID allowlists."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    return []


class Settings(BaseSettings):
    """
    Глобальные настройки приложения.

    Считываются из переменных окружения и .env файла.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==========================================================================
    # Database Configuration (PostgreSQL only)
    # ==========================================================================

    # PostgreSQL connection settings
    db_host: str = Field(
        default="localhost",
        description="PostgreSQL host",
    )
    db_port: int = Field(
        default=5432,
        description="PostgreSQL port",
    )
    db_name: str = Field(
        default="tg_parser",
        description="PostgreSQL database name",
    )
    db_user: str = Field(
        default="tg_parser_user",
        description="PostgreSQL user",
    )
    db_password: str = Field(
        default="",
        description="PostgreSQL password",
    )

    # Connection Pool Settings (PostgreSQL only)
    db_pool_size: int = Field(
        default=5,
        description="Base number of connections in the pool",
        ge=1,
        le=50,
    )
    db_max_overflow: int = Field(
        default=10,
        description="Additional connections when pool is exhausted",
        ge=0,
        le=50,
    )
    db_pool_timeout: float = Field(
        default=30.0,
        description="Timeout in seconds to get a connection from pool",
        ge=1.0,
        le=300.0,
    )
    db_pool_recycle: int = Field(
        default=3600,
        description="Recycle connections after N seconds (1 hour default)",
        ge=60,
        le=7200,
    )
    db_pool_pre_ping: bool = Field(
        default=True,
        description="Check connection health before using it",
    )

    # ==========================================================================
    # LLM настройки (v1.2 Multi-LLM)
    # ==========================================================================

    llm_provider: str = "openai"  # openai | anthropic | gemini | ollama
    llm_model: str | None = None  # Опционально: переопределение модели
    llm_base_url: str | None = None  # Для OpenAI-compatible прокси или Ollama
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for OpenAI API (or compatible proxy)",
    )

    # Per-stage LLM overrides (v3.3 — fallback to global llm_provider/llm_model)
    processing_llm_provider: str | None = None
    processing_llm_model: str | None = None
    topicization_llm_provider: str | None = None
    topicization_llm_model: str | None = None
    rag_llm_provider: str | None = None
    rag_llm_model: str | None = None
    digest_llm_provider: str | None = None
    digest_llm_model: str | None = None
    # F5-C Evolving Topic Summaries: per-stage LLM override for re-summarize.
    resummarize_llm_provider: str | None = None
    resummarize_llm_model: str | None = None

    # API keys (должны быть в ENV)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    # ==========================================================================
    # Processing параметры (TR-38, TR-47)
    # ==========================================================================

    # Детерминизм LLM (TR-38)
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096

    # Parallelism (Session 31)
    processing_concurrency: int = Field(
        default=5,
        description="Number of parallel LLM requests for processing stage",
        ge=1,
        le=50,
    )

    # Ретраи per-message (TR-47)
    processing_max_attempts_per_message: int = 3
    processing_retry_backoff_base: float = 1.0  # секунды
    processing_retry_jitter_max: float = 0.3  # 0-30% jitter

    # ==========================================================================
    # Ingestion параметры (TR-12, TR-13)
    # ==========================================================================

    # Telegram API credentials (для Telethon)
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None
    telegram_session_name: str = "tg_parser_session"

    # Ретраи per-run (TR-13)
    ingestion_max_attempts_per_run: int = 5
    ingestion_retry_backoff_base: float = 1.0
    ingestion_retry_jitter_max: float = 0.3

    # ==========================================================================
    # Topicization параметры (TR-35, TR-36, TR-IF-4)
    # ==========================================================================

    # Число якорей для cluster (TR-IF-4)
    topicization_top_n_anchors: int = 3

    # Пороги качества тем (TR-35)
    topicization_singleton_min_len: int = 300
    topicization_singleton_min_score: float = 0.75
    topicization_cluster_min_anchor_score: float = 0.6

    # Порог supporting элементов (TR-36)
    topicization_supporting_min_score: float = 0.10

    # Supporting items matching (Session 33)
    topicization_max_supporting_items: int = Field(
        default=100,
        description="Maximum supporting items per topic bundle",
        ge=5,
        le=500,
    )
    topicization_min_token_length: int = Field(
        default=3,
        description="Minimum token length for keyword matching (3 captures medical abbreviations: СОЭ, ПЦР, IgE while avoiding 2-char noise)",
        ge=2,
        le=6,
    )
    topicization_text_clean_match_chars: int = Field(
        default=1000,
        description="Max chars of text_clean to use for keyword matching (0 = disabled)",
        ge=0,
        le=5000,
    )

    # Parallelism for topicization batches (Session 31)
    topicization_batch_concurrency: int = Field(
        default=5,
        description="Number of parallel LLM requests for topicization batch processing",
        ge=1,
        le=20,
    )

    # Max docs per LLM call in incremental discover_new_topics (Session 47)
    topicization_batch_size: int = Field(
        default=50,
        description="Max documents per LLM call in discover_new_topics; larger sets are split",
        ge=10,
        le=500,
    )

    # Cross-channel topicization (Session 48)
    cross_channel_topicization: bool = Field(
        default=True,
        description="Enable cross-channel context in incremental topicization and auto-linking",
    )
    cross_channel_link_threshold: float = Field(
        default=0.3,
        description="Minimum similarity score for automatic cross-channel TopicLink creation",
        ge=0.0,
        le=1.0,
    )

    # ==========================================================================
    # Pipeline версии (TR-39)
    # ==========================================================================

    pipeline_version_processing: str = "processing:v1.0.0"
    pipeline_version_topicization: str = "topicization:v1.0.0"
    export_version: str = "export:v1.0.0"

    # ==========================================================================
    # Промпты (v1.1 Configurable Prompts)
    # ==========================================================================

    # Кастомная директория промптов (по умолчанию ./prompts).
    #
    # BUG-028 Layer C: default is Path("prompts") (not None) so downstream
    # callers that do ``str(settings.prompts_dir)`` never see the literal
    # Python string "None". The ``Path | None`` typing is preserved so
    # call-sites can still pass ``None`` explicitly and so the Layer A
    # (scheduler_service.py guard) / Layer B (PromptLoader fallback) layers
    # remain valid defense-in-depth.
    prompts_dir: Path | None = Path("prompts")

    # ==========================================================================
    # Output директория
    # ==========================================================================

    output_dir: Path = Path("output")

    # ==========================================================================
    # Multi-Tenancy (F4)
    # ==========================================================================

    default_max_channels: int = Field(
        default=20,
        description="Default max channels per user when users.max_channels is NULL",
        ge=1,
    )

    # ==========================================================================
    # API Security (Phase 2F)
    # ==========================================================================

    api_keys: Annotated[dict[str, str], BeforeValidator(parse_json_dict)] = Field(
        default_factory=dict,
        description="API keys mapping: key -> client_name",
    )
    api_key_required: bool = Field(
        default=False,
        description="Require API key for all requests",
    )

    # ==========================================================================
    # MCP Server Configuration (D1)
    # ==========================================================================

    mcp_host: str = Field(
        default="127.0.0.1",
        description="MCP server bind host",
    )
    mcp_port: int = Field(
        default=8080,
        description="MCP server bind port",
    )
    mcp_transport: str = Field(
        default="stdio",
        description="MCP transport: stdio or streamable-http",
    )
    mcp_path: str = Field(
        default="/mcp",
        description="Streamable HTTP endpoint path",
    )
    mcp_auth_enabled: bool = Field(
        default=False,
        description="Require bearer token for MCP HTTP transport",
    )
    mcp_auth_tokens: Annotated[dict[str, str], BeforeValidator(parse_json_dict)] = Field(
        default_factory=dict,
        description="MCP auth tokens mapping: token -> client_name",
    )

    # ==========================================================================
    # Rate Limiting (Phase 2F)
    # ==========================================================================

    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_process: str = Field(
        default="10/minute",
        description="Rate limit for POST /api/v1/process",
    )
    rate_limit_export: str = Field(
        default="20/minute",
        description="Rate limit for POST /api/v1/export",
    )
    rate_limit_pipeline_trigger: str = Field(
        default="30/minute",
        description="Rate limit for POST /api/v1/pipeline/trigger (per-user)",
    )
    rate_limit_default: str = Field(
        default="100/minute",
        description="Default rate limit for other endpoints",
    )

    # ==========================================================================
    # Pipeline dispatch (ADR 0007 — Wave 1 step 3.1)
    # ==========================================================================

    pipeline_dispatch_base_url: str = Field(
        default="http://tg_parser:8000",
        description="tg_parser REST API base URL for MCP/Bot dispatch clients",
    )
    pipeline_dispatch_timeout_seconds: float = Field(
        default=30.0,
        description="HTTP timeout for MCP/Bot pipeline dispatch calls",
        ge=1.0,
    )

    # ==========================================================================
    # CORS Configuration (Phase 2F)
    # ==========================================================================

    cors_origins: Annotated[list[str], BeforeValidator(parse_json_list)] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins",
    )

    # ==========================================================================
    # Health Check & LLM Retry Timeouts
    # ==========================================================================

    health_check_timeout: float = Field(
        default=10.0,
        description="Timeout for LLM provider health checks (seconds)",
    )
    ollama_health_check_timeout: float = Field(
        default=5.0,
        description="Timeout for Ollama health check (seconds)",
    )
    llm_json_retry_delay: float = Field(
        default=2.0,
        description="Delay between LLM JSON parse retries (seconds)",
    )

    # ==========================================================================
    # Webhooks (Phase 2F)
    # ==========================================================================

    webhook_timeout: float = Field(
        default=30.0,
        description="Timeout for webhook HTTP calls in seconds",
    )
    webhook_max_retries: int = Field(
        default=3,
        description="Maximum retries for failed webhook calls",
    )

    # ==========================================================================
    # Agent State Persistence (Phase 3B)
    # ==========================================================================

    agent_retention_days: int = Field(
        default=14,
        description="Days to keep full task history before cleanup",
    )
    agent_retention_mode: str = Field(
        default="delete",
        description="What to do with expired records: delete | export",
    )
    agent_archive_path: Path = Field(
        default=Path("data/archive/task_history"),
        description="Path for archived task history (when mode=export)",
    )
    agent_stats_enabled: bool = Field(
        default=True,
        description="Enable aggregated daily statistics collection",
    )
    agent_persistence_enabled: bool = Field(
        default=True,
        description="Enable agent state persistence to database",
    )

    # ==========================================================================
    # Prometheus Metrics (Phase 3D)
    # ==========================================================================

    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics endpoint",
    )

    # ==========================================================================
    # Background Scheduler (Phase 3D)
    # ==========================================================================

    scheduler_enabled: bool = Field(
        default=True,
        description="Enable background task scheduler",
    )
    scheduler_cleanup_interval_hours: int = Field(
        default=24,
        description="Interval for cleanup task in hours",
    )
    scheduler_health_check_interval_minutes: int = Field(
        default=5,
        description="Interval for health check task in minutes",
    )

    # Incremental pipeline scheduler (Session 30)
    scheduler_default_interval: int = Field(
        default=3600,
        description="Default poll interval in seconds for incremental pipeline (1 hour)",
        ge=60,
    )
    scheduler_retopicize_threshold: int = Field(
        default=10,
        description="Number of new processed documents before auto-retopicization",
        ge=1,
    )
    scheduler_max_concurrent_sources: int = Field(
        default=1,
        description="Max sources processed in parallel by scheduler",
        ge=1,
        le=10,
    )
    billing_block_backoff_s: int = Field(
        default=3600,
        description="Backoff in seconds when Anthropic billing is exhausted",
        ge=60,
    )

    anthropic_prompt_caching_enabled: bool = Field(
        default=True,
        description=(
            "Enable Anthropic prompt-caching (cache_control on long-lived prefixes). "
            "Disable only for debugging cache bugs; saves ~90 percent tokens on repeated"
            " prompts."
        ),
    )
    processing_anthropic_input_token_estimate: int = Field(
        default=2000,
        description=(
            "Per-call input token budget passed to the Anthropic rate-limiter for "
            "processing-stage calls. Used as a pre-flight estimate so the limiter can "
            "schedule conservatively before the real token count is known."
        ),
        ge=100,
        le=200_000,
    )
    processing_anthropic_output_token_estimate: int = Field(
        default=2048,
        description=(
            "Per-call output token budget passed to the Anthropic rate-limiter for "
            "processing-stage calls. Mirrors the realistic upper bound on completion "
            "size for processing prompts."
        ),
        ge=100,
        le=64_000,
    )

    # ==========================================================================
    # Scheduled Digests (F6)
    # ==========================================================================

    digest_scheduler_enabled: bool = Field(
        default=True,
        description=(
            "Enable digest scheduler in the bot process. Set to False in API/CLI "
            "schedulers to avoid double delivery."
        ),
    )
    digest_default_timezone: str = Field(
        default="Europe/Moscow",
        description=("Fallback IANA timezone applied when subscription does not specify one"),
    )
    digest_max_docs_per_run: int = Field(
        default=50,
        description="Maximum number of processed documents per channel included in one digest",
        ge=1,
        le=500,
    )
    digest_first_run_lookback_hours: int = Field(
        default=24,
        description=(
            "When `last_digest_cursor` is None, fetch documents from the past N hours; "
            "after the first run the cursor advances to `now` even on empty result."
        ),
        ge=1,
        le=24 * 30,
    )
    digest_refresh_interval: int = Field(
        default=60,
        description=(
            "Seconds between scheduler reconciliation ticks (picks up subscriptions "
            "created/deleted in another process)."
        ),
        ge=10,
        le=3600,
    )
    digest_message_max_chars: int = Field(
        default=4096,
        description="Telegram MARKDOWN_V2 send_message character limit per part",
        ge=512,
        le=4096,
    )
    digest_max_message_parts: int = Field(
        default=10,
        description=(
            "Maximum number of split message parts before the digest is sent as a "
            ".md attachment instead."
        ),
        ge=1,
        le=50,
    )

    # ==========================================================================
    # F5-C Evolving Topic Summaries (a4b5c6d7e8f9)
    # ==========================================================================

    resummarize_enabled: bool = Field(
        default=True,
        description="Master switch for F5-C scheduler hook; off => no LLM calls",
    )
    resummarize_trigger_n: int = Field(
        default=5,
        description=("Trigger threshold: re-summarize when new_items_since_last_summary >= N"),
        ge=1,
        le=1000,
    )
    resummarize_input_window_n: int = Field(
        default=10,
        description=(
            "Top-N bundle items (anchors-first, then highest-score supports) "
            "passed to the resummarize prompt; controls token budget"
        ),
        ge=1,
        le=200,
    )
    resummarize_max_per_tick: int = Field(
        default=10,
        description=(
            "Cap on number of topics re-summarized per scheduler tick per channel; "
            "prevents thundering herd after a large incremental batch"
        ),
        ge=1,
        le=200,
    )
    resummarize_max_duration_s: int = Field(
        default=60,
        description="Per-tick wall-clock cap on F5-C work, in seconds.",
        ge=10,
        le=3600,
    )
    resummarize_max_tokens_per_tick: int = Field(
        default=50000,
        description="Per-tick LLM token cap (sum of input + output across all topics).",
        ge=1000,
        le=10_000_000,
    )

    # ==========================================================================
    # Embedding / RAG Configuration (P5)
    # ==========================================================================

    embedding_provider: str = Field(
        default="openai",
        description="Embedding provider (openai)",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model name",
    )
    embedding_batch_size: int = Field(
        default=100,
        description="Max documents per embedding API call",
        ge=1,
        le=2048,
    )
    embedding_dimension: int = Field(
        default=1536,
        description="Embedding vector dimension",
        ge=1,
    )

    # ==========================================================================
    # Watchlist scoring (F11) — tunable hybrid weights + default threshold
    # ==========================================================================

    watchlist_keyword_weight: float = Field(
        default=0.4,
        description=(
            "Weight of the keyword component in the F11 combined score "
            "(combined = keyword_weight * kw + semantic_weight * sem). "
            "Should sum to 1.0 with watchlist_semantic_weight; the scorer clamps "
            "the result to [0, 1] regardless."
        ),
        ge=0.0,
        le=1.0,
    )
    watchlist_semantic_weight: float = Field(
        default=0.6,
        description=(
            "Weight of the semantic (cosine) component in the F11 combined score. "
            "Lower this (and raise watchlist_keyword_weight) when the embedding "
            "model under-scores the corpus language (DIAG 2026-06-07: Russian "
            "medical text ceilings ~0.3 cosine on text-embedding-3-small)."
        ),
        ge=0.0,
        le=1.0,
    )
    watchlist_default_threshold: float = Field(
        default=0.6,
        description=(
            "Default combined-score cutoff applied to new interests when the "
            "caller does not pass an explicit threshold. Lowering it makes new "
            "watchlists more sensitive; existing rows keep their stored value."
        ),
        ge=0.0,
        le=1.0,
    )
    watchlist_keyword_aggregation: Literal["mean", "topk"] = Field(
        default="topk",
        description=(
            "Aggregation scheme for the F11 keyword component (ADR 0010). "
            "'mean' = matched_phrases / total_phrases (the original behaviour, "
            "which dilutes on-topic docs as soon as an interest names >=4 "
            "keywords — the 'denominator penalty'). 'topk' = min(hits, k) / k "
            "with k=min(watchlist_keyword_topk, n_phrases): caps the denominator "
            "so keywords beyond the top K add no penalty. 'topk' is a strict "
            "no-op for interests with <=K keywords (scores byte-identical to "
            "'mean'), so existing thresholds are preserved. Set to 'mean' as the "
            "production rollback knob."
        ),
    )
    watchlist_keyword_topk: int = Field(
        default=3,
        description=(
            "The K in the 'topk' keyword aggregation (ADR 0010): the keyword "
            "denominator is capped at min(K, n_phrases). Only affects interests "
            "with more than K keyword phrases; ignored entirely when "
            "watchlist_keyword_aggregation='mean'."
        ),
        ge=1,
    )
    watchlist_calibration_enabled: bool = Field(
        default=True,
        description=(
            "When True, new F11 interests without an explicit threshold receive "
            "a corpus-derived suggested cutoff (ADR 0012) instead of "
            "watchlist_default_threshold. Explicit threshold args bypass "
            "calibration."
        ),
    )
    watchlist_calibration_strategy: Literal["target_fraction", "percentile"] = Field(
        default="target_fraction",
        description=(
            "ADR 0012 threshold-selection strategy. 'target_fraction' picks the "
            "Nth-highest combined score so ~fraction of the corpus would match "
            "(clamped by min/max match counts). 'percentile' sets the cutoff "
            "at the configured percentile of the score distribution."
        ),
    )
    watchlist_calibration_target_fraction: float = Field(
        default=0.03,
        description=(
            "For target_fraction strategy: fraction of the scored corpus used "
            "to derive the match budget (e.g. 0.03 → ~3% of docs)."
        ),
        ge=0.0,
        le=1.0,
    )
    watchlist_calibration_target_min_matches: int = Field(
        default=10,
        description="Minimum target match count for target_fraction calibration.",
        ge=1,
    )
    watchlist_calibration_target_max_matches: int = Field(
        default=150,
        description="Maximum target match count for target_fraction calibration.",
        ge=1,
    )
    watchlist_calibration_min_corpus_size: int = Field(
        default=20,
        description=(
            "Corpus smaller than this yields low-confidence calibration; "
            "empty corpus falls back to watchlist_default_threshold."
        ),
        ge=0,
    )
    watchlist_calibration_percentile: float = Field(
        default=97.0,
        description=(
            "For percentile strategy: combined-score percentile used as the "
            "suggested threshold (97 → top ~3% of scores qualify)."
        ),
        ge=0.0,
        le=100.0,
    )
    watchlist_calibration_min_threshold: float = Field(
        default=0.45,
        description=(
            "ADR 0013 absolute precision floor: calibration never returns a "
            "cutoff below this value (threshold = max(target_fraction_threshold, "
            "floor)). Prevents NARROW interests from chasing match volume down "
            "into the noise band (worst pre-fix overshoot was 7.9x too many "
            "matches). This is an embedding-model/corpus-specific magic number — "
            "calibrated for OpenAI text-embedding-3-small on the RU-medical "
            "corpus with semantic weight 0.6 — and must be re-derived if the "
            "embedding model, corpus language, or hybrid weights change."
        ),
        ge=0.0,
        le=1.0,
    )

    # ==========================================================================
    # Hybrid Retrieval (F5-A Phase 1)
    # ==========================================================================

    hybrid_enabled: bool = Field(
        default=True,
        description="Enable hybrid (keyword FTS + semantic pgvector) retrieval",
    )
    hybrid_rrf_k: int = Field(
        default=60,
        description="Reciprocal Rank Fusion constant; higher values reduce discrimination between ranks",
        ge=1,
    )
    fts_languages: str = Field(
        default="russian,english",
        description="Informational: FTS languages blended into the generated search_vector columns",
    )

    # ==========================================================================
    # RAG Relevance Tuning (F5-A Phase 2)
    # ==========================================================================

    fts_min_rank: float = Field(
        default=0.0,
        description="Default ts_rank_cd cutoff for keyword search (0.0 = no cutoff)",
        ge=0.0,
    )
    rag_topic_quota: int = Field(
        default=2,
        description="Number of topic cards reserved in answer() context before filling with messages",
        ge=0,
        le=20,
    )
    rag_search_overfetch_factor: int = Field(
        default=2,
        description="answer() fetches limit * factor before applying quotas for headroom",
        ge=1,
        le=10,
    )

    # ==========================================================================
    # Deduplication (F5-A Phase 3)
    # ==========================================================================

    dedup_enabled: bool = Field(
        default=True,
        description=(
            "Enable SHA-256 content-hash deduplication in processing pipeline "
            "(within-channel scope)"
        ),
    )
    dedup_strip_url_query: bool = Field(
        default=True,
        description=(
            "Strip URL query strings (?...#...) before hashing; catches tracking-param variants"
        ),
    )

    # ==========================================================================
    # Ollama Configuration
    # ==========================================================================

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for Ollama local server",
    )

    # ==========================================================================
    # Google API Key alias
    # ==========================================================================

    google_api_key: str | None = None  # Alias for gemini_api_key

    # ==========================================================================
    # Telegram Bot Configuration (Phase 3)
    # ==========================================================================

    telegram_bot_token: str | None = Field(
        default=None,
        description="Telegram bot token from @BotFather",
    )
    bot_allowed_users: str = Field(
        default="",
        description="Comma-separated Telegram user IDs allowed to use the bot",
    )

    @property
    def bot_allowed_user_ids(self) -> list[int]:
        """Parsed list of allowed Telegram user IDs."""
        return parse_comma_separated_ints(self.bot_allowed_users)

    bot_request_timeout: float = Field(
        default=60.0,
        description="Timeout for LLM/DB requests in bot agent (seconds)",
        ge=5.0,
        le=300.0,
    )
    bot_max_message_length: int = Field(
        default=4096,
        description="Maximum Telegram message length before splitting",
    )
    bot_rate_limit: int = Field(
        default=10,
        description="Maximum bot requests per minute per user",
        ge=1,
        le=100,
    )
    bot_gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model for bot agent reasoning and tool-calling",
    )
    bot_gemini_max_output_tokens: int = Field(
        default=8192,
        description=(
            "Generation-config maxOutputTokens for the bot Gemini agent. "
            "Bumped from the SDK default of 4096 in Session E (BUG-006) — "
            "Gemini-2.5-flash thinking tokens consume the same budget, and "
            "30+ TOOL_DECLARATIONS exhausted 4096 deterministically on "
            "tool-disambiguation queries."
        ),
        ge=512,
        le=65536,
    )
    bot_gemini_thinking_budget: int | None = Field(
        default=0,
        description=(
            "Generation-config thinkingConfig.thinkingBudget for the bot Gemini "
            "agent. Set to 0 to disable thinking entirely (HG-2 hotfix per "
            "BUG-006). Set to None to use the model's default. Set to a positive "
            "integer to allow that many thinking tokens; capped per-model by Google."
        ),
    )

    # ==========================================================================
    # Logging Configuration (Session 23)
    # ==========================================================================

    log_format: str = Field(
        default="text",
        description="Log format: 'json' for production, 'text' for development",
    )
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )

    # ==========================================================================
    # GPT-5 / Responses API Configuration (Session 23)
    # ==========================================================================

    llm_reasoning_effort: str = Field(
        default="low",
        description="Reasoning effort for GPT-5 models: minimal, low, medium, high",
    )
    llm_verbosity: str = Field(
        default="low",
        description="Verbosity for GPT-5 models: low, medium, high",
    )

    @model_validator(mode="after")
    def _resolve_session_path(self) -> "Settings":
        p = Path(self.telegram_session_name)
        if not p.is_absolute():
            self.telegram_session_name = str(_PROJECT_ROOT / p)
        return self


class RetrySettings(BaseSettings):
    """
    Настройки retry для LLM и других операций (Session 22).

    Позволяет конфигурировать параметры retry через ENV переменные.
    """

    model_config = SettingsConfigDict(
        env_prefix="RETRY_",
        extra="ignore",
    )

    max_attempts: int = Field(
        default=3,
        description="Максимальное количество попыток retry",
        ge=1,
        le=10,
    )
    backoff_base: float = Field(
        default=1.0,
        description="Базовая задержка для exponential backoff (секунды)",
        ge=0.1,
        le=60.0,
    )
    backoff_max: float = Field(
        default=60.0,
        description="Максимальная задержка между попытками (секунды)",
        ge=1.0,
        le=300.0,
    )
    jitter: float = Field(
        default=0.3,
        description="Jitter фактор (0.0 - 1.0) для рандомизации задержки",
        ge=0.0,
        le=1.0,
    )


SUPPORTED_LLM_PROVIDERS = ("openai", "anthropic", "gemini", "ollama")
LLM_SCOPES = ("global", "processing", "topicization", "rag", "digest", "resummarize", "bot")


class LLMConfigManager:
    """Runtime LLM configuration overlay.

    Holds per-scope (one of :data:`LLM_SCOPES`: global / processing /
    topicization / rag / digest / resummarize / bot)
    overrides that take effect immediately for new LLM client creation.
    Thread-safe via a reentrant lock so concurrent pipeline workers can
    read safely while an MCP/API call writes.

    Static settings from ``.env`` are used as defaults; runtime overrides
    are lost on restart (safe fallback by design).

    ADR 0005 (Session J): "bot" scope is Gemini-only and immune to global
    overrides (D-1). Only model= can be changed at runtime; temperature and
    max_tokens are rejected with ValueError (D-2).
    """

    _instance: "LLMConfigManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, static_settings: "Settings") -> None:
        self._static = static_settings
        self._lock = threading.RLock()
        self._overrides: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_instance(cls, static_settings: "Settings | None" = None) -> "LLMConfigManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    if static_settings is None:
                        raise RuntimeError(
                            "LLMConfigManager not initialized — pass static_settings on first call"
                        )
                    cls._instance = cls(static_settings)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton (for tests)."""
        with cls._instance_lock:
            cls._instance = None

    # -- helpers ---------------------------------------------------------

    def _api_key_for_provider(self, provider: str) -> str | None:
        m: dict[str, str | None] = {
            "openai": self._static.openai_api_key,
            "anthropic": self._static.anthropic_api_key,
            "gemini": self._static.gemini_api_key or self._static.google_api_key,
            "ollama": None,
        }
        return m.get(provider)

    def _validate_provider(self, provider: str) -> None:
        if provider not in SUPPORTED_LLM_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{provider}'. "
                f"Supported: {', '.join(SUPPORTED_LLM_PROVIDERS)}"
            )
        if provider != "ollama" and not self._api_key_for_provider(provider):
            raise ValueError(
                f"No API key configured for '{provider}'. "
                "Set the corresponding env var before switching."
            )

    # -- public API ------------------------------------------------------

    def set(
        self,
        scope: str,
        provider: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Apply a runtime LLM override for *scope*.

        Returns the full resolved config after the change.
        """
        if scope not in LLM_SCOPES:
            raise ValueError(f"Invalid scope '{scope}'. Use one of: {', '.join(LLM_SCOPES)}")

        # ADR 0005 D-1 + D-2 (Session J): bot scope is Gemini-only and model-only.
        if scope == "bot":
            if provider != "gemini":
                raise ValueError(
                    "scope='bot' only supports provider='gemini' (ADR 0005 Variant A). "
                    "Use set_llm_config(scope='bot', provider='gemini', model='gemini-2.5-pro') "
                    "to switch Gemini model at runtime."
                )
            if temperature is not None or max_tokens is not None:
                raise ValueError(
                    "scope='bot' is model-only (ADR 0005 D-2). "
                    "temperature/max_tokens overrides are not supported — "
                    "they are pinned to BOT_GEMINI_* env vars at startup. "
                    "Pass only model= for runtime model switching."
                )

        self._validate_provider(provider)

        with self._lock:
            self._overrides[scope] = {
                "provider": provider,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

        logger.info(
            "llm_config_changed",
            scope=scope,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self.get_all()

    def resolve(self, stage: str) -> tuple[str, str | None, str | None]:
        """Return ``(provider, api_key, model)`` for a pipeline *stage*.

        Priority: stage-level runtime override → global runtime override →
        stage-level static setting → global static setting.
        """
        with self._lock:
            stage_ov = self._overrides.get(stage)
            global_ov = self._overrides.get("global")

        if stage_ov:
            provider = stage_ov["provider"]  # type: ignore[assignment]
            model = stage_ov.get("model")
        elif global_ov and stage != "bot":
            # ADR 0005 D-1 (Session J): global override does NOT affect "bot" scope —
            # bot is Gemini-only; a global switch to "anthropic" must not
            # silently break the bot agent.
            provider = global_ov["provider"]  # type: ignore[assignment]
            model = global_ov.get("model")
        elif stage == "bot":
            # ADR 0005 Variant A (Session J): bot static defaults — always Gemini.
            provider = "gemini"
            model = getattr(self._static, "bot_gemini_model", None)
        else:
            provider = (
                getattr(self._static, f"{stage}_llm_provider", None) or self._static.llm_provider
            )
            model = getattr(self._static, f"{stage}_llm_model", None) or self._static.llm_model

        api_key = self._api_key_for_provider(provider)
        return provider, api_key, model

    def resolve_full(self, stage: str) -> dict[str, Any]:
        """Return full config dict for *stage* including generation params.

        Keys: provider, api_key, model, temperature, max_tokens.
        temperature/max_tokens are None when not overridden at runtime
        (callers should fall back to their own defaults).
        """
        provider, api_key, model = self.resolve(stage)

        with self._lock:
            stage_ov = self._overrides.get(stage, {})
            global_ov = self._overrides.get("global", {})

        _st = stage_ov.get("temperature")
        _gt = global_ov.get("temperature")
        temperature = _st if _st is not None else _gt

        _sm = stage_ov.get("max_tokens")
        _gm = global_ov.get("max_tokens")
        max_tokens = _sm if _sm is not None else _gm

        return {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def get_all(self) -> dict[str, Any]:
        """Return a snapshot of the full resolved config."""
        with self._lock:
            overrides = dict(self._overrides)

        available_providers: dict[str, bool] = {
            p: bool(self._api_key_for_provider(p)) or p == "ollama" for p in SUPPORTED_LLM_PROVIDERS
        }

        def _stage_config(stage: str) -> dict[str, Any]:
            provider, _key, model = self.resolve(stage)
            stage_ov = overrides.get(stage, {})
            global_ov = overrides.get("global", {})
            cfg: dict[str, Any] = {
                "provider": provider,
                "model": model,
                "overridden": stage in overrides or "global" in overrides,
            }
            _st = stage_ov.get("temperature")
            temp = _st if _st is not None else global_ov.get("temperature")
            _sm = stage_ov.get("max_tokens")
            mt = _sm if _sm is not None else global_ov.get("max_tokens")
            if temp is not None:
                cfg["temperature"] = temp
            if mt is not None:
                cfg["max_tokens"] = mt
            return cfg

        return {
            "global": {
                "provider": overrides.get("global", {}).get("provider")
                or self._static.llm_provider,
                "model": overrides.get("global", {}).get("model") or self._static.llm_model,
                "overridden": "global" in overrides,
            },
            "stages": {stage: _stage_config(stage) for stage in LLM_SCOPES if stage != "global"},
            "available_providers": available_providers,
            "runtime_overrides": overrides,
        }

    def clear(self, scope: str | None = None) -> dict[str, Any]:
        """Remove runtime overrides, reverting to static settings."""
        with self._lock:
            if scope:
                self._overrides.pop(scope, None)
            else:
                self._overrides.clear()
        logger.info("llm_config_reset", scope=scope or "all")
        return self.get_all()


# Глобальные экземпляры настроек
settings = Settings()
retry_settings = RetrySettings()
llm_config = LLMConfigManager.get_instance(settings)
