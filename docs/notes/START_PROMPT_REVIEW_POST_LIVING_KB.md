# Code & Docs Review — Post-Living-KB-Contract Audit

**Назначение:** стартовый промпт для **read-only review-сессии** (code + docs аудит), по итогам которой должен появиться единственный deliverable — `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB.md` (executive summary + numbered findings + tech-debt backlog + recommendation на следующий спринт).

**Тип сессии:** read-only audit. **Ничего не реализовывать, не править, не мигрировать, не открывать issues.** Все find'ы — только в deliverable; юзер заведёт issues по итогу.

**Дата подготовки промпта:** 26 апреля 2026 (после F5-C MVP, ~3 часа post-deploy, watch активен).

**Образцы стиля:** [`START_PROMPT_SESSION40_CODE_REVIEW.md`](START_PROMPT_SESSION40_CODE_REVIEW.md), [`START_PROMPT_SESSION38_CODE_REVIEW.md`](START_PROMPT_SESSION38_CODE_REVIEW.md) (структура чек-листов), [`START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md) (must-read с pin'ами).

---

## 1. Зачем именно сейчас

Текущий момент — **редкая структурная пауза**, объяснимая тремя обстоятельствами:

1. **Закрыт большой контракт.** D.1 + F11 + F5-C закрыли «Living-KB contract» из [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) (строки 11–22, 59–86) — это граница фазы, а не конец одного спринта. Wave 2 (Core Value) — другая по природе, ей лучше стартовать с трезвого аудита.
2. **Три спринта подряд расширяли surface.** Каждый добавил таблицы, метрики, env-переменные, MCP-tools, миграции. Технический долг стоит дёшево *именно сейчас*, пока контекст в памяти автора и нет нового функционала, который скрывает старые швы.
3. **Watch-период всё равно блокирует новый scope.** До завершения 24h watch (см. § 9 — Watch interaction) data-driven решение по следующему спринту нельзя принимать. Read-only ревью — единственный продуктивный класс работ в этом окне.

> **North star одной строкой:** очистить базу — структурно (code), документально (docs) и приоритетно (debt backlog) — чтобы Wave 2 стартовал с **чистого baseline**, а решение по следующему спринту было обоснованным (review-findings × watch-metrics).

---

## 2. Контекст: что закрылось в Wave 1

| Спринт | Дата | Что закрыло | Reference |
|---|---|---|---|
| **D.1** Topicization Hardening | 2026-04-25 | RCA `genotek` silent failure — `failed_stage`, per-batch checkpointing, `AnthropicBillingError`, billing-pause | [`docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`](START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md), [`docs/quality/TRIAGED.md`](../quality/TRIAGED.md) §1 |
| **F11** Topic Watchlist | 2026-04-25 | proactive push — keyword + semantic match, MCP/Bot/CLI surface, scheduler hook | [`docs/notes/START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md), CHANGELOG § Sprint F11 |
| **F5-C** Evolving Topic Summaries | 2026-04-26 | re-summarize по триггеру `new_items >= N`, `topic_card_versions`, advisory-lock | [`docs/notes/START_PROMPT_SPRINT_F5C.md`](START_PROMPT_SPRINT_F5C.md), [`docs/notes/F5C_PR_CHECKLIST.md`](F5C_PR_CHECKLIST.md), CHANGELOG § Sprint F5-C |

**8 коммитов** между `c1c9f35` (F11 backfill) и `eb9756a` (HEAD сейчас). Эти 8 коммитов — основной scope Side A code review.

---

## 3. Out of scope (что НЕ делать)

- ❌ **Никаких code changes** — read-only сессия. Любая правка — отдельный PR после ревью.
- ❌ **Никаких миграций / новых тестов / новых фич.**
- ❌ **Никаких изменений CLI / MCP / Bot API.**
- ❌ **F5-C watch на проде НЕ трогать** — cron работает, `~/f5c-watch/cron.log` растёт пассивно. Если увидишь TRIPWIRE / INFRA-FAIL — записать в Side A findings § Observability, **не** fix'ить.
- ❌ **GitHub issues не открывать** — только формулировать в deliverable. Юзер заведёт по итогу.
- ❌ **TODO/FIXME в коде — это НЕ findings.** Findings — это расхождения между декларацией и реализацией (или architectural smell, или missing observability), а не «у нас уже записано в комментарии».

---

## 4. Ground truth (на момент подготовки промпта)

