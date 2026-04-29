"""Regression suite for ``tg_parser.bot.agent.GeminiAgent`` — BUG-006 closure.

Five areas under test:

* **Generation-config wiring** — ``maxOutputTokens`` / ``thinkingBudget``
  flow from constructor → outgoing Gemini payload. The ``thinking_budget=None``
  sentinel must omit ``thinkingConfig`` entirely (preserving SDK default
  for non-2.5 models).
* **Empty-parts classification by ``finishReason``** — ``MAX_TOKENS`` /
  ``RECITATION`` / ``MALFORMED_FUNCTION_CALL`` / ``OTHER`` / unknown each
  surface a distinct user-facing message.
* **No-candidates branches** — ``promptFeedback.blockReason`` (safety
  block) vs genuine empty must split into different messages and metric
  labels.
* **Prometheus metric** — :data:`BOT_GEMINI_EMPTY_PARTS_TOTAL` increments
  on every empty-parts / no-candidates path with the correct label set.
* **BUG-006 regression** — the original "Покажи LLM конфиг" trace shape
  (``finishReason="MAX_TOKENS"``, empty parts) returns the
  MAX_TOKENS-specific message, not the pre-fix generic
  «Не удалось получить ответ от LLM».
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.api.metrics import BOT_GEMINI_EMPTY_PARTS_TOTAL
from tg_parser.bot.agent import (
    _EMPTY_PARTS_GENERIC_MESSAGE,
    AgentResult,
    GeminiAgent,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _gemini_text(text: str) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 50,
        },
    }


def _gemini_empty_parts(finish_reason: str) -> dict[str, Any]:
    """Reproduces the BUG-006 wire-shape: HTTP 200, candidate present, ``parts=[]``."""
    candidate: dict[str, Any] = {"content": {"parts": []}}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    return {
        "candidates": [candidate],
        "usageMetadata": {
            "promptTokenCount": 12000,
            "candidatesTokenCount": 0,
            "thoughtsTokenCount": 4096,
        },
    }


def _gemini_no_candidates(*, blocked: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"candidates": []}
    if blocked:
        payload["promptFeedback"] = {"blockReason": blocked}
    return payload


def _label(model: str, finish_reason: str) -> dict[str, str]:
    return {"model": model, "finish_reason": finish_reason}


def _metric_value(model: str, finish_reason: str) -> float:
    """Read the current value of the (model, finish_reason) counter cell."""
    return BOT_GEMINI_EMPTY_PARTS_TOTAL.labels(**_label(model, finish_reason))._value.get()


# ---------------------------------------------------------------------------
# Generation-config wiring — payload shape sent to Gemini
# ---------------------------------------------------------------------------


class TestGenerationConfigWiring:
    """``maxOutputTokens`` and ``thinkingBudget`` must be plumbed through."""

    @pytest.mark.asyncio
    async def test_default_payload_carries_thinking_budget_zero(self) -> None:
        agent = GeminiAgent(api_key="test-key")
        captured: dict[str, Any] = {}

        async def fake_post(url: str, **kwargs: Any) -> Any:
            captured["payload"] = kwargs.get("json")
            from unittest.mock import MagicMock

            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: _gemini_text("ok")
            return resp

        with patch.object(agent._client, "post", side_effect=fake_post):
            await agent._call_gemini([{"role": "user", "parts": [{"text": "hi"}]}])

        gen = captured["payload"]["generationConfig"]
        # Defaults: max_output_tokens=8192, thinking_budget=0.
        assert gen["maxOutputTokens"] == 8192
        assert gen["thinkingConfig"] == {"thinkingBudget": 0}

    @pytest.mark.asyncio
    async def test_explicit_thinking_budget_none_omits_thinking_config(self) -> None:
        agent = GeminiAgent(api_key="test-key", thinking_budget=None)
        captured: dict[str, Any] = {}

        async def fake_post(url: str, **kwargs: Any) -> Any:
            captured["payload"] = kwargs.get("json")
            from unittest.mock import MagicMock

            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: _gemini_text("ok")
            return resp

        with patch.object(agent._client, "post", side_effect=fake_post):
            await agent._call_gemini([{"role": "user", "parts": [{"text": "hi"}]}])

        # ``None`` sentinel = use SDK default; do not emit thinkingConfig at all.
        assert "thinkingConfig" not in captured["payload"]["generationConfig"]

    @pytest.mark.asyncio
    async def test_custom_max_output_tokens_is_propagated(self) -> None:
        agent = GeminiAgent(api_key="test-key", max_output_tokens=16384)
        captured: dict[str, Any] = {}

        async def fake_post(url: str, **kwargs: Any) -> Any:
            captured["payload"] = kwargs.get("json")
            from unittest.mock import MagicMock

            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: _gemini_text("ok")
            return resp

        with patch.object(agent._client, "post", side_effect=fake_post):
            await agent._call_gemini([{"role": "user", "parts": [{"text": "hi"}]}])

        assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 16384


# ---------------------------------------------------------------------------
# Empty-parts classification — finish_reason → user message
# ---------------------------------------------------------------------------


class TestEmptyPartsClassification:
    """``parts=[]`` paths must split by ``finishReason``."""

    @pytest.mark.asyncio
    async def test_max_tokens_returns_specific_message(self) -> None:
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "MAX_TOKENS")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_empty_parts("MAX_TOKENS")),
        ):
            result = await agent.process_message("Покажи LLM конфиг")

        assert isinstance(result, AgentResult)
        assert "исчерпал бюджет" in result.response_text
        assert "Не удалось получить ответ от LLM" not in result.response_text
        # Metric must have advanced exactly by 1 on the MAX_TOKENS cell.
        assert _metric_value("gemini-2.5-flash", "MAX_TOKENS") == pytest.approx(before + 1)

    @pytest.mark.asyncio
    async def test_recitation_returns_specific_message(self) -> None:
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "RECITATION")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_empty_parts("RECITATION")),
        ):
            result = await agent.process_message("test")

        assert "recitation" in result.response_text.lower()
        assert _metric_value("gemini-2.5-flash", "RECITATION") == pytest.approx(before + 1)

    @pytest.mark.asyncio
    async def test_malformed_function_call_returns_specific_message(self) -> None:
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "MALFORMED_FUNCTION_CALL")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_empty_parts("MALFORMED_FUNCTION_CALL")),
        ):
            result = await agent.process_message("test")

        assert "некорректный вызов" in result.response_text
        assert _metric_value("gemini-2.5-flash", "MALFORMED_FUNCTION_CALL") == pytest.approx(
            before + 1
        )

    @pytest.mark.asyncio
    async def test_safety_finish_reason_returns_safety_message(self) -> None:
        """``finishReason=SAFETY`` is its own short-circuit before the parts check."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "SAFETY")

        # Note: SAFETY-stop responses sometimes include parts, sometimes not —
        # the agent's pre-existing logic short-circuits on the finishReason.
        payload: dict[str, Any] = {
            "candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}],
        }
        with patch.object(agent, "_call_gemini", new=AsyncMock(return_value=payload)):
            result = await agent.process_message("test")

        assert "безопасности" in result.response_text
        assert _metric_value("gemini-2.5-flash", "SAFETY") == pytest.approx(before + 1)

    @pytest.mark.asyncio
    async def test_empty_parts_no_finish_reason_returns_generic_message(self) -> None:
        """``parts=[]`` with no ``finishReason`` (HG-5/HG-7) → generic empty-LLM message."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "none")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_empty_parts("")),
        ):
            result = await agent.process_message("test")

        assert result.response_text == _EMPTY_PARTS_GENERIC_MESSAGE
        assert _metric_value("gemini-2.5-flash", "none") == pytest.approx(before + 1)

    @pytest.mark.asyncio
    async def test_empty_parts_unknown_finish_reason_returns_generic_message(
        self,
    ) -> None:
        """A new / unmapped ``finishReason`` falls through to generic, no crash."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "FUTURE_REASON")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_empty_parts("FUTURE_REASON")),
        ):
            result = await agent.process_message("test")

        assert result.response_text == _EMPTY_PARTS_GENERIC_MESSAGE
        assert _metric_value("gemini-2.5-flash", "FUTURE_REASON") == pytest.approx(before + 1)


