# ADR 0001 – Общая архитектура TG_parser

## Статус
Accepted

## Контекст

Нужно спроектировать пайплайн, который:
- забирает сообщения из Telegram‑каналов;
- обрабатывает их с помощью ИИ;
- формирует тематическую базу знаний (в MVP — через CLI‑экспорт артефактов).

> **Implementation status (2026-05-14, HEAD `47e1c72`).**
>
> **Access layer evolved:** ADR описывает MVP с CLI как primary entry point.
> Текущая реальность — **4 entry points**:
> - `tg_parser/cli/` (CLI Typer-команды — backbone for ingest / process / export / workspace)
> - `tg_parser/api/main.py` (FastAPI HTTP API — `/api/v1/*` endpoints)
> - `tg_parser/mcp_server.py` (MCP server, **43 tools**: search / Q&A /
>   navigation / channel mgmt / pipeline / F4 user mgmt / F4-B workspaces /
>   F5-C resummarize / F6 digests / F11 watchlist / export / LLM config /
>   prompts reload)
> - `tg_parser/bot/main.py` (Telegram bot, Gemini-powered agent with 24 tools)
>
> Разделение ingestion / processing / storage / access-export сохранено
> per ADR; multi-entry-point эволюция следует из audience-driven roadmap
> (см. [`docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](../notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)).
> Decision **не отменён**, расширен.

## Решение

- Разделить систему на основные слои:
  - **Ingestion** – взаимодействие с Telegram и получение сырых сообщений.
  - **Processing** – очистка, нормализация и интеллектуальная обработка (LLM).
  - **Storage** – сохранение raw/processed артефактов и (в перспективе) индексов для поиска.
  - **Access / Export** – CLI‑экспорт и (в перспективе) API/сервисы доступа к данным.
- Между слоями обмениваться строго определёнными структурами:
  - `RawTelegramMessage` → `ProcessedDocument`.
  - `KnowledgeBaseEntry` формируется на этапе Access / Export (CLI) на основе артефактов обработки (см. TR‑55..TR‑65 и ADR‑0003).
- Допускаются производные артефакты обработки для тематической навигации и выдачи (например, `TopicCard` и `TopicBundle`), формируемые на базе `RawTelegramMessage`/`ProcessedDocument` и сохраняемые/отдаваемые дополнительно к основной магистрали.
- Архитектура должна позволять:
  - добавлять новые источники (не только Telegram);
  - менять LLM‑провайдера/модель без изменения хранилища (провайдер выбирается пользователем через конфигурацию; default — облачный провайдер);
  - использовать разные типы баз знаний (SQL, векторные, комбинированные).

## Последствия

- Появляется чёткое разделение ответственности между модулями и агентами.
- Легче тестировать и развивать каждый слой независимо.
- Требуется поддерживать и версионировать контракты между слоями.

## Ссылки

- Выбранный стек (язык/Telegram/LLM/хранилище): `docs/tech-stack.md`
- Частные решения: `docs/adr/0002-telegram-ingestion-approach.md`, `docs/adr/0003-storage-and-indexing.md`, `docs/adr/0004-hexagonal-architecture-and-module-boundaries.md`
