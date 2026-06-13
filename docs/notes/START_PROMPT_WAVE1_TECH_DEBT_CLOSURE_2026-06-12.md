# START PROMPT — Wave 1 tech-debt closure

> **Status: IMPLEMENTED / Wave 1 tech-debt track closed 2026-06-13** — all § A actionable items resolved on `main` across Wave A–C (per-item commit-refs in [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) § A); only **BUG-008** (MCP transport hang) remains `open`, explicitly **deferred** to Wave 2. Aggregate authority: [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) § 12.

**Дата создания:** 2026-06-12 (конец сессии консолидации tech-debt) · **Для:** новой (свежей) сессии: обсуждение развилок → фикс → реализация по закрытию actionable Wave 1 tech debt, до старта Wave 2 planning.
**Goal (одной строкой):** закрыть actionable-долг, каталогизированный в [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md), в согласованной волновой последовательности (Wave A → B → C), прежде чем переходить к планированию Wave 2.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** branch `main`; `git commit` и деплой — **только по явному запросу пользователя**; `docs/methodology/**` — вне этого workspace (не трогать, не создавать); `pyproject.toml`/`requirements.txt` — не трогать без явного запроса. Принцип сессий S1/S2/S3: **сначала обсуждаем дизайн → фиксируем развилки → потом реализуем**; dry-run/advisory по умолчанию, мутации — явное действие оператора. Scope каждой волны строго ограничен своими item-ами; unrelated-код не задевать.

---

## 1. Контекст — где мы сейчас

Wave 1 (Living-KB MVP surface parity, F4-B workspaces, F6 digest, F11 watchlist, ADR 0010–0014 watchlist scoring rework) закрыт по [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md). По итогам двух разборов (F11 watchlist S1–S3 + Wave 1 closure review) накопился хвост долга, который сведён в единый инвентарь [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md):

- **§ A** — actionable debt (закрыта 2026-06-13 во всех волнах; открыт только BUG-008, deferred).
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

### Wave A — пакет из трёх логических потоков (преимущественно параллельных)

Три **логических потока** ниже в основном независимы по файлам и могут идти конкурентно (разные PR) — **с одной оговоркой по файловому пересечению:** BUG-055 (`check_interests` N+1) живёт в `tg_parser/services/watchlist_service.py`, **в том же файле, что и Wave B BUG-054** (`_apply_upsert`). Значит на этом файле merge **последовательный, не параллельный**. Рекомендация: выпустить **BUG-055 первым** — маленьким standalone N+1 PR во главе Wave A, на который Wave B BUG-054 затем ложится сверху (альтернатива — забандлить BUG-055 в Wave B watchlist-PR; в любом случае — последовательно по этому файлу).

- **Sprint 1 — resilience bundle + смежный PR:**
  - **BUG-019** — LLM JSON-parse retry пересылает идентичный промпт → детерминированный тройной фейл на malformed-JSON пути (`tg_parser/processing/pipeline.py` retry-блок; `tg_parser/processing/topicization.py`).
  - **BUG-020** — нет экспоненциального backoff/jitter на Anthropic HTTP 5xx (520/529/503); **в одном bundle с BUG-019** (`tg_parser/processing/pipeline.py` HTTP-client wrapper).
  - **BUG-021** — `get_cross_channel_stats` игнорирует таблицу `topic_links` (только keyword-overlap; semantic-связи не всплывают) — **отдельный, но смежный PR** (`tg_parser/services/analytics_service.py`; `tg_parser/mcp_server.py` `get_cross_channel_stats`).
- **Sprint 3 — test/CI hygiene:**
  - **BUG-056** — `conftest._reset_test_db_schema` DROP/CREATE SCHEMA гонка под параллельным Postgres → `DuplicateSchema` (`tests/conftest.py:125–161`).
  - **BUG-057** — устаревшие pre-fix `skipif`-гарды в 3 тест-файлах (`test_bot_chat_target_resolution.py`, `test_bot_channel_name_parser.py` 6×, `test_bot_delete_routing_bug047.py`).
  - **TD-confirm-flow-concurrency-integration** — пропущенный two-confirm race-тест → integration-харнес (`tests/test_bot_confirm_flow.py:1199–1215`).
  - **BUG-059** — нет CI-job под `@compose_only` integration-тесты (`.github/workflows/ci.yml`; `tests/test_compose_pipeline_dispatch_integration.py`).
- **N+1 fix — BUG-055:** `check_interests` hot-path per-ref embedding fetch (`get_by_source_ref`) → батч `get_many_by_source_refs` (частичная adoption ADR-0011); вторичный сайт — `notify()` re-`get` каждого интереса в цикле (`tg_parser/services/watchlist_service.py:1148` + `1508`; батч-путь `1367`/`1762`). **Файловое пересечение с Wave B BUG-054 — см. оговорку в заголовке Wave A: рекомендуем выпустить BUG-055 первым standalone PR.**

