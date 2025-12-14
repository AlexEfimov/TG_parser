## План реализации TG_parser (MVP) на основе документации

### 0) Цель и границы
- **Цель MVP**: реализовать CLI‑пайплайн, который проходит магистраль
  `RawTelegramMessage` → `ProcessedDocument` → (`TopicCard`/`TopicBundle`) → export → `KnowledgeBaseEntry`.
- **Интерфейс продукта в MVP**: только CLI (без HTTP API) — см. `docs/pipeline.md`, TR‑55..TR‑64.
- **Архитектурные ограничения (обязательные)**:
  - Hexagonal/Clean (ADR‑0001, ADR‑0004): домен не зависит от инфраструктуры; бизнес‑логика зависит от портов.
  - SQLite‑MVP с **3 файлами** (TR‑14/TR‑17/TR‑42, ADR‑0003): `ingestion_state.sqlite`, `raw_storage.sqlite`, `processing_storage.sqlite`.
  - Ключ идемпотентности материала — **`source_ref`** (TR‑IF‑5); детерминированные id (TR‑41, TR‑IF‑4, TR‑61).
- **Вне скоупа MVP** (пока): серверный режим, PostgreSQL миграции, полнотекст/векторный поиск, скачивание медиа (TR‑19).

### 1) Аудит текущего кода и целевая структура пакетов
Текущий skeleton содержит только протоколы и dataclass‑модели, которые **не совпадают** с контрактами (нет `source_ref`, `message_type`, topic‑моделей и т.д.).

Целевая структура (как в `docs/architecture.md`):
- `tg_parser/domain/` — **Pydantic v2** модели по контрактам + канонизация идентификаторов.
- `tg_parser/config/` — настройки через `pydantic-settings`.
- `tg_parser/storage/` — порты репозиториев + SQLAlchemy 2.x async реализации (SQLite сначала).
- `tg_parser/ingestion/` — порты ingestion + адаптер `ingestion.telegram` (Telethon) + оркестрация backfill/online.
- `tg_parser/processing/` — порты processing + LLM адаптеры + topicization.
- `tg_parser/export/` — сборка экспортных артефактов (topics.json, topic_<id>.json, kb_entries.ndjson).
- `tg_parser/cli/` — Typer команды.

### 2) Зависимости и базовая инфраструктура проекта
- **Добавить/зафиксировать зависимости** в `requirements.txt` (см. `docs/tech-stack.md`):
  - `pydantic>=2`, `pydantic-settings`, `jsonschema`, `httpx`, `typer`, `sqlalchemy[asyncio]`, `aiosqlite`, `telethon`, `structlog`.
  - `pytest`, `ruff` (и при необходимости `mypy`).
- **Единый стиль времени**: ISO 8601 UTC `...Z` при сериализации (см. `docs/architecture.md`).
- **Логирование**: стандартный `logging` + структурирование (TR‑OBS‑1/2, `docs/tech-stack.md`).

### 3) Домен: контракты, модели, идентификаторы, сериализация
**Цель**: привести доменные структуры к `docs/contracts/*.schema.json` (TR‑IF‑1).

#### 3.1 Pydantic‑модели (домен)
Создать/обновить модели:
- `RawTelegramMessage` (включая `id`, `message_type`, `source_ref`, `channel_id`, `date`, `text`, опционально `thread_id`, `parent_message_id`, `language`, `raw_payload`).
- `ProcessedDocument` (включая `id`, `source_ref`, `source_message_id`, `channel_id`, `processed_at`, `text_clean`, опц. `summary`, `topics`, `entities`, `language`, `metadata`).
- `TopicCard` и вложенные `Anchor`.
- `TopicBundle` и вложенные `Item`, опц. `time_range`.
- `KnowledgeBaseEntry` и `KnowledgeBaseEntry.source` (поддержка `telegram_message` и `topic`, см. TR‑57).

