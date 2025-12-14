# Технические требования TG_parser (MVP)

## 1. Требования по этапам

### 1.1 Общие (сквозные)

- TR‑1: Система должна поддерживать Python 3.12 и запускаться в изолированной виртуальной среде (`.venv`).
- TR‑2: Система должна быть способна обрабатывать несколько Telegram‑каналов параллельно.
- TR‑3: Должен быть предусмотрен режим исторического прогона (backfill) и режим регулярного обновления.

### 1.2 Этап I — Ingestion + Raw storage (UC‑1/UC‑2/UC‑3)
- TR‑4: Система должна поддерживать сбор и обработку как постов, так и связанных комментариев (если они доступны источнику), с сохранением связей comment → parent/thread.
- TR‑5: Сбор комментариев должен включаться **опционально на уровне источника** (параметр источника, например `include_comments: true/false`) для управления объёмом и стоимостью обработки, при сохранении поддержки комментариев как функции системы (FR‑5).
- TR‑6 (связи комментариев): система должна обеспечивать детерминированную семантику связей в raw:
  - для `message_type="post"`: `parent_message_id` отсутствует; `thread_id = id`;
  - для `message_type="comment"`: `thread_id` равен id корневого поста обсуждения; `parent_message_id` равен id сообщения, на которое отвечает комментарий (если reply недоступен — допускается `parent_message_id = thread_id`).
- TR‑7 (checkpoint’ы ingestion): система должна хранить прогресс/offset по каждому источнику так, чтобы поддерживать backfill и online режим без дублей:
  - для постов — high‑watermark `last_post_id`;
  - для комментариев (если включены) — курсор **per‑post** (например `last_comment_id` для каждого поста/треда).
- TR‑8 (редактирование/удаление источника): raw‑хранилище рассматривается как снимок на момент ingestion; при повторном сборе не допускается “тихая” перезапись `text/date` уже сохранённого raw‑сообщения с тем же `source_ref`. Изменения/удаления должны отражаться отдельными техническими признаками (например в `raw_payload`/доп. полях) и/или через явный процесс переобработки.
- TR‑9 (параметры backfill/online на источник): для каждого источника должны поддерживаться параметры периода backfill `history_from/history_to` (ISO date-time) и параметры регулярного обновления (например `poll_interval`, `batch_size`).
- TR‑10 (атомарность обновления курсоров): `last_post_id` и per‑post `last_comment_id` должны обновляться только после успешной записи соответствующих raw‑данных. При ошибке запись курсора не должна “проскочить” вперёд (чтобы исключить потери и дубли при повторном запуске).
- TR‑11 (статусы источников): система должна поддерживать минимальные статусы источника `active` / `paused` / `error` и сохранять историю попыток обновления (FR‑3, NFR‑5).
- TR‑12 (классы ошибок и ретраи): система должна различать retryable и non‑retryable ошибки:
  - retryable (например, сетевые ошибки/таймауты/rate limit/5xx) — повторять с экспоненциальным backoff + jitter;
  - non‑retryable (например, нет доступа/неверные креды/канал недоступен) — переводить источник в `error` без бесконечных повторов, оставляя возможность ручного восстановления.
- TR‑13 (параметры ретраев по умолчанию): для одного запуска ingestion рекомендуемые значения по умолчанию:
  - `max_attempts_per_run = 5`;
  - backoff: 1s, 2s, 4s, 8s, 16s; jitter 0–30%;
  - по исчерпанию попыток — фиксировать `last_error`, `last_attempt_at`, увеличивать счётчик неудач и переводить источник в `error`.
