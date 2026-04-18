# F2 — Channel Content Export (Parse-Only) — Implementation Plan

**Версия проекта:** 4.6.0+ (после мёрджа F5-A Phase 3 — `feat/f5a-phase3-deduplication`, PR #9)
**Scope:** Экспорт сырых Telegram-сообщений (`raw_messages`) в JSON/NDJSON через новое измерение `level ∈ {raw, processed, full}` в `ExportService`, API `/api/v1/export`, CLI `tg_parser export`, MCP-tool и bot-tool. `processed` и `full` сохраняют текущее поведение без регрессий.
**Предыдущие фазы:** Wave 1.5 → F8-A ✅ → F5-A Phase 1 (Hybrid) ✅ → Phase 2 (Relevance tuning) ✅ → Phase 3 (Deduplication) ✅.
**Design-doc:** [`../notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F2: Channel Content Export (Parse-Only Mode)"
**Starter prompt:** [`../prompts/F2_PARSE_ONLY_EXPORT_PROMPT.md`](../prompts/F2_PARSE_ONLY_EXPORT_PROMPT.md)
**Ветка:** `feat/f2-parse-only-export` (создать от `main` после мёрджа PR #9)

---

## Контекст (что уже есть)

### Export slice

- [`tg_parser/services/export_service.py`](../../tg_parser/services/export_service.py) — `run_export(output_dir, channel_id?, topic_id?, from_date?, to_date?, pretty?, *repos)` загружает `ProcessedDocument[]` через `processed_repo.list_by_channel` / `list_all`, мапит в `KnowledgeBaseEntry` через [`tg_parser/export/kb_mapping.py`](../../tg_parser/export/kb_mapping.py), пишет `kb_entries.ndjson` + (опционально) `topics.json` + `topic_<id>.json`.
- [`tg_parser/export/kb_export.py`](../../tg_parser/export/kb_export.py) — `export_kb_entries_ndjson(entries, path)`; `filter_kb_entries(...)`.
- [`tg_parser/export/topics_export.py`](../../tg_parser/export/topics_export.py) — `export_topics_json`, `export_topic_detail_json`.
- [`tg_parser/api/routes/export.py`](../../tg_parser/api/routes/export.py) — `POST /api/v1/export` создаёт persistent Job (Phase 2F), фон-задача `_run_export_job` зовёт `run_export(channel_id=body.channel_id)` (без `from_date`/`to_date`/`topic_id`), сохраняет файл в `settings.output_dir`, выставляет `job.download_url = /api/v1/export/download/{job_id}`; `GET /export/status/{job_id}`, `GET /export/download/{job_id}`. Авторизация через `resolve_current_user`, ownership через `assert_channel_access`.
- [`tg_parser/api/schemas.py`](../../tg_parser/api/schemas.py) lines 25–30, 133–148, 167–175 — `ExportFormat` (`ndjson`|`json`), `ExportRequest` (channel_id, format, include_topics, webhook_url, webhook_secret), `ExportResponse`.
- [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py) lines 674–753 — CLI `tg_parser export --out --channel --topic-id --from-date --to-date --pretty`.

### Raw slice (что используем)

- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) line 295 — `RawMessageRepo`. Методы: `upsert`, `upsert_batch`, `get_by_source_ref`, `list_by_channel(channel_id, from_date?, to_date?, limit?)` (line 331), `count_by_channel`, и т.д. **Нет `list_all(from_date, to_date)`** — F2 ограничивается per-channel экспортом для `level=raw`.
- [`tg_parser/storage/sqlalchemy/raw_message_repo.py`](../../tg_parser/storage/sqlalchemy/raw_message_repo.py) — реализация; `list_by_channel` использует `date >= :from_date AND date <= :to_date` + опциональный `LIMIT`.
- [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py) lines 44–89 — `RawTelegramMessage` (id, message_type, source_ref, channel_id, date, text, parent_message_id, thread_id, language, raw_payload). Pydantic → `model_dump(mode="json")` готов.
- [`tg_parser/domain/json_utils.py`](../../tg_parser/domain/json_utils.py) — `stable_json_dumps(obj)` детерминированная сериализация (уже используется в `kb_export`).

### MCP / Bot

- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — 20+ `@mcp.tool()` декораторов; **export-тулы отсутствуют**. Добавим `export_channel`.
- Bot tools: [`tg_parser/bot/agent.py`](../../tg_parser/bot/agent.py) + `tg_parser/bot/handlers/` — добавим `export_channel` tool с отправкой файла через aiogram `InputFile`.

### Observed constraints

- Raw messages могут содержать **256 KB** `raw_payload` (TR-20) — по умолчанию **не** включаем в экспорт (утечка session-специфичных Telethon structs, file_refs, auth-артефактов). Включение через явный флаг `include_raw_payload=false` (default).
- Comments связаны с постами через `parent_message_id` / `thread_id`. Для RAW-envelope группируем: один пост → массив `comments[]`, отсортированных по `date`.
- Большие каналы (5K+ сообщений) — NDJSON предпочтителен (потоковая запись, один message на строку); JSON-envelope приемлем до ~50K сообщений / ~50 MB.

---

## Архитектура

```mermaid
flowchart TD
  subgraph Client
    CLI["tg_parser export --level raw --channel X"]
    API["POST /api/v1/export {level: raw, channel_id: X}"]
    MCP["mcp.export_channel(channel_id, level=raw)"]
    Bot["bot: export_channel tool"]
  end
  CLI --> Svc
  API --> Job[_run_export_job] --> Svc
  MCP --> API
  Bot --> API
  Svc[run_export level=raw|processed|full] -->|raw| Raw[export_raw_channel]
  Svc -->|processed|full| Old[existing path kb_entries + topics]
  Raw --> R1[RawMessageRepo.list_by_channel]
  Raw --> R2[IngestionStateRepo.get_channel_usernames]
  Raw --> Group[group comments under posts by thread_id]
  Group --> Write[writer: JSON envelope or NDJSON stream]
  Write --> File["raw_messages.{json,ndjson}"]
```

---

## Дизайн

### Модель `level`

```python
# tg_parser/api/schemas.py
from enum import StrEnum

class ExportLevel(StrEnum):
    RAW = "raw"            # RawTelegramMessage[] grouped per channel
    PROCESSED = "processed" # ProcessedDocument[] → KnowledgeBaseEntry[] (existing)
    FULL = "full"          # PROCESSED + topics.json + topic_<id>.json (existing, dft)
```

`ExportRequest.level: ExportLevel = ExportLevel.FULL` — **дефолт сохраняет текущее поведение**.

### Raw envelope

```json
{
  "schema_version": "raw_channel_export.v1",
  "channel_id": "1234567890",
  "channel_username": "example_channel",
  "exported_at": "2026-04-18T12:00:00Z",
  "filters": {"from_date": null, "to_date": null},
  "messages_count": 542,
  "comments_count": 1287,
  "messages": [
    {
      "id": "987",
      "source_ref": "tg:1234567890:post:987",
      "message_type": "post",
      "date": "2026-01-15T10:30:00Z",
      "text": "Текст поста...",
      "language": "ru",
      "thread_id": null,
      "comments": [
        {
          "id": "988",
          "source_ref": "tg:1234567890:comment:988",
          "date": "2026-01-15T11:00:00Z",
          "text": "Текст комментария...",
          "parent_message_id": "987",
          "language": "ru"
        }
      ]
    }
  ]
}
```

**NDJSON вариант:** один `RawTelegramMessage.model_dump(mode="json")` на строку — без envelope, без группировки comments (подходит для больших каналов + ETL pipelines).

**Что `НЕ` включаем по умолчанию:**
- `raw_payload` — приватные Telethon-структуры; включается только через явный (пока не-публичный) флаг в сервисе; в API/CLI/MCP **не экспонируется** в Phase F2 (может быть добавлено позже, если появится use-case).

### Группировка comments

```python
def _group_messages(raws: list[RawTelegramMessage]) -> list[dict]:
    """Посты + вложенные комментарии.

    Алгоритм:
    1. Разделить на posts (message_type='post') и comments (message_type='comment').
    2. Отсортировать posts по date.
    3. Построить comment-map: parent_message_id → list[comment] (сортировка по date).
       parent_message_id для comment — id родительского поста (TR-6).
    4. Для каждого post подтянуть comments[] через comment-map.
       Orphan comments (без post в выборке из-за date-фильтра) → отдельный
       bucket "orphan_comments" на верхнем уровне envelope (иначе они
       молча потерялись бы).
    """
```

**Orphan comments** — комментарии, чей parent-post вне фильтра по `from_date`/`to_date`. Намеренно сохраняем в отдельном bucket'е: `{..., "orphan_comments": [...]}` — пользователь видит их и может решить расширить диапазон дат.

### Fail-open для отсутствующего канала

`count_by_channel(channel_id) == 0` → write envelope с `messages_count=0, messages=[]` и завершить успешно (не 404). Совместимо с текущим `run_export`, который возвращает `{kb_entries_count: 0, ...}` при отсутствии processed docs.

---

## Коммит 1 — Core raw export + service/CLI/API integration

### 1.1 `ExportLevel` enum + schema

[`tg_parser/api/schemas.py`](../../tg_parser/api/schemas.py) после `ExportFormat` (строка 30):

```python
class ExportLevel(StrEnum):
    """Export level — controls what gets exported.

    - RAW: raw Telegram messages (parse-only, no LLM). Requires channel_id.
    - PROCESSED: KnowledgeBaseEntry[] (post-LLM; current default).
    - FULL: PROCESSED + topics.json + topic_<id>.json (legacy default).
    """
    RAW = "raw"
    PROCESSED = "processed"
    FULL = "full"
```

В `ExportRequest` (строка 133):

```python
level: ExportLevel = Field(
    default=ExportLevel.FULL,
    description="Export level: 'raw' = RawTelegramMessage[], 'processed' = KnowledgeBaseEntry[], 'full' = processed + topics (default, legacy)",
)
# Новые опциональные фильтры по дате на API:
from_date: datetime | None = Field(default=None, description="Filter messages from this UTC datetime")
to_date: datetime | None = Field(default=None, description="Filter messages up to this UTC datetime")
```

В `ExportResponse` — добавить `level: ExportLevel`.

### 1.2 Raw export writer

Новый файл [`tg_parser/export/raw_export.py`](../../tg_parser/export/raw_export.py):

```python
"""Raw Telegram message export (F2: Parse-Only).

Pure writer module — takes ``list[RawTelegramMessage]`` + channel metadata,
writes JSON envelope or NDJSON stream. No I/O to DB.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from tg_parser.domain.json_utils import stable_json_dumps
from tg_parser.domain.models import RawTelegramMessage

SCHEMA_VERSION: Final[str] = "raw_channel_export.v1"


def export_raw_channel_json(
    *,
    messages: list[RawTelegramMessage],
    channel_id: str,
    channel_username: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
    output_path: Path,
    pretty: bool = False,
) -> dict[str, int]:
    """Write grouped JSON envelope to ``output_path``. Returns stats dict."""
    posts_sorted, grouped, orphan_comments = _group_messages(messages)

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "channel_id": channel_id,
        "channel_username": channel_username,
        "exported_at": datetime.now(UTC).isoformat(),
        "filters": {
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
        },
        "messages_count": len(posts_sorted),
        "comments_count": sum(len(g) for g in grouped.values()),
        "orphan_comments_count": len(orphan_comments),
        "messages": [_post_with_comments(p, grouped.get(p.id, [])) for p in posts_sorted],
        "orphan_comments": [_message_payload(c) for c in orphan_comments],
    }

    payload = stable_json_dumps(envelope, indent=2 if pretty else None)
    output_path.write_text(payload, encoding="utf-8")

    return {
        "posts": envelope["messages_count"],
        "comments": envelope["comments_count"],
        "orphan_comments": envelope["orphan_comments_count"],
    }


def export_raw_channel_ndjson(
    *,
    messages: list[RawTelegramMessage],
    output_path: Path,
) -> dict[str, int]:
    """Write one message per line (no grouping, stream-friendly).

    Order: posts first (by date), then comments (by date). Caller is responsible
    for providing filtered messages.
    """
    posts = sorted([m for m in messages if m.message_type == "post"], key=lambda m: m.date)
    comments = sorted([m for m in messages if m.message_type == "comment"], key=lambda m: m.date)
    with output_path.open("w", encoding="utf-8") as f:
        for msg in [*posts, *comments]:
            f.write(stable_json_dumps(_message_payload(msg)))
            f.write("\n")
    return {"posts": len(posts), "comments": len(comments), "orphan_comments": 0}


def _group_messages(
    messages: list[RawTelegramMessage],
) -> tuple[list[RawTelegramMessage], dict[str, list[RawTelegramMessage]], list[RawTelegramMessage]]:
    """Split into (posts_sorted, {post_id: comments_sorted}, orphan_comments_sorted)."""
    posts = sorted([m for m in messages if m.message_type == "post"], key=lambda m: m.date)
    post_ids = {p.id for p in posts}
    comments = [m for m in messages if m.message_type == "comment"]
    grouped: dict[str, list[RawTelegramMessage]] = {}
    orphans: list[RawTelegramMessage] = []
    for c in sorted(comments, key=lambda m: m.date):
        parent = c.parent_message_id
        if parent and parent in post_ids:
            grouped.setdefault(parent, []).append(c)
        else:
            orphans.append(c)
    return posts, grouped, orphans


def _post_with_comments(post: RawTelegramMessage, comments: list[RawTelegramMessage]) -> dict:
    payload = _message_payload(post)
    payload["comments"] = [_message_payload(c) for c in comments]
    return payload


def _message_payload(msg: RawTelegramMessage) -> dict:
    """Serialize message without raw_payload (privacy + size)."""
    return msg.model_dump(mode="json", exclude={"raw_payload"})
```

**Почему отдельный модуль (а не внутри `export_service.py`):**
- Pure-function writer без DB — тестируется без Postgres-фикстур.
- Симметрично `kb_export.py` / `topics_export.py`.

### 1.3 `run_export` в `export_service.py`

[`tg_parser/services/export_service.py`](../../tg_parser/services/export_service.py) — расширить сигнатуру:

```python
from tg_parser.api.schemas import ExportLevel, ExportFormat
from tg_parser.storage.ports import RawMessageRepo

async def run_export(
    output_dir: str,
    channel_id: str | None = None,
    topic_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    pretty: bool = False,
    level: ExportLevel = ExportLevel.FULL,
    format: ExportFormat = ExportFormat.NDJSON,
    *,
    processed_repo: ProcessedDocumentRepo | None = None,
    raw_repo: RawMessageRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
    ingestion_repo: IngestionStateRepo | None = None,
) -> dict[str, int]:
    """...

    When ``level=ExportLevel.RAW``:
      - ``channel_id`` is **required** (raise ``ValueError`` otherwise).
      - Writes ``raw_messages.{json,ndjson}`` using ``raw_repo.list_by_channel``.
      - ``topic_id`` / ``processed_repo`` / ``topic_card_repo`` are ignored.
      - Returns ``{"raw_posts_count": int, "raw_comments_count": int, "raw_orphan_comments_count": int, "channels_count": 1 | 0}``.

    When ``level=ExportLevel.PROCESSED``:
      - Existing behaviour minus topics (no topics.json, no topic_<id>.json).

    When ``level=ExportLevel.FULL`` (legacy default):
      - Existing behaviour (kb_entries.ndjson + topics.json + topic_<id>.json).
    """
```

Branching:
1. Если `level == RAW`:
   - Валидация: `channel_id is not None` → иначе `ValueError("level='raw' requires channel_id")`.
   - Расширить `export_repos()` context, чтобы также выдавать `RawMessageRepo` (или передать через DI). Решение: **добавить `raw_repo` в `export_repos()` context** ([`tg_parser/services/db_context.py`](../../tg_parser/services/db_context.py) — проверить, есть ли контекст; если нет — создать `raw_repo` inline через `Database.from_settings()` как и остальные).
   - `raw_messages = await raw_repo.list_by_channel(channel_id, from_date, to_date)`.
   - `channel_username = (await ingestion_repo.get_channel_usernames()).get(channel_id)`.
   - `format == NDJSON` → `export_raw_channel_ndjson`, `format == JSON` → `export_raw_channel_json`.
   - Return stats.
2. Если `level == PROCESSED`: существующий код, но **без** блока topics export (lines 166–210 — обернуть в `if level == ExportLevel.FULL`).
3. Если `level == FULL`: существующий код без изменений.

**Backward-compat:** любой caller, вызывающий `run_export(channel_id=...)` без `level`, получает `FULL` — byte-identical behaviour.

### 1.4 CLI

[`tg_parser/cli/app.py`](../../tg_parser/cli/app.py) — расширить `export` (строка 674):

```python
@app.command()
def export(
    out: str = typer.Option("./output", help="Директория вывода"),
    channel: str = typer.Option(None, help="Фильтр по каналу"),
    topic_id: str = typer.Option(None, help="Фильтр по теме"),
    from_date: str = typer.Option(None, help="Дата от (ISO format: YYYY-MM-DD)"),
    to_date: str = typer.Option(None, help="Дата до (ISO format: YYYY-MM-DD)"),
    pretty: bool = typer.Option(False, help="Pretty-print JSON"),
    level: str = typer.Option("full", help="Уровень: raw | processed | full (default)"),
    format: str = typer.Option("json", help="Формат: json | ndjson (для level=raw)"),
):
    """Экспортировать артефакты (TR-56..TR-64 + F2 Parse-Only).

    ``--level raw`` требует --channel; пишет raw_messages.{json,ndjson}.
    """
    from tg_parser.api.schemas import ExportLevel, ExportFormat

    try:
        level_enum = ExportLevel(level)
    except ValueError:
        typer.echo(f"❌ Неверный --level: {level} (ожидается: raw | processed | full)", err=True)
        raise typer.Exit(code=1)

    if level_enum == ExportLevel.RAW and not channel:
        typer.echo("❌ --level=raw требует --channel", err=True)
        raise typer.Exit(code=1)

    format_enum = ExportFormat(format)
    # ... existing date parsing + asyncio.run(run_export(...)) с новыми параметрами
```

Вывод статистики:
```python
if level_enum == ExportLevel.RAW:
    typer.echo(f"   • Posts: {stats['raw_posts_count']}")
    typer.echo(f"   • Comments: {stats['raw_comments_count']}")
    if stats['raw_orphan_comments_count']:
        typer.echo(f"   • Orphan comments (parent out of range): {stats['raw_orphan_comments_count']}")
    typer.echo(f"   • Файл: {out}/raw_messages.{format}")
```

### 1.5 API integration

[`tg_parser/api/routes/export.py`](../../tg_parser/api/routes/export.py):

- `_run_export_job` — прокидывать `level` + `from_date`/`to_date` в `run_export`, вычислять `export_file` по level:
  ```python
  export_stats = await run_export(
      output_dir=str(output_dir),
      channel_id=request.channel_id,
      level=request.level,
      format=request.format,
      from_date=request.from_date,
      to_date=request.to_date,
  )
  if request.level == ExportLevel.RAW:
      ext = "ndjson" if request.format == ExportFormat.NDJSON else "json"
      export_file = output_dir / f"raw_messages.{ext}"
  elif request.level == ExportLevel.PROCESSED or request.format == ExportFormat.NDJSON:
      export_file = output_dir / "kb_entries.ndjson"
  else:
      export_file = output_dir / "topics.json"
  ```
- `start_export` — при `body.level == RAW` валидация `body.channel_id is not None` (иначе `HTTPException(400, "level='raw' requires channel_id")`). `assert_channel_access(user, body.channel_id)` уже вызывается.
- `download_export` — расширить выбор `media_type` + `filename` на `raw_messages.{json,ndjson}`.
- `ExportResponse.level = body.level` — прокинуть в ответ.

**Rate-limit:** существующий `settings.rate_limit_export` не меняем — `raw`-экспорт на больших каналах может быть тяжёлым, но ограничение per-minute на 20 вызовов приемлемо (см. §Риски).

### 1.6 `db_context.py` / DI

Если `export_repos()` сейчас возвращает 4 репозитория — расширить до 5 (добавить `RawMessageRepo`):

```python
@asynccontextmanager
async def export_repos() -> AsyncGenerator[
    tuple[ProcessedDocumentRepo, TopicCardRepo, TopicBundleRepo, IngestionStateRepo, RawMessageRepo, Database],
    None,
]: ...
```

Альтернатива — отдельный context `raw_export_repos()`, если текущий tuple завязан на `ProcessedDocumentRepo` в других callers. Выбор — в plan-mode после чтения `db_context.py`.

### 1.7 Тесты Коммита 1

Новый файл `tests/test_f2_parse_only_export.py`:

- **`TestRawExportWriter`** (~8, no I/O кроме tmp_path):
  - `test_json_envelope_schema_version_present`.
  - `test_json_envelope_fields` — schema_version, channel_id, channel_username, exported_at, filters, messages_count, comments_count, messages[].
  - `test_post_with_comments_grouped_by_parent_message_id`.
  - `test_comments_sorted_by_date_within_post`.
  - `test_orphan_comments_bucket_when_parent_out_of_range`.
  - `test_ndjson_one_message_per_line_posts_first_then_comments`.
  - `test_pretty_flag_produces_indented_json` / `test_compact_json_no_indent`.
  - `test_raw_payload_excluded_by_default` — обеспечиваем что приватные Telethon-структуры не утекают.
  - `test_empty_messages_writes_valid_envelope` — fail-open: 0 messages → валидный JSON.

- **`TestGroupMessages`** (~4, pure function):
  - `test_post_with_no_comments`.
  - `test_multiple_comments_under_one_post_ordered_by_date`.
  - `test_orphan_comments_collected_separately`.
  - `test_multiple_posts_sorted_by_date`.

- **`TestExportServiceRaw`** (~5, requires Postgres fixture):
  - `test_run_export_level_raw_writes_json` — готовим 2 posts + 3 comments, вызываем `run_export(level=RAW)`, читаем `raw_messages.json`, проверяем структуру.
  - `test_run_export_level_raw_ndjson_writes_line_per_message`.
  - `test_run_export_level_raw_requires_channel_id` — ожидается `ValueError`.
  - `test_run_export_level_raw_respects_date_filter`.
  - `test_run_export_level_raw_channel_without_messages_returns_empty_envelope`.

- **`TestExportServiceBackwardCompat`** (~3):
  - `test_run_export_default_level_is_full_identical_to_pre_f2` — тот же набор файлов, что и раньше (`kb_entries.ndjson` + `topics.json` + `topic_<id>.json`).
  - `test_run_export_level_processed_skips_topics` — только `kb_entries.ndjson`, нет `topics.json`.
  - `test_run_export_default_call_signature_still_works` — `run_export(output_dir=..., channel_id=...)` без новых kwargs.

- **`TestCLIExportLevel`** (~3):
  - `test_cli_level_raw_requires_channel` — exit code != 0, stderr содержит ошибку.
  - `test_cli_invalid_level_rejected`.
  - `test_cli_invalid_format_rejected`.

- **`TestAPIExportLevel`** (~4, httpx TestClient):
  - `test_post_export_level_raw_creates_job`.
  - `test_post_export_level_raw_without_channel_returns_400`.
  - `test_get_status_includes_level`.
  - `test_download_raw_ndjson_has_correct_media_type_and_filename`.

### 1.8 Commit 1 message

```
feat(f2): add raw channel export (level=raw|processed|full) to service/CLI/API
```

---

## Коммит 2 — MCP + Bot tool + docs

### 2.1 MCP tool

[`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — новый `@mcp.tool()`:

```python
@mcp.tool()
async def export_channel(
    channel_id: str,
    level: str = "raw",
    format: str = "json",
    from_date: str | None = None,
    to_date: str | None = None,
    ctx: Context | None = None,
) -> ExportChannelResult:
    """Export channel contents at the specified level.

    Args:
        channel_id: Telegram channel ID (required).
        level: 'raw' | 'processed' | 'full' (default: 'raw' — parse-only).
        format: 'json' | 'ndjson' (for level='raw'; processed/full ignore this).
        from_date: ISO-8601 UTC datetime filter (optional).
        to_date: ISO-8601 UTC datetime filter (optional).

    Returns:
        {job_id, status, download_url, level, format}. Poll status with
        get_export_status until 'completed', then fetch via download_url.
    """
```

Внутри:
- Валидация `level` в `ExportLevel` → иначе `ValueError`.
- Валидация ownership: `await assert_channel_access(current_user, channel_id)`.
- Создать Job через `job_store.create_job(...)` + `asyncio.create_task(_run_export_job(job_id, request))` (как в HTTP-routes).
- Вернуть структурированный результат (`job_id`, `status="pending"`, `download_url=None`, `level`, `format`).

**Дополнительно:**
- `@mcp.tool() async def get_export_status(job_id: str) -> ExportStatusResult` — если такого tool'а ещё нет (проверить — `_job_status_to_api` в `api/routes/export.py` намекает на наличие).

### 2.2 Bot tool

[`tg_parser/bot/agent.py`](../../tg_parser/bot/agent.py) + [`tg_parser/bot/handlers/*`](../../tg_parser/bot/handlers/):

- Новый tool `export_channel(channel_id, level='raw', format='json', from_date=None, to_date=None)` — зовёт ту же логику что MCP + polls job до completion + пересылает файл в чат через aiogram `InputFile`:

```python
from aiogram.types import FSInputFile

async def _send_export_file_to_chat(chat_id: int, file_path: Path, filename: str):
    await bot.send_document(
        chat_id=chat_id,
        document=FSInputFile(file_path, filename=filename),
        caption=f"📎 {filename}",
    )
```

- Размер: Telegram Bot API лимит `send_document` = **50 MB**. Для больших экспортов возвращать `download_url` + короткий summary вместо файла (гейт по `file_size`).
- Two-phase confirmation **не требуется** — export read-only; всё же добавить progress-message ("⏳ Готовлю экспорт канала X, уровень raw...") до завершения фонового job'а.

### 2.3 Документация

- [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md) — новый раздел **"Parse-Only Export (F2)"**:
  - Что делает `--level raw`.
  - Структура envelope (schema_version, messages, orphan_comments).
  - NDJSON vs JSON: когда какой выбрать.
  - Примеры CLI / API / MCP / bot.
  - **Приватность:** `raw_payload` не включается.
- [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md) — секция по `export_channel`: параметры, workflow (submit → poll → download).
- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) — короткая заметка, что `OUTPUT_DIR` теперь содержит и `raw_messages.*` (новых env не добавляем).
- [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F2" — отметить DONE + добавить ссылку на PR.

### 2.4 Тесты Коммита 2

В `tests/test_f2_parse_only_export.py` добавить:

- **`TestMCPExportChannel`** (~4):
  - `test_mcp_export_channel_submits_job` — returns job_id + status=pending.
  - `test_mcp_export_channel_invalid_level_raises`.
  - `test_mcp_export_channel_ownership_enforced` — non-owner получает auth error.
  - `test_mcp_export_channel_defaults_to_raw_json`.

- **`TestBotExportChannel`** (~4, mocked aiogram `Bot`):
  - `test_bot_export_channel_small_file_sent_as_document`.
  - `test_bot_export_channel_large_file_returns_download_url` — 60 MB → НЕ send_document, возвращает URL.
  - `test_bot_export_channel_progress_message`.
  - `test_bot_export_channel_ownership_enforced`.

### 2.5 Commit 2 message

```
feat(f2): add export_channel MCP and bot tools with documentation
```

---

## Порядок работы

1. **Plan mode first** — свериться с актуальным `main`: номера строк в `export_service.py`, `routes/export.py`, `cli/app.py`, `api/schemas.py`; проверить наличие/форму `db_context.export_repos()`.
2. **Ветка** `feat/f2-parse-only-export` от актуального `main` (после мёрджа PR #9).
3. **Коммит 1 — имплементация:**
   - `ExportLevel` enum + `ExportRequest.level` + `ExportResponse.level` + `from_date`/`to_date`.
   - `tg_parser/export/raw_export.py` — writer + `_group_messages`.
   - `export_service.run_export` — `level`-branching; `export_repos()` расширить на `RawMessageRepo`.
   - CLI `export` — новые опции `--level`, `--format`, валидация.
   - API `routes/export.py` — проксирование `level`/`from_date`/`to_date` в `_run_export_job`; выбор файла по level; `ExportResponse.level`.
   - `TestRawExportWriter`, `TestGroupMessages`, `TestExportServiceRaw`, `TestExportServiceBackwardCompat`, `TestCLIExportLevel`, `TestAPIExportLevel` (TDD по возможности).
4. **Коммит 1 — local gate (первый прогон):**
   ```bash
   .venv/bin/pytest tests/test_f2_parse_only_export.py -x -q
   TEST_POSTGRES=1 .venv/bin/pytest \
     tests/test_f2_parse_only_export.py \
     tests/test_export*.py \
     tests/test_api_export*.py -x -q
   ```
5. **Коммит 1 — self-review loop (обязателен перед commit):**
   - Перечитать изменённый код (`raw_export.py`, `export_service.py` level-branching, API route, CLI) глазами "что ломается при `level=full` без `level=...` kwarg?".
   - Чек-лист покрытия:
     - [ ] **Backward-compat:** `run_export(channel_id=X)` без kwargs даёт байт-в-байт тот же набор файлов как до F2; fixture-тест с diff-по-файлам (или по стейту output-dir).
     - [ ] **Raw writer edge cases:** пустой канал, канал с 1 постом без комментариев, 1 комментарий без видимого parent (orphan), multiple parents, посты и комменты перемешанные по date.
     - [ ] **Date filter:** `from_date=None, to_date=None` — весь канал; `from_date=X, to_date=None` — с X до конца; только `to_date` — с начала до Y; обратный порядок (`from > to`) — пустой результат (без краша).
     - [ ] **NDJSON:** каждая строка — валидный JSON; нет лишних newlines; posts перед comments.
     - [ ] **`raw_payload` утечка:** явный assert `"raw_payload" not in json.loads(line)` для **каждой** записи в NDJSON и для каждого message в JSON envelope.
     - [ ] **CLI валидация:** `--level raw` без `--channel` → exit != 0, informative stderr; `--level foo` → ValueError с enum options.
     - [ ] **API 400:** POST `/export` с `{level: "raw"}` без `channel_id` → 400 с понятным `detail`.
     - [ ] **Ownership:** `assert_channel_access` вызывается при `level=raw` так же, как при `full` (тест: чужой user → 403).
     - [ ] **Regression:** существующие `test_export*.py`, `test_api_export*.py`, `test_cli_export*.py` не ломаются; если они полагались на старую сигнатуру `run_export` — kwarg'и должны быть backward-compat.
   - Если чек-лист обнаружил пробел — добавить тест/правку в том же коммите.
6. **Коммит 1 — re-run gate + full regression:**
   ```bash
   .venv/bin/pytest tests/test_f2_parse_only_export.py -x -q
   TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
   ```
   Ожидаемо ≥1510 passed (1487 baseline + ~25 новых в Commit 1). Если меньше — разобраться с регрессиями **до** коммита.
7. **Коммит 1 — commit** с указанным message.
8. **Коммит 2 — имплементация:**
   - MCP `export_channel` + (опц.) `get_export_status` tool.
   - Bot tool `export_channel` с `FSInputFile` + size-gate.
   - `TestMCPExportChannel`, `TestBotExportChannel`.
   - Docs: USER_GUIDE, MCP_AGENT_GUIDE, ENV_VARIABLES_GUIDE, FUTURE_FEATURES (F2 DONE).
9. **Коммит 2 — local gate (первый прогон):**
   ```bash
   .venv/bin/pytest tests/test_f2_parse_only_export.py -x -q
   .venv/bin/pytest tests/test_mcp*.py tests/test_bot*.py -x -q
   ```
10. **Коммит 2 — self-review loop (обязателен перед commit):**
    - Перечитать MCP-tool и Bot-tool с позиции "что может пойти не так в продакшене".
    - Чек-лист покрытия:
      - [ ] **MCP tool sig:** параметры соответствуют MCP-конвенциям проекта (см. существующие tools в `mcp_server.py`); возвращаемый структурированный тип определён и документирован.
      - [ ] **MCP auth:** `ctx.user_id` / `current_user` прокинут в `assert_channel_access` (по паттерну остальных MCP-tools).
      - [ ] **Bot size gate:** 50 MB лимит Telegram — тестом зафиксирован (mock file_size > 50 * 1024 * 1024 → НЕ `send_document`, возвращает URL).
      - [ ] **Bot polling:** progress message обновляется/удаляется корректно; timeout при длинном job'е.
      - [ ] **Docs consistency:** USER_GUIDE примеры для CLI/API/MCP/bot совпадают по параметрам; MCP_AGENT_GUIDE содержит workflow submit→poll→download.
      - [ ] **Rate limit:** упомянуть `rate_limit_export` (20/min) в USER_GUIDE для API-caller'ов.
    - Если чек-лист обнаружил пробел — добавить тест/правку в том же коммите.
11. **Коммит 2 — re-run gate + full regression:**
    ```bash
    .venv/bin/pytest tests/test_f2_parse_only_export.py -x -q
    TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
    ```
    Ожидаемо ≥1518 passed (1487 baseline + ~33 новых: 25 в Commit 1 + 8 в Commit 2). Если меньше — разобраться.
12. **Коммит 2 — commit** с указанным message.
13. **PR** против `main` → CI green → rebase-and-merge (паттерн Phase 1/2/3).

---

## Критерии готовности

1. `ExportLevel` enum (`raw` | `processed` | `full`) + `ExportRequest.level` default `full`; **backward-compat** существующих API-caller'ов.
2. `tg_parser/export/raw_export.py` — pure writer; JSON envelope v1 + NDJSON; `raw_payload` excluded; группировка comments + orphan bucket.
3. `run_export` — ветвление по `level`; для `RAW` требует `channel_id`; для `PROCESSED` skip topics; `FULL` — legacy поведение.
4. CLI `tg_parser export --level raw --channel X [--format ndjson|json] [--from-date] [--to-date]` — работает.
5. API `POST /api/v1/export {level, channel_id, format, from_date, to_date}` — создаёт job; status/download поддерживают raw-файлы.
6. MCP tool `export_channel(channel_id, level, format, from_date, to_date)` — job submission + ownership check.
7. Bot tool `export_channel` — file delivery через `FSInputFile` с size-gate 50 MB.
8. Документация: USER_GUIDE (F2 section), MCP_AGENT_GUIDE, ENV_VARIABLES_GUIDE (минимальное обновление), FUTURE_FEATURES (F2 DONE).
9. `tests/test_f2_parse_only_export.py` — ~33 теста (`TestRawExportWriter`, `TestGroupMessages`, `TestExportServiceRaw`, `TestExportServiceBackwardCompat`, `TestCLIExportLevel`, `TestAPIExportLevel`, `TestMCPExportChannel`, `TestBotExportChannel`); все проходят.
10. `TEST_POSTGRES=1 pytest tests/ -x -q` — ≥1518 passed; существующие export/api/cli/mcp/bot тесты не регрессируют.
11. **Self-review loop выполнен перед каждым коммитом** (шаги 5 и 10 в §"Порядок работы").
12. Два коммита с указанными messages; PR с green CI.

---

## Что НЕ входит в scope F2

- **Level=raw для всех каналов** (без `channel_id`) — отложено; требует `RawMessageRepo.list_all()` + paging/streaming стратегии (для больших корпусов JSON envelope не тянет). Если появится use-case — отдельная задача.
- **YAML формат** (`pyyaml` в deps уже есть) — легко добавляется, но не является основным use-case'ом; откладываем.
- **CSV формат** — плоская структура без `comments[]`, требует отдельного writer'а; отложено до явного запроса.
- **Streaming NDJSON через HTTP response** (вместо создания файла в `settings.output_dir`) — может быть нужен для очень больших каналов; Phase 2 оставляет batch-file-then-download паттерн.
- **`raw_payload` включение** через флаг `include_raw_payload` — приватность по умолчанию выше гибкости; если нужно — отдельный feature с строгим warning в USER_GUIDE.
- **Level=raw_plus_processed** (гибрид: raw + processed side-by-side) — не критично; `level=full` уже даёт processed view.
- **PROCESSED-level topics export** — намеренно skipped в `PROCESSED`: topics — это `FULL`-фича; разделение уровней даёт чистую semantics.
- **Incremental export** (только новые сообщения с прошлого запуска) — лучше решается через `--from-date $LAST_EXPORT_TIME` на стороне caller'а.

---

## Риски и митигация

| Риск | Митигация |
|---|---|
| Большие каналы (50K+ messages) → JSON envelope превышает разумный размер | NDJSON — primary рекомендация в USER_GUIDE для каналов с >10K messages; envelope лимитирован фильтрами `--from-date`/`--to-date` |
| `raw_payload` утечка приватных данных (Telethon session artifacts, file_refs) | Excluded by default через `model_dump(..., exclude={"raw_payload"})`; явный тест `test_raw_payload_excluded_by_default` |
| `export_repos()` сигнатура сейчас используется другими callers (топиковый экспорт, etc.) | Либо аккуратное добавление 5-го элемента + обновление всех callers, либо отдельный `raw_export_repos()`; решение по результатам чтения `db_context.py` в plan-mode |
| Telegram Bot API лимит 50 MB на `send_document` | Size-gate в bot-tool: `> 50 MB → return URL`; тест фиксирует |
| `rate_limit_export=20/min` может быть мало для raw-экспортов больших корпусов | Текущий лимит сохраняется; в USER_GUIDE — совет использовать CLI для больших экспортов вместо API |
| Orphan comments (parent-post вне date-range) теряются при наивной группировке | Отдельный bucket `orphan_comments` в envelope + тест; NDJSON orphan-агностичен (все messages как отдельные строки) |
| Обратная совместимость существующих API-caller'ов | `ExportRequest.level: ExportLevel = FULL` (дефолт) + `run_export` kwarg `level=FULL` по умолчанию; тест `test_run_export_default_call_signature_still_works` фиксирует |
| Ownership проверка не работает для `level=raw` (забыли вызвать `assert_channel_access`) | Явно вызываем в `start_export` **перед** созданием job'а (тот же паттерн что и `full`); тест `test_post_export_level_raw_ownership_enforced` |
| MCP-tool принимает `level="full"` и пытается экспортировать без ownership на topic/bundle | `assert_channel_access(user, channel_id)` — channel-scoped; topics/bundles этого канала вложены в ownership через channel_id |
| CLI `--format json` vs `--level processed` — формат игнорируется для PROCESSED | Документировать в `--help` и USER_GUIDE: `format` применим только к `level=raw`; для `processed`/`full` — всегда NDJSON для kb + JSON для topics (legacy) |
| Deserialization в MCP: `from_date="2026-01-15"` vs `"2026-01-15T00:00:00Z"` | Pydantic `datetime` на уровне `ExportRequest` покрывает оба случая; явный тест с ISO-only date |

---

## Связанные документы

- [`../notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F2: Channel Content Export (Parse-Only Mode)" — исходный design-doc.
- [`../notes/ROADMAP_V3_PRODUCTION_FIRST.md`](../notes/ROADMAP_V3_PRODUCTION_FIRST.md) §"Пост-F5-A Phase 3 — утверждённая последовательность (18 апреля 2026)" — место F2 в roadmap'е.
- [`F5A_PHASE3_IMPLEMENTATION_PLAN.md`](F5A_PHASE3_IMPLEMENTATION_PLAN.md) — эталон структуры plan-документа.
- [`../prompts/F2_PARSE_ONLY_EXPORT_PROMPT.md`](../prompts/F2_PARSE_ONLY_EXPORT_PROMPT.md) — стартовый промпт.
- PR #9 ([`feat/f5a-phase3-deduplication`](https://github.com/AlexEfimov/TG_parser/pull/9)) — prerequisite (merged).
