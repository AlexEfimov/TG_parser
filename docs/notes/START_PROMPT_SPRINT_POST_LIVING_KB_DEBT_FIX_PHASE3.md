# Post-Living-KB Debt-Fix Sprint — Phase 3 (deferred from Phase 2)

**Назначение:** Phase 3 завершает оригинальный post-Living-KB debt-fix sprint, забирая P1-stretch'ы которые были **отложены из Phase 2** из-за zero-traffic окна 24h F5-C watch'а. Берёт TD-06, TD-07, TD-08; опционально — hygiene-tier (TD-09, TD-10) если capacity осталась.

**Тип сессии:** writing — code, tests, docs, PRs. Аналогично Phase 1 / Phase 2: одна fix-ветка, multiple commits, single PR (или stacked-per-TD по выбору оператора).

**Дата подготовки промпта:** 2026-04-27 (одновременно с закрытием Phase 2; Phase 3 запускается **после первого продакшн-окна с реальной F5-C нагрузкой**, см. § 1.3 trigger).

**Когда использовать:** **только** после того как:

1. **Phase 2 merged + first F5-C traffic window closed.** Это значит: на проде хотя бы **один (`tg_resummarize_total > 0`) tick** уже отработал — без этого TD-06 «observability ownership / F5-C lifecycle edges» не имеет signal'а для prioritisation. Обычно: ≥ 1 канал с активной добавкой контента + ≥ 24h surveillance после неё.
2. BUG-fix track для Critical багов (BUG-001 / BUG-002 / BUG-006) **closed или explicitly deferred** — иначе тратим капасити на debt вместо security/data-loss.
3. Юзер ответил на гейтинговые вопросы § 1.4 (или взял default).

---

## 0. Known caveats / context inheritance

**Что Phase 1 и Phase 2 уже закрыли** (см. `MERGED_PLAN.md § 6` Status column на момент старта Phase 3):

