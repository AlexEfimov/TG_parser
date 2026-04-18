"""
Scheduled-Digest service (F6).

Generates and delivers a Markdown digest of new ProcessedDocument-s for a single
``DigestSubscription``. Designed to be invoked from APScheduler tasks running
inside the bot process.

Key invariants:

- Strict ``processed_at > last_digest_cursor`` filter — equality would re-include
  the most recent document on the next tick. ``ProcessedDocumentRepo.list_by_channel``
  uses ``>=`` semantics, so the service filters again in Python.
- ``digest_max_docs_per_run`` is a per-channel cap, not a global one — a noisy
  channel cannot starve quieter channels.
- On the first run (``last_digest_cursor is None``) we look back
  ``first_run_lookback_hours`` hours, then advance the cursor to ``now`` even if
  the result is empty so we don't repeat the lookback every tick.
- Cursor + ``last_sent_at`` are persisted ONLY after successful delivery (or
  successful skip-because-empty); a failed ``Bot.send_message`` leaves the
  subscription untouched so the next tick retries.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from tg_parser.domain.models import (
    DigestFormat,
    DigestSubscription,
    ProcessedDocument,
)
from tg_parser.processing.prompt_loader import PromptLoader
from tg_parser.storage.ports import (
    DigestSubscriptionRepo,
    IngestionStateRepo,
    ProcessedDocumentRepo,
)

if TYPE_CHECKING:
    from aiogram import Bot

    from tg_parser.processing.ports import LLMClient


logger = structlog.get_logger(__name__)


# ----------------------------------------------------------------------------
# Markdown V2 helpers
# ----------------------------------------------------------------------------


_MD_V2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"


def escape_markdown_v2(text: str) -> str:
    """Escape every Telegram MarkdownV2 special char in ``text``.

    Used both for dynamic strings inserted into the title (channel names, dates)
    and for the entire LLM-produced body — we cannot trust the LLM to produce
    valid V2 markup, so escaping the body sacrifices intentional formatting in
    exchange for guaranteed safe delivery.
    """
    if not text:
        return ""
    pattern = "[" + re.escape(_MD_V2_SPECIAL) + "]"
    return re.sub(pattern, r"\\\g<0>", text)


# ----------------------------------------------------------------------------
# Result dataclass
# ----------------------------------------------------------------------------


@dataclass
class DigestResult:
    """Outcome of one digest generation run for a subscription."""

    subscription_id: str
    chat_id: int
    title: str
    body_markdown: str
    docs_count: int
    new_cursor: datetime | None
    skipped: bool
    delivery_failed: bool = False
    delivery_error: str | None = None
    per_channel_counts: dict[str, int] = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------


LLMClientFactory = Callable[[], "LLMClient"]


class DigestService:
    """Compose digest text and deliver it to Telegram for a subscription."""

    def __init__(
        self,
        processed_repo: ProcessedDocumentRepo,
        ingestion_repo: IngestionStateRepo,
        subscription_repo: DigestSubscriptionRepo,
        prompt_loader: PromptLoader,
        llm_client_factory: LLMClientFactory,
        *,
        max_docs_per_run: int = 50,
        first_run_lookback_hours: int = 24,
        message_max_chars: int = 4096,
        max_message_parts: int = 10,
        prompt_name: str = "digest",
    ):
        self._processed_repo = processed_repo
        self._ingestion_repo = ingestion_repo
        self._subscription_repo = subscription_repo
        self._prompt_loader = prompt_loader
        self._llm_client_factory = llm_client_factory
        self._max_docs_per_run = max(1, int(max_docs_per_run))
        self._first_run_lookback_hours = max(1, int(first_run_lookback_hours))
        self._message_max_chars = max(512, int(message_max_chars))
        self._max_message_parts = max(1, int(max_message_parts))
        self._prompt_name = prompt_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, sub: DigestSubscription) -> DigestResult:
        """Fetch new docs, summarise via LLM, return ``DigestResult``."""
        now = datetime.now(UTC)
        cursor = sub.last_digest_cursor
        first_run = cursor is None
        if first_run:
            from_date = now - timedelta(hours=self._first_run_lookback_hours)
        else:
            from_date = cursor  # type: ignore[assignment]

        per_channel_docs: dict[str, list[ProcessedDocument]] = {}
        per_channel_total: dict[str, int] = {}
        max_processed_at: datetime | None = None
        all_docs: list[ProcessedDocument] = []

        for channel_id in sub.channel_ids:
            try:
                fetched = await self._processed_repo.list_by_channel(
                    channel_id,
                    from_date=from_date,
                    to_date=now,
                )
            except Exception as exc:
                logger.warning(
                    "digest.fetch_failed",
                    subscription_id=sub.id,
                    channel_id=channel_id,
                    error=str(exc),
                )
                continue

            filtered = [
                d
                for d in fetched
                if d.processed_at is not None
                and (cursor is None or _to_utc(d.processed_at) > _to_utc(cursor))
            ]
            filtered.sort(key=lambda d: d.processed_at, reverse=True)
            per_channel_total[channel_id] = len(filtered)
            kept = filtered[: self._max_docs_per_run]
            per_channel_docs[channel_id] = kept
            for d in kept:
                if d.processed_at is not None:
                    cur_pa = _to_utc(d.processed_at)
                    if max_processed_at is None or cur_pa > max_processed_at:
                        max_processed_at = cur_pa
                    all_docs.append(d)

        docs_count = sum(len(v) for v in per_channel_docs.values())
        title = self._build_title(sub, now)

        if docs_count == 0:
            new_cursor = now if first_run else cursor
            return DigestResult(
                subscription_id=sub.id,
                chat_id=sub.chat_id,
                title=title,
                body_markdown="",
                docs_count=0,
                new_cursor=new_cursor,
                skipped=True,
                per_channel_counts={cid: 0 for cid in sub.channel_ids},
            )

        channels_block = self._render_channels_block(
            sub,
            per_channel_docs,
            per_channel_total,
        )
        body_markdown = await self._call_llm(
            sub=sub,
            channels_block=channels_block,
            from_iso=_iso(from_date),
            to_iso=_iso(now),
        )

        return DigestResult(
            subscription_id=sub.id,
            chat_id=sub.chat_id,
            title=title,
            body_markdown=body_markdown,
            docs_count=docs_count,
            new_cursor=max_processed_at or now,
            skipped=False,
            per_channel_counts={cid: len(per_channel_docs.get(cid, [])) for cid in sub.channel_ids},
        )

    async def deliver(self, bot: "Bot", result: DigestResult) -> None:
        """Send ``result`` to ``chat_id`` over Telegram.

        Raises whatever ``bot.send_message`` / ``bot.send_document`` raises so the
        caller can decide whether to advance the cursor.
        """
        from aiogram.enums import ParseMode

        message = self._compose_message(result)
        parts = self._split_for_telegram(message)

        if len(parts) > self._max_message_parts:
            await self._deliver_as_document(bot, result, message)
            return

        for part in parts:
            await bot.send_message(
                chat_id=result.chat_id,
                text=part,
                parse_mode=ParseMode.MARKDOWN_V2,
            )

    async def run_for_subscription(
        self,
        sub: DigestSubscription,
        bot: "Bot | None",
    ) -> DigestResult:
        """Generate + (optionally) deliver + advance the cursor.

        - Empty result → no delivery, but cursor + last_sent_at advance (so we
          don't keep replaying the lookback window).
        - Bot unavailable + non-empty result → log warning, mark
          ``delivery_failed`` and DO NOT advance cursor.
        - Delivery raises → mark ``delivery_failed`` and DO NOT advance cursor.
        """
        result = await self.generate(sub)

        if result.skipped:
            await self._advance_cursor(sub.id, result.new_cursor)
            logger.info(
                "digest.skipped_empty",
                subscription_id=sub.id,
                chat_id=sub.chat_id,
                first_run=sub.last_digest_cursor is None,
            )
            return result

        if bot is None:
            logger.warning(
                "digest.delivery_skipped_no_bot",
                subscription_id=sub.id,
                docs_count=result.docs_count,
            )
            result.delivery_failed = True
            result.delivery_error = "bot_unavailable"
            return result

        try:
            await self.deliver(bot, result)
        except Exception as exc:  # noqa: BLE001 — surface as delivery failure
            logger.warning(
                "digest.delivery_failed",
                subscription_id=sub.id,
                chat_id=sub.chat_id,
                error=str(exc),
            )
            result.delivery_failed = True
            result.delivery_error = str(exc)
            return result

        await self._advance_cursor(sub.id, result.new_cursor)
        logger.info(
            "digest.delivered",
            subscription_id=sub.id,
            chat_id=sub.chat_id,
            docs_count=result.docs_count,
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _advance_cursor(self, sub_id: str, new_cursor: datetime | None) -> None:
        kwargs: dict[str, Any] = {"last_sent_at": datetime.now(UTC)}
        if new_cursor is not None:
            kwargs["last_digest_cursor"] = new_cursor
        await self._subscription_repo.update(sub_id, **kwargs)

    def _build_title(self, sub: DigestSubscription, now: datetime) -> str:
        date_str = now.strftime("%Y-%m-%d")
        return f"{sub.name} — {date_str}"

    def _render_channels_block(
        self,
        sub: DigestSubscription,
        per_channel: dict[str, list[ProcessedDocument]],
        per_channel_total: dict[str, int],
    ) -> str:
        chunks: list[str] = []
        channel_titles = self._channel_titles(sub.channel_ids)
        for channel_id in sub.channel_ids:
            docs = per_channel.get(channel_id, [])
            if not docs:
                continue
            total = per_channel_total.get(channel_id, len(docs))
            title = channel_titles.get(channel_id, channel_id)
            header = f"## {title} ({len(docs)} of {total} new)"
            lines = [header]
            for d in docs:
                stamp = (
                    d.processed_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
                    if d.processed_at
                    else "?"
                )
                snippet = (d.summary or d.text_clean or "").strip()
                snippet = snippet.replace("\n", " ")
                if len(snippet) > 400:
                    snippet = snippet[:397] + "..."
                lines.append(f"- [{stamp}] {snippet}")
            chunks.append("\n".join(lines))
        return "\n\n".join(chunks)

    def _channel_titles(self, channel_ids: list[str]) -> dict[str, str]:
        """Lightweight resolver — returns ``channel_id`` as title if no metadata.

        Hook for future enrichment (e.g. ``Source.channel_username``).
        """
        return {cid: cid for cid in channel_ids}

    async def _call_llm(
        self,
        *,
        sub: DigestSubscription,
        channels_block: str,
        from_iso: str,
        to_iso: str,
    ) -> str:
        config = self._prompt_loader.load(self._prompt_name)
        system_template = (config.get("system") or {}).get("prompt") or ""
        user_template = (config.get("user") or {}).get("template") or ""
        model_cfg = config.get("model") or {}

        format_value = sub.format.value if isinstance(sub.format, DigestFormat) else str(sub.format)
        render_args: dict[str, Any] = {
            "format": format_value,
            "language": sub.language,
            "from_iso": from_iso,
            "to_iso": to_iso,
            "channels_block": channels_block,
        }

        try:
            system_prompt = system_template.format(**render_args)
        except KeyError:
            system_prompt = system_template
        try:
            user_prompt = user_template.format(**render_args)
        except KeyError as exc:
            raise ValueError(
                f"digest prompt template missing required placeholder: {exc.args[0]!r}"
            ) from exc

        llm = self._llm_client_factory()
        body = await llm.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=float(model_cfg.get("temperature", 0.3)),
            max_tokens=int(model_cfg.get("max_tokens", 1500)),
        )
        return (body or "").strip()

    def _compose_message(self, result: DigestResult) -> str:
        title_md = f"*{escape_markdown_v2(result.title)}*"
        body_md = escape_markdown_v2(result.body_markdown)
        if not body_md:
            return title_md
        return f"{title_md}\n\n{body_md}"

    def _split_for_telegram(self, text: str) -> list[str]:
        if len(text) <= self._message_max_chars:
            return [text]

        parts: list[str] = []
        remaining = text
        limit = self._message_max_chars
        while remaining:
            if len(remaining) <= limit:
                parts.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = limit
            parts.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        return parts

    async def _deliver_as_document(
        self,
        bot: "Bot",
        result: DigestResult,
        full_message: str,
    ) -> None:
        from aiogram.types import BufferedInputFile

        date_str = datetime.now(UTC).strftime("%Y%m%d_%H%M")
        filename = f"digest_{date_str}.md"
        raw_body = f"# {result.title}\n\n{result.body_markdown}"
        file = BufferedInputFile(raw_body.encode("utf-8"), filename=filename)
        caption = escape_markdown_v2(
            f"{result.title} ({result.docs_count} new)"
        )
        from aiogram.enums import ParseMode

        await bot.send_document(
            chat_id=result.chat_id,
            document=file,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _to_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return _to_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "DigestResult",
    "DigestService",
    "escape_markdown_v2",
]
