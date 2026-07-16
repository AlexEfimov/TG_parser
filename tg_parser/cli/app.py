"""
CLI интерфейс TG_parser (Typer).

Реализует TR-44/TR-55..TR-64: команды ingestion/processing/topicization/export.
"""

import typer

from tg_parser.cli.agents_cmd import app as agents_app
from tg_parser.cli.db_cmd import app as db_app
from tg_parser.cli.digest_cmd import app as digest_app
from tg_parser.cli.scheduler_cmd import app as scheduler_app
from tg_parser.cli.topic_cmd import app as topic_app
from tg_parser.cli.watchlist_cmd import app as watchlist_app
from tg_parser.cli.workspace_cmd import app as workspace_app

app = typer.Typer(
    name="tg_parser",
    help="TG_parser CLI - сбор и обработка контента из Telegram",
)

# Add subcommand groups
app.add_typer(agents_app, name="agents")
app.add_typer(db_app, name="db")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(topic_app, name="topic")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(digest_app, name="digest")
app.add_typer(workspace_app, name="workspace")


@app.command()
def auth(
    force: bool = typer.Option(
        False, "--force", help="Удалить существующий session-файл и авторизоваться заново"
    ),
):
    """Авторизоваться в Telegram (интерактивный ввод кода).

    Создаёт session-файл для последующих запусков ingestion.
    Используйте при первом запуске или при expired session.

    В Docker:\n
        docker compose run --rm tg_parser auth
    """
    import asyncio

    from tg_parser.config import settings
    from tg_parser.ingestion.telegram.session_crypto import (
        session_sealed_path,
        session_working_path,
        wipe_working_session,
    )

    session_path = session_working_path(settings.telegram_session_name)
    sealed_path = session_sealed_path(settings.telegram_session_name)

    if force:
        had_working = session_path.exists()
        wipe_working_session(session_path)
        if sealed_path.exists():
            sealed_path.unlink()
            typer.echo(f"🗑️  Удалён sealed session: {sealed_path}")
        if had_working:
            typer.echo(f"🗑️  Удалён старый session-файл: {session_path}")

    session_dir = session_path.parent
    session_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("🔐 Запуск Telegram-авторизации...")
    typer.echo(f"   • Session: {session_path}")
    if settings.telegram_session_key:
        typer.echo(f"   • Sealed form (after auth): {sealed_path}")
    typer.echo(f"   • Phone: {settings.telegram_phone}")
    typer.echo()

    async def _auth() -> None:
        from tg_parser.ingestion.telegram.telethon_client import TelethonClient

        client = TelethonClient(settings)
        try:
            await client.connect()
        finally:
            await client.disconnect()

    try:
        asyncio.run(_auth())
        typer.echo("\n✅ Авторизация успешна! Session сохранена.")
        if settings.telegram_session_key and sealed_path.exists():
            typer.echo(f"   Sealed: {sealed_path}")
        else:
            typer.echo(f"   Файл: {session_path}")
    except EOFError as err:
        typer.echo(
            "\n❌ Невозможно прочитать код подтверждения (stdin закрыт).\n"
            "   Используйте: docker compose run --rm tg_parser auth",
            err=True,
        )
        raise typer.Exit(code=1) from err
    except Exception as e:
        typer.echo(f"\n❌ Ошибка авторизации: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def init(
    force: bool = typer.Option(False, help="Пересоздать базы даже если существуют"),
):
    """
    Инициализировать базы данных (создать таблицы через Alembic или DDL).
    """
    from tg_parser.cli.init_db import init_databases_sync
    from tg_parser.config import settings

    typer.echo("🔧 Инициализация баз данных...\n")
    typer.echo(f"   PostgreSQL: {settings.db_host}:{settings.db_port}/{settings.db_name}")

    try:
        init_databases_sync()
        typer.echo("\n✅ Базы данных успешно инициализированы")
    except Exception as e:
        typer.echo(f"\n❌ Ошибка при создании баз: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def add_source(
    source_id: str = typer.Option(..., help="Уникальный ID источника"),
    channel_id: str = typer.Option(..., help="ID канала в Telegram"),
    channel_username: str = typer.Option(None, help="Username канала (опц.)"),
    include_comments: bool = typer.Option(False, help="Собирать комментарии"),
    batch_size: int = typer.Option(100, help="Размер батча"),
    owner_id: str = typer.Option(
        None,
        help="UUID владельца (DI-13). Если не указан — auto-resolves к admin.",
    ),
):
    """
    Добавить источник (канал) для ingestion (TR-15).
    """
    import asyncio

    from tg_parser.cli.add_source_cmd import run_add_source

    typer.echo(f"➕ Добавление источника: {source_id}\n")
    typer.echo(f"   • Channel ID: {channel_id}")
    if channel_username:
        typer.echo(f"   • Username: {channel_username}")
    typer.echo(f"   • Comments: {'да' if include_comments else 'нет'}")
    if owner_id:
        typer.echo(f"   • Owner: {owner_id}")
    else:
        typer.echo("   • Owner: auto (admin)")

    try:
        asyncio.run(
            run_add_source(
                source_id=source_id,
                channel_id=channel_id,
                channel_username=channel_username,
                include_comments=include_comments,
                batch_size=batch_size,
                owner_id=owner_id,
            )
        )
        typer.echo("\n✅ Источник добавлен")

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def ingest(
    source: str = typer.Option(..., help="ID источника"),
    mode: str = typer.Option("incremental", help="Режим: snapshot или incremental"),
    limit: int = typer.Option(None, help="Лимит сообщений (для отладки)"),
):
    """
    Запустить ingestion для источника (TR-4..TR-17).

    Собирает raw сообщения в PostgreSQL (таблица raw_messages).
    """
    import asyncio

    from tg_parser.cli.ingest_cmd import run_ingestion

    typer.echo(f"📥 Ingestion источника: {source}\n")
    typer.echo(f"   • Режим: {mode}")
    if limit:
        typer.echo(f"   • Лимит: {limit}")

    try:
        # Запускаем async функцию
        stats = asyncio.run(run_ingestion(source_id=source, mode=mode, limit=limit))

        # Выводим статистику
        typer.echo("\n✅ Ingestion завершён:")
        typer.echo(f"   • Постов собрано: {stats['posts_collected']}")
        typer.echo(f"   • Комментариев собрано: {stats['comments_collected']}")
        typer.echo(f"   • Ошибок: {stats['errors']}")
        typer.echo(f"   • Время: {stats['duration_seconds']:.2f}s")

        if stats["errors"] > 0:
            typer.echo("\n⚠️  Ошибки зафиксированы в ingestion_state")
            raise typer.Exit(code=1)

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def process(
    channel: str = typer.Option(..., help="Идентификатор канала"),
    force: bool = typer.Option(False, help="Переобработать существующие"),
    retry_failed: bool = typer.Option(
        False, "--retry-failed", help="Повторить обработку failed сообщений"
    ),
    provider: str = typer.Option(
        None, "--provider", help="LLM provider (openai|anthropic|gemini|ollama)"
    ),
    model: str = typer.Option(None, "--model", help="Model override"),
    concurrency: int = typer.Option(
        None,
        "--concurrency",
        "-c",
        help="Parallel LLM requests (default: from PROCESSING_CONCURRENCY env)",
    ),
    limit: int = typer.Option(
        None, "--limit", "-l", help="Process only first N raw messages (for benchmarking)"
    ),
    agent: bool = typer.Option(False, "--agent", help="Use agent-based processing (v2.0)"),
    agent_llm: bool = typer.Option(False, "--agent-llm", help="Use LLM-enhanced agent tools"),
    hybrid: bool = typer.Option(
        False, "--hybrid", help="Enable v1.2 pipeline as agent tool (Phase 2E)"
    ),
    multi_agent: bool = typer.Option(
        False, "--multi-agent", help="Use multi-agent orchestration (Phase 3A)"
    ),
    dry_run: bool = typer.Option(False, help="Режим dry-run"),
):
    """
    Запустить processing для канала (TR-44).

    Обрабатывает raw → ProcessedDocument.

    С флагом --retry-failed обрабатывает только сообщения с прошлыми ошибками.

    v1.2: Multi-LLM поддержка через --provider и --model флаги.
    v1.2: Параллельная обработка через --concurrency флаг (рекомендуется 3-5).
    v2.0: Agent-based processing через --agent флаг.
    v2.0: LLM-enhanced agent tools через --agent-llm флаг.
    Phase 2E: Hybrid mode через --hybrid флаг (agent + pipeline tool).
    Phase 3A: Multi-agent orchestration через --multi-agent флаг.
    """
    import asyncio

    from tg_parser.cli.process_cmd import run_processing

    typer.echo(f"⚙️  Processing канала: {channel}\n")

    if multi_agent:
        typer.echo("🤖 Режим: Multi-Agent Orchestration (Phase 3A)")
        typer.echo("   • OrchestratorAgent → ProcessingAgent → TopicizationAgent")
    elif agent:
        typer.echo("🤖 Режим: Agent-based processing (v2.0)")
        if agent_llm:
            typer.echo("🧠 LLM-enhanced tools: enabled")
        if hybrid:
            typer.echo("🔄 Hybrid mode: v1.2 pipeline available as tool")
    else:
        typer.echo("📋 Режим: Pipeline processing (v1.2)")

    if provider:
        typer.echo(f"🔌 LLM Provider: {provider}")
    if model:
        typer.echo(f"🧠 Model: {model}")

    if not provider and not model and not multi_agent and not agent:
        from tg_parser.processing.llm.factory import resolve_llm_config

        eff_provider, _, eff_model = resolve_llm_config("processing")
        typer.echo(f"🔌 Processing with {eff_provider}/{eff_model or 'default'}")

    from tg_parser.config import settings as app_settings

    effective_concurrency = (
        concurrency if concurrency is not None else app_settings.processing_concurrency
    )
    typer.echo(
        f"⚡ Concurrency: {effective_concurrency} parallel requests"
        f"{' (from settings)' if concurrency is None else ''}"
    )

    if retry_failed:
        typer.echo("🔄 Режим retry-failed (повтор ошибок)")
    if force:
        typer.echo("⚠️  Режим force (переобработка)")
    if limit:
        typer.echo(f"🔢 Limit: первые {limit} сообщений")

    if dry_run:
        typer.echo("⚠️  Режим dry-run (пока не реализовано)")
        return

    try:
        # Phase 3A: Multi-agent mode
        if multi_agent:
            from tg_parser.cli.process_cmd import run_multi_agent_processing

            stats = asyncio.run(
                run_multi_agent_processing(
                    channel,
                    force=force,
                    provider=provider,
                    model=model,
                )
            )
        else:
            # Запускаем async функцию
            stats = asyncio.run(
                run_processing(
                    channel,
                    force=force,
                    retry_failed=retry_failed,
                    provider=provider,
                    model=model,
                    concurrency=concurrency,
                    limit=limit,
                    use_agent=agent,
                    use_llm_tools=agent_llm,
                    use_pipeline_tool=hybrid,
                )
            )

        # BUG-073 (F1): a lock-contended run is a benign no-op, NOT a successful
        # processing run — report it distinctly so the operator does not read the
        # "✅ завершён, 0 обработано" banner as "the backlog was handled".
        if stats.get("skipped_locked"):
            typer.echo(
                "\n⏭️  Processing пропущен — другой процесс уже обрабатывает этот "
                "канал (per-channel lock занят); backlog будет обработан следующим "
                "запуском."
            )
            return

        # Выводим статистику
        if retry_failed:
            typer.echo("\n✅ Retry processing завершён:")
        else:
            typer.echo("\n✅ Processing завершён:")
        typer.echo(f"   • Обработано: {stats['processed_count']}")
        typer.echo(f"   • Пропущено: {stats['skipped_count']}")
        typer.echo(f"   • Ошибок: {stats['failed_count']}")
        typer.echo(f"   • Всего сообщений: {stats['total_count']}")
        if stats.get("total_tokens"):
            typer.echo(
                f"   • Токены: {stats['input_tokens']} in + {stats['output_tokens']} out = {stats['total_tokens']} total"
            )

        if stats["failed_count"] > 0:
            typer.echo("\n⚠️  Ошибки записаны в processing_failures")
            raise typer.Exit(code=1)

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def topicize(
    channel: str = typer.Option(..., help="Идентификатор канала"),
    force: bool = typer.Option(False, help="Переформировать темы даже если уже есть"),
    no_bundles: bool = typer.Option(False, help="Не создавать topic bundles"),
    mode: str = typer.Option(
        "auto",
        help="Режим: auto (incremental если темы есть, иначе full), full, incremental, assign-only",
    ),
    cross_channel: bool | None = typer.Option(
        None,
        "--cross-channel/--no-cross-channel",
        help="Enable/disable cross-channel context and auto-linking (default: from settings)",
    ),
):
    """
    Запустить topicization для канала (TR-44).

    Формирует TopicCard + TopicBundle из ProcessedDocument.

    Режимы:
      --mode auto        Авто (default): incremental если темы уже есть, full если первый запуск.
      --mode full        Полная topicization. С --force пересоздаёт все темы.
      --mode incremental Phase 1 (keyword assign) + Phase 2 (LLM discover) для uncovered docs.
      --mode assign-only Только Phase 1 (0 LLM tokens) для uncovered docs.

    Cross-channel (incremental/auto only):
      --cross-channel    Phase 2 sees topics from ALL channels; Phase 3 auto-creates TopicLinks.
      --no-cross-channel Disable cross-channel features (per-channel only).
      (omit)             Use CROSS_CHANNEL_TOPICIZATION setting (default: True).
    """

    if mode not in ("auto", "full", "incremental", "assign-only"):
        typer.echo(
            f"❌ Неизвестный режим: {mode}. Допустимо: auto, full, incremental, assign-only",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"🏷️  Topicization канала: {channel}\n")

    if cross_channel is not None:
        typer.echo(f"🔗 Cross-channel: {'enabled' if cross_channel else 'disabled'}")

    if force:
        _run_full_topicization(channel, force=True, no_bundles=no_bundles)
    elif mode == "full":
        _run_full_topicization(channel, force=False, no_bundles=no_bundles)
    elif mode == "auto":
        existing_count = _channel_topic_count(channel)
        if existing_count > 0:
            typer.echo(f"📋 Режим: auto → incremental (найдено {existing_count} тем)")
            _run_incremental_topicization_cli(channel, cross_channel=cross_channel)
        else:
            typer.echo("📋 Режим: auto → full (тем не найдено, первый запуск)")
            _run_full_topicization(channel, force=False, no_bundles=no_bundles)
    elif mode == "incremental":
        _run_incremental_topicization_cli(channel, cross_channel=cross_channel)
    elif mode == "assign-only":
        _run_assign_only_topicization_cli(channel)


