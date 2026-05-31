"""
Gemini agent with function-calling for the Telegram bot.

Receives a free-form user message, uses Gemini to decide which internal
capabilities to invoke, executes them, and returns a structured answer.

BUG-006 (Session E, 2026-04-29) hardening:

* ``maxOutputTokens`` and ``thinkingConfig.thinkingBudget`` are now
  configurable (defaults: ``8192`` and ``0`` respectively). The
  thinking-budget=0 default kills the HG-2 root cause — Gemini-2.5-flash
  used to silently siphon the 4096-token output budget into "thinking"
  on 30+ tool deck disambiguation queries and return ``parts=[]``.
* Empty-parts / no-candidates branches now classify by
  ``candidates[0].finishReason`` and emit specific user-facing messages
  for ``MAX_TOKENS`` / ``RECITATION`` / unknown, plus a Prometheus
  counter (:data:`BOT_GEMINI_EMPTY_PARTS_TOTAL`) for post-deploy
  monitoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from tg_parser.api.metrics import record_bot_gemini_empty_parts
from tg_parser.auth.models import CurrentUser
from tg_parser.bot.states import ReadContextData
from tg_parser.bot.tools import (
    _READ_TOOLS_TRACKED_FOR_CONTEXT,
    TOOL_DECLARATIONS,
    execute_tool,
)

if TYPE_CHECKING:
    from aiogram import Bot

logger = structlog.get_logger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_AGENT_TURNS = 5
FUNCTION_RESPONSE_ROLE = "function"

# Cap for the Gemini response payload dump in logs when we land on the
# empty-parts branch. 2048 chars is enough to recognise finishReason +
# usageMetadata + first chunk of safetyRatings without exploding journald.
EMPTY_PARTS_LOG_DUMP_CAP = 2048

# Default user-facing messages keyed by ``finishReason`` for the
# empty-parts branch. Anything missing falls through to the generic
# message — see :func:`_empty_parts_message`.
_EMPTY_PARTS_MESSAGES: dict[str, str] = {
    "MAX_TOKENS": (
        "LLM исчерпал бюджет ответа на этот запрос. "
        "Попробуйте упростить вопрос или разбейте на части."
    ),
    "RECITATION": ("LLM отказался ответить (recitation guard). Попробуйте переформулировать."),
    "MALFORMED_FUNCTION_CALL": (
        "LLM сформировал некорректный вызов инструмента. Попробуйте переформулировать запрос."
    ),
    "SAFETY": "Ответ был заблокирован фильтрами безопасности LLM.",
    "OTHER": (
        "LLM остановил генерацию по неизвестной причине. "
        "Попробуйте через минуту или переформулируйте."
    ),
}

_EMPTY_PARTS_GENERIC_MESSAGE = (
    "LLM вернул пустой ответ. Возможно, сейчас перегрузка — попробуйте через минуту."
)


def _empty_parts_message(finish_reason: str) -> str:
    """Pick the user-facing message for the empty-parts branch."""
    return _EMPTY_PARTS_MESSAGES.get(finish_reason, _EMPTY_PARTS_GENERIC_MESSAGE)


@dataclass
class AgentResult:
    """Structured outcome of one ``process_message`` invocation.

    ``response_text`` is the user-facing text produced by the LLM.
    ``preview_pending`` and ``pagination_pending`` carry FSM hints back to
    the handler so it can transition the chat into ``ConfirmFlow`` /
    ``PaginationFlow`` and execute the follow-up action deterministically
    (closes BUG-002 / BUG-004).

    ``read_tools_called`` is a list of (tool_name, args) tuples for every
    tracked read-tool call made during this invocation. The handler iterates
    in order and calls ``_refresh_read_context`` so FSMContext always holds
    the LATEST channel_id from this turn (BUG-011, Session H).

    ``preview_pending`` shape::

        {"tool_name": str, "args": dict[str, Any]}  # original args sans confirm

    ``pagination_pending`` shape (populated in commit 4)::

        {"tool_name": str, "args": dict, "total": int, "offset": int, "limit": int}
    """

    response_text: str
    preview_pending: dict[str, Any] | None = None
    pagination_pending: dict[str, Any] | None = None
    read_tools_called: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # BUG-042: the tool's OWN preview ``message`` captured verbatim so the
    # handler can render the preview deterministically instead of letting the
    # LLM paraphrase it (which truncated the cron «0 * * * *» → «0»). ``None``
    # when the tool result carried no preview message.
    preview_message: str | None = None
    # BUG-039 / BUG-040: clarify FSM hint. Populated when a ``subscribe_*``
    # tool rejects a channel name with a ``suggestion`` — the handler arms
    # ``ClarifyFlow.awaiting_channel_clarification`` so an affirmative «да» or
    # a bare channel-name reply re-runs the previewed subscribe with the
    # corrected channel id, deterministically (no stateless LLM re-route).
    #
    # ``clarify_pending`` shape::
    #
    #     {"tool_name": str, "args": dict, "channel_index": int, "suggestion": str}
    clarify_pending: dict[str, Any] | None = None


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
        max_output_tokens: int = 8192,
        thinking_budget: int | None = 0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._tool_timeout = timeout
        self._max_output_tokens = max_output_tokens
        self._thinking_budget = thinking_budget
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))
        self._system_prompt = _load_bot_system_prompt()

    def reload_prompt(self) -> None:
        """Reload the system prompt from YAML (called after reload_prompts)."""
        self._system_prompt = _load_bot_system_prompt()

    def _resolved_model(self) -> str:
        """Return current model from LLMConfigManager (BUG-safe fallback to init default).

        Called on every _call_gemini invocation so runtime set_llm_config(scope='bot')
        takes effect immediately without agent restart (ADR 0005 Session J).
        """
        try:
            from tg_parser.config import llm_config

            _, _, model = llm_config.resolve("bot")
            return model or self._model
        except Exception:
            return self._model

    async def process_message(
        self,
        user_message: str,
        current_user: CurrentUser | None = None,
        bot: Bot | None = None,
        chat_id: int | None = None,
        read_context: ReadContextData | None = None,
    ) -> AgentResult:
        """Process a user message through the agent loop.

        ``bot`` and ``chat_id`` are forwarded to tool executors that need
        direct chat access (e.g. ``export_channel`` to upload files).

        ``read_context`` is the non-stale FSMContext read-context from the
        handler (BUG-011, Session H). When present it is injected into
        ``systemInstruction`` so the LLM can resolve implicit channel
        references on this turn.

        Returns an :class:`AgentResult` so the handler can pick up
        ``preview_pending`` / ``pagination_pending`` hints and switch the
        chat FSM accordingly (BUG-002 / BUG-004 closure).  ``read_tools_called``
        carries (tool_name, args) pairs for every tracked read-tool call so
        the handler can persist the updated channel context (BUG-011).
        """
        contents: list[dict[str, Any]] = [
            {"role": "user", "parts": [{"text": user_message}]},
        ]

        # Track latest preview / pagination hints across tool-call turns.
        # Overwritten on every matching tool result so the FSM uses the
        # most recent hint when the LLM finally produces a text response.
        preview_pending: dict[str, Any] | None = None
        preview_message: str | None = None
        pagination_pending: dict[str, Any] | None = None
        read_tools_called: list[tuple[str, dict[str, Any]]] = []

        for turn in range(MAX_AGENT_TURNS):
            response = await self._call_gemini(contents, read_context=read_context)

            if "error" in response:
                logger.error("gemini_api_error", error=response["error"])
                return AgentResult("Произошла ошибка при обращении к LLM. Попробуйте позже.")

            candidates = response.get("candidates", [])
            if not candidates:
                # BUG-006: structurally distinguish blocked-by-safety from
                # genuinely empty Gemini responses. Both end up here pre-fix
                # but mean very different things to operator + user.
                block_reason = response.get("promptFeedback", {}).get("blockReason")
                if block_reason:
                    logger.warning("gemini_blocked", reason=block_reason)
                    record_bot_gemini_empty_parts(
                        model=self._model,
                        finish_reason="blocked",
                    )
                    return AgentResult("Запрос был заблокирован фильтрами безопасности LLM.")
                # No candidates AND no blockReason = the BUG-006 generic
                # bucket. Dump the response for forensics so future runs
                # have something to grep.
                logger.error(
                    "gemini_no_candidates",
                    response_keys=list(response.keys()),
                    response_dump=json.dumps(response, ensure_ascii=False)[
                        :EMPTY_PARTS_LOG_DUMP_CAP
                    ],
                    usage=response.get("usageMetadata"),
                    model=self._model,
                    tool_count=len(TOOL_DECLARATIONS),
                )
                record_bot_gemini_empty_parts(
                    model=self._model,
                    finish_reason="no_candidates",
                )
                return AgentResult("LLM не вернул ни одного кандидата ответа. Попробуйте позже.")

            candidate = candidates[0]
            finish_reason = candidate.get("finishReason", "")

            if finish_reason == "SAFETY":
                logger.warning("gemini_safety_stop")
                record_bot_gemini_empty_parts(
                    model=self._model,
                    finish_reason="SAFETY",
                )
                return AgentResult(_empty_parts_message("SAFETY"))

            parts = candidate.get("content", {}).get("parts", [])

            if not parts:
                # BUG-006 main signature: HTTP 200, candidate present, but
                # ``parts=[]``. Classify by ``finishReason`` so we surface a
                # specific message AND increment the metric — operators see
                # the rate per (model, reason) post-deploy.
                logger.error(
                    "gemini_empty_parts",
                    finish_reason=finish_reason or "(none)",
                    usage=response.get("usageMetadata"),
                    model=self._model,
                    tool_count=len(TOOL_DECLARATIONS),
                    response_dump=json.dumps(response, ensure_ascii=False)[
                        :EMPTY_PARTS_LOG_DUMP_CAP
                    ],
                )
                record_bot_gemini_empty_parts(
                    model=self._model,
                    finish_reason=finish_reason or "none",
                )
                return AgentResult(_empty_parts_message(finish_reason))

            function_calls = [p for p in parts if "functionCall" in p]

            if not function_calls:
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                response_text = "\n".join(text_parts).strip() or "Пустой ответ от LLM."
                return AgentResult(
                    response_text=response_text,
                    preview_pending=preview_pending,
                    preview_message=preview_message,
                    pagination_pending=pagination_pending,
                    read_tools_called=read_tools_called,
                )

            contents.append({"role": "model", "parts": parts})

            # BUG-039 / BUG-040: a channel-name clarification captured this
            # turn short-circuits the loop so the suggestion text is sent
            # DETERMINISTICALLY (the tool's own error string), with a
            # clarify FSM hint the handler arms — instead of being fed back
            # to the LLM, re-authored, and dropped (the dead-end pre-fix).
            clarify_pending: dict[str, Any] | None = None
            clarify_message: str | None = None

            function_responses = []
            for fc_part in function_calls:
                fc = fc_part["functionCall"]
                tool_name = fc["name"]
                tool_args = fc.get("args", {})

                # Tool args at INFO level — required forensics for BUG-002 /
                # BUG-004 (a single line of "tool=remove_channel
                # args={'channel_id':'test_channel','confirm':true}" would
                # have caught the 28.04 00:04 trace immediately).
                logger.info(
                    "agent_tool_call",
                    tool=tool_name,
                    turn=turn,
                    args=tool_args,
                )

                result = await execute_tool(
                    tool_name,
                    tool_args,
                    timeout=self._tool_timeout,
                    current_user=current_user,
                    bot=bot,
                    chat_id=chat_id,
                )

                # Capture FSM hints from the tool's raw payload.
                if isinstance(result, dict):
                    if result.get("preview") is True and not bool(tool_args.get("confirm")):
                        # Strip ``confirm`` if the LLM passed it explicitly —
                        # the FSM handler is the sole authority that adds
                        # ``confirm=True`` on the user's actual yes.
                        sanitized_args = {k: v for k, v in tool_args.items() if k != "confirm"}
                        preview_pending = {
                            "tool_name": tool_name,
                            "args": sanitized_args,
                        }
                        # BUG-042 + review item B1: keep the tool's OWN preview
                        # message so the handler can render it verbatim
                        # (deterministic), bypassing the LLM paraphrase that
                        # truncated the cron. ONLY the subscribe executors mark
                        # their preview text as user-facing
                        # (``user_facing_message``). Every OTHER preview tool's
                        # ``message`` is LLM-directed scaffolding (e.g. «Preview
                        # only. Ask the user to confirm, then call again with
                        # confirm=true.») and MUST stay on the LLM-paraphrase
                        # (``response_text``) path — surfacing it verbatim would
                        # leak raw English scaffolding to the user (B1).
                        if result.get("user_facing_message") is True:
                            msg = result.get("message")
                            preview_message = msg if isinstance(msg, str) and msg else None
                        else:
                            preview_message = None
                    elif tool_args.get("confirm") is True:
                        # LLM executed the previewed action itself in the
                        # same turn-loop — the FSM hint is stale, drop it.
                        preview_pending = None
                        preview_message = None

                    nested_pagination = result.get("pagination_pending")
                    if isinstance(nested_pagination, dict):
                        pagination_pending = nested_pagination

                    # BUG-039 / BUG-040: a subscribe_* channel-validation
                    # rejection that carries a ``suggestion`` arrives here as
                    # an error with a ``clarify_pending`` hint. Capture it so
                    # the loop can return a deterministic clarification.
                    nested_clarify = result.get("clarify_pending")
                    if isinstance(nested_clarify, dict):
                        clarify_pending = nested_clarify
                        err_msg = result.get("error")
                        clarify_message = (
                            err_msg
                            if isinstance(err_msg, str) and err_msg
                            else "Уточните, пожалуйста, имя канала."
                        )

                # BUG-011 (Session H): track channel_id-bearing read-tool
                # calls so the handler can update FSMContext.read_context.
                if tool_name in _READ_TOOLS_TRACKED_FOR_CONTEXT and tool_args.get("channel_id"):
                    read_tools_called.append((tool_name, dict(tool_args)))

                function_responses.append(
                    {
                        "functionResponse": {
                            "name": tool_name,
                            "response": _safe_serialize(result),
                        },
                    }
                )

            # BUG-039 / BUG-040: return the clarification deterministically
            # (verbatim tool error text) + the clarify FSM hint, WITHOUT
            # feeding the error back to the LLM. Pre-fix the LLM re-authored
            # the suggestion, no FSM was armed, and the follow-up «да» fell
            # into the stateless catch-all «Я не совсем понимаю ваш ответ».
            if clarify_pending is not None:
                return AgentResult(
                    response_text=clarify_message or "Уточните, пожалуйста, имя канала.",
                    clarify_pending=clarify_pending,
                    read_tools_called=read_tools_called,
                )

            contents.append({"role": FUNCTION_RESPONSE_ROLE, "parts": function_responses})

        return AgentResult(
            response_text=(
                "Не удалось получить окончательный ответ после нескольких попыток. "
                "Попробуйте переформулировать вопрос."
            ),
            preview_pending=preview_pending,
            preview_message=preview_message,
            pagination_pending=pagination_pending,
            read_tools_called=read_tools_called,
        )

    async def _call_gemini(
        self,
        contents: list[dict],
        read_context: ReadContextData | None = None,
    ) -> dict[str, Any]:
        """Make a single Gemini API call with tool declarations.

        When ``read_context`` is supplied (BUG-011, Session H), an «Implicit
        channel context» block is appended to the ``systemInstruction`` text
        so Gemini can resolve ambiguous channel references on this turn.
        The block is read-only: write-tools are explicitly exempted (D-6).
        """
        url = f"{GEMINI_API_BASE}/{self._resolved_model()}:generateContent"

        generation_config: dict[str, Any] = {
            "temperature": 0.2,
            "maxOutputTokens": self._max_output_tokens,
        }
        if self._thinking_budget is not None:
            # Gemini 2.5 series: thinkingBudget=0 disables thinking entirely
            # (BUG-006 HG-2 hotfix). Positive integers cap thinking tokens.
            generation_config["thinkingConfig"] = {
                "thinkingBudget": self._thinking_budget,
            }

        system_text = self._system_prompt
        if read_context is not None:
            chan = read_context["last_channel_id"]
            system_text += (
                f"\n\nImplicit channel context (read-side, BUG-011, Session H):\n"
                f'- The user has been reading from channel "{chan}" in the prior turns.\n'
                f"- If their next request mentions a channel name explicitly — "
                f"use the explicit one. NEVER override an explicit reference.\n"
                f"- If their request is ambiguous re: channel (no explicit channel_id) "
                f'AND it would otherwise default to global/cross-channel — use "{chan}" '
                f"and acknowledge it in 1 sentence "
                f'(e.g. "Показываю темы канала {chan}: ...").\n'
                f"- This rule is read-side ONLY. NEVER apply it to write-tools "
                f"(add_channel, remove_channel, pause_channel, resume_channel, "
                f"trigger_pipeline, set_llm_config, reset_llm_config) — those always "
                f"require an explicit channel_id from the user. (D-6 immunity rule.)"
            )

        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": contents,
            "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
            "toolConfig": {
                "functionCallingConfig": {"mode": "AUTO"},
            },
            "generationConfig": generation_config,
        }

        try:
            resp = await self._client.post(
                url,
                json=payload,
                params={"key": self._api_key},
            )

            if resp.status_code != 200:
                error_text = resp.text[:500]
                logger.error(
                    "gemini_http_error",
                    status=resp.status_code,
                    body=error_text,
                )
                return {"error": f"Gemini API returned {resp.status_code}: {error_text}"}

            data = resp.json()

            usage = data.get("usageMetadata", {})
            logger.debug(
                "gemini_response",
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                thoughts_tokens=usage.get("thoughtsTokenCount"),
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
