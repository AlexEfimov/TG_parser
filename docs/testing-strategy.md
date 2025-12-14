# Стратегия тестирования TG_parser

## Уровни тестов

- Unit‑тесты
  - Парсинг и нормализация Telegram‑сообщений.
  - Преобразования текста до/после LLM.
  - Локальная логика хранения (без реального хранилища).
  - Канонизация идентификаторов и ключей идемпотентности (`source_ref`, `doc:`/`topic:`/`kb:`).

- Интеграционные тесты
  - Ingestion ↔ Telegram‑клиент (c использованием заглушек/фикстур).
  - Processing ↔ Storage (проверка формирования и upsert `ProcessedDocument`, `TopicCard`, `TopicBundle` в `processing_storage.sqlite`).
  - Access / Export ↔ Артефакты (проверка правил маппинга артефактов в `KnowledgeBaseEntry` на этапе CLI‑экспорта: `kb_entries.ndjson`, `topics.json`, `topic_<topic_id>.json`).

- E2E‑тесты
  - От тестового канала Telegram до появления результата в экспортируемых артефактах (например `kb_entries.ndjson` и/или `topics.json`), т.е. “до KnowledgeBaseEntry на экспорте” (см. TR‑55..TR‑65).

## Инварианты, которые обязаны проверяться тестами (MVP)

Источник истины: TR‑IF‑* и раздел “Целевая минимальная схема таблиц (SQLite, MVP)” в `docs/architecture.md`.

- **Идемпотентность raw** (TR‑18/TR‑8):
  - повторный ingestion одного и того же материала не создаёт дублей (`raw_messages.source_ref` уникален);
  - “raw snapshot” не перезаписывается “тихо” (минимум: `ON CONFLICT DO NOTHING`).
- **Атомарность курсоров ingestion** (TR‑10):
  - курсоры обновляются только после успешной записи raw;
  - при падении записи raw курсор не “проскакивает” вперёд.
- **Идемпотентность processing** (TR‑22):
  - `processed_documents` содержит одно актуальное состояние на `source_ref` (upsert/replace).
- **Детерминизм идентификаторов**:
  - `ProcessedDocument.id = "doc:" + source_ref` (TR‑41);
  - `TopicCard.id = "topic:" + anchors[0].anchor_ref` (TR‑IF‑4);
  - `KnowledgeBaseEntry.id` детерминирован правилами TR‑61.
- **Детерминизм topicization** (TR‑IF‑4/TR‑32):
  - anchors в cluster выбираются как top‑N по score с tie‑break по `anchor_ref`;
  - повторная тематизация на тех же входах даёт тот же `TopicCard.id` и тот же порядок anchors/items.
- **Детерминизм экспорта** (TR‑63):
  - стабильная сортировка `topics.json`, `TopicBundle.items`, `kb_entries.ndjson`.
- **Резолюция `telegram_url` (best-effort)** (TR‑58/TR‑65):
  - при наличии `channel_username` формируется `https://t.me/<username>/<message_id>`;
  - при `channel_id` вида `-100...` формируется `https://t.me/c/<internal_id>/<message_id>`;
  - иначе, если `channel_id` выглядит как публичный юзернейм (эвристика MVP: `channel_id` не начинается с `-` и матчится на `^[A-Za-z0-9_]{5,}$`), формируется `https://t.me/<channel_id>/<message_id>` (best-effort);
  - иначе `telegram_url = null`;
  - в экспорте всегда присутствуют исходные идентификаторы (`channel_id`, `message_id`, `message_type`, `source_ref`).
- **Детерминизм `resolved_sources[]`** (TR‑59, правила `docs/pipeline.md`):
  - при пересечении anchors и bundle items один `source_ref` даёт ровно одну запись в `resolved_sources[]`;
  - merge правилен и детерминирован: anchor “побеждает” по `role` и `score`, `justification` берётся только из bundle item;
  - порядок `resolved_sources[]` детерминирован (anchor-first, затем score desc, затем `source_ref` asc).
- **Ретраи и классификация ошибок** (TR‑12/TR‑13/TR‑47):
  - ingestion корректно различает retryable/non‑retryable и применяет backoff+jitter;
  - processing не падает целиком из‑за одного сообщения и ограничивает ретраи per-message.
  - при исчерпании ретраев per-message создаётся/обновляется запись о неудаче (рекомендуемо: `processing_failures`), а при успешной обработке она исчезает/помечается resolved.

## Тестовые данные

- Набор сырых сообщений (разные языки, форматы, длины, вложения).
- Размеченный небольшой датасет для оценки качества извлечённой информации.

## Метрики качества (MVP)

- Корректность базовых полей (канал, дата, id, текст).
- Точность выделения темы/категории.
- Доля успешно обработанных сообщений без ошибок пайплайна.


