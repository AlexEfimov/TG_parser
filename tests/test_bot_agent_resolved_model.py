"""Tests for ADR 0005 Session J: GeminiAgent._resolved_model() dynamic dispatch.

T-9..T-10 (agent layer). Kept separate from test_settings_bot_scope.py
because these tests mock the global singleton tg_parser.config.llm_config.
"""

from unittest.mock import patch

import pytest

from tg_parser.bot.agent import GeminiAgent
from tg_parser.config.settings import LLMConfigManager


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
    LLMConfigManager.reset()
    yield
    LLMConfigManager.reset()


# ── T-9 ─────────────────────────────────────────────────────────────────


def test_gemini_agent_resolved_model_uses_llm_config():
    """_resolved_model() returns the runtime override, not the init-time default."""
    fake = _FakeSettings()
    LLMConfigManager.reset()
    mgr = LLMConfigManager(fake)
    mgr.set("bot", "gemini", model="gemini-2.5-pro")

    agent = GeminiAgent(api_key="sk-gemini", model="gemini-2.5-flash")
    with patch("tg_parser.config.llm_config", mgr):
        assert agent._resolved_model() == "gemini-2.5-pro"


# ── T-10 ────────────────────────────────────────────────────────────────


def test_gemini_agent_resolved_model_falls_back_on_error():
    """_resolved_model() falls back to self._model when singleton is unavailable."""
    LLMConfigManager.reset()
    agent = GeminiAgent(api_key="sk-gemini", model="gemini-2.5-flash")

    # Patch llm_config.resolve to raise so we exercise the except branch.
    broken = object()  # has no .resolve() — AttributeError inside try/except
    with patch("tg_parser.config.llm_config", broken):
        assert agent._resolved_model() == "gemini-2.5-flash"
