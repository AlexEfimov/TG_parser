# ADR 0018 – Retention/TTL policy for `topic_card_versions` (hybrid keep-last-N ∧ older-than-M ∧ genesis-pin, hard-DELETE, zero schema-change)

## Статус

**Proposed (2026-07-22) — включено в проде 2026-08-11, `Accepted` ждёт первого тика.**

### Update 2026-08-11 — Событие B выполнено; статус НЕ переводится (пока)

`RESUMMARIZE_VERSION_RETENTION_DAYS=180` живёт в проде с `2026-08-11T23:12:51Z`
(owner GO, бэкап таблицы сверен построчно 1284==1284, dry-run `WOULD purge: 0`,
sanity floor `180 >= 2×21` OK). Полная запись: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
§ «Запись включения — 2026-08-11».

Статус намеренно остаётся `Proposed`: условие приёмки ниже говорит «после первого
**prod-запуска**», а включение — это ещё не запуск. Первый on-path тик cron'а —
`2026-08-12 03:30 UTC`; до него утверждение «работает в проде» было бы истинным
при полном бездействии механизма, а такие формулировки приёмке не подлежат.
Перевод в `Accepted` — после того, как тик отпишется `topic_card_versions_purge`
(не `_skipped`) и гейдж `tg_topic_card_versions_rows` уйдёт с `0.0` на реальный
размер таблицы.

