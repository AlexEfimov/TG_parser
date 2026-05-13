# Wave 1 Step 1 — DONE marker

**Дата:** 2026-05-08
**Закрывает:** Wave 1 step 1 (Bot UX hardening) per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)
**Packaging:** decision A3 (hybrid — bug-fix отдельным PR, ADR adoption + runbook одним PR с 2 atomic commits) per
[`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 1.1](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md)

---

## 1. Что закрыто

| Session | PR | Squash SHA | Deployed | 24h watch verdict |
|---|---|---|---|---|
| H — BUG-011 read-context preservation | [#58](https://github.com/AlexEfimov/TG_parser/pull/58) | `993451d` | 2026-05-03 ~13:35 UTC (~17:35 UTC+4) | GREEN |
| I — BUG-010 username alias resolution | [#59](https://github.com/AlexEfimov/TG_parser/pull/59) | `69243e6` | 2026-05-06 ~15:40 UTC (~19:40 UTC+4) | GREEN |
| J — ADR 0005 bot-scope LLM config + BOT_LLM_FALLBACK runbook | [#61](https://github.com/AlexEfimov/TG_parser/pull/61) | `17b12b3` | 2026-05-07 ~18:46 UTC (~22:46 UTC+4) | GREEN |

> **Deploy timestamps** — derived из PR `mergedAt` + Session R-2 lag (~3-5 min между squash-merge
> и `tg_bot` пересборкой через CD). Точные production timestamps:
> Session H — подтверждены в [`HANDOVER_SESSION_H_TO_I_2026-05-03.md`](HANDOVER_SESSION_H_TO_I_2026-05-03.md)
> § «Session H — статус ЗАКРЫТА» (`tg_bot` healthy + `prompts/bot.yaml` v1.6.0 loaded ~17:35 UTC+4);
> Session I — подтверждены в Session J pre-flight § 5.4 (Telegram smoke на свежем deploy);
> Session J — `2026-05-07 ~18:46 UTC` (точное время, см. Session J conversation timeline).

> **Watch verdict 24h окна:**
> Session H + I — отсутствие hot-fix коммитов в течение 24h после deploy + clean baseline
> (`confirm_flow_mismatch` / `gemini_*` = 0) на момент старта следующей session;
> Session J — pre-flight § 0 этой сессии (2026-05-08 ~19:10 UTC = ~23:10 UTC+4):
> Prometheus `up{service="bot"}` = `"1"`, `confirm_flow_mismatch` (24h, `tg_parser_bot`) = `0`,
> `gemini_empty|no_candidates|blocked|api_error` (24h, `tg_parser_bot`) = `0`.

## 2. Monitoring-only / unresolved

| Item | Reason | Re-evaluate trigger |
|---|---|---|
| BUG-012 | Cosmetic — pagination phrasing на hint fields, mitigated в `prompts/bot.yaml` v1.5.0 (commit `a7dbaac`) | New sighting in production logs |

## 3. Accumulated observations

### 3.1 Parity tracker entries

См. [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md):

- **O-1** (добавлена 2026-05-03 в commit `9d4f7e8` — окно Session H) — Atomic
  `move_workspace_source` defer до signal'а. Surface gap (атомарный перенос канала между
  workspaces одного user'а) для F4-B Core MVP; consciously deferred per Q4 refined decision —
  preemptive flag без pain-driven evidence (confidence very low). Action для F4-B planning
  sub-session: verify «evidence accumulated?» — если нет, держать в backlog'е до Wave 1 step 3
  / Wave 2.
- **O-2** (добавлена 2026-05-06 в commit `cab6efd` — окно Session I) — BUG-007
  fuzzy-suggestion gap на status-check pathway. Smoke-quality observation из Session I
  post-deploy Telegram smoke § 5.4 (typo `AgeMenagment` → bot отвечает «не найден» без
  suggestion-fallback). Intra-surface consistency gap, **не** cross-surface parity. **Action
  не выполнен в Session J** — audit pass `rg -n "не найден|not found" tg_parser/bot/tools.py
  | rg -v _build_no_results_suggestion` отложен. Track как potential BUG-013 candidate для
  любого следующего bot-touch sprint'а (не блокирует Wave 1 step 1 closure).

### 3.2 New FUTURE_FEATURES items

**Нет нового FUTURE_FEATURES** — Wave 1 step 1 был bug-fix + ADR adoption, не feature work.

**Но:** self-review актуальной документации 2026-05-07 нашёл **~30 расхождений** между
документами и кодом (отдельный self-review отчёт в conversation). Из них:

- В этом milestone (Session K extended scope) фиксятся **C-4 / C-5 / C-6 / M-5 / M-9 / M-13**
  (см. § 8 PR description Session K — closures в коммитах C2 + C3).
- Остальные (M-1, M-2, M-3, M-7, M-8, M-15, M-16) — отдельная documentation hygiene сессия
  (~0.5 сессии, до F4-B planning).
- Critical runbook fixes (C-1, C-2 — wrong container/service names в
  `BOT_LLM_FALLBACK.md` + `F5C_DEPLOY_AND_WATCH.md`) — закрыты отдельным hotfix PR
  [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`docs/hotfix-runbook-nomenclature-2026-05-08`,
  `Closes #62`); merged 2026-05-08.
- Latent code mini-fix (M-11, M-12, M-17 — bot metrics resolved model + resolve_full bot
  guard + TopicCardVersion docstring) — opportunistic в любой следующий bot-touch sprint.

### 3.3 Signals collected (для Decision Point — § 5 PLANNING_WAVE1_EXECUTION_PLAN)

**Нет внешних signals** на момент закрытия step 1 — Wave 1 step 1 целиком inward-facing
(Bot UX hardening для owner-as-A1 user). Внешние signals начнут собираться после step 2
(F4-B Core открывает workspace-сценарии для curators) и step 4 (shareable digest).

## 4. Pre-next-step readiness checklist

- [x] All 3 deploys 24h watch GREEN (см. § 1 таблицу + pre-flight § 0 Session K промпта)
- [x] 0 регрессий по существующим тестам (final baseline 2047 passed после Session J — см.
      [`CHANGELOG.md`](../../CHANGELOG.md) § Session J → Verification)
- [x] CHANGELOG.md обновлён под `Unreleased` для Sessions H/I/J — done (см. § Session H/I/J
      blocks в CHANGELOG.md)
- [x] Cross-link на этот marker в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
      (добавлен этим же commit'ом)

## 5. Lessons learned

1. **Hybrid packaging A3 валиден.** Sessions H/I (single PR each) + Session J (single PR
   с 2 atomic commits) дали 3 атомарных rollback'а с независимыми 24h watch'ами. 0 регрессий
   за окно. Применить тот же паттерн для F4-B Core sprint (5 atomic commits в одном PR per
   [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 2.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md)).

2. **REQUIRED_PROMPT_STAGES sync с LLM_SCOPES — implicit contract.** Session J выявил что
   добавление scope в `LLM_SCOPES` без обновления `REQUIRED_PROMPT_STAGES` ломает
   regression-тест (`tests/test_prompt_loader.py::test_required_stages_match_llm_scopes`).
   Будущие изменения LLM scope'ов должны обновлять оба места одним коммитом.

3. **MagicMock fallback для static settings.** `getattr(self._static, "bot_gemini_model", None)`
   потребовался чтобы `LLMConfigManager.resolve("bot")` не падал на `unittest.mock.MagicMock`
   без `bot_gemini_model` атрибута — pattern полезен для других scope'ов с unique static
   settings.

4. **Pre-flight container nomenclature regression.** Pre-flight checks Sessions H/I/J
   использовали `docker logs ... tg_parser` для grep'а bot-specific метрик
   (`confirm_flow_mismatch`, `gemini_*`), но это **API контейнер**
   (`docker-compose.yml:36`) — bot живёт в `tg_parser_bot` (`docker-compose.yml:163`).
   Session J gate-check 2026-05-07 был ложно-GREEN-by-luck (оба контейнера чистые).
   `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 1.2 уже использует правильное имя
   `tg_parser_bot`; Sessions H/I/J prompts отклонились без обоснования. **Action для F4-B
   и далее:** все pre-flight checks для bot-метрик должны указывать `tg_parser_bot` (или
   явно проверять оба контейнера, если cross-cutting). **Action taken (2026-05-08):** runbook
   nomenclature corrected в production runbook'ах `BOT_LLM_FALLBACK.md` и
   `F5C_DEPLOY_AND_WATCH.md` через PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63)
   (`Closes #62`); BOT pre-flight + post-procedure теперь grep'ят `tg_parser_bot`, F5C deploy
   команды используют actual compose service names (`tg_parser`, `mcp`, `tg_bot` с
   `--profile bot`). Останется закрепить паттерн в новых session prompts (Session K
   промпт уже использует исправленное имя).

## 6. Следующий шаг

**Wave 1 step 2 — F4-B Core Workspaces.**

Planning sub-session (~0.3 сессии) — **в fresh chat**, не продолжение Session K — read:

- [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) § 4 Q1–Q8
- [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 8](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)

Apply preliminary recommendations (Q1=B, Q3=skip-bot, Q5=A, Q6=A, Q7=C, Q8=C) + locked
Q2/Q4 refinements (2026-05-03). Produce `START_PROMPT_SPRINT_F4B_CORE_2026-05-XX.md` (~700
строк по образцу [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md)).

---

## Appendix — Cross-references

| Документ | Зачем |
|----------|-------|
| [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) § 4 | Canonical DONE marker template (decision C1) |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 5.1 | Wave 1 sequence (Bot UX → F4-B → Surface Parity → Shareable Digest) |
| [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § 3 | O-1 + O-2 observations (источник для § 3.1) |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Cross-link target (§ 4 readiness checklist) |
| [`HANDOVER_SESSION_H_TO_I_2026-05-03.md`](HANDOVER_SESSION_H_TO_I_2026-05-03.md) | Evidence для Session H deploy verdict |
| [`START_PROMPT_SESSION_K_WAVE1_STEP1_DONE_2026-05-08.md`](START_PROMPT_SESSION_K_WAVE1_STEP1_DONE_2026-05-08.md) | Session K планирующий промпт (extended scope) |
| Sessions H/I/J PRs: [#58](https://github.com/AlexEfimov/TG_parser/pull/58), [#59](https://github.com/AlexEfimov/TG_parser/pull/59), [#61](https://github.com/AlexEfimov/TG_parser/pull/61) | Source of truth для § 1 «Что закрыто» |
| [`docs/adr/0005-bot-llm-provider-flexibility.md`](../adr/0005-bot-llm-provider-flexibility.md) | ADR — input для Session J + annotated в Session K C2 |