### Wave B — BUG-054 (watchlist update-path recalibration)

**DESIGN DECISION УЖЕ ЗАФИКСИРОВАН = HYBRID:**
- при изменении text-полей (`keywords` / `description` / `channels`) — **всегда** ре-эмбеддить интерес;
- порог **авто-рекалибровать только если он изначально был auto-set**; **manually-set порог сохраняется** — для него возвращается только advisory `suggested_threshold` (не перезаписывается).
- Требует новый provenance-флаг `threshold_source: auto|manual` на интересе. **NB: вероятно нужна DB-миграция — явно проговорить это в начале реализации.**
- **Backfill (locked default):** миграция добавляет `threshold_source` (nullable) → backfill `auto` там, где интерес был создан с `threshold=None` (т.е. калиброванный авто-порог), `manual` — где был передан явный порог. ADR-0015 документирует эвристику + edge-cases (напр. интересы до калибровки / неоднозначные строки).
- Формализовать как **ADR-0015** в той же сессии.

Файлы: `tg_parser/services/watchlist_service.py` `_apply_upsert` (948–1021); embedding-путь (ADR-0011); calibration-путь (ADR-0012). Связано: ADR-0012 §R5 (deferred follow-up), BUG-055 (смежный watchlist-touch в том же файле — см. оговорку Wave A: последовательный merge, BUG-055 ведущим PR).

### Wave C — observability + doc-hygiene

- **BUG-058** — `tg_pipeline_trigger_total{surface}` всегда `surface="api"`; `mcp`/`bot` label-значения недостижимы (HTTP-граница ADR-0007 теряет origin). Протащить originating surface через dispatch (`tg_parser/api/routes/pipeline.py:89`; `tg_parser/services/pipeline_dispatch_service.py:95–153`).
- **BUG-060** — alert-правила должны гейтиться на `semantic_available`: `combined=1.0` / `semantic=0.0` — это **намеренный keyword-only режим, НЕ баг**; долг — только в alert-rule. Scoring **не трогать**. Конкретно: проверить/добавить правила под `docker/grafana/provisioning/alerting/` **и** PromQL в runbook (напр. [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)); любую формулу вида `0.4·kw + 0.6·sem` гейтить на `semantic_available`, чтобы keyword-only режим не алёртил ложно.
- **TD-bot-confirm-coverage-completeness** — добавить admin write-tools (`register_user`, `add_user_auth`, …) в confirm-gate `_WRITE_TOOLS_REQUIRING_CONFIRM` (`tg_parser/bot/tools.py`: TD описан в комментарии L99–102; сам frozenset — L103).
- **Doc-drift:**
  - **DOC-001 (verify-and-close)** — `grep -rn "@smoke_tgparser_bot"` по репо: bot username **уже исправлен** в коммите `a06f428` (`@smoke_tgparser_bot` → `@Tgingest_bot` в `docs/prompts/DEV_RESURRECTION_PROMPT.md`); в теле файла сейчас `@Tgingest_bot`. Задача: подтвердить грепом — если строка осталась только в исторических notes/runbooks, пометить DOC-001 resolved в BUG_LOG; иначе поправить оставшиеся вхождения. Не утверждать конкретный line-anchor.
  - Устаревший `START_PROMPT`-инвентарь (`REVIEW_2026-06-03_WAVE1_DONE.md` § 11).
  - `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` Wave D + `docs/notes/PLANNING_NEXT_CONTRACT_PREP.md` — F11 P2 / batch / threshold перечислены как «future», но **superseded ADR-0010–0014** — проставить cross-link на ADR.

---

## 3. Definition of Done (нормативно для КАЖДОЙ волны, по требованию пользователя)

- [ ] **Self-review созданных тестов** — ассерты проверяют реальное целевое поведение (не тавтологичны), покрывают edge-cases + negative paths, а не просто «зелёные».
- [ ] **Полный прогон тестов с БД:** `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` (PR-standard baseline по [`tests/README.md`](../../tests/README.md): **~3130 passed / ~16 env-gated skips**). **Re-baseline после каждой волны, если suite вырос**; любой **новый** fail/skip трактовать как блокирующий — не гнаться за магическим числом. Проанализировать **любой** новый skip/fail — не только scoped-подмножество. Запускать вне sandbox (`required_permissions: all`).
- [ ] **ruff** чисто на изменённых файлах; существующие watchlist/F11/bot-тесты зелёные.
- [ ] **Bump prompt-версии:** любое изменение bot/MCP write-surface → поднять версию `prompts/bot.yaml` + расширить contract/guard-тесты (прецедент BUG-025/046).
- [ ] **commit + deploy — только по явному go-ahead пользователя**; per-bug закрывающие строки в BUG_LOG (конвенция BUG-028) с commit-ref + evidence.

---

