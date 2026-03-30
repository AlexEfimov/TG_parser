# Roadmap v3 — Production-First Strategy

**Дата:** 30 марта 2026
**Статус:** Черновик для обсуждения
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

### Production-подготовка

| Задача | Описание | Статус |
|--------|----------|--------|
| D1 | MCP Streamable HTTP + bearer auth + Docker Compose MCP-сервис | **Выполнено** |

### Текущие метрики

- **1 канал** (@labdiagnostica_logical): 1130 raw → 1128 processed, 80 тем, 77.4% coverage
- **Тесты:** 646+ (все проходят)
- **MCP:** 12 tools, 3 resources, stdio + Streamable HTTP
- **Docker:** Compose с postgres, tg_parser, mcp, ollama (optional)

---

## 2. Пересмотр приоритетов

### Ключевое наблюдение

MCP-сервер, подключённый к Claude Desktop, уже даёт полноценный интерфейс для работы с базой знаний. Вместо разработки Web UI / Telegram-бота, приоритет — **довести MCP-сервер до продакшн-качества**, чтобы он стабильно работал на удалённом сервере 24/7.

### Изменение порядка фаз (относительно v2)

```
Roadmap v2 (исходный):          Roadmap v3 (пересмотренный):
  P6a → P6b → P6c → P6d           P6a → P6b → D1..D5 (Production)
       → P7 → P8                        → Perf → Cross → P6c/P6d
```

**Причины:**
1. MCP через Claude Desktop — уже рабочий интерфейс, Web UI может подождать
2. Production-readiness нужен для развёртывания на сервере (24/7 доступ)
3. Self-hosted версия — фундамент для будущего SaaS
4. Добавление каналов — операционная задача (pipeline уже поддерживает)

### Два продукта из одной кодовой базы (перспектива)

| Вариант | Описание | Аудитория |
|---------|----------|-----------|
| **Self-hosted** | `docker-compose up`, все данные у пользователя | Разработчики, компании |
| **SaaS** (будущее) | Облачный сервис, zero-setup | Конечные пользователи |

Self-hosted — первый. SaaS строится поверх: добавляются multi-tenant, OAuth, биллинг.

---

## 3. Roadmap: ближайшие шаги

### Фаза D: Production-Ready Self-Hosted

**Цель:** `docker-compose up` запускает полностью рабочий сервер с MCP, API, scheduler, мониторингом и бэкапами.

#### ~~D1: MCP Streamable HTTP~~ — ✅ ВЫПОЛНЕНО

Streamable HTTP транспорт, bearer-токен auth, lifespan для DB, Docker Compose `mcp` сервис, CLI --host/--port, 13 тестов.

#### D2: Production Docker + конфигурация

**Цель:** Полный Docker-стек, готовый к запуску на удалённом сервере.

**Scope:**
- Оптимизировать Dockerfile (multi-stage build, .dockerignore, минимальный образ)
- Настроить `tg_parser` сервис как long-running (API + scheduler) вместо `command: ["--help"]`
- Health checks для всех сервисов (postgres, api, mcp)
- Production `.env` шаблон с документацией
- Logging: stdout/stderr → json format для Docker logging driver
- Graceful shutdown для всех сервисов

**Файлы:** `Dockerfile`, `docker-compose.yml`, `.env.production.example`, `docker/`

#### D3: Telegram Session в Docker

**Цель:** Telegram-авторизация работает в контейнеризованном окружении.

**Scope:**
- Persist session file через Docker volume
- Документация: первичная авторизация (интерактивный ввод кода)
- Скрипт / CLI-команда для авторизации внутри контейнера
- Обработка реавторизации (expired session)

**Файлы:** `docker-compose.yml` (volumes), CLI, документация

#### D4: Backup и мониторинг

**Цель:** Данные защищены, состояние сервера наблюдаемо.

**Scope:**
- PostgreSQL backup: скрипт `pg_dump` + cron / scheduled task
- Restore-инструкция и тестирование
- Prometheus metrics (уже есть) → Grafana dashboard (docker-compose сервис)
- Алерты: диск, CPU, failed pipelines, LLM errors
- Опционально: Loki для агрегации логов

**Файлы:** `docker/backup.sh`, `docker/grafana/`, `docker-compose.yml`

#### D5: Reverse Proxy + TLS

**Цель:** Безопасный HTTPS-доступ к MCP и API снаружи.

**Scope:**
- Caddy или nginx как reverse proxy
- Автоматический TLS (Let's Encrypt)
- Проксирование: `https://domain/mcp` → MCP (8080), `https://domain/api` → API (8000)
- Rate limiting на уровне proxy
- Документация по настройке DNS и domain

**Файлы:** `docker/caddy/Caddyfile` или `docker/nginx/`, `docker-compose.yml`

---

### Фаза Perf: Производительность при масштабировании

**Цель:** Стабильная работа с 5–10 каналами, оптимизированный pipeline.

**Scope:**
- Подключить 3–5 новых каналов
- Профилирование pipeline (ingestion, processing, topicization, embedding)
- Оптимизация: batch sizes, connection pool, concurrent LLM calls
- Мониторинг ресурсов под нагрузкой
- Автоматический scheduler для всех каналов

**Предпосылка:** Фаза D завершена, сервер работает стабильно.

---

### Фаза Cross: Кросс-канальная аналитика

**Цель:** Объединение знаний из нескольких каналов.

**Scope:**
- Кросс-канальный поиск (уже работает — search по всем каналам)
- Кросс-канальная топикизация: одна тема может объединять материалы разных каналов
- Сравнительная аналитика: какие темы пересекаются между каналами
- Новые MCP tools / API endpoints для кросс-канальных запросов

**Предпосылка:** 5+ каналов с обработанными данными.

---

### Фаза UI: Интерфейсы (отложена)

**Цель:** Доступ к базе знаний без LLM-клиента.

| Подфаза | Описание | Приоритет |
|---------|----------|-----------|
| P6c: Web Catalog | Next.js, навигация по темам/каналам | Средний |
| P6d: Web Chat | Встроенный чат с RAG, conversation history | Средний |
| TG Bot | Telegram-бот для доступа к базе знаний | Низкий |

**Предпосылка:** Фаза D завершена. Может начаться параллельно с Perf/Cross.

---

## 4. Визуальная схема

```
         ВЫПОЛНЕНО                    В РАБОТЕ / ПЛАНИРУЕТСЯ
    ┌─────────────────┐
    │ P6a API Enrich  │
    │ P6b MCP Server  │
    │ S1–S7 Tech Debt │
    │ D1 Streamable   │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ D2 Docker Prod  │ ◄── Ближайший шаг
    │ D3 TG Session   │
    │ D4 Backup+Monit │
    │ D5 TLS/Proxy    │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ Perf: 5-10 ch.  │
    │ Cross: кросс-   │
    │  канальные темы  │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ UI: Web Catalog │
    │     Web Chat    │
    │     TG Bot      │
    └─────────────────┘
```

---

## 5. Остаточный техдолг (низкий приоритет)

| Задача | Оценка | Когда |
|--------|--------|-------|
| Bare `except` → typed exceptions | 30 мин | По мере работы с файлами |
| Расширение тестового покрытия | По необходимости | При рефакторинге |
| `BearerTokenVerifier` → явное наследование от `TokenVerifier` | 5 мин | D2 или отдельно |

---

## 6. Следующий шаг

Подготовить стартовый промпт для **D2: Production Docker + конфигурация**.
