# Code & Docs Review — Post-Living-KB-Contract Audit

**Назначение:** стартовый промпт для **read-only review-сессии** (code + docs аудит) в составе **ensemble** (2 независимых ревьюера + merge-сессия). По итогам этой конкретной сессии должен появиться **только один** deliverable — `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<REVIEWER_ID>.md` (executive summary + numbered findings + tech-debt backlog + recommendation на следующий спринт). **Никакие изменения в код / документы / GitHub / production не вносятся.** План исправлений будет произведён отдельной merge-сессией ([`START_PROMPT_REVIEW_MERGE.md`](START_PROMPT_REVIEW_MERGE.md)) после того, как оба ревьюера независимо завершат свою работу.

**Тип сессии:** strict read-only audit. См. § 3.1 — список запрещённых tool calls. См. § 15 — протокол ensemble-режима.

**Дата подготовки промпта:** 26 апреля 2026 (после F5-C MVP, ~3 часа post-deploy, watch активен). Доработан 26 апреля 2026 — добавлен ensemble-протокол.

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

## 3. Out of scope (что НЕ делать) — STRICT READ-ONLY

Эта сессия запускается **в составе ensemble** (см. § 15 — два независимых ревьюера + merge-сессия). Деливарабль одного ревьюера будет сравниваться с деливараблем другого, **исправления применяются только после merge**. Любая правка в этой сессии нарушает протокол.

### 3.1 Запрещённые tool calls / действия

| Категория | Запрещено | Исключения |
|---|---|---|
| **Файловая запись** | `Write`, `StrReplace`, `Delete`, `EditNotebook` для любых файлов кодовой базы и документации | **Только** в собственный deliverable: `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<REVIEWER_ID>.md` (см. § 8.1) |
| **Git** | `git add`, `git commit`, `git push`, `git checkout`, `git stash`, `git rebase`, `git reset` любого типа, любые мутирующие subcommands | **Разрешено** read-only: `git log`, `git diff`, `git show`, `git status`, `git blame` |
| **Production / VPS** | Любая команда, которая пишет в prod (`docker compose restart`, `docker compose exec ... psql -c "INSERT/UPDATE/DELETE"`, `crontab -e`, `rm`, `scp` с записью на prod, изменение `~/.ssh/config`) | **Разрешено** read-only: `ssh prod cat ...`, `ssh prod docker compose ps`, `ssh prod docker compose logs --tail`, `ssh prod docker compose exec -T postgres psql -c "SELECT ..."`, `ssh prod bash docker/f5c_watch.sh` (full run), чтение cron-log |
| **GitHub** | `gh issue create`, `gh pr create`, `gh issue close`, `gh pr merge`, `gh issue comment`, любые запись-операции через API | **Разрешено** read: `gh issue view 15`, `gh pr list`, `gh repo view` |
| **Pip / npm / docker pull** | Установка пакетов, pull новых образов, `pip install`, `npm install`, `docker pull` | Если для прогона `pytest --cov` нужен `pytest-cov` и его нет — записать как **OPEN QUESTION** в § 1 deliverable, не устанавливать |
| **MCP write tools** | `add_channel`, `pause_channel`, `resume_channel`, `remove_channel`, `register_user`, `update_user`, `subscribe_*`, `unsubscribe_*`, `force_resummarize`, `set_llm_config`, `reset_llm_config`, `reload_prompts`, `trigger_pipeline`, `export_channel` | **Разрешено** read: `list_*`, `get_*`, `whoami`, `search_knowledge_base`, `ask_question`, `get_export_status` |

### 3.2 Что точно нельзя (даже если кажется безобидным)