#### 3.2 Канонизация и детерминизм id
В `tg_parser/domain/ids.py` (или аналогично) реализовать:
- `make_source_ref(channel_id, message_type, message_id) -> str` в формате `tg:<channel_id>:<message_type>:<id>` (TR‑IF‑5, pattern из схем).
- `make_processed_document_id(source_ref) -> "doc:"+source_ref` (TR‑41).
- `make_topic_id(primary_anchor_ref) -> "topic:"+primary_anchor_ref` (TR‑IF‑4).
- `make_kb_msg_id(source_ref) -> "kb:msg:"+source_ref` и `make_kb_topic_id(topic_id) -> "kb:topic:"+topic_id` (TR‑61).

#### 3.3 Валидация JSON Schema на границах
Добавить утилиту `tg_parser/domain/contract_validation.py`:
- загрузка схем из `docs/contracts/*.schema.json` (путь относительный от repo root) и проверка объектов перед записью/экспортом (TR‑IF‑1).
- применять точечно: перед сохранением в SQLite и перед экспортом.

### 4) Storage слой: порты и SQLite реализации
**Цель**: реализовать минимальные хранилища и инварианты идемпотентности.

#### 4.1 Порты (интерфейсы)
Ввести явные репозитории (Protocols):
- `IngestionStateRepo`: CRUD источников, обновление курсоров, запись попыток (TR‑14/TR‑15).
- `RawMessageRepo`: запись raw по `source_ref` с правилом snapshot (TR‑8/TR‑18/TR‑20).
- `ProcessedDocumentRepo`: upsert по `source_ref` (TR‑22/TR‑43).
- `ProcessingFailureRepo`: upsert “не обработалось” и очистка при успехе (TR‑47).
- `TopicCardRepo`: upsert по `id` (TR‑43).
- `TopicBundleRepo`: upsert “актуальной” подборки по `topic_id` (TR‑43/TR‑IF‑5).

#### 4.2 SQLite DDL и миграции
Реализовать создание таблиц при старте (миграции можно отложить, но DDL должен соответствовать `docs/architecture.md`):
- `ingestion_state.sqlite`: `sources`, `comment_cursors`, `source_attempts`.
- `raw_storage.sqlite`: `raw_messages`, `raw_conflicts`.
- `processing_storage.sqlite`: `processed_documents`, `processing_failures`, `topic_cards`, `topic_bundles`.

Ключевые правила:
- `raw_messages.source_ref` PK; при конфликте — **не перезаписывать** `text/date` (минимум `DO NOTHING`) и при необходимости логировать в `raw_conflicts` (TR‑8).
- processed/topic tables — upsert/replace по ключам из TR‑43.

#### 4.3 JSON поля
Сериализация массивов/metadata в стабильный JSON (для детерминизма экспортов и тестов):
- сортировка ключей, стабильные разделители (или `orjson` опционально).

### 5) Ingestion: Telethon адаптер + оркестрация backfill/online
**Цель**: получить `RawTelegramMessage` и сохранить их с корректными курсорами.

#### 5.1 Конфигурация источников
- Модель `SourceConfig` (channel_id/username?, include_comments, history_from/to, poll_interval, batch_size, статус) в ingestion state (TR‑15).

#### 5.2 Telethon адаптер (async)
- Реализация `TelegramClientPort` / `TelegramIngestor`:
  - fetch posts history/new;
  - опционально fetch comments per post (TR‑5/TR‑7).
- Нормализация связей комментариев (TR‑6):
  - post: `thread_id=id`, `parent_message_id=None`;
  - comment: `thread_id=<root_post_id>`, `parent_message_id=<replied_id or thread_id>`.

#### 5.3 Запись raw + атомарные курсоры
- Для каждого источника: писать raw в `RawMessageRepo`, и **только после успеха** обновлять `last_post_id` / `last_comment_id` (TR‑10).
- Retry/backoff+jitter (TR‑12/TR‑13), статусы `active/paused/error` (TR‑11).
- `raw_payload` ограничивать 256KB (TR‑20): при превышении сохранять “мягко усечённый” объект с признаками `truncated`/`original_size_bytes`.

### 6) Processing (per-message) + LLM адаптер
**Цель**: реализовать 1 raw → 1 processed с инкрементальностью и ретраями.