def _channel_topic_count(channel_id: str) -> int:
    """Return number of existing TopicCards for a channel (0 = first run)."""
    import asyncio

    from tg_parser.services.db_context import processing_repos
    from tg_parser.storage.sqlalchemy.database import Database

    async def _count() -> int:
        try:
            async with processing_repos() as (_, topic_card_repo, _, _):
                cards = await topic_card_repo.list_by_channel(channel_id)
                return len(cards)
        finally:
            await Database.close_instance()

    return asyncio.run(_count())


def _run_full_topicization(channel: str, force: bool, no_bundles: bool) -> None:
    """Run full topicization (current behavior)."""
    import asyncio

    from tg_parser.cli.topicize_cmd import run_topicization
    from tg_parser.processing.llm.factory import resolve_llm_config

    eff_provider, _, eff_model = resolve_llm_config("topicization")
    typer.echo(f"🔌 Topicization with {eff_provider}/{eff_model or 'default'}")

    if force:
        typer.echo("⚠️  Режим force (переформирование тем)")

    if no_bundles:
        typer.echo("⚠️  Bundles не будут созданы")

    try:
        stats = asyncio.run(
            run_topicization(
                channel_id=channel,
                force=force,
                build_bundles=not no_bundles,
            )
        )

        # BUG-018: detect systemic LLM-batch failures BEFORE printing ✅.
        # When more than half of the topicization batches errored (typically
        # billing / auth / quota class errors), the run is a systemic fail
        # and the CLI must exit non-zero so automation scripts wrapping the
        # CLI exit code can detect it instead of silently proceeding.
        failed_batches = stats.get("failed_batches", 0) or 0
        total_batches = stats.get("total_batches", 0) or 0
        last_batch_error = stats.get("last_batch_error")
        systemic_fail = total_batches > 0 and failed_batches / total_batches > 0.5

        if systemic_fail:
            typer.echo(
                f"\n❌ Topicization aborted: {failed_batches}/{total_batches} batches errored",
                err=True,
            )
            if last_batch_error:
                typer.echo(f"   • First error: {last_batch_error}", err=True)
            typer.echo(
                "   • Hint: check LLM provider credentials / quota / billing",
                err=True,
            )
            raise typer.Exit(code=2)

        typer.echo("\n✅ Topicization завершён:")
        typer.echo(f"   • Создано тем: {stats['topics_count']}")
        typer.echo(f"   • Создано подборок: {stats['bundles_count']}")
        if stats.get("total_tokens"):
            typer.echo(
                f"   • Токены: {stats['input_tokens']} in + {stats['output_tokens']} out = {stats['total_tokens']} total"
            )

        if "coverage_pct" in stats:
            typer.echo(
                f"   • Coverage: {stats['coverage_pct']}% "
                f"({stats['covered_documents']}/{stats['total_documents']} documents)"
            )

        # BUG-018: even on partial-fail (≤50% errored) surface the warning so
        # operators are aware some batches failed and the topic set may be
        # incomplete.
        if failed_batches > 0:
            typer.echo(
                f"\n⚠️  Failed: {failed_batches}/{total_batches} batches errored "
                "(partial result — see logs for details)"
            )
            if last_batch_error:
                typer.echo(f"   • First error: {last_batch_error}")

        # BUG-023: surface aggregate quality-filter rejection breakdown so
        # operators can understand why coverage is below expectation /
        # calibrate the quality threshold from logs alone.
        _print_rejection_breakdown(stats.get("rejection_breakdown") or {})

        if stats["topics_count"] == 0 and failed_batches == 0:
            # Only show the «недостаточно данных» hint when batch failures
            # are NOT the cause (BUG-018 — the message was misleading in
            # all-batch-fail scenarios).
            typer.echo("\n⚠️  Темы не созданы (возможно, недостаточно данных)")

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


