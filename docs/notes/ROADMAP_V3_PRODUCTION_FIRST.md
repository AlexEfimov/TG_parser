# Roadmap v3 — Production-First Strategy

**Дата:** 30 марта 2026 (обновлено: 3 апреля 2026)
**Статус:** Активный
**Предыдущие документы:**
- `SESSION48_PRODUCT_STRATEGY.md` — исходная стратегия продукта
- `SESSION48_ROADMAP_V2.md` — roadmap v2 (P6a → P6b → P6c → P6d → P7 → P8)
- `docs/technical-debt-roadmap.md` — трекер техдолга S1–S7, D1

---

## 1. Что выполнено

### Продуктовые фазы (из Roadmap v2)

| Фаза | Описание | Статус |
|------|----------|--------|
| P6a | API Enrichment (Topics, Channels, Documents) | **Выполнено** |
| P6b | MCP Server (12 tools, 3 resources) | **Выполнено** |
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
| D4 | Backup (`docker/backup.sh` + `restore.sh`, ротация 7 дней). Мониторинг Grafana — отложен | **Частично** |
| D5 | Reverse Proxy + TLS | Не начато |

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
- **Тесты:** 763 collected (747 passed, 0 failures, 16 skipped)
- **MCP:** 14 tools, 3 resources, stdio + Streamable HTTP
- **Docker:** Compose с postgres, tg_parser, mcp, ollama (optional)
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

---

## 3. Roadmap: ближайшие шаги

### ~~Фаза D: Production-Ready Self-Hosted~~ — в основном ВЫПОЛНЕНО

**Цель:** `docker-compose up` запускает полностью рабочий сервер с MCP, API, scheduler и бэкапами.

| Задача | Статус | Примечание |
|--------|--------|------------|
| D1: MCP Streamable HTTP | ✅ | Транспорт, bearer auth, Docker Compose `mcp` сервис |
| D2: Production Docker | ✅ | Multi-stage build, health checks, graceful shutdown, `.env.production.example` |
| D3: TG Session в Docker | ✅ | CLI `auth`, volume `data/sessions`, обработка expired session |
| D4: Backup | ✅ | `docker/backup.sh`, `docker/restore.sh`, ротация 7 дней, cron-ready |
| D4: Мониторинг | ⏳ | Grafana/Prometheus/Loki — отложено до деплоя на сервер |
| D5: Reverse Proxy + TLS | ⏳ | Caddy/nginx, Let's Encrypt — отложено до деплоя на сервер |

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

**Выявленные улучшения (→ Cross-dev):**
1. ~~Diversity в поиске~~ — отклонено: pure relevance корректнее, доминирование одного канала означает его объективную релевантность
2. Пагинация тем — 164 темы genotek требуют 4 запроса; AI-агент должен знать про `has_more`
3. Глобальная статистика по типам тем — нет MCP tool для агрегированной аналитики
4. Coverage дисбаланс — от 68% (AgeManagment) до 97% (genotek), можно улучшить инкрементальной топикизацией

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

### Фаза D-remaining: Оставшиеся задачи Production

**Цель:** Завершить подготовку к деплою на удалённый сервер.

#### D4-mon: Мониторинг

- Prometheus metrics → Grafana dashboard (docker-compose сервис)
- Алерты: диск, CPU, failed pipelines, LLM errors
- Опционально: Loki для агрегации логов

#### D5: Reverse Proxy + TLS

- Caddy или nginx как reverse proxy
- Автоматический TLS (Let's Encrypt)
- Rate limiting на уровне proxy
- Документация по настройке DNS и domain

**Предпосылка:** Есть удалённый сервер для деплоя.

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
- V1.0: agentic read-heavy MVP
- V1.1: safe writes (trigger_pipeline, pause/resume)
- V1.2: full operational interface (add/remove channel, LLM config)

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
    │ P6a API Enrich           │
    │ P6b MCP Server           │
    │ S1–S7 Tech Debt          │
    │ D1 Streamable HTTP       │
    │ D2 Production Docker     │
    │ D3 TG Session in Docker  │
    │ D4 Backup (backup.sh)    │
    │ Perf: 5 каналов, 5070 doc│
    │ Cross-val: сценарии 10–13│
    │ Cross-dev: ✅             │
    │  2. Кросс-статистика MCP │
    │  3. Кросс-топикизация    │
    │  4. Улучшение coverage   │
    └────────────┬─────────────┘
                 │
                 ▼
    ┌──────────────────────────┐
    │ D-remaining:             │
    │  D4-mon: Grafana/Prom    │
    │  D5: TLS/Proxy           │
    └────────────┬─────────────┘
                 │
                 ▼
    ┌──────────────────────────┐
    │ Phase 3: TG Bot          │
    │  Gemini + docker-now     │
    │  aiogram + allowlist     │
    └────────────┬─────────────┘
                 │
                 ▼
    ┌──────────────────────────┐
    │ UI / Bot Evolution       │
    │  Web Catalog             │
    │  Web Chat                │
    │  Hybrid TG Bot           │
    └──────────────────────────┘
```

---

## 5. Техдолг — ✅ ЗАКРЫТ (1 апреля 2026)

**Результаты:**

| Метрика | До | После |
|---------|-----|-------|
| Failing tests | 2 | **0** |
| `except Exception` | 91 (35 файлов) | **62** (24 файла, остаток — boundary handlers) |
| Total tests | 729 | **763** (+34) |
| Test gaps | 5 | **2** (ingestion service, pipeline service) |

**Выполнено:**
- **TD-1:** Исправлены 2 pre-existing test failures (mock `generate_with_usage`)
- **TD-2:** 29 `except Exception` → typed exceptions (SQLAlchemyError, ValueError, RuntimeError, httpx.HTTPError и др.) в storage, services, processing, MCP server, health checks, agents
- **TD-3:** Добавлены тесты: TopicLinkRepo integration (7), topicization prompt builders (16), CLI smoke (11)
- **TD-4:** Silent `except pass` → `logger.warning` (mcp_server.py, orchestrator.py); BearerTokenVerifier — уже корректно
- Оставшиеся `except Exception` — осознанные boundary handlers (CLI, scheduler, agent orchestration)

---

## 6. Следующий шаг

Техдолг закрыт, production-база уже собрана. Следующий прикладной этап — **Phase 3: Telegram Bot on Gemini**:
- новый `tg_bot` сервис в `docker-compose.yml`
- `aiogram` + allowlist + long polling
- `GEMINI_API_KEY` и текущий retrieval/RAG слой

Задачи **D-remaining** остаются важными, но больше не блокируют старт пилота Telegram-бота.
