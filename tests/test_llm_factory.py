"""Tests for Session 28: resolve_llm_config and shared rate limiter cache."""

from unittest.mock import patch

import pytest

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
def _clear_rate_limiter_cache():
    """Ensure clean cache between tests."""
    _rate_limiter_cache.clear()
    yield
    _rate_limiter_cache.clear()


SETTINGS_PATH = "tg_parser.processing.llm.factory.resolve_llm_config.__code__"


def _patch_settings(fake: _FakeSettings):
    return patch("tg_parser.config.settings", fake)


# ── resolve_llm_config: fallback to global ──────────────────────────────


def test_resolve_fallback_to_global():
    fake = _FakeSettings()
    with _patch_settings(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "openai"
    assert api_key == "sk-openai"
    assert model == "gpt-4o-mini"


def test_resolve_fallback_topicization():
    fake = _FakeSettings()
    with _patch_settings(fake):
        provider, api_key, model = resolve_llm_config("topicization")
    assert provider == "openai"
    assert api_key == "sk-openai"
    assert model == "gpt-4o-mini"


# ── resolve_llm_config: per-stage override ──────────────────────────────


def test_resolve_per_stage_override_processing():
    fake = _FakeSettings()
    fake.processing_llm_provider = "anthropic"
    fake.processing_llm_model = "claude-3-5-haiku-20241022"
    with _patch_settings(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "anthropic"
    assert api_key == "sk-anthropic"
    assert model == "claude-3-5-haiku-20241022"


def test_resolve_per_stage_override_topicization():
    fake = _FakeSettings()
    fake.topicization_llm_provider = "gemini"
    fake.topicization_llm_model = "gemini-2.0-pro"
    with _patch_settings(fake):
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
    with _patch_settings(fake):
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
    with _patch_settings(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "ollama"
    assert api_key is None
    assert model == "llama3.2"


def test_resolve_partial_override_provider_only():
    """Override provider but not model → model falls back to global."""
    fake = _FakeSettings()
    fake.processing_llm_provider = "anthropic"
    with _patch_settings(fake):
        provider, api_key, model = resolve_llm_config("processing")
    assert provider == "anthropic"
    assert api_key == "sk-anthropic"
    assert model == "gpt-4o-mini"  # global fallback


# ── Shared rate limiter cache ────────────────────────────────────────────


def test_shared_rate_limiter_same_key():
    """Two calls with the same API key must return the same instance."""
    with _patch_settings(_FakeSettings()):
        rl1 = _get_or_create_rate_limiter("sk-anthropic")
        rl2 = _get_or_create_rate_limiter("sk-anthropic")
    assert rl1 is rl2


def test_shared_rate_limiter_different_keys():
    """Different API keys get separate limiters."""
    with _patch_settings(_FakeSettings()):
        rl1 = _get_or_create_rate_limiter("sk-key-a")
        rl2 = _get_or_create_rate_limiter("sk-key-b")
    assert rl1 is not rl2