#### 6.1 LLMClient порт
- Единый интерфейс `LLMClient.generate(...)` с реализациями:
  - default OpenAI через `httpx` (TR‑38, `docs/tech-stack.md`),
  - опционально OpenAI‑compatible (`LLM_BASE_URL`).

#### 6.2 ProcessingPipeline
- Вход: raw сообщения (обычно из `raw_storage.sqlite` по каналу).
- Выход: `ProcessedDocument` (TR‑21..TR‑26):
  - `text_clean` обязателен;
  - `summary` опционален;
  - `topics` опционально/может быть пустым;
  - `language` определяется здесь.
- Идемпотентность (TR‑22/TR‑46/TR‑48):
  - по умолчанию обрабатывать только те `source_ref`, для которых нет processed;
  - `--force` перезаписывает и обновляет `processed_at` (TR‑49).

#### 6.3 Обработка ошибок per-message
- Не валить весь запуск из-за 1 сообщения (TR‑47).
- Ретраи per-message: 3 попытки, backoff 1/2/4s + jitter 0–30% (TR‑47).
- По исчерпанию попыток: запись в `processing_failures`.

#### 6.4 Metadata и версии
- Заполнять `metadata.pipeline_version`, `model_id`, `prompt_id` (sha256), `prompt_name`, `parameters` (TR‑23, TR‑38..TR‑40).

### 7) Topicization (per-channel): TopicCard + TopicBundle
**Цель**: UC‑4b discovered topics с детерминизмом.

#### 7.1 Параметры по умолчанию (MVP)
- `top_n_anchors = 3` (TR‑IF‑4, рекомендуемо),
- thresholds: `singleton_min_len=300`, `singleton_min_score=0.75`, `cluster_min_anchor_score=0.6`, `supporting_min_score=0.5` (TR‑35/TR‑36) — конфигурируемо.

#### 7.2 Детерминизация anchors
- Дедуп anchors по `anchor_ref` (TR примечание про невозможность в JSON Schema).
- Сортировка `(score desc, anchor_ref asc)`; primary anchor = `anchors[0]`.
- `TopicCard.id = "topic:" + anchors[0].anchor_ref` (TR‑IF‑4).

#### 7.3 Формирование TopicBundle
- `items` начинается с anchors (role=`anchor`) (TR‑36).
- Supporting включать при `score>=0.5`, дедуп по `source_ref` (TR‑36).
- Дет. сортировка items для стабильных результатов/экспорта: `(role (anchor first), score desc, source_ref asc)`.

#### 7.4 Run отчёт и метрики
- Генерировать `topicization_run_id` (ULID предпочтительно) и JSON‑отчёт (TR‑50/TR‑51), сохранять в `runs/`.
- Считать `covered_items_total` по уникальным `source_ref` (TR‑52), `outside_topics_total` как `processed_total - covered_items_total`.

### 8) Export (CLI): topics.json, topic_<id>.json, kb_entries.ndjson
**Цель**: слой Access/Export формирует артефакты и `KnowledgeBaseEntry` по TR‑55..TR‑65.

#### 8.1 Telegram URL best-effort
Реализовать функцию `resolve_telegram_url(channel_id, channel_username?, message_id)` по TR‑58/TR‑65 и доп. эвристике из `docs/pipeline.md`:
- username → `https://t.me/<username>/<message_id>`
- `-100...` → `https://t.me/c/<internal_id>/<message_id>`
- иначе, если channel_id похож на username (`^[A-Za-z0-9_]{5,}$` и не начинается с `-`) → `https://t.me/<channel_id>/<message_id>`
- иначе `null`

#### 8.2 topic_<topic_id>.json
- Структура (TR‑59): `{topic_card, topic_bundle, resolved_sources, exported_at, export_version}`.
- `resolved_sources[]`:
  - дедуп по `source_ref`;
  - merge правилен и детерминирован (описано в `docs/pipeline.md`): anchor побеждает по `role/score`, justification только из bundle.

