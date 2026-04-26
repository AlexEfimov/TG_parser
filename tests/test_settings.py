"""Tests for top-level :class:`Settings` Pydantic fields.

Currently focused on TD-03b: Anthropic prompt-cache + token-estimate fields
that previously lived as ``getattr`` fallbacks on the runtime settings object
(silently ignoring the matching ``ANTHROPIC_*`` / ``PROCESSING_ANTHROPIC_*``
env vars). See REVIEW_2026-04-26 MERGED_PLAN S-003 / CODE-004.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tg_parser.config.settings import Settings


def test_anthropic_cap_settings_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Settings`` declares the three Anthropic cap/cache fields with documented defaults.

    Regression for REVIEW_2026-04-26 MERGED_PLAN S-003 (CODE-004): factory.py
    used to read these via ``getattr(settings, ...)`` so env-vars
    ``ANTHROPIC_PROMPT_CACHING_ENABLED`` /
    ``PROCESSING_ANTHROPIC_INPUT_TOKEN_ESTIMATE`` /
    ``PROCESSING_ANTHROPIC_OUTPUT_TOKEN_ESTIMATE`` were silently dropped by
    Pydantic's ``extra="ignore"`` and the hardcoded fallback was always used.

    This test guards three contracts:
    1. The three attributes exist on the Settings model.
    2. Defaults match production behavior (``True``, ``2000``, ``2048``)
       observed via the legacy ``getattr`` path — preserved exactly so this
       refactor doesn't change runtime behavior on hosts without env override.
    3. Env-var overrides are picked up by Pydantic.
    """
    for var in (
        "ANTHROPIC_PROMPT_CACHING_ENABLED",
        "PROCESSING_ANTHROPIC_INPUT_TOKEN_ESTIMATE",
        "PROCESSING_ANTHROPIC_OUTPUT_TOKEN_ESTIMATE",
    ):
        monkeypatch.delenv(var, raising=False)

    s = Settings()
    assert hasattr(s, "anthropic_prompt_caching_enabled")
    assert hasattr(s, "processing_anthropic_input_token_estimate")
    assert hasattr(s, "processing_anthropic_output_token_estimate")
    assert s.anthropic_prompt_caching_enabled is True
    assert s.processing_anthropic_input_token_estimate == 2000
    assert s.processing_anthropic_output_token_estimate == 2048

    monkeypatch.setenv("ANTHROPIC_PROMPT_CACHING_ENABLED", "false")
    monkeypatch.setenv("PROCESSING_ANTHROPIC_INPUT_TOKEN_ESTIMATE", "8000")
    monkeypatch.setenv("PROCESSING_ANTHROPIC_OUTPUT_TOKEN_ESTIMATE", "1500")

    s2 = Settings()
    assert s2.anthropic_prompt_caching_enabled is False
    assert s2.processing_anthropic_input_token_estimate == 8000
    assert s2.processing_anthropic_output_token_estimate == 1500


def test_anthropic_token_estimates_validate_bounds() -> None:
    """Token estimates respect the documented ``ge``/``le`` constraints.

    A regression that bumps the estimate to a non-positive number (or beyond
    Anthropic's hard model context limits) should fail-fast at Settings init,
    not silently propagate to the rate-limiter.
    """
    with pytest.raises(ValidationError):
        Settings(processing_anthropic_input_token_estimate=0)
    with pytest.raises(ValidationError):
        Settings(processing_anthropic_input_token_estimate=300_000)
    with pytest.raises(ValidationError):
        Settings(processing_anthropic_output_token_estimate=0)
    with pytest.raises(ValidationError):
        Settings(processing_anthropic_output_token_estimate=128_000)
