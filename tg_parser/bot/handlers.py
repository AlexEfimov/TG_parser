"""
Aiogram handlers for the Telegram bot.

- /start — greeting and capabilities
- /help — detailed help
- Text messages — route through Gemini agent, FSM-aware

Conversation FSM (BUG-002 + BUG-004 closure):

* When the agent returns ``AgentResult.preview_pending`` we transition the
  chat into :class:`ConfirmFlow.awaiting_confirmation` and stash the
  ``{tool_name, args}`` of the previewed action. On the user's next text
  ``_handle_confirmation_response`` matches yes/no via regex and executes
  the action **deterministically** (``execute_tool(name, {**args,
  "confirm": True})``), without consulting the LLM — this closes the
  BUG-002 hallucination class.
* When the agent returns ``AgentResult.pagination_pending`` we arm
  :class:`PaginationFlow.has_active_list` with the *next* page's
  ``{tool_name, args, total, offset, limit}``. The user's next "ещё /
  next" replays the same query through ``execute_tool`` with the
  channel/type filter intact and the offset advanced — closing BUG-004
  (LLM cannot lose channel context, because it isn't consulted).
* TTL of 5 minutes (``PENDING_TTL_SECONDS``) clears stale state if the
  user disappears between turns.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.formatter import (
    format_error,
    format_timeout,
    markdown_to_html,
    split_message,
)
from tg_parser.bot.states import ClarifyFlow, ConfirmFlow, PaginationFlow, ReadContextData
from tg_parser.bot.tools import (
    _READ_TOOLS_TRACKED_FOR_CONTEXT,
    execute_tool,
    verify_channel_exists,
)

if TYPE_CHECKING:
    from tg_parser.bot.agent import GeminiAgent

logger = structlog.get_logger(__name__)

TYPING_INTERVAL = 4.0  # Telegram typing action lasts ~5 seconds

# Confirm-flow TTL — after this many seconds since the preview, treat the
# pending action as expired. D-3 default per Session D runbook.
PENDING_TTL_SECONDS = 300

# Read-context TTL — after this many seconds since the last tracked read-tool
# call, the implicit channel context is considered stale. 15 min is longer
# than ConfirmFlow / PaginationFlow (5 min) because read sessions naturally
# span 10–15 min as users explore topics and follow up. D-5 default, Session H.
READ_CONTEXT_TTL_SECONDS = 15 * 60

# yes/no detection for ConfirmFlow. Anchored to the start of the message,
# case-insensitive, word-boundary aware. We deliberately keep this list
# tight — anything that doesn't match falls through to D-4 (clear state +
# treat as a fresh request via the agent).
#
# BUG-032 (Wave 1 step 4 post-watch): the canonical classifier is now
# :func:`classify_confirmation_token` below, backed by the
# :data:`AFFIRMATIVE_TOKENS` / :data:`NEGATIVE_TOKENS` frozensets. The
# regex patterns are retained as backward-compat aliases for the few
# callers (mostly tests) that still pre-match against the raw regex;
# both regex AND classifier must agree on every token (a contract test
# in ``tests/test_bot_confirm_flow.py`` pins the equivalence).
CONFIRM_PATTERN = re.compile(
    r"^\s*(да|yes|y|ок|ok|подтвержд\w*|подтверди\w*|подтвердить|"
    r"согласен|согласна|хорошо|ага|уверен\w*|конечно|давай|\+|👍)(\b|$)",
    re.IGNORECASE,
)
REJECT_PATTERN = re.compile(
    r"^\s*(нет|no|n|отмена|cancel|отказ|стоп|stop|"
    r"не\s+надо|не\s+подтвержд\w*|передумал\w*|-|👎)(\b|$)",
    re.IGNORECASE,
)

# BUG-032 — canonical confirmation-token whitelist. Matched against the
# user reply with ``str.casefold()`` (proper Cyrillic / unicode folding)
# after inner whitespace is collapsed via ``" ".join(text.split())``.
# Multi-word phrases (``"не подтверждаю"``, ``"не надо"``) appear here
# verbatim; classifier matches on either the full normalized text OR
# the first whitespace-separated token (so ``"да, давай"`` and
# ``"нет, спасибо"`` still classify correctly).
#
# Maintenance contract — when adding a token:
#   1. Keep both sets disjoint (audit-pinned by the test contract).
#   2. Mirror the entry into the regex above so back-compat callers
#      keep matching.
#   3. Add a parametrize case in ``tests/test_bot_confirm_flow.py``.
AFFIRMATIVE_TOKENS: frozenset[str] = frozenset(
    {
        "да",
        "yes",
        "y",
        "ok",
        "ок",
        "подтверждаю",
        "подтверди",
        "подтвердить",
        "согласен",
        "согласна",
        "хорошо",
        "ага",
        "уверен",
        "уверена",
        "конечно",
        "давай",
        "+",
        "👍",
    }
)

NEGATIVE_TOKENS: frozenset[str] = frozenset(
    {
        "нет",
        "no",
        "n",
        "отмена",
        "cancel",
        "отказ",
        "стоп",
        "stop",
        "не подтверждаю",
        "не надо",
        "передумал",
        "передумала",
        "-",
        "👎",
    }
)


class UnknownConfirmationToken(ValueError):
    """Raised when a reply on the confirm-turn matches neither whitelist.

    Carries the normalized form of the user reply so downstream handlers
    can surface a structured «accepted tokens are: …» message instead of
    the opaque «не совсем понимаю» the LLM used to emit pre-fix.
    """

    def __init__(self, normalized_text: str) -> None:
        super().__init__(
            f"unknown confirmation token: {normalized_text!r}; "
            f"accepted affirmative={sorted(AFFIRMATIVE_TOKENS)} "
            f"negative={sorted(NEGATIVE_TOKENS)}"
        )
        self.normalized_text = normalized_text


def classify_confirmation_token(
    text: str | None,
) -> Literal["affirmative", "negative", "unknown"]:
    """Classify a user reply on the ConfirmFlow turn.

    Normalization:
      * ``None`` → ``"unknown"`` (the FSM handler never reaches here with
        ``None`` in practice, but the typed contract makes call-sites
        defensive).
      * ``" ".join(text.split())`` collapses leading / trailing /
        internal whitespace (tabs, newlines, NBSP via ``str.split``)
        into a single canonical form.
      * ``.casefold()`` is used instead of ``.lower()`` so Cyrillic
        capital forms ("ДА", "НЕТ"), German "ß", and other unicode
        edge-cases fold to their canonical lower form — strict
        equality against the token sets cannot miss a capitalisation
        variant.

    Matching strategy:
      1. Full normalized form against the whitelists (so multi-token
         phrases like ``"не подтверждаю"`` / ``"не надо"`` match).
      2. First whitespace-separated token, with trailing sentence
         punctuation (",.;:!?") stripped, so compound replies like
         ``"да, давай"`` or ``"нет, спасибо"`` still classify.
      3. Anything else → ``"unknown"``.
    """
    if text is None:
        return "unknown"
    normalized = " ".join(text.split()).casefold()
    if not normalized:
        return "unknown"
    if normalized in AFFIRMATIVE_TOKENS:
        return "affirmative"
    if normalized in NEGATIVE_TOKENS:
        return "negative"
    first_token = normalized.split(" ", 1)[0].rstrip(",.;:!?")
    if first_token in AFFIRMATIVE_TOKENS:
        return "affirmative"
    if first_token in NEGATIVE_TOKENS:
        return "negative"
    return "unknown"


# "Next page" detection for PaginationFlow. The cancel/stop case is
# already covered by REJECT_PATTERN — same vocabulary applies.
NEXT_PAGE_PATTERN = re.compile(
    r"^\s*(ещё|еще|дальше|далее|след(?:ующ(?:ая|ие|ую))?|next|more|продолж\w*)\b",
    re.IGNORECASE,
)

# After this many cumulatively-shown items the pagination handler appends
# a soft-cap notice asking the user to confirm continuation. State is
# preserved (the user can still keep paging), this is a UX guardrail
# only — D-6 default per Session D runbook.
PAGINATION_SOFT_CAP = 10

router = Router(name="bot_handlers")

START_TEXT = (
    "<b>Привет!</b> Я ассистент по базе знаний Telegram-каналов.\n\n"
    "Я могу:\n"
    "• Отвечать на вопросы по содержимому каналов\n"
    "• Искать информацию по ключевым словам и темам\n"
    "• Показывать список каналов и тем\n"
    "• Давать детали по конкретным темам\n"
    "• Находить связи между темами из разных каналов\n"
    "• Показывать кросс-канальную аналитику\n"
    "• Запускать обработку канала, смотреть статус пайплайна\n"
    "• Приостанавливать и возобновлять канал (после подтверждения)\n"
    "• Добавлять и удалять каналы (после подтверждения)\n"
    "• Просматривать и переключать LLM-конфигурацию\n\n"
    "Просто напишите вопрос в свободной форме."
)

HELP_TEXT = (
    "<b>Что я умею:</b>\n\n"
    "<b>Вопросы и ответы</b>\n"
    "Задайте любой вопрос — я найду релевантные материалы и сформирую ответ "
    "с указанием источников.\n"
    "<i>Пример: «Что известно про APOE?»</i>\n\n"
    "<b>Поиск</b>\n"
    "Попросите найти материалы — получите список документов по релевантности.\n"
    "<i>Пример: «Найди материалы про витамин D»</i>\n\n"
    "<b>Темы</b>\n"
    "Попросите показать темы — увидите извлечённые из контента тематики.\n"
    "<i>Пример: «Покажи темы по каналу genotek»</i>\n\n"
    "<b>Каналы</b>\n"
    "Попросите показать каналы — увидите подключённые каналы со статистикой.\n"
    "<i>Пример: «Покажи список каналов»</i>\n\n"
    "<b>Аналитика</b>\n"
    "Попросите аналитику — получите статистику по темам и каналам.\n"
    "<i>Пример: «Кросс-канальная статистика»</i>\n\n"
    "<b>Пайплайн и каналы</b>\n"
    "Можно запросить статус обработки, запуск пайплайна для канала, паузу или возобновление. "
    "Операции записи выполняются только после вашего явного подтверждения в чате.\n"
    "<i>Пример: «Статус пайплайна для genotek» / «Запусти обработку genotek»</i>\n\n"
    "<b>Управление каналами</b>\n"
    "Можно добавить новый канал или удалить существующий. Удаление — мягкое: "
    "ingestion останавливается, но сырые сообщения, обработанные документы, "
    "темы и встраивания сохраняются и могут быть восстановлены повторным "
    "добавлением канала. Обе операции требуют подтверждения.\n"
    "<i>Пример: «Добавь канал new_channel» / «Удали канал old_channel»</i>\n\n"
    "<b>LLM конфигурация</b>\n"
    "Посмотреть текущий LLM-провайдер/модель, переключить на другой или сбросить к настройкам из .env.\n"
    "<i>Пример: «Покажи LLM конфиг» / «Переключи LLM на openai»</i>\n\n"
    "<b>Ограничения:</b>\n"
    "• Нет истории разговоров между сессиями\n"
    "• Ответы зависят от качества обработанного контента"
)


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    current_user: CurrentUser | None = None,
) -> None:
    """Greeting and capabilities overview, with registration status."""
    # D-7 (Session H): /start resets read_context — user expects a fresh session.
    await state.clear()

    _DEFAULT_ADMIN_ID = "00000000-0000-0000-0000-000000000000"

    if current_user is None or current_user.id == _DEFAULT_ADMIN_ID:
        await message.answer(
            "Вы не зарегистрированы в системе. Обратитесь к администратору для получения доступа.",
        )
        return

    channel_count = (
        len(current_user.allowed_channel_ids)
        if current_user.allowed_channel_ids is not None
        else "все"
    )
    greeting = (
        f"Привет, {current_user.name}! 👋\n\n"
        f"Роль: {current_user.role}\n"
        f"Каналов: {channel_count}\n\n"
        "Отправьте текстовое сообщение для начала работы."
    )
    await message.answer(greeting, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Detailed help message."""
    await message.answer(HELP_TEXT)


