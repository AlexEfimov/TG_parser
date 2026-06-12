# START PROMPT — Wave 1 tech-debt closure

**Дата создания:** 2026-06-12 (конец сессии консолидации tech-debt) · **Для:** новой (свежей) сессии: обсуждение развилок → фикс → реализация по закрытию actionable Wave 1 tech debt, до старта Wave 2 planning.
**Goal (одной строкой):** закрыть actionable-долг, каталогизированный в [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md), в согласованной волновой последовательности (Wave A → B → C), прежде чем переходить к планированию Wave 2.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** branch `main`; `git commit` и деплой — **только по явному запросу пользователя**; `docs/methodology/**` — вне этого workspace (не трогать, не создавать); `pyproject.toml`/`requirements.txt` — не трогать без явного запроса. Принцип сессий S1/S2/S3: **сначала обсуждаем дизайн → фиксируем развилки → потом реализуем**; dry-run/advisory по умолчанию, мутации — явное действие оператора. Scope каждой волны строго ограничен своими item-ами; unrelated-код не задевать.

---

## 1. Контекст — где мы сейчас

Wave 1 (Living-KB MVP surface parity, F4-B workspaces, F6 digest, F11 watchlist, ADR 0010–0014 watchlist scoring rework) закрыт по [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md). По итогам двух разборов (F11 watchlist S1–S3 + Wave 1 closure review) накопился хвост долга, который сведён в единый инвентарь [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md):

- **§ A** — open actionable debt (то, что закрываем в этой дорожке).
- **§ B** — accepted / by-design (НЕ долг; не перезаводить как баги).
- **§ C** — forward-roadmap (MVP→P2; вне scope Wave-1-debt — это уже Wave 2 planning).

Все actionable-item-ы зафиксированы в [`BUG_LOG.md`](BUG_LOG.md) § «Wave 1 tech-debt consolidation» как **BUG-054…060** (+ ранее заведённые BUG-008/019/020/021 и TD-ids). Эта сессия закрывает их по волнам.

**Что уже на проде (предыдущие сессии, не переделывать):**
- F11 watchlist threshold arc: ADR-0010 (topk-агрегация), ADR-0011 (backfill rework), ADR-0012 (авто-калибровка порога), ADR-0013 (precision floor 0.45), ADR-0014 (batch / silent delivery). Коммиты `44b1ca3`, `888ecbe`, `221f75f`, `52a2ea8`.
- Bot-UX фиксы BUG-025/026/027 (коммит `13d2200`, prompt v1.7.7); закрытия BUG_LOG (`55a2554`, pushed).
- Doc-only консолидация (эта сессия): `WAVE1_TECH_DEBT.md` + BUG-054…060 в BUG_LOG + inline-фикс BUG-005-B stale-status.

---

## 2. Согласованный план (волны)

Закрываем долг тремя волнами. **Sequencing: Wave A (параллельно) → Wave B → Wave C.** Затем — отдельно — Wave 2 planning (после закрытия долга, не в этой дорожке).

### Wave A — параллельный пакет (три file-независимых потока, можно вести одновременно)

Три потока ниже **не пересекаются по файлам** и могут идти конкурентно (разные PR):

- **Sprint 1 — resilience bundle + смежный PR:**
  - **BUG-019** — LLM JSON-parse retry пересылает идентичный промпт → детерминированный тройной фейл на malformed-JSON пути (`tg_parser/processing/pipeline.py` retry-блок; `processing/topicization.py`).
  - **BUG-020** — нет экспоненциального backoff/jitter на Anthropic HTTP 5xx (520/529/503); **в одном bundle с BUG-019** (`pipeline.py` HTTP-client wrapper).
  - **BUG-021** — `get_cross_channel_stats` игнорирует таблицу `topic_links` (только keyword-overlap; semantic-связи не всплывают) — **отдельный, но смежный PR** (`services/analytics_service.py`; `mcp_server.py` `get_cross_channel_stats`).
