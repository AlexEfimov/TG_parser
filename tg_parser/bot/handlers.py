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
from tg_parser.bot.states import (
    ClarifyFlow,
    ConfirmFlow,
    DeleteIntentData,
    LastSubscriptionData,
    PaginationFlow,
    ReadContextData,
    SubscribeIntentData,
)
from tg_parser.bot.tools import (
    _READ_TOOLS_TRACKED_FOR_CONTEXT,
    _build_delete_disambig_clarify,
    _build_delete_suggest_clarify,
    _match_subscription_items,
    execute_tool,
    resolve_subscription_by_name,
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

# BUG-047 — deterministic delete pre-router signals. A sibling of
# CONFIRM_PATTERN, anchored to the start of the message: the user explicitly
# asks to delete / unsubscribe something.
DELETE_VERB_PATTERN = re.compile(
    r"^\s*(удали(ть)?|удал\w*|delete|убери|убрать|отпиш\w*|unsubscribe)\b",
    re.IGNORECASE,
)

# Anaphora referring to a previously-shown subscription («эту подписку», «её»,
# «последнюю», «this subscription»). Matched anywhere in the message; only
# acted on when a NON-STALE last_subscription exists (otherwise the turn falls
# through to the LLM — BUG-047 TTL contract).
ANAPHORA_PATTERN = re.compile(
    r"(эту\s+подписку|этот\s+watchlist|это[тй]\s+\w+|\bэту\b|\bеё\b|\bее\b|"
    r"последн\w+|this\s+subscription|this\s+one)",
    re.IGNORECASE,
)

# Channel-domain hint — when present, the delete is a CHANNEL op
# (remove_channel) or the out-of-scope «по каналу X» phrasing, so the
# subscription pre-router must NOT hijack it (falls through to the agent).
_CHANNEL_HINT_PATTERN = re.compile(r"(\bканал\w*|\bchannel\w*|по\s+каналу)", re.IGNORECASE)

# Optional leading noun after the delete verb («удали подписку X» / «удали
# дайджест X» / «удали watchlist X») — stripped so the remainder is the bare
# subscription name to resolve.
_DELETE_NOUN_PREFIX = re.compile(
    r"^(подписк\w*|дайджест\w*|watchlist|вотчлист\w*|interest|subscription|"
    r"алерт\w*|интерес\w*)\s+",
    re.IGNORECASE,
)

# BUG-049 — a leading preposition («на genotek») hides the bare token from the
# casefolded-substring / fuzzy suggest tier, so «удали подписку на genotek»
# never reduces to «genotek» and falls to a plain not-found (vs «удали подписку
# genotek», which DOES arm the suggest). Stripped ONLY to emit an additional
# LAST-RESORT candidate (appended after the existing shapes). The set is kept
# deliberately small/conservative and only fires when a meaningful remainder
# survives, so a name that legitimately starts with a preposition (or a
# multi-word name) still resolves via the earlier, higher-priority candidates.
_DELETE_PREPOSITION_PREFIX = re.compile(
    r"^(на|об|от|про|по|о)\s+",
    re.IGNORECASE,
)

# BUG-048 (D2) — intent-break / escape detectors. An armed ConfirmFlow /
# subscribe-read ClarifyFlow is "greedy": pre-fix it consumed ANY non-«нет»
# reply as a confirm-token / channel-name, wedging the user when they actually
# typed a NEW command or question. These detectors recognise an EXPLICIT new
# intent so the handler can ABANDON the un-executed flow and reroute.
#
# Deliberately MINIMAL (conservative) to avoid false escapes — only line-initial
# command verbs + question markers. Bare channel names («profendocrinologist»)
# must NOT match (BUG-040/043/045 preserved); affirmative / negative tokens
# («да» / «нет») are excluded explicitly in :func:`_looks_like_new_intent`.
COMMAND_VERB_PATTERN = re.compile(
    r"^\s*("
    # delete / unsubscribe
    r"удали(ть)?|удал\w*|delete|убери|убрать|отпиш\w*|unsubscribe|"
    # subscribe / create / add
    r"созда(й|ть)|подпиш\w*|subscribe|добав(ь|ить)|add|"
    # show / list
    r"покаж\w*|показать|show|list|список|перечисл\w*"
    r")\b",
    re.IGNORECASE,
)

QUESTION_PATTERN = re.compile(
    r"(^\s*(что|как|какие|какой|кака[яйю]|где|why|how|what|which|who)\b|\?\s*$)",
    re.IGNORECASE,
)

# BUG-050 — subscribe-create intent detection (post-agent detector signal).
#
# The defect: on a subscribe-create request with an unknown/typo channel, the
# LLM SOMETIMES answers conversationally («Извините, канал "enotek" не найден…»)
# instead of calling ``subscribe_digest``. Because the tool isn't called, the
# deterministic G2 clarify (``_reject_nonexistent_channel`` →
# ``_build_subscribe_clarify_pending``) never arms, so the user's follow-up bare
# channel name is processed statelessly and misrouted to ``list_topics``. This
# is the SUBSCRIBE analogue of BUG-048's delete-intent gap.
#
# Conservative by construction (minimal blast radius). Two tiers:
#
# * ``подпиш…`` / ``subscribe`` are INHERENTLY subscribe-specific verbs — a
#   line-initial match alone qualifies.
# * ``созда(й|ть)`` / ``добав(ь|ить)`` / ``add`` are GENERIC create/add verbs
#   that also drive ``add_channel`` etc. — they qualify ONLY when a
#   subscription/digest hint is also present, so a bare «добавь канал X»
#   (an ``add_channel`` op) never trips the subscribe detector.
_SUBSCRIBE_VERB_STRONG_PATTERN = re.compile(r"^\s*(подпиш\w*|subscribe)\b", re.IGNORECASE)
_SUBSCRIBE_VERB_WEAK_PATTERN = re.compile(
    r"^\s*(созда(й|ть)|добав(ь|ить)|add)\b",
    re.IGNORECASE,
)
_SUBSCRIBE_DIGEST_HINT_PATTERN = re.compile(
    r"(подписк\w*|дайджест\w*|digest|subscription|рассылк\w*)",
    re.IGNORECASE,
)
_SUBSCRIBE_WATCHLIST_HINT_PATTERN = re.compile(
    r"(watchlist|вотчлист\w*|interest|наблюден\w*|алерт\w*)",
    re.IGNORECASE,
)

# A bare channel-like token (the resume reply on turn 2 — «genotek»). Telegram
# usernames are ASCII alphanumeric + underscore; an optional leading «канал» /
# «channel» word and an optional «@» are tolerated and stripped.
_BARE_CHANNEL_TOKEN_PATTERN = re.compile(r"^@?([A-Za-z0-9_]{2,})$")
_BARE_CHANNEL_PREFIXED_PATTERN = re.compile(
    r"^(?:канал|channel)\s+@?([A-Za-z0-9_]{2,})$",
    re.IGNORECASE,
)

# Channel-token extraction after «канал»/«channel» for the turn-1 parse.
_SUBSCRIBE_CHANNEL_HINT_PATTERN = re.compile(
    r"(?:канал|channel)\s+@?([A-Za-z0-9_]{2,})",
    re.IGNORECASE,
)


def _detect_subscribe_tool(text: str | None) -> str | None:
    """Return the subscribe tool for a create request, or ``None`` (BUG-050).

    ``subscribe_digest`` is the default for strong verbs without a watchlist
    hint. ``subscribe_watchlist`` is selected when a watchlist-specific hint
    is present (parity extension deferred from BUG-050 v1).
    """
    if not text:
        return None
    watchlist = bool(_SUBSCRIBE_WATCHLIST_HINT_PATTERN.search(text))
    digest = bool(_SUBSCRIBE_DIGEST_HINT_PATTERN.search(text))
    if _SUBSCRIBE_VERB_STRONG_PATTERN.match(text):
        if watchlist and not digest:
            return "subscribe_watchlist"
        return "subscribe_digest"
    if _SUBSCRIBE_VERB_WEAK_PATTERN.match(text):
        if watchlist:
            return "subscribe_watchlist"
        if digest:
            return "subscribe_digest"
    return None


def _detect_subscribe_create_intent(text: str | None) -> bool:
    """Return True when ``text`` is a subscribe-CREATE request (BUG-050).

    Drives the POST-agent detector ONLY (the sole ``subscribe_intent`` SET
    site) — never a turn-1 pre-router. Conservative: an inherently
    subscribe-specific verb («подпиш…» / «subscribe») qualifies alone; a generic
    create/add verb («создай» / «добавь» / ``add``) qualifies only with a
    subscription/digest or watchlist hint so ``add_channel`` requests don't trip it.
    """
    return _detect_subscribe_tool(text) is not None


# BUG-050 — minimal schedule parser. Recognizes the hourly phrasings the smoke
# trace exercises and nothing else (lean on the executor + preview for the
# rest):
#   «каждый час в :MM» / «ежечасно [в :MM]» / «hourly»  → "MM * * * *"
#   «каждые N часов в :MM»                              → "MM */N * * *"
#   a literal 5-field cron present in the text          → that cron verbatim
_SUBSCRIBE_EVERY_N_HOURS_PATTERN = re.compile(
    r"кажд\w*\s+(\d{1,2})\s+час\w*(?:\s+в\s+:?(\d{1,2}))?",
    re.IGNORECASE,
)
_SUBSCRIBE_HOURLY_PATTERN = re.compile(
    r"(?:кажд\w*\s+час|ежечас\w*|hourly)(?:\s+в\s+:?(\d{1,2}))?",
    re.IGNORECASE,
)
_LITERAL_CRON_PATTERN = re.compile(
    r"(?<!\S)((?:\d{1,2}|\*)\s+(?:\d{1,2}|\*|\*/\d{1,2})\s+\S+\s+\S+\s+\S+)(?!\S)",
)


def _parse_subscribe_schedule(text: str | None) -> str | None:
    """Extract a cron expression from a subscribe-create request (BUG-050).

    Minimal by design — returns ``None`` when nothing recognizable is present so
    the executor falls back to its own default («0 9 * * *»).
    """
    if not text:
        return None
    m = _SUBSCRIBE_EVERY_N_HOURS_PATTERN.search(text)
    if m:
        n = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) is not None else 0
        return f"{minute} */{n} * * *"
    m = _SUBSCRIBE_HOURLY_PATTERN.search(text)
    if m:
        minute = int(m.group(1)) if m.group(1) is not None else 0
        return f"{minute} * * * *"
    m = _LITERAL_CRON_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return None


