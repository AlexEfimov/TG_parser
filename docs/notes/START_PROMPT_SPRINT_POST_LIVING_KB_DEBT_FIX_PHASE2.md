# Post-Living-KB Debt-Fix Sprint — Phase 2 (after 24h watch close)

**Назначение:** Phase 2 из двух post-Living-KB debt-fix-сессий. Закрывает
оставшийся P0 (TD-03c), берёт P1 stretch (TD-05..08), пишет post-watch
report, формирует финальный sprint-итог.

**Тип сессии:** writing — code, tests, docs, PRs, plus operational
post-watch report. Сессия выполняется в **отдельном окне** от Phase 1;
вся информация о Phase 1 читается из репозитория (git log + MERGED_PLAN
§ 6 / § 9).

**Дата подготовки промпта:** 2026-04-26 (одновременно с Phase 1; Phase 2
запускается ~24h+ позже).

**Когда использовать:** **только** после того как:

1. 24h F5-C watch window закрыто (текущее UTC ≥ `2026-04-27T11:07Z`,
   рекомендуется добавить буфер +30 мин для последнего cron-tick'а).
2. Phase 1 сессия закрыта; Phase 1 PR'ы merged или явно отмечены deferred.
3. Юзер ответил на Q2 / Q4 OPEN QUESTIONS (или взял default).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` — целиком, **с
   обновлениями Phase 1 в § 6 (Status column) и § 9 (Phase 1 landing log)**.
2. `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md` (master) —
   § 0 known caveats, § 4.3 sub-section 3c (TD-03c), § 5 (P1 stretch),
   § 7 PR conventions, § 8 after-sprint handoff.
3. Этот файл (Phase 2) — целиком.
4. `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE1.md` —
   § 3 «Sprint scope» и § 9 «Handoff» — чтобы знать что **должно было**
   landить'ся в Phase 1.
5. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md` —
   мотивация для TD-03c (CODE-005), TD-06 (CODE-007/009/010), TD-08
   (CODE-011/012).
6. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md` —
   мотивация для TD-05 (gpt55-004 + opus CODE-008), TD-07 (gpt55-013 +
   gpt55-012 + opus DOCS-004).
7. `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — § Post-watch report шаблон
   (Phase 2 заполняет его).
8. `CHANGELOG.md` — последние ~200 строк (особенно секция
   «Sprint Debt-Fix Post-Living-KB — Phase 1»).

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. 24h окно закрыто
date -u +%Y-%m-%dT%H:%M:%SZ            # должно быть ≥ 2026-04-27T11:07Z

# 2. Watch verdict log: посчитать GREEN vs TRIPWIRE
ssh prod 'cat ~/f5c-watch/cron.log'    # пройти все строки
ssh prod 'wc -l ~/f5c-watch/cron.log'  # ожидать ~24 verdict-строки (часовой cron)

# 3. Phase 1 landed: сверить с MERGED_PLAN § 9 landing log
git log --oneline main -20             # проверить наличие TD-04/02/01/03a/03b PR-merge'ей
rg "^### TD-(04|02|01|03[ab])" CHANGELOG.md  # должны быть в Phase 1 секции

# 4. Working tree чист, на новой fix-ветке
git status --short
git checkout main && git pull --ff-only origin main
git checkout -b fix/post-living-kb-debt-phase2-2026-04-NN

# 5. Baseline pytest зелёный (после Phase 1 PR'ов)
.venv/bin/pytest -q 2>&1 | tail -20
```

#### Decision tree по watch verdict'ам:

| Watch state | Действие |
|---|---|
| **All GREEN, ≥ 20 verdict rows** | Продолжать Phase 2 в полном объёме (TD-03c + P1 stretch + post-watch). |
| **All GREEN, < 20 rows** (cron не отработал нужное число раз) | Уточнить у юзера — возможно, был ssh-issue или cron сбой. Не блокирующее, но flag в § 7 financial summary. |
| **Mixed (GREEN + 1-2 TRIPWIRE с понятной RCA в логе)** | Прочитать TRIPWIRE-строки, оценить severity. Если RCA уже есть — продолжать Phase 2 + добавить TRIPWIRE-incident в post-watch report. |
| **TRIPWIRE без RCA / повторяющиеся TRIPWIRE** | **Остановиться.** Phase 2 не запускать. Сообщить юзеру: «Watch показал N TRIPWIRE без RCA. Рекомендуется hot-fix track перед Phase 2.» |

### 1.3 Phase 1 verification

Сверить Phase 1 deliverables против ожиданий из Phase 1 prompt'а § 8:

| TD | Ожидание | Если не выполнено |
|---|---|---|
| TD-04 | PR merged, 4 файла docs обновлены | Включить в Phase 2 как catch-up |
| TD-02 | PR merged, 4 metric'а в `tg_parser/api/metrics.py`, runbook обновлён | Включить в Phase 2 как catch-up |
| TD-01 | PR merged, `_truncate_error_message(... = 4096)`, regression test | Включить в Phase 2 как catch-up |
| TD-03a | PR merged, `resummarize` в `LLMConfigManager.get_all()` + docstrings | Включить в Phase 2 как catch-up |
| TD-03b | PR merged, три Pydantic-поля в `Settings` | Включить в Phase 2 как catch-up |

Если Phase 1 был частично revert'нут (по правилу TRIPWIRE-response из
Phase 1 § 5.3) — соответствующий TD идёт первым в Phase 2 как catch-up
(если RCA подтвердил, что revert был сценарием false positive) или
остаётся deferred с issue (если RCA выявил реальную проблему — нужен
другой подход).

### 1.4 Gating OPEN QUESTIONS (Phase 2 only)

Из `MERGED_PLAN.md` § 8 Blocking, для Phase 2:

| ID | Вопрос | Default per master § 1.3 |
|---|---|---|
| Q2 (TD-03c / S-004) | Prompt-loader: complete built-in defaults для всех stages **или** loud-fail? | **fail-loud** (raise `PromptLoaderError`) |
| Q4 (C-003 / DOCS-007) | Next contract — formulate now in ROADMAP_KARPATHY или ставить `Next contract — TBD`? | **`Next contract — TBD`** placeholder + ссылка на будущий планинг |

Q1 и Q3 уже должны быть закрыты Phase 1.

### 1.5 Branch strategy

Phase 2 — отдельная ветка от main (Phase 1 уже merged):

```bash
git checkout -b fix/post-living-kb-debt-phase2-2026-04-NN
```

PR'ы:
- TD-03c → отдельный PR (один)
- TD-05..08 — допустимо batch'ем по логической зоне или каждый отдельным PR (на усмотрение, см. master § 5)
- Post-watch report → отдельный коммит / PR (см. § 3.3 ниже)

---

## 2. Out of scope для Phase 2

Дополнительно к master § 2:

| Категория | Куда | Причина |
|---|---|---|
| **Anything from Phase 1** уже landed | nowhere | already done; не повторять |
| **F5-C internals fixes if watch found unresolved problem** | hot-fix track (отдельная сессия) | scope discipline; Phase 2 — debt-fix, не reactive-fix |
| **Feature scope** (F11 P2, F5-C P2, F1, F10-A, F12-A) | feature sprint | по master § 2 |
| **F11 P2 specifically** | После ≥ 24h F11-metrics calibration | TD-02 metrics landed только в Phase 1; нужен calibration window |
| **TD-09 / TD-10 (P2 backlog)** | Отдельная housekeeping-сессия | по master § 3.1 |

---

## 3. Sprint scope (Phase 2)

### 3.1 P0 finish (must)

| TD | Title | Source | Default decision |
|---|---|---|---|
| TD-03c | Prompt-loader fail-loud (digest, resummarize, all stages) | S-004 (opus CODE-005) | fail-loud per Q2 default |

**Per-TD details:** master § 4.3 sub-section 3c.

### 3.2 P1 stretch (only if capacity)

В порядке номеров. Останавливаться когда capacity исчерпан (≤ 50% sprint
time) — не брать всё сразу за счёт качества:

| TD | Title | Scope | Source |
|---|---|---|---|
| TD-05 | Scheduler billing-error helper + structlog | S/M | C-006 + S-007 |
| TD-06 | Observability ownership + F5-C client lifecycle | M | S-006, S-008, S-011 |
| TD-07 | Changelog + architecture path corrections | S | C-007, S-010 |
| TD-08 | Schema invariant comments / guards | S/M | S-014, S-015 |

**Per-TD details:** master § 5.1 / § 5.2 / § 5.3 / § 5.4.

**Не пытаться взять все 4 — реалистично 2-3 за сессию** при условии что
TD-03c и post-watch report landed первыми.

### 3.3 Post-watch report (mandatory)

После TD-03c, до P1 stretch:

1. **Прочитать полный watch-log:**
   ```bash
   ssh prod 'cat ~/f5c-watch/cron.log' > /tmp/f5c-watch-final.log
   wc -l /tmp/f5c-watch-final.log
   rg "TRIPWIRE|GREEN|YELLOW|RED" /tmp/f5c-watch-final.log
   ```

2. **Заполнить шаблон** из `docs/runbooks/F5C_DEPLOY_AND_WATCH.md`
   § «Post-watch report». Поля:
   - Window: `2026-04-26T11:07:13Z` → `2026-04-27T11:07Z` (или фактический endpoint)
   - Verdict count: GREEN / TRIPWIRE / YELLOW / RED
   - Final verdict: overall GREEN / mixed / failed
   - Incidents (если есть): по каждой TRIPWIRE-строке — RCA, PR-fix-id если есть
   - Metrics anchor: `tg_resummarize_*` counters at end of window
   - F11 metrics anchor (новое в Phase 1!): `tg_watchlist_*` from TD-02
   - Recommendations: безопасно ли стартовать F11 P2 / F5-C internals work

3. **Создать отдельный файл-отчёт:**
   - Путь: `docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md`
   - (если папка не существует — создать).
   - Закоммитить как: `docs(F5C): post-watch report 2026-04-26→2026-04-27 (24h window)`

4. **Связать с MERGED_PLAN.md § 9** — добавить sub-section:
   ```markdown
   ### Post-watch report (2026-04-27)

   See `docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md`.
   Final verdict: <GREEN|TRIPWIRE+resolved|RED+escalated>.
   ```

### 3.4 What NOT to ship in Phase 2

- ❌ Не модифицировать Phase 1 deliverables кроме как catch-up'ом (см. § 1.3).
- ❌ Не открывать F11 P2 / F5-C P2 feature work — это отдельный sprint.
- ❌ Не добавлять «Next contract» формулировку в ROADMAP_KARPATHY поверх
  Q4-default'а — placeholder `Next contract — TBD` достаточен; реальный
  контракт формулируется в отдельной planning-сессии.
- ❌ Не делать mass refactor выходящий за scope конкретного TD (master § 2).

---

## 4. Per-TD playbook

См. master prompt:

- **TD-03c** → `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md` § 4.3 sub-section 3c.
- **TD-05** → master § 5.1.
- **TD-06** → master § 5.2.
- **TD-07** → master § 5.3.
- **TD-08** → master § 5.4.

---

## 5. Watch-aware rules (post-watch)

После закрытия watch'а ограничения смягчаются, но:

1. **Не трогать F5-C internals** если watch показал TRIPWIRE и RCA не
   закрыт — это hot-fix track, не Phase 2.
2. **Post-watch report пишется ДО P1 stretch** — даёт ground truth для
   следующего планирования и фиксирует Phase 1 metrics impact на проде.
3. **F11 P2 calibration window** = `2026-04-NN` (Phase 1 TD-02 deploy time)
   + 24h. Если хочется F11 P2 после Phase 2 — сверить эту дату; не
   начинать раньше.
4. **TD-03c — поведенческое изменение upstream F5-C.** Если в проде уже
   что-то странное (даже не TRIPWIRE-уровня) — landить TD-03c в окно
   когда есть место для observation (минимум первые 4-6h после deploy).
5. **F5-C smoke-проверка после TD-03c deploy:**
   ```bash
   ssh prod 'tail -n 20 ~/f5c-watch/cron.log'   # сразу после deploy
   ssh prod 'tail -n 20 ~/f5c-watch/cron.log'   # через час
   ```
   Если появилась TRIPWIRE сразу после TD-03c → revert (см. master § 7
   commit conventions для revert-PR).

---

## 6. Testing & verification

См. master prompt § 6. Phase-2-специфика:

- TD-03c: `pytest tests/test_prompt_loader.py -q` плюс параметризованный
  тест по всем stages из `LLM_SCOPES \ {"global"}`.
- P1 stretch: per-area pytest (см. master § 6.1 таблица).
- Final sweep: `pytest -q` суммарно ≥ 1881 + новые тесты (Phase 1 и
  Phase 2 combined).

---

## 7. PR / commit conventions

См. master prompt § 7. Phase-2-специфика:

- **CHANGELOG entry**: расширить или создать раздел
  ```markdown
  ## Sprint Debt-Fix Post-Living-KB — Phase 2 (2026-04-NN)

  ### TD-03c: <bullet>
  ### TD-05: <bullet> (если landed)
  ### TD-06: ...
  ...
  ### Post-watch report: see docs/runbooks/post_watch_reports/...
  ```
- **Commit footer**: `Refs: REVIEW_2026-04-26_MERGED_PLAN.md TD-NN, Phase 2.`
- **PR labels**: `tech-debt`, `post-living-kb-review`, `phase-2`, per-area.

---

## 8. Acceptance criteria (Phase 2 + sprint close)

Phase 2 / весь debt-fix sprint считается завершённым, если:

- [ ] § 1.2 sanity-checks прошли (24h closed, watch GREEN-only OR explicit RCA in post-watch report)
- [ ] § 1.3 Phase 1 verification — все 5 Phase 1 TD landed (или explicit catch-up в Phase 2)
- [ ] § 1.4 OPEN QUESTIONS Q2+Q4 отвечены (или взят default)
- [ ] **TD-03c landed** PR на main с зелёным CI
- [ ] **Post-watch report committed** как отдельный файл + ссылка в `MERGED_PLAN.md` § 9
- [ ] (если capacity) — каждый landed P1-TD имеет свой PR/commit
- [ ] full pytest suite зелёный (count ≥ 1881 + Phase 1 додатки + Phase 2 додатки)
- [ ] CHANGELOG обновлён разделом «Sprint Debt-Fix Post-Living-KB — Phase 2»
- [ ] `MERGED_PLAN.md` § 6 — все P0 closed, P1 либо closed либо
      `deferred — issue #N` (с реальным issue-номером)
- [ ] `MERGED_PLAN.md` § 9 — final Phase 2 landing log + ссылка на post-watch report
- [ ] **GitHub-issues открыты** для:
  - P2 backlog: TD-09 (`docs/notes/archive/`), TD-10 (dead-code/dependency sweep)
  - Не-взятые P1 (если capacity не хватило)
  - Любые follow-up'ы из post-watch report (если были incidents)
- [ ] Final sprint summary юзеру содержит:
  - Полный список landed PR'ов (Phase 1 + Phase 2) с PR-#
  - Watch verdict из post-watch report (1 строка)
  - Status каждого TD (P0 / P1 / P2)
  - Какие OPEN QUESTIONS закрыты, какие остались (если есть)
  - Рекомендация что брать следующим — конкретно: planning session
    для next-contract / F11 P2 (если calibration ≥ 24h) / другая
    debt-housekeeping-сессия

---

## 9. After Phase 2 — sprint closes

1. **Sprint считается closed.** `MERGED_PLAN.md` финальный, post-watch
   report committed, GitHub issues для остатков открыты.
2. **Если Q4-default взят** (`Next contract — TBD` placeholder) — открыть
   отдельную **planning-сессию** для формулировки следующего контракта.
   Шаблон стартового промпта — см. предыдущие планинг-промпты
   (`START_PROMPT_PLANNING_F5C.md` как образец).
3. **Если capacity и желание есть для F11 P2** — feature sprint **может
   стартовать через ≥ 24h** после landing'a Phase 1 TD-02 (calibration
   window для thresholds). Стартовый промпт писать с нуля, ссылаясь на:
   - `MERGED_PLAN.md` § 5 (Recommendation alternative)
   - F11 P2 backlog в `docs/notes/FUTURE_FEATURES.md` (после Phase 1 TD-04 закрытия должен ссылаться на issue #15)
   - `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` (для F11-аналога watch-протокола, если будет deploy F11 P2)
4. **TD-09 / TD-10 (P2)** — отдельная мелкая housekeeping-сессия, можно
   делать в любой момент после закрытия sprint'а; не блокирует ничего.

---

## 10. Citation back

- **Master reference:** `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md`
- **Merged plan (источник истины, с обновлениями Phase 1):** `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`
- **Peer phase prompt (что делала Phase 1):** `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE1.md`
- **Source review deliverables:**
  - `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md`
  - `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md`
- **Watch runbook (post-watch report шаблон):** `docs/runbooks/F5C_DEPLOY_AND_WATCH.md`
- **Review/merge protocols:**
  - `docs/notes/START_PROMPT_REVIEW_POST_LIVING_KB.md`
  - `docs/notes/START_PROMPT_REVIEW_MERGE.md`

В commit-message'ах достаточно
`Refs: REVIEW_2026-04-26_MERGED_PLAN.md TD-NN, Phase 2.`
