# TG_parser

TG_parser — система, которая собирает контент из Telegram‑каналов, обрабатывает его с участием ИИ и предоставляет результаты в виде экспортируемых артефактов (MVP: CLI‑экспорт файлов).

## Документация

- **Архитектура**: `docs/architecture.md`
- **Пайплайн**: `docs/pipeline.md`
- **Требования**: `docs/business-requirements.md`, `docs/technical-requirements.md`
- **Стек**: `docs/tech-stack.md`
- **Контракты данных**: `docs/contracts/*.schema.json`
- **ADR**: `docs/adr/`

## Ключевая идея MVP

Данные проходят через фиксированную магистраль контрактов:

`RawTelegramMessage` → `ProcessedDocument` → (`TopicCard`/`TopicBundle`) → export → `KnowledgeBaseEntry`

А доступ внешних потребителей в MVP обеспечивается через CLI‑экспорт (`topics.json`, `topic_<topic_id>.json`, `kb_entries.ndjson`).
