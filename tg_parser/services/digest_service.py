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
import uuid as _uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.exc import IntegrityError

from tg_parser.api.metrics import record_digest_channel_publish
from tg_parser.auth.ownership import WorkspaceNotFound
from tg_parser.domain.models import (
    DigestFormat,
    DigestSubscription,
    ProcessedDocument,
    TargetChannel,
    TargetChat,
    resolve_subscription_target,
    storage_fields_from_target,
    subscription_target_from_digest,
    telegram_address_from_target,
)
from tg_parser.processing.prompt_loader import PromptLoader, PromptLoaderError
from tg_parser.storage.ports import (
    DigestSubscriptionRepo,
    ProcessedDocumentRepo,
    WorkspaceRepo,
)

if TYPE_CHECKING:
    from aiogram import Bot

    from tg_parser.processing.ports import LLMClient


logger = structlog.get_logger(__name__)


class ChannelPublishPermissionDenied(Exception):
    """Permanent channel publish failure (bot not admin, channel missing, etc.)."""


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


_CHANNEL_PUBLISH_PERMANENT_FRAGMENTS: tuple[str, ...] = (
    "chat not found",
    "bot was blocked",
    "user is deactivated",
    "forbidden",
    "not enough rights",
    "need administrator",
    "have no rights",
    "bot is not a member",
    "channel_private",
    "administrator",
)


@dataclass
class DigestResult:
    """Outcome of one digest generation run for a subscription."""

    subscription_id: str
    chat_id: int | None
    title: str
    body_markdown: str
    docs_count: int
    new_cursor: datetime | None
    skipped: bool
    delivery_failed: bool = False
    delivery_error: str | None = None
    per_channel_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SubscribeResult:
    """Outcome of a :meth:`DigestService.subscribe` call (Wave 1 step 3).

    Mirrors :class:`tg_parser.services.watchlist_service.SubscribeResult`
    but carries a :class:`DigestSubscription`. ``changed_fields`` is the
    list of Pydantic field names whose values differ between the stored
    row and the new payload (empty on true no-op replay).
    """

    subscription: DigestSubscription
    created: bool
    changed_fields: list[str]


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------


LLMClientFactory = Callable[[], "LLMClient"]