| Параметр | Значение |
|---|---|
| Branch | `main` |
| HEAD | `eb9756a` (chore(F5C): add 24h watch helper + post-watch report template) |
| Production tag | `f5c-mvp-2026-04-26` (на коммите `29679e0`) |
| Production commit (VPS) | `eb9756a` (после `git pull` в watch-сессии) |
| Alembic head — processing | `a4b5c6d7e8f9` (`migrations/versions/processing/20260426_add_topic_card_versions.py`, F5-C) |
| Alembic head — ingestion | `c8e9f0a1b2c3` (F11 watchlist) **+** D.1 ревизия `add_source_attempts_failed_stage` — две ревизии с одной датой `20260425`, **проверить линейность** (Side A § 6.4.1) |
| Alembic head — raw | `5c658f04eff0` (initial, без изменений с декабря 2025) |
| LOC `tg_parser/` | ~41 700 |
| LOC `tests/` | ~43 000 (тестов больше production-кода — здоровый сигнал) |
| Test snapshot | `pytest -q` → **1881 passed, 4 skipped, 1 deselected** (CHANGELOG § Sprint F5-C Verification, line 47–50) |
| `docs/notes/*.md` | **100 файлов** — кандидат на архивацию старых промптов (Side B § 7.7) |
| `docs/runbooks/*.md` | 4 файла (`ANTHROPIC_BILLING_RECOVERY`, `DEV_RESURRECTION`, `F5C_DEPLOY_AND_WATCH`, `SAFE_MIGRATION_ON_DEV`) |
| `prompts/*.yaml` | 9 файлов (включая новый `resummarize.yaml`) |
| `docs/contracts/*.schema.json` | 5 (включая новый `topic_card_version.schema.json`) |
| `docs/quality/INBOX.md` | пусто (`Empty — first entries will be added here…`) |
| `docs/quality/TRIAGED.md` | 1 запись — `genotek topicization silent failure` (status: fixed in production) |
| Open GitHub issues | **#15** — F5-C P2 backlog (10 deferred items) |
| Watch | cron `0 */4 * * *` активен на VPS, log в `~/f5c-watch/cron.log`; первый verdict — GREEN (idle) |

