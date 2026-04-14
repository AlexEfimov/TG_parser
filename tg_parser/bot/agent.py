"""
Gemini agent with function-calling for the Telegram bot.

Receives a free-form user message, uses Gemini to decide which internal
capabilities to invoke, executes them, and returns a structured answer.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from tg_parser.bot.tools import TOOL_DECLARATIONS, execute_tool

logger = structlog.get_logger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_AGENT_TURNS = 5
FUNCTION_RESPONSE_ROLE = "function"


def _load_bot_system_prompt() -> str:
    """Load the bot system prompt from YAML (with built-in fallback)."""
    from tg_parser.processing.prompt_loader import get_prompt_loader
    return get_prompt_loader().get_system_prompt("bot")


class GeminiAgent:
    """Agentic orchestrator that uses Gemini function-calling to route
    user messages to internal services and compose structured answers."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._tool_timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))
        self._system_prompt = _load_bot_system_prompt()

    def reload_prompt(self) -> None:
        """Reload the system prompt from YAML (called after reload_prompts)."""
        self._system_prompt = _load_bot_system_prompt()

    async def process_message(self, user_message: str) -> str:
        """Process a user message through the agent loop.

        Returns the final text response to send to the user.
        """
        contents: list[dict[str, Any]] = [
            {"role": "user", "parts": [{"text": user_message}]},
        ]

        for turn in range(MAX_AGENT_TURNS):
            response = await self._call_gemini(contents)

            if "error" in response:
                logger.error("gemini_api_error", error=response["error"])
                return "Произошла ошибка при обращении к LLM. Попробуйте позже."

            candidates = response.get("candidates", [])
            if not candidates:
                block_reason = response.get("promptFeedback", {}).get("blockReason")
                if block_reason:
                    logger.warning("gemini_blocked", reason=block_reason)
                    return "Запрос был заблокирован фильтрами безопасности LLM."
                return "Не удалось получить ответ от LLM."

            candidate = candidates[0]
            finish_reason = candidate.get("finishReason", "")
            if finish_reason == "SAFETY":
                logger.warning("gemini_safety_stop")
                return "Ответ был заблокирован фильтрами безопасности LLM."

            parts = candidate.get("content", {}).get("parts", [])

            if not parts:
                return "Не удалось получить ответ от LLM."

            function_calls = [p for p in parts if "functionCall" in p]

            if not function_calls:
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                return "\n".join(text_parts).strip() or "Пустой ответ от LLM."

            contents.append({"role": "model", "parts": parts})

            function_responses = []
            for fc_part in function_calls:
                fc = fc_part["functionCall"]
                tool_name = fc["name"]
                tool_args = fc.get("args", {})

                logger.info("agent_tool_call", tool=tool_name, turn=turn)
                logger.debug("agent_tool_call_args", tool=tool_name, args=tool_args, turn=turn)

                result = await execute_tool(
                    tool_name, tool_args, timeout=self._tool_timeout,
                )

                function_responses.append({
                    "functionResponse": {
                        "name": tool_name,
                        "response": _safe_serialize(result),
                    },
                })

            contents.append({"role": FUNCTION_RESPONSE_ROLE, "parts": function_responses})

        return (
            "Не удалось получить окончательный ответ после нескольких попыток. "
            "Попробуйте переформулировать вопрос."
        )

    async def _call_gemini(self, contents: list[dict]) -> dict[str, Any]:
        """Make a single Gemini API call with tool declarations."""
        url = f"{GEMINI_API_BASE}/{self._model}:generateContent"

        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": self._system_prompt}]},
            "contents": contents,
            "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
            "toolConfig": {
                "functionCallingConfig": {"mode": "AUTO"},
            },
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            },
        }

        try:
            resp = await self._client.post(
                url, json=payload, params={"key": self._api_key},
            )

            if resp.status_code != 200:
                error_text = resp.text[:500]
                logger.error(
                    "gemini_http_error", status=resp.status_code, body=error_text,
                )
                return {"error": f"Gemini API returned {resp.status_code}: {error_text}"}

            data = resp.json()

            usage = data.get("usageMetadata", {})
            logger.debug(
                "gemini_response",
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
            )

            return data

        except httpx.TimeoutException:
            logger.warning("gemini_timeout")
            return {"error": "Gemini API request timed out"}
        except Exception:
            logger.exception("gemini_request_failed")
            return {"error": "Failed to call Gemini API"}

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


def _safe_serialize(obj: Any) -> Any:
    """Ensure the object is JSON-serializable for the Gemini API."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return {"result": str(obj)}