@router.message(F.text)
async def handle_text(
    message: Message,
    agent: GeminiAgent,
    state: FSMContext,
    current_user: CurrentUser | None = None,
) -> None:
    """Route free-form text through the Gemini agent, FSM-aware."""
    user_text = message.text
    if not user_text or not user_text.strip():
        return

    current_state = await state.get_state()

    # ConfirmFlow takes precedence — the user is replying to a preview, so
    # we MUST NOT route the text back through the LLM (BUG-002).
    if current_state == ConfirmFlow.awaiting_confirmation.state:
        await _handle_confirmation_response(message, agent, state, current_user)
        return

    # ClarifyFlow — the user is replying to a channel-name clarification
    # (BUG-039 / BUG-040). Handle deterministically: an affirmative re-runs
    # the previewed subscribe with the suggested channel; a bare channel name
    # is interpreted in-flow; anything else keeps the FSM armed. The LLM is
    # NOT consulted, so the bare reply can't be mis-routed (BUG-040).
    if current_state == ClarifyFlow.awaiting_channel_clarification.state:
        await _handle_clarification_response(message, agent, state, current_user)
        return

    # PaginationFlow — "ещё / next" replays the stashed query deterministically;
    # anything else clears state and routes through the agent (BUG-004).
    if current_state == PaginationFlow.has_active_list.state:
        await _handle_pagination_response(message, agent, state, current_user)
        return

    logger.info("user_message", text_length=len(user_text))

    # BUG-011 (Session H): retrieve non-stale read_context before the agent
    # call so it can be injected into systemInstruction for this turn.
    read_context = await _read_context_for_agent(state)

    async def _keep_typing() -> None:
        """Send typing action periodically until cancelled."""
        try:
            while True:
                await message.answer_chat_action(ChatAction.TYPING)
                await asyncio.sleep(TYPING_INTERVAL)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(_keep_typing())

    try:
        result = await agent.process_message(
            user_text,
            current_user=current_user,
            bot=message.bot,
            chat_id=message.chat.id,
            read_context=read_context,
        )
    except TimeoutError:
        typing_task.cancel()
        await message.answer(format_timeout())
        return
    except Exception:
        typing_task.cancel()
        logger.exception("agent_error")
        await message.answer(format_error("Внутренняя ошибка. Попробуйте позже."))
        return
    finally:
        typing_task.cancel()

    # BUG-042: when the agent carries the tool's OWN preview message, render
    # it verbatim (deterministic, HTML) instead of the LLM-paraphrased
    # ``response_text`` that truncated the cron «0 * * * *» → «0». The
    # preview message is pre-formatted HTML (e.g. cron inside <code>…</code>),
    # so it bypasses the markdown→HTML pass that would mangle the asterisks.
    if result.preview_pending and result.preview_message:
        await _send_html_response(message, result.preview_message)
    else:
        response_text = result.response_text
        if not response_text:
            await message.answer(format_error("Пустой ответ. Попробуйте переформулировать вопрос."))
            return
        await _send_text_response(message, response_text)

    # BUG-011 (Session H): persist the latest read_context from this turn.
    # Iterate in call order so the FSMContext always ends up holding the
    # LAST channel_id the LLM used (if the agent called multiple read-tools).
    for _tool_name, _tool_args in result.read_tools_called:
        await _refresh_read_context(state, _tool_name, _tool_args)

    # FSM transitions are mutually exclusive — a preview pending takes
    # precedence over any pagination hint the same response might carry.
    if result.preview_pending:
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action=result.preview_pending,
            created_at=_utcnow_iso(),
        )
        logger.info(
            "fsm_confirm_armed",
            tool=result.preview_pending.get("tool_name"),
            chat_id=message.chat.id,
        )
    elif result.clarify_pending:
        # BUG-039 / BUG-040: arm the clarify FSM so the next turn (an
        # affirmative «да» OR a bare channel-name reply) re-runs the
        # previewed subscribe with the corrected channel deterministically.
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=result.clarify_pending,
            created_at=_utcnow_iso(),
        )
        logger.info(
            "fsm_clarify_armed",
            tool=result.clarify_pending.get("tool_name"),
            suggestion=result.clarify_pending.get("suggestion"),
            chat_id=message.chat.id,
        )
    elif result.pagination_pending:
        # ``items_shown`` is the cumulative count of items the user has
        # seen so far; equal to the next page's offset by construction
        # (the tool always sets ``offset = previous offset + len(page)``).
        await state.set_state(PaginationFlow.has_active_list)
        await state.update_data(
            pagination=result.pagination_pending,
            items_shown=int(result.pagination_pending.get("offset", 0) or 0),
            created_at=_utcnow_iso(),
        )
        logger.info(
            "fsm_pagination_armed",
            tool=result.pagination_pending.get("tool_name"),
            offset=result.pagination_pending.get("offset"),
            chat_id=message.chat.id,
        )