- ❌ **Никаких code changes** — даже исправление опечатки в комментарии. Любая правка — отдельный PR после merge.
- ❌ **Никаких миграций / новых тестов / новых фич / форматирования / lint-fixes.**
- ❌ **Никаких изменений CLI / MCP / Bot API.**
- ❌ **F5-C watch на проде НЕ трогать** — cron работает, `~/f5c-watch/cron.log` растёт пассивно. Если увидишь TRIPWIRE / INFRA-FAIL — записать в Side A findings § Observability, **не** fix'ить.
- ❌ **GitHub issues не открывать** — только формулировать в deliverable. Юзер заведёт по итогу merge.
- ❌ **TODO/FIXME в коде — это НЕ findings.** Findings — это расхождения между декларацией и реализацией (или architectural smell, или missing observability), а не «у нас уже записано в комментарии».
- ❌ **Не читать deliverable другого ревьюера** до окончания собственной работы (§ 15.3).
- ❌ **Не запускать review-агента из этой сессии как subagent** — ensemble-режим требует *независимых* окон.

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

### 8.1 Filename (важно для ensemble)

Файл должен называться: **`docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<REVIEWER_ID>.md`**

`<REVIEWER_ID>` — short slug идентифицирующий конкретное review-окно. Юзер передаёт его в первом сообщении (см. § 15.1 — handshake). Допустимые форматы:
- по модели: `opus`, `sonnet45`, `gpt5-codex`, `gpt55`, `composer2-fast`
- по букве: `A`, `B`
- если юзер не передал — спросить **до** старта чтения файлов (это первое и единственное допустимое уточнение)

**Запрещено** писать в файл без суффикса `__<REVIEWER_ID>.md` — он зарезервирован для итогового merged deliverable (§ 12).

### 8.2 Шапка deliverable (обязательная, machine-parseable)

Первые ~15 строк должны точно повторять структуру ниже, чтобы merge-агент мог их парсить:

```markdown
# Post-Living-KB Audit — Reviewer <REVIEWER_ID>

**Reviewer model:** {model name as user provided in handshake}
**Reviewer window:** <REVIEWER_ID>
**Started (UTC):** {ISO-8601 timestamp когда начал чтение first file}
**Finished (UTC):** {ISO-8601 timestamp когда закоммитил deliverable; заполняется в самом конце}
**Base commit:** {git rev-parse --short HEAD на момент start}
**Time spent:** {Y часов SideA + W часов SideB, по факту}
**Scope coverage:** {N}/8 code zones, {M}/8 docs zones
**Findings count:** {total}, of which: critical={X}, major={Y}, minor={Z}
**Open questions:** {K} (см. § 1)

---
```

### 8.3 Структура body

```markdown
## 1. Executive summary
3-5 строк. Общий вердикт (clean / minor concerns / major findings). 2-3 ключевых наблюдения.
Recommendation на следующий спринт (одной строкой).

**Open questions** (если есть): нумерованный список того, что было непонятно и не удалось разрешить —
для merge-агента (он сравнит OPEN QUESTIONS обоих ревьюеров и решит, какие вынести юзеру).

## 2. Code findings
Каждый finding ровно по шаблону § 8.4. Группировка по code zone (6.1..6.8) — заголовок ### на zone.

## 3. Docs findings
Каждый finding по шаблону § 8.4. Группировка по docs zone (7.1..7.8).

## 4. Tech-debt backlog → predicted issues
Таблица:

| ID | Source finding(s) | Title | Predicted scope | Priority |
|---|---|---|---|---|
| TD-01 | A-001, A-007 | Linearize ingestion alembic heads | S | P0 |
| TD-02 | A-012 | ... | M | P1 |

- `S` ≤ 1 час, `M` ≤ 4 часа, `L` > 4 часа
- Priority: `P0` (next sprint blocker) / `P1` (next sprint nice-to-have) / `P2` (later)
- ID format: `TD-NN` (просто sequential numbering в этом deliverable)
- **Один finding может породить несколько TD-items**, и наоборот — **один TD может объединять findings**

## 5. Recommendation для следующего спринта
- Watch verdict (заполнить из `~/f5c-watch/cron.log` на момент завершения review)
- Топ-2 P0 debt items (если есть из § 4)
- Choice: F1 Full / F10-A / F12-A / F11 P2 / F5-C P2 #4 (time-based) / F5-C P2 #5 (TTL) / debt-fix-sprint
- Обоснование 1-3 предложениями (review-findings × watch-metrics)
- **Confidence в этой рекомендации:** high / medium / low (для merge-агента)

## 6. Metrics snapshot (на момент завершения review, не на момент старта)
- HEAD: {git rev-parse --short HEAD}
- Tests: {N} passed / {M} skipped (`pytest -q`, no-PG mode)
- LOC: tg_parser={X} / tests={Y} (через `wc -l $(find ... -name "*.py")`)
- Alembic heads: processing@{rev} ingestion@{rev1[,rev2 if multi-head]} raw@{rev}
- INBOX/TRIAGED entries: {N}/{M}
- Watch cron-log: {K} verdict-строк, последняя: `{copy verdict line verbatim}`
```

