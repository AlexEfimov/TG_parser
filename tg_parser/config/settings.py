"""
Конфигурация TG_parser через pydantic-settings.

Реализует docs/tech-stack.md: настройки через ENV + файлы.
"""

import json
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_json_dict(v: str | dict[str, str] | None) -> dict[str, str]:
    """Parse JSON string or dict for API keys."""
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return {}


def parse_json_list(v: str | list[str] | None) -> list[str]:
    """Parse JSON string or list for CORS origins."""
    if v is None:
        return ["*"]
    if isinstance(v, list):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return ["*"]


class Settings(BaseSettings):
    """
    Глобальные настройки приложения.

    Считываются из переменных окружения и .env файла.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==========================================================================
    # SQLite пути (MVP, TR-17)
    # ==========================================================================

    ingestion_state_db_path: Path = Path("ingestion_state.sqlite")
    raw_storage_db_path: Path = Path("raw_storage.sqlite")
    processing_storage_db_path: Path = Path("processing_storage.sqlite")

    # ==========================================================================
    # LLM настройки (v1.2 Multi-LLM)
    # ==========================================================================

    llm_provider: str = "openai"  # openai | anthropic | gemini | ollama
    llm_model: str | None = None  # Опционально: переопределение модели
    llm_base_url: str | None = None  # Для OpenAI-compatible прокси или Ollama

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
    topicization_supporting_min_score: float = 0.5

    # ==========================================================================
    # Pipeline версии (TR-39)
    # ==========================================================================

    pipeline_version_processing: str = "processing:v1.0.0"
    pipeline_version_topicization: str = "topicization:v1.0.0"
    export_version: str = "export:v1.0.0"

    # ==========================================================================
    # Промпты (v1.1 Configurable Prompts)
    # ==========================================================================

    prompts_dir: Path | None = None  # Кастомная директория промптов (default: ./prompts)

    # ==========================================================================
    # Output директория
    # ==========================================================================

    output_dir: Path = Path("output")

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
    rate_limit_default: str = Field(
        default="100/minute",
        description="Default rate limit for other endpoints",
    )

    # ==========================================================================
    # CORS Configuration (Phase 2F)
    # ==========================================================================

    cors_origins: Annotated[list[str], BeforeValidator(parse_json_list)] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins",
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


# Глобальные экземпляры настроек
settings = Settings()
retry_settings = RetrySettings()
