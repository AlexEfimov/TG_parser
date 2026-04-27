# Follow-up — Open GitHub issues for landed tech-debt items (post-Phase-2)

> **Status: ✅ COMPLETED — 2026-04-27.** Все 9 TD issues открыты и закрыты как `completed` на GitHub: [#26 TD-01](https://github.com/AlexEfimov/TG_parser/issues/26), [#27 TD-02](https://github.com/AlexEfimov/TG_parser/issues/27), [#28 TD-03a](https://github.com/AlexEfimov/TG_parser/issues/28), [#29 TD-03b](https://github.com/AlexEfimov/TG_parser/issues/29), [#30 TD-04](https://github.com/AlexEfimov/TG_parser/issues/30), [#31 TD-03c](https://github.com/AlexEfimov/TG_parser/issues/31), [#32 TD-05](https://github.com/AlexEfimov/TG_parser/issues/32), [#33 TD-NEW-A](https://github.com/AlexEfimov/TG_parser/issues/33), [#34 TD-NEW-B](https://github.com/AlexEfimov/TG_parser/issues/34). MERGED_PLAN § 6 backfilled with cross-links via commit `e7a4c1b`. Этот runbook — историческая artifact-документация; повторного запуска не требуется.

**Назначение:** короткая admin-сессия. Открыть и сразу закрыть GitHub issues для всех **9 tech-debt items**, landed во время post-Living-KB debt-fix sprint'а (Phase 1 + Phase 2). Каждое issue — это **запись в трекер**, не план работы: TD уже залендены, цель issue — пост-фактум, чтобы:

1. Любой external reviewer мог пройтись по `MERGED_PLAN.md § 6` и кликнуть на конкретное GH issue.
2. Релиз-нотификации (если они когда-нибудь будут) могли сослаться на закрытые issues.
3. Соблюдалась convention из master prompt'а § 7: «one issue per TD».

**Тип сессии:** admin / mechanical (≈ 10–15 минут, без code-changes). Сессия выполняется **в отдельном окне** от любого спринта или fix-сессии — её единственный output это закрытые issues, без commit'ов.

**Дата подготовки:** 2026-04-27 (в день закрытия Phase 2, сразу после merge PR #25).

**Когда использовать:** после того как PR #25 merged на main (commit `209ca26`). Текущее состояние на момент подготовки промпта:

- Phase 1 PRs merged: #16 (TD-04), #21 (TD-02), #22 (TD-01), #23 (TD-03a), #24 (TD-03b)
- Phase 1 close-out commit: `161bcaa`
- Phase 2 PR merged: #25 (single squash commit `209ca26` содержит TD-03c + TD-05 + TD-NEW-A + TD-NEW-B + post-watch report + MERGED_PLAN close-out)

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` § 6 «Tech-debt backlog (merged)» — это таблица из 12 строк, **9 закрытых TD** идут в issues, 5 открытых (TD-06/07/08, TD-09, TD-10) — НЕ открываются (они для Phase 3 / hygiene-tier).
2. `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` § 9 Phase 1 landing log + Phase 2 landing log — таблицы commit/test mapping для body issue'а.
3. `CHANGELOG.md` — секции «Sprint Debt-Fix Post-Living-KB — Phase 1» и «Sprint Debt-Fix Post-Living-KB — Phase 2» (для копирования impact-описаний в issue body).

### 1.2 Sanity checks

```bash
git checkout main && git pull --ff-only origin main
git status --short                              # должно быть пусто (или только operator drafts)

# Проверка что нет дубликатов (если уже открыты вручную)
gh issue list --search "TD-" --state all --limit 30 --json number,title,state

# Если результат пустой [] — продолжать.
# Если есть существующие issues с пересекающимися ID — НЕ создавать дубликаты,
# а в них добавить ссылку на PR/commit и закрыть.
```

### 1.3 Gating decisions

| ID | Вопрос | Default |
|---|---|---|
| AD-1 | Открывать closed-сразу или оставить open для visibility? | **closed-сразу** (TD уже landed; open issue для landed work — это noise). Если хочется visibility — лейбл `closed-as-completed` + close immediately. |
| AD-2 | Один issue per TD или один master issue + 9 sub-tasks? | **One per TD** — соответствует master prompt § 7 + Phase 1 precedent + позволяет ссылаться поштучно. |
| AD-3 | Лейблы? | `tech-debt` обязателен; опционально: `phase-1` / `phase-2`, `priority/p0` / `priority/p1`. |
| AD-4 | Открывать issues для TD-NEW-A и TD-NEW-B? Они не были в исходном backlog'е. | **Да** — landed в Phase 2 как полноценные TD; pattern: «discovered Phase 2 watch». В body упомянуть post-watch report. |
| AD-5 | Открывать issues для TD-06/07/08, которые deferred to Phase 3? | **Нет.** Это отдельный issue-batch когда Phase 3 откроется. Сейчас они только в `MERGED_PLAN § 6` как «open (deferred to Phase 3)». |

---

## 2. Scope

### 2.1 9 issues to open

| TD | Title (issue) | Phase | PR | Source finding | Priority |
|---|---|---|---|---|---|
| TD-01 | `fix(scheduler): align error_message truncation with D.1 contract` | 1 | #22 | S-001 | P0 |
| TD-02 | `feat(watchlist): add Prometheus metrics for matching and delivery` | 1 | #21 | C-001 | P0 |
| TD-03a | `fix(config): include resummarize in LLM scope-list across all surfaces` | 1 | #23 | S-002 / CODE-002+003+006 | P0 |
| TD-03b | `fix(config): declare anthropic prompt-cache + token-estimate as Settings fields` | 1 | #24 | S-003 / CODE-004 | P0 |
| TD-03c | `feat(prompts): PromptLoader fail-loud для required LLM stages` | 2 | #25 | S-004 / CODE-005 | P0 |
| TD-04 | `docs: close Living-KB contract across deploy and roadmap docs` | 1 | #16 | C-002, C-003, C-004, S-005 | P0 |
| TD-05 | `refactor(scheduler): centralize billing-error handling and structured logs` | 2 | #25 | C-006, S-007 | P1 |
| TD-NEW-A | `fix(health-check): Anthropic probe — switch to /v1/models (was perma-403 root)` | 2 | #25 | discovered Phase 2 watch | P1 |
| TD-NEW-B | `fix(f5c-watch): Tripwire #4 cumulative→delta semantics` | 2 | #25 | discovered Phase 2 watch | P1 |

### 2.2 Issue body template

Для каждого issue использовать этот шаблон, подставляя данные из `MERGED_PLAN § 9` + `CHANGELOG`:

```markdown
## Status

**Closed as completed** — landed in [Phase N landing log][1].

## Source finding

<копия из § 6 MERGED_PLAN: «S-XXX (description)» + ссылка на ревью>

## Resolution

<краткий 1-3-предложение summary что было сделано — копия из CHANGELOG entry header>

## Refs

- PR: #NN
- Landing commit: `<SHA>` (in-branch) → squash-merge `<main-SHA>` on main
- CHANGELOG entry: [Sprint Debt-Fix Post-Living-KB — Phase N → TD-XX][2]
- Plan row: [`MERGED_PLAN.md § 6` row TD-XX][3]
- Tests added: +N (`tests/test_xxx.py`)

[1]: https://github.com/AlexEfimov/TG_parser/blob/main/docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md#9-metrics-snapshot-на-момент-merge
[2]: https://github.com/AlexEfimov/TG_parser/blob/main/CHANGELOG.md
[3]: https://github.com/AlexEfimov/TG_parser/blob/main/docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md#6-tech-debt-backlog-merged
```

### 2.3 Recommended `gh` script

Промпт session'у можно делать вручную через `gh issue create --title ... --body-file ...`, но удобнее одним bash-loop'ом. Шаблон ниже — стартовая точка; перед запуском **прочитать каждый body и поправить под индивидуальный TD**:

```bash
# Phase 1 issues (5 штук)
for entry in \
    "TD-01|fix(scheduler): align error_message truncation with D.1 contract|22|P0" \
    "TD-02|feat(watchlist): add Prometheus metrics for matching and delivery|21|P0" \
    "TD-03a|fix(config): include resummarize in LLM scope-list across all surfaces|23|P0" \
    "TD-03b|fix(config): declare anthropic prompt-cache + token-estimate as Settings fields|24|P0" \
    "TD-04|docs: close Living-KB contract across deploy and roadmap docs|16|P0"
do
    IFS='|' read -r td title pr prio <<<"$entry"
    # cat /tmp/issue_${td}.md  # ← заранее подготовленные body-файлы из § 2.2
    issue_url=$(gh issue create \
        --title "${td}: ${title}" \
        --body-file "/tmp/issue_${td}.md" \
        --label "tech-debt,phase-1,priority/${prio,,}")
    echo "${td} → ${issue_url}"
    # Закрыть сразу с reason completed
    issue_num=$(basename "$issue_url")
    gh issue close "$issue_num" --reason completed
done

# Phase 2 issues (4 штуки) — аналогично с label phase-2
```

Альтернатива (если лень писать loop): открыть 9 issues последовательно через `gh issue create` + сразу `gh issue close`.

### 2.4 Лейблы (создать если ещё нет в репо)

```bash
gh label list | grep -E "tech-debt|phase-1|phase-2|priority"  # проверка
gh label create "tech-debt"     --color "d4c5f9" --description "Tech-debt item from MERGED_PLAN"
gh label create "phase-1"       --color "0e8a16" --description "Sprint Debt-Fix Phase 1 (2026-04-26)"
gh label create "phase-2"       --color "1d76db" --description "Sprint Debt-Fix Phase 2 (2026-04-27)"
gh label create "priority/p0"   --color "b60205"
gh label create "priority/p1"   --color "fbca04"
```

---

## 3. Verification

После открытия и закрытия всех 9 issues:

```bash
# Должно вернуть 9 issues, все state=closed
gh issue list --label "tech-debt" --state closed --limit 20 --json number,title,state | jq length
# → 9

# Каждый issue имеет ссылку на PR
gh issue list --label "tech-debt" --state closed --json number,title,body \
    | jq -r '.[] | select(.body | test("PR: #[0-9]+") | not) | .number'
# → пустой output (если не пустой — добавить ссылку на PR в body)
```

---

## 4. Handoff / next steps

После этой admin-сессии:

- `MERGED_PLAN.md § 6` ссылки на issues можно добавить отдельным doc-commit'ом (опционально; не блокирует).
- Следующая сессия по утверждённому порядку: **BUG-002 B+ hotfix** → `docs/notes/START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md`.

### Утверждённый порядок сессий (зафиксирован 2026-04-27)

| # | Сессия | Промпт-файл | Зависимость |
|---|---|---|---|
| 1 | GH-issues admin (this) | `START_PROMPT_FOLLOWUP_OPEN_GH_ISSUES_2026-04-27.md` | Phase 2 merged ✓ |
| 2 | BUG-002 B+ hotfix | `START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md` | none (independent) |
| 3 | BUG-001 MCP auth C | `START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md` | independent (другой module) |
| 4 | BUG-002 D + BUG-004 (full FSM) | `START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md` | **depends on #2 (B+ hotfix)** |
| 5 | BUG-006 Gemini E | `START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` | depends on #4 (shared `bot/agent.py`) |
| 6 | Read-hardening F (BUG-003+005-B+007) | `START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md` | independent (read-tool path) |
| 7 | Phase 3 sprint (TD-06/07/08) | `START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE3.md` | gated: F5-C traffic > 0 + критичные баги closed/deferred |

**Правила между сессиями:**

```bash
git checkout main && git pull --ff-only
.venv/bin/pytest -q | tail -5             # baseline зелёный
ssh prod 'tail -5 ~/f5c-watch/cron.log'   # watch не деградировал
# обновить BUG_LOG.md: предыдущий BUG → resolved + commit/PR
```

---

## 5. Estimated effort

| Step | Time |
|---|---|
| Required reads (§ 1.1) | 5 min |
| Подготовить 9 body-файлов из шаблона (§ 2.2) | 5–7 min |
| Запустить `gh issue create` × 9 + `gh issue close` × 9 | 2 min |
| Verification (§ 3) | 1 min |
| Optional: backfill `MERGED_PLAN § 6` cross-links | 3 min |
| **Total** | **~15–20 min** |

Это самая короткая сессия в проекте — не растягивать. Если столкнулись с blocking edge-case (например, дубликат issue'а уже открыт другим путём, или GitHub API возвращает 504) — записать в § 1.3 как новый AD-N decision и продолжить со следующим TD.