- TD-01, TD-02, TD-03a, TD-03b, TD-04 → Phase 1 (PRs #16, #21, #22, #23, #24)
- TD-03c, TD-05 → Phase 2 (PR #25, commits `47625b6` + `ba88b90` in-branch / squashed as `209ca26`)
- TD-NEW-A, TD-NEW-B → Phase 2 (PR #25, commits `afba6b0` + `d0d5b5e`)

**Phase 3 НЕ touch'ит** уже закрытые TD. Если в TD-06/07/08 обнаружится, что часть scope'а уже совпадает с landed работой — отметить в pre-flight § 1.3 + узким комментарием в commit message.

**Phase 2 watch RCA — повторное чтение обязательно** (`docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md`):

- Tripwire #1/#2/#3 не сработали → метрики (TD-02 surface) видимы и в норме.
- Tripwire #4 — false-positive RCA → motivated TD-NEW-A + TD-NEW-B. Уроки для TD-06: **observability — не сам факт наличия метрик, а их семантика и восстанавливаемость alarm'ов**.

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` § 6 (Status column with Phase 2 updates) + § 9 Phase 2 landing log (целиком).
2. `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md` (master) — § 5 P1 stretch (TD-05..08), § 7 PR conventions, § 8 after-sprint handoff. **Phase 3 наследует master prompt тот же, что Phase 1/2.**
3. `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md` § 9 Handoff — узнать какой scope Phase 2 явно отдал в Phase 3.
4. `docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md` — целиком, **с акцентом на § «New TDs prioritization»** (там зафиксированы причины deferral'а TD-06/07/08).
5. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md` § CODE-007, CODE-009, CODE-010 — мотивация для TD-06.
6. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md` § 012, 013 + opus § DOCS-004 — мотивация для TD-07.
7. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md` § CODE-011, CODE-012 — мотивация для TD-08.
8. `CHANGELOG.md` — секции Phase 1 + Phase 2 (свежие entries для понимания текущего contract'а).
9. **Свежие prod-метрики** (если есть Grafana / metrics endpoint):
   - `tg_resummarize_total` — должно быть > 0 хотя бы по одному outcome label (иначе trigger из § 1.3 не выполнен).
   - `tg_watchlist_*` — должны экспонироваться (Phase 1 TD-02 landed).
   - `tg_parser_anthropic_billing_block_total` — current value (для отладки TD-NEW-B delta-helper).

### 1.2 Sanity checks

```bash
# 1. На main, working tree чист
git checkout main && git pull --ff-only origin main
git status --short

# 2. Phase 1 + Phase 2 PRs merged (по landing log из MERGED_PLAN § 9)
git log --oneline main -25 | head -25
rg "Sprint Debt-Fix Post-Living-KB — Phase 2" CHANGELOG.md  # должна быть секция
rg "TD-NEW-B" docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md   # должна быть строка в § 6

# 3. Baseline pytest зелёный
.venv/bin/pytest -q 2>&1 | tail -10
# Ожидание: ~1765 passed (post-Phase-2 baseline). Если delta — investigate перед edits.

# 4. F5-C traffic check (КРИТИЧНО для TD-06)
ssh prod 'docker compose exec api curl -s localhost:8000/metrics | grep tg_resummarize_total | head -10'
# Ожидание: хотя бы одна строка с counter > 0. Если все 0 — § 1.3 trigger не выполнен.

# 5. Watch helper baseline после TD-NEW-B
ssh prod 'tail -5 ~/f5c-watch/cron.log'
# Ожидание: GREEN или idle, NO TRIPWIRE без RCA. Если есть новый TRIPWIRE —
# follow F5C runbook § Tripwire response, blocking Phase 3.

# 6. Branch
git checkout -b fix/post-living-kb-debt-phase3-2026-MM-DD
```

### 1.3 Trigger condition (Phase 3 НЕ запускать без выполнения)

| Condition | Verification | Если не выполнено |
|---|---|---|
| **F5-C traffic > 0** — был хотя бы один реальный resummarize tick (success или failure) | `tg_resummarize_total{outcome=*} > 0` в `/metrics` | **Wait.** Phase 3 заблокирована до первого реального тика. Пока ждём — допустимо забирать TD-09 / TD-10 (hygiene) как отдельный hygiene-only sprint, не Phase 3. |
| **Phase 2 watch helper стабилен после TD-NEW-B** | `cron.log` за последние 24h ≥ 6 verdict-строк, **0 false-positive TRIPWIRE** на `#4` | **Wait.** Возможно TD-NEW-B не deploy'нут на прод. Проверить `git log --grep="TD-NEW-B" prod-host` или сделать redeploy перед Phase 3. |
| **Critical BUG-fix track resolved или явно deferred** | `BUG_LOG.md`: BUG-001, BUG-002, BUG-006 = `resolved` или `wontfix` | **Wait.** Сначала закрыть Critical баги (security + data-loss + bot-полностью-сломан); debt — менее срочный. |

Если все три condition'а выполнены — Phase 3 unblocked. Записать в § 1.4 timestamp выполнения каждого.

### 1.4 Gating decisions (must answer before code-changes)

Из `MERGED_PLAN § 8 Non-blocking` для Phase 3:

| ID | Вопрос | Default | Comment |
|---|---|---|---|
| Q-NB-1 | `topic_card_versions.scope_*_json` — TEXT (immutable blob) или JSONB? | **TEXT, по convention'у с другими immutable audit-полями** | Влияет на TD-08 (S-014). |
| Q-NB-2 | `vector(1536)` для F11 watchlists — intentional или artifact? | **Intentional** (current Anthropic embed dim'е) | Влияет на TD-08 (S-015). Если решим менять — отдельный migration sprint. |
| Q-NB-3 | metrics/health → `tg_parser.observability.*` или оставить в `tg_parser.api.metrics`? | **Оставить + явная docstring-allowed-exception** в `architecture.md` | Влияет на TD-06 (S-006). Перенос — большой refactor, без явного юзер-blessing'а — не делать. |
| Q-NB-4 | `summary_version` CLI fallback — forward-compat или scar? | **Forward-compat** — оставить + добавить ADR-note в `topic_card_versions` README | Влияет на TD-09 (post-Phase-2 hygiene), не Phase 3. |
| Q-NB-5 | Нужен ли pre-Phase-3 secondary review (для S-001 / TD-03 кластера)? | **Нет** — Phase 1 + Phase 2 были writing-сессии, не review. Если хочется — отдельный review-prompt. | Outside Phase 3 scope. |

Юзер отвечает на эти вопросы **до** старта code-changes. Default'ы зафиксированы в `MERGED_PLAN § 8 Non-blocking` и могут быть применены автоматически если оператор молчит.

---

## 2. Sprint scope

### 2.1 P1 stretch (priority order)

#### 2.1.1 TD-06 — Clean observability ownership and F5-C metric/client lifecycle edges

**Source:** `S-006`, `S-008`, `S-011`.

**Suspects (читать в pre-flight):**

- `tg_parser/api/metrics.py` — текущая ownership-граница (`api.metrics` vs `observability.*`).
- `tg_parser/services/resummarization_service.py` — F5-C client lifecycle (создание/закрытие LLM client'а, propagation cancellation'а в `_call_llm`).
- `tg_parser/api/health_checks.py` — после TD-NEW-A; проверить что lifecycle httpx client'ов корректный (нет ресурс-leak'ов на каждом probe).

**Acceptance:**

- Все Prometheus metric definitions в одном модуле (или с явной docstring-exception).
- F5-C `_call_llm` корректно closes httpx client при cancellation (timeout / asyncio.cancel) — добавить regression test с `pytest.raises(asyncio.CancelledError)` + assert на client._transport closed.
- `architecture.md` обновлён с «observability layering exception» (Q-NB-3 default).

**Estimate:** M (1–3 файла + 2–4 тестов).

#### 2.1.2 TD-07 — Fix changelog and architecture reference drift

**Source:** `C-007`, `S-010`.

**Suspects:**

- `CHANGELOG.md` — пройтись по всем секциям, проверить что cross-ref'ы ведут на существующие файлы (некоторые упоминают `docs/notes/SESSION*` или удалённые runbooks).
- `docs/architecture.md` (если есть) — refs to outdated module paths.
- `README.md` — раздел «Architecture» / «Components» — drift проверка.

**Acceptance:**

- 0 broken cross-refs в CHANGELOG (verified `markdown-link-check` или вручную).
- `architecture.md` § «Module map» совпадает с актуальным `tg_parser/` layout (использовать `find tg_parser -type d -maxdepth 2 | sort` как ground truth).

**Estimate:** S (1–2 файла, no tests — docs-only).

#### 2.1.3 TD-08 — Document or guard schema/config invariants for F5-C/F11 storage

**Source:** `S-014`, `S-015`.

**Suspects:**

- `tg_parser/storage/sqlalchemy/models.py` — F5-C `topic_card_versions`: `scope_in_json` / `scope_out_json` columns (TEXT vs JSONB — Q-NB-1).
- `tg_parser/storage/sqlalchemy/models.py` — F11 `watch_interests` / `watch_matches`: `vector(1536)` constraint (Q-NB-2).
- `alembic/versions/*` — migrations, добавляющие эти столбцы; убедиться что constraint'ы в миграции совпадают с моделью.

**Acceptance:**

- Если Q-NB-1 default (TEXT immutable) принят — добавить `Comment` в SQLAlchemy column + ADR-note в `docs/decisions/D-N_topic_card_versions_scope_text.md`.
- Если Q-NB-2 default (1536 intentional) принят — добавить runtime invariant check на startup: если `EMBEDDING_DIM != 1536` raise `ConfigError` с сылкой на ADR.
- Regression test: `test_topic_card_versions_scope_columns_are_text` + `test_watch_interest_vector_dim_matches_settings`.

**Estimate:** S/M (1–2 файла + 2 тестов + 1 ADR).

### 2.2 Optional hygiene tier (только если осталась капасити)

#### TD-09 — Archive stale `docs/notes/` prompts and add an index

**Acceptance:** `docs/notes/_archive/` создан + 5–10 устаревших `START_PROMPT_SESSION*.md` перенесены + добавлен `docs/notes/INDEX.md` со списком актуальных prompt'ов и архивных. **Estimate: M, но pure-docs.**

#### TD-10 — Sweep minor dead-code/dependency consistency issues

**Source:** `S-009`, `S-012`, `S-013`, `S-016`. **Acceptance:** ruff-clean (если уже не — fix), `vulture` или manual review для dead-code, `pip-audit` clean. **Estimate: S, batch'едится с TD-07.**

---

## 3. PR conventions

Per master prompt § 7 + Phase 1/2 precedent:

- Один PR per TD (recommended) **или** single phase-PR со stacked commits (Phase 1 + Phase 2 precedent).
- Каждый commit message содержит:
  - Префикс TD ID (`refactor(TD-06):`, `docs(TD-07):`, etc.)
  - Tail: `Refs: REVIEW_2026-04-26_MERGED_PLAN.md TD-NN, Phase 3.`
- В PR body: per-TD detail (что меняется), test plan, link на `MERGED_PLAN § 6` row.
- CHANGELOG: новая секция «Sprint Debt-Fix Post-Living-KB — Phase 3 (YYYY-MM-DD)».

---

## 4. After-sprint handoff

После Phase 3 close:

1. `MERGED_PLAN § 6` Status column: TD-06/07/08 → `closed (Phase 3, commit <SHA>)`.
2. `MERGED_PLAN § 9` — добавить «Phase 3 landing log» (по образцу Phase 1 / Phase 2 секций).
3. CHANGELOG секция Phase 3 заполнена.
4. **Operator-task:** открыть GH issues per landed TD (повторить admin-сессию по `START_PROMPT_FOLLOWUP_OPEN_GH_ISSUES_2026-04-27.md` для Phase 3 batch'а).
5. Если TD-09 / TD-10 не landed в этой сессии — оставить open в § 6, отдельный hygiene-prompt.
6. **Closing the original audit:** после Phase 3 + hygiene весь оригинальный backlog из `MERGED_PLAN § 6` закрыт. Делать closing-commit `docs(merged-plan): close audit — all 12 TD landed across 3 phases + hygiene` и помечать review-trio (`gpt55.md` / `opus.md` / `MERGED_PLAN.md`) как `archived` (можно перенести в `_archive/` если делается TD-09).

---

## 5. Estimated effort

| Stage | Time |
|---|---|
| Pre-flight reads (§ 1.1) | 30–45 min |
| Sanity checks + trigger verification (§ 1.2 / 1.3) | 10 min |
| Q-NB-1..5 решения (§ 1.4) | 5–15 min (если все default) |
| TD-06 implementation + tests | 90–150 min |
| TD-07 docs sweep | 30–60 min |
| TD-08 schema invariants + ADR | 60–90 min |
| Optional TD-09 / TD-10 batch | +60–120 min |
| CHANGELOG + MERGED_PLAN close-out | 20 min |
| PR(s) + push | 15 min |
| **Total (без hygiene)** | **~4–5 часов** |
| **Total (с hygiene)** | **~6–7 часов** — лучше split на две сессии |

Если capacity тесная — TD-06 (P1, observability ownership) **обязателен** в Phase 3, TD-07 / TD-08 — приоритетно в этом порядке. Hygiene tier — отдельный sprint.