### 8.4 Standardized finding format (mandatory)

Каждый finding **обязан** соответствовать этой структуре (machine-parseable для merge-сессии):

```markdown
#### {ID} — {severity} | {category} | confidence: {high|medium|low}

**Where:** `path/to/file.py:LINE` (или диапазон `:LINE-LINE`, или `commit:SHA` для git-history-finding'ов).
Если finding касается нескольких файлов — основной + список «also affects» в Notes.

**Zone:** {6.X / 7.X — какой checklist-secci}

**Observation:** что обнаружено фактически (нейтрально, без оценок). 1-3 предложения. Только то, что
видно — никаких «возможно», «вероятно». Если нужна гипотеза — отдельный пункт ниже.

**Why it matters:** влияние на пользователя / проект / архитектуру. Без этого finding не принимается
(если «неясно почему это плохо» — снижай severity или удали).

**Suggested action (draft PR description):** 1-3 строки, как если бы это был commit message
+ короткое тело PR. Будущий fix-агент должен мочь начать работу с этого текста без переспроса.

**Notes:** опциональный блок — гипотезы, ссылки на прецеденты в проекте, alternatives.
Здесь же — `Also affects: file1.py, file2.py` если применимо.
```

### 8.5 Стандартный словарь (controlled vocab)

Чтобы merge-агент мог сравнивать findings без NLP-магии, используй **только** значения из таблиц:

**Severity (для code и docs одинаково):**

| Severity | Когда использовать | Ожидаемое количество |
|---|---|---|
| `critical` | продакшен-риск, silent-correctness, data-loss, security-смены | ≤ 2 на ревью |
| `major` | architectural smell, observability gap, broken contract без видимого эффекта, untested critical path | 5-15 |
| `minor` | стиль, docstring, dead code, инконсистентность naming, отсутствующий комментарий к non-obvious-логике | без ограничений, но не разводить шум |

**Category (Side A — code):**

| Category | Соответствует zone |
|---|---|
| `dependency-graph` | 6.1 |
| `dead-code` | 6.2 |
| `test-coverage` | 6.3 |
| `schema-hygiene` | 6.4 |
| `error-handling` | 6.5 |
| `observability` | 6.6 |
| `prompt-drift` | 6.7 |
| `migration-replay` | 6.8 |

**Category (Side B — docs):**

| Category | Соответствует zone |
|---|---|
| `roadmap-stale` | 7.1, 7.2 |
| `changelog-incomplete` | 7.3 |
| `future-features-stale` | 7.4 |
| `deploy-stale` | 7.5 |
| `runbook-stale` | 7.6 |
| `notes-archive` | 7.7 |
| `quality-tracker` | 7.8 |

**Confidence:**

| Confidence | Когда использовать |
|---|---|
| `high` | прямое наблюдение из чтения кода/доков; воспроизводимая команда; reference на конкретный commit/файл |
| `medium` | сильный сигнал, но требует интерпретации; например, «X declared in docs but Y implementation» — где интерпретация «несоответствие» субъективна |
| `low` | косвенный сигнал; «возможно» / «может быть»; **в этом случае рассмотри удаление finding'а или перенос в § 1 OPEN QUESTIONS** |

### 8.6 Finding ID format