def _run_incremental_topicization_cli(
    channel: str,
    cross_channel: bool | None = None,
) -> None:
    """Run incremental topicization (Phase 1 + Phase 2) for uncovered docs."""
    import asyncio

    from tg_parser.cli.topicize_cmd import run_incremental_topicization_for_uncovered

    typer.echo("📋 Режим: incremental (Phase 1 keyword + Phase 2 LLM discover)")

    from tg_parser.processing.llm.factory import resolve_llm_config

    eff_provider, _, eff_model = resolve_llm_config("topicization")
    typer.echo(f"🔌 LLM (Phase 2): {eff_provider}/{eff_model or 'default'}")

    try:
        result = asyncio.run(
            run_incremental_topicization_for_uncovered(
                channel_id=channel,
                assign_only=False,
                cross_channel=cross_channel,
            )
        )

        _print_incremental_stats(result)

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


def _run_assign_only_topicization_cli(channel: str) -> None:
    """Run assign-only topicization (Phase 1 only, 0 LLM tokens)."""
    import asyncio

    from tg_parser.cli.topicize_cmd import run_incremental_topicization_for_uncovered

    typer.echo("📋 Режим: assign-only (Phase 1 keyword, 0 LLM tokens)")

    try:
        result = asyncio.run(
            run_incremental_topicization_for_uncovered(
                channel_id=channel,
                assign_only=True,
            )
        )

        _print_incremental_stats(result)

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


