# Post-Living-KB Debt-Fix Sprint — Phase 1 (during 24h watch)

**Назначение:** Phase 1 из двух post-Living-KB debt-fix-сессий. Эта фаза
работает **ПАРАЛЛЕЛЬНО** с продолжающимся 24h F5-C watch window
(anchor: deploy-time GREEN at `2026-04-26T11:07:13Z`, окно закрывается
≈ `2026-04-27T11:07Z`).

**Тип сессии:** writing — code, tests, docs, PRs. Сессия выполняется в
**отдельном окне** от Phase 2; всё необходимое читается из репозитория.

**Дата подготовки промпта:** 2026-04-26.

**Когда использовать:** **немедленно** после landing'a merged plan'а
(`637d4a3 docs(review): post-Living-KB merged plan + debt-fix sprint prompt`),
не дожидаясь закрытия 24h watch'а.

---

## 0. Why two phases (контекст для агента)

Полный debt-fix scope содержит изменения, которые **ухудшают качество
24h F5-C watch-сигнала** если катятся во время окна:

- **TD-03c** (prompt-loader fail-loud) меняет поведение upstream-кода
  (`prompt_loader.get`), который F5-C дёргает на каждом resummarize-tick'е.
  Если в watch появится аномалия — её нельзя будет однозначно отделить
  от потенциального side-effect'а fail-loud-логики.
- **TD-05..08** (P1 stretch) — refactor scheduler / observability /
  schema, всё в hot-path. Watch-инвариант «один кодовый снимок на 24h»
  ломается.

Phase 1 берёт **только тот subset P0**, который **не пересекается**
с F5-C critical path:

| TD | Зона | Watch-impact |
|---|---|---|
| TD-04 (docs closure) | docs only | zero |
| TD-02 (F11 watchlist metrics) | F11, не F5-C | zero (и pre-warm F11 P2 calibration) |
| TD-01 (D.1 error_message) | D.1 path, не F5-C resummarize | низкий |
| TD-03a (LLM scope visibility) | get_all + docstrings | низкий (read-only по факту) |
| TD-03b (Anthropic Settings declaration) | Settings type-only | низкий (defaults сохраняются) |