> Все цифры — на момент `eb9756a`. Ревью обязано **зафиксировать обновлённый snapshot** в § 6 deliverable (что-то могло измениться за 24h watch'a).

---

## 5. Must-read (с приоритетом)

### 5.1 Roadmap / process

| Файл | Зачем | Приоритет |
|---|---|---|
| [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | где живут F5-C / следующие волны; строки 378–425 | **P0** |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | принципы Living-KB; 6 принципов (стр. 11–22), Волны A/B/C/E (стр. 59–86) — должна быть пометка «contract: CLOSED 2026-04-26» (Side B § 7.2) | **P0** |
| [`CHANGELOG.md`](../../CHANGELOG.md) | секции `Sprint D.1`, `Sprint F11`, `Sprint F5-C` (последняя — строки 10–60+) | **P0** |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | backlog F5-C P2 → должны быть ссылки на issue #15; F1 Full / F10-A / F12-A — актуальны? | **P0** |
| [`docs/quality/INBOX.md`](../quality/INBOX.md) + [`TRIAGED.md`](../quality/TRIAGED.md) | open observations? (текущее: INBOX empty, TRIAGED — 1 fixed) | P1 |
| [`docs/runbooks/*.md`](../runbooks/) | 4 файла — duplicate / stale checks (Side B § 7.6) | P1 |

### 5.2 Что только что приземлилось — основной scope ревью

| Коммит | Что | Зачем читать |
|---|---|---|
| `473f107` | F5-C 1/2: schema + service + counter | core domain review |
| `53f72ef` | F5-C 2/2: scheduler hook + MCP/CLI | integration review |
| `5038eda` | F5-C self-review (CLI version_no fix + 15 tests) | qa-fixes review |
| `29679e0` | F5-C MVP merge | reference (PR description) |
| `fa8e4fd` | F5-C deploy runbook | reference |
| `eb9756a` | F5-C watch helper + post-watch template | reference (этот же скрипт — твой инструмент во время review для observability check) |
| `0ff5bcf` | F11 self-review (49 tests + docstring align) | review |
| `c1c9f35` | F11 changelog backfill | reference |

### 5.3 Архитектурные точки

| Файл | Зачем |
|---|---|
| [`docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) | модель incremental топикизации — F5-C / F11 / D.1 в неё вписались; проверить, что декларация и код всё ещё совпадают |
| [`docs/architecture.md`](../architecture.md) | общая схема DB / сервисов |
| `docs/contracts/*.schema.json` (5 файлов) | JSON-контракты — все ли актуальны после F5-C? `topic_card.schema.json` должен иметь 3 новых optional поля; новый файл `topic_card_version.schema.json` |
| `prompts/*.yaml` (9 файлов) | per-stage prompts — все используются? все версионированы по конвенции (`system:` / `user:` / `model:`)? |
| `migrations/versions/{processing,ingestion,raw}/` | миграции — линейность веток (см. ground truth § 4 — две ревизии с одной датой в `ingestion/`) |

### 5.4 Code entry points (для Side A)

| Файл / символ | Зачем |
|---|---|
| `tg_parser/services/scheduler_service.py` | hook chain: `run_topic_embedding` → `run_resummarize_for_channel` → `run_watchlist_check_for_channel`; F5-C / F11 hooks стоят рядом — стиль одинаков? |
| `tg_parser/services/resummarization_service.py` (новый) | F5-C ядро — advisory-lock, triple-cap (`MAX_PER_TICK`, `MAX_DURATION_S`, `MAX_TOKENS_PER_TICK`), commit_resummary; ошибки обработаны единообразно? |
| `tg_parser/services/watchlist_service.py` | F11 ядро — embedding fallback, scoring; consistency со F5-C |
| `tg_parser/services/topicization_service.py` | D.1 + F5-C counter increment в `_update_bundles_for_assignments` |
| `tg_parser/storage/sqlalchemy/topic_card_repo.py` | F5-C расширение: `increment_resummary_counter`, `list_resummarize_candidates`, `commit_resummary` (атомарный single-UPDATE) |
| `tg_parser/storage/sqlalchemy/topic_card_version_repo.py` (новый) | F5-C audit trail repo |
| `tg_parser/auth/ownership.py` | `assert_topic_access` (F5-C) — стиль соответствует `assert_channel_access` / `assert_admin`? |
| `tg_parser/processing/llm/factory.py` | per-stage scopes — `resummarize` (F5-C) добавлен корректно; resolution priority документирован |

---

## 6. Side A — Code review checklist (8 секций)

> **Формат:** на каждую проверку — конкретная команда / grep / файл, и **ожидание**. Обнаруженные расхождения идут в **Findings** deliverable с severity (`critical` / `major` / `minor`). Не fix'ить — только документировать.

### 6.1 Dependency graph hygiene

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | Нет cycle `services → api → services` | `rg "from tg_parser.api" tg_parser/services/` | пусто (после R2 из Session 39) |
| 2 | `Database.from_settings` только в `db_context.py` | `rg "Database.from_settings" tg_parser/services/` | только в `db_context.py` |
| 3 | `auth/` импортируется только из MCP / Bot / CLI / api | `rg "from tg_parser.auth" tg_parser/services/` | пусто или единичные обоснованные случаи |
| 4 | F5-C / F11 / D.1 не нарушают layering `services → storage → domain` | manual review hook chain | one-direction |

### 6.2 Dead code / dead exports

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | Прогнать `vulture tg_parser/ --min-confidence 80` (если установлен) или `ruff check --select F401` | shell | <20 high-confidence false-positives, остальное — finding |
| 2 | Env vars из `.env.example` — все ли используются | `for v in $(grep -oE '^[A-Z_]+=' .env.example); do rg "$v" tg_parser/ \|\| echo "DEAD: $v"; done` | каждый dead → finding |
| 3 | F5-C env: `RESUMMARIZE_INPUT_WINDOW_N`, `RESUMMARIZE_TRIGGER_N`, `MAX_PER_TICK`, `MAX_DURATION_S`, `MAX_TOKENS_PER_TICK`, `RESUMMARIZE_ENABLED` — все runtime-используются | `rg "RESUMMARIZE_" tg_parser/` | 6 переменных, все в коде |
| 4 | Deprecated CLI commands (если есть `--legacy`, `--old-`) | `rg "deprecated\|legacy" tg_parser/cli/` | каталог ссылок на FUTURE_FEATURES для удаления |

### 6.3 Test coverage map

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | `pytest --cov=tg_parser --cov-report=term-missing -q` (no-PG, чтобы быстро) | shell ~3-5 минут | snapshot покрытия |
| 2 | Топ-10 hot-paths с покрытием < 60% | парсинг отчёта | список → finding (severity по hotness) |
| 3 | F5-C новые модули — > 80% покрытия | `pytest --cov=tg_parser/services/resummarization_service` | ожидаемо да (CHANGELOG: 58 PG-gated tests + cli + scheduler hook) |
| 4 | F11 новые модули — > 80% покрытия | то же | то же |
| 5 | D.1 новые ветки (`failed_stage`, `AnthropicBillingError`) — покрыты | `rg "failed_stage" tests/` | ≥ 2 файла |

### 6.4 Schema hygiene (alembic + DDL)

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | **Линейность ingestion-ветки** (две ревизии с датой `20260425`) | `tg-parser db check --db ingestion` (или `alembic heads`) | один head, не два |
| 2 | Все три БД на actual head | `tg-parser db check --db {processing,ingestion,raw}` | `No new upgrade operations detected.` × 3 |
| 3 | Partial-индексы (F5-C `idx_topic_cards_resummarize_candidates`, F11 `idx_watch_interests_active`) — обоснованы документацией | grep по миграциям + комментарии | каждый index имеет docstring |
| 4 | FK consistency: `topic_card_versions.topic_id → topic_cards.id ON DELETE CASCADE`; `watch_matches.interest_id → watch_interests.id` | psql `\d topic_card_versions` + `\d watch_matches` | CASCADE / SET NULL по дизайну |
| 5 | `topic_cards`: 3 новых колонки (`last_summarized_at`, `summary_version`, `new_items_since_last_summary`) — все используются runtime | `rg "summary_version\|last_summarized_at\|new_items_since_last_summary" tg_parser/` | каждое поле в ≥ 1 service + repo + tests |

### 6.5 Error handling consistency

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | `AnthropicBillingError` — где ловится, где пробрасывается | `rg "AnthropicBillingError" tg_parser/` | в hook chain пробрасывается до `_pause_source_for_billing`; в service — пробрасывается, не глотается |
| 2 | `failed_stage` — все падающие stages используют | `rg "failed_stage=" tg_parser/services/` | топикизация / резюме / эмбеддинг — все с `failed_stage` |
| 3 | Generic `except Exception:` — где остался | `rg "except Exception" tg_parser/` | каждый случай имеет `logger.exception` ИЛИ обоснованный комментарий |
| 4 | Silent-log pattern из F5-C Decision #13 (non-billing fail → `logger.exception`, НЕ в `stage_errors`) | scheduler hook source | соблюдён в обоих hook'ах (F5-C + F11) |
| 5 | `try/finally` для `aclose()` — все services с external resources | `rg "aclose\|close\(\)" tg_parser/services/` | каждый async service имеет finally cleanup |

### 6.6 Observability completeness

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | F5-C метрики экспортированы | `curl http://localhost:8000/metrics` (или из текущего watch-cron lo) | `tg_resummarize_total`, `tg_resummarize_tokens_total`, `tg_resummarize_duration_seconds` |
| 2 | F11 метрики экспортированы | то же | `tg_parser_watchlist_*` (имена уточнить из CHANGELOG) |
| 3 | D.1 метрики экспортированы | то же | `tg_parser_anthropic_billing_block_total` (подтверждено в TRIAGED §1 — на проде есть) |
| 4 | Каждая критическая операция имеет 1 metric + 1 structured log | manual review key services | gap-list |
| 5 | Watch-cron на VPS даёт ≥ 4 verdict-строк за 16 часов | `ssh prod cat ~/f5c-watch/cron.log` | non-empty, без TRIPWIRE |
| 6 | Grafana dashboards отражают новые метрики | `ls grafana/` или `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` § PromQL | finding если нет |

### 6.7 Prompt drift

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | Все 9 prompts/*.yaml используются runtime | `for f in prompts/*.yaml; do n=$(basename $f .yaml); rg "load_prompt.*$n\|prompts/$n" tg_parser/ \|\| echo "ORPHAN: $f"; done` | 0 orphans (или каждый orphan — finding) |
| 2 | Каждый yaml имеет `system:` / `user:` / `model:` секции | `for f in prompts/*.yaml; do echo "--- $f ---"; head -5 $f; done` | по конвенции |
| 3 | Per-stage scopes в `LLMConfigManager` — все 9 имён прописаны | `rg "LLM_PROVIDER\|LLM_MODEL" tg_parser/processing/llm/factory.py` | resolve() покрывает все stages |
| 4 | `reload_prompts` MCP tool ловит `resummarize.yaml` (новый) | tested in F5-C tests? | manual scan |

### 6.8 Migration replay

| # | Проверка | Как | Ожидание |
|---|---|---|---|
| 1 | `tests/test_migrations_runtime_upgrade.py` — `EXPECTED_TABLES` содержит `topic_card_versions`, `watch_interests`, `watch_matches` | `rg "EXPECTED_TABLES" tests/` | да (CHANGELOG line 43) |
| 2 | `CRITICAL_INDEXES` содержит все 3 новых index | то же | 3 новых index F5-C + F11 |
| 3 | `alembic upgrade head → downgrade -2 → upgrade head` стабильно | manual run в test container | exit 0, idempotent |

---

## 7. Side B — Docs review checklist (8 секций)

> **Формат:** для каждого документа — что проверить (stale / missing / inconsistent), куда внести finding. Не править — только документировать.

### 7.1 ROADMAP_V3_PRODUCTION_FIRST.md

| Что | Ожидание |
|---|---|
| F5-C статус | DONE 2026-04-26 (а не «next») |
| F11 статус | DONE 2026-04-25 |
| D.1 статус | DONE 2026-04-25 |
| Wave 2 — точки входа | ясно сформулированы; нет «висячих» ссылок на удалённые секции |

### 7.2 ROADMAP_KARPATHY_LIKE_LIVING_KB.md

| Что | Ожидание |
|---|---|
| Living-KB contract | пометка «**CLOSED 2026-04-26** (D.1 + F11 + F5-C)» |
| Next contract | сформулирован раздел про следующий контракт (например, «Cross-channel synthesis», «Bot UX-contract» — обсудить в deliverable § 5 Recommendation) |
| Волны A / B / C / D / E | актуальный статус каждой |

### 7.3 CHANGELOG.md

| Что | Ожидание |
|---|---|
| 8 коммитов между `c1c9f35..eb9756a` | все отражены в секциях `Sprint D.1` / `Sprint F11` / `Sprint F5-C` |
| `Sprint F5-C` секция | ✅ MVP DONE; полный список Added/Changed/Tests/Documentation/Migration; ссылки на коммиты |
| Verification block | актуальные test counts (`1881 passed` etc) |

### 7.4 FUTURE_FEATURES.md

| Что | Ожидание |
|---|---|
| F5-C P2 backlog | каждый из 10 deferred items имеет ссылку на issue #15 (или один общий ref) |
| F11 Phase 2 (batch / silent / cooldown) | формализован сценарий + acceptance criteria |
| F1 Full | актуальный design (ссылка из ROADMAP) |
| F10-A Images + Voice | актуальный design |
| F12-A Cross-channel UX | актуальный design |
| Удалённое / устаревшее | вынести в `docs/notes/archive/` или явно пометить «WONTFIX» |

### 7.5 PRODUCTION_DEPLOYMENT.md (или эквивалент в runbooks/)

| Что | Ожидание |
|---|---|
| Шаги deploy после трёх миграций (D.1 + F11 + F5-C) | актуальные ревизии в инструкции |
| Env vars для D.1 / F11 / F5-C | все упомянуты с дефолтами |
| Обратная совместимость | каждая миграция имеет downgrade-инструкцию (CHANGELOG § Sprint F5-C Migration) |

### 7.6 runbooks/* (4 файла)

| Файл | Что проверить |
|---|---|
| [`ANTHROPIC_BILLING_RECOVERY.md`](../runbooks/ANTHROPIC_BILLING_RECOVERY.md) | обновлён ли после D.1 (`AnthropicBillingError` + `tg_parser_anthropic_billing_block_total`)? |
| [`DEV_RESURRECTION.md`](../runbooks/DEV_RESURRECTION.md) | актуальные шаги для текущей prod-конфигурации? |
| [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) | post-watch template уже встроен (§ 9 этого промпта); проверить полноту § Tripwire response |
| [`SAFE_MIGRATION_ON_DEV.md`](../runbooks/SAFE_MIGRATION_ON_DEV.md) | актуальные шаги для трёх БД и трёх свежих миграций? |

### 7.7 notes/START_PROMPT_*.md — архивация

`docs/notes/` содержит **100 файлов** — преимущественно отыгранные `START_PROMPT_SESSIONxx_*.md`. Архивация:

| Что | Ожидание |
|---|---|
| Существует ли паттерн `docs/notes/archive/` | если нет — предложить структуру в finding |
| Кандидаты на архивацию | все `SESSION{1..47}_*.md` (отыграны), `SPRINT_{A2..A7,D1}*.md` (отыграны), `START_PROMPT_PLANNING_F5C.md` + `START_PROMPT_SPRINT_F11.md` + `START_PROMPT_SPRINT_F5C.md` (отыграны после F5-C MVP) |
| Активные | этот файл (`START_PROMPT_REVIEW_POST_LIVING_KB.md`) + любые pending-промпты для Wave 2 |
| Index | `docs/notes/archive/INDEX.md` со списком архива по дате — рекомендация в finding |

### 7.8 quality/INBOX & TRIAGED

| Что | Ожидание |
|---|---|
| `INBOX.md` | пусто (или только новые observations за время watch) |
| `TRIAGED.md` | 1 запись (`genotek` — fixed); если за watch появилось что-то — переместить (это уже **fix**, не review) |
| Cadence note | подтвердить «триаж перед каждым sprint-планированием» — соблюдается |

---

## 8. Deliverable — структура

Один файл: `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB.md`

```markdown
# Post-Living-KB Audit — 2026-04-{26..27}

**Sessions:** Side A code review (date X, ~Y часов), Side B docs review (date Z, ~W часов).
**Reviewer agent:** {model name}.
**Scope coverage:** 8/8 code zones, 8/8 docs zones.

## 1. Executive summary
3-5 строк. Общий вердикт (clean / minor concerns / major findings). 2-3 ключевых наблюдения. Recommendation на следующий спринт (одной строкой).

## 2. Code findings
Нумерованные. Формат каждого:
- **#A.N | severity | code zone (6.X)**
- **What:** что обнаружено (1-3 строки)
- **Where:** файл:строка
- **Why it matters:** влияние
- **Suggested action:** что нужно сделать (для будущего issue, не сейчас)

Severity:
- `critical` — продакшен-риск или silent-correctness (≤ 2 ожидается)
- `major` — architectural / observability gap, не блокирует, но накапливается
- `minor` — стиль / docstring / dead code

## 3. Docs findings
Аналогично, тип `missing` / `stale` / `inconsistent`.

## 4. Tech-debt backlog → predicted issues
Таблица: id | title | source finding | predicted scope (S/M/L) | priority for next sprint (P0/P1/P2).
S ≤ 1 час; M ≤ 4 часа; L > 4 часа.

## 5. Recommendation для следующего спринта
- watch verdict (заполнить из `~/f5c-watch/cron.log` на момент завершения review)
- топ-2 P0 debt items (если есть)
- choice: F1 / F10-A / F12-A / F11 P2 / F5-C P2 #4 (time-based) / F5-C P2 #5 (TTL) / debt-fix-sprint
- обоснование одной фразой

## 6. Metrics snapshot (на момент завершения review)
- HEAD: ...
- Tests: ... passed / ... skipped
- LOC: tg_parser=... tests=...
- Alembic heads: processing@... ingestion@... raw@...
- INBOX/TRIAGED entries: ... / ...
- Watch cron-log entries since deploy: ... (последний verdict: ...)
```

---

## 9. Watch interaction

Cron на проде (`0 */4 * * *`) запускает `docker/f5c_watch.sh --quiet`, лог в `/home/user/f5c-watch/cron.log`.

| Действие | Допустимо? |
|---|---|
| `ssh prod cat ~/f5c-watch/cron.log` (read) | ✅ обязательно — для § 5 Recommendation и § 6 Metrics |
| `ssh prod bash docker/f5c_watch.sh` (manual full run) | ✅ для свежего snapshot'а |
| `ssh prod docker compose ...` (read-only: `ps`, `logs --tail`) | ✅ |
| Перезапуск cron / docker compose | ❌ |
| Изменение `docker/f5c_watch.sh` или runbook'а | ❌ (это уже не review, а fix) |
| Любая SQL-запись на prod | ❌ |

К концу review (≥ 16-24 часа после deploy) в логе должно быть **≥ 4-6 verdict-строк**. Если все GREEN — это отдельная положительная metric для § 5. Если хоть один TRIPWIRE — это **finding** в § 2 (severity по типу tripwire), а не повод для fix-а в этой сессии.

---

## 10. Time budget

| Часть | Оценка |
|---|---|
| Side A — code review (8 секций) | ~3-4 часа фокусной работы |
| Side B — docs review (8 секций) | ~2-3 часа |
| Сводный документ (структура + finalisation) | ~30 минут |
| **Итого** | **~6-8 часов** |

**Допустимо разнести на 2 захода** (Side A — вечером, Side B — следующим утром после ночёвки). Качество docs-review коррелирует со свежестью головы — не пытаться сделать всё в один раз, если устал.

---

## 11. Критерии прохождения review

Review считается завершённым, если:

- [ ] Все 8 code-зон пройдены (Side A § 6.1–6.8)
- [ ] Все 8 docs-зон пройдены (Side B § 7.1–7.8)
- [ ] Findings нумерованы, имеют severity / type, привязаны к файлу:строке
- [ ] Tech-debt backlog: каждый item с predicted scope (S/M/L) и priority (P0/P1/P2)
- [ ] Recommendation на следующий спринт обоснован (review-findings × watch-metrics)
- [ ] Metrics snapshot зафиксирован (на момент завершения, не на момент старта)
- [ ] `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB.md` создан и закоммичен (один commit, message: `docs(review): post-Living-KB audit — N findings, recommendation: <X>`)
- [ ] (опционально, но желательно) Финальное сообщение review-агента содержит **executive summary** (5-10 строк) — чтобы юзер мог принять решение по следующему спринту, не читая 6-страничный deliverable

---

## 12. После прохождения

1. Заполнить **post-watch comment в issue #15** — шаблон уже встроен в [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § «Post-watch report». Комментарий ссылается на `REVIEW_2026-04-26_POST_LIVING_KB.md` § 6 (Metrics snapshot).
2. **Tech-debt backlog → GitHub issues** (юзер делает руками или delegate):
   - label `tech-debt` + `post-living-kb-review`
   - body цитирует соответствующий finding
3. **Старт следующего спринта** — выбор из:
   - **F1 Full** (Wave 2: Core Value)
   - **F10-A** (Images + Voice)
   - **F12-A** (Cross-channel UX)
   - **F11 Phase 2** (batch / silent / cooldown)
   - **F5-C P2 #4** (time-based trigger) — естественное продолжение
   - **F5-C P2 #5** (TTL retention)
   - **debt-fix-sprint** (если P0 debt items > 2)

   Обоснование выбора — одной фразой ссылается на § 5 deliverable.

---

## 13. Ground rules для review-агента

1. **Ничего не fix'ить.** Любая правка кода / docs — отдельный PR после ревью. Это **read-only** аудит.
2. **Не открывать GitHub issues** — только формулировать в § 4 deliverable. Юзер заведёт по итогу.
3. **Если что-то непонятно — записать как `OPEN QUESTION` в § 1 (executive summary).** Не гадать, не интерпретировать.
4. **TODO/FIXME в коде — НЕ findings.** Это уже backlog. Findings — это **расхождения** между декларацией и реализацией, или architectural smell, или missing observability.
5. **Не цитировать целые файлы.** Только конкретные строки + интерпретация (max ~10 строк code-блока на finding).
6. **При сомнении — severity ниже.** Лучше `minor`, чем «critical», который окажется false-positive.
7. **Findings без attribution не принимаются** — каждое должно ссылаться на конкретный файл:строка или коммит.

---

## 14. Citation back

Когда review-агент будет работать в новой сессии, он может цитировать:

- **Этот промпт:** `docs/notes/START_PROMPT_REVIEW_POST_LIVING_KB.md` (commit где он появился)
- **Транскрипт сессии-источника** (где обсуждали timing review-сессии): UUID `518d7766-dd0b-4f5d-bc6c-5bfb478264da`
- **Образцы стиля:** `docs/notes/START_PROMPT_SESSION40_CODE_REVIEW.md`, `docs/notes/START_PROMPT_PLANNING_F5C.md`
- **Watch sprint-источник:** UUID `736f589b-bfea-4da0-82b3-bae591f5b016` (где F5-C задеплоен на VPS, SSH alias `prod` сохранён)

Эти ссылки — *не для копипасты в deliverable*, а для подтягивания контекста в случае ambiguity.