#### 8.3 KnowledgeBaseEntry mapping
По TR‑61:
- message‑entry: `id="kb:msg:"+source_ref`, `created_at=processed_at`, `content=summary+"\n\n"+text_clean` (если summary есть), topics из ProcessedDocument.topics.
- topic‑entry: `id="kb:topic:"+topic_id`, `created_at=TopicCard.updated_at`, `title=TopicCard.title`, `topics=[TopicCard.id]`, `tags=TopicCard.tags`, `metadata.resolved_sources=...`.

#### 8.4 Детерминизм экспорта
- `topics.json` сортировать по `TopicCard.id`.
- `kb_entries.ndjson` — по `KnowledgeBaseEntry.id`.
- Stable JSON pretty/non-pretty (TR‑60/TR‑63).

### 9) CLI (Typer): команды и флаги
Создать `tg_parser/cli/app.py` и команды (см. `docs/pipeline.md`):
- `ingest` (TR‑44): `--channel`, `--dry-run`, `--out?` (для отчётов), режим backfill/online (параметры из ingestion_state).
- `process`: `--channel`, `--force`, `--dry-run`.
- `topicize`: `--channel`, `--max-topics`, `--force?` (если разрешим пересборку), `--dry-run`.
- `export`: `--channel`, `--topic-id`, `--from/--to`, `--format json|ndjson`, `--pretty`, `--include-supporting`, `--out`.
- `run` (опционально one-shot): последовательно `ingest→process→topicize→export`.

### 10) Тестирование (pytest) по testing-strategy + TR
Минимальный набор тестов (обязательные инварианты из `docs/testing-strategy.md`):
- **Unit**:
  - канонизация `source_ref`/`doc:`/`topic:`/`kb:`;
  - детерминированная сортировка anchors/items/resolved_sources;
  - `resolve_telegram_url`.
- **Integration (SQLite)**:
  - raw idempotency (TR‑18) и snapshot (TR‑8);
  - atomic cursor update (TR‑10) через транзакции;
  - processed upsert (TR‑22) и `--force` семантика (TR‑49);
  - topicization determinism (TR‑IF‑4/TR‑32) на фиксированном наборе входов;
  - export determinism (TR‑63) и include-supporting (TR‑64).
- **E2E (опционально)**: с заглушкой Telegram и mock LLM (без реальных сетевых вызовов).

### 11) Пошаговые этапы реализации (милestones)
1) **Domain + contracts**: Pydantic‑модели, id‑утилиты, JSON schema validation.
2) **Storage (SQLite)**: репозитории + DDL + стабильная JSON‑сериализация.
3) **Export слой**: резолюция URL, формирование всех экспортов и KB entries.
4) **Processing**: LLMClient порт + mock реализация, инкрементальность, ретраи, failures.
5) **Topicization**: детерминизация anchors/items, метрики/отчёты.
6) **Ingestion**: state repo, Telethon адаптер, backfill/online, курсоры, ретраи.
7) **CLI**: команды и wiring портов/адаптеров.
8) **Тесты и стабилизация**: покрытие инвариантов, ruff.

### 12) Риски и меры
- **Детерминизм LLM**: даже при `temperature=0` возможны вариации; минимизация через строгие схемы вывода, фиксированные промпты, сохранение prompt_id/pipeline_version, при необходимости — локальные эвристики для сортировок/порогов.
- **Формат `source_ref`**: схема запрещает двоеточия в компонентах; при реальных id с нестандартными символами потребуется экранирование/кодирование (см. примечание TR‑204).
- **Telegram доступ/лимиты**: Telethon требует user session; нужна аккуратная обработка rate limit и прав доступа (TR‑12).

### 13) Критерии готовности MVP
- CLI команды `ingest/process/topicize/export` работают на одном канале и создают ожидаемые артефакты.
- Соблюдены инварианты: TR‑8/TR‑10/TR‑18/TR‑22/TR‑41/TR‑IF‑4/TR‑61/TR‑63.
- Тесты из раздела 10 покрывают ключевые инварианты и проходят локально.