def _parse_subscribe_channel(text: str | None) -> str | None:
    """Extract the channel token after «канал»/«channel» (turn-1 diagnostics)."""
    if not text:
        return None
    m = _SUBSCRIBE_CHANNEL_HINT_PATTERN.search(text)
    return m.group(1) if m else None


def _subscribe_partial_args(text: str | None) -> dict[str, Any]:
    """Cheaply parse subscribe args from a turn-1 request (BUG-050).

    Minimal — only the schedule is extracted (the channel is filled by the
    turn-2 resume token; the digest name is synthesized at resume time from the
    resolved channel; format / timezone fall back to the executor defaults).
    """
    partial: dict[str, Any] = {}
    cron = _parse_subscribe_schedule(text)
    if cron:
        partial["cron_expression"] = cron
    return partial


def _bare_channel_token(text: str | None) -> str | None:
    """Return the bare channel username from a turn-2 resume reply, or None.

    Accepts a lone token («genotek», «@genotek») or a «канал genotek» /
    «channel genotek» phrasing; anything else (multi-word free text, confirm
    tokens, commands) returns ``None``.
    """
    t = (text or "").strip()
    if not t:
        return None
    m = _BARE_CHANNEL_PREFIXED_PATTERN.match(t)
    if m:
        return m.group(1)
    m = _BARE_CHANNEL_TOKEN_PATTERN.match(t)
    if m:
        return m.group(1)
    return None


def _default_subscribe_name(channel: str, cron_expression: str | None = None) -> str:
    """Synthesize a digest name when the turn-1 request carried none (BUG-050).

    Mirrors the human phrasing the LLM normally derives: an hourly schedule
    (hour field «*») yields «Ежечасный дайджест {channel}», otherwise the
    generic «Дайджест {channel}».
    """
    if cron_expression:
        fields = cron_expression.split()
        if len(fields) == 5 and fields[1] == "*":
            return f"Ежечасный дайджест {channel}"
    return f"Дайджест {channel}"


def _default_watchlist_title(channel: str) -> str:
    """Synthesize a watchlist title when the turn-1 request carried none."""
    return f"Watchlist {channel}"


def _subscribe_intent_rerun_args(
    tool_name: str,
    channel: str,
    partial: dict[str, Any],
) -> dict[str, Any]:
    """Build preview args for a subscribe-intent bare-channel resume."""
    if tool_name == "subscribe_watchlist":
        title = partial.get("title") or _default_watchlist_title(channel)
        return {**partial, "channel_ids": [channel], "title": title}
    cron_expression = partial.get("cron_expression")
    name = partial.get("name") or _default_subscribe_name(channel, cron_expression)
    return {**partial, "channel_ids": [channel], "name": name}


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


