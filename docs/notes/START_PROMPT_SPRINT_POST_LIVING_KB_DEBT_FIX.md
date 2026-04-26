# Post-Living-KB Debt-Fix Sprint — Start Prompt

**Назначение:** стартовый промпт для **fix-сессии**, исполняющей рекомендации
`docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`. Закрывает критический и major
долг, выявленный аудитом после закрытия Living-KB-контракта (D.1 + F11 + F5-C).

**Тип сессии:** writing — code, tests, docs, PRs. **Это первая после
аудита/merge-сессии сессия с правом писать в репозиторий.**

**Источник правды:** `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`
(§ 6 TD-table, § 7 Action plan, § 8 OPEN QUESTIONS, § 9 Metrics snapshot).
Fix-агент **не пересматривает** findings — только исполняет.

**Дата подготовки промпта:** 2026-04-26.

**Когда использовать:** **только** после того, как
1. Merge-сессия (`START_PROMPT_REVIEW_MERGE.md`) выложила `MERGED_PLAN.md`.
2. Юзер ответил на blocking OPEN QUESTIONS из § 8 merged plan'а
   (см. § 1.3 этого промпта — gating).
3. Прод-watch (`f5c-watch/cron.log`) не показывает TRIPWIRE.

---

## 0. Known caveats in the merged plan (from self-review)

Self-review итогового плана выявил расхождения между формальными требованиями
merge-промпта и тем, что реально записано. **Fix-агент должен трактовать
findings ниже как ground-truth-корректировки** к `MERGED_PLAN.md`.

| ID | Caveat | Что это значит для fix-сессии |
|---|---|---|
| **SR-001** | `C-006` слил два разных observation'а в одно confirmed-finding (`gpt55-004` — duplicate adjacent guards; `opus CODE-008` — F11-hook eats `AnthropicBillingError`) | TD-05 покрывает **обе** проблемы. PR должен закрывать и duplicate-guard collapse, и асимметричную обработку billing-error в F11-hook. Не считать «решено» если закрыта только одна сторона. |
| **SR-002** | ~~Поле `**Merge agent:** GPT-5.5` в shapке merged plan'а — фактически неверно~~ | **Resolved:** исправлено на `Claude Opus 4.7` до старта fix-сессии. Caveat историчен. |
| **SR-003** | Same-reviewer консолидация: `S-001 = gpt55-001 + gpt55-009`; `S-002 = CODE-002 + CODE-003 + CODE-006`; `C-003 = 4 источника включая `DOCS-007` (next contract — отдельный фасет) | TD-01 содержит **и** code-side fix (gpt55-001), **и** docs-mirror fix (gpt55-009) в одной правке. TD-03 содержит **три** независимые подзадачи (3a/3b/3c, см. § 4.3). TD-04 включает next-contract-stub из `DOCS-007` как отдельный пункт. |
| **SR-004** | ~~`S-006`…`S-016` пропускают поле «Why it matters (merged)» из формата § 4.3~~ | **Resolved:** все одиннадцать single-findings'ов получили `Why it matters (merged)` до старта fix-сессии. Issue body для P1/P2 теперь можно собирать копипастом из MERGED_PLAN без обращения к source-deliverables. |
| **SR-005** | `C-001` (F11 metrics): `opus` exec-summary называет это `critical observability gap`, finding row — `major`. В merged plan'е оставлен `major` | TD-02 трактовать как **conservative-major**: можно не дёргать никого, но если в ходе работы обнаружится что F11 в проде уже фактически слепой (нет signal на match-rate за 24h+) — эскалировать в `critical` и приоритезировать выше TD-01. |

Caveats `SR-001` / `SR-003` критичны для корректного scoping PR'ов. Прочитать
до старта.

---

## 1. Pre-flight

### 1.1 Required reads

В этом порядке (без этого порядка работа не воспроизводима):

1. `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` — целиком.
2. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md` — пер-finding observation/why-matters/suggested-action для TD-01 / TD-05 / TD-07.
3. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md` — то же для TD-02 / TD-03 / TD-08.
4. `docs/notes/START_PROMPT_REVIEW_MERGE.md` § 8 (ground rules) — почему single-finding-критикал держится P0 несмотря на single-status.
5. `CHANGELOG.md` (последние 200 строк) — формат записей, который должен соблюсти fix-агент.
6. `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — особенно § Post-watch report; TD-02 пишет туда PromQL.
7. § 0 этого промпта — known caveats.

