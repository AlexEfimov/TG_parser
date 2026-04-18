"""
Aiogram handlers for the Telegram bot.

- /start — greeting and capabilities
- /help — detailed help
- Text messages — route through Gemini agent
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import Message

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.formatter import (
    format_error,
    format_timeout,
    markdown_to_html,
    split_message,
)

if TYPE_CHECKING:
    from tg_parser.bot.agent import GeminiAgent

logger = structlog.get_logger(__name__)

TYPING_INTERVAL = 4.0  # Telegram typing action lasts ~5 seconds

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
    "Можно добавить новый канал или удалить существующий со всеми данными. "
    "Обе операции требуют подтверждения. Удаление необратимо.\n"
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
    current_user: CurrentUser | None = None,
) -> None:
    """Route free-form text through the Gemini agent."""
    user_text = message.text
    if not user_text or not user_text.strip():
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
        response_text = await agent.process_message(
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

    if not response_text:
        await message.answer(format_error("Пустой ответ. Попробуйте переформулировать вопрос."))
        return

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
