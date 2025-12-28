"""
CLI интерфейс TG_parser (Typer).

Реализует TR-44/TR-55..TR-64: команды ingestion/processing/topicization/export.
"""

import typer

from tg_parser.cli.agents_cmd import app as agents_app

app = typer.Typer(
    name="tg_parser",
    help="TG_parser CLI - сбор и обработка контента из Telegram",
)

# Add agents subcommand group
app.add_typer(agents_app, name="agents")


@app.command()
def init(
    force: bool = typer.Option(False, help="Пересоздать базы даже если существуют"),
):
    """
    Инициализировать базы данных (создать таблицы).

    Создаёт 3 SQLite файла и выполняет DDL.
    """
    from tg_parser.cli.init_db import check_databases_exist, init_databases_sync
    from tg_parser.config import settings
    from tg_parser.storage.sqlite import DatabaseConfig

    typer.echo("🔧 Инициализация баз данных...\n")

    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )

    # Проверяем существование баз
    if not force and check_databases_exist(config):
        typer.echo("⚠️  Базы данных уже существуют:")
        if config.ingestion_state_path.exists():
            typer.echo(f"   ✓ {config.ingestion_state_path}")
        if config.raw_storage_path.exists():
            typer.echo(f"   ✓ {config.raw_storage_path}")
        if config.processing_storage_path.exists():
            typer.echo(f"   ✓ {config.processing_storage_path}")
        typer.echo("\nИспользуйте --force для пересоздания")
        return

    try:
        init_databases_sync()
        typer.echo("\n✅ Базы данных успешно созданы:")
        typer.echo(f"   • {config.ingestion_state_path}")
        typer.echo(f"   • {config.raw_storage_path}")
        typer.echo(f"   • {config.processing_storage_path}")
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

    try:
        asyncio.run(
            run_add_source(
                source_id=source_id,
                channel_id=channel_id,
                channel_username=channel_username,
                include_comments=include_comments,
                batch_size=batch_size,
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

    Собирает raw сообщения в raw_storage.sqlite.
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
    provider: str = typer.Option(None, "--provider", help="LLM provider (openai|anthropic|gemini|ollama)"),
    model: str = typer.Option(None, "--model", help="Model override"),
    concurrency: int = typer.Option(1, "--concurrency", "-c", help="Parallel requests (default: 1)"),
    agent: bool = typer.Option(False, "--agent", help="Use agent-based processing (v2.0)"),
    agent_llm: bool = typer.Option(False, "--agent-llm", help="Use LLM-enhanced agent tools"),
    hybrid: bool = typer.Option(False, "--hybrid", help="Enable v1.2 pipeline as agent tool (Phase 2E)"),
    multi_agent: bool = typer.Option(False, "--multi-agent", help="Use multi-agent orchestration (Phase 3A)"),
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
    if concurrency > 1:
        typer.echo(f"⚡ Concurrency: {concurrency} parallel requests")

    if retry_failed:
        typer.echo("🔄 Режим retry-failed (повтор ошибок)")
    if force:
        typer.echo("⚠️  Режим force (переобработка)")

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
                    use_agent=agent,
                    use_llm_tools=agent_llm,
                    use_pipeline_tool=hybrid,
                )
            )

        # Выводим статистику
        if retry_failed:
            typer.echo("\n✅ Retry processing завершён:")
        else:
            typer.echo("\n✅ Processing завершён:")
        typer.echo(f"   • Обработано: {stats['processed_count']}")
        typer.echo(f"   • Пропущено: {stats['skipped_count']}")
        typer.echo(f"   • Ошибок: {stats['failed_count']}")
        typer.echo(f"   • Всего сообщений: {stats['total_count']}")

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
):
    """
    Запустить topicization для канала (TR-44).

    Формирует TopicCard + TopicBundle из ProcessedDocument.
    """
    import asyncio

    from tg_parser.cli.topicize_cmd import run_topicization

    typer.echo(f"🏷️  Topicization канала: {channel}\n")

    if force:
        typer.echo("⚠️  Режим force (переформирование тем)")

    if no_bundles:
        typer.echo("⚠️  Bundles не будут созданы")

    try:
        # Запускаем async функцию
        stats = asyncio.run(
            run_topicization(
                channel_id=channel,
                force=force,
                build_bundles=not no_bundles,
            )
        )

        # Выводим статистику
        typer.echo("\n✅ Topicization завершён:")
        typer.echo(f"   • Создано тем: {stats['topics_count']}")
        typer.echo(f"   • Создано подборок: {stats['bundles_count']}")

        if stats["topics_count"] == 0:
            typer.echo("\n⚠️  Темы не созданы (возможно, недостаточно данных)")

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
):
    """
    Экспортировать артефакты (TR-56..TR-64).

    Создаёт kb_entries.ndjson в указанной директории.
    В будущем: topics.json, topic_<id>.json.
    """
    import asyncio
    from datetime import datetime

    from tg_parser.cli.export_cmd import run_export

    typer.echo(f"📤 Экспорт в: {out}\n")

    # Парсинг дат
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
        # Запускаем async функцию
        stats = asyncio.run(
            run_export(
                output_dir=out,
                channel_id=channel,
                topic_id=topic_id,
                from_date=from_datetime,
                to_date=to_datetime,
                pretty=pretty,
            )
        )

        # Выводим статистику
        typer.echo("\n✅ Экспорт завершён:")
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
    
    typer.echo(f"🌐 Starting TG_parser API server...")
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
def run(
    source: str = typer.Option(..., help="ID источника/канала"),
    out: str = typer.Option("./output", help="Директория вывода"),
    mode: str = typer.Option("incremental", help="Режим ingestion: snapshot или incremental"),
    skip_ingest: bool = typer.Option(False, help="Пропустить ingestion"),
    skip_process: bool = typer.Option(False, help="Пропустить processing"),
    skip_topicize: bool = typer.Option(False, help="Пропустить topicization"),
    force: bool = typer.Option(False, help="Force режим для processing/topicization"),
    limit: int = typer.Option(None, help="Лимит сообщений для ingestion (для отладки)"),
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

    typer.echo()

    try:
        # Запускаем full pipeline
        stats = asyncio.run(
            run_full_pipeline(
                source_id=source,
                output_dir=out,
                mode=mode,  # type: ignore
                skip_ingest=skip_ingest,
                skip_process=skip_process,
                skip_topicize=skip_topicize,
                force=force,
                limit=limit,
            )
        )

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


if __name__ == "__main__":
    app()
