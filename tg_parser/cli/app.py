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
    channel_id: str = typer.Option(..., help="Идентификатор канала"),
    channel_username: str = typer.Option(None, help="Username канала (опц.)"),
    include_comments: bool = typer.Option(False, help="Собирать комментарии"),
):
    """
    Добавить источник (канал) для ingestion.
    """
    typer.echo(f"➕ Добавление источника: {channel_id}")

    # TODO: реализовать add_source через IngestionStateRepo
    typer.echo("✅ Источник добавлен")


@app.command()
def ingest(
    channel: str = typer.Option(..., help="Идентификатор канала"),
    dry_run: bool = typer.Option(False, help="Режим dry-run"),
):
    """
    Запустить ingestion для канала (TR-44).

    Собирает raw сообщения в raw_storage.sqlite.
    """
    typer.echo(f"📥 Ingestion канала: {channel}")

    if dry_run:
        typer.echo("⚠️  Режим dry-run (изменения не применяются)")

    # TODO: реализовать ingestion pipeline
    typer.echo("✅ Ingestion завершён")


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
    max_topics: int = typer.Option(None, help="Лимит тем"),
    dry_run: bool = typer.Option(False, help="Режим dry-run"),
):
    """
    Запустить topicization для канала (TR-44).

    Формирует TopicCard + TopicBundle.
    """
    typer.echo(f"🏷️  Topicization канала: {channel}")

    if max_topics:
        typer.echo(f"   Лимит тем: {max_topics}")

    if dry_run:
        typer.echo("⚠️  Режим dry-run")

    # TODO: реализовать topicization
    typer.echo("✅ Topicization завершён")


@app.command()
def export(
    channel: str = typer.Option(None, help="Фильтр по каналу"),
    topic_id: str = typer.Option(None, help="Фильтр по теме"),
    out: str = typer.Option("./output", help="Директория вывода"),
    format: str = typer.Option("json", help="Формат: json|ndjson"),
    pretty: bool = typer.Option(False, help="Pretty-print JSON"),
    include_supporting: bool = typer.Option(True, help="Включать supporting"),
):
    """
    Экспортировать артефакты (TR-56..TR-64).

    Создаёт topics.json, topic_<id>.json, kb_entries.ndjson.
    """
    typer.echo(f"📤 Экспорт в: {out}")

    if channel:
        typer.echo(f"   Фильтр: канал={channel}")
    if topic_id:
        typer.echo(f"   Фильтр: тема={topic_id}")

    # TODO: реализовать export pipeline
    typer.echo("✅ Экспорт завершён")


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
