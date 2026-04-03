"""Tests for Session 28: resolve_llm_config, shared rate limiter cache,
and runtime LLM config switching via LLMConfigManager."""

from unittest.mock import patch

import pytest

from tg_parser.config.settings import LLMConfigManager
from tg_parser.processing.llm.factory import (
    _get_or_create_rate_limiter,
    _rate_limiter_cache,
    resolve_llm_config,
)


class _FakeSettings:
    """Minimal stand-in for tg_parser.config.Settings."""

    llm_provider = "openai"
    llm_model = "gpt-4o-mini"

    processing_llm_provider = None
    processing_llm_model = None
    topicization_llm_provider = None
    topicization_llm_model = None

    openai_api_key = "sk-openai"
    anthropic_api_key = "sk-anthropic"
    gemini_api_key = "sk-gemini"
    google_api_key = None

    # Rate limiter fields used by LLMRateLimiter.from_settings
    processing_rate_limit_rpm = 50
    processing_rate_limit_itpm = 30_000
    processing_rate_limit_otpm = 8_000


@pytest.fixture(autouse=True)
def _clear_caches():
    """Ensure clean cache and LLMConfigManager state between tests."""
    _rate_limiter_cache.clear()
    yield
    _rate_limiter_cache.clear()
    LLMConfigManager.reset()


def _patch_llm_config(fake: _FakeSettings):
    """Replace the global llm_config singleton with one backed by *fake*."""
    LLMConfigManager.reset()
    mgr = LLMConfigManager(fake)
    return patch("tg_parser.config.llm_config", mgr)


# ── resolve_llm_config: fallback to global ──────────────────────────────