def _print_rejection_breakdown(rejection_breakdown: dict) -> None:
    """Render the BUG-023 per-reason quality-filter rejection summary.

    Shared between the full and incremental CLI paths so the wording is
    consistent. No-op when the breakdown is empty.
    """
    if not rejection_breakdown:
        return
    total_rejected = sum(rejection_breakdown.values())
    breakdown_str = ", ".join(
        f"{count} by {reason}" for reason, count in sorted(rejection_breakdown.items())
    )
    typer.echo(f"   • Quality filter rejected {total_rejected} topics: {breakdown_str}")


def _print_incremental_stats(result) -> None:
    """Print statistics for incremental/assign-only topicization."""
    # BUG-073 (F3 — Bugbot follow-up): a backlog-fill that benignly deferred
    # because another incremental run held the channel lock did NO Phase 1/2
    # work. Report it as a DISTINCT, non-success-but-non-error outcome so an
    # operator can never mistake it for a completed "0 assigned / 0% coverage"
    # backlog run. A defer is benign/expected (the uncovered backlog is retried
    # next run), so this is NOT a hard error / non-zero exit — just a prominent,
    # clearly-worded line.
    if getattr(result, "deferred_locked", False):
        typer.echo(
            "\n⏭️  Incremental topicization deferred — another topicization run "
            "holds the channel lock.\n"
            "   Uncovered backlog was NOT processed this run; it will be retried "
            "on the next run."
        )
        return

    typer.echo("\n✅ Incremental topicization завершён:")
    typer.echo(f"   • Phase 1 (keyword): {len(result.assigned_keyword)} docs assigned")

    if result.assigned_llm or result.new_topics:
        typer.echo(
            f"   • Phase 2 (LLM): {len(result.assigned_llm)} docs assigned, "
            f"{len(result.new_topics)} new topic(s) created"
        )

    typer.echo(f"   • Unassignable: {len(result.unassignable)} docs")
    typer.echo(f"   • Coverage: {result.coverage_before}% → {result.coverage_after}%")

    # BUG-023: surface per-reason rejection breakdown (Phase 2 LLM discover).
    rejection_breakdown = getattr(result, "rejection_breakdown", None) or {}
    _print_rejection_breakdown(rejection_breakdown)

    if result.cross_channel_links_created:
        typer.echo(f"   • Cross-channel links: {result.cross_channel_links_created} created")

    total_assigned = len(result.assigned_keyword) + len(result.assigned_llm)
    if total_assigned == 0 and not result.new_topics:
        typer.echo("\n⚠️  Нет uncovered документов или совпадений не найдено")


