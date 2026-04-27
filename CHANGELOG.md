# Changelog

All notable changes to TG_parser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

