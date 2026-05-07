"""Tests for ADR 0005 Session J: bot-scope LLM config in LLMConfigManager.

Covers T-1..T-8 + T-11 (settings layer).
Agent-layer tests (T-9..T-10) live in test_bot_agent_resolved_model.py.
"""

import pytest

from tg_parser.config.settings import LLM_SCOPES, LLMConfigManager


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

    bot_gemini_model = "gemini-2.5-flash"


@pytest.fixture(autouse=True)
def _clear_manager():
    """Ensure clean LLMConfigManager singleton state between tests."""
    LLMConfigManager.reset()
    yield
    LLMConfigManager.reset()


@pytest.fixture()
def manager():
    fake = _FakeSettings()
    LLMConfigManager.reset()
    return LLMConfigManager(fake)


# ── T-1 ─────────────────────────────────────────────────────────────────


def test_llm_scopes_includes_bot():
    assert "bot" in LLM_SCOPES


# ── T-2 ─────────────────────────────────────────────────────────────────


def test_resolve_bot_returns_gemini_defaults(manager):
    provider, api_key, model = manager.resolve("bot")
    assert provider == "gemini"
    assert model == "gemini-2.5-flash"
    assert api_key == "sk-gemini"


# ── T-3 ─────────────────────────────────────────────────────────────────


def test_set_bot_scope_gemini_succeeds(manager):
    manager.set("bot", "gemini", model="gemini-2.5-pro")
    _, _, model = manager.resolve("bot")
    assert model == "gemini-2.5-pro"


# ── T-4 ─────────────────────────────────────────────────────────────────


def test_set_bot_scope_non_gemini_raises(manager):
    with pytest.raises(ValueError, match="only supports provider='gemini'"):
        manager.set("bot", "anthropic", model="claude-sonnet-4")


# ── T-5 ─────────────────────────────────────────────────────────────────


def test_global_override_does_not_affect_bot_scope(manager):
    """D-1: global switch to non-Gemini must NOT break the bot agent."""
    manager.set("global", "anthropic", model="claude-sonnet-4")
    provider, _, model = manager.resolve("bot")
    assert provider == "gemini"
    assert model == "gemini-2.5-flash"


# ── T-6 ─────────────────────────────────────────────────────────────────


def test_resolve_bot_after_runtime_set(manager):
    manager.set("bot", "gemini", model="gemini-2.5-pro")
    provider, key, model = manager.resolve("bot")
    assert provider == "gemini"
    assert model == "gemini-2.5-pro"
    assert key == "sk-gemini"


# ── T-7 ─────────────────────────────────────────────────────────────────


def test_clear_bot_scope_reverts_to_default(manager):
    manager.set("bot", "gemini", model="gemini-2.5-pro")
    manager.clear("bot")
    _, _, model = manager.resolve("bot")
    assert model == "gemini-2.5-flash"


# ── T-8 ─────────────────────────────────────────────────────────────────


def test_get_all_includes_bot_stage(manager):
    config = manager.get_all()
    assert "bot" in config["stages"]
    assert config["stages"]["bot"]["provider"] == "gemini"


# ── T-11 ────────────────────────────────────────────────────────────────


def test_set_bot_scope_with_temperature_raises(manager):
    """D-2: bot scope is model-only — temperature/max_tokens must raise."""
    with pytest.raises(ValueError, match="model-only"):
        manager.set("bot", "gemini", model="gemini-2.5-pro", temperature=0.5)

    with pytest.raises(ValueError, match="model-only"):
        manager.set("bot", "gemini", model="gemini-2.5-pro", max_tokens=16384)