def test_resolve_fallback_to_global():
    fake = _FakeSettings()
    with _patch_llm_config(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "openai"
    assert api_key == "sk-openai"
    assert model == "gpt-4o-mini"


def test_resolve_fallback_topicization():
    fake = _FakeSettings()
    with _patch_llm_config(fake):
        provider, api_key, model = resolve_llm_config("topicization")
    assert provider == "openai"
    assert api_key == "sk-openai"
    assert model == "gpt-4o-mini"


# ── resolve_llm_config: per-stage override ──────────────────────────────


def test_resolve_per_stage_override_processing():
    fake = _FakeSettings()
    fake.processing_llm_provider = "anthropic"
    fake.processing_llm_model = "claude-3-5-haiku-20241022"
    with _patch_llm_config(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "anthropic"
    assert api_key == "sk-anthropic"
    assert model == "claude-3-5-haiku-20241022"


def test_resolve_per_stage_override_topicization():
    fake = _FakeSettings()
    fake.topicization_llm_provider = "gemini"
    fake.topicization_llm_model = "gemini-2.0-pro"
    with _patch_llm_config(fake):
        provider, api_key, model = resolve_llm_config("topicization")
    assert provider == "gemini"
    assert api_key == "sk-gemini"
    assert model == "gemini-2.0-pro"


# ── resolve_llm_config: mixed providers ─────────────────────────────────


def test_resolve_mixed_providers():
    """Processing on Haiku, topicization on Sonnet — different providers possible."""
    fake = _FakeSettings()
    fake.processing_llm_provider = "anthropic"
    fake.processing_llm_model = "claude-3-5-haiku-20241022"
    fake.topicization_llm_provider = "openai"
    fake.topicization_llm_model = "gpt-4o"
    with _patch_llm_config(fake):
        p_provider, p_key, p_model = resolve_llm_config("processing")
        t_provider, t_key, t_model = resolve_llm_config("topicization")

    assert p_provider == "anthropic"
    assert p_key == "sk-anthropic"
    assert p_model == "claude-3-5-haiku-20241022"

    assert t_provider == "openai"
    assert t_key == "sk-openai"
    assert t_model == "gpt-4o"


def test_resolve_ollama_no_key():
    fake = _FakeSettings()
    fake.processing_llm_provider = "ollama"
    fake.processing_llm_model = "llama3.2"
    with _patch_llm_config(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "ollama"
    assert api_key is None
    assert model == "llama3.2"


def test_resolve_partial_override_provider_only():
    """Override provider but not model → model falls back to global."""
    fake = _FakeSettings()
    fake.processing_llm_provider = "anthropic"
    with _patch_llm_config(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "anthropic"
    assert api_key == "sk-anthropic"
    assert model == "gpt-4o-mini"  # global fallback


# ── Shared rate limiter cache ────────────────────────────────────────────


def test_shared_rate_limiter_same_key():
    """Two calls with the same API key must return the same instance."""
    with patch("tg_parser.config.settings", _FakeSettings()):
        rl1 = _get_or_create_rate_limiter("sk-anthropic")
        rl2 = _get_or_create_rate_limiter("sk-anthropic")
    assert rl1 is rl2


def test_shared_rate_limiter_different_keys():
    """Different API keys get separate limiters."""
    with patch("tg_parser.config.settings", _FakeSettings()):
        rl1 = _get_or_create_rate_limiter("sk-key-a")
        rl2 = _get_or_create_rate_limiter("sk-key-b")
    assert rl1 is not rl2


# ── LLMConfigManager: runtime switching ──────────────────────────────────


def test_runtime_override_global():
    """Setting a global runtime override affects all stages."""
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)

    mgr.set("global", "gemini", "gemini-2.0-flash")

    provider, api_key, model = mgr.resolve("processing")
    assert provider == "gemini"
    assert api_key == "sk-gemini"
    assert model == "gemini-2.0-flash"

    provider, api_key, model = mgr.resolve("topicization")
    assert provider == "gemini"
    assert model == "gemini-2.0-flash"


def test_runtime_override_stage_takes_precedence():
    """Stage-level override beats global override."""
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)

    mgr.set("global", "gemini")
    mgr.set("processing", "anthropic", "claude-sonnet-4-20250514")

    p, _, m = mgr.resolve("processing")
    assert p == "anthropic"
    assert m == "claude-sonnet-4-20250514"

    p, _, m = mgr.resolve("topicization")
    assert p == "gemini"


def test_runtime_clear_scope():
    """Clearing a scope reverts only that scope."""
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)

    mgr.set("global", "gemini")
    mgr.set("processing", "anthropic")
    mgr.clear("processing")

    p, _, _ = mgr.resolve("processing")
    assert p == "gemini"  # falls back to global override


def test_runtime_clear_all():
    """Clearing all overrides reverts to static settings."""
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)

    mgr.set("global", "gemini")
    mgr.set("processing", "anthropic")
    mgr.clear()

    p, _, m = mgr.resolve("processing")
    assert p == "openai"
    assert m == "gpt-4o-mini"


def test_runtime_set_invalid_provider():
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)
    with pytest.raises(ValueError, match="Unsupported provider"):
        mgr.set("global", "invalid-provider")


def test_runtime_set_missing_api_key():
    fake = _FakeSettings()
    fake.gemini_api_key = None
    fake.google_api_key = None
    mgr = LLMConfigManager(fake)
    with pytest.raises(ValueError, match="No API key"):
        mgr.set("global", "gemini")


def test_runtime_set_invalid_scope():
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)
    with pytest.raises(ValueError, match="Invalid scope"):
        mgr.set("invalid-scope", "openai")


def test_get_all_shows_overrides():
    fake = _FakeSettings()
    mgr = LLMConfigManager(fake)

    mgr.set("processing", "anthropic", "claude-sonnet-4-20250514")
    config = mgr.get_all()

    assert config["stages"]["processing"]["provider"] == "anthropic"
    assert config["stages"]["processing"]["model"] == "claude-sonnet-4-20250514"
    assert config["stages"]["processing"]["overridden"] is True
    assert config["stages"]["topicization"]["overridden"] is False
    assert config["available_providers"]["openai"] is True
    assert config["available_providers"]["ollama"] is True
