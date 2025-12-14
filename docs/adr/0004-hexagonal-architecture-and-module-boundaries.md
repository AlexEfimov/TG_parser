# ADR 0004 – Hexagonal/Clean архитектура и границы модулей

## Статус
Accepted

## Контекст

ADR‑0001 зафиксировал разбиение на слои (Ingestion / Processing / Storage / Access-Export) и обязательные контракты обмена (`RawTelegramMessage` → `ProcessedDocument` → производные артефакты → экспорт в `KnowledgeBaseEntry`).

Для реализации MVP и последующей эволюции (SQLite → PostgreSQL, CLI → API) нужно дополнительно зафиксировать:
- границы модулей в коде;
- правило зависимостей между слоями (кто от кого зависит);
- принцип “портов и адаптеров” для Telegram/LLM/DB/CLI, чтобы смена провайдера/хранилища не требовала переписывания доменной логики (см. ADR‑0001 и ADR‑0003).

## Решение

Принять архитектурный стиль **Hexagonal / Clean Architecture** поверх слоёв ADR‑0001:

1) **Домен (центр)**:
- доменные модели (Pydantic) строго соответствуют JSON‑контрактам из `docs/contracts/*.schema.json`;
- доменные идентификаторы и ключи идемпотентности детерминированы требованиями TR‑IF‑* и схемами (например `source_ref`, `ProcessedDocument.id = "doc:" + source_ref`, `TopicCard.id = "topic:" + anchors[0].anchor_ref`).

2) **Порты (интерфейсы)**:
- определяются интерфейсы репозиториев и сервисов:
  - ingestion: “ингестор Telegram”, “ingestion state repo”, “raw storage repo”;
  - processing: “processor”, “processed storage repo”, “LLM client”;
  - topicization: “topicizer” (внутри processing stage II);
  - access/export: “exporter” (формирует артефакты экспорта).

3) **Адаптеры (реализации портов)**:
- Telegram: адаптер Telethon (MTProto), инкапсулирован внутри `ingestion.telegram`.
- LLM: адаптеры провайдеров (default OpenAI) за единым интерфейсом `LLMClient` (провайдер выбирается конфигурацией).
- Storage: реализации репозиториев на SQLAlchemy async:
  - MVP: SQLite (3 файла);
  - later: PostgreSQL, без изменения портов и доменных контрактов.
- CLI: единственная точка входа MVP, оркестрирует вызовы портов.

4) **Правило зависимостей**:
- домен не зависит от инфраструктуры;
- бизнес-логика ingestion/processing/topicization/export зависит только от домена и портов;
- адаптеры зависят от домена и портов, но не наоборот.

## Последствия

- Смена Telegram‑клиента/LLM‑провайдера/СУБД выполняется заменой адаптера при неизменных контрактах и портах.
- Тестирование упрощается: бизнес-логику можно покрывать тестами через in-memory/fake адаптеры.
- Требуется дисциплина: любые изменения форматов/инвариантов должны сначала фиксироваться в контрактах/ADR и сопровождаться тестами (TR‑IF‑2).

## Ссылки

- ADR‑0001: `docs/adr/0001-overall-architecture.md`
- ADR‑0002: `docs/adr/0002-telegram-ingestion-approach.md`
- ADR‑0003: `docs/adr/0003-storage-and-indexing.md`
- Архитектура: `docs/architecture.md`
- Pipeline: `docs/pipeline.md`
- Технические требования: `docs/technical-requirements.md`

