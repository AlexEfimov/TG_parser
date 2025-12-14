# Pipeline – TG_parser

## Общий поток

1. Планировщик выбирает активные источники и режим: backfill (по `history_from/history_to`) или online обновление (см. TR‑3/TR‑9/TR‑11).
2. Модуль Ingestion загружает сообщения, нормализует их в `RawTelegramMessage`, сохраняет raw и обновляет курсоры (TR‑7/TR‑10/TR‑14/TR‑18).
3. Модуль Processing формирует `ProcessedDocument` и артефакты тематизации (`TopicCard`/`TopicBundle`) (TR‑21..TR‑45).
4. Слой Access / Export (CLI) формирует и выгружает `KnowledgeBaseEntry` (TR‑55..TR‑65).

## Точки входа (CLI, MVP)

Интерфейс продукта в MVP — CLI (TR‑44/TR‑55..TR‑64). Минимальный набор команд (концептуально):
- `ingest` — сбор raw (посты, опционально комментарии) в `raw_storage.sqlite`.
- `process` — обработка raw → `ProcessedDocument` в `processing_storage.sqlite`.
- `topicize` — тематизация `ProcessedDocument` → `TopicCard`/`TopicBundle` в `processing_storage.sqlite`.
- `export` — формирование экспортных артефактов (`topics.json`, `topic_<topic_id>.json`, `kb_entries.ndjson`).
- `run` (опционально one-shot) — последовательный запуск нескольких шагов за одну команду (TR‑44).

### Минимальный контракт флагов CLI (MVP)

Флаги определяются требованиями TR‑44/TR‑60/TR‑62/TR‑64 и фиксируются здесь как “контракт UX”:

- Общие (для большинства команд):
  - `--channel` (обязателен там, где операция scoped на канал; TR‑44/TR‑60)
  - `--dry-run` (где применимо; TR‑44)
  - `--force` (для processing/topicization, где допустима переобработка; TR‑44/TR‑46/TR‑49)
  - `--out` (директория вывода экспортов/отчётов; TR‑60)

- Topicization:
  - `--max-topics` (по умолчанию без лимита; TR‑44/TR‑37)

- Export:
  - `--format json|ndjson` (TR‑60)
  - `--pretty` (для JSON; TR‑60)
  - `--include-supporting` (default `true`; TR‑60/TR‑64)
  - `--topic-id` (ограничение экспортом одной темой; TR‑56/TR‑60/TR‑62)
  - `--from/--to` (фильтры по времени сообщения `RawTelegramMessage.date`; TR‑60/TR‑62)

### Семантика идемпотентности команд (MVP)

Ожидаемое поведение повторного запуска:

- `ingest`:
  - идемпотентность raw обеспечивается ключом `source_ref` (TR‑18/TR‑IF‑5);
  - курсоры обновляются только после успешной записи raw (TR‑10);
  - raw snapshot не перезаписывается “тихо” (TR‑8).
- `process`:
  - по умолчанию инкрементально обрабатывает только raw без processed (TR‑46/TR‑48);
  - хранит одно актуальное состояние `ProcessedDocument` на `source_ref` (TR‑22);
  - `--force` перезаписывает processed и обновляет `processed_at` (TR‑49).
- `topicize`:
  - пересборка по умолчанию охватывает всю доступную историю канала (TR‑30);
  - `TopicCard` upsert по `id` (детерминированный id, TR‑IF‑4);
  - `TopicBundle` upsert по `topic_id` (TR‑43) / snapshot‑режим допускается при `time_range` (TR‑IF‑5).
- `export`:
  - детерминированный порядок вывода (TR‑63);
  - `--include-supporting=false` исключает supporting‑элементы (TR‑64);
  - `--topic-id` ограничивает экспорт темой и сообщениями из её bundle (TR‑62).

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
- Правило snapshot (TR‑8): при совпадающем `source_ref` raw‑запись не должна “тихо” перезаписывать `text/date`; изменения фиксируются отдельными тех. признаками и/или через явный процесс переобработки.

