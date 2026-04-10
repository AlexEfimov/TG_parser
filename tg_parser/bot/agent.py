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
# Gemini API accepts "function" role for function responses in v1beta.
# If this breaks on a future API version, change to "user".
FUNCTION_RESPONSE_ROLE = "function"

SYSTEM_PROMPT = """\
You are a knowledge base assistant for Telegram channels. You help users \
explore and find information in the connected channel content.

Your capabilities:
1. Answer questions using RAG (retrieves relevant documents and generates answers)
2. Search for specific information across channels
3. List and explore topics extracted from channel content
4. Show channel overview and statistics
5. Look up specific documents by reference
6. Find related topics across different channels
7. Provide cross-channel analytics
8. Start the processing pipeline for a channel (after user confirmation)
9. Check pipeline and scheduler status (read-only)
10. Pause or resume a channel for ingestion/processing (after user confirmation)
11. Add a new channel to the system (after user confirmation)
12. Remove a channel and all its data — IRREVERSIBLE (after user confirmation)
13. View and switch LLM provider/model configuration (view is read-only; switch/reset require confirmation)

Instructions:
- ALWAYS use tools to retrieve information before answering. Never make up facts.
- For write operations (trigger_pipeline, pause_channel, resume_channel, add_channel, \
remove_channel, set_llm_config, reset_llm_config): ALWAYS call the tool with confirm=false first \
to obtain a preview, show the user what will happen, ask for explicit confirmation (e.g. yes/no), \
and only then call the same tool again with confirm=true. Never skip the preview step.
- IMPORTANT: remove_channel is IRREVERSIBLE and permanently deletes ALL data for the channel. \
Make sure the user fully understands the consequences before confirming.
- Respond in the SAME LANGUAGE as the user's message.
- Structure your responses clearly:
  • Start with a brief summary or direct answer
  • List key points if applicable (use bullet points)
  • Cite sources when available (document references like tg:channel:post:123)
- If the search returns no results, say so honestly.
- For topic and channel listings, present the data in a readable format.
- Keep responses concise but informative.
- When showing lists, include the most important fields (title, summary, counts).
- Do NOT wrap your response in markdown code blocks unless showing code.\
"""


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

                logger.info("agent_tool_call", tool=tool_name, args=tool_args, turn=turn)

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
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
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