# ---------------------------------------------------------------------------
# No-candidates branches — safety block vs generic
# ---------------------------------------------------------------------------


class TestNoCandidatesBranches:
    """``candidates=[]`` must split into ``blocked`` vs ``no_candidates`` cells."""

    @pytest.mark.asyncio
    async def test_block_reason_returns_safety_message(self) -> None:
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "blocked")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_no_candidates(blocked="SAFETY")),
        ):
            result = await agent.process_message("test")

        assert "безопасности" in result.response_text
        assert _metric_value("gemini-2.5-flash", "blocked") == pytest.approx(before + 1)

    @pytest.mark.asyncio
    async def test_no_candidates_no_block_returns_specific_message(self) -> None:
        """Genuine empty (no ``promptFeedback.blockReason``) → distinct copy + metric."""
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before = _metric_value("gemini-2.5-flash", "no_candidates")

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_no_candidates()),
        ):
            result = await agent.process_message("test")

        assert "ни одного кандидата" in result.response_text
        # Pre-fix this returned «Не удалось получить ответ от LLM.» — guard
        # against accidental regression.
        assert "Не удалось получить ответ от LLM" not in result.response_text
        assert _metric_value("gemini-2.5-flash", "no_candidates") == pytest.approx(before + 1)


# ---------------------------------------------------------------------------
# Successful path is unchanged — guard against regression
# ---------------------------------------------------------------------------