### 3. Processing (LLM)
- Предобработка текста: очистка, нормализация, детекция языка.
- Вызовы **облачного LLM** (провайдер выбирается пользователем через конфигурацию: `LLM_PROVIDER`, default `openai`; см. `docs/tech-stack.md`) для:
  - классификации по темам;
  - извлечения сущностей;
  - генерации краткого описания.
- Формирование `ProcessedDocument` по схеме.
- Воспроизводимость (TR‑23/TR‑38/TR‑39/TR‑40): в `ProcessedDocument.metadata` фиксируются `pipeline_version`, `model_id`, `prompt_id` и параметры генерации (например `temperature=0` по умолчанию).
- Идемпотентность (TR‑22): `ProcessedDocument` хранится как одно “актуальное” состояние на `source_ref` (upsert/replace).
- Инкрементальность (TR‑46/TR‑48): по умолчанию обрабатываются только raw без соответствующего processed; `--force` допускает переобработку.

### 3a. Topicization (формирование тем, stage II)

Topicization выделяется как отдельная операция этапа II (TR‑27..TR‑37):
- Вход: набор `ProcessedDocument` выбранного канала (по умолчанию — вся доступная история, TR‑30).
- Выход: каталог тем `TopicCard` и “всё по теме” `TopicBundle`.
- Детерминизм (TR‑32, TR‑IF‑4):
  - anchors для cluster выбираются как top‑N по score (tie‑break по `anchor_ref`);
  - `TopicCard.id = "topic:" + anchors[0].anchor_ref`;
  - `TopicBundle` в MVP upsert по `topic_id` (TR‑43).
- Метрики и отчёт (TR‑50/TR‑51): по каждой пересборке формируется `topicization_run_id` и JSON‑отчёт.

#### Алгоритм topicization/скоринг (MVP, LLM‑подход)

Для MVP реализуем topicization через **LLM‑подход** (см. `docs/tech-stack.md`: облачный LLM, default OpenAI) при соблюдении требований детерминизма (TR‑32/TR‑38/TR‑IF‑4).

**Семантика score (0..1):**
- `score` — оценка “якорности/релевантности” материала к теме в шкале 0..1.
- `score` используется для:
  - выбора top‑N anchors в cluster‑темах (TR‑IF‑4),
  - включения supporting‑элементов в bundle по порогу (TR‑36),
  - детерминированной сортировки при экспорте (TR‑63).

**Параметры детерминизма:**
- LLM вызывается с параметрами, минимизирующими стохастику (например `temperature=0`) и фиксируется в `metadata.parameters` (TR‑38).
- В `TopicCard.metadata` и `TopicBundle.metadata` фиксируются: `topicization_run_id`, `pipeline_version`, `model_id`, `prompt_id`, `prompt_name`, `algorithm`, `parameters`, `input_scope` (TR‑34/TR‑39/TR‑40).

**Шаги алгоритма (high-level, но реализуемо):**

1) **Подготовка корпуса**
   - Берём все `ProcessedDocument` выбранного канала (TR‑30).
   - Исключение шума/фильтрация (если реализована) должна быть детерминированной и параметризуемой; параметры фиксируются в `metadata.parameters`.

2) **Выбор кандидатов в якоря (anchor candidates)**
   - Формируем список кандидатов из processed документов (включая комментарии, если они есть).
   - Для каждого кандидата вычисляем `anchor_ref = source_ref` в формате `tg:<channel_id>:<message_type>:<message_id>` (TR‑IF‑4/TR‑IF‑5).

3) **Генерация тем (каталог)**
   - LLM получает батч/выборку кандидатов и генерирует набор тем в режиме UC‑4b (“темы неизвестны”), допускающий:
     - `singleton`‑тему (один сильный якорный материал, TR‑31),
     - `cluster`‑тему (несколько якорей).
   - Для каждой темы LLM возвращает:
     - `type` (`singleton|cluster`),
     - набор anchors с `anchor_ref` и `score`,
     - человекочитаемые поля `title`, `summary`, `scope_in`, `scope_out`, опционально `tags`.