async def _handle_confirmation_response(
    message: Message,
    agent: GeminiAgent,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> None:
    """Deterministic yes/no handler for ``ConfirmFlow.awaiting_confirmation``.

    Closes BUG-002 by routing confirmation **directly** to ``execute_tool``
    with the original previewed args + ``confirm=True``. The LLM is never
    consulted on this turn, so it cannot hallucinate a different
    ``tool_name`` / ``channel_id`` / ``args`` (the entire failure class
    documented under BUG_LOG.md § BUG-002 — including the constructive-op
    sub-form from the 2026-04-28 00:04 trace).
    """
    data = await state.get_data()
    pending_action = data.get("pending_action") or {}
    created_at_iso = data.get("created_at")

    if _is_pending_expired(created_at_iso):
        await state.clear()
        await message.answer("⏱️ Время на подтверждение истекло. Повторите запрос если нужно.")
        return

    text = message.text or ""
    classification = classify_confirmation_token(text)

    if classification == "affirmative":
        tool_name = pending_action.get("tool_name")
        original_args: dict[str, Any] = pending_action.get("args") or {}
        if not tool_name:
            await state.clear()
            await message.answer(
                "Внутренняя ошибка: контекст подтверждения утерян. Повторите запрос."
            )
            return

        confirmed_args = {**original_args, "confirm": True}
        logger.info(
            "fsm_confirm_execute",
            tool=tool_name,
            args=confirmed_args,
            chat_id=message.chat.id,
        )
        try:
            result = await execute_tool(
                tool_name,
                confirmed_args,
                current_user=current_user,
                bot=message.bot,
                chat_id=message.chat.id,
                confirm_flow_state={
                    "tool_name": tool_name,
                    "args": original_args,
                },
            )
        except Exception:
            logger.exception("fsm_confirm_execute_failed", tool=tool_name)
            await state.clear()
            await message.answer(format_error("Внутренняя ошибка при выполнении действия."))
            return

        # BUG-011 (Session H): preserve read_context across state.clear().
        # aiogram MemoryStorage stores data separately from state, but
        # state.clear() resets both — snapshot and restore explicitly.
        _data_before_confirm_clear = await state.get_data()
        _rc_before_confirm_clear = _data_before_confirm_clear.get("read_context")
        await state.clear()
        if _rc_before_confirm_clear is not None:
            await state.update_data(read_context=_rc_before_confirm_clear)
        await _send_text_response(message, _format_tool_result(tool_name, result))
        return

    if classification == "negative":
        _data_before_reject_clear = await state.get_data()
        _rc_before_reject_clear = _data_before_reject_clear.get("read_context")
        await state.clear()
        if _rc_before_reject_clear is not None:
            await state.update_data(read_context=_rc_before_reject_clear)
        await message.answer("❌ Отменено.")
        return

    # BUG-032 closure — unknown token. Pre-fix the handler used to clear
    # the FSM and re-route the reply through the LLM, which produced the
    # opaque «Я не совсем понимаю ваш ответ» (BUG_LOG § BUG-032 trace).
    # We now keep the FSM armed and surface a structured prompt that
    # lists the accepted tokens, so the user can recover within the
    # same FSM turn without re-issuing the original intent.
    logger.info(
        "fsm_confirm_unknown_token",
        chat_id=message.chat.id,
        normalized=" ".join(text.split()).casefold(),
    )
    await message.answer(
        "Не понял ваш ответ. Подтвердите действие: «да», «подтверждаю», «ok» "
        "или отмените: «нет», «отмена», «cancel». Время на подтверждение — "
        f"{PENDING_TTL_SECONDS // 60} мин."
    )


async def _handle_clarification_response(
    message: Message,
    agent: GeminiAgent,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> None:
    """Deterministic handler for ``ClarifyFlow.awaiting_channel_clarification``.

    Closes BUG-039 + BUG-040 and their 2026-05-31 residual on the read
    surface. Two clarification surfaces stash an in-flight call here:

    * **subscribe** (``kind`` absent / ``"subscribe"``): the subscribe
      space-guard (``validate_channel_username`` returned a ``suggestion``);
      the channel lives at ``channel_index`` in a ``channel_ids`` list and the
      re-run yields a subscribe preview → ``ConfirmFlow``.
    * **read** (``kind == "read"``): the channel-not-found fuzzy suggestion
      from ``_build_no_results_suggestion`` (``list_topics`` / ``search`` /
      ``get_cross_channel_stats``); the channel lives in a singular
      ``channel_arg`` and the re-run yields a read result rendered
      deterministically (with ``PaginationFlow`` armed when more pages
      remain).

    Either way the user's reply is resolved WITHOUT consulting the LLM:

    * **affirmative** («да», «ok», ...) → use the stashed ``suggestion`` as the
      corrected channel (BUG-039 — the suggestion is now actionable);
    * **negative** → cancel;
    * **anything else** → treat the reply as a candidate channel name typed
      by the user (BUG-040 — a bare «profendocrinologist» is interpreted
      in-flow, not re-classified to a fresh stateless-LLM turn).

    The chosen channel is verified to exist (BUG-041 defense-in-depth) before
    the original intent is re-run with the corrected channel id.
    """
    data = await state.get_data()
    clarify_action: dict[str, Any] = data.get("clarify_action") or {}
    created_at_iso = data.get("created_at")
    _rc = data.get("read_context")

    if _is_pending_expired(created_at_iso):
        await state.clear()
        if _rc is not None:
            await state.update_data(read_context=_rc)
        await message.answer("⏱️ Время на уточнение истекло. Повторите запрос если нужно.")
        return

    text = (message.text or "").strip()
    classification = classify_confirmation_token(text)

    if classification == "negative":
        await state.clear()
        if _rc is not None:
            await state.update_data(read_context=_rc)
        await message.answer("❌ Отменено.")
        return

    tool_name = clarify_action.get("tool_name")
    base_args: dict[str, Any] = dict(clarify_action.get("args") or {})
    if not tool_name or not base_args:
        await state.clear()
        if _rc is not None:
            await state.update_data(read_context=_rc)
        await message.answer("Внутренняя ошибка: контекст уточнения утерян. Повторите запрос.")
        return

    # An affirmative accepts the suggested correction; anything else is taken
    # as the channel name the user typed (bare-token reply, BUG-040).
    if classification == "affirmative":
        chosen = clarify_action.get("suggestion")
    else:
        chosen = text

    if not chosen:
        await message.answer(
            "Уточните, пожалуйста, имя канала: ответьте «да», чтобы принять "
            "предложенный вариант, пришлите корректное имя канала, или «нет» "
            "для отмены."
        )
        return

    # BUG-041 defense-in-depth — reject an LLM-/user-"corrected" channel that
    # does not actually exist. ``verify_channel_exists`` fail-opens (returns
    # None) when the source repo is unreachable, so an offline DB never wedges
    # the flow; a definitive ``False`` keeps the clarify FSM armed so the user
    # can correct again.
    exists = await verify_channel_exists(chosen)
    if exists is False:
        # Keep the FSM armed so the user can supply another channel; refresh
        # the TTL anchor (N2) so the re-correction window doesn't expire.
        await state.update_data(created_at=_utcnow_iso())
        await message.answer(
            f"Канал «{chosen}» не найден в базе. Проверьте имя и пришлите "
            f"корректное, либо «нет» для отмены."
        )
        return

    # BUG-039/040 residual (2026-05-31): the SAME clarification dead-end
    # surfaced on the READ side, where the channel-not-found fuzzy suggestion
    # is emitted by ``_build_no_results_suggestion`` (list_topics / search /
    # get_cross_channel_stats). The channel there lives in a singular
    # ``channel_id`` arg, not a ``channel_ids`` list, and the re-run yields a
    # read result (not a subscribe preview). ``kind`` discriminates the two.
    kind = clarify_action.get("kind", "subscribe")
    if kind == "read":
        channel_arg = clarify_action.get("channel_arg") or "channel_id"
        rerun_args = {**base_args, channel_arg: chosen}
    else:
        channel_index = int(clarify_action.get("channel_index", 0) or 0)
        channel_ids = list(base_args.get("channel_ids") or [])
        if 0 <= channel_index < len(channel_ids):
            channel_ids[channel_index] = chosen
        else:
            channel_ids = [chosen]
        rerun_args = {**base_args, "channel_ids": channel_ids}

    logger.info(
        "fsm_clarify_rerun",
        tool=tool_name,
        kind=kind,
        chosen=chosen,
        affirmative=(classification == "affirmative"),
        chat_id=message.chat.id,
    )

    try:
        # Re-run as a PREVIEW turn (no confirm) so the corrected channel goes
        # through the full preview/confirm contract — never a silent write.
        result = await execute_tool(
            tool_name,
            rerun_args,
            current_user=current_user,
            bot=message.bot,
            chat_id=message.chat.id,
        )
    except Exception:
        logger.exception("fsm_clarify_rerun_failed", tool=tool_name)
        await state.clear()
        if _rc is not None:
            await state.update_data(read_context=_rc)
        await message.answer(format_error("Внутренняя ошибка при обработке уточнения."))
        return

    if isinstance(result, dict) and result.get("clarify_pending"):
        # The corrected channel is ALSO invalid with a suggestion — re-arm
        # the clarify FSM with the fresh suggestion and relay it verbatim.
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=result["clarify_pending"],
            created_at=_utcnow_iso(),
            **({"read_context": _rc} if _rc is not None else {}),
        )
        clarify_text = result["clarify_pending"].get("message") or _format_tool_result(
            tool_name, result
        )
        await _send_text_response(message, clarify_text)
        return

    if kind == "read":
        # BUG-039/040 residual: render the re-run READ result deterministically
        # (no LLM, so a bare «да» / channel token can't be misrouted). Arm
        # PaginationFlow when the list has more pages — mirroring a normal
        # first-page read turn — otherwise clear back to the resting state.
        pagination = result.get("pagination_pending") if isinstance(result, dict) else None
        await _send_text_response(message, _format_read_result(tool_name, result))
        if isinstance(pagination, dict):
            await state.set_state(PaginationFlow.has_active_list)
            await state.update_data(
                pagination=pagination,
                items_shown=int(pagination.get("offset", 0) or 0),
                created_at=_utcnow_iso(),
                **({"read_context": _rc} if _rc is not None else {}),
            )
        else:
            await state.clear()
            if _rc is not None:
                await state.update_data(read_context=_rc)
        return

    if isinstance(result, dict) and result.get("error"):
        # Non-clarifiable error (e.g. permission / cron / non-existent channel)
        # — keep the FSM armed so the user can supply a different channel, and
        # surface the reason. N2: refresh the TTL anchor so a slow correction
        # after a rejected attempt doesn't expire mid-clarification.
        await state.update_data(created_at=_utcnow_iso())
        await _send_text_response(message, _format_tool_result(tool_name, result))
        return

    if isinstance(result, dict) and result.get("preview") is True:
        # Valid preview for the corrected channel — transition to ConfirmFlow
        # exactly like a normal preview turn, and render the tool's own
        # message verbatim (deterministic, BUG-042).
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": tool_name, "args": rerun_args},
            created_at=_utcnow_iso(),
            **({"read_context": _rc} if _rc is not None else {}),
        )
        logger.info("fsm_confirm_armed", tool=tool_name, chat_id=message.chat.id)
        message_text = result.get("message")
        if isinstance(message_text, str) and message_text:
            await _send_html_response(message, message_text)
        else:
            await _send_text_response(message, _format_tool_result(tool_name, result))
        return

    # Anything else — clear and surface the raw result.
    await state.clear()
    if _rc is not None:
        await state.update_data(read_context=_rc)
    await _send_text_response(message, _format_tool_result(tool_name, result))


