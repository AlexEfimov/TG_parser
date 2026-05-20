# Changelog

All notable changes to TG_parser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### S2 quick-wins — BUG-018 / BUG-017 / BUG-023 (2026-05-21)

**Контекст.** Wave 1 step 3 sequencing S2 slot per [`START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md). Three independent low/medium-effort observability + automation-safety bugs filed against the 2026-05-15 Claude MCP testing session bundled into one PR with atomic commits. Source of truth: per-bug records in [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) (closure rows under «Update 2026-05-21»).

**Changes:**

- **BUG-018** (high severity — automation safety) — `tg-parser topicize` now tracks `total_batches` / `failed_batches` / `last_batch_error` on `TopicizationPipelineImpl`; `run_topicization` surfaces the trio in its returned stats; CLI exits with code **2** when `failed_batches / total_batches > 0.5` (systemic-fail class) and prints the first error class to stderr with a credentials / quota hint. The misleading «возможно, недостаточно данных» line is suppressed when batch failures dominate. Partial-fail (≤50 % errored) stays exit 0 with a warning summary. Automation scripts wrapping the CLI exit code can now detect systemic LLM-batch failures (billing / auth / quota class errors) instead of silently proceeding to dependent steps.
- **BUG-017** (low severity — diagnostic clarity) — `tg_parser/services/pipeline_service.py` scheduler-path log line `[3/4] Topicization skipped (--skip-topicize)` replaced with `[3/4] Topicization skipped (scheduler does not auto-topicize by design; run 'tg-parser topicize <channel>' manually)`. Zero runtime semantics change; clarifies architectural intent so future operators don't waste investigation cycles looking for the non-existent runtime flag (the 2026-05-15 testing session burned ~2h on this).
- **BUG-023** (low severity — observability) — `_validate_quality` now returns `(valid, reason)` with six discrete criteria (`singleton_no_anchors` / `singleton_score_below_min` / `singleton_doc_not_found` / `singleton_text_too_short` / `cluster_too_few_anchors` / `cluster_anchor_score_below_min`); `_build_topic_card` emits structured `topic_failed_quality_criteria` log event with `reason` / `title` / `items` fields for every rejection path (including early `no_raw_anchors` / `no_valid_anchors_after_parsing`); aggregate `rejection_breakdown: dict[str, int]` surfaced via both `run_topicization` stats and new `IncrementalTopicizeResult.rejection_breakdown` field; CLI summary renders «Quality filter rejected X topics: A by …, B by …». Operators can now understand why coverage is below expectation from logs alone.

**Tests:** 31 new pure-mock unit tests across three files (18 in the initial fix-commits + 13 added in pre-PR self-review):

- `tests/test_bug018_topicize_exit_code.py` — **12 cases**: batch-failure counter on multi-batch all-fail / partial-fail / counter reset between runs; single-batch failure records state before raising; first-error capture is deterministic by input order (`gather(return_exceptions=True)`); CLI exit-code matrix — exit 2 on systemic fail with «недостаточно данных» suppressed, exit 0 on partial fail with warning, exit 0 with legacy hint on truly empty channel; **exit 0 at exactly 50 % boundary** (threshold is strictly `> 0.5`), **exit 2 just above 50 %**, **stderr surfaces credentials / quota / billing hint triplet**, **single-batch exception path exits 1** (distinct signal from multi-batch exit 2).
- `tests/test_bug017_topicization_skipped_log.py` — 1 pinning case (the new log line must lack the misleading `--skip-topicize` literal AND mention `by design` + `tg-parser topicize`; integration-ish — actually runs `run_full_pipeline(skip_topicize=True)`).
- `tests/test_bug023_topic_rejection.py` — **18 cases**: seven `(valid, reason)` tuples from `_validate_quality`; `_record_rejection` aggregate counter; structured event with proposed-title context + legacy opaque line is gone; both early-rejection paths counted (**`no_raw_anchors` + `no_valid_anchors_after_parsing`**); `rejection_breakdown` resets between `topicize_channel` runs; **title truncation to 80 chars** in structured event; **`IncrementalTopicizeResult.rejection_breakdown` defaults to `{}` + round-trips**; **service-layer `run_topicization` surfaces the breakdown in stats with defensive `dict()` copy + JSON-serializable**; **CLI renders breakdown in full + incremental paths sorted alphabetically by reason**; **CLI omits the line when breakdown is empty** (operator absence-signal).

**Self-review additions:**

- **Coverage gaps closed:** 50 % threshold boundary (both sides), stderr hint content assertion, single-batch fail exit code, deterministic first-error capture, `no_valid_anchors_after_parsing` early-rejection, title truncation, service-layer stats propagation with defensive-copy invariant, CLI render format (full + incremental + empty no-op).
- **Docs:** [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) `topicize` section gained an «Exit codes» table (0 / 1 / 2 semantics) and [`docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md`](docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md) § 7 explains the same matrix in the billing-pause recovery context.
- **Full suite:** `uv run pytest` → **2147 passed, 258 skipped, 0 failed** (was 2134/258/0 before this slot; ∆ = 13 new tests, no regressions).
- **Lint:** `ruff check` + `ruff format` clean on all touched files.
- **Constraints preserved:** no methodology / `pyproject.toml` / `requirements.txt` / `uv.lock` changes per AGENTS.md; untracked notes (HANDOFF_* / WATCH_WINDOW_* / mcp_testing/) untouched.

### Planning landed — Wave 1 step 3 Surface Parity (2026-05-21)

**Контекст.** S1 planning sub-session per route S1 → S2 → S3 → S4 → S5.
Doc-drift cleanup + ADR drafts + sprint planning artifact, no code changes.

- **C1 doc-drift cleanup:** `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — appended 2026-05-15 (BUG-013/14/24 fix + BUG-016), 2026-05-18 (BUG-014B), 2026-05-20 (doc hygiene + M-15 batch), 2026-05-21 (Wave 1 step 3 NEXT, planning starting). `docs/notes/FUTURE_FEATURES.md` — header dates Apr → May 2026; F4-B status aligned. `docs/notes/BUG_LOG.md` — BUG-016 Active → Resolved (per REVIEW_2026-05-16 §4) с mover note.
- **C2 ADR drafts (status: Draft):** `docs/adr/0007-mcp-scheduler-dispatch.md` — MCP↔scheduler dispatch contract; BUG-015 / ENH-1 / ENH-2 / O-3 blocker context; 5-option matrix; preliminary recommendation = Option A (safety patch) + Option B (HTTP endpoint); decision deferred to step 3.1. `docs/adr/0008-subscription-target-model.md` — chat_id vs polymorphic target (webhook/channel) для watchlist/digest; 3-option matrix; preliminary recommendation = Option B polymorphic target; chat_id-only locked for step 3, full target model deferred to Wave 2A + Wave 1 step 4. `docs/adr/0009-idempotency.md` — idempotency для `subscribe_*` (BUG-022) + `Idempotency-Key` HTTP header; 3-option matrix; preliminary recommendation = Option C hybrid (service-layer upsert + HTTP header middleware); primary input для step 3 sprint Q2.
- **C3 sprint planning artifact:** `docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md` — Wave 1 step 3 Surface Parity sprint prompt. Scope locked: P-1 watchlist HTTP API (`/api/v1/watchlists`), P-2 digest HTTP API (`/api/v1/digests`), ENH-9 (`workspace_id` on `subscribe_*` across 4 surfaces), BUG-022 (idempotency). Decisions Q1–Q9 locked (auth = existing `X-API-Key` via `resolve_current_user`; idempotency = ADR 0009 Option C hybrid with asymmetric natural keys per table — `watch_interests (user_id, title)` and `digest_subscriptions (owner_id, name)`; `workspace_id` = optional FK on both tables, no auto-expansion; base path = `/api/v1/*` plural; versioning = v1; target = chat_id-only; response = Pydantic in flat `api/schemas.py`; DELETE = soft watchlist + hard digest; tests = TestClient + service unit + idempotency contract). 8 OPEN questions explicitly flagged for execution sub-session. Anti-scope: BUG-015 / ENH-1 / ENH-2 / O-3 / ADR 0007 ratify NOT in step 3 (→ step 3.1); polymorphic target NOT in step 3 (→ Wave 1 step 4 + Wave 2A); F4-B Sharing / Bot workspace UX / O-1 NOT in step 3. PR shape: Single PR + 4 atomic commits, ~1000–1400 LOC + ~40–50 new tests.
- **C4 self-review fixups (post-review):** Sprint prompt + ADR 0008 / 0009 corrected against code: Q1 auth header is `X-API-Key` (not `Authorization: Bearer` — the latter is MCP-only); Q6 POST body uses `title` for watchlist (not `name`) per `WatchInterest.title` schema; Q7 Pydantic schemas land in existing flat `tg_parser/api/schemas.py` (no `schemas/` package refactor in scope); ADR 0009 natural keys updated to asymmetric `(user_id, title)` for watch_interests and `(owner_id, name)` for digest_subscriptions; ADR 0008 cross-refs aligned; §5 test plan + Q3 ENH-9 storage description + Karpathy checklist BUG-022 row reflect both UNIQUE constraints.

Branch: `docs/wave1-step3-planning-2026-05-21`. Refs:
[`PARITY_DECISION_TRACKING.md`](docs/notes/PARITY_DECISION_TRACKING.md),
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 5.1,
[`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md`](docs/notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md).

### Documentation Hygiene — counts/versions/ADR-status/MVP-banners (2026-05-20)

**Контекст.** Self-review актуальной документации проекта 2026-05-07 нашёл
~10 расхождений между документами и реальностью кода. Этот sprint фиксит
M-1, M-2, M-3, M-7, M-8, M-15, M-16, M-14, C-3 и testing-strategy refresh
docs-only, no code changes.

- Tools count + версия sync (README, USER_GUIDE, SERVER_ARCHITECTURE): 43 MCP / 32 bot, `4.3.0` per `pyproject.toml`.
- MCP specs — scope-narrow banner + честная CORS отметка для ChatGPT (уже в compat docs; verified).
- ADR 0001/0003/0004 — implementation status sections (bot count 32 sync).
- MVP-banners (architecture, business-requirements, product-overview, testing-strategy).
- ROADMAP_V3 Wave 1 disambiguation (Living-KB vs Audience-driven).
- BUG_LOG Active summary table: BUG-009/010/011/012 → resolved pointers (full entries in § Resolved).

Branch: `docs/doc-hygiene-2026-05-20`. Refs: `docs/notes/START_PROMPT_DOC_HYGIENE_2026-05-XX.md`.

### BUG-014B — storage-boundary tz-aware coerce (2026-05-18)

**Контекст.** After PR #79 closed scheduler-side BUG-014, the same naive-vs-aware `rate_limit_until` comparison became reachable at `orchestrator.py:110`, putting `kdl_ru` and `profendocrinologist` into a permanent fail-loop (~56 `TypeError` lines/day). Source of truth: [`docs/notes/START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md`](docs/notes/START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md).

**Changes:**

- **BUG-014B** ([#83](https://github.com/AlexEfimov/TG_parser/issues/83)) — promoted `coerce_aware_utc` from `scheduler_service` to `tg_parser/domain/json_utils.py` (shared with `parse_iso_datetime`). `SAIngestionStateRepo._row_to_source` now coerces all 8 naive datetime fields to tz-aware UTC on read (Option B storage boundary). Scheduler-side `coerce_aware_utc` retained as belt-and-suspenders.

**Tests:** T-0 helper contract in `tests/test_json_utils.py`; T-1/T-2 in `tests/test_ingestion_state_repo_datetime_coerce.py`; T-3 orchestrator regression in `tests/test_orchestrator_rate_limit.py`.

### Joint scheduler fix-sprint — BUG-013 / BUG-014 / BUG-024 (2026-05-15)

**Контекст.** Three interconnected scheduler bugs filed against the F4-B Core 24h watch window: `IllegalStateChangeError` from shared `AsyncSession` across `asyncio.gather` tasks (BUG-013), `TypeError` from comparing tz-naive `source.rate_limit_until` with `datetime.now(UTC)` (BUG-014), and the `last_attempt_at IS NULL` invariant gap when a task crashed before reaching the `finally`-block `record_attempt` (BUG-024). Single PR + single atomic commit; source of truth: [`docs/notes/START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](docs/notes/START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md).

**Changes:**

- **BUG-013** ([#76](https://github.com/AlexEfimov/TG_parser/issues/76)) — `tg_parser/services/scheduler_service.py:run_incremental_for_all_sources`: moved `ingestion_and_processing_repos()` inside each `_process_source` task so each concurrent task owns its own SQLAlchemy `AsyncSession`. Outer scope now opens a short-lived `ingestion_state_repo()` purely for the initial `list_sources(status="active")` read and closes it before fanning out per-task work. Dropped the `repo_lock` `asyncio.Lock` (no longer needed once sessions are per-task; aggregate-dict mutations are safe under asyncio cooperative scheduling). `asyncio.gather` now uses `return_exceptions=True`; unhandled escapes are surfaced via a `scheduler_unhandled_escape source_id=...` structured log line. Inline contract comment documents the aggregate-mutation safety contract.
- **BUG-014** ([#77](https://github.com/AlexEfimov/TG_parser/issues/77)) — added `_coerce_aware_utc` module-level helper that attaches `UTC` to tz-naive `datetime` inputs (identity on already-aware, `None` passes through). Called at the `rate_limit_until` comparison site in `_process_source` so the comparison is always aware-vs-aware. A parse-boundary fix in `tg_parser/domain/json_utils.parse_iso_datetime` is deferred as a follow-up (cross-cutting change with wider blast radius).
- **BUG-024** ([#78](https://github.com/AlexEfimov/TG_parser/issues/78)) — new `IngestionStateRepo.mark_attempt_started(source_id)` abstract method in `tg_parser/storage/ports.py` + SQLAlchemy implementation in `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` (UPDATE `last_attempt_at = now()` with self-commit, mirrors the `record_attempt` persistence style). Scheduler `_process_source` now calls `await task_state_repo.mark_attempt_started(source_id)` immediately after the rate-limit early-return + "Processing source" log line, BEFORE the first pipeline `await` — guaranteeing the invariant «if the scheduler attempted a source, `last_attempt_at` is non-null» holds even on per-task crash / cancellation.

**Tests:** 6 new pure-mock unit tests in `tests/test_scheduler_service.py` (T-1 .. T-6) cover per-task session isolation across concurrent sources, `return_exceptions=True` isolation + unhandled-escape logging, tz-naive `rate_limit_until` coercion, and `mark_attempt_started` invariant (called once per non-skipped source, BEFORE pipeline; NOT called for rate-limited sources). All 19 pre-existing scheduler tests updated to also patch `ingestion_state_repo` (the new outer-scope read path). Full suite: 2095 passed, 0 regressions; `ruff format` + `ruff check` clean.

### Wave 1 Step 2 — F4-B Core Workspaces (2026-05-13)

**Контекст.** Wave 1 step 2 per `PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1: тематические workspace-коллекции поверх F4-A multi-tenancy. Single PR + 5 atomic commits; ~1450 LOC + ~75 новых тестов. Source of truth: `docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`.

**Hard invariants (locked Q1–Q8 + Karpathy 7-checklist):**

- `workspace_id=None` → bit-for-bit F4-A behaviour (regression-guarded по `tests/test_f4b_backward_compat.py`).
- Unknown / foreign `workspace_id` → 404-like empty (`WorkspaceNotFound`); никогда не leak'аем existence.
- Empty workspace → `effective_channel_ids=[]` (explicit, не silent "all channels" — hidden gotcha § 3).
- `get_topic_details` / `get_document` возвращают full bundle items независимо от workspace (Q4 R3 — workspace narrows list/search, не access control).
- Service-слойные signatures (`retrieval_service.search` и др.) не меняются — workspace resolve живёт на surface level.

#### Commit 1/5 — schema + migration + Pydantic + JSON contract

- `migrations/versions/ingestion/20260513_add_workspaces.py` — Alembic ingestion-branch revision `e9f0a1b2c3d5` создаёт `workspaces` + `workspace_sources` (M2M, composite PK, FK ON DELETE CASCADE).
- `tg_parser/storage/sqlalchemy/_metadata.py` — `INGESTION_METADATA` обновлён до head `e9f0a1b2c3d5` с обоими таблицами.
- `tg_parser/domain/models.py` — `Workspace` + `WorkspaceSource` Pydantic models с trim+length валидацией `name` (gotcha § 6 per-owner uniqueness).
- `docs/contracts/workspace.schema.json` — JSON Schema contract для обоих domain models.
- `tests/test_f4b_schema.py` — 10 тестов: Pydantic валидации + Postgres CHECK constraints (`UNIQUE(owner_id, name)`, `length(trim(name)) > 0`, FK CASCADE).

#### Commit 2/5 — service + repo + ownership

- `tg_parser/storage/ports.py` — `WorkspaceRepo` ABC (CRUD, M2M membership, `resolve_source_id_for_channel`).
- `tg_parser/storage/sqlalchemy/workspace_repo.py` — `SAWorkspaceRepo` (raw SQL через индексы, `ON CONFLICT DO NOTHING` для idempotent membership, JOIN на `sources` с soft-delete фильтром).
- `tg_parser/auth/ownership.py` — `WorkspaceNotFound` (404-like) + `assert_workspace_access` helper (admin-bypass per F4-A Q2 edge case 3).
- `tg_parser/services/workspace_service.py` — `WorkspaceService` (CRUD + `effective_channel_ids` resolver, channel_id → source_id translation, `WorkspaceSourceNotFound`).
- `tg_parser/services/db_context.py` — `workspace_repo()` async context manager.
- 32 теста: `tests/test_f4b_workspace_repo.py` (15), `tests/test_f4b_assert_workspace_access.py` (4), `tests/test_f4b_workspace_service.py` (13).

#### Commit 3/5 — MCP + CLI surface

- `tg_parser/mcp_server.py` — 8 новых MCP tools: `list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `add_workspace_source`, `remove_workspace_source`, `list_workspace_sources`, `list_all_workspaces`. Result types: `WorkspaceInfo`, `ListWorkspacesResult`, `CreateWorkspaceResult`, `RenameWorkspaceResult`, `DeleteWorkspaceResult`, `WorkspaceSourceOpResult`, `ListWorkspaceSourcesResult`.
- `tg_parser/cli/workspace_cmd.py` — `tg-parser workspace` Typer-приложение с 8 подкомандами (`list`, `create`, `rename`, `delete`, `add-source`, `remove-source`, `list-sources`, `list-all`).
- `tg_parser/cli/app.py` — регистрация `workspace_app` через `app.add_typer(..., name="workspace")`.
- 20 тестов: `tests/test_f4b_mcp_tools.py` (12), `tests/test_f4b_cli_workspace.py` (8).

#### Commit 4/5 — scoping integration in read-tools

- `tg_parser/mcp_server.py` — `_resolve_workspace_scope` helper; `workspace_id: str | None = None` на 8 read tools (`list_channels`, `list_topics`, `search_knowledge_base`, `ask_question`, `get_topic_details`, `get_document`, `get_related_topics`, `get_cross_channel_stats`). Service signatures не меняются — narrowing на surface level до downstream call.
- `tg_parser/cli/app.py` — `_resolve_workspace_scope_cli` helper; `--workspace-id` + `--user` флаги на `tg-parser search` и `tg-parser ask`.
- `tests/test_f4b_scoping_read_tools.py` — 14 тестов scope матрицы (None / unknown / foreign / empty / intersect) + Q4 R3 invariant для `get_topic_details` / `get_document`.

#### Commit 5/5 — regression guards + observability + docs

- `tg_parser/api/metrics.py` — Prometheus exporters: `tg_workspace_total` (Gauge), `tg_workspace_size` / `tg_workspace_effective_size` / `tg_workspace_resolver_seconds` (Histogram), `tg_workspace_query_total{result}` / `tg_workspace_tool_total{tool, result}` (Counter). Helpers: `record_workspace_query`, `record_workspace_tool`, `set_workspace_total`, `bump_workspace_total`.
- `tg_parser/services/workspace_service.py` — инструментирован: gauge bump на create/delete, query counter + size/duration histograms в `effective_channel_ids`, structlog `info`/`debug` со связкой `user_id` / `workspace_id` / `resolver_seconds`.
- 31 тест: `tests/test_f4b_backward_compat.py` (12 — каждый scoped tool без workspace_id ≡ F4-A baseline), `tests/test_f4b_workspace_isolation.py` (6 — cross-user 404-like), `tests/test_f4b_metrics.py` (8 — Prometheus exporter shape + emit на create/delete/resolver), `tests/test_f4b_golden_path.py` (1 end-to-end multi-workspace).
- `docs/notes/FUTURE_FEATURES.md` § F4-B → ✅ Core MVP DONE 2026-05-13.
- `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — раздел `## 2026-05-13 — Wave 1 step 2 (F4-B Core) DONE ✅`.

**Verification:** ~2152 passed (baseline 2047 + 75 новых для F4-B + 30 уже существовали в repo), 0 regressions. `ruff format` + `ruff check` clean. Pre-flight gate-1 GREEN (Prometheus `up{service="bot"}` = `1`, `confirm_flow_mismatch` 72h = `0`, `gemini_*` errors 72h = `0` на `tg_parser_bot`).

**Deferred (Wave 1 step 3+ / Wave 2):** O-1 atomic `move_workspace_source` (non-atomic remove + add используется в MVP, см. `PARITY_DECISION_TRACKING.md` § 3); Bot integration (`tg_parser/bot/tools.py` без workspace MVP, Q3 locked); F11 watchlist workspace_id (Q7 deferred); F6 digest workspace_id (Q8 deferred); sharing / collaboration (audience A2/A3 — Wave 2+).

**Roadmap:** F4-B Core ✅ → Wave 1 step 3 (Surface Parity) is next.

### Session J — ADR 0005 mini-refactor: bot-scope LLM config + BOT_LLM_FALLBACK runbook (2026-05-07)

**Контекст.** Реализует ADR 0005 Variant A — добавляет `"bot"` в `LLMConfigManager` с Gemini-only constraint. Устраняет последнюю «снежинку» в LLM-конфигурации: бот теперь получает симметричную runtime-конфигурацию через `set_llm_config(scope="bot", provider="gemini", model=...)` без рестарта. Tracker: GH issue [#60](https://github.com/AlexEfimov/TG_parser/issues/60). Branch: `feat/session-j-adr0005-bot-llm-2026-05-06`.

#### Commit 1 — bot-scope LLM config + GeminiAgent.resolve (ADR 0005)

- `tg_parser/config/settings.py` — добавлен `"bot"` в `LLM_SCOPES`; `LLMConfigManager.set("bot", ...)` валидирует `provider == "gemini"` (D-1) и отвергает `temperature`/`max_tokens` с `ValueError` (D-2 model-only); `resolve("bot")` возвращает Gemini static defaults (`bot_gemini_model`) и иммунен к global override (D-1: `elif global_ov and stage != "bot"`).
- `tg_parser/processing/prompt_loader.py` — добавлен `"bot"` в `REQUIRED_PROMPT_STAGES` (регрессионная синхронизация с `LLM_SCOPES \ {"global"}`).
- `tg_parser/bot/agent.py` — добавлен метод `_resolved_model()`: lazy-import `llm_config.resolve("bot")` с `try/except` fallback на `self._model`; `_call_gemini` URL переключён с `self._model` на `self._resolved_model()` — runtime model switch без рестарта.
- `tg_parser/bot/tools.py` — TOOL_DECLARATIONS для `set_llm_config` и `reset_llm_config` обновлены (scope description включает `"bot"` + Gemini-only + D-2 constraints).
- `tg_parser/mcp_server.py` — docstrings `set_llm_config` и `reset_llm_config` обновлены (scope `"bot"` + ADR 0005 D-2 ref).
- `tests/test_settings_bot_scope.py` — новый файл, 9 тестов T-1..T-8 + T-11 (settings layer): LLM_SCOPES includes bot, resolve defaults, set success/failure, D-1 global immunity critical test, clear/revert, get_all output, D-2 temperature/max_tokens raises.
- `tests/test_bot_agent_resolved_model.py` — новый файл, 2 теста T-9..T-10 (agent layer): `_resolved_model()` uses runtime override, `_resolved_model()` falls back to init default on singleton error.

**Verification:** full pytest baseline 2047 passed (baseline Session I: 2036; +11 новых), 0 regressions. `ruff check` + `ruff format --check` clean.

**Locked decisions:** D-1 (global override immunity for "bot" scope), D-2 ("bot" scope is model-only).

#### Commit 2 — BOT_LLM_FALLBACK runbook (ADR 0005 operational complement)

- `docs/runbooks/BOT_LLM_FALLBACK.md` — manual procedure для оператора при Google Gemini outage: триггеры, pre-flight, runtime model downgrade, rollback, smoke check, quarterly drill.

### Wave 1 Step 1 — DONE marker + ADR 0005 annotation + roadmap markers (Session K, 2026-05-08)

**Контекст.** Закрытие Wave 1 step 1 (Bot UX hardening) per `PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1. Sessions H + I + J все deployed и 24h watch GREEN (verdict §0 Session K pre-flight 2026-05-08 ~19:10 UTC: Prometheus `up{service="bot"}` = `"1"`, `confirm_flow_mismatch` 24h = `0`, `gemini_*` errors 24h = `0` на `tg_parser_bot`). Параллельно — extended docs scope per self-review актуальной документации 2026-05-07.

- `docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` — DONE marker создан (template C1 из `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 4).
- `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — top-level section «2026-05-08 — Wave 1 step 1 DONE» cross-link на marker (mirror `## 2026-04-26 — Contract closed` pattern).
- `docs/adr/0005-bot-llm-provider-flexibility.md` — Implementation status block (Variant A + D-1 + D-2 finalized) + D-3 per-call resolution (Session J landed, заменяет «Без hot-reload» формулировку).
- `docs/notes/FUTURE_FEATURES.md` L96 (Wave 1.5 → F8-A → F5-A) — supersede note под `PRODUCT_STRATEGY_AUDIENCE_DRIVEN` Wave 1.
- `docs/notes/SESSION48_ROADMAP_V2.md` + `DEVELOPMENT_ROADMAP_SESSION29.md` — superseded banners в начале файлов (исторический контекст сохраняется).
- `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 7.1 — F-Prereq-1 status update (filed в `FUTURE_FEATURES.md` L28 + L2296+ + cross-link на `MONETIZATION_MECHANISMS_2026-05-02.md`).
- `docs/SERVER_ARCHITECTURE.md` — Prometheus scrape targets list extended с `tg_parser_bot` job (`tg_bot:8081`, `service: bot`, per `docker/prometheus.yml` + TD #53 close commit `ec52060`).

Tracker: см. `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 4 (template C1) + self-review актуальной документации 2026-05-07 (resolves C-4, C-5, C-6, M-5, M-9, M-13). GitHub issues closed: #46, #47, #48 (BUG-010/011/012) + #51, #52 (tech-debt связанные). Companion PR (separate scope): runbook nomenclature hotfix [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (merged 2026-05-08, `Closes #62`).

### Session I — Source username alias resolution: BUG-010 structural close (2026-05-06)

**Контекст.** Закрывает структурно BUG-010 — write-tools (`remove_channel`, `pause_channel`, `resume_channel`, `trigger_pipeline`, `add_channel` dedup) через bot и MCP принимали `channel_id=username` от пользователя, но передавали его в `get_source(source_id)` который выполняет PK-lookup по числовому Telegram chat ID. Пользователь вводил `AgeManagment`, бот возвращал «Channel not found» хотя канал был виден в `list_channels`. Source: `BUG_LOG.md` § BUG-010. Tracker: GH issue [#50](https://github.com/AlexEfimov/TG_parser/issues/50). Branch: `fix/bug-010-source-username-alias-2026-05-06`.

#### BUG-010 — repo layer + write-tool call-sites

- `tg_parser/storage/ports.py` — добавлен абстрактный метод `get_source_by_username(username, *, include_deleted=False) -> Source | None` в `IngestionStateRepo` (BUG-010, Session I).
- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` — добавлена конкретная реализация `get_source_by_username` (`WHERE channel_username = :username`, аналогичный `deleted_clause` паттерн как в `get_source`).
- `tg_parser/bot/tools.py` — добавлен async helper `_resolve_source(normalized, state_repo)` (PK-first, username-fallback per D-C); все 5 write-tool call-sites обновлены: `_exec_trigger_pipeline`, `_exec_pause_channel`, `_exec_resume_channel`, `_exec_add_channel` (dedup), `_exec_remove_channel`.
- `tg_parser/mcp_server.py` — добавлен module-level `_resolve_source` helper (идентичная логика); все 5 MCP function call-sites обновлены: `add_channel` (dedup), `pause_channel`, `resume_channel`, `remove_channel`, `trigger_pipeline`.
- `tests/test_bot_tools_bug010_username_alias.py` — 6 unit tests: U-1..U-6 (mock-based; `_resolve_source` fallback path, no-fallback-when-PK-found, и 4 executor-level regression тесты).
- `tests/test_ingestion_state_repo_username_alias.py` — 4 testcontainers integration tests: I-1..I-4 (`get_source_by_username` SQL, PK/username isolation, `_resolve_source` fallback и backward-compat paths).

**Verification:** full pytest baseline 2028 → ~2038, 0 regressions. `ruff check` + `ruff format --check` clean.

**Locked decisions (pre-flight):** D-A (fallback в repo layer + shared helper), D-B (все write-tools в обеих поверхностях), D-C (PK first, username fallback).

### Session H — Bot read-context preservation across turns: BUG-011 structural close (2026-05-03)

**Контекст.** Закрывает структурно BUG-011 — bot терял subject channel context между read-tool turns: «темы канала AgeManagment» → «покажи 5 главных тем» → возвращал global top-5 вместо channel-scoped. Та же root-cause-class что BUG-002 (statelessness), но read-side вместо write-side. Source: `BUG_LOG.md` § BUG-011. Tracker: GH issue [#57](https://github.com/AlexEfimov/TG_parser/issues/57). Branch: `fix/bug-011-read-context-2026-05-03`.

#### BUG-011 — read-context shadow state + agent injection

- `tg_parser/bot/states.py` — добавлен `ReadContextData` TypedDict (data-only per D-1; не новый StatesGroup). Fields: `last_channel_id`, `last_tool`, `created_at` (ISO UTC для TTL).
- `tg_parser/bot/tools.py` — добавлен `_READ_TOOLS_TRACKED_FOR_CONTEXT` frozenset (4 tools с `channel_id` в схеме: `ask_question`, `search_knowledge_base`, `list_topics`, `get_cross_channel_stats`; `get_related_topics` исключён — schema использует `topic_id`, D-2 contract test проверяет forward-invariant).
- `tg_parser/bot/handlers.py` — `READ_CONTEXT_TTL_SECONDS = 900` (15 min, D-5); хелперы `_is_stale`, `_refresh_read_context`, `_read_context_for_agent`; `handle_text` читает non-stale read_context перед agent call и записывает `result.read_tools_called` после; `_handle_confirmation_response` + `_handle_pagination_response` сохраняют `read_context` через `state.clear()` (snapshot + restore); `cmd_start` вызывает `state.clear()` для D-7 сброса на `/start`.
- `tg_parser/bot/agent.py` — `AgentResult.read_tools_called: list[tuple[str, dict]]` (возвращает tracked tool calls для handler); `process_message(read_context=None)` параметр; `_call_gemini(read_context=None)` инжектирует «Implicit channel context (read-side, BUG-011, Session H)» блок в `systemInstruction` когда read_context non-None (D-4 programmatic injection). D-6 immunity: блок явно запрещает write-tools от использования implicit context.
- `prompts/bot.yaml` v1.5.0 → v1.6.0 — новая секция «Implicit channel context for read-tools» между «Channel ID normalization» и «Fallback on empty results»; HARD RULE D-6 immunity (перечислены все 7 write-tools по имени); acknowledgement rule («Показываю топ-5 тем канала X:»); override rule (explicit mention > implicit context); stale context → global fallback.
- `tests/test_bot_read_context.py` — новый файл, 29 тестов в 6 классах: A (update-site guard, 5 tests + R-1 contract parametrized), B (TTL resolution, 5 tests), C (agent injection, 4 tests), D (integration / direct BUG-011 regression, 3 tests), E (FSM-state interaction incl. D-7, 5 tests), F (prompt contracts, 3 tests). `tests/test_bot_fsm.py::TestBug009SuggestionConfirmGuard` — исправлен mock `stubbed_call_gemini` для совместимости с новым `read_context=None` параметром.

**Verification:** full pytest **2028 passed** (baseline 1999; +29; 0 regressions). `ruff check` + `ruff format --check` clean.

**D-2 deviation vs pre-flight:** `get_related_topics` убран из frozenset — schema использует `topic_id` а не `channel_id` (это correct exclusion по той же логике что `get_topic_details`; forward-contract test A-R1 закрепляет это инвариантно).

**Locked decisions:** D-1 (data-only), D-4 (programmatic injection), D-6 (write-tools immune). **Default decisions:** D-2 (4 tools), D-3 (update on every call), D-5 (TTL 15 min), D-7 (clear on /start).

### Prompt v1.5.0 — BUG-012 format directive against pagination phrasing on hint fields (2026-05-02)

**Контекст.** Закрывает BUG-012 prompt-only: cosmetic LLM-rendering bug «...темы 1 из ['AgeManagment']» в BUG-007 fallback flow (LLM mis-applied pagination phrasing template к advisory hint field `available_channel_ids`). Source: `BUG_LOG.md` § BUG-012. Tracker: TD-prompt-suggestion-format-clarity (P3, no GH issue filed — too small). Companion landing с Session G (Session G prepared the prompt-loader smoke pattern via v1.4.0 bump, v1.5.0 reuses the same shape).

#### BUG-012 — prompt-only HARD RULE против pagination phrasing
- `prompts/bot.yaml` v1.4.0 → v1.5.0 — bumped version + description tag («v1.5.0 BUG-012 format directive»). Section «Fallback on empty results» reheaded to reference Session F + v1.5.0; appended 5th bullet: HARD RULE that (a) tags `suggestion` + `available_channel_ids` as HINT FIELDS (not paginated lists), (b) enumerates banned templates verbatim («N из M», «1 из 10», «показано N из M», «первая страница», «page 1 of …»), (c) prescribes format ("comma-separated list" / "short bullet list"), (d) explicitly scopes Pagination semantics section ONLY to `items` field of `list_topics`/`list_channels`/`search_knowledge_base`. Existing v1.4.0 hard rules preserved (BUG-009 confirm guard, BUG-007 suggestion semantics, etc.).

#### Test coverage
- **NEW** `tests/test_rag_prompt_config.py::TestBotPromptBug012FormatDirective` (4 contract tests):
  - `test_bot_yaml_version_at_least_1_5_0` — пин на metadata.version ≥ 1.5.0 (semver tuple comparison; defends against accidental version-rollback in future prompt sweeps).
  - `test_bot_yaml_mentions_bug_012_mitigation` — пин на «BUG-012» tag в system prompt (traceability marker for future readers).
  - `test_bot_yaml_forbids_pagination_phrasing_on_hint_fields` — direct contract: prompt must contain anti-pattern phrasing («N из M» или «1 из 10») AND name BOTH affected fields by their payload-key names («available_channel_ids», «suggestion»).
  - `test_bot_yaml_separates_pagination_scope_from_hint_fields` — pagination-scope-separation contract: prompt must reference `items` as the paginated field AND contain «advisory» or «hint» role marker for the hint fields.

**Verification.**
- 4/4 new tests PASS, `pytest tests/test_rag_prompt_config.py tests/test_bot_fsm.py tests/test_bot_execute_tool_guard.py tests/test_bot_tools_session_f.py` → **219 passed**, 0 regressions (no v1.4.0-pinned tests broken by the bump).
- `ruff check` + `ruff format --check` clean for `prompts/` + `tests/test_rag_prompt_config.py`.

**Why prompt-only is sufficient.** BUG-012 is purely an LLM rendering-template selection error — phrasing is generated AFTER all tool calls return, so no Python-side code-path could intercept it. Structural fix would require Gemini structured-output mode, which is a significantly larger change for a Low-severity cosmetic bug. The 4 pinning tests prevent silent regression on future prompt sweeps (CI guarantees the directive's wording stays).

**Production deploy gate.**
Config-only change (no code, no migrations, no Docker rebuild). Deploy path: `git pull --ff-only origin main && docker exec tg_parser_bot kill -HUP 1` (if hot-reload supported) OR `docker compose up -d --no-deps --force-recreate tg_bot` (full restart, ~5–10s). Smoke: real Telegram bot — «темы канала AgeManagement» (typo) → assert response does NOT contain «1 из» or «из ['» before the suggestion list.

**Out of scope.**
- TD-bot-source-username-alias (BUG-010) — separate session.
- TD-bot-read-context-preservation (BUG-011) — Session H, pre-flight document.
- TD-bot-confirm-coverage-completeness — extend confirm-flow to subscribe_*/register_*/*_user_auth (Session G TD, defer until concrete pain-driven use-case).

### Session G — Server-side `execute_tool` ConfirmFlow guard: BUG-009 structural close (2026-05-02)

**Контекст.** Закрывает структурно BUG-009 — LLM-hallucinated `add_channel(confirm=true)` на suggestion-confirmation reply, ранее mitigated prompt-only (v1.3.0) на Phase B-(b) Session F deploy 2026-04-30. Server-side guard в `execute_tool` отвергает любой write-tool call с `confirm=True` без matching FSM snapshot — закрывает hallucination class независимо от LLM-дисциплины (prompt rules сохраняются как defense-in-depth). Источник: [`docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md). Tracker: GH issue [#49](https://github.com/AlexEfimov/TG_parser/issues/49) (parent BUG: [#45](https://github.com/AlexEfimov/TG_parser/issues/45)).

#### BUG-009 — server-side ConfirmFlow guard
- `tg_parser/bot/tools.py` — added `_WRITE_TOOLS_REQUIRING_CONFIRM: frozenset[str]` (7 tools — `add_channel`, `remove_channel`, `pause_channel`, `resume_channel`, `trigger_pipeline`, `set_llm_config`, `reset_llm_config`; все, чьи Gemini-declarations имеют `confirm: BOOLEAN` parameter — audit pre-flight 2026-05-02). Расширение coverage на `subscribe_*`/`register_*`/`*_user_auth` отложено как **TD-bot-confirm-coverage-completeness** (out of scope, ~400+ LOC; те tools не имеют `confirm` parameter в schema, guard был бы no-op).
- New `ConfirmFlowSnapshot` TypedDict (`tool_name: str`, `args: dict[str, Any]` без `confirm`) — типизированный контракт между handler и `execute_tool`.
- New helper `_check_confirm_flow_match(name, args, confirm_flow_state) -> dict | None` — возвращает typed error payload (`{"error": ..., "error_class": "ConfirmFlowMismatch"}`) если (a) `confirm_flow_state is None`, (b) `tool_name` mismatch, или (c) `args` (modulo confirm) mismatch — с diagnostic diff (`extra=`, `missing=`, `changed=` keys).
- `execute_tool` accepts new optional kwarg `confirm_flow_state: ConfirmFlowSnapshot | None = None`. Guard runs ONLY когда `name in _WRITE_TOOLS_REQUIRING_CONFIRM and args.get("confirm") is True` (read-tools и `confirm=False` previews не затронуты). Match contract — exact `tool_name` + exact `args modulo confirm` (subset matching отвергнут — открывал бы attack vector через injected extra args).
- `tg_parser/bot/handlers.py:_handle_confirmation_response` — единственный legitimate confirm=true call-site, теперь передаёт `confirm_flow_state={"tool_name": tool_name, "args": original_args}` (original args без `confirm`, который handler сам добавляет в payload).
- `tg_parser/bot/agent.py:process_message` — намеренно НЕ передаёт `confirm_flow_state` в `execute_tool`; LLM-issued `confirm=True` через agent loop отвергается → `ConfirmFlowMismatch` payload возвращается LLM в functionResponse → агент может gracefully recover (re-issue preview).
- `prompts/bot.yaml` v1.3.0 → v1.4.0 — bumped version + description («Session G structural guard active»). Added recovery hint в § Confirmation semantics: «Since v1.4.0 a server-side guard structurally rejects LLM-issued confirm=true с error_class=ConfirmFlowMismatch — if you ever receive that error, recover by calling the same tool again with confirm=false». Все existing v1.3.0 hard rules (BUG-009 mitigation HARD RULE, suggestion-confirmation flow, etc.) сохранены.

#### Test coverage
- **NEW** `tests/test_bot_execute_tool_guard.py` (13 тестов в 4 классах):
  - `TestGuardRejectPaths` (5 тестов) — все mismatch flavours: no state, tool name mismatch, args extra keys, args missing keys, args changed value. Все возвращают `error_class="ConfirmFlowMismatch"` с диагностическим error message; sentinel executor never fires.
  - `TestGuardPassPaths` (3 теста) — legitimate paths: matching state + executor runs, read-tools passthrough (guard не применяется), `confirm=False` preview passthrough.
  - `TestGuardEdgeCases` (2 теста) — `UnknownTool` сохраняется (guard runs только для known write-tools), dict-ordering insensitivity (R-2 mitigation).
  - `TestWriteToolsContract` (3 теста) — bidirectional contract per R-1 mitigation: forward (`declared confirm-tools ⊆ guard set`), reverse (`guard set ⊆ declared confirm-tools`), pin baseline (`_WRITE_TOOLS_REQUIRING_CONFIRM == frozenset({...7 tools...})`). Forward direction catches new write-tool added без registering; reverse catches accidental over-trim.
- `tests/test_bot_fsm.py` — 2 новых теста:
  - `TestConfirmationResponseHandler.test_handler_passes_confirm_flow_state_matching_preview` — wiring contract: handler передаёт matching `confirm_flow_state` так что guard let's call through (Stop-the-world condition guard).
  - `TestBug009SuggestionConfirmGuard.test_yes_after_suggestion_does_not_call_add_channel` — direct integration regression на 2026-04-30 15:15:44 UTC trace: mock GeminiAgent issues `add_channel(confirm=True)` через agent loop → guard rejects, executor sentinel never fires, `ConfirmFlowMismatch` payload reaches LLM via functionResponse, agent loop terminates с user-facing text response.
- **R-3 audit** (pre-existing tests passing `confirm=True` to `execute_tool` без `confirm_flow_state`): 22 tests в `tests/test_bot_tools_v11.py` (trigger_pipeline × 4, pause_channel × 3, resume_channel × 3), `tests/test_bot_tools_v12.py` (add_channel × 3, remove_channel × 2, set_llm_config × 4, reset_llm_config × 2), `tests/test_rag_prompt_config.py` (set_llm_config × 2) обновлены — добавлен `confirm_flow_state={"tool_name": ..., "args": ...}` matching args. Тесты целились в executor behavior, не в guard — обновление preserves their original intent.

**Verification.**
- Полный `pytest` (default mode) — **1869 passed** (was 1854 baseline; +15 новых; same 35 DB-related infra failures pre/post — pre-existing, не связаны с BUG-009).
- 0 regressions: 67 existing FSM tests (`tests/test_bot_fsm.py`) + 264 bot+MCP tests (`tests/test_bot_*.py` + `tests/test_mcp_management.py`) — все зелёные.
- `ruff check .` clean; `ruff format --check .` clean (291 files formatted).

**Locked decisions** (per pre-flight 2026-05-02 — не relitigate в Session G implementation):
- **A** — trim `_WRITE_TOOLS_REQUIRING_CONFIRM` до 7 tools (vs B — extend confirm coverage to subscribe_*, register_*, *_user_auth — out of scope; tracked as TD-bot-confirm-coverage-completeness, ~400+ LOC, blow Session G scope).
- **X** — prompt-fix landed как doc-only commit `4214d41` directly on main (mirrors `d322afc` precedent), implementation branch starts from corrected main.

**Production deploy gate.**
Post-merge: synthetic in-container smoke (`docker exec tg_parser_bot python3 -c "import asyncio; from tg_parser.bot.tools import execute_tool; print(asyncio.run(execute_tool('add_channel', {'channel_id': 'X', 'confirm': True})))"` → expected `{"error_class": "ConfirmFlowMismatch", "error": "...without an active..."}`); real Telegram bot smoke («да AgeManagment» after suggestion → `list_topics`, NOT `add_channel`); Session D regression — `Удали канал mind_rise` → preview → «да» → soft-delete works (legitimate path passes guard).

**Out of scope (carried as TD).**
- TD-bot-confirm-coverage-completeness — extend two-phase preview/confirm UX to `subscribe_digest`, `subscribe_watchlist`, `register_user`, `update_user`, `add_user_auth`, `remove_user_auth` (currently не имеют `confirm` param в schema; ~400+ LOC, ~25+ tests).
- TD-bot-source-username-alias (BUG-010 structural), TD-bot-read-context-preservation (BUG-011 Session H), TD-prompt-suggestion-format-clarity (BUG-012 P3) — все остаются в backlog.

### Session F — Read-tool hardening: BUG-003 + BUG-005-B + BUG-007 (2026-04-29)

**Контекст.** Финальная BUG-fix-сессия 2026-04-26..29 волны: закрывает три read-side баги одним батчем (общие touch-points `tg_parser/bot/tools.py`, `tg_parser/mcp_server.py`, `prompts/bot.yaml`). Источник: [`docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md`](docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md). Storage-side LIKE→JSONB переход для BUG-007 deferred per gating decision D-5 в TD-storage-jsonb-channel-id.

#### BUG-003 — `@`-prefix asymmetry: read-tool'ы теперь нормализуют `channel_id`
- **NEW** `tg_parser/utils/channel_id.py` — модуль с одним публичным helper'ом `normalize_channel_id(value: str | None) -> str | None`. Стрипает (а) окружающие пробелы, (б) одну пару matching `'`/`"` quotes (mismatched сохраняются для upstream-флага), (в) leading `@`, (г) финальные пробелы (на случай если quote-strip обнажил padding). Идемпотентен; возвращает `None` для пустых / `None` / `"@"` входов. Single source of truth — без cyclic-import риска для `services/`/`mcp_server.py`/`cli/`.
- `tg_parser/bot/tools.py` — все 8 read-tool executor'ов (`_exec_ask_question`, `_exec_search`, `_exec_list_topics`, `_exec_get_topic_details`, `_exec_list_channels` filter-args, `_exec_get_document` (`source_ref`-only), `_exec_get_related_topics`, `_exec_get_cross_channel_stats`) теперь нормализуют `channel_id` через helper. Все existing 14 `lstrip("@")` call-sites (write/scheduler/M2 guard) consolidated через тот же helper.
- `tg_parser/mcp_server.py` — symmetric MCP-fix: 9 occurrences `channel_id.lstrip("@")` → `normalize_channel_id(channel_id)` (`add_channel`, `pause_channel`, `resume_channel`, `remove_channel`, `trigger_pipeline`, `get_pipeline_status`, `export_channel`, `subscribe_digest` list-comp, `subscribe_watchlist` list-comp). Read-tool'ы (`search_knowledge_base`, `ask_question`, `list_topics`, `get_cross_channel_stats`) тоже нормализуют.
- `tg_parser/services/{scheduler,watchlist,pipeline}_service.py`, `tg_parser/cli/watchlist_cmd.py`, `tg_parser/ingestion/telegram/telethon_client.py`, `scripts/add_test_messages.py` — переключены на shared helper. Acceptance grep `rg "lstrip..@.." tg_parser/ scripts/` возвращает **только** строку `tg_parser/utils/channel_id.py:54` (helper body). Закрывает F-7 consolidation criterion.
- **F-8 quote-strip** (regression на 2026-04-29 production observation `Удали канал 'test_channel'` — bot получил literal quoted string → `total=0`): helper стрипает enclosing `'`/`"` pair после initial whitespace strip и до lstrip(`@`); mismatched quotes сохраняются.

#### BUG-007 — suggestion-emit при `total=0`
- `tg_parser/bot/tools.py:_build_no_results_suggestion` — новый helper для bot-side. Возвращает `{available_channel_ids: list[str] (top-10 RBAC-filtered), suggestion: str | None}`. Поиск близкого matching через `difflib.get_close_matches(cutoff=0.7, n=1)`; suggestion-формат `"Возможно, имелся в виду 'X'? (вы запросили 'Y')"`. Свопит implicit failure («не нашёл тем») на actionable hint про typo.
- Wired в `_exec_list_topics`, `_exec_search`, `_exec_get_cross_channel_stats` — payload extends с `available_channel_ids` + `suggestion` ровно когда (а) запрошен specific `channel_id` и (б) `total=0` / `count=0` / `error="Channel not found"`. Errors swallowed (advisory path) — suggestion никогда не маскирует реальный «нет результатов» ответ.
- `tg_parser/mcp_server.py:_build_no_results_suggestion_mcp` — symmetric MCP-side. `TopicListResult` Pydantic model расширен optional полями `available_channel_ids: list[str] | None = None`, `suggestion: str | None = None` (backward compat для existing MCP клиентов; новые поля не появляются на happy-path).
- `prompts/bot.yaml` v1.2.0 — appended секция «Fallback на пустом результате» учит LLM (a) цитировать `suggestion` верба­тим, (b) показывать 3-5 examples из `available_channel_ids`, (c) не говорить «канал не существует» если список доступных непуст.

#### BUG-005-B — typed catch в `execute_tool` (recovery от BUG-005-A class errors)
- `tg_parser/bot/tools.py:execute_tool` — generic `except Exception:` ветка теперь сохраняет `error_class: str` (e.g. `"ValueError"`, `"AnthropicAPIError"`, `"RuntimeError"`) и truncated `error: str` (cap 500 chars) в payload вместо генерализации до «Tool failed with an internal error». Дополнительно: `TimeoutError`, `PermissionError`, `ValueError`, `KeyError` — отдельные ветки с typed `error_class` (не валятся в generic). `Unknown tool` ветка добавляет `error_class: "UnknownTool"`.
- `prompts/bot.yaml` v1.2.0 — appended «Error classification» секция: учит Gemini-агент использовать `error_class` для специфичных ответов (`TimeoutError` → «запрос занял слишком много времени»; `PermissionError` → «нет доступа»; другое → парафраз `error` на русский). Generic «внутренняя ошибка» допускается ТОЛЬКО когда ни `error_class`, ни `error` не указывают на конкретную причину.

#### Test coverage
- **NEW** `tests/test_utils_channel_id.py` (33 теста в `TestNormalizeChannelId`): @ prefix, single/double quotes, mismatched quotes, whitespace (incl. tab/newline), None/empty, idempotency (parametrized × 8 + 4 extra production-shape variants), case preservation, multi-`@`, internal `@`, non-string coercion, only-one-pair quote-peel, triple-`@`, **inner-padding-around-@ regression** (self-review-found bug — see Verification). **Direct regression** на 2026-04-29 production observation (`'test_channel'`).
- **NEW** `tests/test_bot_tools_session_f.py` (47 тестов в 5 классах):
  - `TestBug003ReadToolNormalization` (3 теста + 6 параметризованных на `_exec_list_topics` + 5 параметризованных на `_exec_ask_question` — оригинальный production-симптом BUG-003) — `@`/quotes/whitespace дают canonical storage call.
  - `TestF9ProductionScenarios` (12 параметризованных: 4 × `_exec_remove_channel` + 4 × `_exec_pause_channel` + 4 × `_exec_add_channel preview`) — все 4 input-варианта (`@test_channel`, `test_channel`, `'test_channel'`, `"@test_channel"`) reach storage с одинаковым canonical ID. Direct production trace из BUG_LOG § BUG-006 Update.
  - `TestBug007SuggestionPayload` (10 тестов) — close-match suggestion + far-input no suggestion + RBAC filter (`allowed_channel_ids`) + cap-at-10 + exact-match no suggestion + empty-DB + `_exec_list_topics` empty appends + happy path не emit'ит + `_exec_search` empty appends + **DB-error swallowing contract** (advisory path) + end-to-end suggestion-helper-error survival.
  - `TestBug005BTypedCatch` (10 тестов) — `ValueError`/`KeyError`/`PermissionError`/`RuntimeError` (BUG-005-A regression) preserved; long-message truncation cap=500; `TimeoutError`; `UnknownTool` typed; **happy path не получает `error_class`** (anti-false-positive contract); `ValueError()` empty-message fallback; `RuntimeError` через generic catch.
  - `TestSearchPayloadShape` (1 тест) — happy path не emit'ит optional поля.
- `tests/test_mcp_server.py` (18 новых тестов в `TestSessionFMcpReadHardening`): параметризованные `search_knowledge_base` / `ask_question` / `list_topics` / `get_cross_channel_stats` на 4-5 input-вариантов — все нормализуют до `"Lab4health"`; `list_topics` emit'ит `available_channel_ids` + `suggestion` на typo `"AgeManagement"`; happy path/no-channel — optional поля `None`; `get_cross_channel_stats` None-passthrough.

**Verification.**
- Полный `pytest` (default mode) — **1975 passed, 162 skipped, 1 deselected** (baseline 1877 → +98 новых; 0 регрессий).
- Полный sweep с PostgreSQL + testcontainers + integration gates (`TEST_POSTGRES=1 TEST_TESTCONTAINERS=1 OPENAI_API_KEY -m ""`) — **2138 passed, 0 skipped, 0 deselected** (всё, что can run на dev-машине, runs зелёным).
- `ruff check` clean; `ruff format --check` clean.
- Acceptance grep `rg "lstrip..@.." tg_parser/ scripts/` → 1 match (`tg_parser/utils/channel_id.py:55`, helper body) — F-7 consolidation criterion закрыт.
- **Self-review нашёл 1 production bug** (зафиксен в C1): `normalize_channel_id` не идемпотентен на `' @ch '` — старый порядок (peel-quote → lstrip(@) → strip) оставлял `@` в результате потому что `.lstrip("@")` видел leading space (revealed by quote-peel), не `@`, и bail'ился. Direct re-introduction BUG-003 в quoted-disguise варианте. Fix: `.strip()` сразу после quote-peel чтобы `@` стал leading char до lstrip. Dedicated regression test `test_padding_around_at_inside_quotes`.

**Production deploy gate.**
24h watch metric `tg_bot_gemini_empty_parts_total` (Session E) активен до **2026-04-30 11:49 UTC** — VPS deploy откладывается до closure metric'а для confound-free данных по BUG-006 (исключаем confound при regression-расследовании, если bot-side metric внезапно spike'нет от изменений в `execute_tool`). PR может merge'нуться в main раньше; deploy на VPS — после closure.

**Out of scope (carried as TD).**
- TD-storage-jsonb-channel-id — `LIKE '%"channel_id"%'` → JSONB `?` оператор / `jsonb_path_exists` для `topic_card_repo.list_by_channel`, `topic_bundle_repo.list_by_channel`. Affects миграции, требует отдельного review (D-5 default).
- TD-data-quality-AgeManagment — проверить нужен ли rename канала (если это typo, не реальный username).
- TD-data-quality-test_channel-orphan — pre-existing `test_channel (0 docs)` в БД (создан до landing M2); soft-delete через bot или SQL.
- TD-bot-intent-router (Option B Session E carry-forward), TD-bot-nightly-health-check, BUG-008 diagnostic spike — все остаются в backlog.

### Session F — Production deploy + BUG-009 mitigation hotfix (2026-04-30)

**Контекст.** Production deploy of Session F closure (squash SHA [`88e4337`](https://github.com/AlexEfimov/TG_parser/commit/88e4337)) onto VPS `mcp.tgp.efimov.mobi` 2026-04-30 15:07–15:12 UTC, plus two post-deploy hotfixes for issues discovered during live smoke (Phase B-(a) data-side, Phase B-(b) prompt-side). Source: [`docs/notes/DEPLOY_CHECKLIST_SESSION_F_2026-04-30.md`](docs/notes/DEPLOY_CHECKLIST_SESSION_F_2026-04-30.md) — § Actual deploy log section captures the full 15:07–16:01 UTC execution timeline.

#### Phase 0 — Watch closure (BUG-006 / Session E gate)
- **Pass criterion via alternative observability path** (TD-bot-prometheus-scrape filed): in-process `prometheus_client.REGISTRY` introspection inside `tg_parser_bot` container + `docker logs --since 27h tg_parser_bot | grep "gemini_empty\|gemini_no_candidates\|gemini_blocked"` returned **0 events** for the entire 27h window since Session E deploy. Equivalent confidence to Prometheus query (no scrape job exists for `tg_bot` — TD).

#### Phase 2 — Deploy (15:07–15:12 UTC)
- `git pull --ff-only origin main` advances VPS to `88e4337`.
- `docker compose build tg_parser` (cache-hit для unchanged Python layers, recompile только `prompts/bot.yaml` + `tg_parser/{bot/tools.py,mcp_server.py,utils/channel_id.py,utils/__init__.py}`).
- `docker compose up -d --no-deps --force-recreate tg_parser mcp tg_bot` — все 3 контейнера healthy за ≤30 sec.

#### Phase 3 — Live smoke
- **F-1 PASS** (BUG-003 production trigger closed): `темы канала @AgeManagment` (с @-prefix) → 75 тем returned.
- **F-3 PASS** (BUG-007 production trigger closed): `темы канала AgeManagement` (typo) → bot suggested `AgeManagment` + 6 channels listed.
- **F-2 PASS** (BUG-005-B closed): synthetic typed-catch test через `docker exec tg_parser_bot python3 -c '...'` — `KeyError`/`TimeoutError` payload shape с `error_class` + cap-500 truncated `error`.
- **F-9 deferred** (BUG-010 surfaced): orphan placeholder `test_channel` from Session B+ M2 testing 2.5 days predates Session F (created 2026-04-27 19:59 UTC, NOT a regression).

#### Side-effects discovered & filed during smoke
- **BUG-009 (High)** — Bot Gemini hallucinates `add_channel(confirm=true)` on suggestion-confirmation reply (LLM context-loss, sibling of BUG-002 root-cause-class but distinct manifestation). Mitigated via Phase B-(b).
- **BUG-010 (Medium)** — `IngestionStateRepo.get_source` (PK-only) vs `list_sources` (returns username) UX mismatch surfaces orphan placeholders as «not found». Data-side cleaned via Phase B-(a); structural fix deferred (TD-bot-source-username-alias).
- **BUG-011 (Medium)** — Read-context loss multi-turn: «покажи 5 главных тем» after channel-scoped query returns global top-5 instead of channel-scoped. Same root-cause-class as BUG-002 but read-side. Deferred to Session H (TD-bot-read-context-preservation).
- **BUG-012 (Low)** — Cosmetic LLM phrasing «темы 1 из ['AgeManagment']» format-bleed in BUG-007 fallback. Deferred (TD-prompt-suggestion-format-clarity, P3).

#### Phase B-(a) — Data-side hotfix (15:35 UTC, no rebuild)
- One-shot SQL transaction inside `tg_parser_postgres`: `BEGIN; UPDATE sources SET deleted_at=NOW(), updated_at=NOW() WHERE source_id='-1002123123123'; COMMIT;` — soft-deleted orphan `test_channel` per Session B+ M3 reversible contract. Pre-state had 7 active sources (6 owned + 1 orphan); post-state has 6 (orphan correctly hidden).
- F-9 re-smoke skipped — Phase 2.6 module-import test + F-1/F-3 live smoke already verify normalization at code level (re-running F-9 with orphan removed tests the same code path on a different DB row, no marginal value).

#### Phase B-(b) — Prompt-side hotfix for BUG-009 (15:55–15:59:41 UTC, prompt-only — bind-mount, no rebuild)
- `prompts/bot.yaml` bumped 1.2.0 → 1.3.0 on VPS (file is bind-mounted into container, no image rebuild needed).
- 3 changes: (1) `Instructions` block — strengthened «do NOT call confirm=true» to «**NEVER** call any write tool with confirm=true yourself (HARD RULE; bypassing triggers BUG-009)»; (2) `Confirmation semantics` — added standalone HARD RULE bullet restating same invariant with explicit BUG-009 reference; (3) `Confirmation semantics` — added new bullet covering Suggestion-confirmation flow: «da X»-after-suggestion → re-run THE SAME read-tool with `channel_id=X`, NOT a write-tool.
- `docker compose restart tg_bot` reloaded prompt at 15:59:41 UTC, healthy by 12 sec.

#### Sanity check (16:01 UTC) — both PASS
- **F-1 BUG-002 confirm-flow regression guard** (Session D FSM scaffolding intact): `Удали канал mind_rise` → preview → user «нет» → `Действие отменено` (FSM correctly cancels, no LLM hallucination).
- **BUG-009 mitigation guard:** typo `AgeManagement` → suggestion → user «да AgeManagment» → bot calls `list_topics(channel_id="AgeManagment")` (NOT `add_channel`).

**Verification.** Production state at end of session: 6 active channels, 3 containers healthy, prompt v1.3.0 live (committed via this CHANGELOG entry's accompanying squash). BUG-003/005-B/007 closure proofs collected from real conversation traces.

**Carried forward.**
- BUG-009 structural fix → **TD-bot-execute-tool-confirm-guard** (Session G; estimate 1.5–2 ч, server-side guard в `execute_tool` rejecting `confirm=true` without matching `ConfirmFlow.awaiting_confirmation` FSM state).
- BUG-010 structural fix → **TD-bot-source-username-alias** (add `get_source_by_username` method + integration test via testcontainers).
- BUG-011 structural fix → **TD-bot-read-context-preservation** (Session H; FSM-based read-context for multi-turn).
- BUG-012 prompt polish → **TD-prompt-suggestion-format-clarity** (P3).
- TD-bot-prometheus-scrape (next deploy uses 0.1 path directly).

### Session E — BUG-006 bot Gemini-flash empty `parts` (Critical fix, 2026-04-29)

**Контекст.** Закрывает Critical-баг **BUG-006** — `gemini-2.5-flash` возвращал HTTP 200 с пустым `candidates[].content.parts=[]` на сложных tool-disambiguation запросах (например, «Покажи LLM конфиг»), а `agent.process_message` нормализовал это в generic «Не удалось получить ответ от LLM» без диагностики и без метрики. Источник: [`docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md`](docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md) + [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) § BUG-006 (детерминизм HG-2 подтверждён 2026-04-26 23:51 контрольной B1-проверкой).

**Spike-blocker.** Live research-spike (`tools/spike_bug_006.py`) был геоблокирован в этой среде разработки — Google Generative Language API возвращал HTTP 400 `"User location is not supported for the API use."` на любой запрос. Spike-script сохранён в репозитории (working, ready to run with VPS-side execution); решение об опции принято на детерминированной HG-2 диагностике из BUG_LOG. Empty-parts classification + Prometheus-метрика дают эмпирический сигнал post-deploy для проверки достаточности fix'а.

#### Fix Option A + thinkingBudget=0 (BUG_LOG hotfix)
- `tg_parser/config/settings.py` — две новые конфигурируемые настройки: `bot_gemini_max_output_tokens` (default `8192`, ge=512, le=65536; bumped from SDK default 4096) и `bot_gemini_thinking_budget` (default `0`; `None` отключает `thinkingConfig`, положительные целые задают cap thinking-токенов). Гайдлайн HG-2: thinking-токены 2.5-flash siphon'ятся из того же `maxOutputTokens`-budget'а, и 30+ TOOL_DECLARATIONS детерминистично выбивали 4096 на «Покажи LLM конфиг»-классе запросов.
- `tg_parser/bot/agent.py:GeminiAgent.__init__` — принимает `max_output_tokens` и `thinking_budget`; defaults совпадают с Settings'ами (8192 / 0). `_call_gemini` теперь шаблонит `generationConfig.thinkingConfig.thinkingBudget` ровно когда `thinking_budget is not None` (sentinel-конвенция для не-2.5 моделей где поле игнорируется).
- `tg_parser/bot/main.py` — пробрасывает оба новых параметра в `GeminiAgent` factory-call.

#### Empty-parts classification (operator + user diagnostics)
- `tg_parser/bot/agent.py:process_message` — три ветки `parts=[]`/`candidates=[]`/`promptFeedback.blockReason` теперь различают по `finishReason` и эмитят specific user-facing сообщение:
  - `MAX_TOKENS` → «LLM исчерпал бюджет ответа на этот запрос. Попробуйте упростить вопрос или разбейте на части.»
  - `RECITATION` → «LLM отказался ответить (recitation guard). Попробуйте переформулировать.»
  - `MALFORMED_FUNCTION_CALL` → «LLM сформировал некорректный вызов инструмента. Попробуйте переформулировать запрос.»
  - `SAFETY` (как в `finishReason`, так и в `promptFeedback.blockReason`) → «Ответ был заблокирован фильтрами безопасности LLM.»
  - `OTHER` / unknown / empty `finishReason` → generic «LLM вернул пустой ответ. Возможно, сейчас перегрузка — попробуйте через минуту.»
  - `candidates=[]` без `blockReason` → «LLM не вернул ни одного кандидата ответа. Попробуйте позже.»
- Все эти ветки логируют payload-dump (truncated to 2048 chars per gating decision E-3), `finishReason`, `usageMetadata`, `model`, `tool_count` через structlog `logger.error("gemini_empty_parts" | "gemini_no_candidates")`.
- DEBUG-лог `gemini_response` теперь дополнительно включает `thoughts_tokens` (HG-2 confirmation signal — было только `promptTokenCount`/`candidatesTokenCount`).

#### Telemetry — Prometheus monitoring for BUG-006 follow-up
- `tg_parser/api/metrics.py` — новый Counter `tg_bot_gemini_empty_parts_total{model, finish_reason}` плюс helper `record_bot_gemini_empty_parts(*, model, finish_reason)`. Label set bounded: `finish_reason ∈ {STOP, MAX_TOKENS, MALFORMED_FUNCTION_CALL, RECITATION, SAFETY, OTHER, none, no_candidates, blocked, FUTURE_*}`. Empty/unknown нормализуются к `"none"` чтобы лейблсет оставался ограничен.
- Метрика инкрементится из всех empty-parts/no-candidates/blocked путей `agent.process_message`. Post-deploy: при rate >1% от total bot-Gemini-calls — operator знает, что Option A недостаточно и нужно следовать к Option B (split TOOL_DECLARATIONS) или Option C (model swap).

#### Research-spike script (deferred execution)
- `tools/spike_bug_006.py` — production-ready spike runner для Q1-Q5 reproducible queries × 7 опций (current / a / a-thinking-0 / thinking-0 / b / c-pro / c-flash-2-0). Загружает `GEMINI_API_KEY` из `.env`, `TOOL_DECLARATIONS` из реального бота, system prompt из `prompts/bot.yaml`. Per-option JSONL traces + `summary.json` с success-rate / finish-reason histogram / avg latency / avg thoughts-tokens. Запуск: `.venv/bin/python tools/spike_bug_006.py --option all --runs 2`. Cost ≈ $0.05-0.20 на flash-моделях. **NB:** в текущей dev-среде live execution заблокирован геополитикой Gemini API; запускать с VPS, где бот действительно работает.

#### Test coverage — BUG-006 closure
- `tests/test_bot_agent.py` (новый файл, 14 тестов в 5 классах) — closure для CI blind-spot из BUG_LOG § «Why CI didn't catch» (предыдущие unit-тесты мокали валидный response, не было ни одного теста на `parts=[]`/`candidates=[]`):
  - `TestGenerationConfigWiring` (3 теста) — defaults шлют `thinkingBudget=0` + `maxOutputTokens=8192`; `thinking_budget=None` sentinel **омитит** `thinkingConfig` целиком (preserves SDK default for non-2.5 models); custom `max_output_tokens` пробрасывается.
  - `TestEmptyPartsClassification` (6 тестов) — параметризация на каждый `finishReason` (`MAX_TOKENS`/`RECITATION`/`MALFORMED_FUNCTION_CALL`/`SAFETY`/empty/`FUTURE_REASON`): user-facing message specific, metric counter advanced ровно на 1 на правильной (model, finish_reason)-cell.
  - `TestNoCandidatesBranches` (2 теста) — `promptFeedback.blockReason=SAFETY` → «безопасности» message + `blocked` метрика; genuine empty (no `blockReason`) → «ни одного кандидата» + `no_candidates` метрика. Guard на pre-fix string «Не удалось получить ответ от LLM» — не должна появляться post-fix.
  - `TestHappyPathUnchanged` (1 тест) — text-response paths не инкрементят empty-parts counter (no false positives).
  - `TestBug006Regression` (2 теста) — direct regression на оригинальный «Покажи LLM конфиг» trace: payload carries `thinkingBudget=0`, response message specific, не равно pre-fix string.

**Verification.**
- Полный `pytest` — **1877 passed, 162 skipped, 1 deselected, 13 warnings** (baseline 1863 → +14 новых BUG-006 тестов; 0 регрессий, 67 BUG-002/004 FSM-тестов остаются зелёными).
- Ruff lint clean (см. `ReadLints` на каждом изменённом файле).
- Live smoke (Q1-Q5 на dev-bot) **deferred** до post-merge deploy на VPS — spike-blocker (геополитика API) не позволяет проверить из dev-среды; после deploy 24h-watch на `tg_bot_gemini_empty_parts_total` должен показать ≤1% от total bot-Gemini-calls.

**Operator notes.**
- Production env update: добавьте в `.env` (или ENV-конфиг VPS):
  ```
  BOT_GEMINI_MAX_OUTPUT_TOKENS=8192
  BOT_GEMINI_THINKING_BUDGET=0
  ```
  (defaults в коде совпадают с этими значениями — переопределение не требуется, но явный config упрощает ad-hoc tuning без redeploy.)
- Post-deploy monitoring: `curl localhost:9090/metrics | grep tg_bot_gemini_empty_parts_total` (если Prometheus surface включён) или из Grafana dashboard'а. Ожидаемый baseline после fix'а — околонулевое значение на `MAX_TOKENS`/`MALFORMED_FUNCTION_CALL`-cells (HG-2 закрыт thinkingBudget=0). Если cell `MAX_TOKENS` накапливается даже при `thinkingBudget=0` — это новый класс багов (HG-4 tool-deck overflow без thinking) и сигнал к Option B follow-up.
- `BOT_GEMINI_MODEL=gemini-2.5-pro` доступен как ad-hoc switch без code-change'ев (Option C-Gemini fallback) — при ухудшении ситуации можно временно смержить через ENV до полного follow-up sprint'а.

**Carried over.**
- TD: Option B (split TOOL_DECLARATIONS via intent classification) — реализация отложена до пост-deploy данных от метрики; spike-script готов как baseline.
- TD: nightly health-check job — синтетический «Покажи LLM конфиг» каждый час против реального API + alert при empty-parts spike (см. BUG_LOG § «Why CI didn't catch» #3).

### Session D — BUG-002 + BUG-004 bot FSM (root-cause fix, 2026-04-28)

**Контекст.** Замыкает root cause'ы **BUG-002** (statelessness агента бота → constructive/destructive hallucination на yes-confirm) и **BUG-004** (statelessness pagination → потеря channel-context на «ещё», обнуление нумерации). До этого PR'а bot работал stateless: на user'овский «да» в turn 2 LLM получала bare reply без conversation-state'а и hallucinated любой write-tool — production trace 28.04 00:04 показал constructive sub-form (`add_channel(test_channel_123)` после `remove_channel` preview), который к тому же byp ass'ил M2 reject-list через суффиксированный placeholder. Pagination была сломана аналогично — «ещё» возвращала «все темы по KB» вместо следующей страницы исходного канала. Source: [`docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md`](docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md) + [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) § BUG-002 (incl. update 2026-04-28 00:04) и § BUG-004.

#### Architecture — aiogram FSM scaffolding
- `tg_parser/bot/main.py` — `Dispatcher(storage=MemoryStorage())` (D-4 default; Redis отложен до scale-out).
- `tg_parser/bot/states.py` (новый) — два `StatesGroup`: `ConfirmFlow.awaiting_confirmation` (pending write-tool preview) и `PaginationFlow.has_active_list` (last list-tool returned `has_more=True`).

#### BUG-002 — deterministic confirm-execute
- `tg_parser/bot/agent.py` — `process_message` теперь возвращает `AgentResult` (`response_text` + `preview_pending` + `pagination_pending`) вместо `str`. Agent loop captures hints из tool payload'а (`preview=True` → `preview_pending = {tool_name, args}`; LLM-self-confirm в том же loop'е чистит hint). `tool_args` теперь логируются на INFO level — single-line forensics, который сразу бы поймал 28.04 трейс.
- `tg_parser/bot/handlers.py:handle_text` — FSM-aware: при entry проверяет `ConfirmFlow.awaiting_confirmation` и роутит к `_handle_confirmation_response` **до** обращения к LLM. После agent-call'а при `result.preview_pending` set'ит state с TTL 5 минут (D-3 default).
- `tg_parser/bot/handlers.py:_handle_confirmation_response` — yes/no detection через regex (`CONFIRM_PATTERN` / `REJECT_PATTERN`, anchored, IGNORECASE, word-boundary aware). На yes — **детерминированный** `execute_tool(name, {**original_args, "confirm": True})`; LLM не консультируется. На no — `state.clear()` + «Отменено». На non-match — D-4 default: `state.clear()` + recursive `handle_text` в режиме fresh agent request. TTL expiry → `state.clear()` + сообщение об истечении.
- `tg_parser/bot/handlers.py:_format_tool_result` — детерминированный рендер result'а после confirm-execute (использует `result["message"]` если есть, fallback на error/success generic).

#### BUG-004 — stateful pagination + global numbering
- `tg_parser/bot/tools.py:_exec_list_topics` — каждый item теперь штампуется глобальным 1-based `n` (`offset + idx + 1`); при `has_more=True` payload включает `pagination_pending = {tool_name, args, total, offset, limit}` где `args` несёт исходный channel-/topic_type-фильтр **без изменений** и advanced `offset`.
- `tg_parser/bot/handlers.py:handle_text` — при `result.pagination_pending` set'ит `PaginationFlow.has_active_list` со stash'ем pagination payload'а + `items_shown` для soft-cap.
- `tg_parser/bot/handlers.py:_handle_pagination_response` — на «ещё/далее/next/more/продолжай» (`NEXT_PAGE_PATTERN`) деterministic'но replay'ит stashed query через `execute_tool(name, args)` — channel context structurally сохраняется. На «стоп/cancel» — `state.clear()`. На non-match — D-4 default. На terminal page (`has_more=False`) — `state.clear()`. Soft-cap `PAGINATION_SOFT_CAP=10` (D-6) — после 10-го item к footer'у дописывается warning, state preserved.
- `tg_parser/bot/handlers.py:_format_paginated_list` — детерминированный рендер второй и последующих страниц **без LLM** (использует `n` для нумерации, footer «Показано N–M из K»).
- Препочтительность hints: `preview_pending` побеждает `pagination_pending` если оба set в одном response (write-op safety > UX).

#### Prompt updates — `prompts/bot.yaml` v1.1.0
- Новая секция «Confirmation semantics»: LLM объясняется, что её роль — **только** preview + просьба подтвердить; bot framework сам выполнит confirm=true, LLM не должна делать второй tool-call. Явный counter-instruction про reserved placeholder channel_ids (`test_channel`/`example_channel`/`my_channel`/`default_channel` + suffixed varианты) — direct guard на constructive-op hallucination class из 28.04 трейса.
- Новая секция «Pagination and numbering»: использовать `n` для нумерации (continues across pages, never restarts at 1), оформлять continuation как «Скажите «ещё» / «стоп»», **не** делать самостоятельный list_topics на следующем turn'е (handler перехватит).
- Новая секция «Soft-delete semantics (M3)»: `remove_channel` — soft-delete (ingestion stops, raw/processed/topics/embeddings preserved, restorable via `add_channel`). Замена IRREVERSIBLE/«permanently deletes ALL data» wording'а на «помечен как удалённый — данные сохранены»; ban на misleading фразы.
- Capability item 12: «Remove a channel and all its data — IRREVERSIBLE» → «Remove a channel from active ingestion — soft-delete».

#### Test coverage
- `tests/test_bot_fsm.py` (новый, 67 тестов в 9 классах) — полная regression-сетка:
  - `TestConfirmRejectPatterns` / `TestNextPagePattern` (32 параметризованных) — anchored regex matrix включая false-positive guards для «дайте каналы» / «yesno» / «покажи каналы».
  - `TestProcessMessageReturnsAgentResult` — `AgentResult` contract: preview hint capture, drop при LLM-self-confirm, strip `confirm` field из stashed args.
  - `TestConfirmationResponseHandler` — deterministic yes-execute c `confirm=True`; **`test_yes_after_remove_preview_does_not_call_add_channel`** — direct regression на 28.04 00:04 трейс (bare «да» инвокит ровно `remove_channel` и никогда `add_channel`); no-clears-state, unrelated-text-routes-to-agent, TTL expiry.
  - `TestListTopicsPagination` — `pagination_pending` payload contract: channel filter intact, offset advanced, terminal page omits hint, args strip-then-advance корректно.
  - `TestFormatPaginatedList` / `TestPaginationFlowHandler` — global numbering, deterministic replay, terminal-page state.clear(), soft-cap warning при cumulative > 10.
  - `TestHandleTextSetsConfirmFlow` / `TestHandleTextSetsPaginationFlow` — handle_text arms FSM correctly + preview takes precedence over pagination.

#### Production cleanup (28.04 11:29 UTC+4)
- Soft-deleted orphan placeholder `test_channel_123` через прямой SQL `UPDATE sources SET deleted_at=NOW()` на VPS (M3 семантика, reversible через `add_channel`). Запись была создана 28.04 00:04 hallucination'ом, оставалась в `sources` со status='error' до cleanup'а. Через MCP `remove_channel` cleanup сделать не удалось — remote MCP endpoint висел ~3.5ч без response (заведено TD на расследование).

**Verification.**
- Полный `pytest` — **1863 passed, 162 skipped, 1 deselected, 13 warnings** (baseline 1796 → +67 новых FSM-тестов; 0 регрессий).
- Smoke на pattern matrix: 13/13 confirm vocab, 9/9 reject vocab, 9/9 next vocab, 0 false positives на normal requests.
- `prompts/bot.yaml` v1.1.0 загружается; «Confirmation semantics», «Pagination and numbering», «Soft-delete semantics» секции присутствуют; «IRREVERSIBLE» отсутствует (кроме контекста «Do NOT use ...»).
- Ruff lint clean (см. `ReadLints` на каждом коммите).

**Security/UX advisory.** До этого PR'а: любой пользователь, который сказал «да» после write-preview, получал нестабильный outcome — Gemini теряла conversation state и могла hallucinate constructive (`add_channel(test_channel_*)`) либо destructive (`remove_channel(@unrelated_channel)`) write-call. M1+M2+M3 mitigations снижали blast-radius (test_channel rejected, soft-delete preserved data), но constructive hallucination через суффиксированные placeholder'ы (`test_channel_123`) бypass'ил M2 (exact-match reject-list). Session D закрывает root cause architecturally — на confirm-turn LLM просто не вызывается. Pagination был cosmetic-bug, но создавал false-impression о scope ответа («все темы по KB» вместо «следующая страница genotek»).

#### Carried over
- TD: расследование MCP remote endpoint hang 28.04 11:18 UTC+4 (`list_channels` через MCP не вернул response за ~3.5ч; fallback на прямой SQL отработал).

### Session C — BUG-001 MCP auth identity extraction (Critical security fix, 2026-04-28)

**Контекст.** Critical security-fix sprint, который закрывает root cause
**BUG-001**: до этого PR'а MCP-сервер с `MCP_AUTH_ENABLED=true` silently
аутентифицировал **все** запросы (с любым bearer-токеном или без него)
как синтетического админа `00000000-0000-0000-0000-000000000000`, потому
что каждый tool-handler читал identity из `ctx.client_id` (т.е. из
JSON-RPC `params._meta.client_id` — client-supplied / attacker-controlled
поля), а не из реальной OAuth/Bearer контекстной переменной SDK. Sprint
также закрывает BUG-001b — silent-skip token-verifier'а при
`MCP_AUTH_ENABLED=true && MCP_AUTH_TOKENS={}` (factory cabinetry). Source
of truth: [`docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md`](docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md)
+ [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) § BUG-001 + BUG-001b.

#### Critical security fix — identity extraction
- `tg_parser/mcp_server.py` — новый helper `_extract_authenticated_user_id(ctx)` (синхронный) читает реальный `client_id` из `mcp.server.auth.middleware.auth_context.get_access_token()` (контекст-переменная, заполняемая `AuthContextMiddleware` из ASGI `scope["user"]: AuthenticatedUser` после успешного `BearerAuthBackend.authenticate`). Helper **явно НЕ читает** `ctx.client_id` — это property возвращает `request_context.meta.client_id` (JSON-RPC `params._meta`, attacker-controlled). Docstring и regression-тест на attacker-supplied `_meta.client_id`.
- `tg_parser/mcp_server.py:resolve_mcp_user` — fail-loud в production-режиме. При `mcp_auth_enabled=True` И отсутствии identity (`client_id is None`) теперь **бросает `PermissionError`** с явной отсылкой на BUG-001. Default-admin fallback оставлен только для dev-режима (`mcp_auth_enabled=False` — stdio, локальная разработка). Static-mapping fallback (`MCP_AUTH_TOKENS` legacy) сохранён для известных client_name'ов через DB-lookup miss → admin path.
- `tg_parser/mcp_server.py` — все 35 call-site'ов tool-handler'ов (`user = await resolve_mcp_user(ctx.client_id if ctx else None)` плюс 1 вариант `_user = ...`) переписаны на двухшаговый pattern `user = await resolve_mcp_user(_extract_authenticated_user_id(ctx))`. Verification: `rg "ctx\.client_id" tg_parser/mcp_server.py` возвращает только docstring-упоминание (line 222).
- `tg_parser/mcp_server.py` — структурное логирование auth-decision'ов (`mcp.auth.identity_missing` warning при fail-loud, `mcp.auth.identity_resolved` debug при успешном DB-resolve, `mcp.auth.static_fallback_used` info при legacy static-mapping path, `mcp.auth.identity_dev_fallback` debug в dev-режиме). Без PII (только UUID-форма user_id).

#### BUG-001b — factory cabinetry fail-loud
- `tg_parser/mcp_server.py:create_mcp_server` — старая логика `if settings.mcp_auth_enabled and settings.mcp_auth_tokens:` (silent-skip token-verifier'а при пустом dict, что приводило к anonymous-→-admin fallback'у на все запросы) заменена на explicit `if settings.mcp_auth_enabled:` с **`raise RuntimeError`** при пустом `mcp_auth_tokens`. Сервер теперь не запускается с inconsistent config'ом — оператор видит ошибку немедленно вместо silent admin-bypass'а.

#### Test coverage — closure CI blind-spot
- `tests/test_f4_auth_resolution.py:TestExtractAuthenticatedUserId` (новый класс, 5 unit-тестов) — happy-path extraction из `auth_context_var`, regression-guard на attacker-supplied `_meta.client_id` (helper его игнорирует), приоритет authenticated user над `ctx.client_id`, defensive empty-token edge case.
- `tests/test_f4_auth_resolution.py:TestMcpAuthCabinetry` (новый класс, 3 unit-теста) — BUG-001b regression: factory raises на `auth_enabled=True && tokens={}`, dev-mode без tokens работает, normal config с tokens работает.
- `tests/test_f4_auth_resolution.py:TestResolveMcpUser` — `test_none_client_id_returns_admin` разделён на `test_none_client_id_returns_admin_when_auth_disabled` и `test_none_client_id_fail_loud_when_auth_enabled` (последний — regression на `PermissionError` matching `BUG-001`).
- `tests/test_mcp_auth_integration.py` (новый файл, 6 integration-тестов через `httpx + ASGITransport`) — закрывает CI blind-spot из BUG-001 § «Why CI didn't catch». Покрывает full path: HTTP request с Bearer header → `BearerAuthBackend.authenticate` → `AuthenticatedUser` в ASGI scope → `AuthContextMiddleware` → `auth_context_var` → tool body → helper extracts → real client_id. Cases: (1) valid bearer → tool видит реальный `client_id`; (2) attacker-supplied `_meta.client_id` ignored (BUG-001 regression); (3) missing bearer → 401; (4) invalid bearer → 401; (5) dev-mode (`auth_enabled=False`) → helper returns None → admin fallback; (6) production-mode + no identity → fail-loud `PermissionError`. Inline test-tool `whoami_probe` зарегистрирован через `@server.tool()` на свежем FastMCP'е, dispatch'ится через настоящий middleware-stack SDK.
- `tests/test_mcp_http.py:TestCreateMcpServer.test_auth_enabled_without_tokens_skips_verifier` переписан в `test_auth_enabled_without_tokens_raises` — отражает новый fail-loud контракт.

**Verification.**
- Полный `pytest` — **1796 passed, 162 skipped, 1 deselected, 13 warnings** (was 1781 baseline; +15 от Session C новых тестов).
- `rg "ctx\.client_id" tg_parser/mcp_server.py` — только docstring-упоминание (helper документирует, что он НЕ читает это поле).
- `python -c "create_mcp_server()"` с `mcp_auth_enabled=True && mcp_auth_tokens={}` — `RuntimeError` с явной BUG-001b отсылкой (cabinetry работает).
- Ruff lint + format clean.

**Security advisory.** До этого PR'а: любой клиент (с валидным bearer'ом или без) при `MCP_AUTH_ENABLED=true` получал admin-доступ к МСР-серверу с правом read/write/delete на все channels, users, и system-config tools (`set_llm_config`, `reset_llm_config`, `reload_prompts`). Сценарий эксплоит-вектора: anonymous client отправлял JSON-RPC `tools/call` без Authorization header'а, BearerAuthBackend возвращал `None` (auth-credentials отсутствовали), но AuthContextMiddleware не блокировал запрос (только сохранял `auth_context_var = None`), а тулы читали идентичность из `ctx.client_id`, который без `_meta` равен `None`, что упирало в `get_default_admin()`. Production deploy после merge'а **обязателен** для VPS-инстансов с `MCP_AUTH_ENABLED=true`.

### Hot-fix Session B+ — BUG-002 mitigations M1+M2+M3 (2026-04-27)

**Контекст.** Hot-fix sprint, который снижает blast-radius BUG-002
(LLM-агент бота теряет контекст между turn'ами и hallucinates
destructive write-tool'ы — типичный паттерн `add_channel @real`
turn 1, «да» turn 2 → `remove_channel(channel_id="test_channel",
confirm=True)`). Полный фикс root cause'а — Session D (FSM).
Source-of-truth: [`docs/notes/START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md`](docs/notes/START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md)
+ [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) § BUG-002.

#### M1 — Strip `test_channel` default from production code path (commit `e927f53`)
- `tg_parser/processing/mock_llm.py` — `TopicizationMockLLM.__init__` больше не имеет default'а `channel_id="test_channel"`; параметр стал обязательным с docstring'ом про BUG-002 attractor'ность литерала. Тесты обязаны передавать realistic `channel_id`.
- `scripts/add_test_messages.py` — переписан с `argparse`'ом: `--channel-id` обязателен, валидируется тем же блок-листом placeholder'ов, что и M2 (см. ниже). До фикса скрипт жёстко лил `test_channel` в `sources` каждой dev/CI прогонкой, что превращало hallucination'ы Gemini в реальный data-loss.
- `README.md`, `docs/USER_GUIDE.md`, `docs/notes/QUICK_START.md`, `scripts/README.md` — все примеры переведены с `test_channel` на `my_dev_channel` + добавлен note про rejected placeholder names.
- `tests/test_mock_llm.py` (новый файл) — regression: TypeError без `channel_id`, signature-introspection ассертит `param.default is inspect.Parameter.empty`, source-grep ассертит отсутствие литерала `"test_channel"` в `mock_llm.py:TopicizationMockLLM`, плюс happy-path что explicit `channel_id` пробрасывается в `source_ref`.

#### M2 — Pre-flight reject placeholder channel names (commit `295d6e9`)
- `tg_parser/services/channel_placeholders.py` (новый модуль) — single source of truth для placeholder-блоклиста: `DEFAULT_BLOCKED_PLACEHOLDER_NAMES = {"test_channel", "example_channel", "my_channel", "default", "channel_a", "channel_b", "test", "example"}` + runtime-расширение через CSV `BLOCKED_CHANNEL_IDS` env. Helpers: `get_blocked_placeholder_names()`, `is_blocked_placeholder(channel_id)`, `blocked_message(channel_id)`.
- `tg_parser/bot/tools.py:_exec_add_channel` — guard в самом начале (после `lstrip("@")`) возвращает `{"success": False, "error": "blocked_placeholder_name", "message": …}` если имя в блок-листе. Срабатывает и для preview, и для confirm.
- `tg_parser/mcp_server.py:add_channel` — симметричный guard, возвращающий `AddChannelResult(status="rejected", created=False, …)`. `_MCP_INSTRUCTIONS` обновлён.
- `tests/test_bot_tools_v12.py:TestExecAddChannelBlockedPlaceholder` (новый класс) — preview + confirm rejection of `test_channel`, `@`-prefix normalization, env-var расширение (`BLOCKED_CHANNEL_IDS=foo,bar,baz`), real channel proceeds normally.
- `tests/test_mcp_management.py:TestAddChannelBlockedPlaceholder` (новый класс) — symmetric coverage для MCP. Также `test_add_channel_new` / `test_add_channel_normalizes_at` мигрированы с `my_channel` (теперь блокированное имя) на `my_blog`, чтобы оставаться happy-path.

#### M3 — Soft-delete sources instead of cascade hard-delete (commit `eac05b6`)
- `migrations/versions/ingestion/20260427_soft_delete_sources.py` (revision `d7e8f9a0b1c4`, down `c8e9f0a1b2c3`) — additive: `ALTER TABLE sources ADD COLUMN deleted_at TIMESTAMPTZ NULL` + `CREATE INDEX idx_sources_active ON sources(source_id) WHERE deleted_at IS NULL`. No backfill (HM-2 default — past hard-deleted каналы не реанимируются). `tg_parser/storage/sqlalchemy/_metadata.py` зеркально обновлён для `alembic check`/autogenerate.
- `tg_parser/storage/ports.py` — `Source` модель получила `deleted_at: datetime | None`. `IngestionStateRepo` ABC: новый abstract `find_deleted_source(source_id)`, `get_source(...)` и `list_sources(...)` приобрели `*, include_deleted: bool = False` kwarg. Default-контракт: soft-deleted источники невидимы для всех read'ов.
- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py:SAIngestionStateRepo` — `get_source` / `list_sources` дописали `AND deleted_at IS NULL` в WHERE; `delete_source` теперь soft UPDATE (idempotent, rowcount=0 на already-deleted); `_hard_delete_source` (private escape-hatch для тестов и будущего admin-tool); `upsert_source` сбрасывает `deleted_at = NULL` на `ON CONFLICT DO UPDATE` — re-`add_channel` прозрачно реанимирует канал.
- `tg_parser/mcp_server.py:remove_channel` и `tg_parser/bot/tools.py:_exec_remove_channel` — больше **не** открывают `removal_repos()` и не вызывают `delete_by_channel` ни на одном из 8 cascade-репозиториев. Единственный side-effect — `state_repo.delete_source(channel_id)`. Tool descriptors, preview-warning'и и result-сообщения переписаны на soft-delete семантику. `_MCP_INSTRUCTIONS` line 48 обновлена с «permanently delete a channel and all its data» на «soft-delete a channel (data preserved, ingestion stopped)».
- `tests/test_mcp_management.py:TestRemoveChannel.test_remove_success_soft_delete` — переписан: `result.details == {"source": 1, "soft_delete": True}`, явные `assert_not_awaited` для всех cascade-репозиториев, ассерт что message содержит «soft-delete».
- `tests/test_bot_tools_v12.py:TestExecRemoveChannel.test_confirm_soft_delete_only` — symmetric для бота. `test_preview_with_stats` — assertion обновлён с «IRREVERSIBLE» на «soft-delete»/«preserved» в warning-поле.

**Verification.**
- `alembic -c migrations/alembic.ini heads` → `d7e8f9a0b1c4 (head)` для ingestion-ветки + неизменённые heads для raw / processing.
- Полный `pytest` — **1781 passed, 161 skipped, 1 deselected, 13 warnings** (was 1765 baseline; +16 от M1/M2/M3 regression coverage).

**Что осталось открытым.** Контекст-loss (root cause BUG-002) **не закрыт** — Session D (`docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md`) добавит FSM/conversation memory. До тех пор: Severity BUG-002 понижена Critical → High (data-loss vector закрыт; remaining risk — soft-deleted real channel'ы могут «исчезнуть» из ingestion после hallucination'а, восстанавливаются re-`add_channel`'ом).

#### Follow-up — Session B+ post-merge SQL fix + integration coverage (PR #36, 2026-04-27)

**Контекст.** При локальном smoke-тесте только что смерженного M3 на чистом Docker-стеке `remove_channel` упал с `asyncpg.exceptions.AmbiguousParameterError: inconsistent types deduced for parameter $1`. Юнит-тесты M3 в PR #35 этого не ловили — `state_repo.delete_source` был полностью замокан, реальная asyncpg-сериализация параметров не запускалась. Пост-merge fix с regression integration-test'ом:

- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py:SAIngestionStateRepo.delete_source` (commit `cf978b1`) — `UPDATE sources SET deleted_at = :now, updated_at = :now` переписан на `SET deleted_at = NOW(), updated_at = NOW()`. Корень: один и тот же named-parameter `:now` использовался для двух колонок, asyncpg не мог вывести consistent type ($1 deduced один раз, два разных контекста). Поведение M3 идентично — UTC-now на стороне БД, idempotent.
- `tests/test_ingestion_state_repo_soft_delete.py` (новый файл, commit `cf978b1`) — testcontainers-based regression: real Postgres + `alembic upgrade ingestion@head`, тестирует full M3 lifecycle (`upsert_source` → `get_source` видит → `delete_source` → `get_source` не видит → `find_deleted_source` видит → re-`upsert_source` resurrects → `get_source` снова видит). Sync-фикстура `ingestion_db_url` обходит `asyncio.run() cannot be called from a running event loop` от `alembic_upgrade_for_branch`.
- `.github/workflows/ci.yml:Alembic Runtime Upgrade Smoke (testcontainers)` (commit `cc4f2b8`) — добавил `tests/test_ingestion_state_repo_soft_delete.py` в pytest invocation этого job'а, чтобы integration-test реально гонялся в CI вместе с прочими live-DB тестами.
- `docker-compose.yml` (commit `e9ff001`) — `tg_parser` / `mcp` / `tg_bot` services получили hardcoded `DB_HOST=postgres` + `DB_PORT=5432` с явным комментарием. Корень: project-level `.env` содержит `DB_HOST=localhost` для host-side `tg-parser db ...` CLI runs против published 127.0.0.1:5432 порта, и этот `.env` подхватывался compose'ом и оверайдил `${DB_HOST:-postgres}` дефолт, после чего контейнеры пытались коннектиться к `localhost` внутри своего netns и падали с `ConnectionRefusedError` exit-code 3.

**Verification.** Локальный full pytest passes; integration test проходит на свежем Docker-стеке за ~30 сек; VPS smoke (`docker exec tg_parser_mcp python -c …`) подтверждает full M3 lifecycle на проде: `upsert → soft-delete → filtered out → find_deleted_source returns row → resurrect via upsert`.

### Sprint Debt-Fix Post-Living-KB — Phase 2 (2026-04-27)

**Контекст:** Вторая фаза post-Living-KB debt-fix sprint'а — стартовала после закрытия 24h F5-C deploy-watch окна (`2026-04-26T11:07:13Z` → `2026-04-27T13:35Z`). Окно завершилось **operational GREEN** с двумя побочными находками в watch-tooling: cumulative-counter tripwire (Flaw A) и buggy Anthropic health-check probe (Flaw B). См. подробный отчёт: [`docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md`](docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md). Source-of-truth для scope: [`docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`](docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md), [`docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md`](docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md).

#### TD-03c: PromptLoader fail-loud для required LLM stages (S-004 / merged-plan Q2: `fail_loud`)
- `tg_parser/processing/prompt_loader.py` — новый `PromptLoaderError(RuntimeError)`, конст `REQUIRED_PROMPT_STAGES = frozenset({"processing","topicization","rag","digest","resummarize"})` (синхронизирован с `LLM_SCOPES \ {"global"}` через regression-тест), helper `_stage_has_content()` для проверки непустого `system.prompt`, новый метод `validate_required_stages()` для startup-валидации. Метод `load(name)` теперь **бросает `PromptLoaderError`** для required stages, у которых и YAML, и built-in default пустые/отсутствуют (раньше — silent fallback на пустой dict, что приводило к LLM-вызову с пустым system prompt). Non-required stages сохраняют soft-fallback semantics. Default per merged-plan Q2: **fail-loud** — лучше падение на старте, чем тихая деградация в продакшене.
- `tg_parser/services/resummarization_service.py` — `_call_llm` теперь **бросает `PromptLoaderError`** при отсутствии `user.template` для F5-C resummarize stage (раньше: warning + return `{"status": "llm_error"}`, что маскировало конфигурационную ошибку как обычный llm-error и засоряло outcome-распределение).
- `tg_parser/services/digest_service.py` — аналогично: `_call_llm` **бросает `PromptLoaderError`** при пустом `user.template` для digest stage (раньше: silent continue с пустым шаблоном).
- `tests/test_prompt_loader.py` — новый класс `TestRequiredStagesFailLoud` (12 тестов): regression на `REQUIRED_PROMPT_STAGES == LLM_SCOPES \ {"global"}` (синхронизация при добавлении новых scope'ов), happy path с реальными YAML файлами, error path для каждого known failure mode (YAML отсутствует + default пустой / YAML без `system.prompt` / YAML с whitespace-only prompt'ом), validate_required_stages eager-load contract, non-required stage сохраняет soft-fallback.

#### TD-NEW-A: Anthropic health-check probe — переход на `/v1/models` (обнаружено в watch'е Phase 2)
- `tg_parser/api/health_checks.py` — `_check_anthropic` теперь пробует **`GET /v1/models`** вместо `GET /v1/`. До фикса: пробовался корень `https://api.anthropic.com/v1/`, который Anthropic возвращает с `403 Forbidden` ("Request not allowed") **независимо** от валидности API-ключа и баланса; принимались только `200/404`. Эффект: каждые 5 минут писалась запись `LLM provider health check failed: Client error '403 Forbidden'`, false-negative как при здоровой системе, так и при реальном billing-block (signal value = 0). Replacement endpoint `/v1/models` возвращает `200 OK` только при валидном API-ключе (zero-billing организация даёт `403`/`401` с осмысленным `error.type`) — probe теперь реально валидирует auth+org. Pattern совпадает с `_check_openai` (тот тоже бьёт `/v1/models`). End-of-watch diagnostic transcript из 24h F5-C watch (см. § Tripwire #4 в [`post_watch report`](docs/runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md)): `GET /v1/` → `403 forbidden`, `GET /v1/models` → `200 OK` с каталогом, `POST /v1/messages` с тем же ключом → `200` + completion `"Pong! 🏓"` — подтверждает, что fix даёт реальный сигнал.
- `tests/test_phase3d_advanced.py` — два regression-теста в `TestHealthChecks`: `test_check_anthropic_uses_models_endpoint_not_root` (mock `httpx.AsyncClient`; ассертит что URL = `https://api.anthropic.com/v1/models` и `x-api-key` пробрасывается из settings), `test_check_anthropic_raises_on_403` (мокает 403 от Anthropic; ассертит что `httpx.HTTPStatusError` пробрасывается — раньше 403 silent-accepted'ался).

#### TD-05: Normalize scheduler billing-error handling + structured logs (C-006 / S-007)
- `tg_parser/services/scheduler_service.py`:
  - **F11 watchlist hook (lines 224-251)** — добавлена явная `except AnthropicBillingError as wl_billing_exc` ветка перед `except Exception`. Mirroring F5-C resummarize hook contract (Decision #13 + Gotcha #16). До фикса: generic `except Exception` молча проглатывал `AnthropicBillingError` от F11 embeddings → `stage_errors` оставался пустым → `_pause_source_for_billing` не срабатывал → каждый следующий тик повторно бил по Anthropic API с тем же billing error. Опасный feedback loop при шаренном Anthropic budget'е.
  - **Новый helper `_record_and_pause_on_billing(stage_errors, source, state_repo)`** — заменяет ранее существовавший дублированный пар `if`-блоков в `finally`: один писал `record_anthropic_billing_block` метрику, второй вызывал `_pause_source_for_billing`. Теперь оба side-effect'а в одной функции; idempotent на пустой/non-billing `stage_errors` (callable безусловно из `finally`). Эмитит структурный `anthropic_billing_pause_fired` лог с `stage`/`source_id`/`until` keys для Loki/ELK alerting.
  - **`_pause_source_for_billing`** — log line переведён с printf-style `"anthropic_billing_source_paused source=%s until=%s"` на честные structlog kwargs (`source_id=`, `until=`, `backoff_seconds=`). Поведенческая разница: log aggregator теперь видит структурированные поля вместо строкового мерджа, можно фильтровать без regex.
- `tests/test_scheduler_service.py` — пять новых тестов (TD-05 секция):
  - `test_record_and_pause_on_billing_noop_when_stage_errors_empty` — helper-level, контракт «idempotent на пустом списке».
  - `test_record_and_pause_on_billing_noop_when_first_error_is_not_billing` — non-billing first error → no metric, no pause.
  - `test_record_and_pause_on_billing_records_metric_and_pauses_source` — happy-path для helper'а: метрика +1, `rate_limit_until ≈ now + backoff`.
  - `test_watchlist_billing_error_propagates_and_pauses_source` — **regression на основной фикс**: integration через `run_incremental_for_all_sources` с F11 watchlist выкидывающим `AnthropicBillingError`. Mirror'ит существующий `test_billing_error_pauses_source_and_marks_failure` но для F11 entry point. До фикса этот тест бы упал (pause не происходил).
  - `test_watchlist_generic_exception_does_not_pause_source` — **silent-log contract regression guard**: F11 transient `RuntimeError` всё ещё silent-log'ится без поллюции `stage_errors` (Decision #13 silent-log сохранён, мы добавили только billing-specific ветку поверх).
- Helper `_ok_incr_result()` в test fixture (build корректный `IncrementalTopicizeResult` для F11-path тестов).

#### TD-NEW-B: F5-C watch helper — Tripwire #4 cumulative→delta (обнаружено в watch'е Phase 2)
- `docker/f5c_watch.sh` — Tripwire #4 (`tg_parser_anthropic_billing_block_total`) переведён с **cumulative-ratio** на **delta-between-runs**. До фикса: helper сравнивал absolute counter > 0, поэтому первый же billing-инцидент в истории процесса приводил к **permanent TRIPWIRE** на каждом cron-тике вплоть до перезапуска контейнера (counter живёт в memory `Counter()` Prometheus client'а). Реальный пример из 24h watch'а: 5 последовательных тиков с интервалом 4ч сообщали `#4 anthropic billing block fired 60 time(s)`, хотя единственный billing-инцидент случился ~25 часов назад и система давно восстановилась (operational GREEN подтверждён ad-hoc probe'ом). После фикса: helper хранит previous-tick value в `${F5C_WATCH_STATE_DIR:-~/.f5c-watch}/billing_block_state` и алармит только на **positive delta** между двумя соседними запусками. Edge-cases: (a) первый run без state-файла — alarm подавлен (warm-up), state записывается; (b) container restart с reset counter'а (prev > current) — delta clamped to 0, alarm подавлен (компромисс: следующий *новый* billing-инцидент после рестарта tripp-нет на следующем тике, что приемлемо).
- `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — § "Tripwire #4 — source paused via `_pause_source_for_billing`" расширен с описанием новой delta-семантики, env-var `F5C_WATCH_STATE_DIR`, expected behavior на первом запуске после деплоя и после container restart'а.
- `tests/test_f5c_watch_billing_delta.py` — новый файл, девять regression-тестов покрывающих все шесть сценариев из 24h watch trace + corner-cases:
  - `test_first_run_no_baseline_no_alarm` — first-run warm-up tick.
  - `test_steady_state_no_new_events_no_alarm` — **THE TD-NEW-B regression** (counter unchanged → no alarm).
  - `test_counter_increased_alarms_with_delta` — happy-path alarm.
  - `test_post_recovery_no_alarm_after_alarm` — recovery → next tick GREEN.
  - `test_counter_reset_no_alarm` — container restart, prev > current → no alarm + log note.
  - `test_post_restart_steady_state_no_alarm` — постоянство после reset'а.
  - `test_corrupt_state_file_treated_as_first_run` — non-numeric state → no baseline, no alarm.
  - `test_inline_block_in_script_matches_test_block` — drift detector: ассертит что `docker/f5c_watch.sh` содержит каноничный `STATE_FILE` path и `PAUSED_DELTA` арифметику. Если кто-то переименует переменные / переедет на другой state-format — тест упадёт и заставит синхронизировать тестовый snapshot.
  - `test_bash_available` — sanity что bash установлен (CI runners + dev workstation).
- **Trade-off** vs. `f5c_watch.sh` integration tests: shell helper требует `docker compose` и live `/metrics` endpoint, поэтому тесты вызывают inline-snippet через `subprocess.run("bash -c ...")`. Compromise документирован в docstring файла; drift detector выше — буфер от silent-divergence.

### Sprint Debt-Fix Post-Living-KB — Phase 1 (2026-04-26)

**Контекст:** post-Living-KB merged-plan debt-fix, фаза 1 — выполняется параллельно с 24h F5-C deploy-watch окном (`2026-04-26T11:07:13Z` → ≈`2026-04-27T11:07Z`). Закрываются debt-items, не пересекающиеся с F5-C critical path. См. [`docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`](docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md), [`docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE1.md`](docs/notes/START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE1.md). Phase 2 (TD-03c + P1 stretch + post-watch report) — отдельная сессия после закрытия watch'а.

#### TD-04: Close Living-KB docs across deploy and roadmap docs (C-002, C-003, C-004, S-005)
- `PRODUCTION_DEPLOYMENT.md` — bumped to **v4.4**, added top-level closure note, ToC entry, и новый раздел `## v4.4 Living-KB upgrade notes` (миграции `ac6a4414ac58` / `c8e9f0a1b2c3` / `a4b5c6d7e8f9`, F5-C/F11/Anthropic-billing env vars, cron entry для `f5c_watch.sh`, verification curl/SQL, ссылки на `F5C_DEPLOY_AND_WATCH.md` и `ANTHROPIC_BILLING_RECOVERY.md` runbook'ы).
- `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — добавлен top-level баннер `Living-KB contract: CLOSED 2026-04-26`, новый раздел `## 2026-04-26 — Contract closed` со ссылками на CHANGELOG для D.1 / F11 / F5-C, revision-history table обновлена (Wave C **MVP merged**), новый раздел `## Next contract — TBD` с явным placeholder'ом (per merged-plan Q4 default).
- `docs/notes/FUTURE_FEATURES.md` — § Level C (F5-C P2 backlog) теперь явно ссылается на GitHub issue #15 как tracker и помечает каждый из 9 deferred items суффиксом `(see #15 — <subtask>)`. Файл — source of truth (per merged-plan Q3 default); sync issue body — отдельный follow-up.
- `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — top-level баннер `Wave 1 closed 2026-04-26`, новый раздел `## Done — Living-KB contract (Wave 1)` (D.1 / F11 / F5-C), Wave 2 re-ranked: F11 P2 (closest after TD-02 metrics calibration window) → F5-C P2 → F1 Full → F10-A → F12-A. Rationale зафиксирован в подсекции «Wave 2 re-rank rationale».

#### TD-02: Expose Prometheus surface for F11 watchlist (C-001)
- `tg_parser/api/metrics.py` — четыре новые метрики: `tg_watchlist_matches_total{result=delivered|filtered_threshold|filtered_keywords}`, `tg_watchlist_score` (histogram, buckets 0..1 — observed для каждой scored пары, разрешает порог-калибровку перед F11 P2), `tg_watchlist_delivery_total{outcome=sent|blocked|error}`, `tg_watchlist_active_interests` (gauge). Helper-функции `record_watchlist_match`, `record_watchlist_delivery`, `set_watchlist_active`. Cardinality-safe — `interest_id` намеренно не кладётся в label set.
- `tg_parser/services/watchlist_service.py` — `check_interests` инструментирован: per-pair `record_watchlist_match` (excluded → `filtered_keywords`; below threshold → `filtered_threshold`; persisted → `delivered`) + score-histogram, `notify` пишет `record_watchlist_delivery(sent|blocked|error)`. `_refresh_active_gauge()` обновляет gauge в начале каждого тика (operator-bounded → cheap).
- `tests/test_watchlist_metrics.py` (new, 8 tests) — unit-coverage helper'ов + service-level smoke тест что `check_interests` дёргает `record_watchlist_match` хотя бы один раз.
- `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — новая sub-section «F11 watchlist health» (PromQL для match-flow, score-distribution для F11 P2 калибровки, delivery success rate, active gauge, error-rate tripwire).

#### TD-03b: Declare anthropic prompt-cache + token-estimate as `Settings` fields (S-003 / CODE-004)
- `tg_parser/config/settings.py` — три новых поля в `Settings`: `anthropic_prompt_caching_enabled: bool` (default `True`), `processing_anthropic_input_token_estimate: int` (default `2000`, `ge=100`/`le=200_000`), `processing_anthropic_output_token_estimate: int` (default `2048`, `ge=100`/`le=64_000`). Defaults сохраняют production-поведение, наблюдавшееся через legacy `getattr` fallback (никаких behavior changes на хостах без env-override).
- `tg_parser/processing/llm/factory.py` — три `getattr(settings, ...)` заменены на прямые `settings.<field>`. Env-vars `ANTHROPIC_PROMPT_CACHING_ENABLED`, `PROCESSING_ANTHROPIC_INPUT_TOKEN_ESTIMATE`, `PROCESSING_ANTHROPIC_OUTPUT_TOKEN_ESTIMATE` теперь действительно подхватываются Pydantic'ом (раньше silently dropped).
- `.env.example` — три новых строки с дефолтами и описанием.
- `tests/test_settings.py` (new, 2 tests) — `test_anthropic_cap_settings_declared` (defaults + env-override roundtrip), `test_anthropic_token_estimates_validate_bounds` (ge/le contracts: 0 / 300_000 / 128_000 → ValidationError).

#### TD-03a: Surface `resummarize` across all LLM-config tools (S-002 / CODE-002 + CODE-003 + CODE-006)
- `tg_parser/config/settings.py` — `LLMConfigManager.get_all()` теперь строит `stages` dict из `LLM_SCOPES` (исключая `"global"`), а не из захардкоженного списка из 4 элементов. Future scopes автоматически появляются в snapshot. `resummarize` теперь видим в `get_llm_config` MCP/REST output. Class docstring обновлён со ссылкой на `LLM_SCOPES`.
- `tg_parser/mcp_server.py` — server-level docstring (top-of-file, MCP capabilities banner) и `set_llm_config` / `reset_llm_config` Args-секции теперь перечисляют все 6 scopes (включая `resummarize`) вместо 5.
- `tg_parser/processing/llm/factory.py` — `resolve_llm_config` docstring обновлён: `stage` теперь явно ссылается на `LLM_SCOPES` и перечисляет все валидные значения (`"processing"`, `"topicization"`, `"rag"`, `"digest"`, `"resummarize"`).
- `tests/test_llm_factory.py::test_get_all_includes_every_scope` (new) — regression: assertion что `LLM_SCOPES \ {"global"}` ⊆ `get_all()["stages"].keys()`. Если кто-то добавит новый scope и забудет про `get_all()` — тест падает.

#### TD-01: Align scheduler `error_message` truncation contract with documented 4096 chars (S-001)
- `tg_parser/services/scheduler_service.py` — `_truncate_error_message` default bumped с 500 → **4096**, чтобы соответствовать Sprint D.1 контракту (CHANGELOG `## Sprint D.1 — Topicization Hardening` / `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` Sprint D.1 § 1). RCA evidence (Anthropic billing payload, full Telegram exception strings, stack-trace tail) перестаёт молча обрезаться. Per-fields docstring указывает на S-001 / merged-plan для будущей археологии. **Default per merged-plan Q1: bump to 4096**.
- `tests/test_scheduler_service.py` — два regression-теста: `test_record_attempt_truncates_at_documented_limit` (5000-char `Exception` через `_safe_record_attempt` → ровно 4096 chars в `error_message`), `test_truncate_error_message_default_matches_documented_contract` (signature-level guard через `inspect.signature`, чтобы любой будущий regression на 500 падал моментально).

### Sprint F5-C — Evolving Topic Summaries (2026-04-26)

**Статус:** ✅ MVP DONE 2026-04-26 — commit 1/2 `473f107` (schema + service + counter + core tests), commit 2/2 `53f72ef` (scheduler hook + MCP/CLI + remaining tests + docs). См. `docs/notes/START_PROMPT_SPRINT_F5C.md`, `docs/notes/F5C_PR_CHECKLIST.md`.

**Контекст:** закрывает последний пробел в Living KB-контракте — тема знала о новых материалах через scheduler hook D.1 + F11 evidence log, но **не помнила** их содержания. F5-C делает `TopicCard.summary` функцией от потока supporting items: при накоплении N новых items (default `RESUMMARIZE_TRIGGER_N=5`) тема перезапускает LLM-резюме (новый scope `resummarize`), переэмбеддит обновлённый текст и **сохраняет предыдущую версию** в новой append-only таблице `topic_card_versions` (audit trail + опорная точка для будущих фичей). North star: `TopicCard.summary` — функция `bundle.items`, обновляемая по дешёвому триггеру (счётчик), с полной историей изменений.

#### Added
- **Migration** `migrations/versions/processing/20260426_add_topic_card_versions.py` — три новые колонки в `topic_cards` (`last_summarized_at TIMESTAMPTZ`, `summary_version INTEGER NOT NULL DEFAULT 1`, `new_items_since_last_summary INTEGER NOT NULL DEFAULT 0`); partial index `idx_topic_cards_resummarize_candidates` (`WHERE new_items_since_last_summary > 0`); data-bootstrap (`last_summarized_at = updated_at::timestamptz`); новая append-only таблица `topic_card_versions` с `UNIQUE(topic_id, version_no)` + FK `ON DELETE CASCADE`.
- **Domain models** — `TopicCardVersion` (`tg_parser/domain/models.py`) + три новых optional поля в `TopicCard` (backward-compat по существующим JSON-payload'ам); JSON-schemas: `docs/contracts/topic_card_version.schema.json` (новый файл), `docs/contracts/topic_card.schema.json` (новые поля в `properties`, НЕ в `required`).
- **`TopicCardVersionRepo`** port (`tg_parser/storage/ports.py`) + SAImpl (`tg_parser/storage/sqlalchemy/topic_card_version_repo.py`) — `insert`, `list_by_topic`.
- **`TopicCardRepo`** расширен — `increment_resummary_counter`, `list_resummarize_candidates(threshold)`, `commit_resummary` (атомарный single-UPDATE с optimistic version-check; устраняет race из пары `upsert + reset_after_resummary`).
- **`ResummarizationService`** (`tg_parser/services/resummarization_service.py`) — `resummarize_topic` (Postgres advisory lock `pg_try_advisory_xact_lock(0xF5C, hashtext(topic_id))` → bundle.items[:N] sliding window → LLM call → `commit_resummary` → append `TopicCardVersion` → `run_topic_embedding(force=True)` для одной темы → метрики; внутри использует `topic_card_repo.list_resummarize_candidates`), `run_for_channel` с triple-cap (`MAX_PER_TICK`, `MAX_DURATION_S`, `MAX_TOKENS_PER_TICK`).
- **Counter increment** в `_update_bundles_for_assignments` (`tg_parser/services/topicization_service.py`) — сразу после `topic_bundle_repo.add_items(...)` дёргается `topic_card_repo.increment_resummary_counter(...)`. Каждая операция коммитит свою транзакцию (eventual consistency, две транзакции — gotcha #1: между ними процесс может упасть; counter максимум "опоздает" на тик); per-batch checkpointing D.1 preserved — ингест/топикизация не блокируются падением counter-bump'а.
- **Scheduler hook** `run_resummarize_for_channel` (`tg_parser/services/scheduler_service.py`) — встаёт между `run_topic_embedding(force=False)` и `run_watchlist_check_for_channel`, F11 watchlist scoring теперь идёт по freshest summary. F11-style silent log (Decision #13): non-billing failures → `logger.exception` (НЕ в `stage_errors`, иначе `success=False` соврёт про upstream stages); `AnthropicBillingError` → `stage_errors` для срабатывания `_pause_source_for_billing`. F5-C — post-processing, никогда не блокирует ingestion/topicization.
- **MCP tools (2)** — `get_topic_versions(topic_id, limit=10)` (audit trail; ownership через новый `assert_topic_access` — видим, если у пользователя есть доступ хотя бы к одному из `topic.sources`, mirrors `TopicCardRepo.list_by_channels` semantics), `force_resummarize(topic_id)` (admin-only manual trigger; advisory-lock обязательный). `get_topic_details` extended — три новых поля в ответе.
- **CLI tools (2)** — `tg-parser topic versions <topic_id> [--limit 10]` (audit trail), `tg-parser topic resummarize <topic_id> [--dry-run]` (admin manual trigger).
- **Per-stage LLM scope** `resummarize` в `LLMConfigManager` — env vars `RESUMMARIZE_LLM_PROVIDER` / `RESUMMARIZE_LLM_MODEL`; pydantic default `None` для обоих (наследуют от `LLM_PROVIDER` / `LLM_MODEL` через `LLMConfigManager.resolve()`). Эффективный default при unset обеих переменных — `openai/gpt-4o-mini` (~$0.15/1M input — global `LLM_PROVIDER=openai`, openai client разрешает `None` model в `gpt-4o-mini`). Runtime switching через MCP `set_llm_config(scope='resummarize', ...)` без рестарта.
- **Prompt** `prompts/resummarize.yaml` (system/user/model по конвенции) — `reload_prompts` MCP tool подхватывает out-of-the-box.
- **Metrics** — `tg_resummarize_total{channel_id, outcome}` (outcome ∈ {ok, locked, no_card, no_bundle, empty_scope, llm_error, version_raced, unknown}; channel_id пока всегда `"-"`, резервный label под Phase 2), `tg_resummarize_tokens_total{provider, model, token_type}` (token_type ∈ {prompt, completion}), `tg_resummarize_duration_seconds{model}`. Tokens/duration пишутся только при `outcome=ok`.
- **`assert_topic_access`** (`tg_parser/auth/ownership.py`) — helper для `get_topic_versions` (доступ к теме при доступе хотя бы к одному из её sources; admin always passes).

#### Changed
- **`_update_bundles_for_assignments`** теперь принимает `topic_card_repo` keyword-only — тестовые call sites без позиционного аргумента не ломаются.
- **`get_topic_details` MCP** возвращает три новых поля (`summary_version`, `last_summarized_at`, `new_items_since_last_summary`).
- **Bot tools intentionally NOT added** (Decision #9) — F5-C — backend-фича для аудита/admin debug, MCP+CLI достаточно для пилота.

#### Tests
- **`tests/test_f5c_topic_card_repo.py`** (PG-gated, 12 тестов) — round-trip новых колонок, `increment_resummary_counter` атомарность + no-op for zero, `list_resummarize_candidates` (threshold + channel filter, below-threshold returns empty, **ordering by counter DESC** — fair scheduling), `commit_resummary` (happy-path bumps version + resets counter, optimistic version check loses race, `metadata_extras=None` keeps existing metadata — null-safety), `TopicCardVersionRepo` (`insert` + `list_by_topic`, UNIQUE(topic_id, version_no) collision).
- **`tests/test_f5c_resummarization_service.py`** (PG-gated, 16 тестов) — happy path (writes version + commits + re-embeds), `no_card` / `no_bundle` / `llm_error` / `empty_scope` statuses, **`locked` при недоступном advisory lock**, **`version_raced` при проигрыше commit_resummary**, **re-embed failure не откатывает commit**, **singleton `type` сохраняется после resummarize**, **kill-switch (`RESUMMARIZE_ENABLED=false`) short-circuits run_for_channel**, **`MAX_TOKENS_PER_TICK` cap корректно прерывает loop с reason `cap_tokens`**, `AnthropicBillingError` propagates (НЕ ловится в обобщённом `except Exception`), `run_for_channel` aggregates / triple-cap / billing propagation, `bundle.items[:RESUMMARIZE_INPUT_WINDOW_N]` (top-N), не `[-N:]` (gotcha #6).
- **`tests/test_f5c_counter_increment.py`** (PG-gated, 3 теста) — counter bumps on `add_items` / no-bump when `topic_card_repo` omitted (backward-compat) / **counter не увеличивается, если `add_items` бросил `ValueError` (bundle missing)**.
- **`tests/test_f5c_scheduler_hook.py`** (6 тестов) — happy path invokes `run_for_channel` + closes service; `aclose` called even when `run_for_channel` raises; `AnthropicBillingError` propagates from hook to caller; structural test `inspect.getsource(scheduler_service)` подтверждает порядок (`run_topic_embedding` → `run_resummarize_for_channel` → `run_watchlist_check_for_channel`); silent-log не пишет в `stage_errors` для generic exception; **`stages_ok.append("resummarize")` только при `resummarized > 0`** (Decision #13).
- **`tests/test_f5c_mcp_tools.py`** (10 тестов) — `get_topic_versions` ownership matrix (admin / owner / non-owner with access to one source / non-owner without access — должен видеть cross-channel topic если есть доступ хотя бы к одному source); invalid limit returns error без DB-call; `force_resummarize` admin-only; `aclose` called on raise; **`status="locked"` пробрасывается без подмены**; **`AnthropicBillingError` пробрасывается через `force_resummarize`**.
- **`tests/test_f5c_cli.py`** (11 тестов) — `versions` happy path / topic-not-found exit-1 / empty history / **`--limit` форвардится в repo** / **invalid limit отклоняется Typer'ом**; `resummarize --dry-run` happy / topic-not-found; `resummarize` happy invokes service + closes (фиксирует контракт `version_no` в outcome — масировал реальный баг, что CLI не печатал номер версии); `locked` status soft-warning (exit 0, retry); `unknown` status exit-1; **service exception всё равно закрывает service + exits 1**.
- **`tests/test_migrations_runtime_upgrade.py`** — добавлены `topic_card_versions` в `EXPECTED_TABLES` + три новых index в `CRITICAL_INDEXES` для processing-ветки.

**Verification (локально):**
```text
pytest -q                       → 1881 passed, 4 skipped, 1 deselected   (no PG;
                                  4 skipped — testcontainers, 1 deselected — integration)
TEST_POSTGRES=1 pytest tests/test_f5c_*.py
                                → 58 passed                              (commit 1/2 + 2/2 + self-review)
ruff format + check             → clean
tg-parser db check --db processing → No new upgrade operations detected.
```

#### Migration
- Forward — single Alembic step `a4b5c6d7e8f9` (`migrations/versions/processing/20260426_add_topic_card_versions.py`): создаёт колонки + index + bootstrap + таблицу.
- Backward — `tg-parser db downgrade --db processing --revisions 1 --yes`: дропает таблицу + три колонки. F11 watchlist + F6 digest изолированы — продолжают работать. История версий тем (если успели накопиться) теряется навсегда — для MVP допустимо.

#### Documentation
- `docs/USER_GUIDE.md` — новый раздел «Evolving Topic Summaries (F5-C)» с CLI/MCP примерами, конфигурацией, метриками.
- `docs/notes/FUTURE_FEATURES.md` § Level C → ✅ MVP DONE 2026-04-26.
- `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` Wave C — реализовано.
- `docs/contracts/topic_card.schema.json` — три новых optional поля.
- `docs/contracts/topic_card_version.schema.json` — новый файл.

### Sprint F11 — Topic Watchlist (2026-04-25)

**Статус:** ✅ merged в `main` 2026-04-25 — commit 1/2 `026313c` (storage + scoring), commit 2/2 `8e07212` (scheduler hook + MCP/Bot/CLI + push + docs), self-review test expansion `0ff5bcf` (+49 cases). См. `docs/notes/START_PROMPT_SPRINT_F11.md`, `docs/notes/F11_PR_CHECKLIST.md`. CI: 5/5 jobs зелёные (`24938330375`).

**Контекст:** проактивный мониторинг living KB — пользователь декларирует тему (title + description + keywords + threshold + каналы), `WatchlistService` гибридом keyword+cosine скорит каждый новый документ, на превышении порога пишет evidence row в `watch_matches` и шлёт push-уведомление через aiogram. Hook встаёт **после** `run_incremental_topicization` в одном scheduler tick, чтобы переиспользовать `summary` / `entities` / topics; при сбое topicization матчинг работает по `text_clean` (graceful degradation, не блокирует ingestion).

#### Added
- **Domain models** (`tg_parser/domain/models.py`) — `WatchInterest` (`title`, `description`, `keywords[]`, `exclude_keywords[]`, `channel_ids[]`, `threshold`, `notify_mode={instant,batch,silent}`, `embedding`) и `WatchMatch` (`interest_id`, `source_ref`, `keyword_score`, `semantic_score`, `combined_score`, `notified_at`).
- **Migration** `migrations/versions/ingestion/20260425_add_watchlist.py` — таблицы `watch_interests` (+ pgvector колонка `embedding`) и `watch_matches` с `UNIQUE(interest_id, source_ref)` для идемпотентности; `pgvector` extension `CREATE EXTENSION IF NOT EXISTS` (idempotent в текущей топологии).
- **`WatchInterestRepo` / `WatchMatchRepo`** ports (`tg_parser/storage/ports/`) + SQLAlchemy реализации (`tg_parser/storage/sqlalchemy/{watch_interest_repo,watch_match_repo}.py`) — `upsert_many` с `ON CONFLICT DO NOTHING`, scoping `list_for_user` / `list_all` (admin-vs-owner), `list_active_for_channel` для scheduler tick.
- **`WatchlistService`** (`tg_parser/services/watchlist_service.py`) — `compute_watch_score` (`0.4*keyword + 0.6*semantic`, exclude-keyword negative filter, [0, 1] clamp), `check_interests` (батч новых документов → matches с per-interest threshold), `notify` (group by `interest_id`, MarkdownV2 escaping, soft-fail на «Chat not found», `mark_notified` после успеха), `aclose` для embedding client. Фабрика `make_watchlist_service` с graceful fallback при недоступном embedding-провайдере.
- **Scheduler hook** `run_watchlist_check_for_channel` (`tg_parser/services/scheduler_service.py`) — вызывается из `_process_source` после `run_incremental_topicization`, обёрнут в `try/except + logger.exception`; watchlist-сбой не блокирует ingestion.
- **MCP tools (4)** — `subscribe_watchlist` / `list_watchlists` / `unsubscribe_watchlist` / `get_watchlist_matches` с ownership через `assert_channel_access` для каналов и admin/owner для interest.
- **Bot tools (4)** — те же 4 декларации в `_TOOL_DECLARATIONS` + `_TOOL_EXECUTORS`; `subscribe_watchlist` ∈ `_TOOLS_NEEDING_BOT_CONTEXT` для деривации `chat_id` из bot context.
- **CLI** — `tg-parser watchlist {add,list,remove,matches}` (`tg_parser/cli/watchlist.py`).
- **Push delivery** — aiogram `Bot.send_message(chat_id, parse_mode=MarkdownV2)` с экранированием спецсимволов и t.me-permalinks для public-каналов; backslash escape, fallback на `source_ref` при отсутствующем документе.
- **`MAX_DOCS_PER_TICK = 100`** — защита от flood при backfill.

#### Changed
- **MCP + Bot tool count**: 28 → 32 (+ 4 watchlist tools). `tests/test_bot_tools_v11.py` / `test_bot_tools_v12.py` — assertion `len(TOOL_DECLARATIONS) == 32`.
- **`run_watchlist_check_for_channel` docstring** — приведена в соответствие с реальным контрактом: хук пробрасывает исключение наружу для `try/finally` cleanup `service.aclose()` + `watchlist_repos`, а граничный `try/except` в `_process_source` логирует и продолжает tick. Гарантия «watchlist никогда не блокирует ingestion» сохраняется через scheduler call site, а не через подавление в самом хуке.

#### Tests
- **`tests/test_watchlist_service.py`** — service-level (no DB), 50+ тестов: `compute_watch_score` (hybrid, pure-keyword fallback, exclude-keyword filter, [0,1] clamp, recall partial overlap), `_tokenize` / `_cosine` / `_post_url` / `build_canonical_interest_text` (Cyrillic, None, orthogonal/negative cosine, t.me для @-prefixed/non-numeric/non-tg), `check_interests` ветки (exclude_keywords path, no_processed_docs всё ещё трогает `last_checked_at`, `bot=...` wiring в notify, notify failure не маскирует inserted matches), `notify` edge cases (`match_id=0` не идёт в `mark_notified`, `mark_notified` raise проглатывается, single-group failure не отравляет соседей), `aclose` (none / normal / swallowed error), `make_watchlist_service` (with/without client + graceful fallback), MarkdownV2 helpers (backslash escape, empty input, source_ref fallback, score-desc ordering).
- **`tests/test_f11_watchlist_repo.py`** (PG-gated) — 16 тестов: `upsert_many` идемпотентность, `list_active_for_channel` ordering, `list_for_user` scoping (non-admin), `list_all` (admin audit), `create()` с provided_id round-trip, `NotifyMode.BATCH` round-trip, `mark_notified`.
- **`tests/test_f11_watch_match_repo.py`** (PG-gated) — `mark_notified` batch, `since_iso` фильтр.
- **`tests/test_f11_scheduler_hook.py`** — happy path + `notify` failure не валит scheduler tick.
- **`tests/test_f11_mcp_tools.py`** — `subscribe_watchlist` валидация (`threshold`, ownership через `assert_channel_access`), `list_watchlists` admin-vs-owner, `unsubscribe_watchlist` ownership, `get_watchlist_matches` фильтр `since_iso` (UTC offset).
- **`tests/test_f11_bot_tools.py`** — declarations exist, `chat_id` берётся из bot context, executor ownership, response shape (`interest_id` поле).
- **`tests/test_f11_cli_watchlist.py`** — `watchlist {add,list,remove,matches}` через `CliRunner` (комбинация stdout+stderr, чтобы покрыть `typer.echo(err=True)` пути).

**Verification (локально):**
```text
pytest -q                       → 1697 passed, 130 skipped, 1 deselected   (no PG, CI-equivalent)
TEST_POSTGRES=1 pytest -q       → 1823 passed,   4 skipped, 1 deselected   (+126 PG-gated f11/repo/integration)
TEST_TESTCONTAINERS=1 pytest \
    tests/test_migrations_runtime_upgrade.py
                                → 4 passed                                  (alembic upgrade smoke)
```
Остаточные 4 skip — testcontainers Alembic-upgrade jobs (требуют отдельный Docker daemon, opt-in через `TEST_TESTCONTAINERS=1`, гонятся в CI job `alembic-runtime-smoke`); 1 deselected — `@pytest.mark.integration` end-to-end RAG тест (требует реальный OpenAI key).

#### Documentation
- `docs/USER_GUIDE.md` — новый раздел F11 с примерами `tg-parser watchlist add/list/remove/matches` и описанием полей.
- `docs/MCP_AGENT_GUIDE.md` — описания 4 новых MCP tools (`subscribe_watchlist` / `list_watchlists` / `unsubscribe_watchlist` / `get_watchlist_matches`), ownership-rules, threshold default `0.6`.
- `docs/notes/FUTURE_FEATURES.md` — § F11 помечен `✅ DONE`, ROADMAP-таблица обновлена.
- `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — F11 → ✅ выполнено, F5-C явно помечен следующим шагом.
- `docs/notes/F11_PR_CHECKLIST.md`, `docs/notes/START_PROMPT_NEXT_SESSION_F11.md`, `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — добавлены в commit `84ff794` (PR-чеклист с karpathy-like пометками + сессионный промпт + долгосрочный roadmap living KB).

**Phase 2 (вне scope):** `notify_mode=batch` через digest-инфраструктуру, `notify_mode=silent` (только evidence log), LLM-matching на каждый документ, HTTP `/api/v1/watchlists`, workspace-scoping интересов.

### Sprint D.1 — Topicization Hardening (2026-04-25)

**Статус:** ✅ deployed на VPS `redboxtgbot` 2026-04-25 — code commit `cdce066` (feat), deploy commit на `main` `33d9f48`, ingestion migration `ac6a4414ac58` (`add_source_attempts_failed_stage`). Verification — см. `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` § 7a.

**Контекст:** Silent stall топикизации на канале `genotek` (см. `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md`) — incremental-режим не находил `TopicCard` и тихо пропускал работу, в `source_attempts.success=true` несмотря на 0 произведённых тем.

#### Added
- **`AnthropicBillingError`** (`tg_parser/processing/llm/errors.py`) — отдельный non-retryable класс ошибки для `400 invalid_request_error: credit balance is too low`. Pipeline retry-loops такую ошибку не ретраят.
- **`source_attempts.failed_stage`** — новая колонка (`VARCHAR`, nullable) с именем первого упавшего этапа (`ingest` / `process` / `export` / `topicize` / `incremental_topicization`). Миграция: `migrations/versions/ingestion/20260425_add_source_attempts_failed_stage.py` (revision `ac6a4414ac58`).
- **Метрика `tg_parser_anthropic_billing_block_total{stage}`** (`tg_parser/api/metrics.py`) — счётчик billing-пауз для алертинга.
- **`BILLING_BLOCK_BACKOFF_S`** (env, default `3600`, min `60`) — длительность паузы источника после billing-error. См. `ENV_VARIABLES_GUIDE.md` и `.env.example`.

#### Changed
- **Per-batch checkpointing в incremental Phase 2.** `topicization_service.run_incremental_topicization` теперь вызывает `_discover_single_batch` в цикле и после каждого успешного батча сразу персистит `topic_card_repo.upsert(...)` + `topic_bundle_repo.add_items(...)`. Падение N+1-го батча больше не откатывает первые N. Деталь оркестрации: `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` § Sprint D.1.
- **Эскалация incremental → full.** Если новые документы есть, а `TopicCard` = 0, incremental-режим автоматически вызывает `run_topicization(force=True)` вместо тихого no-op.
- **Truthful `source_attempts`.** `scheduler_service._process_source` ведёт `stage_errors[]` и в `finally` пишет `record_attempt(success, failed_stage, error_class, error_message)`. Любой сбой на любом этапе пишется в БД (`error_message` усечено до 4096 символов).
- **`_discover_single_batch`** (`tg_parser/processing/topicization.py`) пробрасывает `RuntimeError` / `ValueError` / `OSError` наружу вместо «тихого» fallback в `unassignable` — иначе scheduler не узнавал об ошибке.
- **`scheduler_service`** пропускает источники с активным `rate_limit_until` (включая billing-pause).

#### Tests
- `tests/test_anthropic_client_billing.py` — 4 теста: распознавание credit-balance, не-retry, malformed body, case-insensitivity.
- `tests/test_incremental_topicization.py` — добавлены `test_incremental_escalates_to_full_when_no_topic_cards`, `test_incremental_llm_checkpoint_persists_previous_batches_on_failure`.
- `tests/test_scheduler_service.py` — добавлены `test_failed_incremental_topicization_marks_attempt_failed`, `test_billing_error_pauses_source_and_marks_failure` (проверяют `failed_stage`, метрику, `rate_limit_until` ± `BILLING_BLOCK_BACKOFF_S`).
- `tests/test_cross_channel_topicization.py` — оркестрационные тесты адаптированы к новому per-batch call-path.

#### Migration
```bash
docker compose run --rm --no-deps tg_parser db upgrade --db ingestion   # ac6a4414ac58
```
Эквивалент: `alembic -c migrations/alembic_ingestion.ini upgrade head`. Команда `compose exec` НЕ подходит для greenfield/новых ревизий — она цепляется к старому контейнеру; использовать одноразовый `compose run --rm` от только что собранного образа.

#### Deployment (executed 2026-04-25, VPS `redboxtgbot`)
1. Pre-deploy backup: `data/backups/postgres_pre_d1_20260425_180906.sql.gz` (44 МБ).
2. `git pull --ff-only origin main` (`5b71669` → `33d9f48`), `docker compose build` (новый image `tg_parser:latest` `49ebdd16d893`).
3. Миграция `ac6a4414ac58` через `compose run --rm --no-deps` (см. выше).
4. `docker compose up -d` (recreated `tg_parser` + `tg_parser_mcp`). Бот живёт под профилем `bot` и НЕ пересоздаётся командой выше — отдельной командой `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` форсируем подхват нового образа.
5. Smoke: `\d source_attempts` показывает `failed_stage`, `/metrics` отдаёт `tg_parser_anthropic_billing_block_total`, все 5 источников `status=active rate_limit_until=NULL`, `docker compose ps` — все сервисы `healthy`, в логах scheduler errors/exceptions нет.

#### Documentation
- `docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md` — `DONE (deployed)`, post-sprint чек-лист закрыт.
- `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` — добавлен раздел Sprint D.1 + расширена таблица рисков.
- `docs/architecture.md` — `source_attempts` schema (DDL + bullet-list) теперь включает `failed_stage`.
- `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` — `Status: fixed in production` + § 7a Verification.
- `docs/quality/TRIAGED.md` — `Status: fixed in production`.
- `docs/notes/FUTURE_FEATURES.md` / `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — D.1 помечен `deployed`.
- `docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md` — новый runbook оператору: как восстановить источник из billing-pause.
- `ENV_VARIABLES_GUIDE.md` / `.env.example` / `env.production.example` — описан `BILLING_BLOCK_BACKOFF_S`.

## [4.3.0] - 2026-04-15

### Added

#### Multi-Tenancy — User Management (F4 Phase 5)
- **User model** — `users` + `user_auth_mappings` tables with roles (`admin` / `user`), per-user channel limits, and channel ownership (`sources.owner_id`)
- **Auth resolution** — `resolve_user_by_auth()` with TTL cache; supports `api_key` (SHA-256 hash), `mcp_token` (SHA-256 hash), and `telegram` (plain user ID) auth types
- **Ownership enforcement** — `assert_channel_access()`, `assert_admin()`, `check_channel_limit()` helpers used across API, MCP, and Bot layers

#### MCP Server (24 tools — was 17)
- **`register_user`** — create a new user (admin only)
- **`update_user`** — update user properties including `reset_max_channels` (admin only)
- **`list_users`** — list all users with owned channel counts (admin only)
- **`whoami`** — current user profile with channel list (any authenticated user)
- **`add_user_auth`** — add auth mapping; auto-hashes `api_key`/`mcp_token` (admin only)
- **`remove_user_auth`** — remove auth mapping by ID (admin only)
- **`reload_prompts`** — reload prompt YAML files without restart (admin only)

#### Telegram Bot (24 tools — was 17)
- 6 new `_exec_*` functions + 6 new `TOOL_DECLARATIONS` for Gemini function-calling
- Same capabilities as MCP user management tools
- `/start` now shows personalized greeting or "not registered" message based on `CurrentUser`

#### REST API — `/api/v1/users`
- **`GET /api/v1/users/me`** — current user profile with owned channels
- **`GET /api/v1/users`** — list all users with channel counts (admin only)
- **`POST /api/v1/users`** — create user (admin only, 201)
- **`PATCH /api/v1/users/{id}`** — update user with `reset_max_channels` flag (admin only)
- **`DELETE /api/v1/users/{id}`** — delete user + cascade auth mappings (admin only, 204)

#### CLI — Migration
- **`tg-parser migrate-users [--dry-run]`** — one-time migration of existing credentials to user model
  - Maps `API_KEYS` → `api_key` auth mappings (SHA-256 hashed)
  - Maps `MCP_AUTH_TOKENS` → `mcp_token` auth mappings (SHA-256 hashed)
  - Maps `BOT_ALLOWED_USERS` → `telegram` auth mappings
  - Assigns `owner_id` on orphan sources
  - Idempotent: safe to run multiple times

#### Configuration
- **`DEFAULT_MAX_CHANNELS`** — default channel limit per user when `users.max_channels` is NULL (default: 20)

### Changed
- **Version bumped to 4.3.0** from 4.2.0
- **MCP + Bot tool count**: 17 → 24 (+ 6 user management + 1 reload_prompts)
- **1266 tests** — up from 855 (incl. `TEST_POSTGRES=1`)

### Tests
- **`tests/test_f4_user_management.py`** — 57 unit tests covering MCP, Bot, API, Migration tools
- **`tests/test_users_routes.py`** — 13 HTTP integration tests via AsyncClient/ASGITransport
- Updated `test_bot_tools_v11.py` / `test_bot_tools_v12.py` — TOOL_DECLARATIONS count 18 → 24

## [4.2.0] - 2026-04-09

### Added

#### MCP Server (17 tools)
- **Streamable HTTP transport** — production-ready MCP over HTTP (replaces stdio)
- **Bearer token authentication** — `MCP_AUTH_ENABLED` + `MCP_AUTH_TOKENS`
- **Channel management tools** — `add_channel`, `pause_channel`, `resume_channel`, `remove_channel`
- **Pipeline control** — `trigger_pipeline`, `get_pipeline_status`
- **LLM config management** — `get_llm_config`, `set_llm_config`, `reset_llm_config`
- **Cross-channel analytics** — `get_cross_channel_stats`, `get_related_topics`
- **Search & Q&A** — `search_knowledge_base`, `ask_question` (RAG with citations)
- **Navigation** — `list_topics`, `get_topic_details`, `list_channels`, `get_document`

#### Telegram Bot (V1.2 — Full Operational Interface)
- **Gemini-powered agent** — free-form chat, automatic tool routing
- **17 tools** — same capabilities as MCP server
- **Two-phase confirmation** — preview → confirm for all write operations
- **User allowlist** — `BOT_ALLOWED_USERS` for access control
- **Rate limiting** — per-user request throttling

#### Embedding & RAG
- **pgvector embeddings** — semantic search over knowledge base
- **OpenAI embeddings** — `text-embedding-3-small` by default
- **RAG pipeline** — retrieval-augmented Q&A with source citations

#### Cross-channel Analytics
- **Topic linking** — automatic detection of related topics across channels
- **Keyword overlap** — cross-channel keyword analysis
- **Coverage stats** — topic counts and coverage per channel

#### Production Infrastructure
- **Docker Compose full stack** — API, MCP, Bot, PostgreSQL, Prometheus, Grafana
- **Nginx reverse proxy** — TLS via Let's Encrypt, auto-renewal
- **Prometheus + Grafana** — HTTP, LLM, pipeline, scheduler metrics; 2 dashboards
- **Automated backups** — daily PostgreSQL backups with rotation
- **Per-stage LLM overrides** — `PROCESSING_LLM_PROVIDER`, `TOPICIZATION_LLM_PROVIDER`
- **Incremental topicization** — process only new documents
- **Background scheduler** — automatic pipeline execution on intervals

### Changed
- **Version bumped to 4.2.0** from 3.1.1
- **PostgreSQL as primary** — pgvector for embeddings, connection pooling
- **855 tests** — up from 411

## [3.1.1] - 2025-12-30

### Fixed

#### CLI PostgreSQL Compatibility
- **All CLI commands now use `Database.from_settings()`** — unified database initialization
  - `add_source_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `ingest_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `process_cmd.py` — updated 2 instances to from_settings()
  - `export_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `run_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `topicize_cmd.py` — removed DatabaseConfig, uses from_settings()

#### Repository Boolean Type Compatibility
- **Fixed boolean fields for PostgreSQL** — `asyncpg` requires native `bool`, not `int`
  - `ingestion_state_repo.py` — `include_comments`, `comments_unavailable`, `success`
  - `raw_message_repo.py` — `raw_payload_truncated`
  - `agent_state_repo.py` — `is_active`
  - `task_history_repo.py` — `success`
  - Changed from `1 if x else 0` to `bool(x)`

#### Test Fixes
- **E2E tests** — added explicit `db_type="sqlite"` in e2e_settings fixture
- **Migration tests** — added `pytestmark` to skip when `DB_TYPE=postgresql`
- **Run command tests** — added missing `run_cmd.settings` patch

### Tested

#### Session 24 (Initial PostgreSQL Testing)
- Full pipeline on real Telegram channel (@BiocodebySechenov)
- 8 posts ingested, processed, topicized, and exported
- All 411 tests passing

#### Session 25 (Multi-Channel Testing) 🆕
- **4 additional channels tested** with 100% success rate:
  - @durov (46 posts) — технологии/Telegram, EN/RU
  - @telegram (50 posts) — официальный канал, EN
  - @tproger (43 posts) — IT/программирование, RU
  - @habr_com (98 posts) — IT новости, RU
- **Total:** 237 posts processed with **100% success**
- **Performance metrics:**
  - Ingestion: ~80 posts/s
  - Processing: 0.16 posts/s (GPT-4o-mini)
  - 24 topics created
- PostgreSQL backend confirmed stable
- Multi-language support (RU + EN) verified

---

## [3.1.0] - 2025-12-29

### 🎯 v3.1.0 - Production Ready: PostgreSQL & Multi-user Support (Session 24)

**MAJOR RELEASE** - TG_parser теперь production-ready с PostgreSQL, connection pooling, и multi-user support.

#### Added

##### PostgreSQL Support

- **PostgreSQL Database Backend** — production-grade RDBMS
  - `DB_TYPE=postgresql` для production deployments
  - `DB_TYPE=sqlite` для development (backward compatible)
  - Асинхронный драйвер `asyncpg` для высокой производительности
  - `psycopg2-binary` для Alembic migrations
  
- **Connection Pooling** — эффективное управление соединениями
  - `AsyncAdaptedQueuePool` с настраиваемыми параметрами
  - `DB_POOL_SIZE=5` (base connections)
  - `DB_MAX_OVERFLOW=10` (additional connections under load)
  - `DB_POOL_TIMEOUT=30` (connection acquisition timeout)
  - `DB_POOL_RECYCLE=3600` (connection refresh after 1 hour)
  - `DB_POOL_PRE_PING=true` (health check before use)
  
- **Performance Indexes** — 11 новых индексов для оптимизации
  - `ingestion_state`: idx_ingestion_source_id
  - `raw_messages`: idx_raw_source_ref, idx_raw_channel_id, idx_raw_source_channel, idx_raw_date
  - `processed_documents`: idx_processed_source_ref, idx_processed_channel_id
  - `topics`: idx_topics_channel_id
  - `agent_registry`: idx_agents_type, idx_agents_active, idx_agents_type_active

##### Engine Factory

- **Universal Engine Creation** — `tg_parser/storage/engine_factory.py`
  - `create_engine_from_settings()` — автоматический выбор SQLite/PostgreSQL
  - `create_sqlite_engine_config()` — SQLite с NullPool
  - `create_postgres_engine_config()` — PostgreSQL с QueuePool
  - `get_pool_status()` — мониторинг состояния connection pool
  - Password masking для безопасного логирования
  
- **Database Class Refactoring** — обновлен для engine factory
  - `Database.from_settings(settings)` — рекомендуемый способ
  - Backward compatible с `DatabaseConfig`
  - Автоматический выбор backend

##### Migration Tools

- **SQLite → PostgreSQL Migration Script** — `scripts/migrate_sqlite_to_postgres.py`
  - Автоматическая миграция всех 3 БД (ingestion, raw, processing)
  - `--dry-run` режим для тестирования
  - `--verify` для проверки record counts
  - Детальная статистика и progress reporting
  - Error handling с продолжением миграции
  - Поддержка до 12 таблиц
  
- **Alembic PostgreSQL Support** — обновлен `migrations/env.py`
  - Автоматическое определение DB_TYPE из settings
  - PostgreSQL URL building
  - Environment variable override (`ALEMBIC_DATABASE_URL`)
  - Backward compatible с SQLite

##### Docker Compose Production

- **Production-Ready Setup** — обновлен `docker-compose.yml`
  - PostgreSQL service (postgres:16-alpine)
  - Health checks для PostgreSQL
  - Volumes для persistence (`postgres_data`)
  - Connection pool configuration
  - Network isolation (`tg_parser_network`)
  
- **Development Configuration** — новый `docker-compose.dev.yml`
  - SQLite backend для локальной разработки
  - Упрощенная конфигурация
  - Быстрый старт

##### Enhanced Health Checks

- **Database Metrics** — расширен `/health` endpoint
  - `type`: sqlite или postgresql
  - `pool`: connection pool status (type, size, checked_out, overflow)
  - `latency_ms`: database response time
  - PostgreSQL-specific: host, port, database, pool_size
  
- **Pool Monitoring** — real-time pool metrics
  - Количество активных соединений
  - Overflow connections
  - Pool health status

#### Changed

- **Settings** — новые PostgreSQL параметры:
  - `db_type`: sqlite или postgresql
  - `db_host`, `db_port`, `db_name`, `db_user`, `db_password`
  - `db_pool_size`, `db_max_overflow`, `db_pool_timeout`
  - `db_pool_recycle`, `db_pool_pre_ping`
  
- **Health Checks** — обновлены для PostgreSQL:
  - Автоматическое определение database type
  - Pool metrics для PostgreSQL
  - Таблица count для обоих backends

#### Documentation

- **PRODUCTION_DEPLOYMENT.md** — новый полный production guide (500+ lines)
  - Server setup (Ubuntu 22.04)
  - PostgreSQL configuration
  - Docker Compose deployment
  - SSL/TLS setup (Nginx reverse proxy)
  - Monitoring (Prometheus, CloudWatch, Datadog)
  - Backup strategy (automated daily backups)
  - Troubleshooting guide
  - Security checklist
  
- **MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md** — новый migration guide (400+ lines)
  - Когда мигрировать (decision matrix)
  - Pre-migration checklist
  - Пошаговая инструкция
  - Verification procedures
  - Rollback strategy
  - Troubleshooting
  - FAQ (10+ вопросов)
  
- **README.md** — обновлен с PostgreSQL setup
  - Database Setup section (новый)
  - SQLite vs PostgreSQL comparison
  - Quick start для обоих backends
  
- **ENV_VARIABLES_GUIDE.md** — 11 новых DB_* переменных
  - Полная документация PostgreSQL settings
  - Connection pool parameters
  - Рекомендации для development/production
  
- **ENV Templates** — 3 новых файла:
  - `env.example` — общий пример
  - `env.development.example` — SQLite configuration
  - `env.production.example` — PostgreSQL configuration

#### Tests

- **30 новых тестов** для PostgreSQL:
  - `tests/test_postgres_integration.py` (20 тестов):
    - Engine factory (6 тестов)
    - Connection pool (4 теста)
    - PostgreSQL operations (4 теста)
    - Settings validation (3 теста)
    - Health checks (2 теста)
    - Meta test (1 тест)
  - `tests/test_postgres_concurrency.py` (10 тестов):
    - Concurrent writes без deadlocks (3 теста)
    - Pool stress tests (2 теста)
    - E2E с PostgreSQL (2 теста)
    - Migration script tests (2 теста)
    - Meta test (1 тест)
- **1 тест обновлен** для PostgreSQL support:
  - `test_phase3d_advanced.py::test_check_database_missing_file`
- **Общее количество тестов**: **435** (было 405)
- **Test pass rate**: **100%** (435/435 passing)

#### Performance

- **Connection Pool**: < 10ms overhead для получения connection
- **Concurrent Writes**: 5+ processes без deadlocks
- **Migration Speed**: < 5 минут для 1000 сообщений
- **Index Performance**: 2-10x ускорение queries на больших данных
- **Test Execution**: 50.34s для всех 435 тестов

#### Migration Notes

##### Для новых пользователей:
```bash
# Production: PostgreSQL (рекомендуется)
DB_TYPE=postgresql
docker-compose up -d

# Development: SQLite (по умолчанию)
DB_TYPE=sqlite
```

##### Для существующих пользователей:
```bash
# 1. Backup
cp *.sqlite backups/

# 2. Setup PostgreSQL
docker-compose up -d postgres

# 3. Migrate data
python scripts/migrate_sqlite_to_postgres.py --verify

# 4. Switch
DB_TYPE=postgresql
```

#### Breaking Changes

**NONE** — Полная обратная совместимость:
- SQLite продолжает работать как раньше
- Все ENV переменные опциональны
- Default: `DB_TYPE=sqlite`

#### See Also

- `PRODUCTION_DEPLOYMENT.md` — production deployment guide
- `MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md` — database migration guide
- `ENV_VARIABLES_GUIDE.md` — все DB_* переменные
- `docs/notes/START_PROMPT_SESSION24_PRODUCTION.md` — план Session 24

---

## [3.1.0-alpha.2] - 2025-12-29

### 🎯 v3.1.0-alpha.2 - Structured Logging & GPT-5 Support (Session 23)

Production hardening release with structured JSON logging and GPT-5 Responses API support.

#### Added

##### Structured Logging (structlog)

- **JSON Logging Support** — production-ready structured logs
  - `LOG_FORMAT=json` для production (structured JSON, one per line)
  - `LOG_FORMAT=text` для development (human-readable, colored)
  - `LOG_LEVEL` configuration (DEBUG/INFO/WARNING/ERROR/CRITICAL)
  
- **Request ID Propagation** — корреляция логов
  - `request_id` в каждом логе API запросов
  - Автогенерация или использование заголовка `X-Request-ID`
  - Context vars для прокидывания через async границы
  
- **Structured Metadata** — все логи содержат структурированные поля
  - Timestamp, level, logger, event name
  - Дополнительные поля: method, path, duration_ms, error_type и др.
  - jq-friendly формат для фильтрации и анализа

##### GPT-5 / Responses API Support

- **Responses API Integration** — поддержка GPT-5.* моделей
  - Автоматический routing: `/v1/responses` для `gpt-5.*`, `/chat/completions` для остальных
  - `reasoning.effort` параметр: minimal/low/medium/high
  - `verbosity` параметр: low/medium/high
  
- **Configuration** — новые ENV переменные:
  - `LLM_REASONING_EFFORT` (default: low)
  - `LLM_VERBOSITY` (default: low)
  
- **Backward Compatible** — `gpt-4o-mini` и другие модели работают как раньше

##### RetrySettings Integration (Tech Debt from Session 22)

- **Pipeline Integration** — `retry_settings` используется в retry логике
  - Exponential backoff с cap: `min(base * 2^(attempt-1), max)`
  - Jitter для рандомизации: `delay + random(0, delay * jitter)`
  - Конфигурируемо через ENV (`RETRY_*` переменные)

#### Changed

- **Logging** — мигрировано на structlog:
  - `tg_parser.api.main` — structlog logger
  - `tg_parser.api.middleware.logging` — structlog + request_id binding
  - `tg_parser.processing.pipeline` — все логи structured
  - `tg_parser.processing.llm.openai_client` — structlog
  
- **OpenAIClient** — рефакторинг для GPT-5:
  - `_is_gpt5_model()` — detection метод
  - `_generate_chat_completions()` — для GPT-4 и старше
  - `_generate_responses_api()` — для GPT-5.*
  - `reasoning_effort` и `verbosity` в `__init__`

#### Documentation

- **ENV_VARIABLES_GUIDE.md** — полный справочник переменных окружения
  - Все LOG_*, RETRY_*, GPT-5 параметры
  - Примеры для development и production
  - jq рецепты для фильтрации JSON логов
  
- **LLM_SETUP_GUIDE.md** — обновлена секция про GPT-5
  - Описание Responses API
  - Планируемые изменения в Session 23 (completed)

#### Tests

- **12 новых тестов**:
  - `tests/test_logging.py` (7 тестов) — JSON/text format, request_id, context vars
  - `tests/test_gpt5_responses_api.py` (9 тестов) — routing, payload, response parsing
  - `tests/test_retry_settings.py` (9 тестов) — validation, ENV loading, integration
- Общее количество тестов: **393+** (было 381)

#### Migration Notes

- **Logging**: Установите `LOG_FORMAT=json` в production, `LOG_LEVEL=INFO`
- **GPT-5**: Используйте `LLM_MODEL=gpt-5.2` (или gpt-5-mini/gpt-5-nano)
- **Retry**: Настройте через `RETRY_*` переменные (опционально)
- **Backward Compatible**: Существующие конфигурации работают без изменений

#### See Also

- `ENV_VARIABLES_GUIDE.md` — справочник переменных окружения
- `docs/notes/START_PROMPT_SESSION23_LOGGING_GPT5.md` — план Session 23

---

## [3.1.0-alpha.1] - 2025-12-29

### 🔧 v3.1.0-alpha.1 - Foundation & Tech Debt (Session 22)

Foundation release focusing on database migrations and configuration improvements.

#### Added

##### Database Migrations (Alembic)

- **Alembic Integration** — полная поддержка версионирования схемы БД
  - Multi-database support для 3 независимых SQLite баз
  - Initial миграции с полными DDL схемами
  - Отдельные `alembic_version_{db_name}` таблицы для каждой БД
  - Динамическая настройка `version_locations` в `env.py`

- **CLI Commands `db`** — управление миграциями:
  - `tg-parser db upgrade` — применить миграции
  - `tg-parser db downgrade` — откатить миграции
  - `tg-parser db current` — показать текущую версию
  - `tg-parser db history` — история миграций
  - `tg-parser db stamp` — пометить версию

##### Configuration

- **RetrySettings** — конфигурируемые параметры retry через ENV:
  - `RETRY_MAX_ATTEMPTS` (default: 3, range: 1-10)
  - `RETRY_BACKOFF_BASE` (default: 1.0, range: 0.1-60.0)
  - `RETRY_BACKOFF_MAX` (default: 60.0, range: 1.0-300.0)
  - `RETRY_JITTER` (default: 0.3, range: 0.0-1.0)

#### Changed

- **`init` command** — обновлена для использования Alembic миграций с fallback на DDL
- **Documentation** — обновлена структура docs:
  - Архивированы устаревшие документы → `docs/notes/archive/`
  - Создан новый `docs/notes/current-state.md` для v3.0.0
  - Добавлен `SESSION22_SUMMARY.md`

#### Dependencies

- `alembic>=1.13` — database migrations

#### Tests

- **8 новых тестов** в `tests/test_migrations.py`:
  - Migration upgrade tests (3 databases)
  - Migration downgrade tests (3 databases)
  - Multi-database independence test
  - Version table per database test
- Общее количество тестов: **381** (было 373)

#### Migration Notes

- Alembic infrastructure готова для staging deployment
- Миграции работают базово, требуют финализации для production
- `init` команда автоматически применяет миграции
- Для существующих БД рекомендуется использовать `db stamp` для синхронизации

#### Known Limitations

- Миграции пока создают только version tables
- Основные таблицы создаются через fallback DDL
- Требуется дополнительная отладка для полного применения миграций (Session 23)

---

## [3.0.0] - 2025-12-28

### 🎉 v3.0.0 Release - Multi-Agent Architecture

This is the first stable release of the v3.0 Multi-Agent Architecture. See [MIGRATION_GUIDE_v2_to_v3.md](MIGRATION_GUIDE_v2_to_v3.md) for upgrade instructions.

#### Key Features

- **Multi-Agent Architecture** — OrchestratorAgent, ProcessingAgent, TopicizationAgent, ExportAgent
- **Agent State Persistence** — сохранение состояния агентов, истории задач, статистики
- **Agent Observability** — CLI команды `agents`, API endpoints, архивация истории
- **HTTP API v2** — FastAPI с Auth, Rate Limiting, Webhooks, Prometheus Metrics
- **Background Scheduler** — автоматическая очистка и health checks
- **Hybrid Mode** — agent + v1.2 pipeline для адаптивной обработки
- **373+ тестов** — 100% проходят

### Added

#### E2E Integration Tests (Session 21 Phase 3 Finalization)

- **7 новых E2E тестов**:
  - `test_full_cli_workflow` — полный CLI workflow с persistence
  - `test_full_api_workflow` — полный API workflow с TestClient
  - `test_handoff_workflow` — тестирование handoff протокола
  - `test_archive_workflow` — тестирование архивации истории
  - `test_multi_agent_e2e_workflow` — multi-agent pipeline E2E
  - `test_multi_agent_workflow_execution` — workflow execution через orchestrator
  - `test_multi_agent_registry_persistence_sync` — синхронизация registry с persistence

#### Documentation

- **MIGRATION_GUIDE_v2_to_v3.md** — полное руководство по миграции с v2.x на v3.0
- Обновлён README.md с ссылками на Migration Guide

### Tests

- Общее количество тестов: **373** (было 366)
- Все тесты проходят ✅

---

## [3.0.0-alpha.4] - 2025-12-28

### Added

#### Advanced Features (Session 20 Phase 3D) ⭐

- **Prometheus Metrics** (`/metrics` endpoint):
  - HTTP request metrics (count, latency, size)
  - Agent task metrics (count, duration, status)
  - LLM request metrics (provider, model, tokens)
  - Job metrics (active, total)
  - Custom metric helper functions

- **Background Scheduler** (APScheduler):
  - Periodic cleanup of expired records
  - Periodic health checks
  - Configurable intervals
  - Graceful shutdown

- **Health Checks v2**:
  - `GET /status/detailed` — detailed component health
  - `GET /scheduler` — scheduler status and tasks
  - Real database connectivity check
  - LLM provider ping
  - Agent registry status
  - Scheduler status

### Configuration

- `METRICS_ENABLED` — enable Prometheus metrics (default: true)
- `SCHEDULER_ENABLED` — enable background scheduler (default: true)
- `SCHEDULER_CLEANUP_INTERVAL_HOURS` — cleanup interval (default: 24)
- `SCHEDULER_HEALTH_CHECK_INTERVAL_MINUTES` — health check interval (default: 5)
- `OLLAMA_BASE_URL` — Ollama server URL (default: http://localhost:11434)

### Dependencies

- `prometheus-fastapi-instrumentator>=7.0`
- `apscheduler>=3.10`

### Tests

- **26 новых тестов** в `tests/test_phase3d_advanced.py`
- Общее количество тестов: **366** (было 340)
- Все тесты проходят ✅

### Documentation

- Создан `docs/notes/SESSION20_PHASE3D_COMPLETE.md`

---

## [3.0.0-alpha.3] - 2025-12-28

### Added

#### Agent Observability (Session 19 Phase 3C) ⭐
- **CLI группа `agents`**: новые команды для мониторинга агентов
  - `agents list` — список всех агентов с фильтрами (--type, --active)
  - `agents status <name>` — статистика агента (--days для периода)
  - `agents history <name>` — история задач (--limit, --errors)
  - `agents cleanup` — очистка истёкших записей (--dry-run, --archive)
  - `agents handoffs` — статистика handoff'ов (--stats, --agent)
  - `agents archives` — список архивных файлов
- **API Endpoints (Agent Observability)**:
  - `GET /api/v1/agents` — список агентов с метаданными
  - `GET /api/v1/agents/{name}` — информация об агенте
  - `GET /api/v1/agents/{name}/stats` — статистика агента за период
  - `GET /api/v1/agents/{name}/history` — история задач с пагинацией
  - `GET /api/v1/agents/stats/handoffs` — статистика handoff'ов
- **AgentHistoryArchiver**: архивация истёкших записей
  - Экспорт в NDJSON.gz формат
  - Поддержка task_history и handoff_history
  - Автоматическая очистка после архивации
  - Список архивов с метаданными
- **Pydantic Response Models**: типизированные ответы API
  - `AgentListResponse`, `AgentInfoResponse`
  - `AgentStatsResponse`, `TaskHistoryResponse`
  - `HandoffStatsResponse`

### Configuration
- `AGENT_ARCHIVE_ENABLED` — включить архивацию (default: false)
- `AGENT_ARCHIVE_PATH` — путь для архивов (default: ./data/archives)

### Tests
- **15 новых тестов** в `tests/test_agents_observability.py`
- Общее количество тестов: **340** (было 325)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION19_PHASE3C_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION20_PHASE3D.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, README.md, CHANGELOG.md
- Обновлены: tests/README.md, docs/notes/README.md

---

## [3.0.0-alpha.2] - 2025-12-28

### Added

#### Agent State Persistence (Session 18 Phase 3B) ⭐
- **AgentPersistence Layer**: unified интерфейс для работы с persistence
  - Сохранение состояния агентов при регистрации
  - Восстановление статистики при рестарте
  - Полное хранение input/output задач с TTL
  - Агрегированная статистика по дням
- **AgentStateRepo**: хранение метаданных и статистики агентов
  - Сохранение capabilities, model, provider
  - Накопление total_tasks, total_errors, avg_processing_time
  - Автообновление при выполнении задач
- **TaskHistoryRepo**: полная история задач
  - Хранение полного input_json/output_json
  - Настраиваемый TTL через `expires_at`
  - Фильтрация по агенту, каналу, датам
  - Метод `cleanup_expired()` для очистки
- **AgentStatsRepo**: агрегированная статистика по дням
  - Ежедневные агрегаты: total_tasks, successful, failed
  - min/max/avg processing time
  - Сохраняется даже после очистки task_history
- **HandoffHistoryRepo**: история handoffs между агентами
  - Tracking статусов: pending → accepted → completed
  - Время обработки и ошибки
  - Статистика по парам агентов
- **Registry интеграция**:
  - `register_with_persistence()` — регистрация + сохранение + восстановление
  - `unregister_with_persistence()` — отмена + пометка inactive
  - `record_task_completion_with_persistence()` — запись в history + stats

### Database
- **4 новые таблицы** в `processing_storage.sqlite`:
  - `agent_states` — состояние агентов с метаданными и статистикой
  - `task_history` — полная история задач с TTL
  - `agent_stats` — ежедневная агрегированная статистика
  - `handoff_history` — история handoffs между агентами

### Configuration
- `AGENT_RETENTION_DAYS` — TTL для task_history (default: 14)
- `AGENT_RETENTION_MODE` — delete | export (default: delete)
- `AGENT_ARCHIVE_PATH` — путь для архивации
- `AGENT_STATS_ENABLED` — включить агрегацию статистики
- `AGENT_PERSISTENCE_ENABLED` — включить persistence

### Tests
- **25 новых тестов** в `tests/test_agent_persistence.py`
- Общее количество тестов: **325** (было 300)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION18_PHASE3B_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION19_PHASE3C.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, architecture.md, README.md, CHANGELOG.md

---

## [3.0.0-alpha.1] - 2025-12-28

### Added

#### Multi-Agent Architecture (Session 17 Phase 3A) ⭐
- **Base Agent Protocol**: стандартизированный интерфейс для всех агентов
  - `BaseAgent` абстрактный класс с lifecycle методами
  - `AgentInput`/`AgentOutput` типизированные контракты
  - `AgentCapability`/`AgentType` enum'ы для классификации
- **Agent Registry**: централизованное управление агентами
  - Регистрация/отмена регистрации агентов
  - Поиск по типу и capabilities
  - Статистика выполнения задач
  - Health checks
- **Handoff Protocol**: обмен данными между агентами
  - `HandoffRequest`/`HandoffResponse` структуры
  - `HandoffStatus` для отслеживания состояния
  - Приоритеты и контекст передачи
- **OrchestratorAgent**: координация workflow
  - Управление workflow'ами
  - Маршрутизация задач к специализированным агентам
  - Lifecycle management для всех агентов
- **Specialized Agents**:
  - `ProcessingAgent` — очистка текста, извлечение тем/entities, routing (simple/deep)
  - `TopicizationAgent` — кластеризация документов по темам
  - `ExportAgent` — экспорт в NDJSON/JSON форматы
- **CLI флаг `--multi-agent`**: активация multi-agent режима
  - `tg-parser process --channel @lab --multi-agent`
  - `tg-parser process --channel @lab --multi-agent --provider anthropic`

### Architecture
- Hybrid подход: Specialized Agents (Variant A) + элементы Agentic Workflow (Variant C)
- Routing внутри ProcessingAgent для адаптивной обработки
- Расширяемая архитектура через Agent Registry

### Tests
- **42 новых теста** в `tests/test_multi_agent.py`
- Общее количество тестов: **300** (было 258)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION17_PHASE3A_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION18_PHASE3B.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, architecture.md, README.md
- Обновлена пользовательская документация: USER_GUIDE.md, pipeline.md, LLM_SETUP_GUIDE.md, QUICKSTART_v1.2.md

---

## [2.0.0-alpha.4] - 2025-12-28

### Added

#### API Production (Session 16 Phase 2F) ⭐
- **API Key Authentication**: защита endpoints через X-API-Key header
  - Конфигурируемые ключи через `API_KEYS` environment variable
  - Режим разработки (auth опционален) и production (auth обязателен)
- **Rate Limiting**: защита от перегрузки через slowapi
  - Настраиваемые лимиты для `/process`, `/export` endpoints
  - По умолчанию: 10/min для process, 20/min для export
- **Webhooks**: уведомления о завершении задач
  - HMAC-SHA256 подписи для верификации
  - Retry с экспоненциальным backoff
  - Стандартный payload для job completion/failure
- **Request Logging**: структурированное логирование с X-Request-ID
  - Автоматическая генерация UUID для каждого запроса
  - Сохранение пользовательского X-Request-ID
  - Duration tracking
- **Persistent Job Storage**: SQLite хранилище для job state
  - `Job` модель с полным lifecycle tracking
  - `JobRepo` интерфейс (порт) и SQLite реализация
  - `JobStore` singleton для API routes
  - Таблица `api_jobs` в processing_storage.sqlite
- **Configurable CORS**: CORS_ORIGINS через environment

### Tests
- **38 новых тестов** (22 в test_api_security.py, 16 в test_job_storage.py)
- Общее количество тестов: **258** (было 219)
- Исправлено зависание тестов из-за незакрытых SQLite соединений
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION16_PHASE2F_COMPLETE.md`
- Обновлены CHANGELOG.md, DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, README.md

---

## [2.0.0-alpha.3] - 2025-12-28

### Added

#### Hybrid Agent Mode (Session 15 Phase 2E) ⭐
- **Pipeline Tool**: v1.2 pipeline как инструмент агента
  - `process_with_pipeline` — глубокая обработка через проверенный pipeline
  - `PipelineResult` — структурированный результат с metadata
  - Автоматический fallback на basic processing при недоступности pipeline
  - On-demand создание pipeline если не передан в контексте
- **AgentContext update**: добавлено поле `pipeline` для hybrid mode
- **TGProcessingAgent update**: 
  - Новый параметр `use_pipeline_tool` для включения pipeline tool
  - Новый параметр `pipeline` для передачи экземпляра pipeline
  - Динамическое формирование инструкций агента для hybrid mode
- **CLI флаг `--hybrid`**: включает v1.2 pipeline как tool агента
  - `tg-parser process --channel @lab --agent --hybrid` — basic + pipeline (4 tools)
  - `tg-parser process --channel @lab --agent --agent-llm --hybrid` — LLM + pipeline (2 tools)
- **InMemoryProcessedDocumentRepo**: in-memory репозиторий для on-demand pipeline

### Performance
- **Hybrid режим**: адаптивная обработка — простые сообщения через basic tools, сложные через pipeline
- Agent выбирает оптимальный инструмент в зависимости от сложности сообщения

### Tests
- **32 новых теста** в `tests/test_agents_phase2e.py`
- Общее количество тестов: **219** (было 187)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION15_PHASE2E_COMPLETE.md`
- Обновлены CHANGELOG.md, DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md

---

## [2.0.0-alpha.2] - 2025-12-27

### Added

#### Agents Integration (Session 14 Phase 2C) ⭐
- **LLM-Enhanced Tools**: глубокий семантический анализ через LLM
  - `analyze_text_deep` — комплексный анализ с key_points и sentiment
  - `extract_topics_llm` — семантическое извлечение тем
  - `extract_entities_llm` — NER через LLM
- **AgentContext**: dataclass для передачи LLM client в tools
- **DeepAnalysisResult**: расширенная модель с key_points и sentiment
- **CLI флаги**:
  - `--agent` — использовать agent-based processing
  - `--agent-llm` — включить LLM-enhanced tools
- **Multi-provider support**: агент поддерживает OpenAI, Anthropic, Gemini, Ollama
- **Quality comparison script**: `scripts/compare_agents_pipeline.py`

### Performance
- **Agent Basic**: ~0.3ms/сообщение (1000x быстрее pipeline) без LLM вызовов
- Автоматический fallback к pattern matching при отсутствии LLM

### Tests
- **14 новых тестов** для Phase 2C
- Общее количество тестов: **187** (было 174)
- Все тесты проходят ✅

### Documentation
- Обновлён USER_GUIDE.md с секцией об Agent-based Processing
- Обновлён README.md с новыми CLI флагами
- Создан SESSION14_PHASE2C_COMPLETE.md

---

## [2.0.0-alpha.1] - 2025-12-27

### Added

#### HTTP API (Session 14 Phase 2A) ⭐
- **FastAPI HTTP API**: полноценный REST API для TG_parser
- **8 endpoints** в трёх группах:
  - `/health`, `/status` — health checks и статус системы
  - `/api/v1/process`, `/api/v1/status/{job_id}`, `/api/v1/jobs` — управление обработкой
  - `/api/v1/export`, `/api/v1/export/status/{job_id}`, `/api/v1/export/download/{job_id}` — экспорт
- **CLI команда `tg-parser api`**: запуск сервера с параметрами `--port`, `--host`, `--reload`
- **OpenAPI/Swagger**: автодокументация на `/docs` и `/redoc`
- **CORS middleware**: поддержка cross-origin запросов
- **Job-based processing**: асинхронная обработка с отслеживанием статуса

#### OpenAI Agents SDK PoC (Session 14 Phase 2B) ⭐
- **Новый модуль `tg_parser/agents/`**: интеграция с OpenAI Agents SDK
- **TGProcessingAgent**: агент для обработки сообщений с тремя tools:
  - `clean_text` — очистка и нормализация текста
  - `extract_topics` — извлечение тем и генерация summary
  - `extract_entities` — извлечение сущностей (email, URL, phone, hashtags, etc.)
- **Function tools**: используют `@function_tool` декоратор из agents SDK
- **Batch processing**: `process_batch_with_agent()` с настройкой concurrency

### Tests
- **24 теста для HTTP API** в `tests/test_api.py`
- **24 теста для Agents** в `tests/test_agents.py`  
- Общее количество тестов: 174 (было 126)
- Все тесты проходят ✅

### Dependencies
- `openai-agents>=0.6` — OpenAI Agents SDK
- `fastapi>=0.115`, `uvicorn>=0.32` — уже были для API

## [1.2.0] - 2025-12-27

### Added

#### Multi-LLM Support ⭐
- **AnthropicClient**: поддержка Claude models (claude-sonnet-4-20250514)
- **GeminiClient**: поддержка Google Gemini models (gemini-2.0-flash-exp, gemini-1.5-pro)
- **OllamaClient**: поддержка локальных LLM через Ollama (qwen3:8b, llama3.2, mistral, etc.)
- **Factory**: `create_llm_client()` для создания клиентов по провайдеру
- CLI флаги `--provider` и `--model` для выбора LLM
- Environment variables: `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`

#### Performance
- **Parallel processing**: флаг `--concurrency` для параллельной обработки сообщений
- `ProcessingPipelineImpl._process_batch_parallel()` с `asyncio.Semaphore`
- Реальное ускорение: до 3x при `--concurrency 5` для облачных провайдеров

#### Docker & CI/CD
- **Dockerfile**: multi-stage build для production (370MB image)
- **docker-compose.yml**: compose файл с опциональным Ollama service
- **GitHub Actions CI**: автоматическое тестирование, линтинг, Docker build
- Markdown link checking в CI

#### PromptLoader Integration
- `ProcessingPipelineImpl` использует `PromptLoader` по умолчанию
- Model settings (temperature, max_tokens) загружаются из YAML
- Fallback на hardcoded промпты если YAML не найден

#### Documentation
- **TESTING_RESULTS_v1.2.md**: полный отчёт о тестировании
- **MIGRATION_GUIDE_v1.1_to_v1.2.md**: руководство по миграции
- Обновлённые README.md и USER_GUIDE.md с Multi-LLM примерами

### Fixed
- **Anthropic JSON parsing**: Claude иногда возвращает JSON в markdown блоках (`\`\`\`json`), добавлена функция `extract_json_from_response()` для корректного парсинга
- **Anthropic model name**: обновлено с устаревшего `claude-3-5-sonnet-20241022` на актуальное `claude-sonnet-4-20250514`
- **docker-compose.yml**: удалён устаревший атрибут `version`

### Changed
- `tg_parser/processing/pipeline.py`: обновлена `create_processing_pipeline()` для Multi-LLM
- `tg_parser/cli/process_cmd.py`: добавлены параметры `provider`, `model`, `concurrency`
- `tg_parser/cli/app.py`: обновлена команда `process` с новыми флагами
- `tg_parser/config/settings.py`: добавлен `gemini_api_key`

### Performance Benchmarks

| Provider | Model | Throughput | Quality |
|----------|-------|------------|---------|
| OpenAI | gpt-4o-mini | 0.120 msg/s | Good |
| Anthropic | claude-sonnet-4-20250514 | 0.121 msg/s | Best (90% entities) |
| Gemini | gemini-2.0-flash-exp | 0.342 msg/s | Great (fastest!) |
| Ollama | qwen3:8b | 0.024 msg/s | Good |

### Tests
- Добавлено 23 новых теста в `tests/test_llm_clients.py`
- Общее количество тестов: 126 (было 103)
- Все тесты проходят ✅
- Протестированы все 4 LLM провайдера на реальных данных

## [1.1.0] - 2025-12-26

### Added
- **Configurable Prompts (YAML)**: Prompts can now be customized via YAML files in `prompts/` directory
  - `prompts/processing.yaml` - Processing prompts
  - `prompts/topicization.yaml` - Topicization prompts
  - `prompts/supporting_items.yaml` - Supporting items prompts
  - `prompts/README.md` - Documentation for YAML format
- **PromptLoader class** (`tg_parser/processing/prompt_loader.py`): 
  - Loads prompts from YAML with fallback to defaults
  - Caching support
  - Helper methods: `get_system_prompt()`, `get_user_template()`, `get_model_settings()`
- **`--retry-failed` flag** for `process` command: Retry only failed messages
- **`list_all()` method** in ProcessedDocumentRepo: Export all channels without filter
- **`get_channel_usernames()` method** in IngestionStateRepo: Get channel username mappings
- **Improved LLM response validation**: 
  - Validates required fields
  - Fills defaults for optional fields
  - Normalizes entity confidence scores
- **18 new tests** for PromptLoader (total: 103 tests)

### Fixed
- Export command now works without `--channel` filter
- Telegram URLs now correctly include channel usernames when available

### Changed
- Dependencies: added `PyYAML>=6.0`

### Technical Debt Resolved
- Removed TODO at `export_cmd.py:82` (list_all implemented)
- Removed TODO at `export_cmd.py:99` (usernames implemented)

## [1.0.0] - 2025-12-25

### Added
- Initial production-ready release
- **Ingestion Pipeline**: Telethon-based Telegram message collection
  - Posts and comments support
  - Incremental and snapshot modes
  - Cursor-based pagination
- **Processing Pipeline**: LLM-based message processing
  - Text cleaning and normalization
  - Entity extraction
  - Topic detection
  - Language detection
- **Topicization Pipeline**: Message clustering into topics
  - Singleton and cluster topics
  - Anchor-based topic cards
  - Supporting items with relevance scores
- **Export System**:
  - `kb_entries.ndjson` - Knowledge base entries
  - `topics.json` - Topic catalog
  - `topic_<id>.json` - Detailed topic files
- **CLI Commands**:
  - `init` - Initialize databases
  - `add-source` - Add ingestion source
  - `ingest` - Run ingestion
  - `process` - Run processing
  - `topicize` - Run topicization
  - `export` - Export artifacts
  - `run` - One-shot full pipeline
- **Storage**:
  - SQLite-based storage (3 databases)
  - Idempotent operations
  - Cursor management

### Technical
- 85 tests passing
- 99.76% success rate on 846 real messages
- Pydantic v2 domain models
- Async/await architecture
- Type hints throughout

