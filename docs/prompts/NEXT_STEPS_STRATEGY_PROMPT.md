# Стартовый промпт: Стратегия дальнейшего развития TG_parser

## Контекст

TG_parser — self-hosted система для построения базы знаний из Telegram-каналов.
Архитектура: Telegram ingestion → LLM processing → topicization → embeddings → MCP server для AI-агентов.

Текущее состояние: **продукт функционально готов**, техдолг закрыт, 5 каналов подключены, 5405 документов, 401 тема, 264 кросс-канальные связи. 855 тестов проходят. F9 Phase 1 в проде, Bot V1.2 задеплоен.

## Ключевые документы для ознакомления

### 1. Текущий Roadmap и статус (НАЧНИ ЗДЕСЬ)
**`@docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`**
- Полный перечень выполненных фаз (P6a-P6b, D1-D4, Perf, Cross-val, Cross-dev, Tech debt)
- Текущие метрики (каналы, документы, темы, тесты, coverage)
- Незавершённые задачи: D-remaining (мониторинг, TLS), Phase UI (Web Catalog, Web Chat, TG Bot)
- Визуальная схема эволюции проекта

### 2. Продуктовая стратегия
**`@docs/notes/SESSION48_PRODUCT_STRATEGY.md`**
- Два продукта: Self-hosted и SaaS (перспектива)
- Целевая аудитория, ценностное предложение
- Приоритеты: MCP-сервер как основной интерфейс

### 3. Архитектура и развёртывание
- **`@docker-compose.yml`** — сервисы: postgres, tg_parser (API+scheduler), mcp (Streamable HTTP), bot, prometheus, grafana
- **`@.env.example`** — все конфигурационные параметры
- **`@Dockerfile`** — multi-stage production build

### 4. Текущие интерфейсы
- **MCP Server**: 17 tools, 3 resources, stdio + Streamable HTTP транспорт, bearer auth
- **Telegram Bot**: Gemini-powered agent, 17 tools, free-form чат, allowlist, V1.2
- **REST API**: health, process, export, topics, channels, documents, RAG (FastAPI на порту 8000, auth + rate limiting)
- **CLI**: ingest, process, topicize, export, link-topics, scheduler, db, auth, agents, mcp

## Вопросы для обсуждения

### A. Приоритет направления
Два основных пути, которые можно развивать параллельно:

1. **D-remaining: Production infra** — Grafana/Prometheus мониторинг, Reverse Proxy + TLS (Caddy), деплой на удалённый сервер
2. **Phase UI: Пользовательские интерфейсы** — Web Catalog (Next.js), Web Chat (RAG), Telegram Bot

### B. Архитектурные решения для UI
- Web UI может работать напрямую с REST API (уже готов), без дополнительного AI-агента
- Для Q&A/чата используется встроенный RAG-pipeline (`ask_question`), нужен только LLM API-ключ
- Для навигации по темам/каналам LLM не нужен вообще

### C. Deployment model
- Текущий: `docker compose up` поднимает всё
- Вопрос: нужен ли Kubernetes, или Docker Compose достаточно?
- Вопрос: один сервер или распределённая архитектура?

### D. Новая функциональность
- Подключение новых каналов (масштабирование)
- Автоматические дайджесты / нотификации
- Multi-tenant (для SaaS-варианта)
- OAuth / пользовательская авторизация

## Инструкция

Изучи указанные документы и обсуди с пользователем приоритеты и следующие шаги. Не начинай реализацию — это сессия планирования.
