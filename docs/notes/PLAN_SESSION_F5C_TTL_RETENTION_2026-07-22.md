# Plan — Session: F5-C #15 TTL/retention for `topic_card_versions`

**Дата:** 2026-07-22 · **Тип:** implementation planning note (pre-START_PROMPT) · **Branch:** `main` (docs-only planning; commit/PR — **только** по явному запросу пользователя, [`AGENTS.md`](../../AGENTS.md))

**Goal (одной строкой):** спроектировать конфиг-driven retention/TTL для append-only `topic_card_versions`, который ограничивает неограниченный рост истории, сохраняя genesis+recent provenance-floor и не ломая `get_topic_versions` / re-summarize идемпотентность.

> **Статус решений:** все 6 owner-decisions **приняты** (2026-07-22, см. §9) — план полностью специфицирован. Impl-код/миграция/prod-DELETE выполняются в **отдельной реализующей сессии**; сам план — docs-only. Прод-purge (`RETENTION_DAYS>0`) остаётся под in-session owner GO после backup+dry-run (execution-gate, не design-gate).

> Этот документ = **план сессии реализации** (что и как делать, финальные решения, blast-radius, acceptance). Он превращает ζ-скелет [`SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`](SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md) в исполнимый бриф.

---

## 1. Контекст и why-now

- **MVP-решение:** «храним всё». Каждый успешный re-summarize (`outcome=ok`) пишет **одну** строку в `topic_card_versions` (snapshot *предыдущего* состояния), до `commit_resummary`. Роста history-таблицы ничем не ограничен (issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #1).
- **Freshness-петля усилила рост.** Track δ/T7 закрыт 2026-07-22: `RESUMMARIZE_MAX_AGE_DAYS` bumped `14 → 21` LIVE ([`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md)). Age-ветка даёт ~99% re-summarize mix (`ratio14d≈0.99`), несколько каналов age-dominated (`labdiagnostica_logical`≈24/day, `mediamedics`≈11/day). **Больше age-триггеров ⇒ больше `outcome=ok` ⇒ быстрее растёт `topic_card_versions`.** TTL логически продолжает freshness-петлю: чем длиннее cutoff, тем важнее bound на историю.
- **Priority (owner decision #6, final):** TTL — **следующий #15 item к реализации**, впереди diff-API (#2) и Bot-tools (#5). Обоснование: рост history — **ops-adjacent** и измерим (runbook §4 SQL snapshot), самый близкий к ops parking-lot slice, и он логически продолжает только что закрытую freshness-петлю. (ROADMAP **Next** обновляется в impl-сессии — не из этого плана.)

**Единственный read-path** истории: `TopicCardVersionRepo.list_by_topic(topic_id, limit=50)` → MCP `get_topic_versions(topic_id, limit=10)` + CLI `tg-parser topic versions`. Никакой другой сервис (F11 watchlist, F6 digest, RAG) не читает `topic_card_versions`.

---

## 2. Схема и текущее поведение (anchored, verified)

`topic_card_versions` (migration `a4b5c6d7e8f9`, processing-ветка; [`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) L688):

| Column | Тип | Примечание |
|---|---|---|
| `id` | BIGSERIAL PK | surrogate |
| `topic_id` | TEXT FK→`topic_cards.id` **ON DELETE CASCADE** | topic-drop чистит историю |
| `version_no` | INTEGER | монотонный per-topic (`summary_version` на `topic_cards`) |
| `summary`, `scope_in_json`, `scope_out_json` | TEXT | snapshot *предыдущего* состояния |
| `supporting_items_count_at_time` | INTEGER | |
| `llm_provider`, `llm_model`, `prompt_version` | NULLable | provenance |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | DB-clock authoritative |

**Constraints/index:** `UNIQUE(topic_id, version_no)` (`uq_topic_card_versions_topic_version`); `Index idx_topic_card_versions_topic_created (topic_id, created_at DESC)`.

**Write-path** ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L582-618): advisory-lock `pg_try_advisory_xact_lock(0xF5C, hashtext(topic_id))` (первая линия), затем `insert(snapshot)`; `UNIQUE(topic_id, version_no)` — вторая линия против гонок. Никогда не update/renumber.

