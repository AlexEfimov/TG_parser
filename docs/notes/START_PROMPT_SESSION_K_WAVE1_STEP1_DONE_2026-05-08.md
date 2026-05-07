# Session K — Wave 1 Step 1 DONE marker (2026-05-08)

---

## Pre-flight status — AWAITING 24h gate-check (Session J)

**Создан:** 2026-05-07 ~22:55 UTC+4 (планирующая сессия после Session J deploy).

**Deploy Session J:** 2026-05-07 ~18:46 UTC (22:46 UTC+4), commit `17b12b3`, PR [#61](https://github.com/AlexEfimov/TG_parser/pull/61).
**Gate-check ≥24h:** не ранее 2026-05-08 ~18:46 UTC (22:46 UTC+4).

**Что закрывает эта сессия (extended scope per self-review 2026-05-07):**
1. **Wave 1 step 1 DONE marker** — `REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` + cross-link + CHANGELOG.
2. **ADR 0005 implementation status annotation** — фиксация Variant A + D-3 hot-reload after Session J (resolves audit C-5 / C-6).
3. **Superseded markers + factual updates** — FUTURE_FEATURES L96, SESSION48 / Session29 roadmap, PRODUCT_STRATEGY § 7.1, SERVER_ARCHITECTURE scrape targets (resolves audit M-9, M-5, M-13).
4. **GH issue closure** — #46/#47/#48 (BUG-010/011/012) + #51/#52 (tech-debt) via PR keyword `Closes` (resolves audit C-4).

Все 4 пункта = **docs-only**, **3 atomic commits** в одном PR + auto-close issues при merge.

**Что НЕ закрывает:** всю Wave 1 (всего 4 шага). После step 1 — отдельная планирующая сессия для **step 2 (F4-B Core Workspaces)** в **fresh chat** (см. § 5). Также не закрывает остальные находки self-review (M-1, M-2, M-3, M-7, M-8, M-15, M-16) — отдельная «documentation hygiene» сессия (см. `START_PROMPT_DOC_HYGIENE_2026-05-XX.md` если будет создан).

**Anti-scope (важно):**
- **НЕ начинать F8-A LLM cache** — F8-A в audience-driven roadmap'е НЕ в Wave 1, это backlog FUTURE_FEATURES.md `Level A Step 7`. Старая «Wave 1 → F8-A → F5-A» последовательность из FUTURE_FEATURES.md L96 **superseded** `PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 (audience-driven Wave 1: Bot UX → F4-B → Surface Parity → Shareable Digest).
- **НЕ писать F4-B sprint prompt в этой же сессии** — § 2.1 `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` предписывает fresh chat для F4-B planning (новый контекст, не bug-fix).
- **НЕ трогать код / миграции / docker-compose** — это docs-only milestone + аннотации.
- **НЕ фиксить runbook'и BOT_LLM_FALLBACK / F5C_DEPLOY_AND_WATCH** — закрыто в отдельном hotfix (`START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md`), PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`Closes #62`). Может быть merged до или параллельно Session K (independent file sets).
- **НЕ обновлять README / USER_GUIDE / architecture / mcp-management-tools-spec** — отдельная hygiene-сессия (M-1, M-2, M-3, M-7, M-8, M-15, M-16).

---

## 0. Pre-flight § 0 — Gate-check Session J (запустить при старте)

> **ВАЖНО — исправление имени контейнера:** Bot живёт в контейнере `tg_parser_bot`
> (см. `docker-compose.yml:163 container_name`), не `tg_parser` (это API контейнер,
> `docker-compose.yml:36`). Pre-flight checks Sessions H/I/J ошибочно использовали
> `tg_parser` — Session J gate-check 2026-05-07 был **ложно-GREEN-by-luck** (оба
> контейнера оказались чистыми). Этот промпт исправляет nomenclature; см. § 5
> «Lessons learned» marker template.

```bash
# 1. Prometheus bot up
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool | grep -A2 "value"'
# Expected: value="1"

# 2. Error grep 24h — ИСПРАВЛЕНО на tg_parser_bot
ssh -p 2296 user@212.72.189.15 \
  'echo "confirm_flow_mismatch: $(docker logs --since 24h tg_parser_bot 2>&1 | grep -cE confirm_flow_mismatch)" && \
   echo "gemini_errors: $(docker logs --since 24h tg_parser_bot 2>&1 | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked|gemini_api_error")"'
# Expected: оба = 0

# 3. (опционально) API контейнер тоже чистый
ssh -p 2296 user@212.72.189.15 'docker logs --since 24h tg_parser 2>&1 | grep -cE "ERROR|Exception"'
# Expected: 0 (или объяснимый baseline)
```

| Check | Expected | Actual | Status |
|---|---|---|---|
| Prometheus `up{service="bot"}` | `value: "1"` | TBD | TBD |
| `confirm_flow_mismatch` 24h (tg_parser_bot) | `0` | TBD | TBD |
| `gemini_errors` 24h (tg_parser_bot) | `0` | TBD | TBD |

> **Pre-recorded baseline (2026-05-07 ~23:09 UTC+4, ~22h after deploy):** все 3 строки
> GREEN на `tg_parser_bot` после исправленного nomenclature. Промежуточная проверка
> подтверждает stable trajectory; финальный gate-check ≥24h всё равно нужен (не
> ранее 22:46 UTC+4 2026-05-08).

**Если gate-check FAIL:**
- расследовать регрессию (читать `docker logs --since 24h tg_parser_bot` + `tg_parser_mcp` + `tg_parser`),
- НЕ создавать DONE marker,
- если требуется hot-fix — использовать паттерн Sessions H/I/J (single PR, deploy, watch).

**Если gate-check ≥24h ещё не прошло** (старт сессии раньше 22:46 UTC+4 2026-05-08):
- DONE marker отложен до прохождения 24h окна;
- сессию можно использовать для **подготовки draft** marker'а (заполнить всё кроме «verdict» / actual gate-check значений) и закоммитить **после** GREEN gate.

---

## Session K opener (вставить в новый чат)

> Стартую Session K — Wave 1 Step 1 DONE marker (extended scope per self-review 2026-05-07).
> Сначала выполни pre-flight § 0 (gate-check 24h Session J).
> Если все 3 строки таблицы GREEN — прочитай дальше:
> `docs/notes/START_PROMPT_SESSION_K_WAVE1_STEP1_DONE_2026-05-08.md` целиком +
> `docs/notes/PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 4 (template) +
> `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 + § 7.1 +
> `docs/adr/0005-bot-llm-provider-flexibility.md` целиком +
> Sessions H/I/J PR descriptions (#58, #59, #61).
> Затем исполни **3 atomic commits**:
> - **C1** (§ 2 + § 3.1): создать `REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`, cross-link в `ROADMAP_KARPATHY_LIKE_LIVING_KB.md`, CHANGELOG `Wave 1 Step 1 — DONE marker` entry.
> - **C2** (§ 3A): аннотация ADR 0005 — Variant A finalized + D-3 hot-reload status (Session J).
> - **C3** (§ 3B + § 3C + § 3D): superseded markers (FUTURE_FEATURES L96, SESSION48_ROADMAP_V2, DEVELOPMENT_ROADMAP_SESSION29) + § 7.1 PRODUCT_STRATEGY F-Prereq-1 update + SERVER_ARCHITECTURE scrape targets.
> PR description должно содержать `Closes #46, #47, #48, #51, #52` (auto-close при merge).
> Branch: `docs/session-k-wave1-step1-done-2026-05-08`.
> **НЕ** делать F8-A LLM cache — это backlog, не Wave 1.
> **НЕ** писать F4-B Core sprint prompt — отдельная planning sub-session в fresh chat (см. § 5).
> **НЕ** трогать runbook'и (закрыто PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63)) или README/USER_GUIDE (отдельная hygiene сессия).
> Anti-scope (см. pre-flight выше) исполнять буквально.

---

## 1. Контекст — где Session K в roadmap'е

```
Wave 1 step 1 (Bot UX hardening, ~1.5–2 сессии extended scope):
    Session H (BUG-011 read-context)  ✅ PR #58 / 993451d
    Session I (BUG-010 username alias) ✅ PR #59 / 69243e6
    Session J (ADR 0005 + runbook)     ✅ PR #61 / 17b12b3   ← deployed 2026-05-07
        ↓ 24h watch
    Session K — Wave 1 Step 1 DONE marker (этот промпт)   ← сейчас
        ↓
Wave 1 step 2 (F4-B Core Workspaces, ~2.5 сессии):
    Planning sub-session (fresh chat, ~0.3 сессии)
        → produce START_PROMPT_SPRINT_F4B_CORE_2026-05-XX.md
    Sprint (~2.5 сессии, single PR с 5 atomic commits)
        ↓ deploy + 24h watch
    Wave 1 Step 2 DONE marker
        ↓
Wave 1 step 3 (Surface Parity, ~1–2 сессии)
        ↓
Wave 1 step 4 (Shareable Digest via TG-channel, ~0.3 сессии)
        ↓
Decision Point после Wave 1 (~3–4 месяца) — § 5.3 PRODUCT_STRATEGY
```

**Источник истины roadmap'а:**
- [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) — что/для кого
- [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) — packaging/quality bar/DONE marker template

---

## 2. Создать `docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`

Используется **canonical шаблон** из § 4 `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`. Не отклоняться — это step-marker контракт.

### 2.1 Содержание (заполнить точные значения при старте сессии)

```markdown
# Wave 1 Step 1 — DONE marker

**Дата:** 2026-05-08
**Закрывает:** Wave 1 step 1 (Bot UX hardening) per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)
**Packaging:** decision A3 (hybrid — bug-fix отдельным PR, ADR adoption + runbook одним PR с 2 atomic commits) per
[`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 1.1](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md)

## 1. Что закрыто

| Session | PR | Squash SHA | Deployed | 24h watch verdict |
|---|---|---|---|---|
| H — BUG-011 read-context preservation | #58 | 993451d | 2026-05-03 ~XX:XX UTC | GREEN |
| I — BUG-010 username alias resolution | #59 | 69243e6 | 2026-05-06 ~XX:XX UTC | GREEN |
| J — ADR 0005 bot-scope LLM config + BOT_LLM_FALLBACK runbook | #61 | 17b12b3 | 2026-05-07 ~18:46 UTC | GREEN (заполнить из gate-check § 0) |

> Точное deploy-время Sessions H/I — извлечь из CHANGELOG.md / git log при старте Session K.
> Watch verdict для Session J — заполнить значениями из pre-flight § 0 этого промпта.

## 2. Monitoring-only / unresolved

| Item | Reason | Re-evaluate trigger |
|---|---|---|
| BUG-012 | Cosmetic — pagination phrasing на hint fields, mitigated в `prompts/bot.yaml` v1.5.0 (commit a7dbaac) | New sighting in production logs |

## 3. Accumulated observations

### 3.1 Parity tracker entries

См. [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md):
- **O-1** (добавлена 2026-05-03 в commit `9d4f7e8` — окно Session H) — Atomic
  `move_workspace_source` defer до signal'а. Surface gap для F4-B Core MVP;
  consciously deferred per Q4 refined decision. Action для F4-B planning
  sub-session — verify decision still holds.
- **O-2** (добавлена 2026-05-06 в commit `cab6efd` — окно Session I) — BUG-007
  fuzzy-suggestion gap on status-check pathway. Smoke-quality observation из
  Session I post-deploy Telegram dialog. **Action не выполнен в Session J** —
  audit pass `rg -n "не найден|not found" tg_parser/bot/tools.py | rg -v
  _build_no_results_suggestion` отложен. Track как potential BUG-013 candidate
  (intra-surface, не parity scope).

### 3.2 New FUTURE_FEATURES items

**Нет нового FUTURE_FEATURES** — Wave 1 step 1 был bug-fix + ADR adoption.

**Но:** self-review актуальной документации 2026-05-07 нашёл **~30 расхождений**
между документами и кодом (см. отдельный отчёт в чате). Из них:
- В этом milestone (Session K extended scope) фиксятся **C-4 / C-5 / C-6 / M-5 / M-9 / M-13** (см. § 8 PR description).
- Остальные (M-1, M-2, M-3, M-7, M-8, M-15, M-16) — отдельная documentation hygiene сессия (~0.5 сессии, до F4-B planning).
- Critical runbook fixes (C-1, C-2 — wrong container/service names) — отдельный hotfix PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`docs/hotfix-runbook-nomenclature-2026-05-08`, `Closes #62`); merged до или параллельно Session K.
- Latent code mini-fix (M-11, M-12, M-17 — bot metrics resolved model + resolve_full bot guard + TopicCardVersion docstring) — opportunistic в любой следующий bot-touch sprint.

