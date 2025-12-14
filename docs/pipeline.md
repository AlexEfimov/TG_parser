# Pipeline – TG_parser

## Общий поток

1. Планировщик выбирает активные источники и режим: backfill (по `history_from/history_to`) или online обновление (см. TR‑3/TR‑9/TR‑11).
2. Модуль Ingestion загружает сообщения, нормализует их в `RawTelegramMessage`, сохраняет raw и обновляет курсоры (TR‑7/TR‑10/TR‑14/TR‑18).
3. Модуль Processing формирует `ProcessedDocument` и артефакты тематизации (`TopicCard`/`TopicBundle`) (TR‑21..TR‑45).
4. Слой Access / Export (CLI) формирует и выгружает `KnowledgeBaseEntry` (TR‑55..TR‑65).

## Шаги подробно

### 1. Планировщик
- Триггеры: периодический запуск, ручной запуск.
- Единица планирования: **источник/канал** (см. TR‑11/TR‑14).
- Идемпотентность и возобновляемость обеспечиваются **курсорным состоянием ingestion** в `ingestion_state.sqlite` (TR‑14/TR‑17):
  - по постам: high‑watermark `last_post_id` (TR‑7);
  - по комментариям (если включены): per‑post курсор `thread_id -> last_comment_id` (TR‑7/TR‑15).

### 2. Ingestion (Telegram)
- Используемый клиент Telegram: **Telethon (MTProto)** (см. `docs/adr/0002-telegram-ingestion-approach.md` и `docs/tech-stack.md`).
- Учёт лимитов API и ретраи при ошибках.
- Дедупликация сообщений и нормализация временных меток.
- Результат: список `RawTelegramMessage`.
- Правило атомарности (TR‑10): `last_post_id` и `last_comment_id` обновляются **только после успешной записи** соответствующих raw‑данных (чтобы курсор не “проскакивал” вперёд при ошибке).

### 3. Processing (LLM)
- Предобработка текста: очистка, нормализация, детекция языка.
- Вызовы **облачного LLM** (провайдер выбирается пользователем через конфигурацию: `LLM_PROVIDER`, default `openai`; см. `docs/tech-stack.md`) для:
  - классификации по темам;
  - извлечения сущностей;
  - генерации краткого описания.
- Формирование `ProcessedDocument` по схеме.
- Воспроизводимость (TR‑23/TR‑38/TR‑39/TR‑40): в `ProcessedDocument.metadata` фиксируются `pipeline_version`, `model_id`, `prompt_id` и параметры генерации (например `temperature=0` по умолчанию).

### 4. Storage
- На MVP результаты хранятся в отдельных SQLite‑файлах (TR‑17/TR‑42):
  - `raw_storage.sqlite` — raw (уникальность по `source_ref`, TR‑18);
  - `processing_storage.sqlite` — `ProcessedDocument`/`TopicCard`/`TopicBundle` (TR‑42..TR‑45).
- Дальнейший слой **Access / Export** в MVP — CLI‑экспорт (TR‑55..TR‑64); отдельный поисковый индекс не обязателен.

## Взаимодействие с другими системами

- Источники: Telegram‑каналы (публичные или с доступом).
- Потребители: сервисы, использующие базу знаний (поиск, аналитика, ассистенты).

## Связанные документы

- Архитектура: `docs/architecture.md`
- ADR: `docs/adr/0002-telegram-ingestion-approach.md`, `docs/adr/0003-storage-and-indexing.md`
- Технические требования: `docs/technical-requirements.md`
- Стек технологий: `docs/tech-stack.md`