`<REVIEWER_ID>-NNN` где NNN — sequential 3-digit, начиная от 001.

Примеры: `opus-001`, `opus-002`, ..., `sonnet45-001`, `B-014`.

ID **стабилен** в рамках одного deliverable — если решил удалить finding по ходу review, **не переиспользуй** его ID, оставь дырку (так merge-агент увидит «реальное» количество, не «оставшееся»).

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
- [ ] Шапка deliverable машинно-парсебельна (точное соответствие § 8.2)
- [ ] Все findings соответствуют формату § 8.4 — stable ID (§ 8.6), severity / category / confidence из controlled vocab (§ 8.5), file:line attribution
- [ ] Tech-debt backlog: каждый item с predicted scope (S/M/L) и priority (P0/P1/P2), ссылается на source finding ID(s)
- [ ] Recommendation на следующий спринт имеет confidence (§ 8.3 пункт 5)
- [ ] Metrics snapshot зафиксирован на момент завершения (не на момент старта)
- [ ] `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<REVIEWER_ID>.md` создан и закоммичен:
  - один commit
  - message: `docs(review): post-Living-KB audit by <REVIEWER_ID> — N findings (C/M/m), recommendation: <X>` (где C/M/m = critical/major/minor counts)
- [ ] **Не была прочитана работа другого ревьюера** (если в `docs/notes/` уже лежит `REVIEW_2026-04-26_POST_LIVING_KB__<other-id>.md` — он считается forbidden до завершения этой сессии, см. § 15.3)
- [ ] (опционально, но желательно) Финальное сообщение review-агента содержит **executive summary** (5-10 строк) — чтобы юзер мог принять решение по следующему спринту, не читая 6-страничный deliverable

---

## 12. После прохождения — НЕ начинать спринт

В одиночку этот deliverable **не приводит к изменениям**. После твоей работы юзер запустит:

1. **Вторая review-сессия** — другая модель, отдельное окно, тот же промпт, другой `REVIEWER_ID`. Никакая координация между двумя сессиями не требуется и **не допускается**.
2. **Merge-сессия** — отдельная сессия по [`docs/notes/START_PROMPT_REVIEW_MERGE.md`](START_PROMPT_REVIEW_MERGE.md), которая:
   - читает оба deliverable,
   - сводит findings (deduplication, conflict resolution, severity calibration),
   - производит итоговый план исправлений `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`,
   - именно из этого плана будут открыты GitHub issues и запущен следующий спринт.

То есть итоговая цепочка: **2 × review (этот промпт) → merge-сессия → fix-спринт**.

Что **не** делает review-агент:

- ❌ не заполняет post-watch comment в issue #15 — это часть merge-сессии или fix-спринта
- ❌ не открывает tech-debt issues — это часть fix-спринта
- ❌ не выбирает следующий спринт самолично — это часть merge-сессии (двое ревьюеров могут разойтись в Recommendation)

После своей работы review-агент **завершает сессию финальным сообщением** для юзера:
- путь к собственному deliverable (`docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<REVIEWER_ID>.md`)
- counts: critical / major / minor
- top-3 critical findings (одной строкой каждый, для quick-glance)
- own recommendation на следующий спринт + confidence
- список OPEN QUESTIONS (если есть)

---

## 13. Ground rules для review-агента