- TR‑14 (хранилище состояния ingestion): для MVP состояние ingestion (конфигурация источников, статусы, курсоры/offset’ы, история попыток) должно храниться в **локальном SQLite‑хранилище**, чтобы обеспечивать атомарные обновления и возобновляемость после сбоев.
- TR‑15 (минимальный состав ingestion state):
  - по источнику: `source_id/channel_id`, `status`, `include_comments`, `history_from/history_to`, `poll_interval`, `batch_size`, `last_post_id`, `backfill_completed_at`, `last_attempt_at`, `last_success_at`, `fail_count`, `last_error`, `rate_limit_until`, `comments_unavailable`;
  - по комментариям (если включены): per‑post курсор в виде отображения `thread_id -> last_comment_id` (хранить отдельно от “шапки” источника).
- TR‑16 (локальный запуск → сервер): на этапе локальной отладки допустимо хранить raw и состояние в SQLite; при переносе на сервер допускается миграция на PostgreSQL для совместного доступа/масштабирования без изменения контрактов `docs/contracts/*.schema.json`.
- TR‑17 (разделение SQLite‑хранилищ в MVP): состояние ingestion и raw‑данные должны храниться **в разных SQLite‑файлах**. Рекомендуемые имена (должны быть конфигурируемыми):
  - `ingestion_state.sqlite` — конфигурация источников/статусы/курсоры;
  - `raw_storage.sqlite` — raw‑сообщения, ключи идемпотентности и индексы выборок.
- TR‑18 (raw storage, идемпотентность): raw‑сообщения должны сохраняться в SQLite с уникальностью по `RawTelegramMessage.source_ref` (PRIMARY KEY/UNIQUE) и поддерживать безопасный upsert без появления дублей (FR‑6a).
- TR‑19 (медиа в MVP): на этапе I **не скачивать** бинарные вложения (видео/аудио/фото/документы); сохранять только метаданные и ссылки/идентификаторы вложений в `raw_payload` (и/или отдельные поля при необходимости).
- TR‑20 (ограничение raw_payload): для управления ростом SQLite в MVP вводится лимит размера `raw_payload` **256KB**. При превышении лимита `raw_payload` сохраняется в “мягко усечённом” виде (например, с полями `truncated: true`, `original_size_bytes`, `kept_fields`/`summary`), при этом ключевые поля контракта (`source_ref`, `text`, `date`, `thread_id`, `parent_message_id`, …) не должны теряться.

### 1.3 Этап II — Processing + ИИ (UC‑4/UC‑4a/UC‑4b)

- TR‑21 (единица обработки, MVP): обработка выполняется по принципу **“1 raw → 1 processed”**: каждый `RawTelegramMessage` обрабатывается отдельно и порождает отдельный `ProcessedDocument` (включая комментарии, если они собраны на этапе I).
- TR‑22 (идемпотентность обработки, MVP): `ProcessedDocument` должен быть идемпотентен относительно первоисточника и храниться как “одно актуальное состояние” на `RawTelegramMessage.source_ref`. Повторный запуск processing не должен создавать дубликаты `ProcessedDocument` для одного `source_ref` (upsert/replace по `source_ref`).
- TR‑23 (версионирование обработки, MVP): версия пайплайна/модели/промпта должна фиксироваться в `ProcessedDocument.metadata` (например: `pipeline_version`, `model_id`, `prompt_id`, `parameters`). При изменении версии допускается перезапись “актуального” `ProcessedDocument` для того же `source_ref` без хранения истории версий.
- TR‑24 (минимальные результаты обработки, MVP):
  - `ProcessedDocument.text_clean` обязателен и содержит очищенный/нормализованный текст;
  - `ProcessedDocument.summary` остаётся опциональным (может отсутствовать для коротких/шумовых сообщений или при экономии ресурсов).