@app.command(name="link-topics")
def link_topics(
    threshold: float = typer.Option(0.3, help="Minimum similarity score for linking (0.0–1.0)"),
):
    """Link related topics across different channels.

    Computes Jaccard (keyword) + cosine (embedding) similarity between
    topics from different channels and creates links for pairs above threshold.
    """
    import asyncio

    typer.echo("🔗 Cross-channel topic linking\n")
    typer.echo(f"   • Threshold: {threshold}")

    try:
        from tg_parser.services.topic_linking_service import link_topics as do_link

        result = asyncio.run(do_link(threshold=threshold))

        typer.echo("\n✅ Topic linking завершён:")
        typer.echo(f"   • Pairs evaluated: {result.total_pairs_evaluated}")
        typer.echo(f"   • Links created: {result.links_created}")
        typer.echo(f"   • Avg similarity: {result.avg_similarity}")

        if result.links_created == 0:
            typer.echo("\n⚠️  No cross-channel topic links found above threshold")

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def embed(
    channel: str = typer.Option(..., help="Идентификатор канала"),
    force: bool = typer.Option(False, help="Переэмбеддить все документы"),
):
    """
    Сгенерировать embeddings для processed documents канала (P5 RAG).

    Использует OpenAI text-embedding-3-small (или настроенную модель).
    """
    import asyncio

    from tg_parser.config import settings as app_settings

    typer.echo(f"🔢 Embedding канала: {channel}\n")
    typer.echo(f"   • Model: {app_settings.embedding_model}")
    typer.echo(f"   • Batch size: {app_settings.embedding_batch_size}")
    if force:
        typer.echo("   ⚠️  Force: все документы будут переэмбеддированы")

    try:
        from tg_parser.services.embedding_service import run_embedding

        stats = asyncio.run(run_embedding(channel_id=channel, force=force))

        typer.echo("\n✅ Embedding завершён:")
        typer.echo(f"   • Embedded: {stats['embedded_count']}")
        typer.echo(f"   • Skipped: {stats['skipped_count']}")
        typer.echo(f"   • Total: {stats['total_count']}")

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


async def _resolve_workspace_scope_cli(
    user_arg: str | None,
    workspace_id: str | None,
) -> tuple[list[str] | None, bool]:
    """CLI helper — resolve ``--user`` + ``--workspace-id`` to scope.

    Returns ``(effective_channel_ids, ok)``. ``ok`` is ``False`` when the
    workspace is unknown / foreign (caller prints a friendly message and
    exits without dumping a stack trace).
    """
    from tg_parser.auth.ownership import WorkspaceNotFound
    from tg_parser.cli.workspace_cmd import _resolve_acting_user
    from tg_parser.services.db_context import workspace_repo
    from tg_parser.services.workspace_service import WorkspaceService

    if workspace_id is None and user_arg is None:
        return None, True

    acting = await _resolve_acting_user(user_arg)
    if workspace_id is None:
        return acting.allowed_channel_ids, True

    async with workspace_repo() as (repo, _db):
        service = WorkspaceService(repo)
        try:
            return await service.effective_channel_ids(acting, workspace_id), True
        except WorkspaceNotFound:
            return None, False


