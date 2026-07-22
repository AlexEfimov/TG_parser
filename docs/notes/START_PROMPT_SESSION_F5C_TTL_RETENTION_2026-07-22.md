# START PROMPT — Session: F5-C #15 TTL/retention for `topic_card_versions`

**Дата:** 2026-07-22 · **Тип:** implementation (code + Alembic-optional + ADR + docs + prod-knob) · **Ветка:** `main` (или feature-ветка от актуального `main`)

**Goal (одной строкой):** реализовать конфиг-driven retention/TTL для append-only `topic_card_versions` — hard-DELETE purge старых версий с double floor (recent keep-last-N=50 **+** genesis-pin `version_no=1`) и time-bound M=180d, scheduler-cron + CLI dry-run, observability, safe defaults — **без** destructive поведения по умолчанию.

> **✅ Design decisions final (2026-07-22).** Все 6 owner-decisions приняты (см. §7) — бриф полностью специфицирован. **⛔ Execution-gate:** это **pre-written бриф**, а **не** авторизация деплоя. Прод-purge (prod `.env` `RETENTION_DAYS=180`) — **только** по отдельному in-session owner GO после backup + dry-run.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** `git commit` / PR — **только** по явному запросу пользователя (PR = merge-commit + `--delete-branch`). Никаких правок `docs/methodology/**`. `pyproject.toml` / `requirements.txt` — **не трогать** (ADR-0017; новых deps не нужно). Уважать `docs/adr/` (accepted binding) и `docs/contracts/` (JSON Schema нерушимы). Прод-мутация — re-create `docker compose up -d tg_parser`, **не** `restart` (BUG-078).

**Prerequisite SoT (перечитать перед кодом):**
- Plan (this session): [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md) — финальные решения, blast-radius, acceptance.
- ζ skeleton: [`SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`](SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md).
- Track ζ: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2.
- Freshness knob LIVE=21 (interaction constraint `RETENTION_DAYS ≥ 2× MAX_AGE_DAYS`; 2×21=42 ≤ 180 ✓): [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md).

**Все owner-решения зафиксированы** (см. §7 Decisions): M=180 / N=50, hard-DELETE zero-schema, cron+CLI, new ADR-0018, genesis-pin `version_no=1`, TTL = next #15 item.

---

## 0. TL;DR

| Step | Действие | Тип |
|---|---|---|
| 1 | Baseline read-only SQL snapshot (rows, size, rows/day, GB/year projection) | read-only |
| 2 | New file `docs/adr/0018-topic-card-versions-retention.md` (rule C, hard-DELETE zero-schema, defaults, genesis+recent floor), status `Proposed` | docs |
| 3 | Settings: `RESUMMARIZE_VERSION_RETENTION_DAYS=0` code-default (kill-switch) + `_KEEP_LAST_N=50` | code |
| 4 | `TopicCardVersionRepo.purge_stale(keep_last_n, older_than)` (port + SA + unit-test) | code+test |
| 5 | `purge_stale_topic_card_versions()` scheduler-hook + daily cron (skip if retention=0) | code+test |
| 6 | Metrics: gauge rows + counter purged + log; wire Grafana Panel 4 (optional) | code |
| 7 | CLI `tg-parser topic purge-versions [--dry-run]` | code |
| 8 | Docs: runbook purge/ops + growth; FUTURE_FEATURES; ROADMAP; skeleton→landed | docs |
| 9 | Quality gate: ruff + `TEST_POSTGRES=1 uv run pytest -q` | gate |
| 10 | **(in-session owner GO only)** prod `.env` `RETENTION_DAYS=180`/`KEEP_LAST_N=50` → backup → dry-run → `up -d` | ops |