def _looks_like_new_intent(text: str | None) -> bool:
    """Return True when ``text`` is an EXPLICIT new command / question (BUG-048).

    Used by the FSM intent-break guard: when a greedy ConfirmFlow / ClarifyFlow
    receives one of these the handler abandons the un-executed flow and reroutes
    instead of consuming the reply as a confirm-token / channel-name.

    Conservative by construction (line-initial command verbs + question
    markers). Affirmative / negative tokens («да» / «нет», incl. compound forms
    like «да?») are NEVER treated as a new intent — the cancel / affirmative
    classification must keep winning where it should (BUG-039/043/045/046).
    """
    if not text:
        return False
    if classify_confirmation_token(text) != "unknown":
        return False
    return bool(COMMAND_VERB_PATTERN.match(text) or QUESTION_PATTERN.search(text))


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

    # BUG-047 — deterministic delete / anaphora pre-router. Fires ONLY on an
    # explicit delete-intent signal (a delete verb, or an anaphora token backed
    # by a non-stale last_subscription) so it never hijacks questions / search /
    # subscribe flows. When it resolves a target it arms the EXISTING BUG-046
    # ConfirmFlow preview gate WITHOUT consulting the LLM; otherwise it returns
    # falsey and the turn falls through to the normal agent path (G2 / BUG-043 /
    # normal Q&A untouched).
    if await _handle_delete_prerouter(message, state, current_user):
        return

    # BUG-048 (Part A): persisted-delete-intent router. Runs AFTER the explicit
    # delete pre-router and BEFORE the agent: when a non-stale delete_intent is
    # active and the turn is a BARE subscription name (no new intent / delete
    # verb / channel hint), re-resolve it deterministically as a DELETE rather
    # than letting it fall to the agent (which would mis-emit subscribe_digest).
    if await _handle_delete_intent_router(message, state, current_user):
        return

    # BUG-050: persisted-subscribe-intent router. Runs AFTER the delete-intent
    # router (delete precedence) and BEFORE the agent: when a non-stale
    # subscribe_intent is active and the turn is a BARE channel name, resume the
    # subscribe deterministically rather than letting it fall to the agent
    # (which would misroute the bare name to list_topics).
    if await _handle_subscribe_intent_router(message, state, current_user):
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
        # BUG-050: a deterministic preview/clarify hand-off supersedes any
        # pending subscribe-resume intent — drop it (CLEAR on FSM armed).
        await _clear_subscribe_intent(state)
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action=result.preview_pending,
            created_at=_utcnow_iso(),
        )
        # BUG-047: when the preview being armed is an unsubscribe_* SHOWN by id,
        # remember it as last_subscription so a later anaphora resolves to it.
        _preview_ls = _last_subscription_from_preview(result.preview_pending)
        if _preview_ls is not None:
            await state.update_data(last_subscription=_preview_ls)
        logger.info(
            "fsm_confirm_armed",
            tool=result.preview_pending.get("tool_name"),
            chat_id=message.chat.id,
        )
    elif result.clarify_pending:
        # BUG-039 / BUG-040: arm the clarify FSM so the next turn (an
        # affirmative «да» OR a bare channel-name reply) re-runs the
        # previewed subscribe with the corrected channel deterministically.
        await _clear_subscribe_intent(state)
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
    elif tool := _detect_subscribe_tool(user_text):
        # BUG-050 POST-agent detector (the ONLY subscribe_intent SET site).
        # The turn was a subscribe-create request AND the agent returned
        # TEXT-ONLY (no preview / clarify / pagination above) — i.e. the LLM
        # answered «канал X не найден…» conversationally instead of calling
        # subscribe_digest/subscribe_watchlist and arming the deterministic G2
        # clarify. Arm a TTL intent so the user's next BARE channel name resumes
        # the subscribe (instead of being misrouted to list_topics).
        await _set_subscribe_intent(
            state,
            tool_name=tool,
            requested_channel=_parse_subscribe_channel(user_text),
            partial_args=_subscribe_partial_args(user_text),
        )
        logger.info("subscribe_intent_set", tool=tool, chat_id=message.chat.id)


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

    # BUG-048 (Part C): intent-break at the TOP, before token classification.
    # When a write-preview is pending and the user sends an explicit NEW command
    # verb / question, ABANDON the un-executed preview and reroute (the preview
    # was never executed, so nothing is created / deleted). «да» / «нет» / unknown
    # non-command tokens («maybe») are NOT new intents — they fall through to the
    # confirm classification below (BUG-032 prompt preserved).
    if _looks_like_new_intent(text):
        await _release_fsm_and_reroute(message, agent, state, current_user)
        return

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
        _ls_before_confirm_clear = _data_before_confirm_clear.get("last_subscription")
        _di_before_confirm_clear = _data_before_confirm_clear.get("delete_intent")
        _si_before_confirm_clear = _data_before_confirm_clear.get("subscribe_intent")
        await state.clear()
        if _rc_before_confirm_clear is not None:
            await state.update_data(read_context=_rc_before_confirm_clear)
        # BUG-047: a subscribe_* confirm CREATED a subscription — remember it
        # (overriding any prior last_subscription) so a follow-up «удали эту
        # подписку» resolves deterministically; otherwise preserve the prior
        # last_subscription across this state.clear() (snapshot-and-restore).
        _new_ls = _build_last_subscription_from_result(tool_name, result)
        if _new_ls is not None:
            await state.update_data(last_subscription=_new_ls)
        elif _ls_before_confirm_clear is not None:
            await state.update_data(last_subscription=_ls_before_confirm_clear)
        # BUG-048 (Part A): a SUCCESSFUL unsubscribe confirm is the terminal step
        # of a delete flow → drop the intent. Any other confirmed tool preserves
        # it (snapshot-and-restore) until its own lifecycle end.
        if not _is_unsubscribe_tool(tool_name) and _di_before_confirm_clear is not None:
            await state.update_data(delete_intent=_di_before_confirm_clear)
        # BUG-050: a SUCCESSFUL subscribe confirm is the terminal step of a
        # subscribe-resume → drop the intent. Any other confirmed tool preserves
        # it (snapshot-and-restore) until its own lifecycle end.
        if not _is_subscribe_tool(tool_name) and _si_before_confirm_clear is not None:
            await state.update_data(subscribe_intent=_si_before_confirm_clear)
        await _send_text_response(message, _format_tool_result(tool_name, result))
        return

    if classification == "negative":
        _data_before_reject_clear = await state.get_data()
        _rc_before_reject_clear = _data_before_reject_clear.get("read_context")
        _ls_before_reject_clear = _data_before_reject_clear.get("last_subscription")
        _di_before_reject_clear = _data_before_reject_clear.get("delete_intent")
        _si_before_reject_clear = _data_before_reject_clear.get("subscribe_intent")
        await state.clear()
        if _rc_before_reject_clear is not None:
            await state.update_data(read_context=_rc_before_reject_clear)
        if _ls_before_reject_clear is not None:
            await state.update_data(last_subscription=_ls_before_reject_clear)
        # BUG-048 (Part A): «нет» on an unsubscribe confirm is a delete cancel →
        # drop the intent; any other confirm reject preserves it.
        if (
            not _is_unsubscribe_tool(pending_action.get("tool_name"))
            and _di_before_reject_clear is not None
        ):
            await state.update_data(delete_intent=_di_before_reject_clear)
        # BUG-050: «нет» on a subscribe confirm is a create cancel → drop the
        # intent; any other confirm reject preserves it.
        if (
            not _is_subscribe_tool(pending_action.get("tool_name"))
            and _si_before_reject_clear is not None
        ):
            await state.update_data(subscribe_intent=_si_before_reject_clear)
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
    _ls = data.get("last_subscription")
    _di = data.get("delete_intent")
    _si = data.get("subscribe_intent")
    _kind = clarify_action.get("kind", "subscribe")

    if _is_pending_expired(created_at_iso):
        await state.clear()
        if _rc is not None:
            await state.update_data(read_context=_rc)
        if _ls is not None:
            await state.update_data(last_subscription=_ls)
        # BUG-048: the clarify TTL (5 min) is shorter than the delete-intent TTL
        # (15 min) — preserve the intent so a bare-name retry still routes to a
        # delete after the clarify lapses.
        if _di is not None:
            await state.update_data(delete_intent=_di)
        # BUG-050: same rationale for a subscribe-resume intent.
        if _si is not None:
            await state.update_data(subscribe_intent=_si)
        await message.answer("⏱️ Время на уточнение истекло. Повторите запрос если нужно.")
        return

    text = (message.text or "").strip()
    classification = classify_confirmation_token(text)

    if classification == "negative":
        await state.clear()
        if _rc is not None:
            await state.update_data(read_context=_rc)
        if _ls is not None:
            await state.update_data(last_subscription=_ls)
        # BUG-048 (Part A): «нет» on a DELETE clarify (suggest / disambig) is a
        # delete cancel → drop the intent; on a subscribe / read clarify the
        # intent (if any) is unrelated and preserved.
        if _di is not None and _kind not in ("delete_suggest", "delete_disambig"):
            await state.update_data(delete_intent=_di)
        # BUG-050: «нет» on a SUBSCRIBE clarify is a create cancel → drop the
        # intent; on a delete / read clarify the subscribe intent (if any) is
        # unrelated and preserved.
        if _si is not None and _kind != "subscribe":
            await state.update_data(subscribe_intent=_si)
        await message.answer("❌ Отменено.")
        return

    # BUG-048 (Part C): intent-break / escape guard — after negative / TTL
    # handling, before treating the reply as a channel-name / confirm-token.
    # An explicit NEW command verb / question abandons the armed flow and
    # reroutes. For DELETE clarifies (suggest / disambig) a NEW *delete* verb is
    # NOT an escape — it keeps re-resolving in-flow (existing behaviour); only a
    # NON-delete command / question escapes. For subscribe / read clarifies any
    # new intent escapes. Bare channel names («profendocrinologist») don't match
    # `_looks_like_new_intent`, so BUG-040/043/045 stay intact.
    if _looks_like_new_intent(text):
        _delete_kind = _kind in ("delete_suggest", "delete_disambig")
        if not (_delete_kind and DELETE_VERB_PATTERN.match(text)):
            await _release_fsm_and_reroute(message, agent, state, current_user)
            return

    # BUG-047: a delete disambiguation clarify carries candidate subscriptions
    # (not a channel re-run). Resolve the user's selection by id or name and
    # arm the unsubscribe ConfirmFlow preview — the LLM is never consulted.
    if clarify_action.get("kind") == "delete_disambig":
        await _handle_delete_disambig_selection(message, state, clarify_action, current_user, text)
        return

    # BUG-047 follow-up: a delete SUGGESTION clarify (single near-miss). «да»
    # accepts the suggested subscription and routes through the unsubscribe
    # confirm-preview gate; any other text is re-resolved as a fresh name.
    if clarify_action.get("kind") == "delete_suggest":
        await _handle_delete_suggest_selection(
            message, state, clarify_action, current_user, text, classification
        )
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
        original_token = ""
        if 0 <= channel_index < len(channel_ids):
            original_token = str(channel_ids[channel_index])
            channel_ids[channel_index] = chosen
        else:
            channel_ids = [chosen]
        rerun_args = {**base_args, "channel_ids": channel_ids}
        # BUG-044: keep an AUTO-DERIVED subscription name consistent with the
        # CORRECTED channel. The LLM often derives the digest ``name`` /
        # watchlist ``title`` from the user's original (typo'd) text — e.g.
        # «Ежечасный дайджест pro fendocrinologist» — so after we substitute
        # the channel token the display name still embeds the typo. We rewrite
        # the name ONLY when it literally contains the original channel token
        # being corrected (precise substring at the corrected index, NOT a
        # blind global replace); a user-chosen name that doesn't embed the
        # token is left untouched — no guessing, no clobber.
        name_key = "title" if tool_name == "subscribe_watchlist" else "name"
        name_val = rerun_args.get(name_key)
        if (
            isinstance(name_val, str)
            and original_token
            and original_token != chosen
            and original_token in name_val
        ):
            rerun_args[name_key] = name_val.replace(original_token, chosen)

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
        await _send_text_response(message, _format_read_result(tool_name, result, channel=chosen))
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


