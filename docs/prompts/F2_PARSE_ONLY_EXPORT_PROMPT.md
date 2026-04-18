# F2 — Parse-Only Export Implementation — Стартовый промпт

**Версия проекта:** 4.6.0+ (после мёрджа F5-A Phase 3 — PR #9, ветка `feat/f5a-phase3-deduplication`)
**Ветка:** `feat/f2-parse-only-export` (создать от обновлённого `main`)
**План реализации:** [`docs/plans/F2_PARSE_ONLY_EXPORT_PLAN.md`](../plans/F2_PARSE_ONLY_EXPORT_PLAN.md) — **читать первым**
**Design-doc:** [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F2: Channel Content Export (Parse-Only Mode)"
**Roadmap:** [`docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`](../notes/ROADMAP_V3_PRODUCTION_FIRST.md) §"Пост-F5-A Phase 3 — утверждённая последовательность (18 апреля 2026)"

---

## Цель

Дать пользователю возможность использовать систему исключительно как **парсер
Telegram-каналов** — без LLM-обработки, топикизации, embeddings, RAG —
экспортируя `raw_messages` в структурированный формат (JSON/NDJSON).

Реализуется через новое измерение `level ∈ {raw, processed, full}` поверх
существующего export-слоя:

1. **Новый модуль** `tg_parser/export/raw_export.py` — pure writer:
   `export_raw_channel_json()` (envelope с группировкой comments под посты)
   и `export_raw_channel_ndjson()` (одно сообщение на строку).
2. **Расширение** `run_export(level=ExportLevel.FULL)` — branching по level;
   `FULL` = legacy (kb_entries + topics), `PROCESSED` = kb_entries only,
   `RAW` = новый путь через `RawMessageRepo.list_by_channel`.
3. **CLI/API/MCP/Bot** — сквозное прокидывание `level` + `format` + date
   filters; MCP и Bot tools `export_channel` используют ту же инфраструктуру
   persistent jobs.
4. **Обратная совместимость:** любой caller, не указавший `level`, получает
   `FULL` с byte-identical output — тест `test_run_export_default_level_is_full_identical_to_pre_f2`.

---

## Коротко об архитектуре

```
CLI / API / MCP / Bot
    │  {channel_id, level, format, from_date, to_date}
    ▼
ExportService.run_export(level=...)
    │
    ├── level=RAW        → RawMessageRepo.list_by_channel(...)
    │                    → group comments under posts (by parent_message_id)
    │                    → writer: JSON envelope or NDJSON stream
    │                    → raw_messages.{json,ndjson}
    │
    ├── level=PROCESSED  → ProcessedDocumentRepo → KnowledgeBaseEntry[]
    │                    → kb_entries.ndjson (без topics.json!)
    │
    └── level=FULL (dft) → existing path (kb_entries + topics.json + topic_<id>.json)
```

**Параметры `raw`-envelope** (schema `raw_channel_export.v1`):
- `channel_id`, `channel_username`, `exported_at`, `filters` (from/to date).
- `messages_count` (posts), `comments_count`, `orphan_comments_count`.
- `messages[]` — посты по дате, каждый с вложенным `comments[]` (отсортированы по дате).
- `orphan_comments[]` — комментарии, чей parent-post вне даты-диапазона (иначе потерялись бы молча).

**Приватность:** `raw_payload` (256 KB Telethon structs) **не включается**.
Writer вызывает `model_dump(mode="json", exclude={"raw_payload"})`. Тест
`test_raw_payload_excluded_by_default` фиксирует.

---

## Ключевые уточнения (после разведки)

- [`tg_parser/services/export_service.py`](../../tg_parser/services/export_service.py) — `run_export(output_dir, channel_id?, topic_id?, from_date?, to_date?, pretty?, *repos)` — сейчас возвращает `{kb_entries_count, topics_count, channels_count}`.
- [`tg_parser/api/routes/export.py`](../../tg_parser/api/routes/export.py) — `_run_export_job` вызывает `run_export(output_dir=..., channel_id=body.channel_id)` без `from_date`/`to_date`/`topic_id` (строка 67). Нужно прокидывать `level` + `from_date` + `to_date`.
- [`tg_parser/api/schemas.py`](../../tg_parser/api/schemas.py):
  - строка 25 — `ExportFormat` (NDJSON | JSON); оставляем.
  - строка 133 — `ExportRequest` (channel_id, format, include_topics, webhook_url, webhook_secret). Добавляем `level: ExportLevel`, `from_date`, `to_date`.
  - строка 167 — `ExportResponse` (job_id, status, format, created_at, download_url, message). Добавляем `level: ExportLevel`.
- [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py) строки 674–752 — CLI `export` уже принимает `--channel`, `--topic-id`, `--from-date`, `--to-date`, `--pretty`. Добавляем `--level`, `--format`.
- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py):
  - строка 295 — `RawMessageRepo`; нужный метод `list_by_channel(channel_id, from_date?, to_date?, limit?)` — строка 331 — **уже есть**.
  - строка 373 — `ProcessedDocumentRepo` — не трогаем.
- [`tg_parser/storage/sqlalchemy/raw_message_repo.py`](../../tg_parser/storage/sqlalchemy/raw_message_repo.py) строки 155–190 — `list_by_channel` реализация.
- [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py) строки 44–89 — `RawTelegramMessage` готов к `model_dump(mode="json", exclude={"raw_payload"})`.
- `tg_parser/services/db_context.py::export_repos()` — уточнить сигнатуру в plan mode: нужно либо расширить до 5-кортежа с `RawMessageRepo`, либо завести отдельный `raw_export_repos()`.
- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — 20+ `@mcp.tool()` декораторов; export-тула **нет**. Добавляем `export_channel` + (опционально) `get_export_status`, если такого ещё нет.
- **Aiogram 50 MB лимит** на `send_document` — size-gate в bot-tool; если `file_size > 50 MB` → возвращать `download_url` вместо файла.
- **Visible behavior preservation #1:** `run_export(channel_id=X)` без `level` → `FULL` → байт-в-байт идентичный output (kb_entries.ndjson + topics.json + topic_<id>.json).
- **Visible behavior change #1:** `run_export(..., level=PROCESSED)` — только `kb_entries.ndjson`, **нет** `topics.json`. Это намеренно: разделение уровней даёт чистую semantics.
- **`raw_payload` exclusion — hard invariant:** любой `level=RAW` output не содержит `raw_payload`. Фиксируем явным assert'ом в тестах.

---

## Структура работы (2 коммита)

### Коммит 1 — Core raw export + service/CLI/API integration

**Файлы:**
- [`tg_parser/api/schemas.py`](../../tg_parser/api/schemas.py):
  - Новый enum `ExportLevel(StrEnum)` — `RAW | PROCESSED | FULL`.
  - `ExportRequest.level: ExportLevel = Field(default=ExportLevel.FULL, ...)`.
  - `ExportRequest.from_date: datetime | None`, `to_date: datetime | None`.
  - `ExportResponse.level: ExportLevel`.
- [`tg_parser/export/raw_export.py`](../../tg_parser/export/raw_export.py) (new):
  - `SCHEMA_VERSION = "raw_channel_export.v1"`.
  - `export_raw_channel_json(messages, channel_id, channel_username, from_date, to_date, output_path, pretty=False) -> dict[str, int]`.
  - `export_raw_channel_ndjson(messages, output_path) -> dict[str, int]`.
  - `_group_messages(messages) -> (posts, {post_id: [comments]}, orphans)` — pure helper.
  - `_message_payload(msg)` — `msg.model_dump(mode="json", exclude={"raw_payload"})`.
- [`tg_parser/services/export_service.py`](../../tg_parser/services/export_service.py):
  - Расширить сигнатуру `run_export(..., level=ExportLevel.FULL, format=ExportFormat.NDJSON, *, raw_repo=None, ...)`.
  - Ветвление по `level`: `RAW` → `raw_repo.list_by_channel` + writer; `PROCESSED` → existing minus topics; `FULL` → unchanged.
  - `level=RAW` без `channel_id` → `ValueError("level='raw' requires channel_id")`.
  - Возврат: `{raw_posts_count, raw_comments_count, raw_orphan_comments_count, channels_count}` для RAW; legacy для PROCESSED/FULL.
- [`tg_parser/services/db_context.py`](../../tg_parser/services/db_context.py):
  - Расширить `export_repos()` context на `RawMessageRepo` (либо отдельный `raw_export_repos()` — решить в plan-mode).
- [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py):
  - В `export` добавить `--level str = "full"`, `--format str = "json"` + валидация + прокинуть в `run_export`.
  - `--level raw` без `--channel` → typer.Exit(1) + stderr message.
- [`tg_parser/api/routes/export.py`](../../tg_parser/api/routes/export.py):
  - `_run_export_job`: прокинуть `request.level`, `request.from_date`, `request.to_date` в `run_export`; выбор `export_file` по `level` + `format`.
  - `start_export`: `body.level == RAW and not body.channel_id` → `HTTPException(400, "level='raw' requires channel_id")`.
  - `download_export`: расширить выбор `media_type` / `filename` на `raw_messages.{json,ndjson}`.
  - `ExportResponse(level=body.level, ...)`.
- Новый файл `tests/test_f2_parse_only_export.py` с классами (Commit 1 — ~25 тестов):
  - `TestRawExportWriter` (~8, tmp_path) — envelope schema, группировка, sorted comments, orphans, NDJSON layout, pretty flag, `raw_payload` excluded, empty channel.
  - `TestGroupMessages` (~4, pure) — одиночный пост, несколько comments, orphans, multiple posts.
  - `TestExportServiceRaw` (~5, Postgres fixture) — end-to-end writes, requires-channel_id ValueError, date filter, empty channel.
  - `TestExportServiceBackwardCompat` (~3) — default level=FULL byte-identical, level=PROCESSED skips topics, старая сигнатура работает.
  - `TestCLIExportLevel` (~3) — валидация `--level`, `--format`, `--level raw` без `--channel`.
  - `TestAPIExportLevel` (~4, TestClient) — POST raw создаёт job, 400 без channel_id, status includes level, correct media_type/filename для NDJSON.

**Commit message:**
```
feat(f2): add raw channel export (level=raw|processed|full) to service/CLI/API
```

### Коммит 2 — MCP + Bot tool + docs

**Файлы:**
- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py):
  - Новый `@mcp.tool() async def export_channel(channel_id, level="raw", format="json", from_date=None, to_date=None, ctx=None) -> ExportChannelResult`.
  - Внутри: валидация `ExportLevel`, ownership `assert_channel_access`, создание Job через `job_store.create_job(...)`, `asyncio.create_task(_run_export_job(...))`.
  - Если `get_export_status` tool отсутствует — добавить.