## 4. Out of scope / НЕ Wave-1 debt (не затягивать)

- **§ B accepted-by-design** (НЕ перезаводить как баги): `min_threshold 0.45` precision floor; sync-латентность калибровки; batch-cron в bot-процессе; SILENT journal `notified=True`; O-1 non-atomic workspace move; Q6 polymorphic targets отсутствуют в HTTP-схемах; streaming scorer отложен; knee/gap threshold-детекция отклонена; `skipped_non_instant` batch-mode filter semantics (accepted-by-design); idempotency-key scope (ADR-0009, accepted-by-design) — оба не перезаводить.
- **BUG-008** — MCP `list_channels` hang (через `CallMcpTool` не вернул response за ~3.5 ч); нужен diagnostic spike, **reference-only — НЕ часть этой Wave 1 debt-closure дорожки**.
- **§ C forward-roadmap** (это уже Wave 2 planning, не долг): F5-C P2; F11 HTTP CRUD; S4 multilang tokenizer; F1 Full (DB-backed prompts/versioning/A-B); webhook subscription target (ADR-0008 polymorphic target).

---

## 5. Параллельные ops (вне волн, по календарю)

`topk`-rollout monitoring ведётся по [`CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md`](CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md): **каденс §7** (День 1–3 — беглый просмотр свежих матчей по high-priority интересам GLP-1 / Биомаркеры; День 7–14 — оценка по критерию эскалации, решение по `+0.05` / `exclude_keywords`) и **критерий эскалации §4** (когда поднимать порог per-interest). Decision-gate инструментов при шуме (CAL §4): **`exclude_keywords` → `+0.05` к порогу → сужение каналов**.

Предлагаемый **операторский календарный таргет этой консолидационной сессии** для формального review-прохода — окно **2026-06-15 → 2026-06-22**. NB: это таргет сессии, **пока НЕ зафиксирован в CAL-доке** (там нет ни этих дат, ни формального verdict). Промежуточные проходы (день 1–3, день ~5) прошли тихо — это **из истории сессии, ещё не формальная watch-note** (не «GREEN»-вердикт). Не блокирует волны A–C, но окно надо отработать по календарю.

---

## 6. Артефакты для контекста (прочитать в начале сессии)

- **Инвентарь:** [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) (карта долга + триаж § A/B/C/D).
- **Backlog of record:** [`BUG_LOG.md`](BUG_LOG.md) — BUG-054…060 (§ «Wave 1 tech-debt consolidation») + referenced BUG-008 / BUG-019 / BUG-020 / BUG-021; TD-bot-confirm-coverage-completeness, TD-confirm-flow-concurrency-integration.
- **ADR (watchlist arc):** [`0010`](../adr/0010-watchlist-keyword-aggregation.md), [`0011`](../adr/0011-watchlist-backfill-rework.md), [`0012`](../adr/0012-watchlist-threshold-calibration.md), [`0013`](../adr/0013-watchlist-threshold-precision-floor.md), [`0014`](../adr/0014-watchlist-batch-silent-delivery.md); для Wave A/C — [`0007`](../adr/0007-mcp-scheduler-dispatch.md) (MCP→scheduler HTTP dispatch).
- **Ops:** [`CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md`](CAL_WATCHLIST_TOPK_MONITORING_2026-06-08.md); deploy-процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (в корне репо; деплой — **только по явному go-ahead**).
- **Рабочий режим:** [`AGENTS.md`](../../AGENTS.md); режимы pytest — [`tests/README.md`](../../tests/README.md).
- **Прод (если потребуется проверка):** `ssh prod` (HostName 212.72.189.15, Port 2296, User user), `~/TG_parser`, docker compose.

---

## 7. Стартовая реплика для новой сессии (можно скопировать)

> Берёмся за закрытие Wave 1 tech debt. Прочитай [`docs/notes/START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](docs/notes/START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md), [`docs/notes/WAVE1_TECH_DEBT.md`](docs/notes/WAVE1_TECH_DEBT.md) и записи BUG-054…060 в BUG_LOG. План: Wave A (параллельно — Sprint 1 resilience BUG-019/020 + смежный BUG-021; Sprint 3 test/CI hygiene BUG-056/057/059 + TD-confirm-flow-concurrency; N+1 fix BUG-055) → Wave B (BUG-054, дизайн уже зафиксирован = HYBRID, формализуем как ADR-0015, возможна DB-миграция) → Wave C (observability BUG-058/060 + confirm-gate TD + doc-drift DOC-001). Начнём с Wave A: обсудим развилки по каждому потоку, потом фиксы. DoD на каждую волну: self-review тестов, полный прогон `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` вне sandbox, ruff чисто, закрывающие строки в BUG_LOG. Режим: коммит/деплой — только по моему явному запросу; сначала дизайн, потом код; `docs/methodology/**` и `pyproject.toml`/`requirements.txt` не трогать.
