# Dev Resurrection — Стартовый промпт исполнительной сессии

**Тип сессии:** реализация (destructive operations: `docker volume rm`, БД-rebuild, миграции).
**Базируется на:** `docs/plans/DEV_RESURRECTION_PLAN.md` (commit `a7e1ff8` или новее) + `docs/runbooks/DEV_RESURRECTION.md`.
**Не для:** планирования. Если планирование сдвинулось — сначала переоткрыть планировочную сессию по `docs/prompts/DEV_RESURRECTION_PROMPT.md`.

---

## Зачем

Привести оба dev-окружения (локальное и VPS `redboxtgbot`) в синхрон с `main` через **full rebuild** (опция выбрана в плане §1.4) и установить CI-guardrail, чтобы ситуация не повторилась.

Подготовить почву для отложенного smoke F6 — но **сам smoke F6 в эту сессию НЕ входит**.

---

## Обязательное чтение перед стартом

1. `docs/plans/DEV_RESURRECTION_PLAN.md` — целиком, особенно §1.4 (decision rationale), §3 (local), §4 (VPS), §5 (verification), §7 (CI guardrail), Appendix A (снимок VPS).
2. `docs/runbooks/DEV_RESURRECTION.md` — целиком, особенно FAQ.
3. `.env` (локальный) — убедиться, что есть всё из §3.1.3.
4. `git log -1 --format='%h %s'` — убедиться, что HEAD = `a7e1ff8` (Dev Resurrection plan commit) или новее на main.

---

## Scope

### IN scope (делаем в эту сессию)

| # | Этап | Раздел плана | Estimate |
|---|------|--------------|----------|
| 1 | VPS re-check (read-only, сравнить с Appendix A) | §4.1 | 10 мин |
| 2 | Local rebuild | §3.1–3.7 | 30 мин активно + 30–90 мин backfill фоном |
| 3 | Local verification | §5 | 15–20 мин |
| 4 | VPS rebuild | §4.3–4.7 | 40 мин активно + 30–90 мин backfill фоном |
| 5 | VPS verification | §5 + §4.8 (auth headers) | 15–20 мин |
| 6 | CI guardrail (PR в feature branch) | §7 | 15–25 мин (можно параллельно с VPS backfill) |
| 7 | Финализация runbook граблями, обнаруженными по факту | §6 | 10 мин |

### OUT of scope

- **Smoke F6** (9 пунктов) — отдельная сессия после resurrection.
- **Backfill остальных 4 каналов** (`AgeManagment`, `Lab4health`, `LongevityClub`, `genotek`) — следующая обычная dev-сессия (DI-5 в `FUTURE_FEATURES.md`).
- **Подключение `target_metadata` к `migrations/env.py`** для рабочего `alembic check` — DI-1.
- **Чистка `migrations/alembic.ini` от SQLite-секций** — DI-2.
- **F9 Phase 2+ hardening, TLS, Caddy production profile** — D-remaining track.
- **`git push` коммитов** в remote — оставляем на пользователя в конце сессии.

---

## Safety contract (обязательно)

1. **Перед каждой destructive командой** показать пользователю:
   - точную команду,
   - ожидаемый результат / критерий успеха,
   - что произойдёт, если упадёт.
   Дождаться явного «ок»/«го»/«подтверждаю». Список destructive:
   - `docker volume rm tg_parser_pgvector17_data` (локально и на VPS)
   - `docker compose stop|rm` для `tg_parser_postgres` (на VPS — селективно, НЕ задеть n8n/flowise/grafana/prometheus)
   - `git checkout main` на VPS (хотя HEAD `ffcad72 ∈ origin/main`, всё равно подтвердить)
   - `git push` (если будет)
2. **Если pre-flight шаг возвращает что-то отличное от Appendix A** — STOP, показать diff, спросить.
3. **Если миграция падает** — STOP, не пытаться чинить ручным DDL или `alembic stamp`. Зафиксировать в FAQ runbook'а как новую graблю.
4. **НЕ менять** `.env`, `migrations/`, схему БД ручным DDL без явного подтверждения.
5. **НЕ запускать `tg_parser_caddy`** (profile `production`) — вне scope.
6. **Не делать smoke F6** даже если backfill закончился рано — это отдельная сессия.

---

## Sequential gating (порядок жёсткий)