Phase 2 (после закрытия watch'а) берёт TD-03c + P1 stretch + post-watch
report. Контракт между фазами зафиксирован в § 7 этого промпта (handoff)
и в § 1 Phase 2 prompt'а (sanity-checks).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` — целиком (§ 6 / § 7 / § 8 / § 9 особенно).
2. `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md` (master) —
   § 0 known caveats, § 4.1 / § 4.2 / § 4.3 (sub-sections 3a и 3b only) /
   § 4.4 per-TD playbooks, § 7 PR conventions.
3. Этот файл (Phase 1) — целиком.
4. `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md` —
   только § 2 «Out of scope» и § 3 «Scope», чтобы знать **что НЕ трогать**.
5. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md` —
   мотивация для TD-01 (gpt55-001 + gpt55-009) и пер-finding контекст.
6. `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md` —
   мотивация для TD-02 (CODE-001) и TD-03a/3b (CODE-002/003/004/006).
7. `CHANGELOG.md` — последние ~200 строк (формат записей).
8. `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — § Post-watch report
   (TD-02 пишет PromQL туда).

### 1.2 Sanity checks (must pass before edits)

```bash
git rev-parse --abbrev-ref HEAD          # должно быть НЕ main
git status --short                        # working tree чист
ssh prod 'cat ~/f5c-watch/cron.log'      # ни одной TRIPWIRE-строки
.venv/bin/pytest -q 2>&1 | tail -20      # baseline зелёный
git log --oneline -1 main                 # ожидать 637d4a3 (merged plan + master prompt)
```

Если **любой** шаг падает — остановиться и сообщить юзеру, не приступать
к работам.

### 1.3 Gating OPEN QUESTIONS (Phase 1 only)

Из `MERGED_PLAN.md` § 8 Blocking — для Phase 1 нужны ответы только на:

| ID | Вопрос | Default per master § 1.3 |
|---|---|---|
| Q1 (S-001 / TD-01) | `error_message` truncation: 4096 как в docs или 500 как в коде? | **bump до 4096** (docs were the contract; code was the bug) |
| Q3 (C-004 / TD-04) | Issue #15 — source of truth или зеркалит файл? | **файл — source of truth**, sync issue body из файла отдельным follow-up |

Q2 (TD-03c) и Q4 (C-003 next contract) — **не нужны для Phase 1**, относятся к Phase 2.

Если у юзера нет явного ответа — взять default и явно сообщить ему в финальном summary («взято Q1=4096 / Q3=file-as-source per default»).

### 1.4 Branch / PR strategy

```bash
git checkout main
git pull --ff-only origin main           # если remote синхронизован
git checkout -b fix/post-living-kb-debt-phase1-2026-04-26
```

Один **PR на TD**:
- TD-04 → docs PR (один)
- TD-02 → feat-PR (один)
- TD-01 → fix-PR (один)
- TD-03a → fix-PR (один)
- TD-03b → fix-PR (один)

Стэкаются от одной базы; landing-порядок — § 3.2 ниже.

---

## 2. Out of scope для Phase 1

Дополнительно к master prompt § 2 (общие out-of-scope rules):

| Категория | Куда отложить | Причина |
|---|---|---|
| **TD-03c** (prompt-loader fail-loud) | Phase 2 | поведенческое изменение upstream F5-C; ухудшает watch-сигнал |
| **TD-05..08** (P1 stretch — scheduler/observability/changelog/schema) | Phase 2 | timing — берётся после 24h GREEN |
| **TD-09 / TD-10** (P2 archive / dead-code sweep) | После Phase 2 | по master § 3.1 |
| **Любая правка `ResummarizationService` / `commit_resummary` / advisory-lock / `topic_card_versions` schema** | Phase 2 | F5-C internals frozen во время watch'а (master § 2) |
| **Изменение `prompts/resummarize.yaml` или `prompts/digest.yaml`** | Phase 2 | те же причины (upstream F5-C) |
| **Post-watch report** | Phase 2 | watch ещё не закрыт |
| **Any feature scope** (F11 P2, F5-C P2, F1 Full, F10-A, F12-A) | Отдельный feature-sprint | по master § 2 |

---

## 3. Sprint scope (Phase 1)

### 3.1 TD subset

| TD | Title | Scope | Risk | Source IDs |
|---|---|---|---|---|
| TD-04 | Docs closure (PRODUCTION_DEPLOYMENT, KARPATHY roadmap, FUTURE_FEATURES, ROADMAP_V3) | M | zero | C-002, C-003, C-004, S-005 |
| TD-02 | F11 watchlist Prometheus metrics surface | S/M | zero | C-001 |
| TD-01 | Align scheduler `error_message` truncation contract | S | low | S-001 |
| TD-03a | Surface `resummarize` across LLM-config tools | S | low | S-002 part (CODE-002, CODE-003, CODE-006) |
| TD-03b | Declare anthropic cap/cache settings as Pydantic fields | S | low | S-003 (CODE-004) |

**Per-TD детали — в master prompt § 4.1 / § 4.2 / § 4.3 (только 3a и 3b!) / § 4.4.**

### 3.2 Suggested execution order

```
1. TD-04 (docs)            ← warm-up, zero-risk, прерываемый
2. TD-02 (F11 metrics)     ← быстрая прод-ценность; pre-warm F11 P2 calibration window
3. TD-01 (error_message)   ← маленький, изолированный
4. TD-03a (LLM scope)      ← single-line + docstrings + один тест
5. TD-03b (Settings fields)← добавление трёх полей + удаление getattr-fallback
```

Каждый landing → ребейз остальных PR'ов на новый main → следующий PR.

### 3.3 What NOT to ship in Phase 1 (явное исключение)

- ❌ Не модифицировать `tg_parser/processing/prompt_loader.py` (это TD-03c, Phase 2).
- ❌ Не добавлять «Why it matters» / merged-finding изменения в `MERGED_PLAN.md` body — только Status-колонка в § 6 и landing-log в § 9 (см. § 7 этого промпта).
- ❌ Не открывать GitHub-issues по P1/P2 в Phase 1 — это handoff-задача Phase 2.
- ❌ Не редактировать `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` поверх Q4-default'а — `Next contract — TBD` placeholder; финальный contract-stub формулирует Phase 2 / отдельный планировщик.

---

## 4. Per-TD playbook

См. master prompt:

- **TD-04** → `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md` § 4.4
- **TD-02** → master § 4.2
- **TD-01** → master § 4.1
- **TD-03a** → master § 4.3 sub-section 3a
- **TD-03b** → master § 4.3 sub-section 3b

**Не делать TD-03c из master § 4.3 sub-section 3c** — это Phase 2.

---

## 5. Watch-aware tactical rules

Эти правила специфичны для Phase 1 (живём параллельно с активным watch'ом):

1. **One-PR-at-a-time near end of watch window.** В последние ~3 часа до
   `2026-04-27T11:07Z` не landить два PR'а одновременно — если сработает
   tripwire, нужен один blame-кандидат.
2. **Record каждый landed PR в `MERGED_PLAN.md` § 9** — короткий sub-log:
   ```
   - TD-NN: PR #NN landed at 2026-04-NNTHH:MM:SSZ, commit-SHA <hash>, tests +N
   ```
   Это критично для post-watch correlation analysis в Phase 2.
3. **TRIPWIRE response (если сработает):**
   - Немедленно остановить in-flight PR'ы.
   - `ssh prod 'cat ~/f5c-watch/cron.log'` — посмотреть verdict-строку и
     совпадение по timestamp с последним landed PR'ом.
   - Если последний landed PR подозрителен → revert этой же сессией
     (`git revert <SHA>`, отдельный PR с лейблом `revert`, объяснение в body).
   - Если PR непричастен (timestamp не совпадает или logical-impossible) →
     остановить Phase 1, передать tripwire в hot-fix track (отдельная
     сессия), не маскировать симптомы внутри debt-PR'ов.
4. **Не делать force-push на main**, не ребейзить уже задеплоенные коммиты —
   мешает корреляции watch-данных с git-историей.
5. **PR review/CI зелёные до landing'a** — никаких shortcut'ов «merged because
   it's small».
6. **Watch state check каждые ~2-3 PR'а** — короткий sanity:
   ```bash
   ssh prod 'tail -5 ~/f5c-watch/cron.log'
   ```
   Это не блокирует работу, просто early signal.

---

## 6. Testing & verification

См. master prompt § 6 целиком. Дополнительно для Phase 1:

- После каждого PR-merge: `pytest -q` локально на новом main; ожидать
  count ≥ 1881 (anchor).
- TD-02 specific: `curl localhost:8000/metrics | grep tg_watchlist`
  должен вернуть 4 metric line'а (или хотя бы 4 metric definitions).
- TD-04 specific: `rg`-based assertions из master § 4.4 «Acceptance».

---

## 7. PR / commit conventions

См. master prompt § 7 целиком. Phase-1-специфика:

- **CHANGELOG entry**: создать раздел
  ```markdown
  ## Sprint Debt-Fix Post-Living-KB — Phase 1 (2026-04-NN)

  ### TD-04: <bullet>
  ### TD-02: <bullet>
  ### TD-01: <bullet>
  ### TD-03a: <bullet>
  ### TD-03b: <bullet>
  ```
  Один раздел, не плодить «Sprint Debt-Fix … Phase 1.1» и т.д.
- **Commit message Refs footer**: `Refs: REVIEW_2026-04-26_MERGED_PLAN.md TD-NN, Phase 1.`
- **PR labels**: `tech-debt`, `post-living-kb-review`, `phase-1`, per-area (`docs` / `watchlist` / `scheduler` / `config`).

---

## 8. Acceptance criteria (Phase 1)

Phase 1 считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 OPEN QUESTIONS Q1+Q3 отвечены (или взят default)
- [ ] **5 TD landed на main** с зелёным CI: TD-04, TD-02, TD-01, TD-03a, TD-03b
- [ ] Каждый PR имеет regression-test (TD-01 / TD-02 / TD-03a / TD-03b) или
      docs-acceptance (TD-04)
- [ ] full pytest suite зелёный (count ≥ 1881)
- [ ] CHANGELOG обновлён единым разделом «Sprint Debt-Fix Post-Living-KB — Phase 1»
- [ ] `MERGED_PLAN.md` § 6 содержит Status-колонку с `closed (PR #N)` для
      пяти Phase-1-TD; `open` или `phase 2` для остальных
- [ ] `MERGED_PLAN.md` § 9 содержит sub-section «Phase 1 landing log»
      с per-PR (TD-id, PR#, SHA, UTC timestamp)
- [ ] Watch state на момент завершения Phase 1 — GREEN (или явный TRIPWIRE
      с отчётом)
- [ ] § 7 (handoff) завершён

---

## 9. Handoff to Phase 2

Перед закрытием Phase 1 сессии сделать:

1. **Update `MERGED_PLAN.md` § 6** — Status column (`closed (PR #N)` /
   `open` / `phase 2`).
2. **Update `MERGED_PLAN.md` § 9** — добавить sub-section:
   ```markdown
   ### Phase 1 landing log (2026-04-NN)
   - TD-04: PR #NN landed YYYY-MM-DDTHH:MM:SSZ, commit <SHA>
   - TD-02: PR #NN landed ..., commit <SHA>, +N tests
   - TD-01: ...
   - TD-03a: ...
   - TD-03b: ...
   - Watch state at Phase 1 close: <GREEN|TRIPWIRE+RCA>
   - 24h watch ETA close: 2026-04-27T11:07Z
   ```
3. **НЕ редактировать Phase 2 prompt** — он уже готов. Phase 2 на старте
   сама прочитает `MERGED_PLAN.md` (§ 6 status + § 9 landing log) и
   определит свою стартовую картину.
4. **Финальное сообщение юзеру** должно содержать:
   - Список PR-номеров и их статус (merged / pending review / reverted).
   - Watch verdict at Phase 1 close.
   - 24h окно closes когда (UTC + локально UTC+4).
   - Какие OPEN QUESTIONS закрыты (Q1, Q3 — какой ответ выбран).
   - Что Phase 2 должна сделать (1 строка: TD-03c + P1 stretch + post-watch report).
   - Если был revert / TRIPWIRE — отдельный block с RCA-summary.

---

## 10. После Phase 1

Юзер открывает **отдельную сессию** через
[`START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md`](START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md)
**после** того как:

1. 24h watch window закрыто (`2026-04-27T11:07Z` + небольшой буфер).
2. Phase 1 PR'ы все merged (или явно зафиксирован deferred-список).
3. Текущая Phase 1 сессия закрыта.

Эта сессия (Phase 1) на этом завершена.

---

## 11. Citation back

- **Master reference:** `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX.md`
- **Merged plan (источник истины):** `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`
- **Peer phase prompt:** `docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md`
- **Source review deliverables:**
  - `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md`
  - `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md`
- **Watch runbook:** `docs/runbooks/F5C_DEPLOY_AND_WATCH.md`
- **Review/merge protocols:**
  - `docs/notes/START_PROMPT_REVIEW_POST_LIVING_KB.md`
  - `docs/notes/START_PROMPT_REVIEW_MERGE.md`

Эти ссылки — для контекста; в commit-message'ах достаточно
`Refs: REVIEW_2026-04-26_MERGED_PLAN.md TD-NN, Phase 1.`