### 3.3 Signals collected (для Decision Point — § 5 PLANNING_WAVE1_EXECUTION_PLAN)

**Нет внешних signals** на момент закрытия step 1 — Wave 1 step 1 целиком inward-facing
(Bot UX hardening для owner-as-A1 user). Внешние signals начнут собираться после step 2 (F4-B
Core открывает workspace-сценарии для curators) и step 4 (shareable digest).

## 4. Pre-next-step readiness checklist

- [ ] All 3 deploys 24h watch GREEN (заполнить из gate-check § 0)
- [ ] 0 регрессий по существующим тестам (final baseline 2047 passed после Session J)
- [ ] CHANGELOG.md обновлён под `Unreleased` для Sessions H/I/J — done
- [ ] Cross-link на этот marker в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) (one-line entry)

## 5. Lessons learned

1. **Hybrid packaging A3 валиден.** Sessions H/I (single PR each) + Session J (single PR с 2 atomic commits) дали 3 атомарных rollback'а с независимыми 24h watch'ами. 0 регрессий за окно. Применить тот же паттерн для F4-B Core sprint (5 atomic commits в одном PR).

2. **REQUIRED_PROMPT_STAGES sync с LLM_SCOPES — implicit contract.** Session J выявил что добавление scope в `LLM_SCOPES` без обновления `REQUIRED_PROMPT_STAGES` ломает regression-тест (`tests/test_prompt_loader.py::test_required_stages_match_llm_scopes`). Будущие изменения LLM scope'ов должны обновлять оба места одной commit.