- TR‑25 (topics, MVP): `ProcessedDocument.topics` опционален и может быть пустым. Пустой/отсутствующий список трактуется как “не классифицировано / нет уверенных тем”; downstream‑логика (тематизация/поиск) должна корректно обрабатывать такие документы (например, относить их к “вне тем”).
- TR‑26 (language, MVP): определение языка (`ProcessedDocument.language`) выполняется на этапе processing. `RawTelegramMessage.language` может отсутствовать и не является источником истины.
- TR‑27 (обнаружение тем, MVP): система должна поддерживать самостоятельное обнаружение тем по источнику/каналу (UC‑4b): формировать каталог тем (`TopicCard`) и тематические подборки (`TopicBundle`) на основе набора `ProcessedDocument` + ссылок на первоисточники.
- TR‑28 (режимы тематизации, MVP): при отсутствии заранее заданного списка целевых тем допускается фокус на UC‑4b (discovered topics). Поддержка UC‑4a (known topics) может быть добавлена позже как расширение.
- TR‑29 (запуск пересборки тем): пересборка/обновление `TopicCard`/`TopicBundle` должна поддерживать:
  - запуск по команде пользователя (manual/on-demand);
  - опционально — запуск по расписанию (scheduled).
  Автоматическая event-driven пересборка “по каждому новому сообщению” в MVP не требуется.
- TR‑30 (область пересборки тем, MVP): по умолчанию пересборка тем выполняется **по всей доступной истории** выбранного источника/канала. Поддержка пересборки по окну времени (например, последние N дней) может быть добавлена позже как оптимизация.
- TR‑31 (singleton‑темы в discovered mode, MVP): в режиме UC‑4b допускаются темы‑статьи (`type="singleton"`). Для предотвращения “тем‑упоминаний” должна применяться минимальная фильтрация качества (например, пороги по длине/уверенности/полноте карточки).
- TR‑32 (детерминизм тематизации, MVP): при одинаковых входных данных и одинаковой `pipeline_version` процесс тематизации должен быть максимально детерминированным (фиксированные параметры, минимизация стохастики) и эти параметры должны фиксироваться в `metadata` соответствующих артефактов (`TopicCard`/`TopicBundle`).
- TR‑33 (manual‑запуск пересборки, MVP): manual/on-demand пересборка тем должна поддерживаться через пользовательскую команду (например CLI) с указанием источника/канала и режима пересборки.
- TR‑34 (metadata тематизации, MVP): артефакты тематизации (`TopicCard`/`TopicBundle`) должны фиксировать в `metadata` информацию, достаточную для воспроизводимости и отладки:
  - `topicization_run_id` (идентификатор одной пересборки);
  - `pipeline_version` и ключевые параметры, влияющие на результат (например `algorithm`, `parameters`, включая temperature/seed/top_n_anchors/пороги);
  - область входа `input_scope` как минимум с `channel_id` и `mode="full_history"` (в MVP).
- TR‑35 (критерии качества тем, MVP):
  - singleton‑тема допускается только если якорный `text_clean` имеет длину не менее **300 символов** и `anchors[0].score >= 0.75`;
  - cluster‑тема должна иметь минимум 2 якоря; якоря в top‑N должны удовлетворять `score >= 0.6`;
  - критерии качества должны быть параметризуемыми и фиксироваться в `TopicCard.metadata.parameters`.
  - длина якорного `text_clean` определяется по соответствующему `ProcessedDocument.text_clean` для якоря (сопоставление через `anchor_ref`/`source_ref`).
- TR‑36 (формирование TopicBundle, MVP):
  - элементы из `TopicCard.anchors` включаются в `TopicBundle.items` с `role="anchor"`;
  - supporting‑элементы включаются при `score >= 0.5` (порог параметризуемый); рекомендуется сохранять `justification` при наличии;
  - `TopicBundle.items` должны дедуплицироваться по `source_ref` (контрактный ключ).