1. **Ничего не fix'ить.** Любая правка кода / docs — отдельный PR после merge-сессии. Это **read-only** аудит. См. § 3.1 — точный список запрещённых tool calls.
2. **Не открывать GitHub issues** — только формулировать в § 4 deliverable. Юзер заведёт по итогу merge.
3. **Если что-то непонятно — записать как OPEN QUESTION в § 1 (executive summary).** Не гадать, не интерпретировать.
4. **TODO/FIXME в коде — НЕ findings.** Это уже backlog. Findings — это **расхождения** между декларацией и реализацией, или architectural smell, или missing observability.
5. **Не цитировать целые файлы.** Только конкретные строки + интерпретация (max ~10 строк code-блока на finding).
6. **При сомнении — снижай confidence, не severity.** Severity = «насколько это важно если правда»; confidence = «насколько я уверен что это правда». Это разные оси. Низкий confidence + high severity = валидный finding для merge'а (другой ревьюер либо подтвердит, либо опровергнет).
7. **Findings без attribution не принимаются** — каждое должно ссылаться на конкретный файл:строка или коммит.
8. **Не читать чужие deliverable** — если в `docs/notes/` уже есть `REVIEW_2026-04-26_POST_LIVING_KB__<other-id>.md`, он forbidden до окончания твоей работы. Это нужно для независимости перспектив (см. § 15.3).
9. **Detection > prescription.** Твоя задача — **обнаружить** расхождения, не **предписать** конкретное решение. Suggested action (§ 8.4) — это draft, fix-агент имеет право на альтернативу.
10. **Каждый finding должен пройти 3 теста перед записью:**
    - **Existence test:** есть ли реально в коде/доках то, на что я ссылаюсь? (open the file, verify the line)
    - **Damage test:** что случится с пользователем / прод / архитектурой если оставить как есть? (если ничего не случится — это не finding)
    - **Verifiability test:** другой ревьюер с другим контекстом сможет независимо подтвердить? (если зависит от моей интерпретации — снижай confidence)

---

## 14. Citation back

Когда review-агент будет работать в новой сессии, он может цитировать:

- **Этот промпт:** `docs/notes/START_PROMPT_REVIEW_POST_LIVING_KB.md` (commit где он появился)
- **Транскрипт сессии-источника** (где обсуждали timing review-сессии): UUID `518d7766-dd0b-4f5d-bc6c-5bfb478264da`
- **Образцы стиля:** `docs/notes/START_PROMPT_SESSION40_CODE_REVIEW.md`, `docs/notes/START_PROMPT_PLANNING_F5C.md`
- **Watch sprint-источник:** UUID `736f589b-bfea-4da0-82b3-bae591f5b016` (где F5-C задеплоен на VPS, SSH alias `prod` сохранён)

Эти ссылки — *не для копипасты в deliverable*, а для подтягивания контекста в случае ambiguity.

---

## 15. Ensemble mode (multi-window review protocol)

Этот промпт запускается в **двух независимых окнах** разными моделями. Их выводы потом сводит третья сессия по [`START_PROMPT_REVIEW_MERGE.md`](START_PROMPT_REVIEW_MERGE.md). Чтобы это сработало, протокол **обязан** соблюдаться обоими ревьюерами.

### 15.1 Handshake (первое сообщение в новой сессии)

В первом сообщении к review-агенту юзер передаёт `REVIEWER_ID` (например, `opus`, `sonnet45`, `gpt5-codex`, или просто `A` / `B`). Если `REVIEWER_ID` не передан в явном виде — **первый и единственный допустимый clarifying question** перед началом работы:

> «Прежде чем начать — какой REVIEWER_ID использовать для этой сессии? Это нужно для имени deliverable и для отделения от второго ревьюера в ensemble-режиме.»

После получения `REVIEWER_ID` — приступать к работе без дальнейших уточнений (любые остальные вопросы фиксируются как OPEN QUESTIONS в § 1 deliverable).

### 15.1a Запуск двух окон — ПАРАЛЛЕЛЬНЫЙ (mandatory)

Юзер запускает оба review-окна **одновременно**, до того как любое из них закоммитит свой deliverable. Это:

1. Гарантирует одинаковый base commit для обоих ревьюеров (§ 15.4 calibration anchor).
2. **Исключает metadata leakage** через `git log`: к моменту первого `git log` в окне 2 коммита окна 1 ещё нет (и наоборот).
3. Сокращает wall-clock время (~6-8ч вместо ~12-16ч).