3. **MagicMock fallback для static settings.** `getattr(self._static, "bot_gemini_model", None)` потребовался чтобы `LLMConfigManager.resolve("bot")` не падал на `unittest.mock.MagicMock` без `bot_gemini_model` атрибута — pattern полезен для других scope'ов с unique static settings.

4. **Pre-flight container nomenclature regression.** Pre-flight checks Sessions
   H/I/J использовали `docker logs ... tg_parser` для grep'а bot-specific метрик
   (`confirm_flow_mismatch`, `gemini_*`), но это **API контейнер**
   (`docker-compose.yml:36`) — bot живёт в `tg_parser_bot` (`docker-compose.yml:163`).
   Session J gate-check 2026-05-07 был ложно-GREEN-by-luck (оба контейнера чистые).
   `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 1.2 уже использует правильное имя
   `tg_parser_bot`; Sessions H/I/J prompts отклонились без обоснования. **Action для
   F4-B и далее:** все pre-flight checks для bot-метрик должны указывать
   `tg_parser_bot` (или явно проверять оба контейнера, если cross-cutting).
   **Action taken (2026-05-08):** runbook nomenclature corrected в production
   runbook'ах `BOT_LLM_FALLBACK.md` и `F5C_DEPLOY_AND_WATCH.md` через PR
   [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`Closes #62`); BOT
   pre-flight + post-procedure теперь grep'ят `tg_parser_bot`, F5C deploy
   команды используют actual compose service names (`tg_parser`, `mcp`, `tg_bot`
   с `--profile bot`). Останется закрепить паттерн в новых session prompts.

## 6. Следующий шаг

**Wave 1 step 2 — F4-B Core Workspaces.**

Planning sub-session (~0.3 сессии) — **в fresh chat**, не продолжение Session K — read:
- [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) § 4 Q1–Q8
- [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 8](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)