async def _handle_pagination_response(
    message: Message,
    agent: GeminiAgent,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> None:
    """Deterministic next/cancel handler for ``PaginationFlow.has_active_list``.

    Closes BUG-004: a "ещё" replays the stashed
    ``{tool_name, args, offset, limit}`` directly — the LLM is never
    consulted on a pagination tick, so it cannot "forget" the original
    ``channel_id`` filter or restart numbering at 1.
    """
    data = await state.get_data()
    pagination: dict[str, Any] = data.get("pagination") or {}
    items_shown = int(data.get("items_shown") or 0)
    created_at_iso = data.get("created_at")
    # BUG-011 (Session H): snapshot read_context so we can restore it
    # across state.clear() calls below.
    _pagination_rc = data.get("read_context")

    if _is_pending_expired(created_at_iso):
        await state.clear()
        if _pagination_rc is not None:
            await state.update_data(read_context=_pagination_rc)
        await message.answer("⏱️ Список устарел. Повторите запрос если нужно ещё страницы.")
        return

    text = (message.text or "").strip()

    if REJECT_PATTERN.match(text):
        await state.clear()
        if _pagination_rc is not None:
            await state.update_data(read_context=_pagination_rc)
        await message.answer("✅ Остановлено.")
        return

    if NEXT_PAGE_PATTERN.match(text):
        tool_name = pagination.get("tool_name")
        page_args: dict[str, Any] = pagination.get("args") or {}
        if not tool_name:
            await state.clear()
            if _pagination_rc is not None:
                await state.update_data(read_context=_pagination_rc)
            await message.answer("Внутренняя ошибка: контекст списка утерян. Повторите запрос.")
            return

        logger.info(
            "fsm_pagination_execute",
            tool=tool_name,
            args=page_args,
            chat_id=message.chat.id,
        )
        try:
            result = await execute_tool(
                tool_name,
                page_args,
                current_user=current_user,
                bot=message.bot,
                chat_id=message.chat.id,
            )
        except Exception:
            logger.exception("fsm_pagination_execute_failed", tool=tool_name)
            await state.clear()
            if _pagination_rc is not None:
                await state.update_data(read_context=_pagination_rc)
            await message.answer(format_error("Внутренняя ошибка при загрузке страницы."))
            return

        new_pagination = result.get("pagination_pending") if isinstance(result, dict) else None
        page_items = result.get("items") if isinstance(result, dict) else None
        new_items_shown = items_shown + (len(page_items) if page_items else 0)

        # Soft-cap warning — show after the page text but DO NOT clear
        # state. The user can still keep paging.
        soft_cap_hit = (
            items_shown < PAGINATION_SOFT_CAP <= new_items_shown and new_pagination is not None
        )

        await _send_text_response(
            message,
            _format_paginated_list(tool_name, result, soft_cap_hit=soft_cap_hit),
        )

        if isinstance(new_pagination, dict):
            await state.set_state(PaginationFlow.has_active_list)
            await state.update_data(
                pagination=new_pagination,
                items_shown=int(new_pagination.get("offset", new_items_shown) or new_items_shown),
                created_at=_utcnow_iso(),
                # Carry forward read_context through paginated list turns.
                **({"read_context": _pagination_rc} if _pagination_rc is not None else {}),
            )
        else:
            await state.clear()
            if _pagination_rc is not None:
                await state.update_data(read_context=_pagination_rc)
        return

    # Fall-through: D-4 default — clear state and re-route as a fresh
    # agent request. Restore read_context so handle_text can inject it.
    await state.clear()
    if _pagination_rc is not None:
        await state.update_data(read_context=_pagination_rc)
    await handle_text(message, agent=agent, state=state, current_user=current_user)


def _format_paginated_list(
    tool_name: str,
    result: Any,
    *,
    soft_cap_hit: bool = False,
) -> str:
    """Render a paginated list-tool result deterministically — no LLM involved.

    This is the user-facing rendering path for the SECOND page onwards
    (the first page is still produced by the agent). Items use the
    ``n`` field set by the tool (global 1-based numbering across pages).
    """
    if not isinstance(result, dict):
        return str(result)

    if result.get("error"):
        return f"❗ {result.get('message') or result['error']}"

    items = result.get("items") or []
    offset = int(result.get("offset", 0) or 0)
    total = int(result.get("total", offset + len(items)) or 0)
    has_more = bool(result.get("has_more", False))

    if not items:
        return "📭 Больше нет элементов."

    lines: list[str] = []
    for item in items:
        n = item.get("n", "?")
        title = (
            item.get("title")
            or item.get("name")
            or item.get("channel_id")
            or item.get("id")
            or "(без названия)"
        )
        summary = item.get("summary")
        line = f"<b>{n}.</b> {title}"
        if summary:
            line += f" — {summary[:120]}"
        lines.append(line)

    footer = f"\n\nПоказано {offset + 1}–{offset + len(items)} из {total}."
    if has_more:
        footer += " Скажите «ещё» для следующей страницы или «стоп» чтобы остановиться."
    if soft_cap_hit:
        footer += (
            f"\n\n⚠️ Уже показано {offset + len(items)} элементов. "
            "Продолжать листать или остановиться?"
        )

    return "\n".join(lines) + footer


def _format_tool_result(tool_name: str, result: Any) -> str:
    """Render a deterministic-execute tool result into user-facing text.

    The FSM handler does NOT call the LLM after a confirmation, so we
    can't rely on Gemini to phrase the success/error message. Instead we
    dehydrate the structured result via the tool's own ``message`` field
    when present, with a sensible fallback for tools that don't include
    one.
    """
    if not isinstance(result, dict):
        return str(result)

    if result.get("error"):
        msg = result.get("message") or result["error"]
        return f"❗ {msg}"

    msg = result.get("message")
    if msg:
        return msg

    return f"✅ Готово: {tool_name}."


def _format_read_result(tool_name: str, result: Any) -> str:
    """Render a deterministically re-run READ tool result (BUG-039/040 residual).

    After a channel-not-found clarification on the read surface, the clarify
    handler re-runs the ORIGINAL read intent server-side (no LLM, so a bare
    «да» / channel token cannot be misrouted), then renders the structured
    result here:

    * ``list_topics`` reuses the global-numbered paginated-list renderer;
    * ``search`` renders its ranked hits;
    * everything else (e.g. ``get_cross_channel_stats``) falls back to the
      tool's own ``message`` or a compact completion note.

    This never re-enters the LLM, so the opaque «Я не совсем понимаю ваш
    ответ» fallback can't resurface on this surface.
    """
    if not isinstance(result, dict):
        return str(result)
    if result.get("error"):
        return f"❗ {result.get('message') or result['error']}"
    if isinstance(result.get("items"), list):
        return _format_paginated_list(tool_name, result)
    if isinstance(result.get("results"), list):
        hits = result["results"]
        if not hits:
            return "📭 Ничего не найдено по запросу."
        lines: list[str] = []
        for i, hit in enumerate(hits, start=1):
            title = (
                hit.get("summary")
                or hit.get("text_preview")
                or hit.get("source_ref")
                or "(без названия)"
            )
            lines.append(f"<b>{i}.</b> {str(title)[:160]}")
        return "\n".join(lines)
    msg = result.get("message")
    if isinstance(msg, str) and msg:
        return msg
    return f"✅ Готово: {tool_name}."


async def _send_text_response(message: Message, response_text: str) -> None:
    """Render markdown → HTML and split if needed (preserves prior behavior)."""
    html_text = markdown_to_html(response_text)
    chunks = split_message(html_text)

    for i, chunk in enumerate(chunks):
        try:
            await message.answer(chunk, parse_mode="HTML")
        except Exception:
            logger.warning("html_send_failed_fallback_to_plain", chunk_index=i)
            plain_chunks = split_message(response_text)
            for plain_chunk in plain_chunks:
                await message.answer(plain_chunk, parse_mode=None)
            break


async def _send_html_response(message: Message, html_text: str) -> None:
    """Send pre-formatted HTML verbatim, WITHOUT the markdown→HTML pass.

    Deterministic-preview path (BUG-042): the tool's preview ``message`` is
    already valid Telegram HTML (e.g. the cron inside ``<code>…</code>``).
    Routing it through :func:`markdown_to_html` would let the italic-``*``
    rule mangle a cron like «0 * * * *», which is exactly the truncation we
    are eliminating. We still split for the 4096-char limit and fall back to
    plain text if Telegram rejects the HTML.
    """
    for i, chunk in enumerate(split_message(html_text)):
        try:
            await message.answer(chunk, parse_mode="HTML")
        except Exception:
            logger.warning("preview_html_send_failed_fallback_to_plain", chunk_index=i)
            for plain_chunk in split_message(html_text):
                await message.answer(plain_chunk, parse_mode=None)
            break


def _utcnow_iso() -> str:
    """UTC-aware ISO timestamp used to anchor FSM-stored TTL checks."""
    return datetime.now(UTC).isoformat()


def _is_pending_expired(created_at_iso: str | None) -> bool:
    """Return True when the FSM-stored ``created_at`` exceeds ``PENDING_TTL_SECONDS``."""
    if not created_at_iso:
        return False
    try:
        created_at = datetime.fromisoformat(created_at_iso)
    except (TypeError, ValueError):
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created_at).total_seconds() > PENDING_TTL_SECONDS