**Hard OUT:** soft-delete, **Alembic-миграция (OUT-by-default — hard-DELETE не требует schema-change)**, diff API (#2), Bot tools (#5), F6 topic-digest (#3), retention др. таблиц (processed_documents/raw), Wave E, F11 HTTP, webhook 2A, methodology, pyproject/requirements, «Wave 3» naming.

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → (GO) 10. Код перед docs; prod последним.

---

## 1. Контекст

MVP F5-C хранит **все** `topic_card_versions` (один row per successful re-summarize, snapshot *предыдущего* состояния). Роста не ограничен (issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #1). Track δ/T7 закрыт 2026-07-22 — `RESUMMARIZE_MAX_AGE_DAYS` bump `14→21` LIVE; age-ветка = ~99% re-summarize mix ⇒ **freshness bump ускоряет рост history-таблицы**, усиливая нужду в TTL. **Owner decision #6: TTL — следующий #15 item к реализации** (впереди diff-API/Bot-tools); все 6 design-решений приняты (§7).

**Единственный read-path истории:** `list_by_topic` → MCP `get_topic_versions` + CLI `topic versions`. Никакой другой сервис (F11/F6/RAG/workspaces) не читает таблицу.

---

## 2. Anchors (перечитать перед правкой)

| Якорь | Файл | Примечание |
|---|---|---|
| Schema table | [`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) L688 | `UNIQUE(topic_id, version_no)`, idx `(topic_id, created_at DESC)`, FK CASCADE |
| Migration head (processing) | [`20260426_add_topic_card_versions.py`](../../migrations/versions/processing/20260426_add_topic_card_versions.py) | rev `a4b5c6d7e8f9` = текущий head processing-ветки; новую миграцию (если понадобится) чейнить отсюда |
| Repo (read-only сейчас) | [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) | добавить `purge_stale` |
| Port ABC | [`ports.py`](../../tg_parser/storage/ports.py) L828 `TopicCardVersionRepo` | добавить abstract `purge_stale` |
| Write-path (не ломать) | [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L582-618 | advisory-lock `pg_try_advisory_xact_lock(0xF5C, hashtext(topic_id))`; `UNIQUE` = 2-я линия |
| **Purge precedent (зеркалить)** | [`cleanup_stale_idempotency_keys`](../../tg_parser/services/scheduler_service.py) L1398 | `delete_older_than(cutoff)`+`count()`→gauge; ADR-0009 Q-OPEN-2, KISS |
| Cron registration | [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py) L118 `add_cron_task`, L443 idempotency cron | daily cron register |
| Settings block | [`settings.py`](../../tg_parser/config/settings.py) L1090-1145 | добавить 2 knob рядом с `resummarize_max_age_days` (L1134) |
| Metrics | [`api/metrics.py`](../../tg_parser/api/metrics.py) | Counter/Gauge (prometheus_client) |
| MCP tool (не менять код) | [`mcp_server.py`](../../tg_parser/mcp_server.py) L2604 `get_topic_versions` | документировать «gaps = policy» |
| CLI subapp | [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) L29 `@app.command` | добавить `purge-versions` |
| Runbook | [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) §4 (size SQL), §T7 | добавить purge/ops-секцию |
| ADR | [0006](../adr/0006-karpathy-like-living-kb-principles.md) #1/#2/#4/#6, [0009](../adr/0009-idempotency.md), [0017](../adr/0017-dependency-management-policy.md) | next free ADR = **0018** |

### Baseline read-only commands (Step 1)

```sql
-- processing-БД через ssh prod / docker exec tg_parser_postgres (НЕ Prometheus)
SELECT COUNT(*) AS rows,
       pg_size_pretty(pg_total_relation_size('topic_card_versions')) AS size,
       COUNT(DISTINCT topic_id) AS topics_with_history,
       MAX(version_no) AS max_version,
       AVG(version_no)::numeric(10,2) AS avg_version
FROM topic_card_versions;
```
```bash
# rows/day proxy (successful re-summarize за 24h)
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_total{outcome=\"ok\"}[24h]))'"
ssh prod 'docker exec tg_parser env | grep -E "RESUMMARIZE_(MAX_AGE_DAYS|VERSION)"'
```

### Purge SQL (rule C — hybrid keep-last-N ∧ older-than-M ∧ genesis-pin)

**Финальный retention-predicate (v1, канонический — дословно в repo/CLI/ADR/tests):**

> Строка версии удаляется **iff** она (a) **вне** N новейших версий своей темы **AND** (b) старше M дней **AND** (c) `version_no > 1` — genesis-snapshot (`version_no = 1`) **никогда** не purge.

```sql
WITH ranked AS (
  SELECT id, version_no,
         row_number() OVER (PARTITION BY topic_id ORDER BY version_no DESC) AS rn
  FROM topic_card_versions
)
DELETE FROM topic_card_versions t
USING ranked r
WHERE t.id = r.id
  AND r.rn > :keep_last_n                                              -- вне новейших N (=50)
  AND t.created_at < (now() - make_interval(days => :retention_days))  -- старше M дней (=180)
  AND t.version_no > 1;                                                -- genesis-pin: version_no=1 никогда
-- dry-run: SELECT count(*) с тем же WHERE (вкл. version_no > 1) вместо DELETE
```

---

## 3. Scope — детально

### 3.1 Baseline (read-only, docs)
- Снять SQL snapshot (§2) + rows/day + projected GB/year; зафиксировать в новой snapshot-note (`docs/notes/F5C_VERSIONS_GROWTH_BASELINE_<date>.md` или секция в runbook §4). Это evidence для owner GO по числам M/N.

### 3.2 ADR-0018 (docs) — new file, status `Proposed` (decision #4)
- Новый файл `docs/adr/0018-topic-card-versions-retention.md` (**0018 = next free**, verified; addendum к ADR-0006 отклонён). Decision: rule **C** (hybrid keep-last-N ∧ older-than-M ∧ genesis-pin), **hard-DELETE zero-schema**, defaults (`RETENTION_DAYS=0` code-default disabled, `KEEP_LAST_N=50`, prod `RETENTION_DAYS=180`), double-floor rationale (ADR-0006 #2: recent keep-last-N **+** genesis `version_no=1`), sanity floor `RETENTION_DAYS ≥ 2× RESUMMARIZE_MAX_AGE_DAYS`. Status `Proposed` (следовать `docs/adr/` шаблону).

### 3.3 Settings (code) — numbers final (decision #1)
- В F5-C блоке [`settings.py`](../../tg_parser/config/settings.py):
  - `resummarize_version_retention_days: int = Field(default=0, ge=0, le=3650, ...)` — code-default `0` = purge disabled (kill-switch, bit-for-bit MVP «храним всё»); **prod-value = 180**.
  - `resummarize_version_keep_last_n: int = Field(default=50, ge=1, le=10000, ...)` — recent-floor per topic; активен только при retention_days>0.
  - Description: связь с `RESUMMARIZE_MAX_AGE_DAYS` (читать из Settings в runtime, sanity floor `≥ 2× MAX_AGE_DAYS`; 2×21=42 ≤ 180 ✓), genesis-pin, «no destructive default».

### 3.4 Repo (code+test) — genesis-pin predicate
- Port [`ports.py`](../../tg_parser/storage/ports.py) `TopicCardVersionRepo`: `@abstractmethod async def purge_stale(self, *, keep_last_n: int, older_than: datetime) -> int`.
- SA impl [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py): window-CTE DELETE (§2, вкл. `version_no > 1`), возвращает deleted count; commit; отдельная транзакция (не пересекается с write-path advisory-lock). `list_by_topic` **без изменений**.
- Unit-test (`tests/test_f5c_*`): фикстура с топиками/версиями разного возраста → проверить: (a) последние N per topic **никогда** не удаляются; (b) строки < M дней **никогда** не удаляются; (c) **genesis `version_no=1` никогда** не удаляется (даже если вне N и старше M); (d) идемпотентность (2-й вызов → 0); (e) `retention_days=0`/большой ⇒ 0 удалений.

### 3.5 Scheduler (code+test)
- `purge_stale_topic_card_versions()` в [`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) (зеркало `cleanup_stale_idempotency_keys`): читать Settings; **skip + return `{"deleted":0,"skipped":True}` если `retention_days==0`**; иначе `purge_stale(...)` + `count()` → set gauge + log.
- Register daily cron в [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py) через `add_cron_task` (рядом с idempotency cron L443).
- Test: skip-path (retention=0) + on-path (mock repo).

### 3.6 Metrics (code)
- [`api/metrics.py`](../../tg_parser/api/metrics.py): `tg_topic_card_versions_rows` (Gauge, post-purge count), `tg_topic_card_versions_purged_total` (Counter), setter-функция (зеркало `set_idempotency_keys_table_size`). structured log `topic_card_versions_purge {deleted, table_size, keep_last_n, retention_days, cutoff, duration_s}`.
- Grafana Panel 4 (`docker/grafana/dashboards/wave2_observation.json` — row count сейчас manual SQL): wire gauge (optional, если panel provisioning уже есть).

### 3.7 CLI (code)
- `tg-parser topic purge-versions [--dry-run] [--keep-last-n N] [--retention-days M]` в [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py). `--dry-run` = SELECT count() с тем же predicate (вкл. `version_no > 1`) без DELETE. Defaults из Settings (N=50, M=180). Печатать план + count перед реальным DELETE.

### 3.8 Docs
- Runbook: purge/ops-секция (cron cadence, dry-run, backup, rollback `=0`) + growth note. FUTURE_FEATURES F5-C TTL bullet → DONE/partial + PR ref. ROADMAP **Next**. Skeleton → pointer «landed». `get_topic_versions` описание/runbook: «gaps в version_no = retention policy, не потеря данных».

### 3.9 Prod apply (ТОЛЬКО in-session owner GO, ops)
- Baseline snapshot → prod `.env`: `RESUMMARIZE_VERSION_RETENTION_DAYS=180`, `RESUMMARIZE_VERSION_KEEP_LAST_N=50` → backup (`pg_dump -t topic_card_versions`) → CLI `--dry-run` (sanity count) → `docker compose up -d tg_parser` (re-create, **не** restart) → verify OS-env + первый purge-log/gauge.

---

## 4. Out of scope (жёстко)

- **Soft-delete** (`deleted_at` column/filter) — отклонён (decision #2 = hard-DELETE); не реализуем.
- **Alembic-миграция** — OUT-by-default (hard-DELETE не требует schema-change); добавлять только если `EXPLAIN` покажет seq-scan боль на prod-объёме.
- **#2 diff API** `get_topic_history_diff`, **#5 Bot tools**, **#3 F6 topic-level digest**, **#6 type-promotion**, **#7 topic dedup**, **#8 bundle-item GC**, **#9 HTTP endpoints** (все после TTL — decision #6).
- **Retention для `processed_documents` / raw / embeddings / прочих таблиц** — отдельный concern; НЕ в этом slice.
- **Dense «history index»** / renumber `version_no` / скрытие gaps от API.
- **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- **Track δ/T7** повторный bump (re-watch ≈2026-08-05) — отдельная сессия.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`, «Wave 3» naming.

---

## 5. Acceptance criteria

- [ ] Baseline snapshot записан (rows, size, rows/day, projected GB/year).
- [ ] ADR-0018 (`docs/adr/0018-topic-card-versions-retention.md`) документирует rule C / hard-DELETE zero-schema / defaults / double floor (genesis+recent); status `Proposed`.
- [ ] Settings: code-default `RETENTION_DAYS=0` ⇒ **ноль purge** (bit-for-bit MVP); `KEEP_LAST_N=50`; descriptions включают sanity floor (≥ 2× MAX_AGE_DAYS, читать из Settings).
- [ ] `purge_stale` идемпотентен; **никогда** не удаляет: (a) последние N per topic, (b) строки < M дней, (c) genesis `version_no=1`; unit-test покрывает 5 кейсов (§3.4) вкл. явный genesis-pin.
- [ ] Scheduler skip при `retention_days==0`; on-path эмитит gauge/counter/log; test на обе ветки.
- [ ] `get_topic_versions` возвращает оставшиеся версии; **не** 500 на gaps (genesis всегда присутствует).
- [ ] CLI `--dry-run` печатает count (predicate вкл. `version_no > 1`) без DELETE.
- [ ] Concurrent re-summarize не нарушает `UNIQUE(topic_id, version_no)`; `version_no` не renumber; write-path advisory-lock не блокируется.
- [ ] `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] Runbook (purge/ops + growth) + FUTURE_FEATURES + ROADMAP + skeleton pointer обновлены.
- [ ] Prod `RETENTION_DAYS=180`/`KEEP_LAST_N=50` — только по явному in-session owner GO, после backup + dry-run; rollback (`=0` + `up -d`) задокументирован; hard-DELETE необратимость отмечена.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 6. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем repo/scheduler/settings/migration paths → нужен Postgres):
TEST_POSTGRES=1 uv run pytest -q
# Runner note: tests/README.md L76 предпочитает `.venv/bin/python -m pytest` для real runs;
# `uv run pytest` — принятый эквивалент (те же режимы default / TEST_POSTGRES=1). Один runner в обоих доках.

# migration drift check (только если добавили миграцию — по умолчанию НЕ добавляем):
# uv run tg-parser db check --db processing   # verified: db_cmd.py `check` command

# baseline / dry-run (read-only, safe):
ssh prod "docker exec tg_parser_postgres psql -U <user> -d <proc_db> -c \"SELECT COUNT(*), pg_size_pretty(pg_total_relation_size('topic_card_versions')) FROM topic_card_versions;\""
tg-parser topic purge-versions --dry-run    # count only, no DELETE

# prod apply (ONLY after in-session owner GO):
# edit ~/TG_parser/.env: RESUMMARIZE_VERSION_RETENTION_DAYS=180  RESUMMARIZE_VERSION_KEEP_LAST_N=50
cp .env .env.bak.ttl-$(date -u +%Y%m%dT%H%M%SZ)
docker compose up -d tg_parser   # RE-CREATE — NOT restart (BUG-078)
docker exec tg_parser env | grep RESUMMARIZE_VERSION
# rollback: set RETENTION_DAYS=0 in .env → docker compose up -d tg_parser (deleted rows recoverable ONLY from backup)
```

---

## 7. Decisions (final — все 6 owner-решений приняты 2026-07-22; см. plan §9)

1. **Числа (conservative):** `RESUMMARIZE_VERSION_RETENTION_DAYS = 180`, `RESUMMARIZE_VERSION_KEEP_LAST_N = 50`. Constraint `≥ 2× MAX_AGE_DAYS` holds (2×21=42 ≤ 180 ✓); MAX_AGE_DAYS читать из Settings в runtime (не хардкодить 21).
2. **Delete mode:** hard DELETE, **zero schema-change** — MVP без Alembic-миграции (migration OUT-by-default).
3. **Trigger:** scheduler cron (daily), зеркало `cleanup_stale_idempotency_keys` (ADR-0009), **+** CLI `topic purge-versions --dry-run`.
4. **ADR:** новый **ADR-0018** (`docs/adr/0018-topic-card-versions-retention.md`, next free number confirmed; addendum к ADR-0006 отклонён), status `Proposed`.
5. **Provenance floor (v1 pin):** genesis `version_no = 1` **никогда** не purge. Predicate = (вне новейших N) **AND** (старше M дней) **AND** (`version_no > 1`). Rationale: ~ноль storage (+1 строка/тему), полная genesis-provenance для hot+old тем.
6. **Priority:** TTL — **следующий #15 item** (впереди diff-API #2 / Bot-tools #5). ROADMAP правится в impl-сессии.

**Execution-gates (не design-решения, остаются в силе):**
- **Prod mutation** — `RETENTION_DAYS=180` в prod `.env` только по явному **in-session** owner GO, после backup + dry-run; planning/impl сами по себе purge не запускают.
- **Re-create only** — `docker compose up -d tg_parser`, никогда `restart` (BUG-078).
- **Commit/PR** — только по явному запросу пользователя.

---

## 8. Self-review fixes applied (START_PROMPT)

Критический pass (internal consistency vs plan / anchor-correctness / testable acceptance / explicit OUT):

1. **Typo fix** — «usedowngrade for interaction» → корректная формулировка interaction-constraint `RETENTION_DAYS ≥ 2× MAX_AGE_DAYS` (Prerequisite SoT).
2. **Migration-consistency с plan** — подтверждено: миграция **OUT по умолчанию** (hard-DELETE не требует schema-change); `db check` закомментирован и запускается только если миграция добавлена. Header type «Alembic-optional» согласован с §3/§6.
3. **Verified `db check` command** — существует в `db_cmd.py` (`@app.command def check --db`); убран placeholder «или проектный эквивалент».
4. **Anchor line-numbers verified** — L688 (schema), L828 (port), L1398 (purge precedent), L118/L443 (cron), L1134 (settings knob), L2604 (MCP tool), L29 (CLI) — все существуют.
5. **Acceptance ↔ plan §7 mapping** — каждый acceptance-пункт трассируется к plan; добавлен явный regression-safe критерий для `get_topic_versions` (не 500 на gaps).
6. **GATED статус усилен** — impl только по owner product GO; prod-purge (`RETENTION_DAYS>0`) — отдельный in-session GO после backup+dry-run; default `=0` = no-op. Разведены planning/impl/prod-ops.
7. **Out-of-scope включает др. таблицы** — `processed_documents`/raw/embeddings retention явно deferred (не только F5-C history).
8. **Rollback необратимость** — hard-DELETE: `=0` останавливает будущие purge, но удалённое восстановимо только из backup — отмечено в §5/§6.

### Decision-bake pass (2026-07-22, owner GO — 6 решений)

9. **Numbers 180/50 baked** — header, §0 TL;DR (step 3/10), §2 SQL comments, §3.3/§3.9, §5, §6 prod-apply, §7. Constraint 42 ≤ 180 ✓ в header/§3.3/§7.
10. **Genesis-pin `version_no > 1` baked** — canonical predicate добавлен в §2 (текст + SQL + dry-run comment), §3.2/§3.4 (unit-test genesis-кейс), §3.7 CLI, §5 acceptance (5 кейсов + genesis всегда в `get_topic_versions`), §7 decision #5. Согласовано с plan §3.1 дословно.
11. **ADR-0018 = new file, next-free, Proposed** — §0/§3.2/§5/§7; addendum отклонён.
12. **hard-DELETE / migration OUT** — §3.2, §4 (добавлен явный «Alembic OUT-by-default»), §7 decision #2; header type «Alembic-optional» согласован.
13. **TL;DR/§7 переписаны** — из «owner-inputs нужны» в «final decisions»; execution-gates (prod/re-create/commit) выделены отдельно.
14. **Removed TBD-language** — §3.9 «owner выбирает M/N» → фиксированные 180/50; §7 без «lean/required».

---

## 9. Ссылки

- Plan: [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
- Skeleton: [`SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`](SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md)
- Track ζ: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2
- Freshness knob LIVE=21: [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md)
- Runbook §4/§T7: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
- Format refs: [`START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md), [`START_PROMPT_SESSION_EPS_ZETA_INTERNAL_FILL_TTL_SKELETON_2026-07-20.md`](START_PROMPT_SESSION_EPS_ZETA_INTERNAL_FILL_TTL_SKELETON_2026-07-20.md)
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #1 TTL
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0009](../adr/0009-idempotency.md), [0017](../adr/0017-dependency-management-policy.md)
