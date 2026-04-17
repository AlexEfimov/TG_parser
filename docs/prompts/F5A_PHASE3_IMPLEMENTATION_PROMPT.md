# F5-A Phase 3 Implementation — Стартовый промпт

**Версия проекта:** 4.5.0+ (после мёрджа Phase 2 в `main` — PR #8, ветка `feat/f5a-phase2-relevance-tuning`)
**Ветка:** `feat/f5a-phase3-deduplication` (создать от обновлённого `main`)
**План реализации:** [`docs/plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md`](../plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md) — **читать первым**
**Design-doc:** [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md) §5

---

## Цель

Добавить **exact-duplicate detection** в processing pipeline через SHA-256 content hash.
Устраняет шум в KB от пересылок, репостов и одинаковых объявлений в пределах канала.

1. Колонка `processed_documents.content_hash CHAR(64)` + B-tree индекс `(channel_id, content_hash)`.
2. Domain-level field `ProcessedDocument.content_hash: str | None`.
3. Pure-function `compute_content_hash(text_clean, *, normalize_urls=True) -> str` + `normalize_for_hash(text) -> str` (lowercase + collapse whitespace + strip URL query strings).
4. Pipeline-hook: после LLM-call до `upsert` проверяем `find_by_content_hash(channel_id, hash)` → если совпадение найдено, skip без записи в `processed_documents` + log-событие + Prometheus метрика.
5. Batch dedup: within-batch duplicates отсекаются перед `upsert_batch`.
6. Backfill для существующих данных — через новый CLI `tg_parser backfill-content-hash`.

---

## Коротко об архитектуре

```
message → process_message
          │
          ├── exists(source_ref)              ← TR-48 (already works)
          │       └─ hit → return existing doc
          │
          ├── _process_single_message          ← LLM call (text_clean produced)
          │       └─ assigns doc.content_hash = compute_content_hash(doc.text_clean)
          │
          ├── find_by_content_hash(channel_id, hash)     ← NEW
          │       └─ hit → log dedup_duplicate_found + metric + return existing_doc
          │
          └── upsert(doc)                       ← writes content_hash column
```

**Post-LLM dedup** (а не pre-LLM по `raw.text`):
- LLM-нормализация сглаживает форматирование, и именно `text_clean` — стабильный ключ.
- Экономия не в LLM-tokens, а в storage + качестве поиска (меньше дублей в top-K).
- Pre-LLM hash по raw — отложено на Phase 3.5 (опциональная оптимизация).

**Within-channel only:** один и тот же пост в двух каналах — **не** дубликат (multi-tenancy интуитивно правильна).

---

## Ключевые уточнения (после разведки)

- `processed_documents` **не имеет** `content_hash` сейчас (разведка: `tg_parser/storage/sqlalchemy/schemas/processing_storage.py:16-33`).
- Alembic миграции идут по цепочке — последняя для `processed_documents`: `20260417_add_fts_to_processed_documents.py` (`revision=d4e5f6a7b8c9`). Новая миграция Phase 3 — `down_revision="d4e5f6a7b8c9"`.
- `ProcessedDocument` (Pydantic) в `tg_parser/domain/models.py:105-158` — добавляем `content_hash: str | None`.
- `SAProcessedDocumentRepo.upsert` (строки 31-77) и `upsert_batch` (79-127) — нужно добавить `content_hash` в параметры INSERT; `_row_to_model` (270-291) — читать обратно.
- `ProcessedDocumentRepo` port в `tg_parser/storage/ports.py:373` — добавляем abstract `find_by_content_hash(channel_id, content_hash) -> ProcessedDocument | None`.
- Pipeline: `process_message` (`tg_parser/processing/pipeline.py:185`) делает `exists(source_ref)` check + LLM call + `upsert`. Phase 3 вставляет `find_by_content_hash` между LLM и `upsert`.
- Batch path: `_process_batch_parallel` (696-823) — после `gather(*llm_tasks)` и перед `upsert_batch` прогоняем within-batch dedup + DB-check.
- Legacy DDL в `processing_storage.py` (CREATE TABLE IF NOT EXISTS) + idempotent `_ensure_content_hash_column` — для fresh DBs и существующих без alembic history.
- Settings идут после `rag_search_overfetch_factor` (`tg_parser/config/settings.py:505-510`); следующая секция — `Ollama Configuration` (512+).
- **Visible behavior change #1:** дубликаты НЕ появятся в KB → `count_by_channel` после первой обработки будет меньше, чем `raw_messages` count. Намеренно.
- **Visible behavior change #2:** `process_batch(...)` возвращает список короче `len(messages)` при dedup skip (в отличие от уже-обработанных `source_ref`, которые подтягиваются post-hoc). Задокументировано.
- **`force=True` bypass'ит dedup** (и single, и batch) — явный reprocess не должен молча возвращать чужой existing doc при случайном hash-совпадении.
- **Single `self._db_lock`** вокруг `find_by_content_hash` + `upsert` в single-path — закрывает TOCTOU-окно.
- **НЕ делаем** write duplicate-marker row — skip полностью. Факт dedup виден через logs + metric. Таблица-реестр отложена.

---

## Структура работы (2 коммита)

### Коммит 1 — Schema + domain + hash utils + repo

**Файлы:**
- [`migrations/versions/processing/20260418_add_content_hash.py`](../../migrations/versions/processing/) (new) — `ALTER TABLE ADD COLUMN content_hash CHAR(64)` + composite B-tree index `(channel_id, content_hash)`. `down_revision="d4e5f6a7b8c9"`.
- [`tg_parser/storage/sqlalchemy/schemas/processing_storage.py`](../../tg_parser/storage/sqlalchemy/schemas/processing_storage.py):
  - Добавить `content_hash CHAR(64)` в `PROCESSING_STORAGE_DDL` CREATE TABLE.
  - Добавить `_ensure_content_hash_column(engine)` (идемпотентно `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
  - Подключить вызов в `init_processing_storage_schema`.
- [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py):
  - `ProcessedDocument.content_hash: str | None = Field(None, description="...", pattern=r"^[0-9a-f]{64}$")`.
- [`tg_parser/domain/hashing.py`](../../tg_parser/domain/hashing.py) (new):
  - `normalize_for_hash(text: str, *, strip_url_query: bool = True) -> str`
  - `compute_content_hash(text_clean: str, *, strip_url_query: bool = True) -> str` (SHA-256 hex)
- [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) (после строки 510):
  - `dedup_enabled: bool = True`
  - `dedup_strip_url_query: bool = True`
- `.env.example` — новый блок.
- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py):
  - `ProcessedDocumentRepo.find_by_content_hash(channel_id: str, content_hash: str) -> ProcessedDocument | None` — abstract.
- [`tg_parser/storage/sqlalchemy/processed_document_repo.py`](../../tg_parser/storage/sqlalchemy/processed_document_repo.py):
  - `upsert` + `upsert_batch`: добавить `content_hash` в INSERT/UPDATE.
  - `_row_to_model`: читать `content_hash`.
  - Все SELECT'ы (`get_by_source_ref`, `get_by_source_refs`, `list_by_channel`, `list_all`): добавить `content_hash` в projection.
  - Новый метод `find_by_content_hash`.
- Новый файл `tests/test_f5a_phase3_dedup.py` с классами (Commit 1 — ~23 теста):
  - `TestNormalizeForHash` (~7 pure unit-тестов)
  - `TestComputeContentHash` (~4)
  - `TestSettingsPhase3` (~3)
  - `TestProcessedDocumentDomainContentHash` (~2 — validator regex)
  - `TestProcessedDocRepoContentHash` (~4 — нужен Postgres fixture: upsert + roundtrip + find_by_content_hash + batch)
  - `TestMigrationIdempotency` (~3 — по образцу `tests/test_f5a_hybrid_search.py::TestMigrationIdempotency`: idempotent helper, `content_hash` column exists, `idx_pd_channel_content_hash` index exists)
- Расширить [`tests/test_migrations.py::test_init_processing_storage_schema`](../../tests/test_migrations.py) — добавить assertion что колонка `content_hash` создана после `init_processing_storage_schema` (ловит регрессию "забыли подключить `_ensure_content_hash_column`").

**Commit message:**
```
feat(f5a-phase3): add content_hash column, domain field, and normalization helpers
```

### Коммит 2 — Pipeline integration + backfill CLI + docs

**Файлы:**
- [`tg_parser/processing/pipeline.py`](../../tg_parser/processing/pipeline.py):
  - `_process_single_message`: после построения `ProcessedDocument` присвоить `processed.content_hash = compute_content_hash(processed.text_clean, strip_url_query=settings.dedup_strip_url_query)`.
  - `process_message`: между `_process_single_message` и `upsert` добавить dedup-check (only if `settings.dedup_enabled`) → на hit вернуть existing doc + log + metric + **не вызывать upsert**.
  - `_process_batch_parallel`: после `gather(llm_only_tasks)`, до `upsert_batch`, прогнать within-batch dedup (hash-map) + DB-check через batch-friendly lookup (N индекс-лукапов).
  - `_process_batch_sequential`: dedup уже покрывается через `process_message` (который вызывается в цикле).
- [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py):
  - `record_dedup_duplicate_detected(channel_id)` — новая Prometheus метрика `tg_dedup_duplicates_detected_total{channel_id}`.
- [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py):
  - Новая команда `tg_parser backfill-content-hash [--channel-id XXX] [--batch-size 500] [--dry-run]`.
- [`tg_parser/services/_wiring.py`](../../tg_parser/services/_wiring.py) или аналогичная точка — убедиться что настройки подхватываются (проверить совместимость).
- `tests/test_f5a_phase3_dedup.py` — дополнить классами (Commit 2 — ~17 тестов):
  - `TestDedupPipeline` (~7 интеграционных с моками repo): exact-duplicate skip, different-channel no-dedup, dedup_disabled bypass, empty text, None content_hash fallback, **force=True bypasses dedup**, metric emitted.
  - `TestBatchDedup` (~5): within-batch dedup, DB + within-batch сочетание (DB wins), batch без дубликатов, metric считается, **batch returns shorter list on skip**.
  - `TestBackfillCLI` (~4): dry-run не пишет, fills null hashes, `--channel-id` фильтр, **natural duplicates get same hash**.
  - `TestDedupMetric` (~1): Prometheus counter increments.
- [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md) — новая подсекция "Deduplication (F5-A Phase 3)".
- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) — `DEDUP_ENABLED`, `DEDUP_STRIP_URL_QUERY`.
- [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md) — короткая заметка что search не возвращает дубликаты.
- [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md) — Phase 3 DONE, что отложено в 3.5.

**Commit message:**
```
feat(f5a-phase3): integrate content-hash dedup into processing pipeline with backfill CLI
```

---

## Settings шпаргалка

```python
# В tg_parser/config/settings.py, после rag_search_overfetch_factor (~510)

# ==========================================================================
# Deduplication (F5-A Phase 3)
# ==========================================================================

dedup_enabled: bool = Field(
    default=True,
    description="Enable SHA-256 content-hash deduplication in processing pipeline (within-channel scope)",
)
dedup_strip_url_query: bool = Field(
    default=True,
    description="Strip URL query strings (?...#...) before hashing; catches tracking-param variants",
)
```

`.env.example`:
```bash
# --- F5-A Phase 3: Deduplication ---
DEDUP_ENABLED=true
DEDUP_STRIP_URL_QUERY=true
```

---

## `compute_content_hash` / `normalize_for_hash` спецификация

```python
# tg_parser/domain/hashing.py
import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")
# matches query string + fragment after a URL path
_URL_QUERY_RE = re.compile(r"(https?://[^\s?#]+)[?#][^\s]*")


def normalize_for_hash(text: str, *, strip_url_query: bool = True) -> str:
    """Deterministic normalization for content-hash.

    Order matters: URL strip first (while case preserved in path),
    then lowercase, then whitespace collapse.
    """
    if strip_url_query:
        text = _URL_QUERY_RE.sub(r"\1", text)
    text = text.lower()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def compute_content_hash(text_clean: str, *, strip_url_query: bool = True) -> str:
    """SHA-256 hex digest of normalized text_clean."""
    normalized = normalize_for_hash(text_clean, strip_url_query=strip_url_query)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

Ключевые тест-кейсы:
- `test_lowercase_folding` — `"Hello"` и `"hello"` дают один hash.
- `test_whitespace_collapse` — `"a  b"`, `"a\tb"`, `"a\nb"` → все одинаковые.
- `test_leading_trailing_whitespace_stripped`.
- `test_url_query_stripped_by_default` — `https://x.com/p?a=1` == `https://x.com/p`.
- `test_url_query_preserved_when_flag_off` — `strip_url_query=False` сохраняет `?a=1`.
- `test_url_fragment_also_stripped` — `https://x.com/p#frag` == `https://x.com/p`.
- `test_url_in_path_not_touched` — `https://x.com/some/path` без изменений.
- `test_empty_string_hash_is_deterministic`.
- `test_hash_is_64_char_hex`.

---

## Миграция Phase 3 — патч

```python
# migrations/versions/processing/20260418_add_content_hash.py

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"  # FTS migration

def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("processed_documents")]

    if "content_hash" not in columns:
        conn.execute(sa.text(
            "ALTER TABLE processed_documents ADD COLUMN content_hash CHAR(64)"
        ))

    # Composite B-tree: channel_id first — most queries filter by channel
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_pd_channel_content_hash "
        "ON processed_documents (channel_id, content_hash) "
        "WHERE content_hash IS NOT NULL"
    ))

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pd_channel_content_hash"))
    conn.execute(sa.text("ALTER TABLE processed_documents DROP COLUMN IF EXISTS content_hash"))
```

**Важно:**
- Колонка `NULL`-able — существующие записи без hash не блокируют миграцию; backfill выполняется отдельной CLI-командой.
- `WHERE content_hash IS NOT NULL` делает partial index — экономит размер до завершения backfill.
- Composite `(channel_id, content_hash)` — lookup-pattern: `WHERE channel_id=? AND content_hash=?`.
- `ALTER TABLE ADD COLUMN` с NULL-able и без `DEFAULT` — O(1) в Postgres 11+, не переписывает таблицу.
- `CREATE INDEX` (без `CONCURRENTLY`) берёт `ShareLock` — блокирует DML на время построения. Для production с высоким write-load рекомендуется pre-run `CREATE INDEX CONCURRENTLY` до `alembic upgrade` (тогда `IF NOT EXISTS` в миграции становится no-op). Задокументировать в deploy-runbook при rollout'е.

---

## Pipeline hook — форма кода

**Ключевые моменты:**
- **Один** `async with self._db_lock` вокруг check + `upsert` — иначе между
  релизом lock'а после `find_by_content_hash` и его повторным захватом в
  `upsert` другой concurrent task может вставить дубликат (TOCTOU race).
- **`force=True` bypass'ит dedup** — явный reprocess не должен возвращать
  чужой существующий doc, даже если новый hash случайно совпал.
- `existing.source_ref != message.source_ref` защищает от self-match
  при reprocess того же сообщения.

```python
# tg_parser/processing/pipeline.py — process_message, после _process_single_message:

processed = await self._process_single_message(message)

# Phase 3: content-hash dedup (post-LLM, within-channel).
# Single lock wraps both check and upsert to close the TOCTOU window.
async with self._db_lock:
    if (
        settings.dedup_enabled
        and processed.content_hash
        and not force  # explicit reprocess bypasses dedup
    ):
        existing = await self.processed_doc_repo.find_by_content_hash(
            channel_id=message.channel_id,
            content_hash=processed.content_hash,
        )
        if existing is not None and existing.source_ref != message.source_ref:
            from tg_parser.api.metrics import record_dedup_duplicate_detected

            record_dedup_duplicate_detected(channel_id=message.channel_id)
            logger.info(
                "dedup_duplicate_found",
                source_ref=message.source_ref,
                duplicate_of=existing.source_ref,
                channel_id=message.channel_id,
                content_hash=processed.content_hash,
            )
            return existing  # skip upsert

    await self.processed_doc_repo.upsert(processed)
    if self.failure_repo:
        await self.failure_repo.delete_failure(message.source_ref)
```

---

## Batch-path dedup — форма кода

**Ключевые моменты:**
- `force=True` bypass'ит `_filter_duplicates` — аналогично single-path.
- `_filter_duplicates` вызывается в serial post-gather фазе `_process_batch_parallel`
  → lock не нужен (совпадает с поведением `upsert_batch`, который сам тоже
  не оборачивается в `self._db_lock`).
- **Visible behavior change:** `process_batch(...)` может вернуть список
  короче `len(messages)`, если в батче есть дубликаты. Задокументировано в
  USER_GUIDE, зафиксировано тестом `test_batch_return_excludes_skipped_duplicates`.

```python
# tg_parser/processing/pipeline.py — _process_batch_parallel, после gather(llm_only_tasks):

new_docs = [r for r in completed_results if r is not None]

# Phase 3: within-batch + DB dedup (force bypasses)
if settings.dedup_enabled and new_docs and not force:
    new_docs = await self._filter_duplicates(new_docs)

# ... existing upsert_batch ...
```

Вспомогательный метод:

```python
async def _filter_duplicates(
    self, docs: list[ProcessedDocument]
) -> list[ProcessedDocument]:
    """Remove within-batch + DB duplicates; emit metrics and logs.

    Called in the serial post-gather phase of _process_batch_parallel;
    no db_lock needed (matches upsert_batch pattern).
    """
    from tg_parser.api.metrics import record_dedup_duplicate_detected

    seen_hashes: dict[tuple[str, str], str] = {}  # (channel_id, hash) → source_ref
    unique: list[ProcessedDocument] = []
    for doc in docs:
        if not doc.content_hash:
            unique.append(doc)
            continue
        key = (doc.channel_id, doc.content_hash)
        if key in seen_hashes:
            record_dedup_duplicate_detected(channel_id=doc.channel_id)
            logger.info(
                "dedup_within_batch_duplicate",
                source_ref=doc.source_ref,
                duplicate_of=seen_hashes[key],
                content_hash=doc.content_hash,
            )
            continue
        existing = await self.processed_doc_repo.find_by_content_hash(
            channel_id=doc.channel_id, content_hash=doc.content_hash
        )
        if existing is not None and existing.source_ref != doc.source_ref:
            record_dedup_duplicate_detected(channel_id=doc.channel_id)
            logger.info(
                "dedup_db_duplicate",
                source_ref=doc.source_ref,
                duplicate_of=existing.source_ref,
                content_hash=doc.content_hash,
            )
            continue
        seen_hashes[key] = doc.source_ref
        unique.append(doc)
    return unique
```

---

## Backfill CLI

```
tg_parser backfill-content-hash [--channel-id ID] [--batch-size 500] [--dry-run]
```

**Pagination:** cursor-style, **НЕ `OFFSET`**. После каждого UPDATE-батча
набор `WHERE content_hash IS NULL` сокращается — `OFFSET` пропустил бы
строки между итерациями. Используется repeat-select до пустого результата.

Алгоритм:
1. Цикл:
   ```sql
   SELECT source_ref, channel_id, text_clean
   FROM processed_documents
   WHERE content_hash IS NULL [AND channel_id=:cid]
   ORDER BY source_ref
   LIMIT :batch_size
   ```
   Завершение — когда SELECT вернёт 0 строк.
   Для `--dry-run` (UPDATE не выполняется) — cursor по `source_ref > :last_seen`,
   иначе цикл будет бесконечным.
2. Для каждой записи: `compute_content_hash(text_clean, strip_url_query=settings.dedup_strip_url_query)`.
   Пустой `text_clean` → skip (counter `total_skipped_empty_text`).
3. Если `dry_run=False`: `UPDATE processed_documents SET content_hash=:h WHERE source_ref=:sr`, commit per batch.
4. Progress-bar (rich or plain counter) — количество записей + ETA.
5. Итоговая сводка: `total_scanned`, `total_hashed`, `total_skipped_empty_text`, `elapsed_sec`.
6. Ничего не удаляет — пост-backfill дубликаты остаются в таблице; отдельная
   стадия `--prune-duplicates` отложена на Phase 3.5 (намеренно не включено
   в `backfill-content-hash`).

Тесты `TestBackfillCLI`:
- `test_backfill_dry_run_does_not_write` — 3 NULL-записи; после `--dry-run`
  все 3 остались NULL.
- `test_backfill_fills_null_hashes` — без флагов; все записи получают
  валидный 64-char hash.
- `test_backfill_channel_filter_scopes_update` — `--channel-id A`: только
  канал A обновлён.
- `test_backfill_existing_duplicates_all_get_same_hash` — 2 существующих
  doc'а с идентичным `text_clean` получают одинаковый hash (prune не делаем).

---

## Тесты

| Класс | Кейсов | Requires Postgres? |
|---|---|---|
| `TestNormalizeForHash` | ~7 | no |
| `TestComputeContentHash` | ~4 | no |
| `TestSettingsPhase3` | ~3 | no |
| `TestProcessedDocumentDomainContentHash` | ~2 | no |
| `TestProcessedDocRepoContentHash` | ~4 | yes (fixture `pg_processed_doc_repo`) |
| `TestMigrationIdempotency` | ~3 | yes (fixture `test_db`) |
| `TestDedupPipeline` | ~7 (incl. `test_force_reprocess_bypasses_dedup`) | no (mocks repo) |
| `TestBatchDedup` | ~5 (incl. `test_batch_return_excludes_skipped_duplicates`) | no (mocks repo) |
| `TestBackfillCLI` | ~4 (incl. `test_backfill_existing_duplicates_all_get_same_hash`) | yes |
| `TestDedupMetric` | ~1 | no |
| `test_init_processing_storage_schema` (extension) | +1 assertion | yes |

**Запуск:**
```bash
# Unit
.venv/bin/pytest tests/test_f5a_phase3_dedup.py::TestNormalizeForHash tests/test_f5a_phase3_dedup.py::TestComputeContentHash tests/test_f5a_phase3_dedup.py::TestSettingsPhase3 tests/test_f5a_phase3_dedup.py::TestProcessedDocumentDomainContentHash tests/test_f5a_phase3_dedup.py::TestDedupPipeline tests/test_f5a_phase3_dedup.py::TestBatchDedup tests/test_f5a_phase3_dedup.py::TestDedupMetric -x -q

# Full with Postgres
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

**Ожидаемо:** 1346 → ~1386 (добавляется ~40 тестов в `test_f5a_phase3_dedup.py` + расширение существующего smoke-теста `test_init_processing_storage_schema`).

---

## Существующие тесты — риски

- `tests/test_processing_pipeline.py` — создаёт `ProcessedDocument` без `content_hash` (None дефолт) — не должно ломаться, но проверить.
- `tests/test_processed_document_repo.py` — прогонять `upsert` + `_row_to_model` roundtrip; обновить если фиксирует точный SQL.
- `tests/test_postgres_integration.py` — может потребовать обновления schema-setup fixture на новый ALTER TABLE.

Стратегия: пробежать `pytest tests/test_processing*.py tests/test_processed_document*.py -x -q` до и после правок — если поломалось, исправлять в том же коммите.

---

## Критерии готовности

1. Миграция `20260418_add_content_hash.py` применяется/откатывается идемпотентно; composite index создан; `test_content_hash_column_exists` проходит.
2. `ProcessedDocument.content_hash` — опциональное поле с regex `^[0-9a-f]{64}$`; невалидные значения отклоняются Pydantic-валидатором.
3. `compute_content_hash` — pure function; детерминистична; все нормализационные правила покрыты тестами; length всегда 64.
4. `SAProcessedDocumentRepo.find_by_content_hash` — composite-index lookup; возвращает `None` если нет match; null-hash записи игнорируются.
5. `upsert` / `upsert_batch` / все SELECT-ы пишут/читают `content_hash` без регрессии; existing roundtrip-тесты зелёные.
6. `_process_single_message` присваивает `content_hash` всегда (кроме media-only? — определить в плане: media-only doc без `text_clean` получает hash пустой строки или `None`).
7. `process_message` при `dedup_enabled=True` и совпадении hash в пределах того же канала пропускает `upsert` и возвращает existing doc; при разных каналах — **не** дедупит.
8. `_process_batch_parallel` отсекает within-batch дубликаты перед `upsert_batch`.
9. Метрика `tg_dedup_duplicates_detected_total{channel_id}` увеличивается при каждом detect.
10. CLI `backfill-content-hash` с `--dry-run` не пишет; без флага — заполняет `content_hash` батчами.
11. Новый файл `tests/test_f5a_phase3_dedup.py` — ~40 тестов (включая `TestMigrationIdempotency`, `test_force_reprocess_bypasses_dedup`, `test_batch_return_excludes_skipped_duplicates`, `test_backfill_existing_duplicates_all_get_same_hash`); все проходят.
12. `tests/test_migrations.py::test_init_processing_storage_schema` расширен assertion'ом на колонку `content_hash`.
13. Полный regression `TEST_POSTGRES=1 pytest tests/ -x -q` — не ниже 1386 passed **ПЕРЕД каждым из двух коммитов** (не только перед финальным).
14. **Self-review loop выполнен** перед каждым коммитом: (а) первый прогон новых тестов → (б) перечитать код + тесты по чек-листу фазы → (в) при необходимости добавить тесты/правки → (г) повторный прогон новых тестов → (д) полный regression → (е) commit. Детали — §"Рекомендации исполнения" п. 12.
15. Документация: USER_GUIDE (Deduplication), ENV_VARIABLES_GUIDE (2 env), MCP_AGENT_GUIDE (короткая заметка), F5A_PERSISTENT_KB_PLAN (Phase 3 DONE).
16. Два коммита с указанными messages.

---

## Что НЕ входит в scope Phase 3

- **Near-duplicate** через embedding cosine ≥ 0.97 — Phase 3.5 (или отложено до мониторинга).
- **Pre-LLM raw-text hash** (экономия LLM tokens) — Phase 3.5 как опциональный feature (`DEDUP_PRE_LLM_RAW_HASH`).
- **Cross-channel deduplication** — намеренно не делаем (multi-tenancy требует keep-separate).
- **Duplicate-tracking table** (реестр пар orig/dup с timestamps) — отложено.
- **Prune existing duplicates** в бэкфилле — `backfill-content-hash` только заполняет hash; удаление дубликатов — отдельная команда/решение.
- **Dedup metadata в embeddings** (если переобрабатываем дубль — не перегенерируем embedding) — уже покрывается skip-логикой на уровне processed_documents.
- **Near-dedup через MinHash / SimHash** — не применимо для Telegram текстов (короткие, мало signal).
- **Auto-detect reposts через `message.forward_from_*`** — оставляем как чистый content hash, без метаданных.

---

## Рекомендации исполнения

1. **Plan mode first** — сверить номера строк в `processing/pipeline.py`, `processed_document_repo.py`, `settings.py` с актуальным `main`.
2. **TDD для `compute_content_hash`** — pure function, 8+ тестов сразу, потом реализация. Ноль dependencies → быстрый цикл.
3. **Порядок Commit 1:** миграция → domain model → hash utils → settings → port → repo → tests. Каждый шаг gated unit-тестами.
4. **Порядок Commit 2:** pipeline hook (single) → `_filter_duplicates` (batch) → metric → backfill CLI → docs. Mock repo в pipeline-тестах по образцу `tests/test_processing_pipeline.py`.
5. **Постгресные тесты** (`TestProcessedDocRepoContentHash`, `TestBackfillCLI`) — использовать существующий `pg_session` fixture; убедиться что DDL helper `_ensure_content_hash_column` вызывается в setup.
6. **Media-only documents** (`_build_media_only_document` в pipeline.py) — решить в плане: hash по синтетическому descriptor `"[Фото]"` / пропустить. Рекомендация: **hash computed normally** — позволяет отловить повторные media-только сообщения с одинаковым descriptor.
7. **Backward-compat** — `dedup_enabled=False` полностью bypass'ит логику; существующее поведение сохраняется byte-for-byte.
8. **Metric registry** — проверить что `record_dedup_duplicate_detected` использует существующий Prometheus registry из `tg_parser/api/metrics.py`; не городить новый.
9. **Backfill CLI** — batched с commit каждые N rows; graceful на `KeyboardInterrupt` (SIGINT fllush last batch + log progress).
10. **Логи dedup** — `structlog` уровень `info`; избегать попадания `text_clean` в логи (PII); только `source_ref`, `duplicate_of`, `content_hash`, `channel_id`.

### 11. Batch return shorter than input — намеренное поведение

`process_batch(...)` возвращает список короче `len(messages)`, если в батче
обнаружены дубликаты (они не добавляются в `results` post-hoc, в отличие
от already-existing `source_ref`, которые подтягиваются через `get_by_source_ref`).
Caller интерпретирует diff как "N на вход, M осталось после dedup".
Задокументировано в USER_GUIDE; fixed тестом `test_batch_return_excludes_skipped_duplicates`.
Если в Phase 3.5 потребуется — можно добавить подтяжку "существующего doc,
с которым совпал hash" по аналогии с already-processed фазой.

### 12. Self-review loop (обязателен перед каждым коммитом)

После того как новые тесты впервые прошли локально, **ДО** коммита:

1. **Первый прогон тестов** — убедиться что новые тесты зелёные:
   ```bash
   .venv/bin/pytest tests/test_f5a_phase3_dedup.py -x -q
   ```
2. **Self-review** — перечитать **весь** новый и изменённый код + новые тесты. Оценить покрытие по чек-листу фазы:
   - **Commit 1 чек-лист:** edge cases pure-функций (empty/unicode/long/multi-URL), Pydantic валидатор (границы длины, uppercase, non-hex, None), repo roundtrip (NULL↔None, conflict-update, partial-index miss), migration idempotency (повторный вызов, колонка создана, downgrade чистый).
   - **Commit 2 чек-лист:** pipeline single-path (`dedup_enabled=False` bypass, empty hash, self-match, **`force=True` bypass**, metric-once, cross-channel no-dedup, log без `text_clean`, **single lock вокруг check+upsert**), batch-path (within-batch + DB interplay с DB-wins, order preservation, `force=True` bypass, **batch return shorter on skip**), backfill CLI (`--dry-run` без UPDATE, **cursor-pagination вместо OFFSET**, `--channel-id` scope, already-hashed skip, **natural duplicates same hash**, KeyboardInterrupt), metric cardinality, regression в существующих processing/pipeline/batch-tests.
   - Детальные чек-листы — в [`F5A_PHASE3_IMPLEMENTATION_PLAN.md`](../plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md) §"Порядок работы" шаги 4 и 9.
3. **Добавить недостающие тесты** или поправить код, если чек-лист обнаружил пробелы. Это часть текущего коммита, не отдельный.
4. **Повторный прогон новых тестов** — убедиться что доработки зелёные:
   ```bash
   .venv/bin/pytest tests/test_f5a_phase3_dedup.py -x -q
   ```
5. **Полный regression перед коммитом** — **обязателен**, ловит регрессии в существующих processing/pipeline/migration-тестах:
   ```bash
   TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
   ```
   Ожидаемо после Commit 1: ≥1369 passed (1346 + 23 новых). После Commit 2: ≥1386 passed.
6. **Commit** только после зелёного полного прогона.

Этот цикл применяется к **каждому** коммиту (Commit 1 и Commit 2 отдельно). Тот же паттерн, который мы использовали в Phase 1 и Phase 2 — он явно ловит "тесты зелёные, но мы забыли edge case" и "наш новый код сломал что-то в existing suite".
