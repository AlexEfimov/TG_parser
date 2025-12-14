"""
Конфигурация TG_parser через pydantic-settings.

Реализует docs/tech-stack.md: настройки через ENV + файлы.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # LLM настройки (docs/tech-stack.md)
    # ==========================================================================

    llm_provider: str = "openai"  # default: OpenAI
    llm_model: str | None = None  # Опционально: переопределение модели
    llm_base_url: str | None = None  # Для OpenAI-compatible прокси

    # API keys (должны быть в ENV)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

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


# Глобальный экземпляр настроек
settings = Settings()