Apply preliminary recommendations (Q1=B, Q3=skip-bot, Q5=A, Q6=A, Q7=C, Q8=C) +
locked Q2/Q4 refinements (2026-05-03). Produce
`START_PROMPT_SPRINT_F4B_CORE_2026-05-XX.md` (~700 строк по образцу
[`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md)).
```

### 2.2 Pre-fill инструкция при старте Session K

При старте Session K заполнить плейсхолдеры:

1. **Deploy timestamps** Sessions H, I, J — извлечь из git commit timestamps (`git log -1 --format="%ai" 993451d`) или CHANGELOG.md.
2. **Watch verdicts** для Sessions H, I — извлечь из commits, последовавших за их PR merge (если были hot-fix коммиты в течение 24h после deploy — verdict yellow; иначе GREEN).
3. **Watch verdict** для Session J — заполнить **результатами pre-flight § 0** этого промпта.
4. **Parity tracker O-2 summary** — прочитать `docs/notes/PARITY_DECISION_TRACKING.md`, найти `O-2`, скопировать 2-3 строки summary.

### 2.3 Cross-link refresh в ROADMAP_KARPATHY_LIKE_LIVING_KB.md

Добавить one-line entry в подходящее место (предположительно «История» раздел или Wave 1 секцию):

```markdown
- 2026-05-08 — Wave 1 step 1 (Bot UX hardening) DONE.
  See [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md).
```

Точное место вставки определить при чтении файла.

---

## 3. CHANGELOG.md — Unreleased entry (для C1)

Добавить раздел **под существующим Session J entry**, **над** Session I entry:

```markdown
### Wave 1 Step 1 — DONE marker + ADR 0005 annotation + roadmap markers (Session K, 2026-05-08)

**Контекст.** Закрытие Wave 1 step 1 (Bot UX hardening) per
`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1. Sessions H + I + J все
deployed и 24h watch GREEN. Параллельно — extended docs scope per self-review
актуальной документации 2026-05-07.

- `docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` — DONE marker создан (template C1 из PLANNING_WAVE1_EXECUTION_PLAN § 4).
- `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — one-line cross-link на DONE marker.
- `docs/adr/0005-bot-llm-provider-flexibility.md` — Implementation status block + D-3 per-call resolution (Session J landed).
- `docs/notes/FUTURE_FEATURES.md` L96 (Wave 1.5 → F8-A → F5-A) — supersede note.
- `docs/notes/SESSION48_ROADMAP_V2.md` + `DEVELOPMENT_ROADMAP_SESSION29.md` — superseded banner.
- `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 7.1 — F-Prereq-1 status update (filed in FUTURE_FEATURES + cross-linked).
- `docs/SERVER_ARCHITECTURE.md` — Prometheus scrape targets table extended c `tg_parser_bot` job.

Tracker: см. `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 4 (template C1) +
self-review актуальной документации 2026-05-07 (resolves C-4, C-5, C-6, M-5, M-9, M-13).
GitHub issues closed: #46, #47, #48 (BUG-010/011/012) + #51, #52 (tech-debt связанные).
```

> Этот entry размещается в коммите C1 и описывает все 3 коммита Session K (см. § 8).
> Отдельных CHANGELOG entries для C2 / C3 не нужно — они часть одного milestone.

> **Это конец Commit 1 (C1).** PR будет содержать ещё 2 коммита (C2 + C3) — см. ниже.

---

## 3A. Commit 2 — ADR 0005 implementation status annotation

**Файл:** `docs/adr/0005-bot-llm-provider-flexibility.md`

**Контекст из self-review:** ADR 0005 имеет **Status: Accepted (2026-05-02)**, но раздел «Контекст» описывает старое pre-Session-J состояние без явной пометки исторического характера. Также строка ~139–141 «Без hot-reload в живом процессе» **противоречит** реализованному в Session J `_resolved_model()` (runtime model resolution per call).

**Цель commit'а:** не менять accepted decisions, а **зафиксировать post-Session-J implementation status** через две вставки.

### 3A.1 Вставка #1 — после блока «Контекст» (~line 30-32)

```markdown
> **Implementation status (2026-05-07 — Session J landed PR #61, commit `17b12b3`).**
>
> Раздел «Контекст» выше описывает **pre-Session-J** состояние. Текущая реализация:
>
> - `LLM_SCOPES` в `tg_parser/config/settings.py:837` включает `"bot"`.
> - `LLMConfigManager.set(scope="bot", ...)` (строки 923–936) валидирует D-2 (provider только `gemini`, `temperature` / `max_tokens` запрещены).
> - `LLMConfigManager.resolve("bot")` (строки 972–975) реализует D-1 — глобальный override **игнорируется** для bot scope.
> - `GeminiAgent._resolved_model()` (`tg_parser/bot/agent.py:143–154`) дёргает `llm_config.resolve("bot")` **на каждый вызов** → runtime model swap без рестарта процесса (см. § «Решение» Variant A + D-3 ниже).
> - `tools.py` TOOL_DECLARATIONS для `set_llm_config` / `reset_llm_config` документируют scope `"bot"` + ADR 0005 D-1 / D-2 constraints.
> - Runbook: `docs/runbooks/BOT_LLM_FALLBACK.md` оперативно дополняет этот ADR (Variant B failover **отвергнут** в пользу manual procedure + quarterly drill).
```

### 3A.2 Вставка #2 — заменить строку «Без hot-reload в живом процессе»

Найти в § «Решение» (Variant A) строку:

```
Без hot-reload в живом процессе (рестарт не требуется для смены `BOT_GEMINI_MODEL`,
требуется для смены `GEMINI_API_KEY`).
```

Заменить на:

```markdown
**D-3 — Per-call model resolution (Session J, 2026-05-07).** `GeminiAgent._resolved_model()`
читает `llm_config.resolve("bot")` на **каждый** `_call_gemini` invocation. Runtime
model swap (`set_llm_config(scope="bot", model="...")`) применяется **без рестарта
процесса** — изменение модели берёт силу со следующего bot-запроса. Рестарт всё
ещё требуется для смены `GEMINI_API_KEY` (env-var) — для этого см. `BOT_LLM_FALLBACK`
runbook § 3.4 / § 4.5.
```

### 3A.3 Update header

```markdown
**Status:** Accepted 2026-05-02 (Variant A + D-1 + D-2). Updated 2026-05-07 (Session J — D-3 per-call resolution implementation).
```

### 3A.4 Commit message (C2)

```
docs(adr-0005): annotate post-Session-J implementation status (Variant A + D-3 hot-reload)

ADR 0005 был принят 2026-05-02 в Variant A (bot static defaults), но раздел
«Контекст» описывал pre-Session-J состояние без пометки. Также строка «Без
hot-reload в живом процессе» противоречила реализованному в Session J
GeminiAgent._resolved_model() (per-call resolution → runtime model swap без
рестарта).

- Implementation status block (после § Контекст) — фиксирует что Variant A +
  D-1 + D-2 + D-3 реализованы; ссылки на code locations.
- D-3 — per-call model resolution: новое decision lemma, заменяет «Без
  hot-reload» формулировку. Рестарт всё ещё требуется только для смены
  GEMINI_API_KEY (env-var) — cross-link на BOT_LLM_FALLBACK § 3.4 / § 4.5.

Refs: self-review актуальной документации 2026-05-07 (C-5, C-6).
```

---

## 3B. Commit 3 — Superseded markers + § 7.1 + SERVER_ARCHITECTURE

Один atomic commit, 4 файла (низко-связанные правки одного типа — «привести устаревшие документы в синхронизацию с фактом»).

### 3B.1 `docs/notes/FUTURE_FEATURES.md` — пометить L96 как superseded

Найти блок (примерно L94-L100):

```markdown
**Зафиксированная последовательность (15 апреля 2026):** Wave 1.5 → F8-A → F5-A
```

Заменить на:

```markdown
**Зафиксированная последовательность (15 апреля 2026):** Wave 1.5 → F8-A → F5-A

> **⚠️ Superseded (2026-05-02).** Эта последовательность была актуальна
> для **infrastructure-driven** roadmap'а до перехода на audience-driven
> модель. Текущий приоритет — **audience-driven Wave 1**: Bot UX hardening
> → F4-B Core Workspaces → Surface Parity → Shareable Digest. См.
> [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).
> F8-A LLM cache **остаётся в backlog'е** (Level A Step 7), но не блокирует Wave 1.
> F5-A persistent KB **завершён** ранее (см. `ROADMAP_V3_PRODUCTION_FIRST.md` Wave 1).
```

### 3B.2 `docs/notes/SESSION48_ROADMAP_V2.md` — добавить superseded banner

В самом верху файла (после `# ` заголовка) добавить:

```markdown
> **⚠️ Superseded (2026-05-02).** Этот roadmap был актуален на момент Session 48
> (~2026-04-XX). Текущая версия roadmap — двухслойная:
>
> - **Operational track:** [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) (что построено / что в backlog инфраструктурно).
> - **Strategic track:** [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) (audience-driven Wave 1 = Bot UX → F4-B → Surface Parity → Shareable Digest).
>
> Этот файл сохраняется для исторического контекста; не использовать как source of truth.
```

### 3B.3 `docs/notes/DEVELOPMENT_ROADMAP_SESSION29.md` — добавить superseded banner

Аналогично § 3B.2:

```markdown
> **⚠️ Superseded (2026-05-02).** Этот roadmap из Session 29 (~2026-03-XX);
> заменён последовательностью:
> Session 48 roadmap → ROADMAP_V3_PRODUCTION_FIRST → PRODUCT_STRATEGY_AUDIENCE_DRIVEN.
> Сохраняется для исторического контекста; не использовать как source of truth.
> Актуальный план: [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 5.1.
```

### 3C. `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 7.1 — F-Prereq-1 status update

Найти в § 7.1 строку (примерно):

```
> **Не отражено ни в одном существующем документе** — это «riser» для будущих feature'ов A4 (...).
```

Заменить на:

```markdown
> **Status (updated 2026-05-08):** Filed as **F-Prereq-1 — SaaS MTProto Legal Wrapping**
> в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) (L28 + детальная секция L2296+).
> Cross-linked в [`MONETIZATION_MECHANISMS_2026-05-02.md`](MONETIZATION_MECHANISMS_2026-05-02.md)
> § «SaaS dependencies». Это «riser» для будущих feature'ов A4 (multi-user SaaS),
> не блокирует Wave 1 (audience-driven Wave 1 целиком single-tenant per A1 owner).
```

### 3D. `docs/SERVER_ARCHITECTURE.md` — Prometheus scrape targets

Найти секцию про Prometheus scrape jobs / targets (поиск `scrape_configs` / `prometheus.yml` / `tg_parser_mcp` / job_name). Должна быть таблица или список scrape targets.

**Текущее состояние (per self-review):** перечислены только API + MCP scrape jobs.

**Должно быть:** добавить scrape для bot контейнера, реально настроенный в `docker/prometheus.yml` job `tg_parser_bot` → `tg_bot:8081`, label `service: bot` (за Session F deploy + TD-bot-prometheus-scrape close commit ec52060).

Inline edit (либо в таблицу, либо в список):

```markdown
| job_name | target | service label | metrics path |
|---|---|---|---|
| `tg_parser_api` | `tg_parser:8000` | `api` | `/metrics` |
| `tg_parser_mcp` | `mcp:8002` | `mcp` | `/metrics` |
| `tg_parser_bot` | `tg_bot:8081` | `bot` | `/metrics` (added Session F, TD #53 close commit `ec52060`) |
```

> Если фактическая структура SERVER_ARCHITECTURE.md другая — adapt syntax, но три job'а должны быть перечислены.

### 3B+C+D Commit message (C3)

```
docs(notes): superseded markers + F-Prereq-1 status + SERVER_ARCHITECTURE scrape targets

Self-review актуальной документации 2026-05-07 нашёл несколько устаревших
формулировок, которые направляют читателя на superseded plans:
- FUTURE_FEATURES.md L96 «Wave 1.5 → F8-A → F5-A» без supersede note;
- SESSION48_ROADMAP_V2.md / DEVELOPMENT_ROADMAP_SESSION29.md помечены «Утверждён»
  без указания на audience-driven замену;
- PRODUCT_STRATEGY § 7.1 говорил «не отражено ни в одном документе» про
  F-Prereq-1, хотя FUTURE_FEATURES + MONETIZATION_MECHANISMS его уже содержат;
- SERVER_ARCHITECTURE.md scrape targets не упоминал bot scrape job
  (фактически настроен в docker/prometheus.yml после Session F + TD #53 close).

- FUTURE_FEATURES.md: inline supersede note под L96.
- SESSION48_ROADMAP_V2.md / DEVELOPMENT_ROADMAP_SESSION29.md: superseded banner
  в начале файла + cross-link на ROADMAP_V3 + PRODUCT_STRATEGY.
- PRODUCT_STRATEGY § 7.1: F-Prereq-1 status update с cross-links на
  FUTURE_FEATURES L2296+ и MONETIZATION_MECHANISMS.
- SERVER_ARCHITECTURE.md: scrape targets table extended с tg_parser_bot job
  (per docker/prometheus.yml настройки и TD-bot-prometheus-scrape close).

Refs: self-review актуальной документации 2026-05-07 (M-9, M-5, M-13).
```

---

## 4. Verification gates

### 4.1 Self-review checklist (extended scope)

**C1 — DONE marker:**
```
[ ] docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md создан
[ ] Шаблон § 4 PLANNING_WAVE1_EXECUTION_PLAN — все 5 секций (Что закрыто / Monitoring-only / Observations / Readiness checklist / Lessons learned) заполнены
[ ] Все 3 watch verdicts заполнены реальными значениями (не TBD)
[ ] Cross-link добавлен в ROADMAP_KARPATHY_LIKE_LIVING_KB.md
[ ] CHANGELOG.md `Wave 1 Step 1 — DONE marker` entry добавлен
[ ] PARITY_DECISION_TRACKING.md O-1 + O-2 summary включён в § 3.1 marker'а
```

**C2 — ADR 0005 annotation:**
```
[ ] docs/adr/0005-bot-llm-provider-flexibility.md — Implementation status block после § Контекст добавлен
[ ] D-3 per-call resolution block заменил «Без hot-reload» формулировку
[ ] Header Status обновлён: «Accepted 2026-05-02 (...). Updated 2026-05-07 (Session J — D-3 ...)»
[ ] grep -n "Без hot-reload" docs/adr/0005-*.md → 0 matches
```

**C3 — Superseded markers + § 7.1 + SERVER_ARCHITECTURE:**
```
[ ] docs/notes/FUTURE_FEATURES.md — superseded note под L96 («Wave 1.5 → F8-A → F5-A»)
[ ] docs/notes/SESSION48_ROADMAP_V2.md — banner в начале файла
[ ] docs/notes/DEVELOPMENT_ROADMAP_SESSION29.md — banner в начале файла
[ ] docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md § 7.1 — «не отражено ни в одном документе» заменено на F-Prereq-1 status update
[ ] docs/SERVER_ARCHITECTURE.md — scrape targets секция содержит tg_parser_bot job
```

**Cross-cutting:**
```
[ ] git log --oneline --since="2026-05-02" показывает 3 session commits (Sessions H/I/J) + cab6efd planning + 3 Session K commits — без other code changes
[ ] grep -r "F8-A LLM cache" docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md → 0 matches (не должно быть)
[ ] PR description содержит `Closes #46, #47, #48, #51, #52`
[ ] PR title явно говорит «Session K» + «Wave 1 Step 1 DONE»
```

### 4.2 No-code change verification

```bash
git diff --stat origin/main..HEAD
# Expected:
#   docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md     | NEW (~80-120 lines)
#   docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md        | +2-3 lines
#   docs/notes/FUTURE_FEATURES.md                        | +5-8 lines (supersede note)
#   docs/notes/SESSION48_ROADMAP_V2.md                   | +6-10 lines (banner)
#   docs/notes/DEVELOPMENT_ROADMAP_SESSION29.md          | +6-10 lines (banner)
#   docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_*.md     | ±3-5 lines (§ 7.1)
#   docs/adr/0005-bot-llm-provider-flexibility.md        | +15-25 lines
#   docs/SERVER_ARCHITECTURE.md                          | +3-5 lines (scrape table)
#   CHANGELOG.md                                         | +12-18 lines
# 0 changes in tg_parser/, tests/, docker-compose.yml, prompts/, migrations/, docs/runbooks/
```

> **Важно:** `docs/runbooks/` НЕ должны меняться в этом PR — runbook nomenclature
> hotfix живёт в отдельном PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63)
> (`START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md`, `Closes #62`).

### 4.3 CI

Все 5 checks GREEN (Lint Documentation должен пройти; Test Python 3.12 — нет code changes, должен быть фактически no-op).

### 4.4 GH issue auto-close verification (post-merge)

После merge PR проверить что issues #46/#47/#48/#51/#52 автоматически закрыты:

```bash
for n in 46 47 48 51 52; do
  echo -n "#$n: "
  gh issue view $n --json state -q .state
done
# Expected: все 5 = "CLOSED"
```

Если какой-то из issues остался open (например, GitHub keyword не сработал) — закрыть вручную:

```bash
gh issue close 46 --comment "Closed by Session H deploy (PR #58 / 993451d) + Session K marker (PR #XX)"
# Аналогично для #47 (Session H/I), #48 (BUG-012 mitigation a7dbaac), #51, #52
```

---

## 5. После Session K — handover к F4-B Core planning

### 5.1 Когда стартовать F4-B planning sub-session

**Сразу после merge** Session K PR (или в любое удобное время — F4-B planning не зависит от deploy).

### 5.2 Где стартовать

**FRESH CHAT** — не продолжение Session K.

Обоснование (per `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 2.1):
> «**Чат:** fresh (не продолжение Session H/I/J — F4-B это новый контекст, не bug-fix).»

То же применимо к Session K (закрытие bug-fix wave) → F4-B planning (новая фича).

### 5.3 Что должна сделать planning sub-session

Per § 2.1 PLANNING_WAVE1_EXECUTION_PLAN:

1. **Прочитать** `PLANNING_F4B_WORKSPACES_PREP.md` целиком, особое внимание на § 4 Q2 + Q4 (refined 2026-05-03 deep-dive — locked semantics).
2. **Confirm preliminary recommendations** из `PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 8.x:
   - Q1 = B (opt-in, no default workspace)
   - Q3 = skip-bot-MVP (MCP+CLI only)
   - Q5 = A (M2M shared `workspace_sources`)
   - Q6 = A (mirror F4-A any-source visibility)
   - Q7 = C (skip F11 watchlist integration в MVP)
   - Q8 = C (skip F6 digest integration в MVP)
3. **Apply locked refined Q2 + Q4** (3 edge cases для Q2 + 3 refinements для Q4 — см. `PLANNING_F4B_WORKSPACES_PREP.md` § 4 Q2/Q4 «Refined decisions»).
4. **Produce** `docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-XX.md` (~700 строк, 5 фаз: schema → service → MCP/CLI → scoping → tests) по образцу [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md).
5. **Karpathy 7-checklist pass** — `docs/adr/0006-karpathy-like-living-kb-principles.md`.

### 5.4 Что planning sub-session делать НЕ должна

- Не реализовывать код (это будет F4-B Core sprint после planning).
- Не изменять F4-A контракт (`CurrentUser`, `allowed_channel_ids`, ownership).
- Не объединять F4-B planning + F4-B sprint в одну сессию (planning ~0.3 + sprint ~2.5 сессии — разные концентрации).

---

## 6. Risks

**R-1 — Gate-check FAIL.** Если 24h watch Session J yellow / FAIL — DONE marker блокируется до hot-fix. Mitigation: при FAIL немедленно переходить в режим hot-fix sprint (паттерн Sessions H/I/J), не делать DONE marker с yellow verdict.

**R-2 — Pre-fill Sessions H/I deploy timestamps неточные.** Mitigation: использовать
PR merge timestamps как proxy (deploy шёл сразу после merge, lag ~5 мин):
- Session H: PR #58 merged 2026-05-03T13:32:07Z, см. также
  [`HANDOVER_SESSION_H_TO_I_2026-05-03.md`](HANDOVER_SESSION_H_TO_I_2026-05-03.md) §
  «Session H — статус ЗАКРЫТА» — deploy подтверждён `tg_bot` healthy + prompts/bot.yaml
  v1.6.0 loaded, документ датирован ~17:38 UTC+4 (~13:38 UTC), т.е. deploy
  ~17:33–17:38 UTC+4.
- Session I: PR #59 merged 2026-05-06T15:36:25Z; deploy подтверждён в Session J
  pre-flight § 5.4 Telegram smoke (этот же документ) — отдельного handover marker
  для Session I→J не создавался.
- Session J: deploy 2026-05-07 ~22:46 UTC+4 (18:46 UTC) — точный timestamp есть в
  conversation history Session J.

Если требуется precision — `ssh -p 2296 user@212.72.189.15 'docker logs --since 1w
tg_parser_bot 2>&1 | grep -i "starting\|startup complete" | head -10'`.

**R-3 — Двойная роль Session K как closure + handover.** Сессия техническая (DONE marker), но также подготавливает F4-B planning. Risk что planning sub-session начнут в том же чате (anti-pattern per § 2.1 PLANNING_WAVE1_EXECUTION_PLAN). Mitigation: § 5.2 этого промпта эксплицитно требует fresh chat; opener (выше) повторяет это требование.

---

## 7. Out of scope (явно)

- **F8-A LLM cache** — backlog FUTURE_FEATURES.md `Level A Step 7`, не Wave 1, **НЕ делать в Session K**. Reasoning: audience-driven Wave 1 (4 шага) приоритетнее любых infrastructure-improvements; F8-A зайдёт когда станет блокером F5-A или появится capacity-driven driver.
- **F4-B Core planning** — отдельная сессия в fresh chat, см. § 5.
- **`ROADMAP_V3_PRODUCTION_FIRST.md`** — устарел (написан до audience-driven); ревизия = баннер «приоритеты после 2026-05-02» — **отложен в documentation hygiene sprint** (audit C-3 двойного определения «Wave 1»).
- **Runbook nomenclature fixes** (BOT_LLM_FALLBACK + F5C_DEPLOY_AND_WATCH) — закрыто в отдельном hotfix PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) per `START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md` (`Closes #62`). Если PR #63 ещё не merged к моменту старта Session K — **не блокирует**, можно работать параллельно (independent file sets).
- **README / USER_GUIDE / architecture.md / business-requirements / mcp-management-tools-spec / chatgpt-mcp-compatibility / testing-strategy** — отдельная documentation hygiene сессия (M-1, M-2, M-3, M-7, M-8, M-15, M-16 из self-review).
- **ADR 0001 / 0003 / 0004 implementation status sections** — также documentation hygiene sprint (M-3 из self-review).
- **Code mini-fixes** (M-11 metrics resolved model, M-12 resolve_full bot guard, M-17 TopicCardVersion docstring) — opportunistic в bot-touch sprint, не Session K.
- **Contract hardening** (M-6 — content_hash в schema + validation tests для 4 contracts) — отдельный sprint, не Session K.

> **Принцип scoping:** Session K = closure milestone + targeted accumulated docs cleanup,
> tightly связанный с Wave 1 step 1 и Session J landing. Всё остальное — separate scope'ы.

---

## 8. PR / commit plan (extended scope)

**Branch:** `docs/session-k-wave1-step1-done-2026-05-08`

**Single PR, 3 atomic commits в порядке C1 → C2 → C3:**

### Commit 1 (C1) — DONE marker

```
docs(milestone): Wave 1 Step 1 DONE marker — Bot UX hardening complete (Session K)

Sessions H (BUG-011) + I (BUG-010) + J (ADR 0005 + runbook) — all deployed
and 24h watch GREEN. Wave 1 step 1 closed per
PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md § 4 template C1.

- docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md created (DONE marker).
- docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md cross-link added.
- CHANGELOG.md `Wave 1 Step 1 — DONE marker` Unreleased entry.

Next: Wave 1 step 2 (F4-B Core Workspaces) planning sub-session in fresh chat.
```

### Commit 2 (C2) — ADR 0005 annotation

См. § 3A.4 — точная commit message там.

### Commit 3 (C3) — Superseded markers + § 7.1 + SERVER_ARCHITECTURE

См. § 3B+C+D — точная commit message там.

### PR

**Title:** `docs(milestone): Wave 1 Step 1 DONE — Bot UX hardening + ADR 0005 annotation + roadmap markers (Session K)`

**Body template:**

```markdown
## Summary

Closes Wave 1 step 1 (Bot UX hardening) per PRODUCT_STRATEGY_AUDIENCE_DRIVEN § 5.1.

3 atomic commits:
1. **C1** — DONE marker `REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` + cross-link in ROADMAP_KARPATHY + CHANGELOG entry.
2. **C2** — ADR 0005 implementation status annotation (Variant A finalized + D-3 per-call resolution after Session J).
3. **C3** — superseded markers (FUTURE_FEATURES L96, SESSION48 / Session29) + PRODUCT_STRATEGY § 7.1 F-Prereq-1 update + SERVER_ARCHITECTURE scrape targets.

## Refs

- Self-review актуальной документации проекта (chat 2026-05-07): C-4, C-5, C-6, M-5, M-9, M-13.
- Sessions H/I/J: PRs #58, #59, #61.
- Companion PRs (separate scope): runbook nomenclature hotfix (если уже merged), documentation hygiene sprint (планируется).

## Closes

Closes #46
Closes #47
Closes #48
Closes #51
Closes #52

## Test plan

- [ ] All 3 self-review checklists в § 4.1 промпта Session K — все GREEN.
- [ ] `git diff --stat origin/main..HEAD` — только docs (no code).
- [ ] CI 5/5 GREEN.
- [ ] Post-merge: `gh issue view 46/47/48/51/52` все CLOSED.
```

> **Замечание:** PR будет содержать только docs changes. Lint Documentation check
> должен пройти; Test Python 3.12 будет фактически no-op (нет code changes).

---

## 9. Appendix — Key references

| Документ | Зачем |
|----------|-------|
| [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) § 4 | Canonical DONE marker template (C1 decision) |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 5.1 | Wave 1 sequence — supersedes старую FUTURE_FEATURES.md L96 |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 8 | Q1–Q8 preliminary recs для F4-B planning sub-session |
| [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) § 4 Q2/Q4 | Refined 2026-05-03 decisions — locked semantics |
| [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) | Observations log; O-2 entry для § 3.1 marker'а |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Cross-link target (§ 4 readiness checklist) |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist для F4-B planning (не для Session K) |
| Sessions H/I/J PRs: [#58](https://github.com/AlexEfimov/TG_parser/pull/58), [#59](https://github.com/AlexEfimov/TG_parser/pull/59), [#61](https://github.com/AlexEfimov/TG_parser/pull/61) | Source of truth для marker'а § 1 «Что закрыто» |
| [`HANDOVER_SESSION_H_TO_I_2026-05-03.md`](HANDOVER_SESSION_H_TO_I_2026-05-03.md) | Evidence для Session H deploy verdict + watch baseline |
| `docker-compose.yml:36, 163` | Container nomenclature reference (`tg_parser` API vs `tg_parser_bot` bot) |

---

## Appendix B — История правок

| Дата | Изменение |
|------|-----------|
| 2026-05-07 ~22:55 UTC+4 | Первая версия. Создана после deploy Session J. **Replaces** ошибочный draft `START_PROMPT_SESSION_K_F8A_WAVE1_DONE_2026-05-08.md`, который неверно интерпретировал «Wave 1 step 1 DONE» как «вся Wave 1 done» и предлагал F8-A LLM cache как next step (F8-A — backlog, не Wave 1). |
| 2026-05-07 ~23:15 UTC+4 | Self-review pass #2. **Critical fix:** pre-flight § 0 использовал `docker logs ... tg_parser` (API контейнер), но bot-специфичные метрики (`confirm_flow_mismatch`, `gemini_*`) живут в `tg_parser_bot`. Sessions H/I/J prompts имели ту же ошибку — все их gate-check'и были ложно-GREEN-by-luck. Исправлено nomenclature; pre-recorded baseline 22h после deploy GREEN. Добавлен lesson learned #4. **Minor:** O-1 (atomic move_workspace_source defer, 2026-05-03) явно перечислена в § 3.1 наравне с O-2; HANDOVER_SESSION_H_TO_I добавлен в Appendix; R-2 уточнён конкретными timestamps. |
| 2026-05-07 ~23:35 UTC+4 | **Extended scope per self-review актуальной документации проекта (chat 2026-05-07).** Сессия теперь делает 3 atomic commits в одном PR: C1 — DONE marker (как было); C2 (NEW) — ADR 0005 annotation (Variant A finalized + D-3 hot-reload resolves audit C-5 / C-6); C3 (NEW) — superseded markers (FUTURE_FEATURES L96, SESSION48 / Session29) + PRODUCT_STRATEGY § 7.1 F-Prereq-1 update + SERVER_ARCHITECTURE scrape targets (resolves M-9, M-5, M-13). PR description содержит `Closes #46, #47, #48, #51, #52` (resolves C-4). Размер ожидаемого diff: +60-100 lines docs total, no code. **НЕ включено в Session K (отдельные scope'ы):** runbook nomenclature hotfix (`START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md`); documentation hygiene sprint (M-1, M-2, M-3, M-7, M-8, M-15, M-16) — отдельная сессия после Session K, до F4-B planning. |