- [`tg_parser/bot/agent.py`](../../tg_parser/bot/agent.py) + `tg_parser/bot/handlers/*`:
  - Bot tool `export_channel` — зовёт ту же job-логику + polls до completion + отправляет файл через aiogram `FSInputFile`.
  - Size-gate: `file_size > 50 MB` → НЕ `send_document`, вернуть `download_url` + summary.
  - Progress-message до готовности.
- [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md) — новый раздел "Parse-Only Export (F2)": что делает `--level raw`, envelope structure, NDJSON vs JSON, примеры CLI/API/MCP/bot, privacy (raw_payload excluded).
- [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md) — секция `export_channel`: параметры, workflow submit → poll → download.
- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) — заметка про `OUTPUT_DIR` (новых env нет).
- [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F2" — DONE + ссылка на PR.
- `tests/test_f2_parse_only_export.py` — дополнить (Commit 2 — ~8 тестов):
  - `TestMCPExportChannel` (~4) — submits job, invalid level ValueError, ownership enforced, defaults to raw/json.
  - `TestBotExportChannel` (~4, mocked Bot) — small file sent as document, large file returns URL, progress message, ownership enforced.

**Commit message:**
```
feat(f2): add export_channel MCP and bot tools with documentation
```

---

## `ExportLevel` шпаргалка

```python
# tg_parser/api/schemas.py, after ExportFormat (line 30):
from enum import StrEnum

class ExportLevel(StrEnum):
    RAW = "raw"
    PROCESSED = "processed"
    FULL = "full"
```

`ExportRequest`:

```python
class ExportRequest(BaseModel):
    channel_id: str | None = Field(default=None, description="Filter by channel (required for level='raw')")
    level: ExportLevel = Field(default=ExportLevel.FULL, description="Export level: raw (parse-only) | processed (KB) | full (legacy, default)")
    format: ExportFormat = Field(default=ExportFormat.NDJSON, description="Export format (applies to level=raw; processed/full use legacy conventions)")
    from_date: datetime | None = Field(default=None, description="Filter messages from this UTC datetime")
    to_date: datetime | None = Field(default=None, description="Filter messages up to this UTC datetime")
    # existing: include_topics, webhook_url, webhook_secret
```

---

## Raw envelope — спецификация

```json
{
  "schema_version": "raw_channel_export.v1",
  "channel_id": "1234567890",
  "channel_username": "example_channel",
  "exported_at": "2026-04-18T12:00:00Z",
  "filters": {"from_date": null, "to_date": null},
  "messages_count": 542,
  "comments_count": 1287,
  "orphan_comments_count": 3,
  "messages": [
    {
      "id": "987",
      "source_ref": "tg:1234567890:post:987",
      "message_type": "post",
      "date": "2026-01-15T10:30:00Z",
      "text": "...",
      "language": "ru",
      "thread_id": null,
      "parent_message_id": null,
      "comments": [
        {
          "id": "988",
          "source_ref": "tg:1234567890:comment:988",
          "message_type": "comment",
          "date": "2026-01-15T11:00:00Z",
          "text": "...",
          "parent_message_id": "987",
          "language": "ru"
        }
      ]
    }
  ],
  "orphan_comments": [
    {
      "id": "990",
      "source_ref": "tg:1234567890:comment:990",
      "message_type": "comment",
      "date": "2025-12-31T22:00:00Z",
      "text": "...",
      "parent_message_id": "850"
    }
  ]
}
```

**NDJSON:** один message на строку (через `stable_json_dumps(_message_payload(msg)) + "\n"`); posts первыми (отсортированы по date), потом comments (отсортированы по date). Без envelope, без группировки, без orphan-секции.

---

## Ключевые тест-кейсы

### `TestRawExportWriter` (pure, tmp_path)
- `test_json_envelope_schema_version_present`.
- `test_json_envelope_fields` — все required поля.
- `test_post_with_comments_grouped_by_parent_message_id`.
- `test_comments_sorted_by_date_within_post`.
- `test_orphan_comments_bucket_when_parent_out_of_range`.
- `test_ndjson_one_message_per_line_posts_first_then_comments`.
- `test_pretty_flag_produces_indented_json` / `test_compact_json_no_indent`.
- `test_raw_payload_excluded_by_default` — критичный invariant.
- `test_empty_messages_writes_valid_envelope` — fail-open.

### `TestGroupMessages` (pure)
- `test_post_with_no_comments`.
- `test_multiple_comments_under_one_post_ordered_by_date`.
- `test_orphan_comments_collected_separately`.
- `test_multiple_posts_sorted_by_date`.

### `TestExportServiceRaw` (Postgres fixture)
- `test_run_export_level_raw_writes_json`.
- `test_run_export_level_raw_ndjson_writes_line_per_message`.
- `test_run_export_level_raw_requires_channel_id` — ожидаем `ValueError`.
- `test_run_export_level_raw_respects_date_filter`.
- `test_run_export_level_raw_channel_without_messages_returns_empty_envelope`.

### `TestExportServiceBackwardCompat`
- `test_run_export_default_level_is_full_identical_to_pre_f2`.
- `test_run_export_level_processed_skips_topics`.
- `test_run_export_default_call_signature_still_works`.

### `TestCLIExportLevel`
- `test_cli_level_raw_requires_channel`.
- `test_cli_invalid_level_rejected`.
- `test_cli_invalid_format_rejected`.

### `TestAPIExportLevel` (TestClient)
- `test_post_export_level_raw_creates_job`.
- `test_post_export_level_raw_without_channel_returns_400`.
- `test_get_status_includes_level`.
- `test_download_raw_ndjson_has_correct_media_type_and_filename`.

### `TestMCPExportChannel`
- `test_mcp_export_channel_submits_job`.
- `test_mcp_export_channel_invalid_level_raises`.
- `test_mcp_export_channel_ownership_enforced`.
- `test_mcp_export_channel_defaults_to_raw_json`.

### `TestBotExportChannel` (mocked Bot)
- `test_bot_export_channel_small_file_sent_as_document`.
- `test_bot_export_channel_large_file_returns_download_url`.
- `test_bot_export_channel_progress_message`.
- `test_bot_export_channel_ownership_enforced`.

**Запуск:**
```bash
# Unit
.venv/bin/pytest tests/test_f2_parse_only_export.py -x -q

# Full with Postgres
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

**Ожидаемо:** 1487 → ~1520 (добавляется ~33 теста).

---

## Существующие тесты — риски

- `tests/test_export*.py` / `tests/test_kb_export*.py` — могут полагаться на точную сигнатуру `run_export` или присутствие обоих `kb_entries.ndjson` + `topics.json` после каждого вызова. Нужно проверить и обновить, если `level=PROCESSED` не пишет topics.
- `tests/test_api_export*.py` — могут фиксировать `ExportRequest` fields. Backward-compat сохраняется (новые поля имеют defaults), но `ExportResponse.level` новое — тесты могут потребовать обновления.
- `tests/test_cli_export*.py` — если полагаются на hardcoded args CLI.
- `tests/test_mcp_server.py` / `tests/test_bot_tools.py` — новые tools могут повлиять на tool-listing тесты (количество tools).

**Стратегия:** пробежать `pytest tests/test_export*.py tests/test_api_export*.py tests/test_cli_export*.py tests/test_mcp*.py tests/test_bot*.py -x -q` до и после правок; ломающиеся — чинить в том же коммите.

---

## Критерии готовности

1. `ExportLevel` enum (`raw` | `processed` | `full`), `ExportRequest.level = FULL` default; все API-caller'ы без `level` получают byte-identical output — тест `test_run_export_default_level_is_full_identical_to_pre_f2`.
2. `tg_parser/export/raw_export.py` — pure writer, JSON envelope v1 + NDJSON, `raw_payload` excluded (явный тест); orphan-bucket.
3. `run_export(level=RAW)` требует `channel_id`; `level=PROCESSED` skip topics; `FULL` — legacy unchanged.
4. CLI `tg_parser export --level raw --channel X [--format ndjson|json]` — работает; валидация негативных случаев.
5. API `POST /api/v1/export {level, channel_id, format, from_date, to_date}` — создаёт job; download поддерживает raw-файлы; 400 при `raw` без `channel_id`.
6. MCP `export_channel(channel_id, level, format, from_date, to_date)` — ownership + job submission.
7. Bot `export_channel` tool — file delivery через `FSInputFile`; size-gate 50 MB.
8. Документация: USER_GUIDE (F2), MCP_AGENT_GUIDE, ENV_VARIABLES_GUIDE (минимальное), FUTURE_FEATURES (F2 DONE).
9. `tests/test_f2_parse_only_export.py` — ~33 теста; все проходят; ключевой invariant `test_raw_payload_excluded_by_default` включён.
10. `TEST_POSTGRES=1 pytest tests/ -x -q` — ≥1518 passed **перед каждым** из двух коммитов; существующие export/api/cli/mcp/bot тесты не регрессируют.
11. **Self-review loop выполнен** перед каждым коммитом (§"Рекомендации исполнения" п. 12).
12. Два коммита с указанными messages.

---

## Что НЕ входит в scope F2

- **Level=raw без `channel_id`** (по всем каналам) — отложено; требует `RawMessageRepo.list_all()` + paging-стратегии.
- **YAML/CSV форматы** — откладываются; не входят в MVP.
- **Streaming NDJSON через HTTP response** (вместо batch-файла) — существующий Phase 2F паттерн (Job → file → download_url) остаётся.
- **`include_raw_payload` флаг** — приватность по умолчанию выше гибкости; если потребуется — отдельная фича с warning'ом.
- **Level=raw_plus_processed** (гибрид) — `level=full` покрывает use-case.
- **Incremental export** — решается через `--from-date $LAST_EXPORT_TIME` caller'ом.
- **Topics в `level=PROCESSED`** — намеренно только в `FULL`; разделение даёт чистую semantics.

---

## Рекомендации исполнения

1. **Plan mode first** — свериться с актуальным `main`: номера строк в `export_service.py`, `routes/export.py`, `cli/app.py`, `api/schemas.py`; проверить форму `db_context.export_repos()` (tuple size + callers).
2. **TDD для `raw_export.py`** — pure writer, zero dependencies → 12+ тестов (`TestRawExportWriter` + `TestGroupMessages`), затем реализация.
3. **Порядок Commit 1:** schema (`ExportLevel`) → raw_export.py writer → `run_export` branching → db_context → CLI → API → tests. Каждый шаг gated unit-тестами.
4. **Порядок Commit 2:** MCP tool → Bot tool → docs → tests. Reuse existing job-patterns из `api/routes/export.py`.
5. **Backward-compat первым делом** — добавить `test_run_export_default_call_signature_still_works` + `test_run_export_default_level_is_full_identical_to_pre_f2` **до** любых правок в `export_service.py`; запустить (упадёт на API, если сигнатура уже меняется) → доработать реализацию.
6. **`raw_payload` exclusion — hard invariant** — тест `test_raw_payload_excluded_by_default` ДОЛЖЕН проверять **каждый** serialized message (и envelope, и NDJSON), не только один; `assert "raw_payload" not in json.loads(line)` в loop.
7. **Aiogram размер** — `file_size > 50 * 1024 * 1024` гейт реальным файлом в тесте (mock `Path.stat().st_size`); иначе пользователь получит telegram-ошибку "File too large" в проде.
8. **Ownership** — `assert_channel_access(user, channel_id)` вызывается в `start_export` **до** создания job'а, для всех уровней, включая `RAW`. Тест на non-owner → 403.
9. **Логи** — при `level=RAW` логировать `channel_id`, `posts_count`, `comments_count`, `format`; НЕ логировать содержимое сообщений (PII).
10. **Orphan comments** — не объединять с `messages[]`; отдельный bucket с counter'ом; USER_GUIDE объясняет как они возникают (вне date-range).

### 11. Backward-compatibility — hard requirement

`run_export(output_dir=..., channel_id=...)` без `level`/`format` kwargs
должен возвращать байт-идентичный output как до F2. Любой caller,
который не знает про новые параметры, продолжает работать.

Тест-паттерн:
```python
# До F2 (зафиксировано в baseline)
stats_before = await run_export(output_dir=out1, channel_id="X", from_date=..., to_date=...)

# После F2 (с новыми kwargs-дефолтами)
stats_after = await run_export(output_dir=out2, channel_id="X", from_date=..., to_date=...)

# Файлы идентичны
assert (out1 / "kb_entries.ndjson").read_bytes() == (out2 / "kb_entries.ndjson").read_bytes()
assert (out1 / "topics.json").read_bytes() == (out2 / "topics.json").read_bytes()
```

### 12. Self-review loop (обязателен перед каждым коммитом)

После того как новые тесты впервые прошли локально, **ДО** коммита:

1. **Первый прогон тестов** — убедиться что новые тесты зелёные:
   ```bash
   .venv/bin/pytest tests/test_f2_parse_only_export.py -x -q
   ```
2. **Self-review** — перечитать **весь** новый и изменённый код + новые тесты. Оценить покрытие по чек-листу фазы:
   - **Commit 1 чек-лист:** backward-compat (`run_export(channel_id=X)` без kwargs — byte-identical), raw writer edge cases (empty, only-post, only-comment, orphans, multi-parent), date filter corner cases (None/None, only from, only to, reversed), NDJSON validity (каждая строка — валидный JSON), `raw_payload` exclusion (каждый message), CLI validation (`--level raw` без `--channel` → exit != 0), API 400 (`level=raw` без channel_id), ownership (non-owner → 403 для всех уровней), regression в existing export/api/cli тестах.
   - **Commit 2 чек-лист:** MCP tool signature соответствует проектным конвенциям, MCP auth (ownership enforced), Bot size gate (> 50 MB → URL, не `send_document`), Bot polling (progress message + timeout), docs consistency (CLI/API/MCP/bot примеры совпадают по параметрам), rate-limit упомянут в USER_GUIDE.
   - Детальные чек-листы — в [`F2_PARSE_ONLY_EXPORT_PLAN.md`](../plans/F2_PARSE_ONLY_EXPORT_PLAN.md) §"Порядок работы" шаги 5 и 10.
3. **Добавить недостающие тесты** или поправить код, если чек-лист обнаружил пробелы. Это часть текущего коммита, не отдельный.
4. **Повторный прогон новых тестов** — убедиться что доработки зелёные:
   ```bash
   .venv/bin/pytest tests/test_f2_parse_only_export.py -x -q
   ```
5. **Полный regression перед коммитом** — **обязателен**, ловит регрессии в существующих export/api/cli/mcp/bot-тестах:
   ```bash
   TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
   ```
   Ожидаемо после Commit 1: ≥1512 passed (1487 + ~25 новых). После Commit 2: ≥1518 passed.
6. **Commit** только после зелёного полного прогона.

Этот цикл применяется к **каждому** коммиту (Commit 1 и Commit 2 отдельно). Тот же паттерн, что и в F5-A Phase 1/2/3 — он ловит "тесты зелёные, но мы забыли edge case" и "новый код сломал что-то в existing suite".