```
[1] VPS re-check (§4.1) → если совпало с Appendix A:
        ↓
[2] Local rebuild (§3.1–3.7)
        ↓
[3] Local verification (§5) PASSED?
        ↓
[7a] Зафиксировать новые грабли в runbook §6 (если были)
        ↓
[4] VPS rebuild (§4.3–4.7)
        ↓
        (параллельно, во время VPS backfill)
[6] CI guardrail (§7) — отдельная feature branch, отдельный коммит
        ↓
[5] VPS verification (§5 + §4.8 auth) PASSED?
        ↓
[7b] Финальное обновление runbook (если были новые грабли VPS)
        ↓
        STOP. Smoke F6 — следующая сессия.
```

Между [3] и [4] — **обязательная сверка с пользователем**: «локально OK, идём на VPS?». VPS rebuild не запускать, если local verification не PASSED.

---

## Коммиты

Делать **отдельными атомарными коммитами**, не сквозным:

| Коммит | Когда | Стиль (по проекту) |
|--------|-------|---------------------|
| `chore(dev-infra): runbook updates from local rebuild` | После [3], если были граbли | если правок не было — пропустить |
| `ci(alembic): add migration guardrails (heads/upgrade/downgrade smoke)` | После [6] | отдельная feature branch (`ci/alembic-guardrails`) |
| `chore(dev-infra): runbook updates from VPS rebuild` | После [5], если были граbли | если правок не было — пропустить |

⚠️ НЕ коммитить никакие изменения в `tg_parser/`, `migrations/`, моделях — это вне scope. Если по ходу обнаружится баг — фиксировать в `FUTURE_FEATURES.md` или `BUGS.md`, не править.

---

## Прогресс / статус

Во время сессии вести короткий статус (markdown table или маркеры):

```
✅ [1] VPS re-check — совпало с Appendix A
✅ [2] Local rebuild — db heads single per db, users created, channel added
🔄 [3] Local verification — 3/5 шагов
⏸️ [4] VPS rebuild — ждёт подтверждения
🔜 [6] CI guardrail
```

---

## Definition of Done (этой сессии)

- [ ] Local: `tg-parser db heads --db {ingestion,raw,processing}` — single head per db; в БД присутствуют `users`, `user_auth_mappings`, `digest_subscriptions`, `sources.owner_id`; admin user создан; `labdiagnostica_logical` ingest'ится; verification §5.1–5.5 PASSED.
- [ ] VPS: то же + auth-protected endpoints отвечают с правильным `X-API-Key` / `Authorization: Bearer`.
- [ ] CI guardrail в `.github/workflows/ci.yml` (отдельная feature branch), прогнан, ловит искусственный duplicate revision.
- [ ] `docs/runbooks/DEV_RESURRECTION.md` дополнен граблями, обнаруженными по ходу (или подтверждено, что новых не было).
- [ ] Все артефакты закоммичены отдельными коммитами; ничего uncommitted в working tree.
- [ ] Smoke F6 — НЕ выполнен (по контракту scope), передан в следующую сессию.

---

## Если что-то пошло не так

| Симптом | Действие |
|---------|----------|
| Local pre-flight: HEAD не на main | STOP, спросить пользователя; не делать `git reset` без подтверждения |
| Local rebuild: `db upgrade` упал | STOP, показать вывод, занести в FAQ runbook'а как новую graблю |
| VPS pre-flight: появился новый соседний контейнер с зависимостью на `tg_parser_postgres` | STOP, обновить план §4.3 (селективный teardown) и спросить |
| VPS pre-flight: `docker compose config` падает | STOP, проверить compose v5.1.0 — возможно, обновился; адаптировать команды |
| VPS rebuild: `git checkout main` отказывается из-за uncommitted changes (хотя ожидалось clean) | STOP, показать `git status`, спросить — НЕ stash'ить и НЕ reset'ить без подтверждения |
| Backfill висит >2 часов без прогресса | STOP, показать логи `tg_parser`, проверить LLM provider keys/quotas |
| Verification: какой-то endpoint 5xx | STOP, показать логи + ответ; не пытаться чинить код |

---

## Финал

После DoD — короткий summary пользователю с:
- что сделано,
- какие новые граbли пошли в runbook,
- следующий шаг (smoke F6, отдельная сессия).
