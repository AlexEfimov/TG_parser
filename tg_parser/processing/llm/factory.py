"""
LLM Client Factory.

Создаёт LLM клиент по провайдеру.
"""

from typing import TYPE_CHECKING, Any

import structlog

from tg_parser.processing.ports import LLMClient

if TYPE_CHECKING:
    from .rate_limiter import LLMRateLimiter

logger = structlog.get_logger(__name__)

_rate_limiter_cache: dict[str, "LLMRateLimiter"] = {}

_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.0-flash-exp",
    "ollama": "llama3.2",
}

# Metrics stage -> the ``resolve_llm_config`` scope its call site resolves.
# Keys must equal tg_parser.api.metrics.LLM_STAGES (pinned by a test).
LLM_STAGE_SCOPES = {
    "processing": "processing",
    "topicization_full": "topicization",
    "topicization_discover": "topicization",
    "rag": "rag",
    "digest": "digest",
    "resummarize": "resummarize",
}


def _get_or_create_rate_limiter(api_key: str, settings: Any = None) -> "LLMRateLimiter":
    """Return shared rate limiter per API key (Anthropic org-level limits)."""
    from .rate_limiter import LLMRateLimiter

    if settings is None:
        from tg_parser.config import settings as settings

    if api_key not in _rate_limiter_cache:
        _rate_limiter_cache[api_key] = LLMRateLimiter.from_settings(settings)
    return _rate_limiter_cache[api_key]


def resolve_llm_config(
    stage: str,
    settings: Any = None,
) -> tuple[str, str | None, str | None]:
    """Return (provider, api_key, model) for a pipeline stage.

    Delegates to :class:`LLMConfigManager` which honours runtime overrides,
    then falls back to per-stage static settings, then global static settings.

    Args:
        stage: One of :data:`tg_parser.config.settings.LLM_SCOPES` —
            currently ``"processing"``, ``"topicization"``, ``"rag"``,
            ``"digest"``, or ``"resummarize"`` (``"global"`` is the
            implicit fallback root and is not addressed directly here).
        settings: Optional Settings object. Falls back to global singleton if not provided.
    """
    from tg_parser.config import llm_config

    return llm_config.resolve(stage)


def prime_llm_stage_metrics() -> None:
    """Create every stage's LLM series at 0 for its currently configured model.

    Called once per process at startup. Priming in the client constructor alone
    is not enough: a Phase 2 call can finish faster than the 15 s scrape, and
    then the series is born at its first value and ``increase()`` misses the
    whole call. Best-effort — a config error here must not stop the process.
    """
    from tg_parser.api.metrics import init_llm_series

    for stage, scope in LLM_STAGE_SCOPES.items():
        try:
            provider, _api_key, model = resolve_llm_config(scope)
            provider = provider.lower()
            init_llm_series(
                provider=provider,
                model=model or _DEFAULT_MODELS.get(provider, "unknown"),
                stage=stage,
            )
        except Exception as exc:
            logger.warning("llm_stage_metrics_prime_failed", stage=stage, error=str(exc))


def create_llm_client(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    settings: Any = None,
    instrument: bool = True,
    stage: str = "unknown",
    **kwargs: Any,
) -> LLMClient:
    """
    Create an LLM client for the given provider.

    Args:
        provider: "openai" | "anthropic" | "gemini" | "ollama"
        api_key: Provider API key (not required for Ollama)
        model: Model override (default depends on provider)
        base_url: Custom base URL (for Ollama or OpenAI-compatible proxies)
        settings: Optional Settings for provider-specific config. Falls back to global singleton.
        instrument: Wrap with InstrumentedLLMClient for Prometheus metrics (default True)
        stage: Metrics ``stage`` label, one of :data:`tg_parser.api.metrics.LLM_STAGES`
            (BUG-108 a). Not the ``resolve_llm_config`` scope: Phase 2 discover and the
            full topicization run share the ``topicization`` scope but not the label.
        **kwargs: Additional client parameters

    Returns:
        LLMClient instance

    Raises:
        ValueError: Unknown provider or missing API key
    """
    provider = provider.lower()
    client: LLMClient
    resolved_model: str

    if provider == "openai":
        from .openai_client import OpenAIClient

        if not api_key:
            raise ValueError("OpenAI API key required")

        resolved_model = model or _DEFAULT_MODELS["openai"]
        client = OpenAIClient(
            api_key=api_key,
            model=resolved_model,
            base_url=base_url,
            max_retries=kwargs.pop("max_retries", 5),
            **kwargs,
        )

    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient

        if not api_key:
            raise ValueError("Anthropic API key required")

        if settings is None:
            from tg_parser.config import settings as settings

        rate_limiter = _get_or_create_rate_limiter(api_key, settings=settings)

        resolved_model = model or _DEFAULT_MODELS["anthropic"]
        client = AnthropicClient(
            api_key=api_key,
            model=resolved_model,
            rate_limiter=rate_limiter,
            prompt_caching_enabled=settings.anthropic_prompt_caching_enabled,
            rate_limit_input_estimate=settings.processing_anthropic_input_token_estimate,
            rate_limit_output_estimate=settings.processing_anthropic_output_token_estimate,
            max_retries=kwargs.pop("max_retries", 5),
            timeout=kwargs.pop("timeout", settings.anthropic_http_timeout_s),
            call_timeout=kwargs.pop("call_timeout", settings.anthropic_call_timeout_s),
            streaming=kwargs.pop("streaming", settings.anthropic_streaming_enabled),
            streaming_read_timeout=kwargs.pop(
                "streaming_read_timeout", settings.anthropic_streaming_read_timeout_s
            ),
            **kwargs,
        )

    elif provider == "gemini":
        from .gemini_client import GeminiClient

        if not api_key:
            raise ValueError("Gemini API key required")

        resolved_model = model or _DEFAULT_MODELS["gemini"]
        client = GeminiClient(
            api_key=api_key,
            model=resolved_model,
            max_retries=kwargs.pop("max_retries", 5),
            **kwargs,
        )

    elif provider == "ollama":
        from .ollama_client import OllamaClient

        resolved_model = model or _DEFAULT_MODELS["ollama"]
        client = OllamaClient(
            model=resolved_model,
            base_url=base_url or "http://localhost:11434",
            max_retries=kwargs.pop("max_retries", 5),
            **kwargs,
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. Supported: openai, anthropic, gemini, ollama"
        )

    if instrument:
        from .instrumented import InstrumentedLLMClient

        client = InstrumentedLLMClient(client, provider=provider, model=resolved_model, stage=stage)

    return client


def get_model_id_from_client(client: LLMClient) -> str:
    """
    Извлечь model_id из LLM клиента.

    Args:
        client: LLM клиент instance

    Returns:
        Model ID строка
    """
    from .instrumented import InstrumentedLLMClient

    if isinstance(client, InstrumentedLLMClient):
        return client._model

    if hasattr(client, "model"):
        return client.model
    return "unknown"


def get_provider_from_client(client: LLMClient) -> str:
    """
    Определить провайдера по типу клиента.

    Args:
        client: LLM клиент instance

    Returns:
        Provider name
    """
    from .instrumented import InstrumentedLLMClient

    if isinstance(client, InstrumentedLLMClient):
        return client._provider

    class_name = client.__class__.__name__

    if "OpenAI" in class_name:
        return "openai"
    elif "Anthropic" in class_name:
        return "anthropic"
    elif "Gemini" in class_name:
        return "gemini"
    elif "Ollama" in class_name:
        return "ollama"
    else:
        return "unknown"