- TR‑37 (лимит тем, MVP): лимит `max_topics_per_channel` по умолчанию отсутствует, но должен поддерживаться как пользовательский параметр тематизации. При наличии лимита темы должны отбираться по детерминированному правилу (например, по суммарному score/покрытию) и это правило фиксируется в `metadata.parameters`.
- TR‑38 (детерминизм LLM, MVP): для processing и topicization по умолчанию использовать параметры, минимизирующие стохастику (например `temperature=0`). Параметры генерации, влияющие на результат (temperature/top_p/seed/max_tokens/format/stop), должны фиксироваться в `metadata.parameters`.
- TR‑39 (pipeline_version, MVP): `pipeline_version` должен быть строкой формата `<stage>:vX.Y.Z`, например `processing:v1.0.0` и `topicization:v1.0.0`. Изменение версии обязательно при изменении промптов/моделей/порогов/алгоритмов, влияющих на результаты.
- TR‑40 (prompt_id, MVP): `prompt_id` должен быть идентификатором, однозначно связанным с текстом промпта, в формате хэша (например `sha256:<...>`). Дополнительно рекомендуется сохранять человекочитаемое имя `prompt_name` в `metadata` для удобства анализа.
- TR‑41 (ProcessedDocument.id, MVP): идентификатор `ProcessedDocument.id` должен формироваться детерминированно от первоисточника: `ProcessedDocument.id = "doc:" + source_ref`. Это обеспечивает стабильность id и согласуется с upsert/replace по `source_ref`.
- TR‑42 (хранилище результатов этапа II, MVP): результаты этапа II (`ProcessedDocument`, `TopicCard`, `TopicBundle`) должны храниться в отдельном SQLite‑хранилище (один файл, например `processing_storage.sqlite`, имя должно быть конфигурируемым), отдельно от `raw_storage.sqlite` и `ingestion_state.sqlite`.
- TR‑43 (модель хранения результатов этапа II, MVP): в `processing_storage.sqlite` должны быть определены минимальные таблицы и ключи идемпотентности:
  - `processed_documents`: ключ/UNIQUE по `source_ref` (одно актуальное состояние на материал), upsert/replace по `source_ref`;
  - `topic_cards`: ключ/PK по `id` (одно актуальное состояние на тему), upsert/replace по `id`;
  - `topic_bundles`: ключ/UNIQUE по `topic_id` (одно актуальное состояние на тему), upsert/replace по `topic_id` (снэпшоты по `time_range` не требуются в MVP).
  Комплексные поля (`topics`, `entities`, `anchors`, `items`, `metadata`) допускается хранить как JSON/Text в SQLite.
- TR‑44 (CLI команды этапа II, MVP): пользователь должен иметь возможность запускать этап II через CLI:
  - отдельно processing (raw → `ProcessedDocument`);
  - отдельно topicization (набор `ProcessedDocument` → `TopicCard`/`TopicBundle`);
  - опционально “one-shot” запуск нескольких шагов за одну команду.
  CLI должна поддерживать как минимум: `--channel` (обяз.), `--dry-run`, `--force`, `--max-topics` (по умолчанию без лимита), а также возможность указать/зафиксировать `pipeline_version` в metadata.
- TR‑45 (выходы этапа II, MVP): этап II должен формировать и хранить `ProcessedDocument`, `TopicCard`, `TopicBundle`. Формирование `KnowledgeBaseEntry` откладывается на этап III (слой **Access / Export**), чтобы не вводить лишний формат до определения интерфейсов выдачи.
- TR‑46 (инкрементальность processing, MVP): processing по умолчанию должен обрабатывать только те raw‑сообщения, для которых отсутствует запись `ProcessedDocument` (проверка по `source_ref`). Флаг `--force` должен перезаписывать `ProcessedDocument` для выбранных сообщений/источника.
- TR‑47 (ошибки и ретраи этапа II, MVP):
  - processing (per-message) не должен “ронять” весь запуск из‑за ошибки на одном сообщении: ошибки фиксируются и обработка продолжается;
  - рекомендуемое значение `max_attempts_per_message = 3`, backoff 1s/2s/4s + jitter 0–30%;
  - по исчерпанию попыток должна сохраняться запись о неудачной обработке (минимум: `source_ref`, класс/текст ошибки, attempts, last_attempt_at), чтобы CLI мог показать “что не обработалось”;
  - topicization (per-channel) должна корректно работать по доступным `ProcessedDocument`, фиксируя предупреждения/пропуски в `metadata`.