def _read_intent_header(tool_name: str, channel: str | None, result: Any) -> str:
    """Per-intent preamble naming the RESOLVED channel for a read re-run.

    Defect-1 (final-smoke 2026-05-31): after a channel-not-found clarification
    the deterministic re-run jumped straight into the list, dropping the
    descriptive header the normal (LLM-rendered) path shows — e.g. «Показываю
    топ-20 тем канала profendocrinologist:» (the canonical wording from
    ``prompts/bot.yaml`` § implicit-context). That header is the user's
    confirmation of WHICH channel was finally resolved, so its absence after an
    AMBIGUOUS clarification is a fidelity gap, not mere cosmetics. We reproduce
    the same wording here (the normal header is composed by the model, so there
    is no shared Python string to import — we mirror the documented format).

    Returns ``""`` when no channel is known or the intent has no header.
    """
    if not channel or not isinstance(result, dict):
        return ""
    if tool_name == "list_topics":
        n = len(result.get("items") or [])
        if n <= 0:
            return ""
        return f"Показываю топ-{n} тем канала {channel}:"
    if tool_name == "search":
        return f"Результаты поиска в канале «{channel}»:"
    if tool_name == "get_cross_channel_stats":
        return f"Статистика по каналу «{channel}»:"
    return ""


def _format_read_result(tool_name: str, result: Any, channel: str | None = None) -> str:
    """Render a deterministically re-run READ tool result (BUG-039/040 residual).

    After a channel-not-found clarification on the read surface, the clarify
    handler re-runs the ORIGINAL read intent server-side (no LLM, so a bare
    «да» / channel token cannot be misrouted), then renders the structured
    result here:

    * a per-intent header (:func:`_read_intent_header`) naming the RESOLVED
      ``channel`` is prepended (Defect-1 fidelity fix), so the re-run matches
      the normal path and confirms which channel was resolved;
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
        body = _format_paginated_list(tool_name, result)
    elif isinstance(result.get("results"), list):
        hits = result["results"]
        if not hits:
            body = "📭 Ничего не найдено по запросу."
        else:
            lines: list[str] = []
            for i, hit in enumerate(hits, start=1):
                title = (
                    hit.get("summary")
                    or hit.get("text_preview")
                    or hit.get("source_ref")
                    or "(без названия)"
                )
                lines.append(f"<b>{i}.</b> {str(title)[:160]}")
            body = "\n".join(lines)
    else:
        msg = result.get("message")
        body = msg if isinstance(msg, str) and msg else f"✅ Готово: {tool_name}."

    header = _read_intent_header(tool_name, channel, result)
    return f"{header}\n\n{body}" if header else body


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


# ---------------------------------------------------------------------------
# BUG-047 — deterministic delete-by-name + anaphora routing
# ---------------------------------------------------------------------------

# Map a subscription kind to its unsubscribe tool + id parameter.
_DELETE_KIND_TOOLS: dict[str, tuple[str, str]] = {
    "digest": ("unsubscribe_digest", "subscription_id"),
    "watchlist": ("unsubscribe_watchlist", "interest_id"),
}

# Bare nouns that are NOT a concrete subscription name (e.g. «удали подписку»
# with no name) — treated as "no name" so they fall through rather than
# fuzzy-resolving the noun itself.
_BARE_DELETE_NOUNS: frozenset[str] = frozenset(
    {
        "подписку",
        "подписка",
        "подписки",
        "дайджест",
        "дайджеста",
        "watchlist",
        "вотчлист",
        "subscription",
        "алерт",
        "интерес",
        "interest",
    }
)


def _build_last_subscription_from_result(
    tool_name: str | None,
    result: Any,
) -> LastSubscriptionData | None:
    """Build a ``last_subscription`` snapshot from a CREATED subscription
    (the affirmative confirm of a ``subscribe_*``). Returns ``None`` for any
    other tool / a result without an id (BUG-047 B-2)."""
    if not isinstance(result, dict):
        return None
    if tool_name == "subscribe_digest":
        sid = result.get("subscription_id") or result.get("digest_id")
        if sid:
            return LastSubscriptionData(
                id=str(sid),
                kind="digest",
                name=str(result.get("name") or ""),
                created_at=_utcnow_iso(),
            )
    elif tool_name == "subscribe_watchlist":
        wid = result.get("watchlist_id") or result.get("interest_id")
        if wid:
            return LastSubscriptionData(
                id=str(wid),
                kind="watchlist",
                name=str(result.get("title") or ""),
                created_at=_utcnow_iso(),
            )
    return None


def _last_subscription_from_preview(
    preview_pending: dict[str, Any] | None,
) -> LastSubscriptionData | None:
    """Build a ``last_subscription`` snapshot when an ``unsubscribe_*`` preview
    by id is being armed — so a later anaphora resolves to it (BUG-047 B-2)."""
    if not isinstance(preview_pending, dict):
        return None
    tool = preview_pending.get("tool_name")
    args = preview_pending.get("args") or {}
    if tool == "unsubscribe_digest":
        sid = str(args.get("subscription_id") or "").strip()
        if sid:
            return LastSubscriptionData(id=sid, kind="digest", name="", created_at=_utcnow_iso())
    elif tool == "unsubscribe_watchlist":
        iid = str(args.get("interest_id") or "").strip()
        if iid:
            return LastSubscriptionData(id=iid, kind="watchlist", name="", created_at=_utcnow_iso())
    return None


async def _last_subscription_for_router(state: FSMContext) -> dict[str, Any] | None:
    """Return the non-stale ``last_subscription`` context, or None (BUG-047).

    TTL mirrors ``read_context`` (``READ_CONTEXT_TTL_SECONDS``, 15 min); a
    missing / unparseable timestamp is treated as stale (fail-safe), so an
    anaphora can never resolve to an expired reference.
    """
    data = await state.get_data()
    ls = data.get("last_subscription")
    if not ls or not isinstance(ls, dict):
        return None
    if _is_stale(ls.get("created_at"), READ_CONTEXT_TTL_SECONDS):
        return None
    return ls


# Unsubscribe tools — a SUCCESSFUL confirm of one (or a «нет» reject of one) is
# the terminal step of a delete flow and clears any persisted ``delete_intent``.
_UNSUBSCRIBE_TOOLS: frozenset[str] = frozenset({"unsubscribe_digest", "unsubscribe_watchlist"})


def _is_unsubscribe_tool(tool_name: str | None) -> bool:
    return tool_name in _UNSUBSCRIBE_TOOLS


async def _set_delete_intent(state: FSMContext, *, requested: str | None = None) -> None:
    """Record an explicit delete intent (BUG-048, Part A).

    Written the moment a delete verb / anaphora is seen, and refreshed whenever
    a deterministic delete flow is (re-)armed — so a later BARE subscription
    name (after an intervening junk/clear) still routes to a DELETE rather than
    falling to the stateless agent (which mis-emits ``subscribe_digest``).
    TTL-anchored to ``created_at`` (``READ_CONTEXT_TTL_SECONDS``, 15 min).
    """
    intent: DeleteIntentData = {"created_at": _utcnow_iso()}
    if requested:
        intent["requested"] = requested
    await state.update_data(delete_intent=intent)


async def _delete_intent_for_router(state: FSMContext) -> dict[str, Any] | None:
    """Return the non-stale ``delete_intent`` snapshot, or None (BUG-048).

    TTL mirrors ``read_context`` / ``last_subscription`` (15 min); a missing /
    ``None`` / unparseable value is treated as absent (lazy TTL expiry), so a
    stale intent can never reroute a bare name into a delete.
    """
    data = await state.get_data()
    di = data.get("delete_intent")
    if not di or not isinstance(di, dict):
        return None
    if _is_stale(di.get("created_at"), READ_CONTEXT_TTL_SECONDS):
        return None
    return di


async def _clear_delete_intent(state: FSMContext) -> None:
    """Drop any persisted ``delete_intent`` (terminal delete-flow step)."""
    await state.update_data(delete_intent=None)


# BUG-050 — subscribe tools. A SUCCESSFUL confirm of one clears any persisted
# ``subscribe_intent`` (the create flow reached its terminal step).
_SUBSCRIBE_TOOLS: frozenset[str] = frozenset({"subscribe_digest", "subscribe_watchlist"})


def _is_subscribe_tool(tool_name: str | None) -> bool:
    return tool_name in _SUBSCRIBE_TOOLS


async def _set_subscribe_intent(
    state: FSMContext,
    *,
    tool_name: str = "subscribe_digest",
    requested_channel: str | None = None,
    partial_args: dict[str, Any] | None = None,
) -> None:
    """Record an explicit subscribe-create intent (BUG-050).

    Written by the POST-agent detector when a subscribe-create turn returned
    TEXT-ONLY (the LLM bypassed ``subscribe_digest`` / ``subscribe_watchlist``
    and answered «канал не найден» conversationally), so the user's follow-up
    bare channel name resumes the subscribe deterministically instead of being
    misrouted to ``list_topics``. TTL-anchored to ``created_at``
    (``READ_CONTEXT_TTL_SECONDS``, 15 min).
    """
    intent: SubscribeIntentData = {"created_at": _utcnow_iso(), "tool_name": tool_name}
    if requested_channel:
        intent["requested_channel"] = requested_channel
    if partial_args:
        intent["partial_args"] = dict(partial_args)
    await state.update_data(subscribe_intent=intent)


async def _subscribe_intent_for_router(state: FSMContext) -> dict[str, Any] | None:
    """Return the non-stale ``subscribe_intent`` snapshot, or None (BUG-050).

    TTL mirrors ``read_context`` / ``last_subscription`` / ``delete_intent``
    (15 min); a missing / ``None`` / unparseable value is treated as absent
    (lazy TTL expiry), so a stale intent can never resume a bare name into a
    subscribe.
    """
    data = await state.get_data()
    si = data.get("subscribe_intent")
    if not si or not isinstance(si, dict):
        return None
    if _is_stale(si.get("created_at"), READ_CONTEXT_TTL_SECONDS):
        return None
    return si


async def _clear_subscribe_intent(state: FSMContext) -> None:
    """Drop any persisted ``subscribe_intent`` (terminal subscribe-flow step)."""
    await state.update_data(subscribe_intent=None)


def _delete_name_candidates(text: str) -> list[str]:
    """Ordered candidate subscription names to resolve after a delete verb.

    The leading noun («подписку»/«дайджест»/«watchlist»/…) is genuinely
    ambiguous — it can be a connector («удали подписку Genotek») OR part of the
    real name («удали Ежечасный дайджест Genotek»). So we try the FULL remainder
    first (verb stripped only), then the noun-stripped variant as a fallback —
    the first that resolves / is ambiguous wins. A bare «удали» / «удали
    подписку» yields no candidate (falls through to the agent)."""
    stripped = DELETE_VERB_PATTERN.sub("", text, count=1).strip()
    if not stripped:
        return []
    out: list[str] = []
    if stripped.casefold() not in _BARE_DELETE_NOUNS:
        out.append(stripped)
    no_noun = _DELETE_NOUN_PREFIX.sub("", stripped).strip()
    if no_noun and no_noun != stripped and no_noun.casefold() not in _BARE_DELETE_NOUNS:
        out.append(no_noun)
    # BUG-049: a leading preposition («на genotek») hides the bare token from the
    # substring/fuzzy suggest tier. Append the preposition-stripped remainder as
    # a LAST-RESORT fallback (AFTER the existing candidates) — `_best_delete_match`
    # prefers the first actionable outcome, so this never changes behavior for
    # inputs that already resolve / disambiguate / suggest on an earlier shape.
    for base in (no_noun, stripped):
        bare = _DELETE_PREPOSITION_PREFIX.sub("", base).strip()
        if bare and bare != base and bare not in out and bare.casefold() not in _BARE_DELETE_NOUNS:
            out.append(bare)
    return out


async def _best_delete_match(
    text: str,
    current_user: CurrentUser | None,
) -> tuple[str, dict[str, Any]] | None:
    """Resolve a free-text delete target into ``(name, match)`` (BUG-047 D1).

    Shared by the bare-name pre-router AND the ``delete_suggest`` re-resolution
    branch so BOTH passes slice the reply identically: an ordered candidate list
    (full remainder with the delete verb stripped, then the connector-noun
    stripped variant — :func:`_delete_name_candidates`) is resolved
    owner-scoped, preferring the FIRST actionable outcome
    (``resolved`` / ``ambiguous`` / ``suggest``) over a bare ``not_found``.

    Returns:

    * ``None`` — there is no candidate at all (a bare «удали» / bare connector
      noun); the caller falls back (agent path / re-ask);
    * ``(candidate, {"status": "unavailable"})`` — a transient repo error on a
      candidate; the caller falls back without falsely claiming «не найдена»;
    * ``(name, match)`` — the best resolver outcome to route via
      :func:`_route_delete_match`.

    Before D1 the pre-router did this candidate slicing but the
    ``delete_suggest`` re-resolution fed the WHOLE reply to the resolver once —
    so a noun-/verb-prefixed «another name» (e.g. «подписку Genotek») fell to an
    FSM-less not-found and the follow-up «да» dead-ended (G1-class). Routing
    both passes through this helper removes that asymmetry.
    """
    names = _delete_name_candidates(text)
    if not names:
        return None
    name = names[0]
    match: dict[str, Any] | None = None
    for candidate in names:
        m = await resolve_subscription_by_name(candidate, current_user)
        if m.get("status") == "unavailable":
            return candidate, m
        # A high-confidence resolve / disambiguation / single near-miss
        # suggestion are all actionable — prefer them over a bare not-found.
        if m.get("status") in ("resolved", "ambiguous", "suggest"):
            return candidate, m
        if match is None:
            # Remember the first not-found (the full remainder) for messaging.
            name, match = candidate, m
    assert match is not None  # loop always assigns at least the first not-found
    return name, match


async def _arm_delete_preview(
    message: Message,
    state: FSMContext,
    *,
    tool_name: str,
    id_param: str,
    resolved_id: str,
    current_user: CurrentUser | None,
) -> bool:
    """Run the resolved ``unsubscribe_*`` as a confirm=false PREVIEW and arm the
    EXISTING BUG-046 ConfirmFlow gate (the LLM is never consulted). The preview
    text is the executor's own deterministic «… будет удал… [да/нет]» message,
    rendered verbatim (BUG-042 lineage). Returns True (the turn is handled)."""
    try:
        result = await execute_tool(
            tool_name,
            {id_param: resolved_id, "confirm": False},
            current_user=current_user,
            bot=message.bot,
            chat_id=message.chat.id,
        )
    except Exception:
        logger.exception("delete_prerouter_execute_failed", tool=tool_name)
        await message.answer(format_error("Внутренняя ошибка при подготовке удаления."))
        return True

    if isinstance(result, dict) and result.get("preview") is True:
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": tool_name, "args": {id_param: resolved_id}},
            created_at=_utcnow_iso(),
        )
        # BUG-048 (Part A): a delete confirm-preview is the deterministic delete
        # flow (pre-router resolved / anaphora / delete_suggest «да» accept /
        # disambig selection) — (re-)record the intent so it survives until the
        # confirm «да» (success) or «нет» (cancel) clears it.
        await _set_delete_intent(state)
        logger.info("fsm_confirm_armed", tool=tool_name, chat_id=message.chat.id)
        msg = result.get("message")
        if isinstance(msg, str) and msg:
            await _send_html_response(message, msg)
        else:
            await _send_text_response(message, _format_tool_result(tool_name, result))
        return True

    # Not a preview (not-found / permission / error) — surface it, don't wedge.
    await _send_text_response(message, _format_tool_result(tool_name, result))
    return True


async def _handle_delete_disambig_selection(
    message: Message,
    state: FSMContext,
    clarify_action: dict[str, Any],
    current_user: CurrentUser | None,
    text: str,
) -> None:
    """Resolve the user's selection on a ``delete_disambig`` clarify (by id or
    name) and arm the unsubscribe preview; re-ask when still ambiguous."""
    candidates = clarify_action.get("candidates") or []
    selection = (text or "").strip()

    chosen: dict[str, Any] | None = None
    for c in candidates:
        if str(c.get("id")) == selection:
            chosen = c
            break
    if chosen is None:
        items = [{"id": c["id"], "name": c["name"], "kind": c["kind"]} for c in candidates]
        match = _match_subscription_items(selection, items)
        if match.get("status") == "resolved":
            chosen = {"id": match["id"], "name": match["name"], "kind": match["kind"]}

    if chosen is None:
        # Keep the clarify FSM armed; refresh the TTL anchor and re-ask.
        await state.update_data(created_at=_utcnow_iso())
        await message.answer(
            "Не понял, какую подписку удалить. Пришлите точное название или ID "
            "из списка, либо «нет» для отмены."
        )
        return

    kind = str(chosen.get("kind") or "")
    if kind not in _DELETE_KIND_TOOLS:
        await state.clear()
        await message.answer("Внутренняя ошибка: неизвестный тип подписки.")
        return
    tool_name, id_param = _DELETE_KIND_TOOLS[kind]
    logger.info("delete_disambig_selected", kind=kind, chat_id=message.chat.id)
    await _arm_delete_preview(
        message,
        state,
        tool_name=tool_name,
        id_param=id_param,
        resolved_id=str(chosen["id"]),
        current_user=current_user,
    )


async def _route_delete_match(
    message: Message,
    state: FSMContext,
    *,
    requested_name: str,
    match: dict[str, Any],
    current_user: CurrentUser | None,
) -> bool:
    """Arm the right deterministic outcome for a resolver ``match`` (BUG-047).

    Shared by the pre-router (bare-name path) and the ``delete_suggest``
    re-resolution branch so the four terminal shapes stay consistent:

    * ``resolved`` → arm the unsubscribe confirm-preview gate;
    * ``ambiguous`` → arm a ``delete_disambig`` clarify (list with IDs);
    * ``suggest`` → arm a ``delete_suggest`` clarify (single near-miss, «да»-able);
    * ``not_found`` → a deterministic not-found message; the FSM is cleared
      (read_context / last_subscription snapshot-restored) so a stray «да»
      afterwards is inert.

    Always returns ``True`` — the turn was handled deterministically.
    """
    status = match.get("status")
    if status == "resolved":
        kind = str(match["kind"])
        if kind not in _DELETE_KIND_TOOLS:
            await state.clear()
            await message.answer("Внутренняя ошибка: неизвестный тип подписки.")
            return True
        tool_name, id_param = _DELETE_KIND_TOOLS[kind]
        logger.info("delete_prerouter_name_resolved", kind=kind, chat_id=message.chat.id)
        return await _arm_delete_preview(
            message,
            state,
            tool_name=tool_name,
            id_param=id_param,
            resolved_id=str(match["id"]),
            current_user=current_user,
        )

    if status == "ambiguous":
        clarify = _build_delete_disambig_clarify(requested_name, match["candidates"])
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(clarify_action=clarify, created_at=_utcnow_iso())
        # BUG-048 (Part A): arming a delete clarify enters a deterministic delete
        # flow — (re-)record the intent so it survives a later clear.
        await _set_delete_intent(state, requested=requested_name)
        logger.info(
            "delete_prerouter_ambiguous",
            count=len(match["candidates"]),
            chat_id=message.chat.id,
        )
        await _send_text_response(message, clarify["message"])
        return True

    if status == "suggest":
        clarify = _build_delete_suggest_clarify(requested_name, match["suggestion"])
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(clarify_action=clarify, created_at=_utcnow_iso())
        # BUG-048 (Part A): see the ambiguous branch above.
        await _set_delete_intent(state, requested=requested_name)
        logger.info(
            "delete_prerouter_suggest",
            kind=match["suggestion"].get("kind"),
            chat_id=message.chat.id,
        )
        await _send_text_response(message, clarify["message"])
        return True

    # not_found — clear the FSM (preserving read_context / last_subscription /
    # delete_intent) so a stray «да» can never fire a false delete, yet the
    # explicit delete intent stays alive for one more bare-name attempt within
    # TTL (BUG-048: a hard not-found does NOT immediately clear the intent).
    data = await state.get_data()
    _rc = data.get("read_context")
    _ls = data.get("last_subscription")
    _di = data.get("delete_intent")
    _si = data.get("subscribe_intent")
    await state.clear()
    if _rc is not None:
        await state.update_data(read_context=_rc)
    if _ls is not None:
        await state.update_data(last_subscription=_ls)
    if _di is not None:
        await state.update_data(delete_intent=_di)
    # BUG-050: preserve a concurrent subscribe-resume intent across this clear.
    if _si is not None:
        await state.update_data(subscribe_intent=_si)
    closest = match.get("closest")
    hint = f" Ближайшее совпадение: «{closest}»." if closest else ""
    logger.info("delete_prerouter_not_found", chat_id=message.chat.id)
    await _send_text_response(message, f"Подписка с названием «{requested_name}» не найдена.{hint}")
    return True


async def _handle_delete_suggest_selection(
    message: Message,
    state: FSMContext,
    clarify_action: dict[str, Any],
    current_user: CurrentUser | None,
    text: str,
    classification: str,
) -> None:
    """Resolve the user's reply on a ``delete_suggest`` clarify (BUG-047
    follow-up).

    * **affirmative** («да», «ok», …) → accept the suggested subscription and
      arm the unsubscribe confirm-preview gate (the actual delete still needs a
      SECOND «да» — BUG-009 / BUG-046 contract preserved; nothing is deleted on
      the acceptance turn);
    * **anything else** → treat the reply as a DIFFERENT subscription name and
      re-resolve it owner-scoped (resolved → preview, ambiguous → disambig,
      another near-miss → a fresh suggest, nothing → not-found).

    (The «нет»/negative cancel is handled by the caller before dispatch.)
    """
    suggestion = clarify_action.get("suggestion") or {}
    if classification == "affirmative":
        kind = str(suggestion.get("kind") or "")
        rid = str(suggestion.get("id") or "")
        if not rid or kind not in _DELETE_KIND_TOOLS:
            await state.clear()
            await message.answer("Внутренняя ошибка: контекст уточнения утерян. Повторите запрос.")
            return
        tool_name, id_param = _DELETE_KIND_TOOLS[kind]
        logger.info("delete_suggest_accepted", kind=kind, chat_id=message.chat.id)
        await _arm_delete_preview(
            message,
            state,
            tool_name=tool_name,
            id_param=id_param,
            resolved_id=rid,
            current_user=current_user,
        )
        return

    # A different name typed in place of «да»/«нет» → re-resolve owner-scoped.
    # D1 (BUG-047): slice the reply with the SAME candidate logic the pre-router
    # uses (``_best_delete_match`` → verb + connector-noun stripping) so a
    # noun-/verb-prefixed «another name» (e.g. «подписку Genotek») re-arms the
    # clarify exactly like the first pass instead of dead-ending on an FSM-less
    # not-found.
    if not (text or "").strip():
        await state.update_data(created_at=_utcnow_iso())
        await message.answer(
            "Уточните: ответьте «да», чтобы удалить предложенную подписку, "
            "пришлите другое название или «нет» для отмены."
        )
        return
    resolved = await _best_delete_match(text, current_user)
    if resolved is None:
        # No resolvable candidate (a bare connector noun) — keep the clarify
        # armed so the user can answer «да»/«нет» or send a real name.
        await state.update_data(created_at=_utcnow_iso())
        await message.answer(
            "Уточните: ответьте «да», чтобы удалить предложенную подписку, "
            "пришлите другое название или «нет» для отмены."
        )
        return
    name, match = resolved
    if match.get("status") == "unavailable":
        # Transient repo error — keep the clarify armed so the user can retry.
        await state.update_data(created_at=_utcnow_iso())
        await message.answer(
            "Не удалось проверить подписки сейчас. Повторите попытку чуть позже "
            "или «нет» для отмены."
        )
        return
    logger.info("delete_suggest_reresolve", status=match.get("status"), chat_id=message.chat.id)
    await _route_delete_match(
        message, state, requested_name=name, match=match, current_user=current_user
    )


async def _handle_delete_prerouter(
    message: Message,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> bool:
    """Deterministic delete / anaphora pre-router (BUG-047 B-3).

    Fires ONLY on an explicit delete-intent signal so it never hijacks
    questions / search / subscribe flows:

    * the message STARTS with a delete verb («удали», «delete», «убери»,
      «отпишись», «unsubscribe»); OR
    * it contains an anaphora token («эту подписку» / «её» / «последнюю» /
      «this subscription») backed by a NON-STALE ``last_subscription``.

    A channel-domain hint («канал X» / «по каналу X») suppresses the router so
    ``remove_channel`` and the out-of-scope «по каналу X» phrasing fall through
    to the agent. Returns True when the turn was handled deterministically
    (preview armed / disambiguation / not-found), False to fall through.
    """
    text = (message.text or "").strip()
    if not text or current_user is None:
        return False

    has_delete_verb = bool(DELETE_VERB_PATTERN.match(text))
    has_anaphora = bool(ANAPHORA_PATTERN.search(text))
    if not has_delete_verb and not has_anaphora:
        return False
    if _CHANNEL_HINT_PATTERN.search(text):
        return False

    # BUG-048 (Part A): the user has EXPLICITLY expressed a delete intent (a
    # leading delete verb or a delete anaphora that passed the channel-hint
    # guard). Persist it now — BEFORE routing — so it survives even a hard
    # not-found / an intervening junk-reply FSM clear, and a later bare name
    # still routes to a DELETE (never falls to the agent → create misroute).
    await _set_delete_intent(state, requested=text if has_delete_verb else None)

    # 1) Anaphora → the most-recently referenced subscription (non-stale).
    if has_anaphora:
        last_sub = await _last_subscription_for_router(state)
        if last_sub is None:
            # Stale / absent reference — fall through to the LLM (no false
            # delete; BUG-047 TTL contract).
            return False
        kind = str(last_sub.get("kind") or "")
        rid = str(last_sub.get("id") or "")
        if not rid or kind not in _DELETE_KIND_TOOLS:
            return False
        tool_name, id_param = _DELETE_KIND_TOOLS[kind]
        logger.info("delete_prerouter_anaphora", kind=kind, chat_id=message.chat.id)
        return await _arm_delete_preview(
            message,
            state,
            tool_name=tool_name,
            id_param=id_param,
            resolved_id=rid,
            current_user=current_user,
        )

    # 2) Bare subscription NAME after a delete verb.
    resolved = await _best_delete_match(text, current_user)
    if resolved is None:
        return False
    name, match = resolved
    if match.get("status") == "unavailable":
        # Transient repo error — let the agent try rather than falsely 404.
        return False
    return await _route_delete_match(
        message, state, requested_name=name, match=match, current_user=current_user
    )


async def _release_fsm_and_reroute(
    message: Message,
    agent: GeminiAgent,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> None:
    """Abandon a greedy ConfirmFlow / ClarifyFlow and re-dispatch the turn
    (BUG-048, Part C).

    Modeled on the PaginationFlow D-4 fall-through: clear the FSM, snapshot-and-
    restore ``read_context`` / ``last_subscription`` (so cross-turn channel /
    subscription context survives), then recurse into :func:`handle_text` so the
    NEW intent is routed exactly like a fresh turn (pre-router → delete-intent
    router → agent).

    The persisted ``delete_intent`` is INTENTIONALLY NOT restored: an explicit
    new-intent escape ends the delete flow (BUG-048 lifecycle). If the new
    intent is itself a delete (a delete verb), the pre-router re-records the
    intent on re-dispatch, so nothing is lost where it matters.
    """
    data = await state.get_data()
    _rc = data.get("read_context")
    _ls = data.get("last_subscription")
    _si = data.get("subscribe_intent")
    await state.clear()
    if _rc is not None:
        await state.update_data(read_context=_rc)
    if _ls is not None:
        await state.update_data(last_subscription=_ls)
    # BUG-050: preserve a pending subscribe-resume intent across the reroute
    # (the re-dispatched subscribe_intent_router CLEARS it when the new intent is
    # an explicit command / question — so a genuine escape still drops it).
    if _si is not None:
        await state.update_data(subscribe_intent=_si)
    logger.info("fsm_intent_break_reroute", chat_id=message.chat.id)
    await handle_text(message, agent=agent, state=state, current_user=current_user)


async def _handle_delete_intent_router(
    message: Message,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> bool:
    """Persisted-delete-intent router (BUG-048, Part A — fixes defect 1).

    Runs in ``handle_text`` AFTER :func:`_handle_delete_prerouter` and BEFORE
    the agent. When a non-stale ``delete_intent`` is active and the message is a
    BARE subscription name (NOT a new intent, NO delete verb — the pre-router
    already handled those — and NO channel hint), it re-resolves the name
    owner-scoped and routes via :func:`_route_delete_match` exactly like the
    pre-router would. This closes the delete→junk→bare-name → CREATE misroute:
    without it the bare name fell to the stateless agent and the LLM emitted
    ``subscribe_digest`` (create) instead of a delete.

    Contract:

    * NEVER executes a tool with ``confirm=True`` — only produces a
      preview / disambig / suggest (the BUG-046 two-step confirm gate is
      preserved; the actual delete still needs a separate «да»).
    * A stray «да» / «нет» (or any affirmative / negative token) is NEVER
      treated as a deletable name (BUG-047 D1 — it stays inert and falls through
      to the agent).

    Returns True when the turn was handled deterministically, False to fall
    through to the agent.
    """
    text = (message.text or "").strip()
    if not text or current_user is None:
        return False
    if await _delete_intent_for_router(state) is None:
        return False
    # A bare affirmative / negative token is never a deletable name (D1 inert
    # «да») and a new explicit intent / delete verb / channel op are handled
    # elsewhere — only a plain bare name reaches the resolver here.
    if classify_confirmation_token(text) != "unknown":
        return False
    if _looks_like_new_intent(text):
        return False
    if DELETE_VERB_PATTERN.match(text):
        return False
    if _CHANNEL_HINT_PATTERN.search(text):
        return False

    resolved = await _best_delete_match(text, current_user)
    if resolved is None:
        return False
    name, match = resolved
    if match.get("status") == "unavailable":
        return False
    logger.info(
        "delete_intent_router_resolved",
        status=match.get("status"),
        chat_id=message.chat.id,
    )
    return await _route_delete_match(
        message, state, requested_name=name, match=match, current_user=current_user
    )


async def _handle_subscribe_intent_router(
    message: Message,
    state: FSMContext,
    current_user: CurrentUser | None,
) -> bool:
    """Persisted-subscribe-intent router (BUG-050).

    Runs in ``handle_text`` AFTER :func:`_handle_delete_intent_router` and BEFORE
    the agent. When a non-stale ``subscribe_intent`` is active and the message is
    a BARE channel-like token (NOT a new intent, NOT a confirm/negative token, NO
    delete verb, and NO active ``delete_intent`` — delete precedence), it merges
    the token as the channel into the (partial) subscribe args, re-runs
    ``subscribe_digest`` (confirm=false) and arms the EXISTING ClarifyFlow /
    ConfirmFlow gate exactly like the clarify re-run path. This closes the
    subscribe→LLM-channel-not-found→bare-name → ``list_topics`` misroute.

    Contract:

    * NEVER executes a tool with ``confirm=True`` — only a preview / clarify
      (the BUG-031/045 two-step gate is preserved).
    * An explicit NEW command / question ends the resume flow → ``subscribe_intent``
      is CLEARED and the turn falls through to the agent (BUG-050 lifecycle).
    * A stray «да» / «нет» stays inert (keeps the intent, falls through).
    * A delete verb / an active ``delete_intent`` defers to the delete surface
      (delete precedence).

    Returns True when the turn was handled deterministically, False to fall
    through to the agent.
    """
    text = (message.text or "").strip()
    if not text or current_user is None:
        return False
    if await _subscribe_intent_for_router(state) is None:
        return False

    # An explicit new command / question ENDS the resume flow (BUG-050
    # lifecycle): clear the intent and let the agent route the new intent. Bare
    # channel names do NOT match ``_looks_like_new_intent`` so they stay in-flow.
    if _looks_like_new_intent(text):
        await _clear_subscribe_intent(state)
        return False
    # A bare affirmative / negative token is never a channel — stay inert (keep
    # the intent so a later real bare name still resumes) and fall through.
    if classify_confirmation_token(text) != "unknown":
        return False
    # Delete precedence — a delete verb or an active delete_intent owns the turn.
    if DELETE_VERB_PATTERN.match(text):
        return False
    if await _delete_intent_for_router(state) is not None:
        return False

    channel = _bare_channel_token(text)
    if not channel:
        return False

    si = await _subscribe_intent_for_router(state) or {}
    partial: dict[str, Any] = dict(si.get("partial_args") or {})
    tool_name = si.get("tool_name") or "subscribe_digest"
    rerun_args = _subscribe_intent_rerun_args(tool_name, channel, partial)

    logger.info(
        "subscribe_intent_router_resume",
        tool=tool_name,
        channel=channel,
        chat_id=message.chat.id,
    )
    try:
        # Re-run as a PREVIEW turn (no confirm) so the resolved channel goes
        # through the full preview/confirm + G2 clarify contract.
        result = await execute_tool(
            tool_name,
            rerun_args,
            current_user=current_user,
            bot=message.bot,
            chat_id=message.chat.id,
        )
    except Exception:
        logger.exception("subscribe_intent_router_execute_failed")
        await message.answer(format_error("Внутренняя ошибка при оформлении подписки."))
        return True

    if isinstance(result, dict) and result.get("clarify_pending"):
        # The resumed channel is ALSO not-found with a suggestion (G2) — arm the
        # clarify FSM with the fresh suggestion and relay it verbatim. The
        # subscribe intent has been handed off to the deterministic flow → drop.
        await _clear_subscribe_intent(state)
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=result["clarify_pending"],
            created_at=_utcnow_iso(),
        )
        clarify_text = result["clarify_pending"].get("message") or _format_tool_result(
            tool_name, result
        )
        logger.info("fsm_clarify_armed", tool=tool_name, chat_id=message.chat.id)
        await _send_text_response(message, clarify_text)
        return True

    if isinstance(result, dict) and result.get("preview") is True:
        # Valid preview for the resolved channel — hand off to ConfirmFlow
        # exactly like a normal preview turn (render the tool's own message
        # verbatim, BUG-042 lineage). The subscribe intent is consumed → drop.
        await _clear_subscribe_intent(state)
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={"tool_name": tool_name, "args": rerun_args},
            created_at=_utcnow_iso(),
        )
        logger.info("fsm_confirm_armed", tool=tool_name, chat_id=message.chat.id)
        msg = result.get("message")
        if isinstance(msg, str) and msg:
            await _send_html_response(message, msg)
        else:
            await _send_text_response(message, _format_tool_result(tool_name, result))
        return True

    # Non-clarifiable error (permission / cron / still-not-found w/o suggestion)
    # — keep the intent alive (refresh the TTL anchor) so the user can supply
    # another channel, and surface the reason deterministically.
    await _set_subscribe_intent(
        state,
        tool_name=tool_name,
        requested_channel=si.get("requested_channel"),
        partial_args=partial,
    )
    await _send_text_response(message, _format_tool_result(tool_name, result))
    return True