**Precedent для purge:** [`cleanup_stale_idempotency_keys`](../../tg_parser/services/scheduler_service.py) (ADR-0009 Q-OPEN-2) — cron-hook: `delete_older_than(cutoff)` + `count()` → gauge `tg_idempotency_keys_table_size`; регистрируется в [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py) через `add_cron_task`. **TTL-purge зеркалит этот паттерн точь-в-точь.**

---

## 3. Policy design — финальные решения

### 3.1 Retention rule — **C: hybrid keep-last-N ∧ older-than-M ∧ genesis-pin** (owner decision #5, final)

| Option | Правило DELETE | Pros | Cons |
|---|---|---|---|
| A. Time-TTL only | `created_at < now - M days` | простой mental model, matches age-family | стирает историю холодных тем целиком; нет floor |
| B. Keep-last-N only | `version_no <= max_version_no - N` per topic | защищает свежую историю hot-тем | глобальный диск растёт с кардинальностью тем; старые темы держат N навсегда |
| **C. Hybrid + genesis-pin (ВЫБРАНО)** | **DELETE iff `rn > N` (по `version_no DESC` per topic) AND `created_at < now - M days` AND `version_no > 1`** | provenance-floor (≥ N последних per topic) + глобальный time-bound + genesis (`version_no = 1`) навсегда; строка удаляется только если провалила **все три** защиты | больше knobs; acceptance-матрица шире |

**Финальный retention-predicate (v1, канонический — использовать дословно везде):**

> Строка версии удаляется **iff** она (a) **вне** N новейших версий своей темы **AND** (b) старше M дней **AND** (c) `version_no > 1` — то есть genesis-snapshot (`version_no = 1`) **никогда** не purge.

Значит: последние N per topic сохраняются **навсегда** независимо от возраста; ничего младше M дней не удаляется независимо от count; **первый (genesis) snapshot каждой темы сохраняется навсегда** независимо от N/M. Это минимальный destructive footprint с полной genesis-provenance.