- TR‑48 (определение “processed отсутствует”, MVP): для инкрементальной обработки raw‑сообщение считается “не обработанным”, если в `processing_storage.sqlite.processed_documents` отсутствует запись с соответствующим `source_ref`.
- TR‑49 (семантика processed_at, MVP): `ProcessedDocument.processed_at` трактуется как время **последнего успешного формирования/обновления** документа (last success). При `--force` и при переобработке `processed_at` обновляется.
- TR‑50 (метрики processing/topicization, MVP): этап II должен формировать минимальный набор метрик по каждому запуску:
  - processing run: `processing_run_id`, `channel_id`, `processed_total`, `skipped_total`, `failed_total`, `duration_seconds`;
  - topicization run: `topicization_run_id`, `channel_id`, `topics_total`, `singleton_topics_total`, `cluster_topics_total`, `bundles_total`, `covered_items_total`, `outside_topics_total`.
- TR‑51 (отчёт о запуске, MVP): по каждому запуску processing/topicization должен формироваться отчёт в виде JSON (по `*_run_id`) и/или логироваться ключевой срез метрик. Метрика “вне тем” в MVP может считаться как `outside_topics_total = processed_total - covered_items_total` по итогам topicization.
- TR‑52 (покрытие темами и многотемность, MVP):
  - `covered_items_total` должен считаться как число **уникальных** материалов (по `source_ref`) канала, которые попали хотя бы в один `TopicBundle.items[]`;
  - в MVP допускается “многотемность”: один материал может входить в несколько тем. Метрики покрытия должны оставаться корректными за счёт подсчёта по уникальным `source_ref`.
- TR‑53 (explainability, MVP): для элементов `TopicBundle.items[]` с `role="supporting"` поле `justification` остаётся опциональным, но рекомендуется заполнять его (особенно для пограничных случаев рядом с порогом `score`). В отчёте topicization (TR‑50/TR‑51) рекомендуется считать `justification_coverage` — долю supporting‑элементов с заполненным `justification`.
- TR‑54 (ссылки на первоисточник, MVP): на этапе II достаточно хранить ссылки на первоисточники в виде `source_ref`/`channel_id`/`message_id`/`message_type` (в `TopicCard.anchors` и `TopicBundle.items`). Генерация человекочитаемых URL/ссылок на Telegram переносится на этап III (слой выдачи).

### 1.4 Этап III — Access / Export (UC‑5, FR‑11..13)

- TR‑55 (интерфейс доступа, MVP): доступ потребителей к результатам должен предоставляться через CLI‑экспорт файлов (без HTTP API в MVP).
- TR‑56 (экспорты, MVP): CLI должна поддерживать как минимум три вида экспорта:
  - **каталог тем** по каналу/источнику (например файл `topics.json`, список `TopicCard`);
  - **одна тема** по `topic_id` (например файл `topic_<topic_id>.json`: `TopicCard` + `TopicBundle` + служебные поля);
  - **плоские KB entries** в формате NDJSON (например `kb_entries.ndjson`, каждая строка — `KnowledgeBaseEntry`), с фильтрами `--channel`, `--topic-id` и (опционально) `--from/--to`.
- TR‑57 (формирование KnowledgeBaseEntry, MVP): `KnowledgeBaseEntry` формируется на этапе III на основе артефактов этапа II. В MVP должны поддерживаться как минимум два типа KB entry:
  - **уровень темы** (на базе `TopicCard` + `TopicBundle`): `KnowledgeBaseEntry.id` детерминирован (например `kb:topic:<topic_id>`), `source.type="topic"`, `source.topic_id=<topic_id>`, а ссылки на первоисточники темы (anchors + supporting) передаются через `metadata` (включая `source_ref` и вычисленные URL);
  - **уровень сообщения** (на базе `ProcessedDocument`): `KnowledgeBaseEntry.id` детерминирован (например `kb:msg:<source_ref>`), `source.type="telegram_message"`, `source.source_ref=<source_ref>`, `source.channel_id`, `source.message_id` и `source.message_type` заполняются из raw/processed.