Предусловие, вскрывшееся при включении: до PR [#384](https://github.com/AlexEfimov/TG_parser/pull/384)
флип был **инертен** — обе retention-переменные отсутствовали в compose-блоке, а
приложение не читает bind-mounted `/app/.env` ([BUG-092](../notes/BUG_LOG.md)).

---

Реализация конфиг-driven retention для append-only
истории `topic_card_versions` (F5-C, issue #15 item #1). Код (`purge_stale`
repo-метод + daily cron + CLI `topic purge-versions --dry-run` + observability)
 landed в impl-сессии; **prod-purge выключен по умолчанию** — code-default
`RESUMMARIZE_VERSION_RETENTION_DAYS=0` (kill-switch). Перевод в `Accepted`
после первого prod-запуска (`RETENTION_DAYS=180`) по отдельному in-session owner
GO с backup + dry-run. Sources of truth:
[`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](../notes/PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md),
[`START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](../notes/START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md).

## Контекст

F5-C (evolving topic summaries, migration `a4b5c6d7e8f9`) пишет **одну** строку
в `topic_card_versions` на каждый успешный re-summarize (`outcome=ok`) —
snapshot *предыдущего* состояния `TopicCard` (summary / scope_in / scope_out +
LLM-provenance). Таблица append-only; рост ничем не ограничен (MVP-решение
«храним всё»).

Track δ/T7 (закрыт 2026-07-22, [`DELTA_T7_VERDICT_2026-07-22.md`](../notes/DELTA_T7_VERDICT_2026-07-22.md))
поднял `RESUMMARIZE_MAX_AGE_DAYS` `14 → 21` LIVE. Age-ветка даёт ~99% re-summarize
mix ⇒ **freshness-петля ускоряет рост history-таблицы**, усиливая нужду в TTL.

**Единственный read-path** истории — `TopicCardVersionRepo.list_by_topic` →
MCP `get_topic_versions` + CLI `topic versions`. Ни один другой сервис
(F11 watchlist, F6 digest, RAG, workspaces) таблицу не читает. `topic_cards.summary_version`
(монотонный счётчик) — отдельная колонка и purge её не трогает.

Interaction с ADR-0006 (Karpathy living-KB): principle #2 (provenance/evidence)
требует, чтобы удаление истории не выглядело как потеря данных багом — отсюда
двойной provenance-floor (см. Решение). Purge-паттерн зеркалит уже принятый
`cleanup_stale_idempotency_keys` (ADR-0009 Q-OPEN-2): cron-hook `delete_older_than`
+ `count()` → gauge.

## Решение

### 1. Retention rule — **C: hybrid keep-last-N ∧ older-than-M ∧ genesis-pin**

Канонический предикат (v1, дословно в repo / CLI / tests):

> Строка версии удаляется **iff** она (a) **вне** N новейших версий своей темы
> **AND** (b) старше M дней **AND** (c) `version_no > 1` — genesis-snapshot
> (`version_no = 1`) **никогда** не purge.

```sql
WITH ranked AS (
  SELECT id, version_no,
         row_number() OVER (PARTITION BY topic_id ORDER BY version_no DESC) AS rn
  FROM topic_card_versions
)
DELETE FROM topic_card_versions t
USING ranked r
WHERE t.id = r.id
  AND r.rn > :keep_last_n                                              -- вне новейших N
  AND t.created_at < (now() - make_interval(days => :retention_days))  -- старше M дней
  AND t.version_no > 1;                                                -- genesis-pin
-- dry-run: SELECT count(*) с тем же WHERE (вкл. version_no > 1) вместо DELETE
```

Отклонённые альтернативы: **A. Time-TTL only** (стирает историю холодных тем
целиком, нет floor); **B. keep-last-N only** (глобальный диск растёт с
кардинальностью тем, старые темы держат N навсегда). **C** удаляет строку только
если она провалила **все три** защиты.

**Доминирующий knob:** строки < M дней сохраняются все ⇒ для hot-тем реальный
per-topic bound ≈ `rate × M`; keep-last-N — floor для cold-тем; genesis-pin — +1
строка на тему. **M — главный левер глобального роста.**

### 2. Delete mode — hard DELETE, **zero schema-change**

Hard DELETE ⇒ настоящий disk-reclaim, **ноль** schema-changes (нет
`deleted_at`-колонки и фильтра во всех readers), проще backward-compat.
**Alembic-миграция OUT-by-default** — hard-DELETE не требует schema-change;
существующий `idx_topic_card_versions_topic_created (topic_id, created_at DESC)`
покрывает partition-order. Новый индекс добавлять **только** если `EXPLAIN` на
prod-объёме покажет seq-scan боль. Soft-delete **отклонён** (колонка + миграция +
`WHERE deleted_at IS NULL` во всех read-path, без disk-reclaim).

**Необратимость:** rollback (`RETENTION_DAYS=0`) останавливает только будущие
purge; уже удалённые строки восстановимы **только** из backup (`pg_dump -t
topic_card_versions` перед первым prod-запуском).

### 3. Defaults + prod-числа

| Knob (env / Settings) | Code default | Prod (owner-chosen) | Семантика |
|---|---|---|---|
| `RESUMMARIZE_VERSION_RETENTION_DAYS` | **`0`** | **`180`** | `0` = purge DISABLED (kill-switch, bit-for-bit MVP). `>0` = M-days cutoff. |
| `RESUMMARIZE_VERSION_KEEP_LAST_N` | **`50`** | **`50`** | recent-floor per topic; активен только при retention_days > 0. |

Code-default `RETENTION_DAYS=0` ⇒ деплой кода **ничего не удаляет** — «no
destructive default» + встроенный kill-switch.

**Sanity floor:** `RETENTION_DAYS ≥ 2 × RESUMMARIZE_MAX_AGE_DAYS`. MAX_AGE_DAYS
LIVE=21 ⇒ 2×21 = 42 ≤ 180 ✓. Значение читается из Settings в runtime (**не
хардкодить 21** — может измениться на re-watch ≈2026-08-05); при нарушении
scheduler логирует `topic_card_versions_purge_retention_below_floor` (advisory,
purge продолжается).

### 4. Двойной provenance-floor (ADR-0006 #2)

- **recent-floor** (keep-last-N): последние N per topic сохраняются навсегда,
  независимо от возраста.
- **origin-floor** (genesis-pin `version_no = 1`): первый snapshot каждой темы
  сохраняется навсегда, независимо от N/M. Стоит ~ноль storage (+1 строка/тему),
  сохраняет full-lifetime genesis→current provenance для hot+old тем.

Версии старше M, вне последних N, с `version_no > 1` считаются **reclaimed by
policy, не потеряны багом**. `get_topic_versions` возвращает оставшиеся версии;
gaps в `version_no` = retention policy (genesis всегда присутствует ⇒ не 500).

### 5. Trigger + observability

- **Daily cron** `purge_stale_topic_card_versions()` (зеркало
  `cleanup_stale_idempotency_keys`), 03:30 UTC, skip при `retention_days == 0`.
- **CLI** `tg-parser topic purge-versions [--dry-run] [--keep-last-n N]
  [--retention-days M]` — dry-run = SELECT count() с тем же предикатом.
- **Metrics:** gauge `tg_topic_card_versions_rows` (post-purge count), counter
  `tg_topic_card_versions_purged_total`, structured log `topic_card_versions_purge`.

### 6. Concurrency safety

Purge — отдельная транзакция; DELETE только строк `rn > N` **AND**
`version_no > 1` (sealed старые, кроме genesis) — никогда над новейшей версией
(in-flight re-summarize под advisory-lock `pg_try_advisory_xact_lock(0xF5C, ...)`)
и никогда над genesis. `UNIQUE(topic_id, version_no)` не трогаем, `version_no`
не renumber. F5-C write-path не блокируется.

## Последствия

**Плюсы:** ограниченный рост history-таблицы с сохранением recent+genesis
provenance; zero schema-change (нет миграции, нет reader-изменений);
non-destructive default; идемпотентный, наблюдаемый, dry-run-able purge.

**Минусы / watch-items:**
- Window-CTE `row_number()` ранжирует **всю** таблицу за проход (full scan
  независимо от индекса). Для daily cron на MB-scale приемлемо; при росте в
  GB-territory — оптимизировать (pre-agg `HAVING count(*) > N` или batched
  delete). Watch-item, не блокер.
- Hard-DELETE необратим — mitigated backup + dry-run перед первым prod-run.
- Больше knobs (M + N) ⇒ шире acceptance-матрица (покрыто unit-тестами).

## Альтернативы

- **Time-TTL only (A)** — отклонён (нет floor).
- **keep-last-N only (B)** — отклонён (нет глобального time-bound; прежний
  provenance-floor был keep-last-N-only, теперь усилен genesis-pin).
- **Soft-delete** — отклонён (schema-change + reader-фильтры, без disk-reclaim).
- **Addendum к ADR-0006** вместо отдельного ADR — отклонён (retention — отдельное
  нормативное решение; проект ведёт ADR-per-decision).

## История

- **2026-07-20** — ζ-skeleton `SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`.
- **2026-07-22** — все 6 owner-decisions приняты (plan §9): M=180 / N=50,
  hard-DELETE zero-schema, cron+CLI, ADR-0018, genesis-pin `version_no=1`,
  TTL = следующий #15 item. Impl-сессия: код + tests + this ADR (`Proposed`).

## Ссылки

- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #1 TTL
- ADR [0006](0006-karpathy-like-living-kb-principles.md) (#1/#2/#4/#6), [0009](0009-idempotency.md) (cleanup precedent), [0017](0017-dependency-management-policy.md) (dep policy)
- Runbook [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) §4 / §T7
- Schema [`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) L688; repo [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py)