**Genesis-pin rationale (decision #5):** пин стоит ~ноль storage (+1 строка на тему) и сохраняет full-lifetime genesis-provenance именно для **hot+old** тем — там, где diff-история (origin → current) наиболее ценна.

Purge SQL (window-CTE, v1 с genesis-pin):
```sql
WITH ranked AS (
  SELECT id, version_no,
         row_number() OVER (PARTITION BY topic_id ORDER BY version_no DESC) AS rn
  FROM topic_card_versions
)
DELETE FROM topic_card_versions t
USING ranked r
WHERE t.id = r.id
  AND r.rn > :keep_last_n                                       -- вне новейших N
  AND t.created_at < (now() - make_interval(days => :retention_days))  -- старше M дней
  AND t.version_no > 1;                                          -- genesis-pin: version_no=1 никогда
-- dry-run: SELECT count(*) с тем же WHERE вместо DELETE
```

**Perf note:** window-CTE ранжирует **всю** таблицу за проход (full scan независимо от индекса). Для daily cron на MB-scale приемлемо, но зафиксировать как watch-item: при росте в GB-territory оптимизировать (например ранжировать только темы с `> N` версий через pre-agg `HAVING count(*) > N`, или batched delete). Индекс `idx_topic_card_versions_topic_created` помогает partition-order, но не устраняет scan.

**Который knob — доминирующий:** строки младше M дней сохраняются **все** ⇒ для **hot** тем (age-dominated: `labdiagnostica_logical`≈24/day) реальный per-topic bound ≈ `rate × M` (при M=180 → 24 × 180 ≈ 4320 строк), а keep-last-N здесь почти не срабатывает. Для **cold** тем (редкий re-summarize) наоборот: time-window ничего не режет, работает keep-last-N floor. genesis-pin добавляет ровно +1 строку на тему поверх обоих. Вывод: **M (retention_days) — главный лева́р глобального роста; keep-last-N — recent-floor; genesis-pin — origin-floor.**

### 3.2 Delete mode: **hard DELETE, zero schema-change** (owner decision #2, final)

- **Hard DELETE** ⇒ true reclaim, **ноль schema-changes** (нет `deleted_at`-колонки, нет фильтра во всех readers), проще backward-compat. Необратимо → mitigated dry-run + backup перед первым prod-запуском.
- **MVP без Alembic-миграции:** hard-DELETE не требует schema-change; migration остаётся **OUT-by-default** (см. §5, §6). Soft-delete отвергнут (требует колонку + миграцию + `WHERE deleted_at IS NULL` во всех read-path, не даёт disk-reclaim).

### 3.3 Defaults + chosen prod numbers (owner decision #1, final)

| Knob (env / Settings) | Code default | **Prod (owner-chosen)** | Семантика |
|---|---|---|---|
| `RESUMMARIZE_VERSION_RETENTION_DAYS` / `resummarize_version_retention_days` | **`0`** | **`180`** | `0` = **purge DISABLED** (kill-switch; bit-for-bit MVP «храним всё»). `>0` = удалять строки старше M дней (в связке с keep-last-N ∧ genesis-pin). |
| `RESUMMARIZE_VERSION_KEEP_LAST_N` / `resummarize_version_keep_last_n` | **`50`** | **`50`** | recent-floor: всегда держать ≥ N новейших версий per topic. Активен только при retention_days > 0. |

**Default = no-op:** code-default `RETENTION_DAYS=0` ⇒ деплой кода **ничего не удаляет** пока owner явно не выставит prod-value `180`. Это выполняет «no destructive default» + встроенный kill-switch. Prod-числа (conservative): **M = 180 дней, N = 50 версий**.

**Interaction с freshness knob (constraint holds):** M должен быть **≫** текущего prod `RESUMMARIZE_MAX_AGE_DAYS`. Sanity floor `RETENTION_DAYS ≥ 2 × RESUMMARIZE_MAX_AGE_DAYS`: MAX_AGE_DAYS LIVE=21 ⇒ 2× = **42 ≤ 180 ✓**. `RESUMMARIZE_MAX_AGE_DAYS` — prod env-value (code-default 0), может измениться на re-watch ≈2026-08-05, поэтому constraint проверять **читая значение из Settings в runtime, не хардкодить 21**. Задокументировать в Settings-description + runbook.

---

## 4. Karpathy checklist impact (ADR-0006)

| Принцип | Impact / gate |
|---|---|
| **#1 Persistent entities** | Versions остаются first-class rows; retention — lifecycle policy, не демоция в blob. ✅ |
| **#2 Provenance/evidence** | **Критично — двойной floor.** recent-floor (keep-last-N) **+** origin-floor (genesis-pin `version_no=1`). Задокументировать в ADR-0018 + runbook: «версии старше M, вне последних N, с `version_no > 1` считаются reclaimed by policy, не потеряны багом; genesis (`version_no=1`) сохраняется навсегда». |
| **#4 / ADR-0009 Idempotency** | Purge идемпотентен (повторный запуск удаляет 0). Purge работает только над **sealed** старыми строками (`rn > N`, `version_no > 1`) — никогда над новейшей версией (in-flight re-summarize) и никогда над genesis. `UNIQUE(topic_id, version_no)` не трогаем, `version_no` не renumber. |
| **#6 Observability** | Purge эмитит: gauge (row count post-purge), counter (deleted total), duration + structured log. Karpathy measure→decide петля продолжает T7. |

**ADR decision (owner decision #4, final): новый ADR-0018 «topic_card_versions retention policy».** Подтверждено: **0018 — следующий свободный номер** в `docs/adr/` (последний = [ADR-0017](../adr/0017-dependency-management-policy.md)). Retention — нормативное решение о минимуме сохраняемого provenance (взаимодействует с ADR-0006 #2); проект ведёт ADR-per-decision (0009 idempotency, 0017 dep-policy). **Полный ADR-0018 пишется в impl-сессии** (status `Proposed`); в этом plan/START_PROMPT — только reference-stub, не сам файл (docs-only planning). Addendum к ADR-0006 **отклонён** в пользу отдельного ADR.

---

## 5. Blast-radius

| Surface | Touch? | Notes |
|---|---|---|
| Alembic (processing-ветка) | **Опционально / нет для MVP** | Hard-DELETE не требует schema-change. Существующий `idx_topic_card_versions_topic_created (topic_id, created_at DESC)` покрывает partition-scan. Новую миграцию (доп. индекс) добавлять **только** если `EXPLAIN` на prod-объёме покажет seq-scan боль — иначе OUT. |
| `TopicCardVersionRepo` | **Yes** | Новый метод `purge_stale(keep_last_n, older_than) -> int` (port + SA impl). `list_by_topic` не меняется. |
| Scheduler | **Yes** | Новый `purge_stale_topic_card_versions()` в [`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) (зеркало `cleanup_stale_idempotency_keys`); регистрация cron в [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py). Daily cadence. Skip when `retention_days == 0`. |
| Settings | **Yes** | 2 knob'а в F5-C блоке [`settings.py`](../../tg_parser/config/settings.py) (~L1090-1145, рядом с `resummarize_max_age_days`). |
| Metrics | **Yes** | Новые `tg_topic_card_versions_rows` (gauge), `tg_topic_card_versions_purged_total` (counter), purge duration/log в [`api/metrics.py`](../../tg_parser/api/metrics.py). Grafana Panel 4 wiring (row count — сейчас manual SQL) — **optional**, если provisioning уже существует. |
| MCP `get_topic_versions` / CLI `topic versions` | **No code change** | Возвращает оставшиеся строки; gaps в `version_no` = policy, не crash. Задокументировать в tool-описании / runbook. |
| F11 watchlist / F6 digest / RAG / workspaces | **No** | Не читают `topic_card_versions`. |
| `topic_cards.summary_version` | **No** | Монотонный счётчик не сбрасывается; удаляем только history-строки. |
| Prod data | **Never без backup + dry-run** | Первый prod-purge: read-only projection → CLI `--dry-run` → backup (`pg_dump` таблицы) → реальный запуск. **Hard-DELETE необратим:** «rollback» = только остановка будущих purge (`RETENTION_DAYS=0`); уже удалённые строки восстановимы **только** из backup. |
| CLI | **Yes (recommended)** | `tg-parser topic purge-versions [--dry-run]` — manual/dry-run путь до включения cron. |

**Concurrency safety:** purge — отдельная транзакция, DELETE только строк `rn > N` **AND** `version_no > 1` (sealed старые, кроме genesis); row-locks не пересекаются с insert новейшей версии под advisory-lock. Никакого renumber. F5-C write-path не блокируется.

---

## 6. Session steps (execution outline для impl-сессии)

1. **Baseline (read-only).** runbook §4 SQL snapshot: `COUNT(*)`, `pg_total_relation_size`, `COUNT(DISTINCT topic_id)`, `MAX/AVG(version_no)`, rows/day из `tg_resummarize_total{outcome="ok"}`. Спроектировать GB/year. Зафиксировать в snapshot-note.
2. **ADR-0018 draft** — новый файл `docs/adr/0018-topic-card-versions-retention.md`: retention policy (rule C, hard-DELETE zero-schema, defaults, double floor genesis+recent); status `Proposed`.
3. **Settings** — 2 knob'а (code-default `RETENTION_DAYS=0`, `KEEP_LAST_N=50`) + description с sanity floor (≥ 2× max_age_days, читать из Settings).
4. **Repo** — `purge_stale(keep_last_n, older_than)` (port + SA impl, window-CTE §3.1 с `version_no > 1`) + unit-тест (проверить floor: последние N, <M-days, и genesis `version_no=1` сохраняются).
5. **Scheduler** — `purge_stale_topic_card_versions()` + cron-регистрация (daily); skip при `retention_days==0`. Test на skip-path + on-path.
6. **Metrics** — gauge/counter/log; wire Panel 4 gauge (**optional** — если provisioning уже есть).
7. **CLI** — `topic purge-versions [--dry-run]`.
8. **Docs** — runbook §T7/§4 purge/ops-секция + growth note; FUTURE_FEATURES F5-C TTL bullet → DONE/partial; ROADMAP **Next**; skeleton → «landed» pointer.
9. **Quality gate** — `uv run ruff check .` / `ruff format --check .` / `uv run pytest -q`; PR-standard `TEST_POSTGRES=1 uv run pytest -q` (репо трогает repo/scheduler/migration paths). _Runner note: [`tests/README.md`](../../tests/README.md) L76 предпочитает `.venv/bin/python -m pytest` для real runs; `uv run pytest` — принятый эквивалент (те же режимы default / `TEST_POSTGRES=1`). Использовать один и тот же runner в обоих доках._
10. **Prod (только in-session owner GO):** выставить `RESUMMARIZE_VERSION_RETENTION_DAYS=180` / `RESUMMARIZE_VERSION_KEEP_LAST_N=50` в prod `.env` → backup (`pg_dump -t topic_card_versions`) → `--dry-run` sanity count → `docker compose up -d tg_parser` (re-create, **не** restart, BUG-078) → verify OS-env + первый purge-log.

---

## 7. Acceptance criteria (impl-сессия done when)

- [ ] Baseline snapshot записан (rows, size, rows/day, projected GB/year) — §6 step 1.
- [ ] ADR-0018 (`docs/adr/0018-topic-card-versions-retention.md`) написан (rule C, hard-DELETE zero-schema, defaults, double floor genesis+recent); status `Proposed`.
- [ ] 2 Settings knob'а; code-default `RETENTION_DAYS=0` ⇒ **ноль purge** (bit-for-bit MVP «храним всё»); `KEEP_LAST_N=50`.
- [ ] `purge_stale` идемпотентен (повторный запуск удаляет 0); **никогда** не удаляет: (a) последние N per topic, (b) строки < M дней, (c) genesis `version_no = 1`.
- [ ] Unit-test доказывает genesis-pin: тема со старой `version_no=1` вне N и старше M → **не** удалена.
- [ ] Concurrent re-summarize не нарушает `UNIQUE(topic_id, version_no)`; purge не renumber `version_no`.
- [ ] `get_topic_versions` возвращает оставшиеся версии; **не** 500 на gaps (genesis всегда присутствует).
- [ ] Dry-run путь (CLI `--dry-run` = SELECT count с тем же predicate вкл. `version_no > 1`) доступен до первого destructive prod-run.
- [ ] Observability: gauge row-count + counter deleted + log. Grafana Panel 4 wiring — **optional** (только если panel provisioning уже существует; иначе gauge экспонируется, панель — follow-up).
- [ ] `uv run ruff check .` + `ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] Runbook (growth + purge/ops) + FUTURE_FEATURES + ROADMAP обновлены.
- [ ] Prod: `RETENTION_DAYS=180` / `KEEP_LAST_N=50` выставлены только по явному in-session owner GO, после backup + dry-run; rollback (`=0` + `up -d`) задокументирован.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 8. Out of scope (жёстко — impl-сессия не расширяет без нового GO)

- **Soft-delete** (`deleted_at` column/filter) — отклонён (decision #2 = hard-DELETE); не реализуем в этом slice.
- **#2 diff API** `get_topic_history_diff`, **#5 Bot tools** F5-C, **#3 F6 topic-level digest**, **#6 type-promotion**, **#7 topic dedup**, **#8 bundle-item GC**, **#9 HTTP endpoints** (все после TTL — decision #6).
- **Retention для `processed_documents` / raw / embeddings / других таблиц** — отдельный concern (F2 ingestion/export retention), НЕ в этом slice; явно deferred.
- **Dense «history index»** / renumber `version_no` / скрытие gaps от API — API показывает что осталось.
- **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- **Track δ/T7** повторный bump — отдельная follow-up сессия (re-watch ≈2026-08-05).
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt` (ADR-0017 — новых deps не нужно).
- «Wave 3» naming.

---

## 9. Owner decisions (final, 2026-07-22 — все 6 приняты)

1. **Числа (conservative):** `RESUMMARIZE_VERSION_RETENTION_DAYS = 180`, `KEEP_LAST_N = 50`. Interaction constraint `RETENTION_DAYS ≥ 2× MAX_AGE_DAYS` holds: 2 × 21 = 42 ≤ 180 ✓. MAX_AGE_DAYS читать из Settings в runtime (не хардкодить 21).
2. **Delete mode:** hard DELETE, **zero schema-change** (MVP без Alembic-миграции; migration OUT-by-default).
3. **Trigger:** scheduler cron (daily) — зеркало `cleanup_stale_idempotency_keys` (ADR-0009) — **+** CLI `topic purge-versions --dry-run`.
4. **ADR:** новый **ADR-0018** «retention policy» (0018 = next free number; addendum к ADR-0006 отклонён). Полный ADR — в impl-сессии, status `Proposed`.
5. **Provenance floor (v1 pin, CHANGED от прежнего keep-last-N-only):** genesis `version_no = 1` **никогда** не purge. Predicate: delete iff (вне новейших N) **AND** (старше M дней) **AND** (`version_no > 1`). Rationale: ~ноль storage (+1 строка/тему), сохраняет full-lifetime genesis-provenance для hot+old тем — где diff-история ценнее всего.
6. **Priority:** TTL — **следующий #15 item к реализации**, впереди diff-API / Bot-tools (см. §1). ROADMAP правится в impl-сессии, не здесь.

---

## 10. Self-review fixes applied (plan)

Критический pass (correctness / blast-radius / migration-safety / backward-compat / alignment):

1. **Perf-риск window-CTE** — добавлена perf-note: `row_number()` ранжирует всю таблицу (full scan); зафиксирован watch-item + оптимизация при GB-scale (§3.1). Изначально план подразумевал «индекс покрывает» — это неверно для глобального ранжирования.
2. **Уточнён доминирующий knob** — явно разведены роли: M (retention_days) = главный левер глобального роста (hot-темы держат все строки < M дней), keep-last-N = floor для cold-тем. Раньше N/M подавались как равноценные (§3.1, §3.3).
3. **Freshness-value не хардкодить** — `RESUMMARIZE_MAX_AGE_DAYS=21` это prod env-value (code-default 0), может измениться на re-watch ≈2026-08-05; sanity floor читать из Settings в runtime (§3.3).
4. **Hard-DELETE необратимость** — явно: «rollback» = стоп будущих purge; удалённое восстановимо только из backup (§5). Убрана двусмысленность «reversible».
5. **Migration = OUT для MVP подтверждён** — hard-DELETE не требует schema-change; существующий индекс достаточен; новый индекс только по EXPLAIN-боли (§5).
6. **Verified anchors** — `add_cron_task` (background_scheduler L118), Counter/Gauge (api/metrics), CLI `@app.command` (topic_cmd), ADR-0009 filename — все существуют; план не ссылается на несуществующие символы.
7. **Default no-op подтверждён** — code-default `RETENTION_DAYS=0` ⇒ ноль purge = «no destructive default» + kill-switch (§3.3, §7).

### Decision-bake pass (2026-07-22, owner GO — 6 решений)

8. **Numbers 180/50 baked** — §3.3 (table + prod-value), §6 step 3/10, §7, §9. Constraint 42 ≤ 180 ✓ явно в §3.3 + §9.
9. **Genesis-pin (decision #5) baked** — predicate `version_no > 1` добавлен в §3.1 (rule table, canonical predicate, SQL), §4 (#2/#4), §5 (concurrency), §6 step 4, §7 (+ dedicated genesis unit-test criterion), §9. Canonical predicate wording зафиксирован в §3.1 для дословного reuse.
10. **ADR-0018 confirmed next-free** — `ls docs/adr/` → last 0017; §4/§6/§7/§9 говорят «новый файл, status Proposed, пишется в impl-сессии»; addendum отклонён.
11. **hard-DELETE / migration OUT** — §3.2 переписан на «zero schema-change, migration OUT-by-default», согласовано с §5 (Alembic row) и §6.
12. **Trigger cron+CLI** — decision #3 явно в §9; §5/§6/§7 уже описывали cron + CLI `--dry-run`.
13. **Priority** — §1 «TTL = next #15 item» + §8/§9; ROADMAP-правка отложена в impl-сессию (не редактируем ROADMAP отсюда).
14. **Removed TBD-language** — §9 из «open questions» → «final decisions»; §3.2/§3.3/§8 убрали «owner-opt-out на GO / owner выбирает / lean».

---

## 11. Links

- ζ skeleton: [`SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`](SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md)
- Track-selection: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2 Track ζ
- δ/T7 verdict (freshness knob LIVE=21): [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md)
- Runbook: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) §4 (size SQL) / §T7
- Schema: [`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) L688; migration [`20260426_add_topic_card_versions.py`](../../migrations/versions/processing/20260426_add_topic_card_versions.py)
- Repo/port: [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py), [`ports.py`](../../tg_parser/storage/ports.py) L828
- Write-path: [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L582
- Purge precedent: [`cleanup_stale_idempotency_keys`](../../tg_parser/services/scheduler_service.py) L1398, [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py)
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #1 TTL
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md) (#1/#2/#4/#6), [0009](../adr/0009-idempotency.md) (cleanup precedent), [0017](../adr/0017-dependency-management-policy.md) (dep policy)
- START_PROMPT (companion): [`START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