def _is_stale(created_at_iso: str | None, ttl_seconds: int) -> bool:
    """Return True when ``created_at_iso`` is absent or exceeds ``ttl_seconds``.

    Generalised version of :func:`_is_pending_expired` that accepts an
    explicit TTL so different context types can use different windows.
    A missing / unparseable timestamp is treated as stale (fail-safe).
    """
    if not created_at_iso:
        return True
    try:
        created_at = datetime.fromisoformat(created_at_iso)
    except (TypeError, ValueError):
        return True
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created_at).total_seconds() > ttl_seconds


async def _refresh_read_context(state: FSMContext, tool_name: str, args: dict[str, Any]) -> None:
    """Update FSMContext data with the latest read_context after a tracked
    read-tool call (BUG-011, Session H).

    No-op when ``tool_name`` is not in ``_READ_TOOLS_TRACKED_FOR_CONTEXT``
    or when ``args`` carries no ``channel_id``.
    """
    if tool_name not in _READ_TOOLS_TRACKED_FOR_CONTEXT:
        return
    channel_id = args.get("channel_id")
    if not channel_id:
        return
    await state.update_data(
        read_context=ReadContextData(
            last_channel_id=channel_id,
            last_tool=tool_name,
            created_at=_utcnow_iso(),
        )
    )


async def _read_context_for_agent(
    state: FSMContext,
) -> ReadContextData | None:
    """Return non-stale read_context for agent injection, or None.

    Returns ``None`` when no context is stored, the stored value is not a
    dict, or the TTL has expired (BUG-011, Session H).
    """
    data = await state.get_data()
    rc = data.get("read_context")
    if not rc or not isinstance(rc, dict):
        return None
    if _is_stale(rc.get("created_at"), READ_CONTEXT_TTL_SECONDS):
        return None
    return rc  # type: ignore[return-value]