@app.command()
def search(
    query: str = typer.Option(..., help="Поисковый запрос"),
    channel: str = typer.Option(None, help="Фильтр по каналу"),
    limit: int = typer.Option(10, help="Количество результатов"),
    workspace_id: str = typer.Option(
        None,
        "--workspace-id",
        help="F4-B: narrow search scope to channels in this workspace",
    ),
    user: str = typer.Option(
        None,
        "--user",
        help="Act as this user UUID (required if --workspace-id is set)",
    ),
):
    """
    Семантический поиск по embedded документам (P5 RAG).
    """
    import asyncio

    typer.echo(f'🔍 Поиск: "{query}"\n')
    if channel:
        typer.echo(f"   Фильтр: канал={channel}")
    if workspace_id:
        typer.echo(f"   Workspace: {workspace_id}")

    try:
        effective, ok = asyncio.run(_resolve_workspace_scope_cli(user, workspace_id))
        if not ok:
            typer.echo("\n⚠️  Workspace не найден")
            raise typer.Exit(code=1)

        from tg_parser.services.retrieval_service import search as do_search

        results = asyncio.run(
            do_search(
                query=query,
                channel_id=channel,
                limit=limit,
                allowed_channel_ids=effective,
            )
        )

        if not results:
            typer.echo("\n⚠️  Ничего не найдено")
            return

        typer.echo(f"\n📋 Найдено {len(results)} результатов:\n")
        for i, r in enumerate(results, 1):
            title = ""
            if r.document:
                title = r.document.summary or r.document.text_clean[:80]
            typer.echo(f"  [{i}] (score={r.score:.3f}) {r.source_ref}")
            if title:
                typer.echo(f"      {title[:120]}")
            typer.echo()

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def ask(
    question: str = typer.Option(..., help="Вопрос на естественном языке"),
    channel: str = typer.Option(None, help="Фильтр по каналу"),
    workspace_id: str = typer.Option(
        None,
        "--workspace-id",
        help="F4-B: narrow retrieval scope to channels in this workspace",
    ),
    user: str = typer.Option(
        None,
        "--user",
        help="Act as this user UUID (required if --workspace-id is set)",
    ),
):
    """
    Q&A по содержимому каналов с использованием RAG (P5).
    """
    import asyncio

    typer.echo(f'❓ Вопрос: "{question}"\n')
    if channel:
        typer.echo(f"   Фильтр: канал={channel}")
    if workspace_id:
        typer.echo(f"   Workspace: {workspace_id}")

    try:
        effective, ok = asyncio.run(_resolve_workspace_scope_cli(user, workspace_id))
        if not ok:
            typer.echo("\n⚠️  Workspace не найден")
            raise typer.Exit(code=1)

        from tg_parser.services.retrieval_service import answer as do_answer

        result = asyncio.run(
            do_answer(
                question=question,
                channel_id=channel,
                allowed_channel_ids=effective,
            )
        )

        typer.echo("\n💬 Ответ:\n")
        typer.echo(result.answer)

        if result.sources:
            typer.echo(f"\n📌 Источники ({len(result.sources)}):")
            for i, s in enumerate(result.sources, 1):
                score_str = f"score={s.score:.3f}"
                typer.echo(f"  [{i}] {s.source_ref} ({score_str})")

        if result.model:
            typer.echo(f"\n🤖 Model: {result.model}")

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def export(
    out: str = typer.Option("./output", help="Директория вывода"),
    channel: str = typer.Option(None, help="Фильтр по каналу"),
    topic_id: str = typer.Option(None, help="Фильтр по теме"),
    from_date: str = typer.Option(None, help="Дата от (ISO format: YYYY-MM-DD)"),
    to_date: str = typer.Option(None, help="Дата до (ISO format: YYYY-MM-DD)"),
    pretty: bool = typer.Option(False, help="Pretty-print JSON"),
    level: str = typer.Option(
        "full",
        help="Уровень экспорта: raw | processed | full (по умолчанию full — legacy)",
    ),
    format: str = typer.Option(
        "json",
        help="Формат для level=raw: json | ndjson (для processed/full игнорируется)",
    ),
):
    """
    Экспортировать артефакты (TR-56..TR-64 + F2 Parse-Only).

    Уровни экспорта (F2):

    - ``--level full`` (по умолчанию): ``kb_entries.ndjson`` + ``topics.json``
      + ``topic_<id>.json`` (legacy behaviour; обратная совместимость).
    - ``--level processed``: только ``kb_entries.ndjson`` (без topics).
    - ``--level raw``: ``raw_messages.{json,ndjson}`` (parse-only, без LLM).
      Требует ``--channel``.
    """
    import asyncio
    from datetime import datetime

    from tg_parser.api.schemas import ExportFormat, ExportLevel
    from tg_parser.cli.export_cmd import run_export

    try:
        level_enum = ExportLevel(level)
    except ValueError as e:
        typer.echo(
            f"❌ Неверный --level: {level} (ожидается: raw | processed | full)",
            err=True,
        )
        raise typer.Exit(code=1) from e

    try:
        format_enum = ExportFormat(format)
    except ValueError as e:
        typer.echo(
            f"❌ Неверный --format: {format} (ожидается: json | ndjson)",
            err=True,
        )
        raise typer.Exit(code=1) from e

    if level_enum == ExportLevel.RAW and not channel:
        typer.echo("❌ --level=raw требует --channel", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"📤 Экспорт в: {out} (уровень: {level_enum.value})\n")

    from_datetime = None
    to_datetime = None

    if from_date:
        try:
            from_datetime = datetime.fromisoformat(from_date)
            typer.echo(f"   Фильтр: от {from_date}")
        except ValueError as e:
            typer.echo(f"❌ Неверный формат даты: {from_date} (используйте YYYY-MM-DD)", err=True)
            raise typer.Exit(code=1) from e

    if to_date:
        try:
            to_datetime = datetime.fromisoformat(to_date)
            typer.echo(f"   Фильтр: до {to_date}")
        except ValueError as e:
            typer.echo(f"❌ Неверный формат даты: {to_date} (используйте YYYY-MM-DD)", err=True)
            raise typer.Exit(code=1) from e

    if channel:
        typer.echo(f"   Фильтр: канал={channel}")
    if topic_id:
        typer.echo(f"   Фильтр: тема={topic_id}")

    try:
        stats = asyncio.run(
            run_export(
                output_dir=out,
                channel_id=channel,
                topic_id=topic_id,
                from_date=from_datetime,
                to_date=to_datetime,
                pretty=pretty,
                level=level_enum,
                format=format_enum,
            )
        )

        typer.echo("\n✅ Экспорт завершён:")

        if level_enum == ExportLevel.RAW:
            typer.echo(f"   • Posts: {stats['raw_posts_count']}")
            typer.echo(f"   • Comments: {stats['raw_comments_count']}")
            if stats.get("raw_orphan_comments_count"):
                typer.echo(
                    "   • Orphan comments (parent out of range): "
                    f"{stats['raw_orphan_comments_count']}"
                )
            typer.echo(f"   • Каналов: {stats['channels_count']}")
            typer.echo(f"   • Файл: {out}/raw_messages.{format_enum.value}")
            if (
                stats["raw_posts_count"] == 0
                and stats["raw_comments_count"] == 0
                and stats.get("raw_orphan_comments_count", 0) == 0
            ):
                typer.echo("\n⚠️  Нет сообщений для экспорта (пустой envelope записан)")
        else:
            typer.echo(f"   • KB entries: {stats['kb_entries_count']}")
            typer.echo(f"   • Topics: {stats['topics_count']}")
            typer.echo(f"   • Каналов: {stats['channels_count']}")

            if stats["kb_entries_count"] > 0:
                typer.echo(f"   • Файл: {out}/kb_entries.ndjson")
            if stats["topics_count"] > 0:
                typer.echo(f"   • Файлы: {out}/topics.json, {out}/topic_*.json")

            if stats["kb_entries_count"] == 0 and stats["topics_count"] == 0:
                typer.echo("\n⚠️  Нет данных для экспорта")

    except Exception as e:
        typer.echo(f"\n❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def api(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, help="Enable auto-reload (development)"),
    workers: int = typer.Option(1, help="Number of worker processes"),
    log_level: str = typer.Option("info", help="Logging level"),
):
    """
    Start HTTP API server (v2.0).

    Runs FastAPI server for HTTP-based processing.

    Examples:
        tg-parser api --port 8000
        tg-parser api --reload  # Development mode
        tg-parser api --workers 4  # Production mode
    """
    from tg_parser.cli.api_cmd import run_api_server

    typer.echo("🌐 Starting TG_parser API server...")
    typer.echo(f"   • Host: {host}")
    typer.echo(f"   • Port: {port}")
    if reload:
        typer.echo("   • Auto-reload: enabled (development mode)")
    if workers > 1:
        typer.echo(f"   • Workers: {workers}")
    typer.echo()
    typer.echo(f"📚 API docs: http://{host}:{port}/docs")
    typer.echo(f"📖 ReDoc: http://{host}:{port}/redoc")
    typer.echo()

    run_api_server(
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level=log_level,
    )


