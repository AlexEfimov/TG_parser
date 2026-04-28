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
* TTL of 5 minutes (``PENDING_TTL_SECONDS``) clears stale state if the
  user disappears between turns.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

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
from tg_parser.bot.states import ConfirmFlow
from tg_parser.bot.tools import execute_tool

if TYPE_CHECKING:
    from tg_parser.bot.agent import GeminiAgent

logger = structlog.get_logger(__name__)

TYPING_INTERVAL = 4.0  # Telegram typing action lasts ~5 seconds

# Confirm-flow TTL — after this many seconds since the preview, treat the
# pending action as expired. D-3 default per Session D runbook.
PENDING_TTL_SECONDS = 300

# yes/no detection for ConfirmFlow. Anchored to the start of the message,
# case-insensitive, word-boundary aware. We deliberately keep this list
# tight — anything that doesn't match falls through to D-4 (clear state +
# treat as a fresh request via the agent).
CONFIRM_PATTERN = re.compile(
    r"^\s*(да|yes|ок|ok|подтвержд\w*|подтверди\w*|ага|уверен\w*|конечно|давай)\b",
    re.IGNORECASE,
)
REJECT_PATTERN = re.compile(
    r"^\s*(нет|no|отмена|cancel|стоп|stop|не\s+надо|передумал\w*)\b",
    re.IGNORECASE,
)

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
async def cmd_start(message: Message, current_user: CurrentUser | None = None) -> None:
    """Greeting and capabilities overview, with registration status."""
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

    logger.info("user_message", text_length=len(user_text))

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

    response_text = result.response_text
    if not response_text:
        await message.answer(format_error("Пустой ответ. Попробуйте переформулировать вопрос."))
        return

    await _send_text_response(message, response_text)

    # Transition into ConfirmFlow if the agent reported a pending preview.
    # The handler intentionally clears any pre-existing state by calling
    # ``set_state`` again with fresh data — pagination_pending wiring lands
    # in commit 4.
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
        await message.answer(
            "⏱️ Время на подтверждение истекло. Повторите запрос если нужно."
        )
        return

    text = (message.text or "").strip()

    if CONFIRM_PATTERN.match(text):
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
            )
        except Exception:
            logger.exception("fsm_confirm_execute_failed", tool=tool_name)
            await state.clear()
            await message.answer(format_error("Внутренняя ошибка при выполнении действия."))
            return

        await state.clear()
        await _send_text_response(message, _format_tool_result(tool_name, result))
        return

    if REJECT_PATTERN.match(text):
        await state.clear()
        await message.answer("❌ Отменено.")
        return

    # D-4 default: clear state and re-route the message as a fresh request.
    # The ConfirmFlow branch in handle_text guards against re-entering this
    # path, so the recursion terminates after one hop.
    await state.clear()
    await handle_text(message, agent=agent, state=state, current_user=current_user)


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


def _utcnow_iso() -> str:
    """UTC-aware ISO timestamp used to anchor FSM-stored TTL checks."""
    return datetime.now(timezone.utc).isoformat()


def _is_pending_expired(created_at_iso: str | None) -> bool:
    """Return True when the FSM-stored ``created_at`` exceeds ``PENDING_TTL_SECONDS``."""
    if not created_at_iso:
        return False
    try:
        created_at = datetime.fromisoformat(created_at_iso)
    except (TypeError, ValueError):
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds() > PENDING_TTL_SECONDS
