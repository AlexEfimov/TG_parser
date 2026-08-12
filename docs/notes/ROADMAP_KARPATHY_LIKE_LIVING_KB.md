# Roadmap: Karpathy-like подход и Living KB

> **Living-KB contract: CLOSED 2026-04-26**
> (D.1 hardening + F11 watchlist + F5-C evolving summaries — Wave A/B/C ниже)
> См. [`## 2026-04-26 — Contract closed`](#2026-04-26--contract-closed-) и `CHANGELOG.md`.
>
> **Нормативное определение принципов:** [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md)
> (формализованы 2026-05-02 — 7 принципов как ADR-якорь, защищённый от
> drift'а этого живого документа).

**Статус:** активный ориентир для развития продукта — **forward source-of-truth для направления** (совместно с [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md)). [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) — **DEPRECATED** (исторический календарь волн/релизов), этот документ его **не дополняет, а заменяет** как ориентир направления.

**Дата:** 25 апреля 2026 (последняя крупная правка: 2026-08-11 — Wave 3 planning readiness: tech-debt gate отсутствует; δ/ε/ζ + F5-C #15 core closed; next decision-input [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md) + [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md); SoT = § «Post-Wave-2 треки» / Next).

---

## 2026-04-26 — Contract closed ✅

Living-KB-контракт (волны A + B + C) закрыт коммитами этого спринтового
цикла. Ссылки на CHANGELOG-секции и detailed deliverables — в каждом
пункте.

| Wave | Sprint | Что закрыто | CHANGELOG |
|---|---|---|---|
| A | D.1 | Topicization hardening — truthful `failed_stage`, per-batch checkpointing, error_message persistence (4096-char contract aligned in TD-01, post-Living-KB sprint Phase 1). | § Sprint D.1 — Topicization Hardening |
| B | F11 | Topic Watchlist MVP — hybrid keyword+embedding scoring, idempotent matches, instant push via aiogram, MCP/Bot/CLI surface, scheduler hook with graceful degradation. | § Sprint F11 — Topic Watchlist |
| C | F5-C | Evolving Topic Summaries MVP — counter-driven re-summarize, append-only `topic_card_versions` audit trail, advisory-lock + UNIQUE second line of defence, MCP/CLI surface. | § Sprint F5-C — Evolving Topic Summaries |

24h F5-C deploy-watch window: opens at `2026-04-26T11:07:13Z`, closes
≈ `2026-04-27T11:07Z`. Verdict reporting per [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
§ Post-watch report.

---

## 2026-05-08 — Wave 1 step 1 (Bot UX hardening) DONE ✅

Audience-driven Wave 1 step 1 (Bot UX → F4-B Core → Surface Parity →
Shareable Digest per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md))
закрыт. Sessions H (BUG-011 read-context, PR [#58](https://github.com/AlexEfimov/TG_parser/pull/58)) +
I (BUG-010 username alias, PR [#59](https://github.com/AlexEfimov/TG_parser/pull/59)) +
J (ADR 0005 mini-refactor + BOT_LLM_FALLBACK runbook, PR [#61](https://github.com/AlexEfimov/TG_parser/pull/61))
deployed, 24h watch GREEN. Step marker:
[`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md).

Следующий шаг — Wave 1 step 2 (F4-B Core Workspaces), стартует с planning sub-session
в fresh chat per
[`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 2.1](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md).

---

## 2026-05-13 — Wave 1 step 2 (F4-B Core Workspaces) DONE ✅

Audience-driven Wave 1 step 2 закрыт per
[`START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`](START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md):
Single PR + 5 atomic commits, ~1450 LOC + ~75 новых тестов. Pre-flight
gate-1 GREEN (Prometheus `up{service="bot"}` = `1`, `confirm_flow_mismatch` 72h = `0`,
`gemini_*` errors 72h = `0` на `tg_parser_bot`).

| # | Commit | Что добавлено |
|---|---|---|
| 1/5 | `feat(F4-B): schema + migration + Pydantic + JSON contract` | `workspaces` + `workspace_sources` (alembic `e9f0a1b2c3d5`), Pydantic `Workspace`/`WorkspaceSource`, `docs/contracts/workspace.schema.json`, 10 schema tests. |
| 2/5 | `feat(F4-B): service + repo + ownership` | `WorkspaceRepo` ABC + `SAWorkspaceRepo`, `WorkspaceNotFound`/`assert_workspace_access`, `WorkspaceService` с `effective_channel_ids` resolver и channel_id→source_id translation, 32 теста (repo + ownership + service). |
| 3/5 | `feat(F4-B): MCP + CLI surface` | 8 MCP tools (`create/list/rename/delete_workspace`, `add/remove_workspace_source`, `list_workspace_sources`, `list_all_workspaces`) + `tg-parser workspace` Typer-приложение с 8 подкомандами, 20 surface-тестов. |
| 4/5 | `feat(F4-B): scoping integration in read-tools` | `workspace_id: str \| None = None` на 8 read tools + CLI `--workspace-id` для `search`/`ask`; `_resolve_workspace_scope` helper; Q4 R3 invariant для get-details, 14 scoping тестов. |
| 5/5 | `test(F4-B): regression guards + observability + docs` | `tests/test_f4b_backward_compat.py` (12 — F4-A bit-for-bit parity), `tests/test_f4b_workspace_isolation.py` (6 — cross-user 404-like), `tests/test_f4b_metrics.py` (8 — Prometheus exporter shape), `tests/test_f4b_golden_path.py` (1 — end-to-end); `tg_workspace_*` метрики в `api/metrics.py`; structlog + metric инструментация в `WorkspaceService`. |

**Hard invariants (locked):** `workspace_id=None` → bit-for-bit F4-A;
unknown/foreign → 404-like empty (`WorkspaceNotFound`); empty workspace →
`effective_channel_ids=[]` (не silent "all channels"); service-слойные
signatures не меняются; `get_topic_details`/`get_document` возвращают full
bundle (Q4 R3 — workspace narrows list/search, не access control).

**Deferred (Wave 1 step 3+ / Wave 2):** O-1 atomic `move_workspace_source`
(non-atomic remove+add в MVP — см. `PARITY_DECISION_TRACKING.md` § 3);
Bot integration (Q3); F11 watchlist workspace_id (Q7); F6 digest
workspace_id (Q8); sharing / audience A2/A3.

Следующий шаг — Wave 1 step 3 (Surface Parity) per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).

---

## 2026-05-14 — Wave 1 step 2 (F4-B Core) watch-close DONE ✅

24h post-deploy watch для F4-B Core закрыто verdict **GREEN** (окно
`2026-05-13T19:30:28Z` → `2026-05-14T19:30:28Z`). Все три
`up{service=...}` gauges hold value=1 across 97 samples; counter
time series для `confirm_flow_mismatch_total` и `gemini_*_total`
отсутствуют в Prometheus (canonical zero events с момента deploy);
`tg_workspace_resolver_seconds` p99 = **4.96 ms** (healthy baseline
для будущих watch'ей); 0 workspace-related errors через api / bot /
mcp containers; F4-A bit-for-bit invariant holds. Step marker:
[`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md).

Watch window дополнительно surface'ил **два pre-existing scheduler
bug'а** ([BUG-013](BUG_LOG.md#bug-013--scheduler-shares-one-asyncsession-pair-across-asynciogather-tasks--illegalstatechangeerror--cascading-interfaceerror-on-every-incremental_pipeline-tick)
+ [BUG-014](BUG_LOG.md#bug-014--scheduler-_process_source-compares-offset-naive-sourcerate_limit_until-against-datetimenowutc--typeerror-aborts-the-tick-before-any-pipeline-work-runs))
— оба structurally pre-existing, **NOT F4-B regression**: `git diff
7953302^ 7953302 -- tg_parser/services/scheduler_service.py
tg_parser/services/db_context.py` показывает 0 lines changed в
scheduler_service.py + 12 additive в db_context.py (workspace_repo()
only). Observability noise only: 100% scheduler `incremental_pipeline`
ticks marked `status="error"` while `processed_documents` + embeddings
continue to advance correctly. Fix-sprint планируется в next session
per [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md)
§ 6 step #2 (~half-day: per-task session pair refactor + tz-aware
datetime invariant + 3-4 testcontainers integration tests).

Следующий шаг — **BUG-013/014 fix-sprint** (closes observability
baseline перед Wave 1 step 3), затем **Wave 1 step 3 planning
sub-session** (Surface Parity P-1 Watchlist API vs P-2 Digest API).

---

## 2026-05-15 — Joint BUG-013/014/024 fix-sprint DONE ✅ + BUG-016 infra unblock

Closes scheduler observability baseline ahead of Wave 1 step 3.

| Bug | PR | Squash SHA | Verdict |
|---|---|---|---|
| BUG-013 (shared `AsyncSession` across `asyncio.gather` → `IllegalStateChangeError` + cascading `InterfaceError`) | [PR #79](https://github.com/AlexEfimov/TG_parser/pull/79) | `5465918` | ✅ 0 events / 28h post-deploy scan |
| BUG-014 (scheduler-side naive-vs-aware comparison on `rate_limit_until` at `scheduler_service.py:89`) | [PR #79](https://github.com/AlexEfimov/TG_parser/pull/79) | `5465918` | ✅ 0 scheduler-site `TypeError` events |
| BUG-024 (`last_attempt_at` non-null invariant; synchronous pre-await write via new `mark_attempt_started`) | [PR #79](https://github.com/AlexEfimov/TG_parser/pull/79) | `5465918` | ✅ 9/9 active sources hold invariant |
| BUG-016 (`tg_parser_mcp` / `tg_bot` env_file + sessions volume drift) | [PR #81](https://github.com/AlexEfimov/TG_parser/pull/81) | `5907179` | ✅ infra unblock; closed issue #80 |

Single squash-merged PR per fix, 6/6 acceptance signals GREEN over the
24h post-deploy watch (2026-05-15T15:01Z → 2026-05-16T15:01Z; 28h scan
span with 3.7h post-close buffer). DONE marker:
[`REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md).

Per-task `AsyncSession` ownership + tz-aware coerce helper + synchronous
attempt-tracking restore the «scheduler tick is observable» invariant
that BUG-013/014 silently broke since the F4-B Core watch window
discovered them. BUG-016 env-drift fix was bundled into the same watch
window via PR #81 — same root cause cluster (cross-container
nomenclature drift compounding architectural cross-container dispatch
opacity).

**Known partial discovered during the watch:** BUG-014B — orchestrator-
side naive-vs-aware comparison at `tg_parser/ingestion/orchestrator.py:110`
became newly reachable after PR #79 cleared the scheduler-side abort.
Tracked as separate sprint (see ## 2026-05-18 below). Verification
methodology improvement noted: live MCP probe surfaced what 2050-test
pre-merge suite + static analysis could not. Lesson captured in DONE
marker § 7.

---

## 2026-05-18 — BUG-014B storage-boundary fix DONE ✅

Closes the second-site failure-loop surfaced by the 2026-05-15T20:55Z
AMBER MCP probe of PR #79.

| Bug | PR | Squash SHA | Verdict |
|---|---|---|---|
| BUG-014B (orchestrator-side naive-vs-aware comparison; storage-boundary coerce in `_row_to_source` — Option B per analysis) | [PR #84](https://github.com/AlexEfimov/TG_parser/pull/84) | `39da8cc` | ✅ `kdl_ru` + `profendocrinologist` exit fail-loop |

Option B promoted `coerce_aware_utc` from `scheduler_service` to
`tg_parser/domain/json_utils.py` (shared with `parse_iso_datetime`);
`SAIngestionStateRepo._row_to_source` now coerces all 8 naive datetime
fields to tz-aware UTC on read. Scheduler-side coercion retained as
belt-and-suspenders. 24h watch GREEN per
[`REVIEW_2026-05-20_BUG014B_DONE.md`](REVIEW_2026-05-20_BUG014B_DONE.md).

This closes the scheduler observability triad
(BUG-013 + BUG-014 + BUG-014B + BUG-024) and confirms the pattern «fix
one site, expose its sibling» that landed in this cluster.

---

## 2026-05-20 — Doc hygiene + M-15 BUG_LOG batch DONE ✅

Tail-end docs hygiene sprint covering ~10 doc-vs-code drift findings
from the 2026-05-07 self-review (M-1 / M-2 / M-3 / M-7 / M-8 / M-15 /
M-16 / M-14 / C-3 + testing-strategy refresh).

| Sprint | PR | Squash SHA | Scope |
|---|---|---|---|
| Doc hygiene (counts / versions / ADR-status / MVP-banners) | [PR #85](https://github.com/AlexEfimov/TG_parser/pull/85) | `9068cbf` | Tools counts (43 MCP / 32 bot) + version `4.3.0` sync; MCP specs scope-narrow banner; ADR 0001/0003/0004 implementation status; MVP banners; ROADMAP_V3 Wave 1 disambiguation |
| M-15 BUG_LOG hygiene (Active → Resolved batch) | (bundled) `db4b5d8` | — | BUG-013/014/024/014B moved to `§ Resolved bugs` with housekeeping note; BUG-014B watch GREEN closure row |

Pure docs change, no code touched. Counts now reflect HEAD reality:
43 MCP tools (F4-B added 8 workspace tools), 32 bot tools (F4-B
deferred per Q3), `pyproject.toml` v4.3.0.

---

## 2026-05-21 — S2 quick-wins (BUG-018 / BUG-017 / BUG-023) DONE ✅

Three independent low/medium-effort observability + automation-safety
bugs filed against the 2026-05-15 Claude MCP testing session bundled
into one PR with atomic commits — slotted in S2 between Wave 1 step 3
planning (S1) and execution (S3) per sequencing route
S1 → S2 → S3 → S4 → S5.

| Bug | PR | Squash SHA | Scope |
|---|---|---|---|
| BUG-018 (high — automation safety) | [PR #87](https://github.com/AlexEfimov/TG_parser/pull/87) | `2e9213c` | `tg-parser topicize` tracks `total_batches` / `failed_batches` / `last_batch_error`; CLI exits with code **2** when `failed_batches / total_batches > 0.5`; first error class to stderr with billing / quota hint; misleading «недостаточно данных» suppressed |
| BUG-017 (low — diagnostic clarity) | (bundled) | `2e9213c` | Scheduler-path log line `[3/4] Topicization skipped (--skip-topicize)` → `... skipped (scheduler does not auto-topicize by design; run 'tg-parser topicize <channel>' manually)` |
| BUG-023 (low — observability) | (bundled) | `2e9213c` | `_validate_quality` returns `(valid, reason)` with six discrete criteria; structured `topic_failed_quality_criteria` event with reason / title / items; aggregate `rejection_breakdown: dict[str, int]` surfaced via service stats + `IncrementalTopicizeResult` + CLI summary |

Tests: **31 new pure-mock unit tests** (12 / 1 / 18 across the three
files; 13 added in pre-PR self-review covering 50 % boundary, stderr
hint content, single-batch fail exit code, deterministic first-error
capture, both early-rejection paths, title truncation, service-layer
stats round-trip, CLI render format). Docs: `docs/USER_GUIDE.md`
topicize «Exit codes» table + `docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md`
§ 7 billing-pause recovery matrix. Full suite:
**2147 passed, 258 skipped, 0 failed** (was 2134/258/0; ∆ = 13 net new
tests landing on top of pre-existing topicize coverage).

Backfill commit `4d567ce` updates BUG_LOG closure rows with PR #87 SHA.

Karpathy-like compliance: principle 4 (idempotency + journals — exit
code now reflects per-invocation systemic-fail state without resetting
between runs); principle 6 (observability — `rejection_breakdown`
+ structured events make «why coverage is below expectation» visible
from logs alone); principle 7 (graceful degradation — partial-fail ≤
50 % stays exit 0 with warning summary; systemic ≥ 50 % blocks
automation downstream).

---

## 2026-05-21 — Wave 1 step 3 (Surface Parity) DONE ✅

Audience-driven Wave 1 step 3 закрыт. PR [#89](https://github.com/AlexEfimov/TG_parser/pull/89) → `a30abd5`; step 3.1 dispatch PR [#90](https://github.com/AlexEfimov/TG_parser/pull/90); follow-ups PR [#91](https://github.com/AlexEfimov/TG_parser/pull/91). 24h watch **GREEN** (early close T+22h09m documented). Step marker: [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md).

**Landed:** P-1 Watchlist HTTP API, P-2 Digest HTTP API, ENH-9 `workspace_id`, BUG-022 idempotency, Idempotency-Key middleware. Step 3.1: ADR 0007 MCP dispatch (BUG-015 closed).

**Deferred from step 3:** BUG-025/026/027 bot UX → step 4.1 → ultimately Wave 2. **✅ RESOLVED `13d2200`** (deployed prod 2026-06-12, bot prompt v1.7.7) — hardened watchlist-unsubscribe UX; см. BUG_LOG BUG-025/026/027 closure rows. (see aggregate closure § 5).

---

## 2026-05-25 — Wave 1 step 4 (Shareable Digest / ADR 0008) DONE ✅ (PASS-WITH-CAVEATS)

PR [#93](https://github.com/AlexEfimov/TG_parser/pull/93) → `926a165`; alembic `a8b7c6d5e4f3`. 24h VPS watch closed **PASS-WITH-CAVEATS** — C-1/C-2 materialized; **C-3 (`failed` counter) untested**. Step marker: [`REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md).

Post-step-4 tail (BUG-031…053, PR [#171](https://github.com/AlexEfimov/TG_parser/pull/171) URL preservation) resolved before Wave 1 aggregate closure.

---

## 2026-06-03 — Wave 1 aggregate closure ✅ (step 5 ops **PASS — DONE 2026-06-06**)

Audience-driven Wave 1 (steps 1–4) declared done 2026-06-03; **formally closed 2026-06-06** (PR [#175](https://github.com/AlexEfimov/TG_parser/pull/175) / [#197](https://github.com/AlexEfimov/TG_parser/pull/197) / [#198](https://github.com/AlexEfimov/TG_parser/pull/198); tag `v4.4.0` on `6ec3574`). Aggregate marker: [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md).

**Step 5 ops (Grafana / observability):** **PASS — DONE 2026-06-06** — prod aligned with `main` Wave 1 closure SHA (post-PR #197 prod = `b04353b`); BUG-036/038 provisioning (PR [#140](https://github.com/AlexEfimov/TG_parser/pull/140)) live; Grafana healthy, `wave1_step4.yaml` loads cleanly (2026-06-06 recreate verified). `GRAFANA_WEBHOOK_URL` (2026-06-03) + `GRAFANA_WEBHOOK_TOKEN` (2026-06-06) both set on prod; **E2E alert path verified end-to-end 2026-06-06** (synthetic curl → issue [#195](https://github.com/AlexEfimov/TG_parser/issues/195), closed as smoke). **Post-closure cleanup:** § A **Done** (single-shot automations `2bd25769` / `f93e557a` confirmed inactive), § C **Done** (Grafana admin password rotated on VPS); § B **deferred** (7 schema-probe deletes — Cursor UI, no MCP delete tool), § D **deferred** (Telegram test artifacts kept per runbook default).

**Deferred to Wave 2:** BUG-025, BUG-026, BUG-027 (step 4.1 bot UX bundle). — **✅ RESOLVED `13d2200`** (deployed prod 2026-06-12, bot prompt v1.7.7); эта строка «deferred» устарела, оставлена для контекста. См. BUG_LOG BUG-025/026/027.

**Next:** Wave 2 planning / Decision Point lightweight signal cadence per [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 5](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md). — *(superseded: Wave 2 спланирован и **закрыт** `b294b05` — см. секцию «2026-06-14 — Next contract: Wave 2 … ✅ CLOSED» ниже.)*

---

## 1. Что мы называем «karpathy-like» в этом проекте

Речь не про конкретного автора, а про **устойчивый стиль системы знаний**, согласованный с уже принятыми решениями (TopicCard, TopicBundle, hybrid RAG, incremental topicization, `TopicLink`):

| Принцип | Смысл для TG_parser |
|--------|---------------------|
| **Персистентные сущности** | Интересы, темы, матчи, дайджесты — явные таблицы и доменные модели, не «всё в JSON в одной колонке». |
| **Provenance / evidence** | К ответу или алерту привязаны `source_ref`, scores, версии — можно объяснить «почему сработало». |
| **Дешёвые циклы retrieval** | Keyword + embedding / hybrid там, где поток большой; LLM — на сжатых кандидатах или для редких операций (summarize, Q&A), не на каждое сырое сообщение без фильтра. |
| **Идемпотентность и журналы** | Повторный pipeline не плодит дубликаты «фактов» и уведомлений; история матчей и версий тем сохраняется осмысленно. |
| **Инкрементальный living loop** | Новые документы → processing → topicization → (алерты / дайджесты / будущие пересуммаризации тем) без ручного «пересобери всё». |
| **Наблюдаемость → тюнинг** | Метрики по bucket'ам score, дедуп, шум watchlist — правим пороги и доки по данным, а не вслепую добавляем LLM-слой. |
| **Деградация без падения ядра** | Сбой уведомлений, частичный topicization, отсутствие chat — не валят ingestion для остальных пользователей. |

Этот документ **склеивает** продуктовый roadmap с этими принципами, чтобы следующие спринты не расходились с архитектурой «живой базы знаний».

---

## 2. Связь с существующими документами

| Документ | Роль |
|----------|------|
| [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | **DEPRECATED** (исторический). Календарь волн, D.*, F-фичи, приоритеты релизов. Forward-ориентир — этот документ + `FUTURE_FEATURES.md`. |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | Дизайн F11, F5-C, F6 и др.; зафиксированный порядок **D.1 → F11 → F5-C**. |
| [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) | Полный спек F11 с karpathy-like деталями в чеклисте и рисках. |
| [`START_PROMPT_NEXT_SESSION_F11.md`](START_PROMPT_NEXT_SESSION_F11.md) | Старт сессии после D.1: дожим F11 + ссылки на этот roadmap. |
| [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) | PR-чеклист F11 с пометками **karpathy-like** по пунктам. |

---

## 3. Волны внедрения (состояние и очередь)

Условные **волны** ниже отражают **логический** порядок karpathy-like усилений; нумерация может совпадать с таблицами в Roadmap v3, но этот файл — про **тип изменений**, а не про замену таблицы приоритетов.

### Волна 0 — Фундамент (выполнено в продукте)

- Ingestion → processing → topicization → embeddings → hybrid RAG, MCP, бот, scheduled digests (F6).
- Multi-tenancy (F4), cross-channel темы и links.
- **Karpathy-like итог:** уже есть «страницы тем» (`TopicCard`), поиск с источниками, инкрементальная обработка.

### Волна A — Надёжность topicization (перед расширением «личного слоя»)

- **Sprint D.1** — topicization hardening (например учёт `failed_stage`, операционная диагностика).
- **Karpathy-like итог:** living loop не «молчит» при частичных сбоях; данные для watchlist и тем согласованы с реальным состоянием пайплайна.

### Волна B — Персональный слой внимания (✅ реализовано 2026-04-26 — F11 watchlist)

- **F11 — Topic Watchlist:** персистентный интерес, `watch_matches` с scores, hybrid matching без LLM на документ, hook после topicization, instant notify, MCP/bot/CLI.
- **Karpathy-like итог:** user-defined «страница интереса» + evidence log + digest-style уведомления + метрики (желательно) для калибровки threshold.

### Волна C — Память темы (✅ реализовано 2026-04-26; **P2 freshness landed Wave 2**)

> **Update 2026-07-20 (doc-drift cross-link):** формулировка «MVP only» ниже — **историческая**. F5-C **P2 freshness** уже landed в **Wave 2 T7** (`b294b05`, 2026-06-14): issue #15 item #4 (time-based re-summarize trigger, env `RESUMMARIZE_MAX_AGE_DAYS`) + item #10 (per-channel re-summarize metric `tg_resummarize_total{channel_id}`). Остальные 8 пунктов #15 (TTL, diff-API, F6 topic-digest, Bot-tools и т.д.) остаются в #15-backlog.

- **F5-C — Evolving Topic Summaries:** пересуммаризация / re-embed `TopicCard` при накоплении N новых supporting items; append-only версии в `topic_card_versions`.
- **Статус (26.04.2026):** ✅ **MVP DONE** — commit 1/2 `473f107` (schema + service + counter + 22 core tests), commit 2/2 `53f72ef` (scheduler hook + MCP/CLI + 21 surface tests + docs); self-review добавил ещё 15 тестов, итого **58 F5-C тестов** (10 mock + 48 PG-gated). См. CHANGELOG § Sprint F5-C. Реализовано: триггер по счётчику `new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N` (default 5), append-only `topic_card_versions` с `version_no`, hook между `run_topic_embedding(force=False)` и `run_watchlist_check_for_channel`, MCP/CLI surface (без Bot в MVP), triple cap (per_tick / duration / tokens), advisory lock + UNIQUE second line of defence, F11-style silent log + Anthropic billing-pause escalation.
- **Связка с D.1 + F11:** поток новых документов через D.1-incremental + match-evidence из F11 подпитывает сигнал «тема устарела по содержанию»; F5-C наследует **per-batch checkpointing** D.1 (counter инкрементируется per-batch без отката), но **не** контракт `failed_stage='resummarize'` — по Decision #13 F5-C использует F11-style silent log (single-billing исключение для billing-pause); F11 watchlist скорит против актуального summary благодаря порядку hook'ов.
- **Karpathy-like итог:** тема не только «видит» новые `source_ref`, но **обновляет формулировку** под накопленный корпус, сохраняя append-only провенанс эволюции каждой «страницы темы».

### Волна D — Данные и шум (по сигналам метрик)

- Тюнинг default threshold, документация, при необходимости **Phase 2 F11** (`batch` / `silent`) через существующую digest-инфраструктуру — отдельные PR.
  - **Update 2026-06-13 (doc-drift cross-link):** «Phase 2 F11 (batch/silent)» **DONE** через [ADR-0014](../adr/0014-watchlist-batch-silent-delivery.md); threshold-тюнинг покрыт [ADR-0012](../adr/0012-watchlist-threshold-calibration.md) / [ADR-0013](../adr/0013-watchlist-threshold-precision-floor.md). Эта строка Волны D в части F11 закрыта — оставлена для исторического контекста.
- **F5-B** — near-duplicate по embedding после метрик (`tg_dedup_duplicates_detected_total` и т.д., см. [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) § «После F11»).
  - **Update 2026-07-20 (doc-drift cross-link):** **Phase 0 observation-only counter landed Wave 2 T1** (`b294b05`; `tg_dedup_near_duplicates_detected_total{dimension="intra"|"cross"}` + histogram, observe-only). **Phase 1 (фактический dedup) — ✅ `Rejected — rate below threshold` (2026-07-20)** ([ADR-0016](../adr/0016-near-duplicate-dedup.md)): gate закрыт на данных за всю жизнь observer'а (с 2026-06-14, ~36д ≫ 7д) — **intra 0.055 % (18/32 805), cross 0.000 % (0/32 805)** ≪ 5 % по обеим осям → Phase 1 не строится. Phase-0 counter остаётся как permanent observability; F5-B Волны D закрыта по данным (не переоткрывать без нового сигнала).
- **Karpathy-like итог:** меньше мусорных дублей и ложных алертов; решения подкреплены телеметрией.

### Волна E — Граф и retrieval+ (отдельные инициативы)

- Более явные типизированные связи (topic–doc, topic–topic, cross-channel), graph-assisted retrieval — **после** стабилизации F5-C и метрик F11, отдельными спринтами.
- В [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) это может оформляться как новые строки таблицы, когда появится спека; до тех пор этот раздел — **логический хвост**, не блокер F11/F5-C.

### Волна F — Операции и guardrails

- **DI-5**, **DI-20** и аналоги из § «После F11» спринт-промпта F11 — ops и регрессионная гигиена схемы БД, не смешивать с фиче-PR F11.

---

## 4. Что намеренно не входит в ближайшие волны

- **LLM-matching на каждый новый документ** для watchlist — только если hybrid даёт систематический шум; тогда узкий classifier на top-k (отдельное решение).
- **HTTP CRUD `/api/v1/watchlists`** — вне MVP F11 (см. спринт-промпт); MCP/bot/CLI достаточно для пилота.
- **Полная замена Postgres на graph DB** — не roadmap karpathy-like для текущей фазы; эволюция от реляционной модели + pgvector.

---

## 5. Критерий «мы на правильном пути»

После **F11 + F5-C** (плюс стабильный D.1) продукт закрывает цикл:

ingestion → processing → topicization → **обновляемые темы** → **user-defined алерты** → scheduled digests,

с явными артефактами provenance и без обязательного LLM на весь поток сообщений. Дальнейшие волны (D–F) усиливают **качество и граф**, а не переписывают контракт living KB с нуля.

---

## 6. История правок документа

| Дата | Изменение |
|------|-----------|
| 2026-04-25 | Первая версия: склейка обсуждения karpathy-like с Roadmap v3 и F11/F5-C. |
| 2026-04-26 | Волна C — статус **READY к реализации**: F5-C планировочная сессия закрыта, фиксированы 12 решений (триггер по счётчику N=5, append-only `topic_card_versions`, hook между F11-prep embedding и F11 watchlist, MCP/CLI без Bot в MVP, triple cap, advisory lock). Артефакты: `START_PROMPT_SPRINT_F5C.md`, `F5C_PR_CHECKLIST.md`. F11 (Волна B) смерджен (commit `c1c9f35`). |
| 2026-04-26 | Волна C — **MVP merged** (commits `473f107` + `53f72ef`). Living-KB-контракт (Waves A/B/C) **закрыт**, баннер сверху + `## 2026-04-26 — Contract closed` секция; 24h F5-C deploy-watch окно открыто `2026-04-26T11:07:13Z`. Добавлен `## Next contract — TBD` placeholder для будущей планирующей сессии. Правка из post-Living-KB debt-fix Phase 1 (TD-04). |
| 2026-05-02 | **ADR 0006 формализован** ([`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md)) — 7 принципов получили нормативный якорь, защищённый от drift'а этого живого документа. Закрытие review-finding C-002/C-003/C-004 из [`REVIEW_2026-04-26_MERGED_PLAN.md`](REVIEW_2026-04-26_MERGED_PLAN.md) § 2. Добавлен cross-link на ADR 0006 в [`docs/architecture.md`](../architecture.md) § «Семантика данных и Living-KB». **Planning prep** для будущей next-contract сессии: [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) — 3 кандидата (F11 P2 / F5-B / Wave E) + альтернативы + open questions. Pure docs change, без code impact. |
| 2026-05-21 | **Doc-drift cleanup post-Wave-1-step-2 hygiene tail.** Добавлены секции `## 2026-05-15 — Joint BUG-013/014/024 fix-sprint DONE`, `## 2026-05-18 — BUG-014B storage-boundary fix DONE`, `## 2026-05-20 — Doc hygiene + M-15 BUG_LOG batch DONE`, `## 2026-05-21 — Wave 1 step 3 (Surface Parity) — NEXT, planning starting`. Cross-links на PR #79/#81/#84/#85 + review markers + ADR 0007/0008/0009 drafts (см. `docs/adr/`). Pure docs change, без code impact. |
| 2026-05-21 (pre-flight) | **S3 pre-flight drift cleanup.** Добавлена секция `## 2026-05-21 — S2 quick-wins (BUG-018 / BUG-017 / BUG-023) DONE` (PR #87 SHA `2e9213c`, backfill `4d567ce`). Header «Последняя крупная правка» обновлён под post-S2 sequencing (S1 planning landed → S2 quick-wins landed → S3 execution pending). Pure docs change, без code impact. |
| 2026-06-03 | **Wave 1 aggregate closure.** Steps 3–4 marked DONE (step 4 PASS-WITH-CAVEATS); step 5 ops PARTIAL; cross-link to [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md). BUG-025/026/027 deferred to Wave 2. Pure docs change. |
| 2026-06-14 | **Wave 2 Dogfood-Quality** контракт landed (`b294b05`) — секция `## 2026-06-14 — Wave 2 …`. |
| 2026-07-20 | **Post-Wave-2 reconciliation (doc-drift hygiene).** Wave 2 закрыт целиком (T2 F5-B Phase 1 = `Rejected` на данных); Волна B помечена реализованной; forward-pointer на DRAFT переписан (все 3 трека разрешены — α1/α2 DONE, β REJECTED, γ2 DONE, γ3 partial); ADR-0016 статус в §3/Wave-2 обновлён; добавлена секция `## 2026-06-18 … 07-20 — Post-Wave-2 треки (α/γ) + июльская remediation`. Pure docs change. |
| 2026-07-20 (evening) | **Residual reconcile after T7 live-check.** DRAFT §0 marked frozen-historical; review #1 row COMPLETE; γ2 DONE + anchors PR #336/#337; ROADMAP γ2 row + open Next (γ3 / γ1′ / T7 watch); PLAN_WAVE2 SoT → ROADMAP; HANDOFF B `commit pending` → DONE; ADR-0016 open-questions → moot; FUTURE_FEATURES F5-B/F5-C/F9 status banners. Pure docs. |
| 2026-07-20 (evening) | **γ3 debt-audit closeout.** [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md); WAVE1_TECH_DEBT §C F5-B → Rejected; FUTURE_FEATURES summary F5/F9 + DF disposition; γ3 row → DONE. Pure docs. |
| 2026-07-20 (evening) | **Next-contract decision-input (post-γ).** [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) — tracks δ/ε/ζ, default ε‖δ; Next pointer updated. Pure docs. |
| 2026-08-11 | **Wave 3 planning readiness.** Tech-debt gate = none; δ/ε/ζ + F5-C #15 core closed; signals 2A/2B/2C = 0/0/0; interim default = continue dogfooding. New decision-input [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md) + [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md); γ-closeout draft marked SUPERSEDED; Wave 3 unnamed. Ops: `ResummarizeLLMErrorRate` denominator excludes `refusal_cooldown`; BUG-088/087 bot deploy verified on prod. |

---

## 2026-06-14 — Wave 2 Dogfood-Quality (internal-quality track) — ✅ CLOSED (implemented `b294b05`)

> **✅ CLOSED 2026-07-20 (все треки, residual'ов нет).** Контракт **реализован**: combo **T1 / T3 / T4 / T5 / T7 shipped `b294b05`** (2026-06-14; closes #39/#40/#41); **T6 gated watchlist alert shipped `eead91e`** (2026-06-18). **T2 (F5-B Phase 1) — ✅ `Rejected — rate below threshold` (2026-07-20)** ([ADR-0016](../adr/0016-near-duplicate-dedup.md)): gate закрыт на данных (с 2026-06-14, ~36д): intra 0.055 % / cross 0.000 % (N=32 805) ≪ 5 % → Phase 1 не строится, Phase-0 counter остаётся observability.
>
> **Forward pointer — next contract:** decision-input [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md) (readiness; default = continue dogfooding при 2A/2B/2C = 0). Planning prompt: [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md). [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) — **SUPERSEDED** (δ/ε/ζ исполнены). [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) — исторический. «Wave 3» entry сюда добавляется **только** после явного выбора product-контракта (choice C в planning prompt).

Decision Point (Wave 1.5 signal-state 2A/2B/2C = 0/0/0; owner-active dogfooding,
KB grew ~2× since baseline) → **continue dogfooding → A1 internal-quality**, не
публичные 2A/2B/2C плечи. Контракт = combo: F5-B near-dup dedup (Phase 0 counter
intra+cross + gated Phase 1, canonical=earliest + «свёрнуто N» transparency), Bot UX
hygiene (TD-D-01/02/03, rich-deterministic renderer), F5-C P2 evolving topic-summaries
freshness (#15 item #4 time-based trigger + item #10 per-channel re-summarize metric).
Wave E graph / F11 HTTP CRUD / webhook 2A /
gated-score alert → parking-lot (нет signal / non-blocking). Планировочные артефакты:
[`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) +
[`START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) +
[ADR-0016](../adr/0016-near-duplicate-dedup.md) (Phase 0 Implemented; **Phase 1 Rejected 2026-07-20** — rate below gate).

---

## 2026-06-18 … 07-20 — Post-Wave-2 треки (α / γ) + июльская remediation — состояние

> **Актуальный post-Wave-2 снимок (обновлён 2026-08-11).** Все кандидатные треки из post-Wave-2 + γ-closeout (α/β/γ/δ/ε/ζ) разрешены; F5-C #15 core shipped. Следующий decision-input: [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md) (Wave 3 не именован до owner choice C).

| Трек / workstream | Состояние | Anchor |
|---|---|---|
| **α1** — watchlist recall-lift measurement (read-only) | ✅ DONE | report [`REPORT_ALPHA1_RECALL_LIFT_2026-06-18.md`](REPORT_ALPHA1_RECALL_LIFT_2026-06-18.md), `e9dfb11` |
| **Wave 1.5 review #1** (2026-06-20) | ✅ COMPLETE — «continue dogfooding»; α2 GO; сигналы 2A/2B/2C = 0/0/0 | [`REVIEW_WAVE1_5_1_2026-06-20.md`](REVIEW_WAVE1_5_1_2026-06-20.md) |
| **α2** — watchlist seed-map extend (5 GLP-1 molecule clusters) | ✅ DONE & deployed | `284436c` |
| **β / F5-B Phase 1 (T2)** — near-dup dedup | ✅ REJECTED (rate ≪ 5% gate: intra 0.055 % / cross 0.000 %, N=32 805) | [ADR-0016](../adr/0016-near-duplicate-dedup.md), `26c53e2` |
| **γ2 / T7** — F5-C P2 freshness ops-enablement | ✅ DONE — knob LIVE (prod с 2026-07-19 `=14`); C1/C2/C3 (PR [#336](https://github.com/AlexEfimov/TG_parser/pull/336)/[#337](https://github.com/AlexEfimov/TG_parser/pull/337)); **δ watch CLOSED + bump `14 → 21` APPLIED 2026-07-22T19:49Z** ([`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md)) | `b84b383`, `2c77bf5`, `55e85b5`, `fe0da5d`, `b6ca9df`, `6736672`, `b0784e6`; [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md) |
| **γ3** — parking-lot prune / debt audit | ✅ DONE (2026-07-20) — WAVE1 inventory closed (BUG-008 → γ1′); §C F5-B → Rejected; FUTURE_FEATURES F5/F9 + DF disposition; formal report | [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md) |
| **γ1 / BUG-008** — MCP remote hang | server-side H1-fix shipped (`5165875`); статус `open` by-design (pending live recurrence + transport-гипотеза H3) | [`BUG_LOG.md`](BUG_LOG.md) BUG-008 |
| **F9 Phase 2–3** — prompt-injection defense + session-at-rest/audit_log | ✅ DONE | `757eba3`, `8f42e12` |
| **S1–S7** — topicization/perf remediation + cross-channel topic-linking | ✅ DONE | S4 `b1e4c7b`, S5 `7575a2f`, S2/S3 perf |
| **BUG-064 … BUG-085** — операционные фиксы (DB-pool, refusal-quarantine, embedding-quota, ingestion outage B1/B2) | в основном ✅ resolved | [`BUG_LOG.md`](BUG_LOG.md) |

**Next (open):** **δ/T7 CLOSED** — bump `14 → 21` **APPLIED** 2026-07-22T19:49Z; **re-watch 2026-08-05 CLOSED — keep `=21`** (raw `ratio14d≈0.989` / alert still firing = BUG-083 `refusal_cooldown` noise on `labdiagnostica_logical`, not a cutoff failure; bump `→30` rejected; productive age `ok`≈35 / counter `ok`≈4 over 14d). SoT: [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md) § «Re-watch checkpoint CLOSED». ε+ζ ✅ (#342/`f4073a6`). **TTL/retention для `topic_card_versions` (#15 item #1) — ✅ CODE DONE 2026-07-22 (prod-gated):** hybrid keep-last-N ∧ older-than-M ∧ genesis-pin, hard-DELETE zero-schema, daily cron + CLI `topic purge-versions --dry-run` + gauge/counter; default `RESUMMARIZE_VERSION_RETENTION_DAYS=0` (kill-switch), prod `180`/`KEEP_LAST_N=50` по in-session owner GO + backup + dry-run ([ADR-0018](../adr/0018-topic-card-versions-retention.md), [plan](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md)). **Deploy-split:** «Событие A» ✅ deployed default-off 2026-07-24; **«Событие B» (флип `RETENTION_DAYS=180`) — ✅ ВЫПОЛНЕНО 2026-08-11T23:12:51Z** по owner GO. Момент выбран пока `WOULD purge: 0` (1284 строки, старейшим версиям ~3,5 месяца): механизм hard-DELETE обкатывается вхолостую до ~конца октября 2026, а не проверяется сразу на реальном удалении. Предусловием оказался PR [#384](https://github.com/AlexEfimov/TG_parser/pull/384) — до него флип был **инертен**, потому что приложение не читает bind-mounted `/app/.env` ([BUG-092](BUG_LOG.md)), а `up -d` не пересоздавал контейнер. **Первый on-path тик подтверждён 2026-08-12 03:30:00 UTC** — `deleted=0`, `table_size=1285`, `retention_days=180` из самого scheduler-синглтона, гейдж `0.0 → 1285.0`, counter `0.0`, ноль строк `_skipped`; **[ADR-0018](../adr/0018-topic-card-versions-retention.md) переведён в `Accepted`**. Запись включения и сверка сигналов: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § «Запись включения — 2026-08-11». Baseline 2026-07-23: would_purge=0. **diff-API (#15 item #2) — ✅ CODE DONE 2026-07-23:** read-only `get_topic_history_diff` (MCP) + `tg-parser topic diff` (CLI) поверх общего pure-helper `diff_topic_summaries` (`difflib` summary text-diff + `scope_in`/`scope_out` set-diff); dual-source (archival `version_no` pairs `topic_card_versions` **+** `current`/`latest` → live card `topic_cards`), default genesis (v1) → current; robust к post-TTL `version_no` gaps (ADR-0018) — typed not-found «reclaimed by retention policy», не 500; repo read-path `TopicCardVersionRepo.get_two_versions`; no schema-change, no new deps ([plan](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md), [START_PROMPT](START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md)). **F5-C #15 #3 topic-digest + #5 bot read-tools — ✅ DONE** (ADR-0019 / PR #355; не parking-lot). Parking-lot: Wave E, F11 HTTP CRUD, webhook 2A, S4/F1 Full, F5-C #6–#9, `force_resummarize`-в-боте — gated на 2A/2B/2C > 0 or explicit GO. Decision-input: [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md). **Optional hygiene — ✅ ИСПОЛНЕНА И ЗАДЕПЛОЕНА 2026-08-06** (PR [#370](https://github.com/AlexEfimov/TG_parser/pull/370), прод `ba7d66d`). Все три follow-up'а того вердикта закрыты: (1) `refusal_cooldown` исключён из **обеих** частей `ratio14d` — замер на одних прод-данных `0.9887 → 0.8824`; **gate-алерт `ResummarizeAgeTriggerGateF5CPhase2` снят** (решение закрыто, вечно-красный info-алерт вреден), взамен добавлен компенсирующий сигнал `tg:resummarize_refusal_cooldown:count24h` + `ResummarizeRefusalCooldownPoisonPill` — то есть строка «alert still firing» выше относится к состоянию **на 2026-08-05** и больше не описывает прод; (2) skip cooldown-тем при отборе кандидатов — **не понадобился**: poison-pill `comment:8992` вылечен разовым cross-vendor fallback'ом (`openai/gpt-4.1`, `new_version: 3`), тема выпала из age-предиката; (3) постоянный `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` — **отклонён owner'ом**: он потребовал бы второго chat-LLM аккаунта, что против модели single-operator / self-host (A1); knob остаётся опцией, выключенной по умолчанию. Побочно вскрыт и структурно закрыт [BUG-090](BUG_LOG.md) (одиночный file bind-mount пинил Prometheus к старому inode ⇒ конфиг молча не деплоился). SoT сессии: [`SESSION_F5C_MINIMAL_FALLBACK_2026-08-05.md`](SESSION_F5C_MINIMAL_FALLBACK_2026-08-05.md). **Открытые хвосты:** ~~знаменатель `ResummarizeLLMErrorRate` разбавлен бесплатными `refusal_cooldown`~~ → ✅ **fixed 2026-08-11** (`outcome!="refusal_cooldown"` in denominator); остаточные file-маунты из BUG-090 — `init-db.sh` (low; правка mount-спеки = пересоздание контейнера БД) и `.env`×3 (разбирать вместе с BUG-078). `Caddyfile` из этого списка **снят 2026-08-07 как неактуальный**: Caddy на хосте не используется вообще (80/443 держит системный nginx с живым LE-сертификатом), чинить было нечего. Побочно вскрытые расхождения: (1) документированный `--profile production` упал бы на этом хосте по конфликту портов с nginx — **закрыто 2026-08-07**: единый источник правды по reverse-proxy теперь [`SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md) § Reverse proxy (инварианты + команды чтения живой правды), исправлены два runbook'а, утверждавших существование контейнера Caddy; (2) конфиги nginx вне репозитория — **открыто**, вынесено в [`technical-debt-roadmap.md`](../technical-debt-roadmap.md) § 7 с промежуточной мерой (дамп `nginx -T` в приватный бэкап).