class DigestService:
    """Compose digest text and deliver it to Telegram for a subscription."""

    def __init__(
        self,
        processed_repo: ProcessedDocumentRepo | None,
        subscription_repo: DigestSubscriptionRepo,
        prompt_loader: PromptLoader | None,
        llm_client_factory: LLMClientFactory | None,
        *,
        max_docs_per_run: int = 50,
        first_run_lookback_hours: int = 24,
        message_max_chars: int = 4096,
        max_message_parts: int = 10,
        prompt_name: str = "digest",
        workspace_repo: WorkspaceRepo | None = None,
    ):
        self._processed_repo = processed_repo
        self._subscription_repo = subscription_repo
        self._prompt_loader = prompt_loader
        self._llm_client_factory = llm_client_factory
        self._max_docs_per_run = max(1, int(max_docs_per_run))
        self._first_run_lookback_hours = max(1, int(first_run_lookback_hours))
        self._message_max_chars = max(512, int(message_max_chars))
        self._max_message_parts = max(1, int(max_message_parts))
        self._prompt_name = prompt_name
        self._workspace_repo = workspace_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        *,
        owner_id: str,
        name: str,
        channel_ids: list[str],
        chat_id: int | None = None,
        target: TargetChat | TargetChannel | None = None,
        cron_expression: str = "0 9 * * *",
        timezone: str = "UTC",
        format: DigestFormat = DigestFormat.SUMMARY,
        language: str = "ru",
        workspace_id: str | None = None,
        is_admin: bool = False,
    ) -> SubscribeResult:
        """Idempotent upsert on the ``(owner_id, name)`` natural key (BUG-022).

        Wave 1 step 3 commit 1/4 — closes BUG-022. Mirrors
        :meth:`tg_parser.services.watchlist_service.WatchlistService.subscribe`
        but on the digest natural key (table column ``owner_id`` + label
        column ``name`` — see Q6 asymmetry in sprint prompt). Scheduler
        registration is intentionally NOT performed here: surfaces
        (MCP, Bot) call ``register_digest_subscription`` separately so
        the cron/timezone validation stays at the call-site.

        ``workspace_id`` semantics (ENH-9):

        - ``None`` (default) → identical to pre-ENH-9 behaviour
          (column stays NULL on INSERT; left untouched on UPDATE).
        - Valid UUID → validated via the injected ``workspace_repo``;
          unknown or foreign UUIDs raise :class:`WorkspaceNotFound`.
        - ``is_admin=True`` bypasses the cross-tenant ownership check.
        - When ``workspace_repo`` is not configured (e.g. unit tests
          that don't need workspace validation) the value is stored
          as-is without validation.

        Race condition: a concurrent INSERT from two surfaces is
        caught via :class:`IntegrityError` from the new
        ``UNIQUE (owner_id, name)`` constraint and the path retries
        as UPDATE so the result still collapses to a single row.
        """
        resolved_target = resolve_subscription_target(chat_id=chat_id, target=target)
        target_storage = storage_fields_from_target(resolved_target)

        if workspace_id is not None and self._workspace_repo is not None:
            workspace = await self._workspace_repo.get(workspace_id)
            if workspace is None:
                raise WorkspaceNotFound(f"Workspace {workspace_id} not found")
            if not is_admin and workspace.owner_id != owner_id:
                raise WorkspaceNotFound(f"Workspace {workspace_id} not found")

        existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name)
        if existing is not None:
            return await self._apply_digest_upsert(
                existing=existing,
                target_storage=target_storage,
                channel_ids=channel_ids,
                cron_expression=cron_expression,
                timezone=timezone,
                format=format,
                language=language,
                workspace_id=workspace_id,
            )

        draft = DigestSubscription(
            id=str(_uuid.uuid4()),
            owner_id=owner_id,
            target_kind=target_storage["target_kind"],
            chat_id=target_storage["chat_id"],
            channel_id=target_storage["channel_id"],
            name=name,
            channel_ids=list(channel_ids),
            workspace_id=workspace_id,
            cron_expression=cron_expression,
            timezone=timezone,
            format=format,
            language=language,
            is_active=True,
            last_sent_at=None,
            last_digest_cursor=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        try:
            created = await self._subscription_repo.create(draft)
        except IntegrityError:
            logger.info(
                "digest.subscribe_race_retry_update",
                owner_id=owner_id,
                name=name,
            )
            existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name)
            if existing is None:
                raise
            return await self._apply_digest_upsert(
                existing=existing,
                target_storage=target_storage,
                channel_ids=channel_ids,
                cron_expression=cron_expression,
                timezone=timezone,
                format=format,
                language=language,
                workspace_id=workspace_id,
            )
        return SubscribeResult(subscription=created, created=True, changed_fields=[])

    async def _apply_digest_upsert(
        self,
        *,
        existing: DigestSubscription,
        target_storage: dict[str, Any],
        channel_ids: list[str],
        cron_expression: str,
        timezone: str,
        format: DigestFormat,
        language: str,
        workspace_id: str | None,
    ) -> SubscribeResult:
        """Diff existing row vs payload, UPDATE changed columns only."""
        new_channels = list(channel_ids)

        update_kwargs: dict[str, Any] = {}
        changed_fields: list[str] = []

        if existing.target_kind != target_storage["target_kind"]:
            update_kwargs["target_kind"] = target_storage["target_kind"]
            changed_fields.append("target_kind")
        if existing.chat_id != target_storage["chat_id"]:
            update_kwargs["chat_id"] = target_storage["chat_id"]
            changed_fields.append("chat_id")
        if existing.channel_id != target_storage["channel_id"]:
            if target_storage["channel_id"] is None:
                update_kwargs["unset_channel_id"] = True
            else:
                update_kwargs["channel_id"] = target_storage["channel_id"]
            changed_fields.append("channel_id")
        if list(existing.channel_ids) != new_channels:
            update_kwargs["channel_ids"] = new_channels
            changed_fields.append("channel_ids")
        if existing.cron_expression != cron_expression:
            update_kwargs["cron_expression"] = cron_expression
            changed_fields.append("cron_expression")
        if existing.timezone != timezone:
            update_kwargs["timezone"] = timezone
            changed_fields.append("timezone")
        if existing.format != format:
            update_kwargs["format"] = format
            changed_fields.append("format")
        if existing.language != language:
            update_kwargs["language"] = language
            changed_fields.append("language")
        if not existing.is_active:
            update_kwargs["is_active"] = True
            changed_fields.append("is_active")
        if workspace_id is not None and existing.workspace_id != workspace_id:
            update_kwargs["workspace_id"] = workspace_id
            changed_fields.append("workspace_id")

        if not update_kwargs:
            return SubscribeResult(subscription=existing, created=False, changed_fields=[])

        updated = await self._subscription_repo.update(existing.id, **update_kwargs)
        if updated is None:
            updated = existing
        return SubscribeResult(subscription=updated, created=False, changed_fields=changed_fields)

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
            # Oldest-first: when len(filtered) > max_docs_per_run we keep the
            # oldest slice. The cursor then advances to the *last kept* doc, so
            # the leftover newer docs are picked up on the next tick instead of
            # being silently skipped (which would happen if we kept the newest
            # slice and advanced cursor to the newest of the kept).
            filtered.sort(key=lambda d: _to_utc(d.processed_at))
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
                per_channel_counts=dict.fromkeys(sub.channel_ids, 0),
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

    async def deliver(
        self,
        bot: Bot,
        result: DigestResult,
        sub: DigestSubscription,
    ) -> None:
        """Send ``result`` to the subscription's delivery target over Telegram.

        Raises whatever ``bot.send_message`` / ``bot.send_document`` raises so the
        caller can decide whether to advance the cursor (chat targets only;
        channel permission-denied is handled inside :meth:`_publish_to_target`).
        """
        target = subscription_target_from_digest(sub)
        message = self._compose_message(result)
        parts = self._split_for_telegram(message)

        if len(parts) > self._max_message_parts:
            await self._publish_to_target(
                bot,
                target,
                parts=None,
                sub=sub,
                document_payload=(result, message),
            )
            return

        await self._publish_to_target(bot, target, parts=parts, sub=sub)

    async def _publish_to_target(
        self,
        bot: Bot,
        target: TargetChat | TargetChannel,
        *,
        parts: list[str] | None,
        sub: DigestSubscription,
        document_payload: tuple[DigestResult, str] | None = None,
    ) -> None:
        """Dispatch digest body to ``target`` (chat or channel).

        Channel targets use best-effort delivery per ADR 0008 OQ#3: permanent
        permission errors soft-deactivate the subscription, notify the owner
        ``chat_id`` when available, and increment ``tg_digest_channel_publish_total``.
        """
        from aiogram.enums import ParseMode

        address = telegram_address_from_target(target)
        is_channel = isinstance(target, TargetChannel)

        async def _send_parts() -> None:
            if document_payload is not None:
                res, full_message = document_payload
                await self._deliver_as_document(bot, res, full_message, chat_id=address)
                return
            assert parts is not None
            for part in parts:
                await bot.send_message(
                    chat_id=address,
                    text=part,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )

        try:
            await _send_parts()
        except Exception as exc:
            if not is_channel:
                raise
            error_text = str(exc).lower()
            permanent = any(
                fragment in error_text for fragment in _CHANNEL_PUBLISH_PERMANENT_FRAGMENTS
            )
            logger.warning(
                "channel_publish_permission_denied"
                if permanent
                else "digest.channel_publish_failed",
                subscription_id=sub.id,
                channel_id=target.channel_id,
                permanent=permanent,
                error=str(exc),
            )
            record_digest_channel_publish(result="permission_denied" if permanent else "failed")
            if permanent:
                await self._subscription_repo.update(sub.id, is_active=False)
                if sub.chat_id is not None:
                    try:
                        notice = escape_markdown_v2(
                            f"Digest «{sub.name}» deactivated: bot cannot publish to "
                            f"channel {target.channel_id}. Add the bot as channel admin "
                            f"and re-subscribe."
                        )
                        await bot.send_message(
                            chat_id=sub.chat_id,
                            text=notice,
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                    except Exception:
                        logger.debug(
                            "digest.channel_publish_fallback_notify_failed",
                            subscription_id=sub.id,
                            exc_info=True,
                        )
                raise ChannelPublishPermissionDenied(str(exc)) from exc
            raise

        if is_channel:
            record_digest_channel_publish(result="success")

    async def run_for_subscription(
        self,
        sub: DigestSubscription,
        bot: Bot | None,
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
            await self.deliver(bot, result, sub)
        except ChannelPublishPermissionDenied as exc:
            logger.warning(
                "digest.delivery_failed",
                subscription_id=sub.id,
                chat_id=sub.chat_id,
                error=str(exc),
                channel_publish=True,
            )
            result.delivery_failed = True
            result.delivery_error = str(exc)
            return result
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

        if not user_template.strip():
            raise PromptLoaderError(
                f"digest stage has no user.template (prompt_name={self._prompt_name!r}); "
                "check prompts/digest.yaml or built-in default"
            )

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
        bot: Bot,
        result: DigestResult,
        full_message: str,
        *,
        chat_id: int | str | None = None,
    ) -> None:
        from aiogram.types import BufferedInputFile

        date_str = datetime.now(UTC).strftime("%Y%m%d_%H%M")
        filename = f"digest_{date_str}.md"
        raw_body = f"# {result.title}\n\n{result.body_markdown}"
        file = BufferedInputFile(raw_body.encode("utf-8"), filename=filename)
        caption = escape_markdown_v2(f"{result.title} ({result.docs_count} new)")
        from aiogram.enums import ParseMode

        dest = chat_id if chat_id is not None else result.chat_id
        await bot.send_document(
            chat_id=dest,
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