4) **Нормализация и детерминизация anchors (обязательное правило)**
   - Удаляем дубликаты anchors по `anchor_ref` (см. примечание TR‑204).
   - Для cluster‑тем:
     - сортируем anchors по `(score desc, anchor_ref asc)` и берём top‑N (рекомендуемо N=3, TR‑IF‑4),
     - primary anchor = `anchors[0]`,
     - `TopicCard.id = "topic:" + anchors[0].anchor_ref`.
   - Для singleton‑тем:
     - `anchors` содержит ровно один primary anchor (или несколько, но primary = `anchors[0]`; рекомендация MVP — 1),
     - `TopicCard.id` строится по тому же правилу.

5) **Применение критериев качества (MVP)**
   - `singleton` допускается только если:
     - длина `ProcessedDocument.text_clean` primary anchor ≥ 300 символов (TR‑35),
     - `anchors[0].score >= 0.75` (TR‑35).
   - `cluster`‑тема:
     - минимум 2 anchors (контракт `TopicCard` + TR‑35),
     - якоря в top‑N удовлетворяют `score >= 0.6` (TR‑35).
   - Пороги параметризуются и фиксируются в `TopicCard.metadata.parameters` (TR‑35).

6) **Формирование TopicBundle (“всё по теме”)**
   - `TopicBundle.items` начинается с anchors темы (TR‑36): каждый anchor включается как item с `role="anchor"`.
   - Дальше LLM (или детерминированная эвристика с LLM‑оценкой) присваивает каждому материалу канала релевантность к теме и формирует supporting‑items:
     - включаем supporting‑элементы при `score >= 0.5` (TR‑36, параметризуемо),
     - `justification` для supporting опционален, но рекомендуется (TR‑53).
   - Дедуп `TopicBundle.items` по `source_ref` (TR‑36).
   - Upsert TopicBundle по `topic_id` (MVP, TR‑43).

7) **Детерминизация результатов**
   - Порядок `TopicBundle.items` и экспортов должен быть детерминированным (TR‑63).
   - Параметры, влияющие на результат (top‑N, thresholds, лимиты, стратегия батчинга), фиксируются в metadata.

Рекомендуемое значение `algorithm` в metadata: `llm_topicization_v1`.

### 4. Storage
- На MVP результаты хранятся в отдельных SQLite‑файлах (TR‑17/TR‑42):
  - `raw_storage.sqlite` — raw (уникальность по `source_ref`, TR‑18);
  - `processing_storage.sqlite` — `ProcessedDocument`/`TopicCard`/`TopicBundle` (TR‑42..TR‑45).
- Дальнейший слой **Access / Export** в MVP — CLI‑экспорт (TR‑55..TR‑64); отдельный поисковый индекс не обязателен.

## Ошибки и ретраи (MVP)

Источник истины: TR‑12/TR‑13 (ingestion) и TR‑47 (processing).

### Ingestion retry policy

- Классы ошибок:
  - retryable: сетевые ошибки/таймауты/rate limit/5xx → ретраи с экспоненциальным backoff + jitter (TR‑12)
  - non‑retryable: нет доступа/неверные креды/канал недоступен → перевод источника в `error` до ручного вмешательства (TR‑12)
- Параметры по умолчанию за один запуск ingestion (TR‑13):
  - `max_attempts_per_run = 5`
  - backoff: 1s, 2s, 4s, 8s, 16s; jitter 0–30%
  - после исчерпания попыток: фиксировать `last_error`, `last_attempt_at`, увеличивать `fail_count` и переводить источник в `error`

### Processing retry policy

- Ошибка на одном сообщении не должна “ронять” весь запуск (TR‑47): фиксируем ошибку и продолжаем.
- Параметры по умолчанию (TR‑47):
  - `max_attempts_per_message = 3`
  - backoff: 1s, 2s, 4s; jitter 0–30%
- По исчерпанию попыток должна сохраняться запись о неудачной обработке (минимум: `source_ref`, класс/текст ошибки, attempts, `last_attempt_at`) (TR‑47).
- Рекомендуемое место хранения записи: `processing_storage.sqlite.processing_failures` (см. `docs/architecture.md`, раздел “Целевая минимальная схема таблиц (SQLite, MVP)”).

## Артефакты, которые производит пайплайн (MVP)