### 1.2 Sanity checks (must pass)

```bash
# 1. Merged plan существует, untracked-файлы прибраны
ls -la docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md
git status --short docs/notes/REVIEW_2026-04-26_*

# 2. Working tree чист (или коммит уже сделан до старта работ)
git status --short

# 3. На fix-ветке, не на main
git rev-parse --abbrev-ref HEAD   # должно быть НЕ main

# 4. Watch state
ssh prod 'cat ~/f5c-watch/cron.log'   # последняя строка не должна содержать TRIPWIRE

# 5. Тесты до правок зелёные (anchor для regression-проверки)
.venv/bin/pytest -q 2>&1 | tail -20
```

Если хоть один шаг падает — **остановиться и сообщить юзеру**, не приступать
к работам.

### 1.3 Gating OPEN QUESTIONS

Эти вопросы из `MERGED_PLAN.md` § 8 (Blocking) **должны** быть отвечены
юзером перед стартом:

| ID | Вопрос | Зачем гейтит |
|---|---|---|
| Q1 (S-001) | `error_message` truncation: 4096 как в docs или 500 как в коде? | TD-01 не может стартовать — выбор policy определяет, что правим (код или docs) |
| Q2 (TD-03 / S-004) | Prompt-loader: complete built-in defaults для всех stages **или** loud-fail? | TD-03c — диаметрально разные реализации |
| Q3 (C-004) | Issue #15 — source of truth для F5-C P2 backlog или зеркалит файл? | TD-04 — направление синхронизации |
| Q4 (C-003 / DOCS-007) | Next contract — формулировать сейчас в ROADMAP_KARPATHY или ставить `Next contract — TBD`? | TD-04 — есть ли отдельная подзадача с stub-документом |

**Если ответы не получены** — задать юзеру в одном сообщении и не стартовать.
Default-стратегии (если юзер просит «решай сам»):
- Q1 → **bump до 4096** (docs were the contract; code was the bug). Sane default; меняется одно число + один тест.
- Q2 → **fail-loud**. Безопаснее silent-degraded; явные defaults можно добавить отдельным PR в P2.
- Q3 → **файл — source of truth**, sync issue body из файла. Файл проходит code review; issue не обязан.
- Q4 → **`Next contract — TBD`** placeholder + ссылка на будущий планинг. Не выдумывать контракт без планирующей сессии.

### 1.4 Branch / PR strategy

```bash
git checkout -b fix/post-living-kb-debt-2026-04-26
```

