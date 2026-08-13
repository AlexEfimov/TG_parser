#!/usr/bin/env python3
"""Разбор бэклога недоставленных watchlist-матчей (BUG-095, шаг §3.3).

Инстант-доставка F11 не работала с 2026-06-15: матчер пишет матчи в процессе
`tg_parser`, где `get_bot()` всегда `None`, поэтому доставка молча пропускалась.
Матчи копились с `notified=false`. Фикс (форма B) восстанавливает доставку
**вперёд** — историю он намеренно не трогает: инстант-flush отсекает её
watermark'ом, иначе первый же тик выслал бы двухмесячный бэклог одной пачкой.

Скрипт закрывает эту историю по решению владельца от 2026-08-13 — **гибрид**:
матчи помечаются обработанными, и в каждый чат уходит **одна** сводка
«интерес → сколько пропущено, за какой период» плюс подсказка про
`get_watchlist_matches`. Не список постов: пересылать алерты двухмесячной
давности значит имитировать поломку, а не восстанавливать ценность —
содержание никуда не делось и читается из БД.

**Запускать в контейнере бота** (`tg_parser_bot`): нужен `TELEGRAM_BOT_TOKEN`,
которого нет в периметре `tg_parser`.

Идемпотентность — из того же watermark'а, которым живёт доставка: рабочее
множество это строки `notified=false`, успешная отправка их переключает,
поэтому повторный прогон не отправляет ничего. Значит скрипт безопасно
запускать повторно; позже он сообщит только о том, что действительно осталось
недоставленным.

Использование:

    # что будет отправлено (ничего не меняет)
    python scripts/watchlist_backlog_summary.py

    # отправить сводки и пометить матчи обработанными
    python scripts/watchlist_backlog_summary.py --apply

    # явная граница вместо watermark'а из настроек / «сейчас»
    python scripts/watchlist_backlog_summary.py --apply --before 2026-08-13T12:00:00Z

`--before` обязан совпадать с watermark'ом инстант-flush'а
(`WATCHLIST_INSTANT_FLUSH_CUTOFF`, если он закреплён): граница делит
недоставленные матчи на две непересекающиеся половины — старше неё разбирает
этот скрипт, новее доставляет flush. По умолчанию берётся закреплённый
watermark, а без него — момент запуска.

Контекст: docs/notes/BUG_LOG.md § BUG-095, docs/adr/0014-watchlist-batch-silent-delivery.md.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime


def _parse_before(raw: str | None) -> datetime:
    """Разобрать `--before`, иначе взять закреплённый watermark, иначе «сейчас»."""
    from tg_parser.services.watchlist_service import get_instant_flush_watermark

    if raw:
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SystemExit(f"--before: не ISO-8601 ({raw!r}): {exc}") from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    return get_instant_flush_watermark() or datetime.now(UTC)


async def _run(*, before: datetime, apply: bool) -> int:
    from aiogram import Bot

    from tg_parser.config import settings
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    if apply and not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не задан — запускайте скрипт в контейнере бота "
            "(в tg_parser токена нет по устройству периметра)"
        )

    bot = Bot(token=settings.telegram_bot_token) if apply else None
    try:
        async with watchlist_repos() as (
            interest_repo,
            match_repo,
            processed_doc_repo,
            embedding_repo,
            _db,
        ):
            service = make_watchlist_service(
                interest_repo=interest_repo,
                match_repo=match_repo,
                processed_doc_repo=processed_doc_repo,
                embedding_repo=embedding_repo,
            )
            try:
                summaries = await service.summarize_backlog(
                    bot,
                    before=before,
                    dry_run=not apply,
                )
            finally:
                await service.aclose()
    finally:
        if bot is not None:
            await bot.session.close()

    _report(summaries, before=before, apply=apply)
    failed = [s for s in summaries if apply and not s.sent]
    return 1 if failed else 0


def _report(summaries: list, *, before: datetime, apply: bool) -> None:
    mode = "ОТПРАВКА" if apply else "DRY-RUN (ничего не изменено)"
    print(f"\nBUG-095 — разбор бэклога · {mode}")
    print(f"граница (before): {before.isoformat()}\n")

    if not summaries:
        print("Недоставленных матчей старше границы нет — отправлять нечего.")
        return

    total = 0
    for summary in summaries:
        status = "отправлено" if summary.sent else ("—" if not apply else "ОШИБКА ОТПРАВКИ")
        print(f"chat_id={summary.chat_id}: {summary.match_count} матчей [{status}]")
        for entry in summary.entries:
            period = f"{entry.oldest:%Y-%m-%d} … {entry.newest:%Y-%m-%d}"
            print(f"    • {entry.title}: {entry.missed} пропущено, {period}")
        total += summary.match_count

    print(f"\nитого: {total} матчей в {len(summaries)} чат(ах)")
    if not apply:
        print("Это был dry-run. Повторите с --apply, чтобы отправить и закрыть историю.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BUG-095: одна сводка на чат по недоставленным watchlist-матчам",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="отправить сводки и пометить матчи обработанными (по умолчанию dry-run)",
    )
    parser.add_argument(
        "--before",
        default=None,
        help=(
            "ISO-8601 граница: разбираются матчи старше неё. По умолчанию — "
            "закреплённый watermark инстант-flush'а, иначе момент запуска"
        ),
    )
    args = parser.parse_args()

    before = _parse_before(args.before)
    return asyncio.run(_run(before=before, apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