- TR‑58 (генерация Telegram URL, MVP): CLI экспорта должна генерировать человекочитаемые ссылки на первоисточники Telegram best-effort на этапе III на основе `channel_id` и `message_id`:
  - для публичных каналов/юзернеймов: `https://t.me/<channel>/<message_id>`;
  - для числовых id (например `-100...`): допускается формат `https://t.me/c/<internal_id>/<message_id>` (где `internal_id` = `channel_id` без префикса `-100`).
  Если корректная ссылка не может быть построена, в экспортируемых данных должны сохраняться исходные идентификаторы (`channel_id`, `message_id`, `source_ref`) для последующей резолюции.
- TR‑59 (формат topic_<topic_id>.json, MVP): экспорт одной темы должен включать `TopicCard`, `TopicBundle` и таблицу резолюции ссылок на первоисточники:
  - `topic_card`: объект `TopicCard`;
  - `topic_bundle`: объект `TopicBundle`;
  - `resolved_sources[]`: список объектов `{source_ref, message_type, channel_id, message_id, telegram_url?}` для всех материалов, встречающихся в anchors/bundle items;
  - служебные поля: `exported_at`, `export_version`.
- TR‑60 (параметры CLI‑экспорта, MVP): экспорт должен поддерживать как минимум: `--channel`, `--topic-id`, `--out`, `--format json|ndjson`, `--pretty` (для JSON), `--include-supporting` (по умолчанию `true`), а также фильтры по времени `--from/--to` (опционально).
- TR‑61 (маппинг KnowledgeBaseEntry, MVP): правила формирования KB entries при экспорте должны быть детерминированными:
  - message‑entry (из `ProcessedDocument`):
    - `id = "kb:msg:" + <source_ref>`;
    - `source.type="telegram_message"`, `source.source_ref=<source_ref>`, `source.channel_id`, `source.message_id`, `source.message_type`;
    - `created_at = processed_at`;
    - `content = summary + "\n\n" + text_clean` (если summary присутствует), иначе `content = text_clean`;
    - `topics = ProcessedDocument.topics` (если присутствует), `tags` не обязателен;
    - `metadata.processing` включает `ProcessedDocument.metadata`, `metadata.telegram_url` включает вычисленный URL (best-effort).
  - topic‑entry (из `TopicCard` + `TopicBundle`):
    - `id = "kb:topic:" + <topic_id>`; `source.type="topic"`, `source.topic_id=<topic_id>`;
    - `created_at = TopicCard.updated_at`;
    - `title = TopicCard.title`;
    - `content` должен быть компактным: `summary` + `scope_in/scope_out` (без встраивания полного списка источников);
    - для стабильного фильтра “по теме” `topics = [TopicCard.id]`;
    - `tags = TopicCard.tags` (если есть);
    - `metadata.resolved_sources` включает таблицу резолюции источников `{source_ref, channel_id, message_id, message_type, telegram_url?, role?, score?, justification?}` (best-effort), а также при необходимости сериализованные `TopicCard`/`TopicBundle`.
- TR‑62 (фильтры экспорта, MVP):
  - `--channel` ограничивает экспорт данными выбранного канала;
  - `--topic-id` ограничивает экспорт выбранной темой: topic‑entry по `topic_id`, а message‑entries — только сообщениями, входящими в `TopicBundle.items` этой темы (по `source_ref`);
  - `--from/--to` для message‑entries применяется по времени сообщения `RawTelegramMessage.date` (а не по `processed_at`).