Один **базовый PR** (или серия PR'ов, по одному на TD-item) против `main`:

- TD-01 / TD-02 / TD-03 / TD-04 — отдельные PR'ы (легче review, легче rollback).
- TD-05 / TD-06 / TD-07 / TD-08 — допустимо batch'ем по логическим зонам, если стретч-капасити есть.
- Все PR'ы стэкаются от одной базы; первый merge → ребейз остальных.
- Каждый PR заканчивается зелёным CI и обновлением CHANGELOG.

Лейблы (по § 7 merge-промпта): `tech-debt`, `post-living-kb-review`,
плюс per-area (`scheduler`, `watchlist`, `config`, `docs`).

---

## 2. Out of scope (что НЕ делать в fix-сессии)

| Категория | Запрещено |
|---|---|
| **Новые фичи** | F11 P2 (`notify_mode=batch`/`silent`), F5-C P2 (#1-#10), F1 Full, F10-A, F12-A — ничего из feature backlog'а. Если в процессе работы появляется идея — запиши в `docs/quality/INBOX.md` и продолжай |
| **F5-C internals** | Не трогать `ResummarizationService.resummarize_topic`, `commit_resummary`, advisory-lock flow, `topic_card_versions` schema **до** 24h+ окна watch'а с verdict GREEN. Только TD-08 (S-014: TEXT vs JSONB documentation comment) — допустим |
| **Mass refactor** | Не делать sweep-refactor, выходящий за scope конкретного TD. Пример: TD-06 (S-006) не должен попутно переписать всю layout-структуру `tg_parser/`; либо «move metrics to observability/» либо «доб. exception в layering rule», но не «разнести api/ на 5 модулей» |
| **Удаление тестов** | Никаких удалений тестов. Конвертация — допустима с очень узким PR. Регрессии — только **добавление** |
| **Контестед-findings** | Их нет (§ 4 merged plan'а пуст), но если возникнут — НЕ исполнять, эскалировать к юзеру |
| **P2 без согласования** | TD-09 (`docs/notes/archive/`) и TD-10 (dead-code/dependency sweep) — отдельная сессия. Не трогать в этом спринте |
| **Изменение MERGED_PLAN** | Не редактировать findings/severity. Допустимо: только закрывающая отметка статуса в § 6 (см. § 7.2 этого промпта) и SR-002 правка строки 7 (имя merge-агента) |
| **Скрытие watch-tripwire** | Если в процессе watch покажет TRIPWIRE — **сразу** остановиться, открыть отдельный hot-fix PR, не маскировать симптомы внутри debt-fix-PR'ов |

---

## 3. Sprint scope

### 3.1 Default scope (ship this sprint)

**P0 (must):** TD-01, TD-02, TD-03, TD-04 — closure rolling-debt'a Living-KB
контракта.

**P1 stretch (if capacity):** TD-05, TD-06, TD-07, TD-08 — нормализация
scheduler/observability/docs hygiene. Брать в порядке номеров.

**Hold (out of sprint):** TD-09, TD-10.

### 3.2 Suggested execution order

```
TD-01 (S, P0, single-critical)            ─┐
   └─→ TD-02 (S/M, P0, confirmed-major)   ─┤  unblocks F11 P2 в будущем
        └─→ TD-03 (M, P0, single-major)   ─┤  3 independent sub-tasks (3a/3b/3c)
TD-04 (M, P0, mostly-confirmed-docs)      ─┘  можно вести параллельно с TD-01..03 (другие файлы)

──── TD-05..08 stretch goals ──────────────────────────────
TD-05 (S/M, P1)  —  scheduler hygiene
TD-06 (M, P1)    —  observability ownership
TD-07 (S, P1)    —  changelog/architecture path corrections
TD-08 (S/M, P1)  —  schema invariant docs/guards
```

Не запускать P1 пока **все** P0 не зелёные локально (тесты + ручная
верификация по § 6 этого промпта).

---

## 4. Per-TD playbook (P0)

Каждый блок ниже — самодостаточная инструкция для одного PR.

### 4.1 TD-01 — Align scheduler error_message truncation contract

**Source findings:** `S-001` (gpt55-001 + gpt55-009 per SR-003).
**Severity (merged):** critical (single).
**Scope:** S (≤ 1h).
**Default decision per § 1.3 Q1:** bump code to **4096**, keep docs.

**Files to touch:**
- `tg_parser/services/scheduler_service.py:744` — изменить дефолт
  `_truncate_error_message(message: str, max_len: int = 500)` на `4096`.
  Альтернатива (если хочется явной конфигурируемости): добавить
  `Settings.error_message_max_len: int = 4096` и передавать в helper.
- `tests/test_scheduler_service.py` — новый test
  `test_record_attempt_truncates_at_documented_limit`:
  - вход: failed-stage с `Exception("a" * 5000)`
  - проверка: `source_attempts.error_message` имеет длину **ровно 4096** и
    содержит первые 4096 символов исходного сообщения.

**Docs alignment (в этом же PR):**
- `CHANGELOG.md:131` — оставить «4096» как и есть, но добавить пометку про
  bug-fix в раздел «Изменения после D.1» (см. формат CHANGELOG ниже).
- `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` Sprint D.1 § 1 —
  оставить «4096», убедиться что число согласовано.

**Acceptance:**
- Новый тест проходит локально и в CI.
- `.venv/bin/pytest tests/test_scheduler_service.py -q` зелёный.
- `rg "max_len: int = 500" tg_parser/services/` пуст.
- CHANGELOG обновлён.

**Suggested PR title:**
`fix(scheduler): align error_message truncation with documented 4096-char contract`

**Suggested commit message:**
```
fix(scheduler): bump error_message truncation to documented 4096 chars

D.1 sprint promised 4096-char persistence (CHANGELOG, ARCH); the helper
landed with 500. RCA evidence (Anthropic billing payloads, full Telegram
errors, stack-trace fragments) was being silently dropped at 500.

Add regression test against the documented contract.

Refs: REVIEW_2026-04-26_MERGED_PLAN.md S-001 (gpt55-001 + gpt55-009).
```

---

### 4.2 TD-02 — F11 watchlist Prometheus metrics surface

**Source findings:** `C-001` (gpt55-002 + opus CODE-001).
**Severity (merged):** major (potentially escalatable per SR-005).
**Scope:** S/M (≤ 4h).

**Files to touch:**
- `tg_parser/api/metrics.py` — добавить:
  ```python
  WATCHLIST_MATCHES = Counter(
      "tg_watchlist_matches_total",
      "Watchlist match results.",
      ["result"],   # delivered | filtered_keywords | filtered_threshold | blocked | error
  )
  WATCHLIST_SCORE = Histogram(
      "tg_watchlist_score",
      "Distribution of hybrid watchlist match scores (0..1).",
      buckets=[0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
  )
  WATCHLIST_DELIVERY = Counter(
      "tg_watchlist_delivery_total",
      "Watchlist delivery outcomes.",
      ["outcome"],   # sent | blocked | error
  )
  WATCHLIST_ACTIVE_INTERESTS = Gauge(
      "tg_watchlist_active_interests",
      "Currently active watchlist interests.",
  )
  ```
  Вспомогательные функции `record_watchlist_match(result, score)`,
  `record_watchlist_delivery(outcome)`, `set_watchlist_active(count)`.

  **Заметка по cardinality:** `gpt55-002` предлагает доп. label `interest_id`
  / `score_bucket`. **Не добавлять `interest_id`-label** (cardinality blow up).
  Bucket'ить score через histogram, не label.
- `tg_parser/services/watchlist_service.py` — убрать TODO в строке 21,
  вызывать `record_watchlist_match(...)` в `run_for_documents` (для каждого
  document'а: `delivered` / `filtered_keywords` / `filtered_threshold`),
  `record_watchlist_delivery(...)` в bot push helper'е,
  `set_watchlist_active(...)` при start-up из repo-load.

**Tests:**
- `tests/test_watchlist_metrics.py` (new) — unit-тест на helper'ы +
  smoke-тест что `WATCHLIST_MATCHES._metrics` непустое после фейковой
  match-сессии.
- `tests/test_watchlist_service.py` — расширить существующий тест чтобы
  ассертить вызов `record_watchlist_match` хотя бы один раз.

**Runbook update:**
- `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — добавить sub-section «F11
  watchlist health» с PromQL-снипетами:
  ```
  rate(tg_watchlist_matches_total{result="delivered"}[1h])
  histogram_quantile(0.5, sum by (le) (rate(tg_watchlist_score_bucket[1h])))
  rate(tg_watchlist_delivery_total{outcome="blocked"}[1h])
  ```
- (опционально) создать новый `docs/runbooks/F11_WATCHLIST_OBSERVABILITY.md`
  если хочется развести F5-C и F11 — но НЕ обязательно для этого PR.

**Acceptance:**
- 4 metric'а экспортированы (проверка: запустить локально, `curl
  localhost:8000/metrics | grep tg_watchlist`).
- Тесты проходят.
- F5C_DEPLOY_AND_WATCH.md содержит F11-секцию.

**Suggested PR title:**
`feat(watchlist): export tg_watchlist_* Prometheus metrics for F11`

---

### 4.3 TD-03 — LLM scopes + Anthropic settings + prompt-loader fail-loud

**Source findings:** `S-002` (CODE-002+003+006), `S-003` (CODE-004),
`S-004` (CODE-005). **Три независимые подзадачи** (per SR-003).
**Severity (merged):** major (single).
**Scope:** M (~3-4h всего).

#### 4.3a — Surface `resummarize` across all LLM-config tools

**Files:**
- `tg_parser/config/settings.py` — `LLMConfigManager.get_all()`: добавить
  `"resummarize": _stage_config("resummarize")` в `stages` dict (одна строка).
- `tg_parser/mcp_server.py:1469-1474` — extend `set_llm_config` docstring
  enumeration: `'global' | 'processing' | 'topicization' | 'rag' | 'digest' | 'resummarize'`.
- `tg_parser/processing/llm/factory.py` — docstring `resolve_llm_config`:
  заменить «processing/topicization» на полный список из `LLM_SCOPES`.

**Tests:**
- `tests/test_llm_config_manager.py::test_get_all_includes_every_scope`:
  ассерт что `LLM_SCOPES \ {"global"}` ⊆ `get_all()["stages"].keys()`.

**Suggested commit:**
`fix(config): include resummarize in LLM scope-list across all surfaces`

#### 4.3b — Declare anthropic cap/cache settings as Pydantic fields

**Files:**
- `tg_parser/config/settings.py` — добавить три поля в `Settings`:
  ```python
  anthropic_prompt_caching_enabled: bool = Field(default=True, description="...")
  processing_anthropic_input_token_estimate: int = Field(default=8000, description="...")
  processing_anthropic_output_token_estimate: int = Field(default=1500, description="...")
  ```
- `tg_parser/processing/llm/factory.py` — заменить три `getattr(settings, ...)`
  на прямые обращения `settings.anthropic_prompt_caching_enabled` и т.д.
- `.env.example` — добавить три строки с дефолтами и описанием.

**Tests:**
- `tests/test_settings.py::test_anthropic_cap_settings_declared`:
  `Settings()` без env возвращает три атрибута с правильными дефолтами;
  `Settings(_env_file=...)` с env-vars подтягивает override.

**Suggested commit:**
`fix(config): declare anthropic prompt-cache + token-estimate as Settings fields`

#### 4.3c — Prompt-loader fail-loud (default per § 1.3 Q2: fail-loud)

**Files:**
- `tg_parser/processing/prompt_loader.py` — `_get_default(name)`:
  для каждого stage из `LLM_SCOPES` (или явного списка stages), если
  default отсутствует / пуст / возвращает `{}` — `raise PromptLoaderError(
  f"missing default prompt for stage={name!r}; YAML and built-in default both empty")`.
  **Не молчать с пустой строкой.**
- `tg_parser/services/digest_service.py` — добавить (или подтвердить
  существование) defensive-check как в `ResummarizationService`: пустая
  prompt-строка → `raise`.

**Tests:**
- `tests/test_prompt_loader.py::test_no_silent_empty_default`:
  для каждого stage в `LLM_SCOPES \ {"global"}`, если убрать YAML и
  fallback — `get(stage)` поднимает `PromptLoaderError`. Параметризованный
  тест.

**Suggested commit:**
`fix(prompts): fail loudly when both YAML and default prompt are absent`

**Объединённый PR title (вариант, если три коммита идут одним PR):**
`fix(config): consolidate LLM scopes, declare anthropic settings, fail-loud prompts`

---

### 4.4 TD-04 — Close Living-KB docs

**Source findings:** `C-002` (PRODUCTION_DEPLOYMENT), `C-003` (Karpathy
roadmap), `C-004` (FUTURE_FEATURES + #15), `S-005` (ROADMAP_V3).
**Severity (merged):** major (3 confirmed + 1 single).
**Scope:** M (~2-3h docs only).

**Files to touch (по одному коммиту на файл, или один docs-PR — на выбор):**

1. **`PRODUCTION_DEPLOYMENT.md`** (C-002):
   - Версия → `v4.4`.
   - Новый раздел `## v4.4 Living-KB upgrade notes` со списком:
     - Migration heads: `processing@a4b5c6d7e8f9`, `ingestion@c8e9f0a1b2c3`,
       processing-D.1 `ac6a4414ac58`.
     - Новые env-vars: `RESUMMARIZE_TRIGGER_N`, `_MAX_PER_TICK`,
       `_MAX_DURATION_S`, `_MAX_TOKENS_PER_TICK`, `_INPUT_WINDOW_N`,
       `RESUMMARIZE_LLM_PROVIDER/MODEL`, `RESUMMARIZE_ENABLED` (kill-switch),
       `MAX_DOCS_PER_TICK` (F11), плюс анти-billing knobs из TD-03b.
     - Cron-entry: `f5c_watch.sh`, ссылка на `F5C_DEPLOY_AND_WATCH.md`.
     - Verification curl: `curl localhost:8000/metrics | grep -E
       'tg_resummarize|tg_watchlist'`.
     - Verification SQL: `SELECT count(*) FROM topic_card_versions`,
       `SELECT count(*) FROM watch_interests`.

2. **`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`** (C-003):
   - В самом верху банер:
     ```markdown
     > **Living-KB contract: CLOSED 2026-04-26**
     > (D.1 hardening + F11 watchlist + F5-C evolving summaries — Wave A/B/C ниже)
     ```
   - Новый раздел `## 2026-04-26 — Contract closed ✅` с тремя строками
     (D.1 / F11 / F5-C) + ссылкой на CHANGELOG.
   - Revision-history table: запись 2026-04-26 «Wave C READY к реализации»
     → «Wave C MVP merged (PR #14)».
   - **Default per § 1.3 Q4:** добавить раздел `## Next contract — TBD`
     со ссылкой «формулируется в отдельной планирующей сессии (см.
     `docs/notes/PLANNING_NEXT_CONTRACT_*.md` когда появится)».

3. **`docs/notes/FUTURE_FEATURES.md`** (C-004):
   - Под заголовком § Level C (или F5-C P2 backlog) — одна строка:
     `> **Tracked in GitHub:** [issue #15](…)`.
   - Каждый из 9-10 deferred items: добавить `(see #15 — <subtask>)` суффикс.
   - **Default per § 1.3 Q3:** файл — source of truth; после landing'a
     открыть отдельный issue для sync'a issue #15 body со списком из файла.

4. **`ROADMAP_V3_PRODUCTION_FIRST.md`** (S-005):
   - Top-of-document banner: `> **Wave 1 closed 2026-04-26** — Living-KB
     контракт закрыт (D.1 + F11 + F5-C).`
   - Move D.1 / F11 / F5-C из Wave 3 / future в новую секцию `## Done`.
   - Re-rank Wave 2 entries (F1 Full / F10-A / F12-A / F11 P2 / F5-C P2);
     порядок взять из `Recommendation` § 5 merged plan'а
     («F11 P2 closest after TD-02»).

**Tests:**
- Нет (docs-only).
- (опционально) добавить в CI grep-check «банер CLOSED присутствует» —
  но это уже стретч.

**Acceptance:**
- 4 файла обновлены.
- `rg "CLOSED 2026-04-26" docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` ≥ 1.
- `rg "v4.4" PRODUCTION_DEPLOYMENT.md` ≥ 1.
- `rg "#15" docs/notes/FUTURE_FEATURES.md` ≥ 1.
- `rg "Wave 1 closed" ROADMAP_V3_PRODUCTION_FIRST.md` ≥ 1.

**Suggested PR title:**
`docs: close Living-KB contract across deploy and roadmap docs`

---

## 5. Per-TD playbook (P1 stretch — only if capacity)

Краткие pointers; полные observation/why-matters в source-deliverables.

### 5.1 TD-05 — Scheduler billing-error helper + structlog
- Source: `C-006` (per SR-001 — две стороны), `S-007` (gpt55-005).
- Извлечь `_handle_stage_errors(channel_id, stage_errors)` helper,
  переиспользовать в F5-C, F11, любом будущем hook'е.
- Сжать дублирующий `if isinstance(... AnthropicBillingError)` в
  `_process_source` (gpt55-004).
- Конвертировать `%s`-style логи в `scheduler_service.py` (строки 244,
  254, 289, 741, 753) на `event=...` key/value.
- Suggested PR: `refactor(scheduler): centralize billing-error escalation, unify structlog`.

### 5.2 TD-06 — Observability ownership + F5-C client lifecycle
- Source: `S-006` (gpt55-003), `S-008` (gpt55-006), `S-011` (opus CODE-007).
- **Default решение S-006:** не двигать api/metrics в `observability/`
  в этом спринте (M-effort с риском); вместо этого добавить **explicit
  exception** в layering rule (где документирована? — `docs/architecture/`
  или README — найти и записать). Оставить move как P2 follow-up.
- S-008: pool LLM client в `ResummarizationService.__init__`,
  закрывать в `aclose()`, заменить `contextlib.suppress` на
  `logger.exception("f5c_llm_client_close_failed", ...)`.
- S-011: либо передать реальный `channel_id` в `record_resummarize_outcome`,
  либо убрать label целиком до Phase 2.
- Suggested PR: `refactor(observability): pool F5-C LLM client; document services→api exception`.

### 5.3 TD-07 — CHANGELOG + ARCHITECTURE path corrections
- Source: `C-007` (gpt55-013, opus DOCS-004), `S-010` (gpt55-012).
- Исправить пути в CHANGELOG (`tests/test_f11_watchlist_repo.py::TestWatchMatchRepo`,
  `tg_parser/cli/watchlist_cmd.py`, `tg_parser/storage/ports.py`).
- Добавить F5-C/F11 services в § Ключевые файлы
  `ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`.
- (опционально) CI shell-check: `rg -o 'tg_parser/[^ )]*\.py' CHANGELOG.md`
  vs `git ls-files`.
- Suggested PR: `docs: fix path references in CHANGELOG and architecture notes`.

### 5.4 TD-08 — Schema invariant comments / guards
- Source: `S-014` (opus CODE-011), `S-015` (opus CODE-012).
- S-014: **default — добавить комментарий в migration**, что TEXT для
  `topic_card_versions.scope_*_json` намеренно (audit-immutable). НЕ
  делать downgrade на JSONB в этом спринте.
- S-015: добавить startup-time assert в `WatchlistService.__init__` или
  health-check: `db_vector_dim == settings.embedding_dimension`. Если
  расходится — `raise` или жирный warning в логи.
- Suggested PR: `chore(schema): document and guard F5-C/F11 schema invariants`.

---

## 6. Testing & verification

### 6.1 Per-TD gates

| TD | Required green |
|---|---|
| TD-01 | `pytest tests/test_scheduler_service.py -q` |
| TD-02 | `pytest tests/test_watchlist_service.py tests/test_watchlist_metrics.py -q` + manual `curl /metrics \| grep tg_watchlist` |
| TD-03 | `pytest tests/test_llm_config_manager.py tests/test_settings.py tests/test_prompt_loader.py -q` |
| TD-04 | `rg`-based assertions из § 4.4 Acceptance |
| TD-05..08 | per-area `pytest` + ручная sanity-проверка |

### 6.2 Final sweep before merge
```bash
.venv/bin/pytest -q                                  # full suite green
.venv/bin/ruff check tg_parser/ tests/               # lint clean
.venv/bin/mypy tg_parser/ 2>&1 | tail               # no new mypy errors
git diff main --stat                                 # sanity на размер diff'a
```

Цель: total test count **≥ 1881** (anchor из gpt55 metrics snapshot),
никаких флаков. Если pytest выходит дольше 5 минут — это сам по себе
сигнал regression, проверить.

### 6.3 No-PG vs full-PG
- Локально: тесты ходят в no-PG mode (CHANGELOG: `1881 passed, 4 skipped,
  1 deselected` — подтверждено в metrics snapshot).
- Перед PR-merge: убедиться что CI на dev-PG прошёл (если настроен) или
  явно указать в PR-description «no-PG only» с обоснованием.

---

## 7. PR / commit conventions

### 7.1 Commit message format

Используется conventional-commits (по pattern'у CHANGELOG):
```
<type>(<area>): <imperative summary>

<2-5 sentence motivation, including link to merged plan>

Refs: REVIEW_2026-04-26_MERGED_PLAN.md <TD-NN> (<source-finding-ids>).
```
`type` ∈ {`fix`, `feat`, `refactor`, `chore`, `docs`}. `area` — конкретный
модуль (`scheduler`, `watchlist`, `config`, `prompts`, `observability`, etc).

### 7.2 CHANGELOG entry per PR

В `CHANGELOG.md` создать (если ещё нет) раздел:
```markdown
## Sprint Debt-Fix Post-Living-KB — 2026-04-NN

### TD-01: ...
### TD-02: ...
```
Каждый landing-PR добавляет одну bullet'у с file/test/issue-references.
Не плодить отдельные секции на каждый коммит — один раздел на спринт.

### 7.3 Merged plan status update

После landing'a P0 PR'ов отредактировать `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`:
- В § 6 (TD-table) добавить колонку `Status` со значениями
  `closed (PR #NN)` / `partial` / `deferred`.
- В § 9 (Metrics snapshot) добавить строку `Sprint closed: 2026-04-NN, head HASH`.
- НЕ менять findings/severity/source-IDs.

Это единственная допустимая правка merged plan'а в fix-сессии.

### 7.4 Issue creation (если ещё не сделаны юзером)

Для каждого P0 TD создать GitHub issue с body:
```
**Source:** REVIEW_2026-04-26_MERGED_PLAN.md § <2|3> finding <ID>
**Priority:** P0
**Scope:** <S|M|L>

<paste merged observation + why it matters + suggested action из MERGED_PLAN>
```
Labels: `tech-debt`, `post-living-kb-review`, per-area.

---

## 8. After-sprint — handoff

После landing'a всех P0 (минимум) PR'ов:

1. **Update merged plan** (§ 7.3) — finalize Sprint closed snapshot.
2. **CHANGELOG bumped** с разделом «Sprint Debt-Fix Post-Living-KB».
3. **Open follow-up issues** для P1/P2 (если P1 не вошли в спринт):
   - issue per stretch-TD с body из MERGED_PLAN.
   - label: `tech-debt`, `post-living-kb-review`, `deferred`.
4. **Post-watch comment** в issue #15 (см.
   `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` § Post-watch report) —
   приложить ссылку на § 9 Metrics snapshot.
5. **TODO для следующего планирования:**
   - Если `## Next contract — TBD` остался placeholder'ом — открыть
     planning-сессию следующим шагом.
   - Если F11 P2 — следующий feature-спринт, убедиться что TD-02
     metrics уже в проде ≥ 24h до старта (calibration window).

---

## 9. Acceptance criteria

Fix-сессия считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 OPEN QUESTIONS отвечены (или взят explicit default)
- [ ] Все P0 TD (TD-01..04) → отдельные landed PR'ы на `main` с зелёным CI
- [ ] Каждый P0 PR имеет regression-тест (там, где scope code) или
      доказательство выполнения acceptance из § 4 (для docs-only)
- [ ] Full pytest suite зелёный (count ≥ 1881)
- [ ] CHANGELOG обновлён единым разделом «Sprint Debt-Fix Post-Living-KB»
- [ ] MERGED_PLAN.md § 6 содержит Status-колонку с `closed (PR #N)`
- [ ] Watch state на момент завершения сессии — GREEN (если уже > 24h
      окно — отметить в § 9 metrics snapshot merged plan'а)
- [ ] P1/P2 deferred-items имеют GitHub issues (хотя бы placeholder'ы)
- [ ] Post-sprint summary юзеру содержит:
  - список PR-номеров и их статус
  - какие OPEN QUESTIONS были закрыты, какие остались
  - watch verdict
  - что осталось из P1/P2 и куда перенесено
  - рекомендация что брать следующим (planning vs F11 P2 vs etc.)

---

## 10. Citation back

- **Этот промпт:** `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md`
- **Merged plan (источник истины):** `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`
- **Source review deliverables (мотивация per-finding):**
  - `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md`
  - `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md`
- **Review/merge протоколы:** `docs/notes/START_PROMPT_REVIEW_POST_LIVING_KB.md`,
  `docs/notes/START_PROMPT_REVIEW_MERGE.md`
- **Operational runbooks:**
  - `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` (TD-02 пишет PromQL туда)
  - `docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md` (TD-03b context)
- **Sprint предыдущих волн (для шаблонов CHANGELOG / PR):**
  `docs/notes/START_PROMPT_SPRINT_F11.md`, `docs/notes/START_PROMPT_SPRINT_F5C.md`

Эти ссылки — для контекста; **не копировать в commit-message**'ы кроме
`Refs: REVIEW_2026-04-26_MERGED_PLAN.md <TD-ID>` строки в footer'е.