class TestHappyPathUnchanged:
    @pytest.mark.asyncio
    async def test_text_response_does_not_increment_empty_parts(self) -> None:
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        before_total = sum(
            cell._value.get() for cell in BOT_GEMINI_EMPTY_PARTS_TOTAL._metrics.values()
        )

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_text("Hello")),
        ):
            result = await agent.process_message("hi")

        assert result.response_text == "Hello"
        after_total = sum(
            cell._value.get() for cell in BOT_GEMINI_EMPTY_PARTS_TOTAL._metrics.values()
        )
        assert after_total == pytest.approx(before_total)


# ---------------------------------------------------------------------------
# BUG-006 regression — the original failing trace must now succeed
# ---------------------------------------------------------------------------


class TestBug006Regression:
    """The original 23:51 ``Покажи LLM конфиг`` trace must surface
    a specific, actionable user message, not the generic pre-fix string."""

    @pytest.mark.asyncio
    async def test_pokazhi_llm_config_returns_max_tokens_message(self) -> None:
        """Reproduces BUG-006: empty parts + finishReason=MAX_TOKENS."""
        agent = GeminiAgent(
            api_key="test-key",
            model="gemini-2.5-flash",
            max_output_tokens=8192,
            thinking_budget=0,
        )

        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_empty_parts("MAX_TOKENS")),
        ):
            result = await agent.process_message("Покажи LLM конфиг")

        # Pre-fix string — must NOT appear post-fix.
        assert result.response_text != "Не удалось получить ответ от LLM."
        # Post-fix copy — actionable, points to budget exhaustion.
        assert "исчерпал бюджет" in result.response_text
        assert "упростить" in result.response_text or "разбейте" in result.response_text

    @pytest.mark.asyncio
    async def test_payload_carries_thinking_budget_zero_for_bug006_hotfix(
        self,
    ) -> None:
        """The Session E hotfix is ``thinkingBudget=0``; verify it's wired."""
        agent = GeminiAgent(
            api_key="test-key",
            model="gemini-2.5-flash",
            max_output_tokens=8192,
            thinking_budget=0,
        )
        captured: dict[str, Any] = {}

        async def fake_post(url: str, **kwargs: Any) -> Any:
            captured["payload"] = kwargs.get("json")
            from unittest.mock import MagicMock

            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: _gemini_text("ok")
            return resp

        with patch.object(agent._client, "post", side_effect=fake_post):
            await agent._call_gemini([{"role": "user", "parts": [{"text": "Покажи LLM конфиг"}]}])

        gen = captured["payload"]["generationConfig"]
        assert gen["maxOutputTokens"] == 8192
        assert gen["thinkingConfig"]["thinkingBudget"] == 0