- TR‑63 (детерминизм экспорта, MVP): экспорт должен быть стабильным по порядку вывода:
  - `topics.json` сортируется по `TopicCard.id`;
  - при экспорте темы `TopicBundle.items` сортируется детерминированно (например `(role desc, score desc, source_ref asc)`);
  - `kb_entries.ndjson` выводится в детерминированном порядке (например по `KnowledgeBaseEntry.id`).
- TR‑64 (include-supporting, MVP): флаг `--include-supporting=false` должен исключать supporting‑элементы из экспортируемых `TopicBundle.items` и `resolved_sources` (включая topic‑entry metadata), оставляя только `role="anchor"`.
- TR‑65 (telegram_url best-effort, MVP): при экспорте `telegram_url` должен вычисляться best-effort:
  - если для источника известен `channel_username` (например сохранён в ingestion state/metadata источника) — использовать `https://t.me/<channel_username>/<message_id>`;
  - иначе, если `channel_id` имеет вид `-100...` — использовать `https://t.me/c/<internal_id>/<message_id>` (где `internal_id` = `channel_id` без префикса `-100`);
  - иначе `telegram_url` допускается оставлять пустым/`null`. Во всех случаях должны экспортироваться исходные идентификаторы (`channel_id`, `message_id`, `message_type`, `source_ref`) для последующей резолюции.

## 2. Нефункциональные требования

- Производительность:
  - TR‑NF‑1: Время обработки сообщения (от получения до появления в экспортируемых артефактах) должно укладываться в SLA конкретного проекта/заказчика и задаётся параметрами запуска/частотой обновления.
- Надёжность:
  - TR‑NF‑2: Система должна корректно возобновлять работу после сбоев, без потери уже обработанных сообщений.
- Масштабируемость:
  - TR‑NF‑3: Архитектура должна позволять горизонтальное масштабирование отдельных компонентов (ingestion, processing).

## 3. Требования к интерфейсам и форматам

- TR‑IF‑1: Обмен между модулями должен осуществляться только через структуры, описанные в `docs/contracts/*.schema.json`.
- TR‑IF‑2: Изменения в контрактах должны сопровождаться обновлением соответствующих ADR и тестов.
- TR‑IF‑3: Тематические артефакты должны быть представлены отдельными контрактами:
  - карточка темы — `docs/contracts/topic_card.schema.json` (FR‑9e, AC‑4c);
  - тематическая подборка — `docs/contracts/topic_bundle.schema.json` (FR‑9a/9b, UC‑4a/4b).
- TR‑IF‑4 (идемпотентность тем и детерминизм): для тем типа `cluster` anchors должны формироваться детерминированно (чтобы повторные запуски не плодили дубликаты):
  - для каждого кандидата вычисляется `anchor_ref = "tg:<channel_id>:<message_type>:<message_id>"`;
  - каждому кандидату назначается `score`;
  - выбираются **top‑N** якорей по `score` (по убыванию), при равенстве `score` tie‑break по `anchor_ref` (по возрастанию);
  - `anchors[]` в `TopicCard` записываются в этом отсортированном порядке; primary anchor = `anchors[0]`;
  - идентификатор темы должен быть детерминированным: `TopicCard.id = "topic:" + anchors[0].anchor_ref`;
  - рекомендуемое значение **N=3** для MVP (может быть конфигурируемым, но порядок и tie‑break должны сохраняться).
- TR‑IF‑5 (идемпотентность материалов и подборок):
  - `RawTelegramMessage.source_ref` обязателен; рекомендуется формат `source_ref = "tg:<channel_id>:<message_type>:<id>"` и upsert raw‑хранилища по `source_ref` (FR‑6a, AC‑2a);
  - `ProcessedDocument.source_ref` обязателен и должен ссылаться на `RawTelegramMessage.source_ref` для однозначной трассируемости (FR‑8, NFR‑3);
  - для `TopicBundle` в MVP выполнять upsert по `topic_id` (одна «актуальная» подборка на тему). Если используется `time_range` — допускается хранить снапшоты, ключом становится `(topic_id, time_range.from, time_range.to)`.
  - для `TopicBundle.items[]` рекомендуется хранить `source_ref` материала и использовать его для дедупликации внутри подборки.