Хранилища (внутренние артефакты):
- `ingestion_state.sqlite` — конфигурация источников, статусы, курсоры (TR‑14/TR‑15/TR‑17).
- `raw_storage.sqlite` — `RawTelegramMessage` (TR‑18..TR‑20).
- `processing_storage.sqlite` — `ProcessedDocument` + `TopicCard` + `TopicBundle` (TR‑42..TR‑45).

Экспорты (артефакты для потребителей, TR‑55..TR‑64):
- `topics.json` — список `TopicCard` по каналу.
- `topic_<topic_id>.json` — объект `{topic_card, topic_bundle, resolved_sources, exported_at, export_version}` (TR‑59).
- `kb_entries.ndjson` — поток `KnowledgeBaseEntry` (message‑entries и/или topic‑entries) по правилам TR‑57/TR‑61.

## Артефакты наблюдаемости (MVP)

Согласно TR‑50/TR‑51, каждый запуск processing/topicization должен производить отчёт (JSON) и/или логировать ключевые метрики:
- processing run: `processing_run_id`, `channel_id`, `processed_total`, `skipped_total`, `failed_total`, `duration_seconds`
- topicization run: `topicization_run_id`, `channel_id`, `topics_total`, `singleton_topics_total`, `cluster_topics_total`, `bundles_total`, `covered_items_total`, `outside_topics_total`

Рекомендуется сохранять отчёты рядом с экспортом или в отдельную директорию “runs/” с детерминированными именами файлов по `*_run_id`.

## Версионирование и идентификаторы запусков (MVP)

Источник истины: TR‑23/TR‑38/TR‑39/TR‑40/TR‑50/TR‑51.

### `pipeline_version` (обязательно)

Для воспроизводимости результаты processing/topicization обязаны фиксировать версию в `metadata.pipeline_version`:
- формат: `<stage>:vX.Y.Z` (TR‑39)
- примеры:
  - `processing:v1.0.0`
  - `topicization:v1.0.0`

При изменении промптов/моделей/порогов/алгоритмов, влияющих на результат, версия должна быть увеличена (TR‑39).

### `prompt_id` (обязательно для LLM)

`prompt_id` должен быть однозначно связан с текстом промпта, формат рекомендуется: `sha256:<...>` (TR‑40).
Дополнительно сохраняется `prompt_name` для удобства анализа (TR‑40).

### `export_version` (для экспортных файлов)

Экспорт должен включать `export_version` (как минимум в `topic_<topic_id>.json`, TR‑59) в формате:
- `export:vX.Y.Z`

### `*_run_id` (processing/topicization)

Каждый запуск processing/topicization генерирует уникальный идентификатор:
- `processing_run_id` / `topicization_run_id`
- требования:
  - уникальность в пределах проекта;
  - сортируемость по времени **желательна** (упрощает анализ).

Рекомендуемый формат: **ULID** (строка), либо ISO‑timestamp + короткий suffix.

### Формат JSON‑отчёта запуска (рекомендуемый минимум)

Помимо метрик TR‑50/TR‑51, отчёт рекомендуется расширять полями:
- `started_at`, `finished_at` (ISO date-time)
- `pipeline_version`
- `parameters` (JSON): параметры CLI/порогов/режимов (`--channel`, `--force`, `--max-topics`, thresholds…)
- `git_commit` (опционально): SHA текущего коммита, если доступно

### Имена файлов отчётов

Рекомендуемое именование:
- `runs/processing_<processing_run_id>.json`
- `runs/topicization_<topicization_run_id>.json`

## Резолюция Telegram URL и `resolved_sources` (MVP)

Источник истины: TR‑58..TR‑65.

### Алгоритм `telegram_url` (best-effort)

CLI‑экспорт строит человекочитаемые ссылки на первоисточник Telegram по правилам:

1) Если известен `channel_username` (например, хранится в `ingestion_state.sqlite.sources.channel_username`), то:
- `telegram_url = "https://t.me/<channel_username>/<message_id>"`