- **Sprint 3 — test/CI hygiene:**
  - **BUG-056** — `conftest._reset_test_db_schema` DROP/CREATE SCHEMA гонка под параллельным Postgres → `DuplicateSchema` (`tests/conftest.py:125–161`).
  - **BUG-057** — устаревшие pre-fix `skipif`-гарды в 3 тест-файлах (`test_bot_chat_target_resolution.py`, `test_bot_channel_name_parser.py` 6×, `test_bot_delete_routing_bug047.py`).
  - **TD-confirm-flow-concurrency-integration** — пропущенный two-confirm race-тест → integration-харнес (`tests/test_bot_confirm_flow.py:1199–1215`).
  - **BUG-059** — нет CI-job под `@compose_only` integration-тесты (`.github/workflows/ci.yml`; `tests/test_compose_pipeline_dispatch_integration.py`).
- **N+1 fix — BUG-055:** `check_interests` hot-path per-ref embedding fetch (`get_by_source_ref`) → батч `get_many_by_source_refs` (частичная adoption ADR-0011); вторичный сайт — `notify()` re-`get` каждого интереса в цикле (`watchlist_service.py:1148` + `1508`; батч-путь `1367`/`1762`).

### Wave B — BUG-054 (watchlist update-path recalibration)

**DESIGN DECISION УЖЕ ЗАФИКСИРОВАН = HYBRID:**
- при изменении text-полей (`keywords` / `description` / `channels`) — **всегда** ре-эмбеддить интерес;
- порог **авто-рекалибровать только если он изначально был auto-set**; **manually-set порог сохраняется** — для него возвращается только advisory `suggested_threshold` (не перезаписывается).
- Требует новый provenance-флаг `threshold_source: auto|manual` на интересе. **NB: вероятно нужна DB-миграция — явно проговорить это в начале реализации.**
- Формализовать как **ADR-0015** в той же сессии.

Файлы: `tg_parser/services/watchlist_service.py` `_apply_upsert` (948–1033); embedding-путь (ADR-0011); calibration-путь (ADR-0012). Связано: ADR-0012 §R5 (deferred follow-up), BUG-055 (смежный watchlist-touch — естественно бандлить).

### Wave C — observability + doc-hygiene

- **BUG-058** — `tg_pipeline_trigger_total{surface}` всегда `surface="api"`; `mcp`/`bot` label-значения недостижимы (HTTP-граница ADR-0007 теряет origin). Протащить originating surface через dispatch (`api/routes/pipeline.py:89`; `services/pipeline_dispatch_service.py:95–153`).
- **BUG-060** — alert-правила должны гейтиться на `semantic_available`: `combined=1.0` / `semantic=0.0` — это **намеренный keyword-only режим, НЕ баг**; долг — только в alert-rule (Grafana provisioning). Scoring не трогать.
- **TD-bot-confirm-coverage-completeness** — добавить admin write-tools (`register_user`, `add_user_auth`, …) в confirm-gate `_WRITE_TOOLS_REQUIRING_CONFIRM` (`tg_parser/bot/tools.py:99–103`).
- **Doc-drift:**
  - **DOC-001** — устаревший bot username `@smoke_tgparser_bot` → `@Tgingest_bot` (`docs/prompts/DEV_RESURRECTION_PROMPT.md:26`).
  - Устаревший `START_PROMPT`-инвентарь (`REVIEW_2026-06-03_WAVE1_DONE.md` § 11).
  - `ROADMAP_KARPATHY_LIKE_LIVING_KB.md` Wave D + `PLANNING_NEXT_CONTRACT_PREP.md` — F11 P2 / batch / threshold перечислены как «future», но **superseded ADR-0010–0014** — проставить cross-link на ADR.

---

## 3. Definition of Done (нормативно для КАЖДОЙ волны, по требованию пользователя)

- [ ] **Self-review созданных тестов** — ассерты проверяют реальное целевое поведение (не тавтологичны), покрывают edge-cases + negative paths, а не просто «зелёные».
- [ ] **Полный прогон тестов с БД:** `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` (PR-standard; ожидаем ~3217 passed / ~16 env-gated skips). Проанализировать **любой** новый skip/fail — не только scoped-подмножество. Запускать вне sandbox (`required_permissions: all`).
- [ ] **ruff** чисто на изменённых файлах; существующие watchlist/F11/bot-тесты зелёные.
- [ ] **commit + deploy — только по явному go-ahead пользователя**; per-bug закрывающие строки в BUG_LOG (конвенция BUG-028) с commit-ref + evidence.

