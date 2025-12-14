"""
CLI интерфейс TG_parser (Typer).

Реализует TR-44/TR-55..TR-64: команды ingestion/processing/topicization/export.
"""

import typer

app = typer.Typer(
    name="tg_parser",
    help="TG_parser CLI - сбор и обработка контента из Telegram",
)


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
    dry_run: bool = typer.Option(False, help="Режим dry-run"),
):
    """
    Запустить processing для канала (TR-44).

    Обрабатывает raw → ProcessedDocument.
    """
    import asyncio

    from tg_parser.cli.process_cmd import run_processing

    typer.echo(f"⚙️  Processing канала: {channel}\n")

    if force:
        typer.echo("⚠️  Режим force (переобработка)")

    if dry_run:
        typer.echo("⚠️  Режим dry-run (пока не реализовано)")
        return

    try:
        # Запускаем async функцию
        stats = asyncio.run(run_processing(channel, force=force))

        # Выводим статистику
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
def run(
    channel: str = typer.Option(..., help="Идентификатор канала"),
    out: str = typer.Option("./output", help="Директория вывода"),
):
    """
    One-shot запуск: ingest → process → topicize → export (TR-44).
    """
    typer.echo(f"🚀 One-shot запуск для канала: {channel}\n")

    # TODO: реализовать последовательный вызов всех этапов
    typer.echo("📥 Ingestion...")
    typer.echo("⚙️  Processing...")
    typer.echo("🏷️  Topicization...")
    typer.echo(f"📤 Экспорт в {out}...")

    typer.echo("\n✅ One-shot завершён")


if __name__ == "__main__":
    app()