Что это означает практически для review-агента:
- При старте делай `git rev-parse --short HEAD` — это твой base commit (зафиксируй в шапке § 8.2).
- В течение работы **не делай** `git pull` — даже если знаешь, что юзер мог что-то добавить. Работай на стартовом коммите. Если есть критическая необходимость в свежем коммите — это OPEN QUESTION для юзера.
- При коммите своего deliverable — `git commit` **без** предварительного `git pull`. Если push отклонён из-за non-fast-forward — это сигнал, что второе окно уже коммитило; в этом случае: **не rebase**, **не merge** — сообщить юзеру и завершить сессию (юзер сам решит конфликт или разнесёт по веткам).

### 15.2 Independence rules (что обеспечивает «честность» ensemble)

| Правило | Зачем |
|---|---|
| **Не читать deliverable другого ревьюера** до завершения собственного | если ревьюер B читает работу ревьюера A, ensemble превращается в «echo chamber» — B будет искать только то, что A пропустил, а не независимо проверять весь scope |
| **Не общаться с другими ревьюерами** через любые каналы (общие файлы, запись в shared note, перекрёстные ссылки) | то же самое |
| **Не использовать subagents для разделения работы** между ревьюерами | каждый ревьюер должен пройти **все 8+8 зон лично** — это даёт coverage; subagents допустимы для рутинных подсчётов внутри одной зоны (например, run pytest --cov), но не для делегирования зоны целиком |
| **Если случайно увидел work-in-progress другого ревьюера** (через recent files, через transcript-цитирование, через `git log`) — пометить это как **disclosure event** в § 1 OPEN QUESTIONS | merge-агент учтёт пониженную независимость при калибровке |
| **Метрики snapshot брать самостоятельно**, не доверять цифрам из § 4 этого промпта | цифры в § 4 могут устареть; верифицируй каждую (HEAD, alembic heads, test count) при старте; если расхождение — записать в § 6 deliverable, а не править § 4 этого промпта |

### 15.3 Изоляция на уровне файлов

Когда стартует **второй** ревьюер, в `docs/notes/` уже может лежать deliverable первого. Что делать:

- ✅ **Можно** убедиться, что файл существует (`ls docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__*.md`) — это безопасно и помогает не перетереть его
- ❌ **Нельзя** открывать содержимое (Read, Grep по содержимому, indirect via Shell `cat`) — это нарушает § 15.2
- ❌ **Нельзя** запускать `git log -p` на этот файл, `git show <commit-with-deliverable>`, `git diff` где он фигурирует
- ✅ **Можно** видеть факт коммита через `git log --oneline` (имя файла из commit message), но не открывать содержимое

### 15.4 Calibration anchors (общие точки отсчёта)

Чтобы **результаты** двух ревьюеров были сравнимы, оба обязаны зафиксировать одни и те же базовые величины в одинаковом формате (см. § 8.3 пункт 6 «Metrics snapshot»). Merge-агент сравнит эти значения первыми — если расхождение в HEAD / alembic head / test count — это **disclosure event** (один из ревьюеров работал на другом коммите) и требует переcorrelation.

### 15.5 Termination signal

Review-сессия считается завершённой, когда:
- deliverable закоммичен с message по формату § 11
- финальное сообщение юзеру (§ 12) отправлено
- агент прекращает работу — **не** ждёт «второго раунда», **не** напрашивается на правки, **не** запускает merge самостоятельно

Если после завершения юзер захочет уточнений — это новая сессия (или продолжение этой через `resume`), но любые правки deliverable — **только** через явный запрос юзера и **только** в рамках этого же `REVIEWER_ID` (нельзя «дополнить» от имени другого ревьюера).

### 15.6 Чего ensemble НЕ решает (и не должен)

- **Outcome conflict** между двумя ревьюерами — это нормально и желательно. Merge-агент калибрует severity (если оба нашли — точно critical; если один нашёл — sanity check; если оба пропустили — fix-агент может найти позже).
- **Merge сам по себе** — отдельная сессия, не задача review-агента.
- **Decision на следующий спринт** — каждый ревьюер даёт свою Recommendation с confidence; merge-агент сводит их с учётом watch-метрик; финальное решение — за юзером.