## 4. Требования к наблюдаемости

- TR‑OBS‑1: Ключевые шаги пайплайна (ingestion, processing, storage) должны логироваться.
- TR‑OBS‑2: Должны быть базовые метрики: количество обработанных сообщений, ошибки, задержки.

## 5. Связанные документы

- Бизнес‑требования: `business-requirements.md`.
- Архитектура: `architecture.md`, `pipeline.md`.
- Стек технологий: `tech-stack.md`.
- Контракты данных: `docs/contracts/*.schema.json`.

## 6. Примечания для реализации (важно учитывать; не всегда выражается схемами)

- **Dedup по anchor_ref в TopicCard**: требование “anchors уникальны по `anchor_ref`” зафиксировано текстом в `topic_card.schema.json`, но не может быть строго провалидировано JSON Schema draft‑07 без кастомной валидации. В реализации/тестах нужно явно проверять уникальность по `anchor_ref`.
- **Согласованность источников**: `ProcessedDocument.source_ref` должен совпадать с `RawTelegramMessage.source_ref` того же материала; `source_message_id` носит вспомогательный характер и может быть неуникален без контекста.
- **Канонизация идентификаторов**: форматы `source_ref`/`anchor_ref` предполагают отсутствие двоеточий внутри компонентов (`channel_id`, `message_id`). Если в реальности встречается иной формат id, потребуется либо экранирование/кодирование компонентов, либо пересмотр `pattern`.
- **Score в cluster‑темах**: `TopicCard.type="cluster"` требует `score` у anchors (через условие в схеме). Нужно заранее определить диапазон/семантику `score` и обеспечить детерминированность вычисления.
- **Идемпотентность TopicBundle**: “актуальная” подборка upsert по `topic_id`; снапшоты допустимы только при заполненном `time_range` и отдельном ключе `(topic_id, from, to)`. Это влияет на модель хранения и на API выдачи.
- **Уникальность материала**: везде ключом материала считается `source_ref`, а не `id`/`message_id` в одиночку; любые индексы/таблицы должны строиться вокруг `source_ref`.

## 7. Трассировка ключевых требований (MVP)

| Бизнес‑требование | Проверяемое условие | TR | Контракты |
|---|---|---|---|
| FR‑5 (комментарии) | Комментарии поддерживаются и включаются per‑source (`include_comments`) | TR‑5, TR‑6, TR‑7 | `raw_telegram_message.schema.json` |
| FR‑6 (raw) | Raw сохраняется и пригоден для переобработки/трассируемости | TR‑8, TR‑18 | `raw_telegram_message.schema.json` |
| FR‑6a / AC‑2a (без дублей) | Повторный сбор/переобработка не создаёт дублей | TR‑10, TR‑18, TR‑IF‑5 | `raw_telegram_message.schema.json` (`source_ref`) |
| FR‑8 / NFR‑3 (трассируемость) | Любой обработанный документ однозначно указывает первоисточник | TR‑IF‑5 | `processed_document.schema.json` (`source_ref`) |
| FR‑9e / AC‑4c (карточка темы) | Карточка темы содержит обязательные поля и якорь | TR‑IF‑3, TR‑IF‑4 | `topic_card.schema.json` |
| UC‑4b / FR‑9a/9d (discovered topics) | По каналу формируется каталог тем + подборки “всё по теме” (full-history) | TR‑27, TR‑30, TR‑31, TR‑36 | `topic_card.schema.json`, `topic_bundle.schema.json` |
| Метрики качества тем | Есть метрики topicization run (topics_total, covered/outside, …) | TR‑50, TR‑51, TR‑52 | `topic_bundle.schema.json` (items/source_ref), `processed_document.schema.json` |
