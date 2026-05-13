# Roadmap v3 — Production-First Strategy

> ⚠️ **DEPRECATED 2026-05-13.** This roadmap has been superseded by
> [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
> as the forward-looking source of truth (current contract pointer +
> audience-driven Wave 1 step 1/2/3 sequence + Next-contract candidates).
> This file is kept for **historical reference** of completed P6a/P6b/D1–D5/
> Perf/Cross-val/Cross-dev/F4/F5-A/F8-A phases.
>
> **Items not yet migrated to ROADMAP_KARPATHY** (forward-looking Wave 2-5
> tail; tracked for migration in a future docs-hygiene sprint, not blocking
> Wave 1 step 3):
>
> - **Wave 2 re-rank (post-Living-KB):** F11 P2 calibration, F5-C P2
>   (TTL/diff/digest + Bot tools, issue #15 in `FUTURE_FEATURES.md`),
>   F1 Full (Configurable Prompt System DB + A/B), F10-A (Multimodal —
>   images + voice), F12-A (Channel Discovery).
> - **Wave 3 — User Experience:** F6 enhancements, F1 full DB/versioning.
> - **Wave 4 — Scale & Monetize:** F9-2 (advanced security), F8-B
>   (Redis + horizontal scaling), F7 (Billing).
> - **Wave 5 — Strategic:** F3 (WhatsApp / Discord connectors),
>   F5-D (Knowledge Graph), F10-C (full multimodal), F8-C.
> - **Deferred individual items:** F5-B (near-duplicate via embedding ≥ 0.97),
>   UI phase (P6c Web Catalog, P6d Web Chat), TG Bot Hybrid, Grafana alerting
>   (входит в F8-A scope).
>
> See [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md § Next contract — TBD`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
> for the canonical "what's next" pointer and
> [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) for
> the next-contract candidate analysis.

> **Wave 1 closed 2026-04-26** — Living-KB контракт закрыт (D.1 + F11 + F5-C).
> См. `## Done — Living-KB contract (Wave 1)` ниже и
> [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
> § «2026-04-26 — Contract closed» для full deliverables.
> Wave 2 re-ranked после debt-fix sprint'а (F11 P2 — closest follow-up after TD-02).

**Дата:** 30 марта 2026 (обновлено: 2026-04-26 — Living-KB closure + Wave 2 re-rank)
**Статус:** Активный
**Предыдущие документы:**
- `SESSION48_PRODUCT_STRATEGY.md` — исходная стратегия продукта
- `SESSION48_ROADMAP_V2.md` — roadmap v2 (P6a → P6b → P6c → P6d → P7 → P8)
- `docs/technical-debt-roadmap.md` — трекер техдолга S1–S7, D1

---

## Done — Living-KB contract (Wave 1)

| Sprint | Дата | Что закрыто | См. |
|---|---|---|---|
| D.1 | 2026-04-25 | Topicization hardening — truthful `failed_stage`, per-batch checkpointing, `error_message` persistence (4096-char contract aligned in TD-01, post-Living-KB Phase 1). | CHANGELOG § Sprint D.1 |
| F11 | 2026-04-25 | Topic Watchlist MVP — hybrid keyword+embedding scoring, idempotent matches, instant push via aiogram, MCP/Bot/CLI surface. | CHANGELOG § Sprint F11 |
| F5-C | 2026-04-26 | Evolving Topic Summaries MVP — counter-driven re-summarize, append-only `topic_card_versions`, MCP/CLI surface. | CHANGELOG § Sprint F5-C |

24h F5-C deploy-watch окно: `2026-04-26T11:07:13Z` → ≈`2026-04-27T11:07Z`,
verdict reporting per [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
§ Post-watch report.

---

## 1. Что выполнено

### Продуктовые фазы (из Roadmap v2)

| Фаза | Описание | Статус |
|------|----------|--------|
| P6a | API Enrichment (Topics, Channels, Documents) | **Выполнено** |
| P6b | MCP Server (17 tools, 3 resources) | **Выполнено** |
| P6b-val | Валидация MCP в Claude Desktop / Cursor | **Выполнено** (неформально) |

### Технический долг

| Сессия | Описание | Статус |
|--------|----------|--------|
| S1–S6 | MCP logging, management tools, DB optimization, N+1, cleanup, тесты | **Выполнено** |
| S7 | Singleton Database, unified structlog, lazy formatting | **Выполнено** |

### Production-подготовка (Фаза D)

| Задача | Описание | Статус |
|--------|----------|--------|
| D1 | MCP Streamable HTTP + bearer auth + Docker Compose MCP-сервис | **Выполнено** |
| D2 | Production Docker + конфигурация (multi-stage build, health checks, graceful shutdown) | **Выполнено** |
| D3 | Telegram Session в Docker (CLI `auth`, volume для sessions, expired session) | **Выполнено** |
| D4 | Backup (`docker/backup.sh` + `restore.sh`, ротация 7 дней) + Мониторинг (Prometheus, Grafana, 2 дашборда) | **Выполнено** |
| D5 | Reverse Proxy (Nginx на хосте) + TLS (Let's Encrypt, auto-renewal) | **Выполнено** |

### Фаза Perf: Производительность при масштабировании — **Выполнено**

| Задача | Результат |
|--------|-----------|
| Подключение новых каналов | +3 канала (AgeManagment, genotek, Lab4health) + LongevityClub ранее |
| Профилирование pipeline | Замеры по каждому этапу (ingestion, processing, topicization, embedding) |
| Оптимизация batch/concurrency | Batch upserts, parallel LLM calls (concurrency 10), 1.6x speedup |
| Трекинг токенов | Input/output tokens в логах и CLI для processing и topicization |
| Фикс модели processing | Исправлена подстановка Sonnet вместо Haiku через docker-compose env |
| Фикс asyncio event loop | Устранён баг двойного `asyncio.run()` в `topicize --mode auto` |

### Фаза Cross: Кросс-канальная валидация — **Выполнено** (1 апреля 2026)

Прогон сценариев 10–13 из MCP-валидации на 5 каналах, ~5070 документах, 382 темах:

| # | Сценарий | Результат |
|---|----------|-----------|
| 10 | Кросс-канальный поиск (без channel_id) | **PASSED** — результаты из 3 каналов (genotek, labdiagnostica, LongevityClub) |
| 11 | Сравнение тем Lab4health vs genotek | **PASSED** — 58 и 164 темы, пересечения по генетике, витаминам, онкологии |
| 12 | Q&A по всем каналам | **PASSED** — ответ с источниками из genotek, labdiagnostica, AgeManagment |
| 13 | Фильтрация по topic_type=singleton | **PASSED** — 68 singleton-тем из genotek и AgeManagment |

### Текущие метрики

- **5 каналов:** labdiagnostica_logical (1124), Lab4health (1797), AgeManagment (1075), genotek (1070), LongevityClub (339)
- **5405 processed documents**, **401 тема**, полный embedding, **264 cross-channel topic links**
- **Coverage:** AgeManagment 97.8%, labdiagnostica 93.0%, Lab4health 99.2%, genotek 97.0%, LongevityClub 84.7%
- **Тесты:** 855 collected (838 passed, 0 failures, 16 skipped)
- **MCP:** 17 tools, 3 resources, stdio + Streamable HTTP
- **Bot:** 17 tools (V1.2: full operational interface), задеплоен 9 апреля 2026
- **Docker:** Compose с postgres, tg_parser, mcp, bot, prometheus, grafana, ollama (optional)
- **Pipeline tokens (новые каналы):** ~6.2M processing (Haiku) + ~1.4M topicization (Sonnet)

---

## 2. Стратегия и приоритеты

### Ключевое наблюдение

MCP-сервер, подключённый к Claude Desktop и другим MCP-клиентам, уже даёт полноценный интерфейс для работы с базой знаний. После завершения production-базы следующая практическая проверка продукта — **Telegram-бот для тестовых пользователей**, работающий на существующем RAG-слое и Gemini.

### Эволюция фаз

```
Roadmap v2 (исходный):          Roadmap v3 (фактический):
  P6a → P6b → P6c → P6d           P6a → P6b → D1..D3 (Production) ✅
       → P7 → P8                        → Perf ✅ → Cross-val ✅
                                         → Cross-dev ✅ → D4/D5
                                         → Phase 3: TG Bot on Gemini
                                         → P6c/P6d / optional hybrid bot
```

### Два продукта из одной кодовой базы (перспектива)

| Вариант | Описание | Аудитория |
|---------|----------|-----------|
| **Self-hosted** | `docker-compose up`, все данные у пользователя | Разработчики, компании |
| **SaaS** (будущее) | Облачный сервис, zero-setup | Конечные пользователи |

Self-hosted — первый. SaaS строится поверх: добавляются multi-tenant, OAuth, биллинг.

### Living KB и karpathy-like ориентир

Долгосрочная склейка принципов развития базы знаний (provenance, дешёвый hybrid retrieval, инкрементальные темы и алерты, волны после F11): [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md). Документ **дополняет** этот roadmap v3, не заменяет таблицы приоритетов ниже.

---

## 3. Roadmap: ближайшие шаги

### ~~Фаза D: Production-Ready Self-Hosted~~ — в основном ВЫПОЛНЕНО

**Цель:** `docker-compose up` запускает полностью рабочий сервер с MCP, API, scheduler и бэкапами.

| Задача | Статус | Примечание |
|--------|--------|------------|
| D1: MCP Streamable HTTP | ✅ | Транспорт, bearer auth, Docker Compose `mcp` сервис |
| D2: Production Docker | ✅ | Multi-stage build, health checks, graceful shutdown, `.env.production.example` |
| D3: TG Session в Docker | ✅ | CLI `auth`, volume `data/sessions`, обработка expired session |
| D4: Backup | ✅ | `docker/backup.sh`, `docker/restore.sh`, ротация 7 дней, cron daily 02:00 |
| D4: Мониторинг | ✅ | Prometheus (API + MCP scrape), Grafana (system + pipeline dashboards), auto-provisioning |
| D5: Reverse Proxy + TLS | ✅ | Nginx на хосте, 3 vhosts (API, MCP, Grafana), Let's Encrypt auto-renewal |

---

### ~~Фаза Perf: Производительность при масштабировании~~ — ✅ ВЫПОЛНЕНО

**Результат:** 5 каналов, ~5070 документов, оптимизированный pipeline.

- Подключено 3+1 новых каналов (AgeManagment, genotek, Lab4health, LongevityClub)
- Batch upserts для DB (raw, processed, embeddings) — 1.6x speedup
- Parallel LLM calls с concurrency 10 (processing), 5 (topicization)
- Трекинг input/output tokens в логах и CLI
- Фикс подстановки модели в docker-compose env
- Фикс бага двойного `asyncio.run()` в topicize --mode auto

---

### ~~Фаза Cross-val: Кросс-канальная валидация~~ — ✅ ВЫПОЛНЕНО (1 апреля 2026)

Прогон сценариев 10–13 подтвердил: кросс-канальные функции работают из коробки.

**Что работает:**
- Поиск без `channel_id` → результаты из нескольких каналов, `channel_id` в каждом результате
- Q&A без `channel_id` → ответ с источниками из разных каналов
- `list_topics` без `channel_id` → все темы глобально, фильтрация по `topic_type`
- `list_channels` → сводка по всем 5 каналам (raw, processed, topics, coverage)

**Выявленные улучшения (→ Cross-dev) — все решены:**
1. ~~Diversity в поиске~~ — отклонено: pure relevance корректнее, доминирование одного канала означает его объективную релевантность
2. ~~Пагинация тем~~ — AI-агент использует `has_more` для навигации
3. ~~Глобальная статистика по типам тем~~ — реализовано в Cross-dev 2 (`get_cross_channel_stats`)
4. ~~Coverage дисбаланс~~ — решено в Cross-dev 4: AgeManagment 68% → **97.8%**, все каналы ≥ 84%

---

### ~~Фаза Cross-dev: Кросс-канальные улучшения~~ — ✅ ВЫПОЛНЕНО (1 апреля 2026)

**Цель:** Улучшить кросс-канальный опыт на основе результатов валидации.

#### ~~Cross-dev 1: Diversity в поиске~~ — ОТКЛОНЕНО

Решение: оставить pure relevance. Доминирование одного канала в top-K — не баг, а отражение его объективной релевантности запросу. Искусственное ограничение скроет полезную информацию от пользователя.

#### ~~Cross-dev 2: Кросс-канальная статистика (MCP tool)~~ — ✅ ВЫПОЛНЕНО

**Решение:** MCP tool `get_cross_channel_stats(channel_id=None)` — агрегированная аналитика по каналам: документы, темы (singleton/cluster), coverage, пересечения ключевых слов. Режим single-channel: детальная статистика + related channels.
**Файлы:** `tg_parser/services/analytics_service.py` (новый), `tg_parser/mcp_server.py`, `tests/test_analytics_service.py` (11 тестов)

#### ~~Cross-dev 3: Кросс-канальная топикизация~~ — ✅ ВЫПОЛНЕНО

**Решение:** Topic linking (не merge) — таблица `topic_links` для связей между темами из разных каналов. Алгоритм: Jaccard (keywords) + cosine (embeddings). 264 ссылок создано из 58K пар (threshold=0.3).
**Файлы:** `tg_parser/domain/models.py` (TopicLink), `tg_parser/storage/ports.py` (TopicLinkRepo), `tg_parser/storage/sqlalchemy/topic_link_repo.py` (новый), `tg_parser/services/topic_linking_service.py` (новый), `tg_parser/cli/app.py` (link-topics), `tg_parser/mcp_server.py` (get_related_topics, обновлённый get_topic_details), `tests/test_topic_linking_service.py` (13 тестов)

#### Cross-dev 5: Кросс-канальная инкрементальная топикизация — ✅ ВЫПОЛНЕНО (1 апреля 2026)

**Решение:** Гибридная кросс-канальная инкрементальная топикизация в 3 фазах:
- **Phase 2 Enhancement:** LLM при поиске/создании тем видит темы ВСЕХ каналов (предотвращение дубликатов)
- **Phase 3 (новая):** После назначения документа, автоматически создаются TopicLinks к похожим темам из других каналов
- Управляется настройкой `cross_channel_topicization` (по умолчанию вкл.) и CLI флагом `--cross-channel/--no-cross-channel`
- Принцип: документ ВСЕГДА остаётся в теме своего канала; кросс-связи — только через TopicLinks

**Файлы:** `tg_parser/config/settings.py` (+2 настройки), `tg_parser/domain/models.py` (+cross_channel_links_created), `tg_parser/processing/topicization_prompts.py` (расширенный промпт), `tg_parser/processing/topicization.py` (cross_channel_topics param), `tg_parser/services/topicization_service.py` (+_run_cross_channel_linking, _load_cross_channel_topics, _collect_touched_topic_ids), `tg_parser/cli/app.py` (--cross-channel flag), `tests/test_cross_channel_topicization.py` (20 тестов: хелперы, промпт, оркестратор, prompt size stress)
**Тестирование:** CLI smoke, unit-тесты оркестратора (cross_channel=True/False/None), live E2E на реальной БД (--cross-channel создал 11 TopicLinks, 338 тем контекста), MCP верификация, совместимость с link-topics, prompt size до 1000 тем

#### ~~Cross-dev 4: Улучшение coverage~~ — ✅ ВЫПОЛНЕНО

**Результат:** Инкрементальная топикизация для всех каналов с coverage < 80%:
- AgeManagment: 68.3% → 92.0% → **97.8%** (+10 тем, включая инкрементальные с --cross-channel)
- labdiagnostica_logical: 76.1% → **93.0%** (+4 темы)
- Lab4health: 82.0% → **99.2%** (+5 тем)
Все каналы теперь ≥ 84%. Общее число тем: 401.

---

### ~~Фаза D-remaining: Production Infrastructure~~ — ✅ ВЫПОЛНЕНО (2 апреля 2026)

**Сервер:** `redboxtgbot` (Ubuntu 24.04, `efimov.mobi`)

#### D4-mon: Мониторинг — ✅

- Prometheus scrapes API (`tg_parser:8000/metrics`) + MCP (`mcp:8080/metrics`)
- Grafana с auto-provisioned datasource и 2 дашбордами (system, pipeline)
- Grafana доступна на `https://grafana.tgp.efimov.mobi`
- Метрики: HTTP rate/latency/errors, LLM requests/duration/tokens, pipeline messages, scheduler tasks

#### D5: Reverse Proxy + TLS — ✅

- Nginx на хосте (не Docker Caddy) — 3 vhosts:
  - `tgp.efimov.mobi` → API (:8000), `/metrics` заблокирован (403)
  - `mcp.tgp.efimov.mobi` → MCP (:8080), WebSocket/SSE support
  - `grafana.tgp.efimov.mobi` → Grafana (:3001)
- TLS через Let's Encrypt (certbot, auto-renewal)
- Все порты привязаны к `127.0.0.1` — не торчат наружу
- Документация: `docs/SERVER_ARCHITECTURE.md`

---

### Фаза 3: Telegram Bot on Gemini — Agentic Read-Heavy MVP

**Цель:** Дать пользователям, не работающим с IDE и MCP, полноценный человеческий интерфейс к системе tg_parser через Telegram-бота.

**Принятые решения:**
- **LLM backend:** Gemini
- **Доступ к модели:** `GEMINI_API_KEY`
- **Развёртывание:** сразу новый `tg_bot` сервис в `docker-compose.yml`
- **Bot framework:** `aiogram`
- **Режим доступа:** allowlist-only для пилота
- **Архитектура:** agent/orchestrator layer на Gemini tool-calling над внутренними Python-сервисами; MCP остаётся внешним интерфейсом для IDE/агентов
- **UX:** free-form чат, structured-first ответы с источниками

**V1.0 Capabilities (read-only):**
- Q&A по базе знаний (ask_question)
- Семантический поиск (search_knowledge_base)
- Навигация по темам (list_topics, get_topic_details)
- Обзор каналов (list_channels)
- Просмотр документов (get_document)
- Связанные темы (get_related_topics)
- Кросс-канальная аналитика (get_cross_channel_stats)

**Версионная лестница:**
- V1.0: agentic read-heavy MVP ✅
- V1.1: safe writes (trigger_pipeline, pause/resume) ✅
- V1.2: full operational interface (add/remove channel, LLM config) ✅

**Scope V1.0:**
- Agent layer: Gemini tool-calling для выбора capability по free-form сообщению
- Structured-first ответы: summary, key points, sources
- `/start`, `/help`, таймауты, обработка ошибок, split длинных ответов
- Long polling без webhook и без нового публичного ingress
- Allowlist, rate limiting, logging с `telegram_user_id` и request id
- Пилот на 2-3 пользователях

**Критерии готовности V1.0:**
- `docker compose up` поднимает отдельный `tg_bot` сервис
- Allowlisted пользователь может: задать вопрос, поискать материалы, посмотреть темы/каналы/документы, получить кросс-канальную аналитику
- Ответы структурированы с источниками
- Документация описывает запуск, env vars и ограничения прототипа

---

### Фаза UI: Интерфейсы (отложена)

**Цель:** Доступ к базе знаний без LLM-клиента.

| Подфаза | Описание | Приоритет |
|---------|----------|-----------|
| P6c: Web Catalog | Next.js, навигация по темам/каналам | Средний |
| P6d: Web Chat | Встроенный чат с RAG, conversation history | Средний |
| TG Bot Hybrid | Оптимизация Phase 3: direct API/router/hybrid path при необходимости | Низкий |

**Предпосылка:** Cross-dev завершён. Может начаться параллельно с D-remaining.

---

## 4. Визуальная схема

```
              ВЫПОЛНЕНО ✅                        ПЛАНИРУЕТСЯ
    ┌──────────────────────────┐
    │ P6a API Enrich           │     Волна 1: Фундамент (~1.5 сессии)
    │ P6b MCP Server           │     ┌────────────────────────────┐
    │ S1–S7 Tech Debt          │     │ F9-quick: Security Fixes   │
    │ D1 Streamable HTTP       │────▶│ F8-A: Hardening            │
    │ D2 Production Docker     │     │ Пилот бота (2–3 users)     │
    │ D3 TG Session in Docker  │     └────────────┬───────────────┘
    │ D4 Backup + Monitoring   │                  │
    │ D5 TLS/Proxy (Nginx+LE) │     Волна 2: Core Value (~4 сессии)
    │ Perf: 5 каналов, 5070 doc│     ┌────────────▼───────────────┐
    │ Cross-val + Cross-dev    │     │ F5-A: KB + Topic RAG       │
    │ Phase 3: TG Bot V1.2    │     │ F2: Parse-Only Export      │
    │  Gemini + 17 tools      │     │ F10-A: Images + Voice      │
    │  aiogram + allowlist     │     │ F12-A: Channel Discovery   │
    │ v4.2.0                   │     └────────────┬───────────────┘
    └──────────────────────────┘                  │
                                     Волна 3: UX (~6–7 сессий)
                                     ┌────────────▼───────────────┐
                                     │ F6: Scheduled Digests      │
                                     │ F11: Topic Watchlist       │
                                     │ F1: Configurable Prompts   │
                                     │ F5-C: Evolving Summaries   │
                                     └────────────┬───────────────┘
                                                  │
                                     Волна 4+: Scale & Monetize
                                     ┌────────────▼───────────────┐
                                     │ F4: Multi-User/Workspaces  │
                                     │ F7: Billing                │
                                     │ F8-B/C: Redis, Horizontal  │
                                     │ F3/F5-D: Sources, KG       │
                                     └────────────────────────────┘
```

---

## 5. Техдолг — ✅ ЗАКРЫТ (1 апреля 2026)

**Результаты:**

| Метрика | До | После |
|---------|-----|-------|
| Failing tests | 2 | **0** |
| `except Exception` | 91 (35 файлов) | **62** (24 файла, остаток — boundary handlers) |
| Total tests | 729 | **855** (+126, включая Phase 3 Bot и F9) |
| Test gaps | 5 | **2** (ingestion service, pipeline service) |

**Выполнено:**
- **TD-1:** Исправлены 2 pre-existing test failures (mock `generate_with_usage`)
- **TD-2:** 29 `except Exception` → typed exceptions (SQLAlchemyError, ValueError, RuntimeError, httpx.HTTPError и др.) в storage, services, processing, MCP server, health checks, agents
- **TD-3:** Добавлены тесты: TopicLinkRepo integration (7), topicization prompt builders (16), CLI smoke (11)
- **TD-4:** Silent `except pass` → `logger.warning` (mcp_server.py, orchestrator.py); BearerTokenVerifier — уже корректно
- Оставшиеся `except Exception` — осознанные boundary handlers (CLI, scheduler, agent orchestration)

---

## 6. Текущий статус и следующие шаги

**Всё задеплоено и работает.** Техдолг закрыт, инфраструктура развёрнута (D1–D5), TG Bot V1.2 задеплоен.

Статус на 13 апреля 2026:
- Сервер (`redboxtgbot`): API, MCP, Bot, Prometheus, Grafana, Nginx+TLS — **все работают**
- Bot V1.2: 17 tools (read + write с two-phase confirmation), 855 тестов pass
- PR #1 (`feature/phase3-tg-bot` → `main`): **смержен** (10 апреля 2026)
- **F9 Phase 1** в проде: auth на API, CORS, логи, generic 500; `API_KEY_REQUIRED`, ключи в compose env, бот с allowlist
- Версия проекта: **v4.2.0**

### Стратегическое планирование (актуализация 13 апреля 2026)

Проведён аудит и обсуждение 12 перспективных направлений развития. Детали, DB schema, планы реализации и дорожная карта из 5 волн — в **[`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md)**.

Функции (F1–F12):

| ID | Функция | Effort | Приоритет |
|----|---------|--------|-----------|
| F1 | Configurable Prompt System | ~2 сессии | Средний |
| F2 | Channel Content Export (Parse-Only) | ~0.5 сессии | Средний |
| F3 | Multi-Source Connectors (WA, Discord) | ~2–3 сессии | Низкий |
| F4 | Multi-Tenancy (Users + Workspaces) | ~2–4 сессии | Низкий |
| F5 | Living Knowledge Base | ~1.5–6+ сессий | Высокий |
| F6 | Scheduled Digests | ~1.5–2 сессии | Средний-высокий |
| F7 | Monetization (Billing) | ~3–4 сессии | Средний |
| F8 | Scalability & Resilience | ~1–3+ сессий | Высокий |
| F9 | Security Hardening | ~0.5–3 сессии | **ВЫСШИЙ** (Phase 1 ✅) |
| F10 | Multimodal Content Processing | ~1–4 сессий | Средний |
| F11 | Topic Watchlist (тематические алерты) ✅ DONE | ~1.5–2 сессии | Средний-высокий |
| F12 | Channel Discovery (поиск каналов) | ~1–3 сессий | Средний |

### Ближайшие шаги (приоритет — актуализация 15 апреля 2026)

| # | Шаг | Effort | Статус |
|---|-----|--------|--------|
| ~~1~~ | ~~Merge PR #1 в `main`~~ | — | ✅ Выполнено 10 апреля 2026 |
| ~~2~~ | ~~**F9 Phase 1: Security Quick Fixes**~~ | ~0.5 сессии | ✅ Выполнено 10 апреля 2026 |
| ~~3~~ | ~~**F4: Multi-Tenancy** (все 5 фаз)~~ | ~3 сессии | ✅ Выполнено 15 апреля 2026, v4.3.0 |
| ~~4~~ | ~~**Doc Cleanup & Audit**~~ | ~0.5 сессии | ✅ Выполнено 15 апреля 2026 (27 исправлений, MCP Agent Guide) |
| ~~5~~ | ~~**Wave 1.5: RAG & Prompt Config**~~ | ~0.5–0.7 сессии | ✅ Выполнено (PromptLoader, RAG prompt refactor, static RAG env vars) |
| ~~6~~ | ~~**F8-A: Hardening**~~ | ~1 сессия | ✅ Выполнено (unified retry, DB pool metrics, circuit breaker) |
| ~~7~~ | ~~**F5-A: Persistent KB + Topic RAG**~~ | ~1.5 сессии | ✅ Выполнено (Phase 1 hybrid search, Phase 2 tuning, Phase 3 dedup) |

**Выбранная последовательность:** Wave 1.5 → F8-A → F5-A (зафиксирована 15 апреля 2026) — **полностью пройдена**, см. таблицу ниже для пост-F5-A treka.

### Пост-F5-A Phase 3 — утверждённая последовательность (18 апреля 2026)

После мёрджа F5-A Phase 3 (PR #9 — content-hash deduplication) зафиксирован
следующий порядок работ до конца Волны 2 и первой части Волны 3:

| # | Шаг | Effort | Обоснование |
|---|-----|--------|-------------|
| 1 | ~~**F5-A Phase 3: Deduplication**~~ | ~0.5 сессии | ✅ Выполнено 18 апреля 2026 (PR #9 merged — content-hash MVP) |
| 2 | ~~**F2: Channel Content Export (Parse-Only)**~~ | ~0.5 сессии | ✅ Выполнено 18 апреля 2026 (PR #10 — `feat/f2-parse-only-export`) — `level={raw,processed,full}` через CLI/API/MCP/bot, JSON envelope + NDJSON, `raw_payload` excluded |
| 3 | ~~**F6: Scheduled Digests**~~ | ~1.5–2 сессии | ✅ Выполнено 19 апреля 2026 (PR #11 — `feat(F6): Scheduled Digests — cron-driven channel summaries via Telegram bot`) — `subscribe_digest` / `list_digests` / `unsubscribe_digest` через CLI/MCP/bot, APScheduler-driven, ownership-aware |
| 4 | ~~**F11: Topic Watchlist**~~ | ~1.5–2 сессии | ✅ Выполнено 25 апреля 2026 (Sprint F11, два feature-коммита `026313c` + `8e07212` + self-review test expansion `0ff5bcf` на +49 кейсов) — `WatchlistService` (hybrid keyword + embedding scoring, idempotent `ON CONFLICT DO NOTHING`), scheduler hook после `run_incremental_topicization` с graceful degradation, push-уведомления (MarkdownV2 escaping, soft-delete on permanent bot failure), MCP/Bot/CLI tools (`subscribe_watchlist` / `list_watchlists` / `unsubscribe_watchlist` / `get_watchlist_matches`); итог `pytest -q` 1697 / `TEST_POSTGRES=1` 1823 passed, CI `24938330375` 5/5 зелёный. См. `CHANGELOG.md` § Sprint F11, `START_PROMPT_SPRINT_F11.md`, `F11_PR_CHECKLIST.md` |
| 5 | ~~**F5-C: Evolving Topic Summaries**~~ | ~1 сессия | ✅ Выполнено 26 апреля 2026 (Sprint F5-C, два feature-коммита `473f107` (1/2) + `53f72ef` (2/2)) — `ResummarizationService` (advisory-lock guarded `commit_resummary` с optimistic version-check, append-only `topic_card_versions` audit trail), counter increment в `_update_bundles_for_assignments` (per-batch checkpointing D.1 preserved, eventual consistency — две транзакции), scheduler hook между `run_topic_embedding` и `run_watchlist_check_for_channel` (F11-style silent log + `AnthropicBillingError` escalation), MCP/CLI surface (без Bot tools — Decision #9). См. `CHANGELOG.md` § Sprint F5-C, `START_PROMPT_SPRINT_F5C.md`, `F5C_PR_CHECKLIST.md` |

**Параллельный трек — Sprint A (migration tech-debt zero-out):**
A.5 (DI-7) ✅ → A.6 (DI-9 phase 2) ✅ → A.7 (DI-19) ✅ — все завершены **19 апреля 2026**.
Migration tech-debt = 0; alembic — единственный источник правды для схемы.
Sprint D.1 (topicization hardening) задеплоен на VPS `redboxtgbot` 25 апреля 2026 (код `cdce066`, deploy commit `33d9f48`, миграция ingestion `ac6a4414ac58`); F11 (Topic Watchlist) завершён в тот же день двумя коммитами и стал первой полной end-to-end push-фичей, переиспользующей F6 notification-инфраструктуру.
Подробности см. в `docs/notes/FUTURE_FEATURES.md` § «Migration tech-debt zero-out roadmap (Sprint A.5 → A.6 → A.7)».

**F5-B (near-duplicate via embedding ≥ 0.97)** отложен до сигнала из продовых
метрик. Обоснование:
- F5-A Phase 3 (exact content-hash) уже покрывает ~80% реальных дубликатов в
  Telegram (пересылки, репосты, одинаковые объявления в одном канале).
- Для near-dup нужен размеченный корпус для калибровки порога (0.95? 0.97?
  0.98?); без него threshold выбирается вслепую и даёт непредсказуемые
  false-positives.
- После F2/F6/F11/F5-C у нас будет реальный трафик + метрика
  `tg_dedup_duplicates_detected_total{channel_id}` + пользовательский
  фидбек → станет понятно, есть ли остаточные дубликаты, какого типа и
  стоит ли вкладывать ~1.5 сессии в embedding-based near-dup.
- Если сигнал подтвердится — near-dup возвращается в backlog как
  **F5-B Phase 3.5** с планом по образцу Phase 3 (отдельный PR, content
  hash остаётся fast-path).

Итого `2→3→4→5` — это ~4–5 сессий (Волна 2 tail + вход в Волну 3),
каждый шаг с чистым PR и независимым value delivery (never-break-main).

### Дальние горизонты

| Волна | Фокус | Effort | Функции |
|-------|-------|--------|---------|
| ~~1~~ | ~~Фундамент (security + stability)~~ | ~~~1.5 сессии~~ | ~~F9-quick ✅, F4 ✅~~ |
| ~~1.5~~ | ~~RAG & Prompt Config~~ | ~~~0.5–0.7 сессии~~ | ~~YAML все промпты + reload + rag scope + RAG-промпт рефакторинг ✅~~ |
| ~~1.5→2~~ | ~~F8-A: Hardening~~ | ~~~1 сессия~~ | ~~Unified retry, DB pool metrics, circuit breaker, graceful degradation ✅~~ |
| ~~2 (tail) / 3 (head) — Living-KB~~ | ~~Living-KB contract — D.1 + F11 + F5-C~~ | ~~~3 сессии~~ | ~~D.1 ✅, F11 ✅, F5-C ✅ (closed 2026-04-26)~~ |
| **2 (re-ranked, post-Living-KB)** | **Core Value — calibrated extensions** | ~3–4 сессии | **F11 P2** (closest after TD-02 metrics calibration), **F5-C P2** (TTL/diff/digest), **F1 Full**, **F10-A**, **F12-A** |
| 3 | User Experience (engagement) | ~3–4 сессии | F6 enhancements, F1 (полная — DB + A/B) |
| 4 | Scale & Monetize (рост) | ~11–12 сессий | F9-2, F8-B, F7 |
| 5 | Strategic (по потребности) | — | F3, F5-D, F10-C, F8-C |

**Wave 2 re-rank rationale (2026-04-26, post-Living-KB merged plan § 5):**

1. **F11 P2** — closest feature after TD-02 lands; needs ≥ 24h prod-сигнал
   на `tg_watchlist_*` метриках для калибровки threshold/notify_mode
   defaults. Не запускать до того, как metrics в проде > 24h.
2. **F5-C P2** — TTL/retention + diff API + F6 digest на topic.summary +
   Bot tools (см. issue #15 в [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § Level C).
   Не запускать до закрытия 24h F5-C deploy-watch + post-watch report.
3. **F1 Full** — полная версия Configurable Prompt System (DB, версионирование,
   A/B тесты). Базовая управляемость уже в Wave 1.5.
4. **F10-A** — Multimodal Content Processing (Level A — images + voice).
5. **F12-A** — Channel Discovery (Level A — поиск каналов).

**Примечание:** F1 в Wave 2 (полная) ≠ F1 базовой управляемости из Wave 1.5
(YAML + reload + LLM config), которая уже закрывает single-server deployment.

Отложенные направления из предыдущей версии roadmap:
- **UI фаза** (P6c Web Catalog, P6d Web Chat) — приоритет пересмотрен в пользу F5/F6/F11
- **TG Bot Hybrid** — оптимизация по результатам пилота
- **Grafana alerting** — входит в F8-A