2) Иначе, если `channel_id` имеет вид `-100...` (например `-1001234567890`), то:
- `internal_id = channel_id` без префикса `-100`
- `telegram_url = "https://t.me/c/<internal_id>/<message_id>"`

3) Иначе, если `channel_id` уже является публичным именем/юзернеймом канала (best-effort). Рекомендуемое эвристическое правило для MVP:
- `channel_id` не начинается с `-` и
- `channel_id` матчится на `^[A-Za-z0-9_]{5,}$`

то:
- `telegram_url = "https://t.me/<channel_id>/<message_id>"`

4) Иначе:
- `telegram_url = null`

Во всех случаях, даже если URL не построен, экспорт обязан сохранять исходные идентификаторы: `channel_id`, `message_id`, `message_type`, `source_ref` (TR‑58/TR‑65).

Примечания:
- `message_id` берётся из `RawTelegramMessage.id`/`ProcessedDocument.source_message_id` и хранится строкой.
- Ссылка на комментарий формируется так же, как на пост: по его `message_id` (Telegram сам отображает контекст в треде).

### `resolved_sources[]` в экспорте темы

Экспорт `topic_<topic_id>.json` должен включать таблицу резолюции источников `resolved_sources[]` (TR‑59) для **всех** материалов, встречающихся в:
- `TopicCard.anchors[]` и
- `TopicBundle.items[]`.

Правила:
- дедупликация по `source_ref` (это ключ материала в системе, TR‑IF‑5);
- для каждого `source_ref` вычисляются/переносятся:
  - `source_ref`, `channel_id`, `message_id`, `message_type`
  - `telegram_url` (best-effort по алгоритму выше)
  - опционально: `role`, `score`, `justification` (если доступно из bundle/item или anchors)
- порядок `resolved_sources[]` должен быть детерминированным (например по `source_ref`).

### Слияние (merge) данных для одного `source_ref`

Если один и тот же `source_ref` встречается одновременно:
- в `TopicCard.anchors[]` (якорь темы) и
- в `TopicBundle.items[]` (элемент подборки),

то `resolved_sources[]` должен содержать **одну** запись для этого `source_ref` со следующими правилами merge:

- **role**:
  - если материал является anchor (присутствует в `TopicCard.anchors[]`) → `role="anchor"`;
  - иначе, если присутствует только в `TopicBundle.items[]` → `role` берётся из bundle item (`anchor|supporting` по контракту `TopicBundle`).
- **score**:
  - если `role="anchor"` и score есть у anchor → использовать anchor score;
  - иначе, если score есть у bundle item → использовать bundle score;
  - иначе score отсутствует.
- **justification**:
  - заполняется только из `TopicBundle.items[].justification` (если есть);
  - для `role="anchor"` justification обычно отсутствует (и не требуется).

Эти правила обеспечивают детерминизм и согласуются с TR‑36 (формирование bundle из anchors + supporting).

### Детерминированная сортировка `resolved_sources[]`

Рекомендуемая сортировка (для стабильного экспорта и диффов):
1) `role` (anchor сначала, затем supporting),
2) `score` по убыванию (null/отсутствующие score — в конце внутри role),
3) `source_ref` по возрастанию (tie‑break).

## Детерминизм вывода (MVP)

Для воспроизводимости и стабильных диффов экспорт должен быть упорядочен детерминированно (TR‑63):
- `topics.json` сортируется по `TopicCard.id`;
- при экспорте темы `TopicBundle.items` сортируется детерминированно (например `(role desc, score desc, source_ref asc)`);
- `kb_entries.ndjson` выводится в детерминированном порядке (например по `KnowledgeBaseEntry.id`).

## Взаимодействие с другими системами

- Источники: Telegram‑каналы (публичные или с доступом).
- Потребители: сервисы, использующие базу знаний (поиск, аналитика, ассистенты).

## Связанные документы

- Архитектура: `docs/architecture.md`
- ADR: `docs/adr/0002-telegram-ingestion-approach.md`, `docs/adr/0003-storage-and-indexing.md`, `docs/adr/0004-hexagonal-architecture-and-module-boundaries.md`
- Технические требования: `docs/technical-requirements.md`
- Стек технологий: `docs/tech-stack.md`