---

## 4. Out of scope / НЕ Wave-1 debt (не затягивать)

- **§ B accepted-by-design** (НЕ перезаводить как баги): `min_threshold 0.45` precision floor; sync-латентность калибровки; batch-cron в bot-процессе; SILENT journal `notified=True`; O-1 non-atomic workspace move; Q6 polymorphic targets отсутствуют в HTTP-схемах; streaming scorer отложен; knee/gap threshold-детекция отклонена.
- **§ C forward-roadmap** (это уже Wave 2 planning, не долг): F5-C P2; F11 HTTP CRUD; S4 multilang tokenizer; F1 Full (DB-backed prompts/versioning/A-B); webhook subscription target (ADR-0008 polymorphic target).

---

## 5. Параллельные ops (вне волн, по календарю)

Формальный **§4 topk-monitoring review** — окно **2026-06-15 → 2026-06-22** ([`CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md`](CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md)). Decision-gate эскалации широких интересов: `exclude_keywords` → `+0.05` к порогу → channel narrowing. Траектория **GREEN** на ~5-й день. Это не блокирует волны A–C, но review-окно надо отработать по календарю.

---

## 6. Артефакты для контекста (прочитать в начале сессии)

- **Инвентарь:** [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) (карта долга + триаж § A/B/C/D).
- **Backlog of record:** [`BUG_LOG.md`](BUG_LOG.md) — BUG-054…060 (§ «Wave 1 tech-debt consolidation») + referenced BUG-008 / BUG-019 / BUG-020 / BUG-021; TD-bot-confirm-coverage-completeness, TD-confirm-flow-concurrency-integration.
- **ADR (watchlist arc):** [`0010`](../adr/0010-watchlist-keyword-aggregation.md), [`0011`](../adr/0011-watchlist-backfill-rework.md), [`0012`](../adr/0012-watchlist-threshold-calibration.md), [`0013`](../adr/0013-watchlist-threshold-precision-floor.md), [`0014`](../adr/0014-watchlist-batch-silent-delivery.md); для Wave A/C — [`0007`](../adr/0007-mcp-scheduler-dispatch.md) (MCP→scheduler HTTP dispatch).
- **Ops:** [`CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md`](CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md).
- **Рабочий режим:** [`AGENTS.md`](../../AGENTS.md); режимы pytest — [`tests/README.md`](../../tests/README.md).
- **Прод (если потребуется проверка):** `ssh prod` (HostName 212.72.189.15, Port 2296, User user), `~/TG_parser`, docker compose.

---

## 7. Стартовая реплика для новой сессии (можно скопировать)

> Берёмся за закрытие Wave 1 tech debt. Прочитай [`docs/notes/START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](docs/notes/START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md), [`docs/notes/WAVE1_TECH_DEBT.md`](docs/notes/WAVE1_TECH_DEBT.md) и записи BUG-054…060 в BUG_LOG. План: Wave A (параллельно — Sprint 1 resilience BUG-019/020 + смежный BUG-021; Sprint 3 test/CI hygiene BUG-056/057/059 + TD-confirm-flow-concurrency; N+1 fix BUG-055) → Wave B (BUG-054, дизайн уже зафиксирован = HYBRID, формализуем как ADR-0015, возможна DB-миграция) → Wave C (observability BUG-058/060 + confirm-gate TD + doc-drift DOC-001). Начнём с Wave A: обсудим развилки по каждому потоку, потом фиксы. DoD на каждую волну: self-review тестов, полный прогон `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` вне sandbox, ruff чисто, закрывающие строки в BUG_LOG. Режим: коммит/деплой — только по моему явному запросу; сначала дизайн, потом код; `docs/methodology/**` и `pyproject.toml`/`requirements.txt` не трогать.