@app.command()
def bot() -> None:
    """Start the Telegram bot (Phase 3 — Gemini agent).

    The bot uses Gemini function-calling to route user messages to internal
    services (search, Q&A, topics, channels, analytics) and returns
    structured responses.

    Requires: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, BOT_ALLOWED_USERS.

    Examples:
        tg-parser bot
        docker compose up tg_bot -d
    """
    from tg_parser.config import settings

    typer.echo("🤖 Starting TG_parser Telegram Bot (Phase 3)...")
    typer.echo(f"   • Gemini model: {settings.bot_gemini_model}")
    typer.echo(f"   • Allowed users: {len(settings.bot_allowed_user_ids) or 'all (no allowlist)'}")
    typer.echo(f"   • Rate limit: {settings.bot_rate_limit}/min")
    typer.echo(f"   • Request timeout: {settings.bot_request_timeout}s")
    typer.echo()

    from tg_parser.bot.main import run_bot_sync

    run_bot_sync()


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="Transport: stdio or streamable-http"),
    host: str = typer.Option(None, help="Bind host (default from settings)"),
    port: int = typer.Option(None, help="Bind port (default from settings)"),
):
    """Start MCP server for AI agents (Claude Desktop, Cursor).

    Exposes search, Q&A, topic navigation, and channel tools
    via the Model Context Protocol.

    Examples:
        tg-parser mcp                               # stdio (default)
        tg-parser mcp --transport streamable-http    # HTTP on configured host:port
        tg-parser mcp --transport streamable-http --host 0.0.0.0 --port 8080
    """
    valid_transports = ("stdio", "streamable-http")
    if transport not in valid_transports:
        typer.echo(
            f"❌ Invalid transport: {transport}. Must be one of: {', '.join(valid_transports)}",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo("🔌 Starting TG_parser MCP server...")
    typer.echo(f"   • Transport: {transport}")

    if host or port:
        from tg_parser.mcp_server import mcp as mcp_server

        if host:
            mcp_server.settings.host = host
            typer.echo(f"   • Host: {host}")
        if port:
            mcp_server.settings.port = port
            typer.echo(f"   • Port: {port}")

    typer.echo()

    if transport == "stdio":
        import asyncio

        from tg_parser.mcp_server import _run_mcp

        asyncio.run(_run_mcp())
    else:
        import asyncio

        from tg_parser.mcp_server import _run_http

        asyncio.run(_run_http())


@app.command()
def run(
    source: str = typer.Option(..., help="ID источника/канала"),
    out: str = typer.Option("./output", help="Директория вывода"),
    mode: str = typer.Option("incremental", help="Режим ingestion: snapshot или incremental"),
    skip_ingest: bool = typer.Option(False, help="Пропустить ingestion"),
    skip_process: bool = typer.Option(False, help="Пропустить processing"),
    skip_topicize: bool = typer.Option(False, help="Пропустить topicization"),
    force: bool = typer.Option(False, help="Force режим для processing/topicization"),
    limit: int = typer.Option(None, help="Лимит сообщений для ingestion (для отладки)"),
    concurrency: int = typer.Option(
        None,
        "--concurrency",
        "-c",
        help="Parallel LLM requests for processing (default: from PROCESSING_CONCURRENCY env)",
    ),
):
    """
    One-shot запуск: ingest → process → topicize → export (TR-44).

    Последовательно выполняет все этапы pipeline:
    1. Ingestion - сбор raw сообщений из Telegram
    2. Processing - обработка через LLM
    3. Topicization - формирование тем
    4. Export - экспорт результатов
    """
    import asyncio

    from tg_parser.cli.run_cmd import run_full_pipeline

    typer.echo(f"🚀 One-shot запуск для источника: {source}\n")
    typer.echo(f"   • Режим ingestion: {mode}")
    typer.echo(f"   • Директория вывода: {out}")

    if skip_ingest:
        typer.echo("   ⚠️  Ingestion будет пропущен")
    if skip_process:
        typer.echo("   ⚠️  Processing будет пропущен")
    if skip_topicize:
        typer.echo("   ⚠️  Topicization будет пропущен")
    if force:
        typer.echo("   ⚠️  Force режим включён")
    if limit:
        typer.echo(f"   • Лимит сообщений: {limit}")

    from tg_parser.config import settings as run_settings

    eff_conc = concurrency if concurrency is not None else run_settings.processing_concurrency
    typer.echo(f"   • Concurrency: {eff_conc}{' (from settings)' if concurrency is None else ''}")

    typer.echo()

    try:
        # Запускаем full pipeline
        stats = asyncio.run(
            run_full_pipeline(
                source_id=source,
                output_dir=out,
                mode=mode,  # type: ignore[arg-type]  # Typer provides str; runtime-valid Literal
                skip_ingest=skip_ingest,
                skip_process=skip_process,
                skip_topicize=skip_topicize,
                force=force,
                limit=limit,
                concurrency=concurrency,
            )
        )

        # BUG-073 (F1): the full pipeline short-circuits when its processing
        # stage was a benign lock-skip (another run owns the channel). Report it
        # distinctly — NOT the green "Pipeline завершён успешно!" banner — so the
        # operator does not read a no-op as a successful end-to-end run.
        if stats.get("skipped_locked"):
            typer.echo(
                "\n⏭️  Pipeline пропущен — другой процесс уже обрабатывает этот "
                "канал (per-channel lock занят); processing/topicization/export "
                "не выполнялись. Будет обработано следующим запуском."
            )
            return

        # Выводим детальную статистику по этапам
        typer.echo("\n" + "=" * 60)
        typer.echo("📊 Итоговая статистика:")
        typer.echo("=" * 60)

        if stats["ingest"]:
            typer.echo("\n📥 Ingestion:")
            typer.echo(f"   • Постов собрано: {stats['ingest']['posts_collected']}")
            typer.echo(f"   • Комментариев собрано: {stats['ingest']['comments_collected']}")
            typer.echo(f"   • Ошибок: {stats['ingest']['errors']}")
            typer.echo(f"   • Время: {stats['ingest']['duration_seconds']:.2f}s")

        if stats["process"]:
            typer.echo("\n⚙️  Processing:")
            typer.echo(f"   • Обработано: {stats['process']['processed_count']}")
            typer.echo(f"   • Пропущено: {stats['process']['skipped_count']}")
            typer.echo(f"   • Ошибок: {stats['process']['failed_count']}")

        if stats["topicize"]:
            typer.echo("\n🏷️  Topicization:")
            typer.echo(f"   • Создано тем: {stats['topicize']['topics_count']}")
            typer.echo(f"   • Создано подборок: {stats['topicize']['bundles_count']}")
            if "coverage_pct" in stats["topicize"]:
                typer.echo(
                    f"   • Coverage: {stats['topicize']['coverage_pct']}% "
                    f"({stats['topicize']['covered_documents']}/{stats['topicize']['total_documents']})"
                )

        if stats["export"]:
            typer.echo("\n📤 Export:")
            typer.echo(f"   • KB entries: {stats['export']['kb_entries_count']}")
            typer.echo(f"   • Topics: {stats['export']['topics_count']}")
            typer.echo(f"   • Каналов: {stats['export']['channels_count']}")
            typer.echo(f"   • Директория: {out}")

        typer.echo("\n" + "=" * 60)
        typer.echo(f"⏱️  Общее время выполнения: {stats['total_duration_seconds']:.2f}s")
        typer.echo("=" * 60)
        typer.echo("\n✅ Pipeline завершён успешно!")

    except RuntimeError as e:
        # Обрабатываем ошибки из run_full_pipeline
        typer.echo(f"\n❌ {e}", err=True)
        typer.echo(
            "\n⚠️  Pipeline остановлен. Проверьте логи для деталей.",
            err=True,
        )
        raise typer.Exit(code=1) from e
    except Exception as e:
        typer.echo(f"\n❌ Непредвиденная ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command(name="migrate-users")
def migrate_users(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be done without making changes"
    ),
):
    """Migrate existing API keys, MCP tokens, and bot user IDs to multi-tenancy user model.

    One-time utility for existing deployments upgrading to F4 multi-tenancy.
    Safe to run multiple times (idempotent).
    """
    import asyncio

    from tg_parser.cli.migrate_users_cmd import run_migrate_users

    typer.echo("🔄 Migrating to multi-tenancy user model...\n")
    if dry_run:
        typer.echo("   ⚠️  Dry-run mode: no changes will be made\n")

    try:
        stats = asyncio.run(run_migrate_users(dry_run=dry_run))

        typer.echo("✅ Migration completed:\n")
        typer.echo(
            f"   • Admin user: {stats['admin_user_id']}"
            f"{' (created)' if stats['admin_created'] else ' (existing)'}"
        )
        typer.echo(f"   • API keys mapped: {stats['api_keys_mapped']}")
        typer.echo(f"   • MCP tokens mapped: {stats['mcp_tokens_mapped']}")
        typer.echo(f"   • Telegram users mapped: {stats['telegram_users_mapped']}")
        typer.echo(f"   • Orphan sources assigned: {stats['orphan_sources_assigned']}")
        if stats["skipped_existing"] > 0:
            typer.echo(f"   • Skipped (already mapped): {stats['skipped_existing']}")

    except Exception as e:
        typer.echo(f"\n❌ Migration error: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command(name="backfill-content-hash")
def backfill_content_hash(
    channel_id: str | None = typer.Option(
        None, "--channel-id", help="Limit backfill to a single channel"
    ),
    batch_size: int = typer.Option(
        500, "--batch-size", min=1, max=10_000, help="Rows per SQL batch"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count only; do not write content_hash"),
) -> None:
    """F5-A Phase 3: compute content_hash for existing processed_documents.

    Idempotent — safe to re-run. Only touches rows where content_hash IS
    NULL. Does NOT delete existing duplicates (see F5A_PERSISTENT_KB_PLAN
    §3.5 for prune-duplicates scope).
    """
    import asyncio

    from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

    typer.echo("🔐 Backfilling content_hash...\n")
    if dry_run:
        typer.echo("   ⚠️  Dry-run mode: no UPDATE will be issued\n")
    if channel_id is not None:
        typer.echo(f"   Scope: channel_id = {channel_id}\n")

    try:
        stats = asyncio.run(
            run_backfill_content_hash(
                channel_id=channel_id,
                batch_size=batch_size,
                dry_run=dry_run,
            )
        )
    except KeyboardInterrupt:
        typer.echo("\n⚠️  Interrupted by user", err=True)
        raise typer.Exit(code=130) from None
    except Exception as e:
        typer.echo(f"\n❌ Backfill error: {e}", err=True)
        raise typer.Exit(code=1) from e

    typer.echo("✅ Backfill complete:\n")
    typer.echo(f"   • Scanned: {stats.total_scanned}")
    typer.echo(f"   • Hashed:  {stats.total_hashed}")
    typer.echo(f"   • Skipped (empty text_clean): {stats.total_skipped_empty_text}")
    typer.echo(f"   • Elapsed: {stats.elapsed_sec}s")


if __name__ == "__main__":
    app()
