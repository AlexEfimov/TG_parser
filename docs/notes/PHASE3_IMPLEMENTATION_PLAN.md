# Phase 3 Implementation Plan — Gemini TG Bot

**Дата:** 3 апреля 2026 (обновлено: 3 апреля 2026)  
**Статус:** Принято для реализации

---

## Принятые решения

- **Агент / LLM backend:** Gemini
- **Доступ к модели:** `GEMINI_API_KEY`
- **Развёртывание:** сразу новый `tg_bot` сервис в `docker-compose.yml`
- **Bot framework:** `aiogram`
- **Режим доступа:** allowlist-only для пилота
- **Режим доставки Telegram updates:** long polling

---

## Видение продукта

Telegram-бот — это **человеческий интерфейс ко всей системе tg_parser** для людей, не работающих с IDE и MCP-клиентами.

Бот должен ощущаться не как "RAG-чат", а как **ассистент по базе знаний**, который умеет:
- отвечать на вопросы;
- искать материалы;
- показывать темы, каналы, документы;
- делать кросс-канальные сравнения;
- а в будущем — выполнять операционные действия.

Формат взаимодействия:
- **free-form чат** без специальных команд;
- **структурированные ответы**: summary, ключевые пункты, источники;
- ответы с опорой на реальные данные из базы знаний.

---

## Архитектурный подход

### Ключевое изменение по сравнению с ранней версией плана

Ранний план предполагал тонкую обертку вокруг `retrieval_service.answer()`. Новый план предполагает **агентный слой оркестрации** над набором внутренних capabilities.

### Архитектура бота

```
Telegram User
    |
    v
 aiogram handlers (parse, allowlist, limits)
    |
    v
 Agent / Orchestrator layer
    |
    +---> retrieval_service.search()
    +---> retrieval_service.answer()
    +---> topic navigation (list_topics, get_topic_details)
    +---> channel overview (list_channels)
    +---> document lookup (get_document)
    +---> related topics (get_related_topics)
    +---> cross-channel stats (get_cross_channel_stats)
    +---> [future] pipeline operations
    +---> [future] channel management
    |
    v
 Response formatter (structured, split, sources)
    |
    v
Telegram reply
```

### Принципы

- Бот реализуется внутри Python-кода проекта, а не как внешний CLI-агент.
- Бот использует **Gemini как LLM для рассуждений и tool-calling**, а не просто для генерации ответа на промпт.
- Набор capabilities бота концептуально соответствует MCP tools, но вызывается через **внутренние Python сервисы**, не через MCP protocol.
- MCP остаётся внешним интерфейсом для IDE-агентов.
- Bot credentials отделены от Telethon ingestion credentials.

---

## Версионная лестница

### V1.0 — Agentic read-heavy MVP

**Цель:** полезный бот для тестовых пользователей, работающий как read-only ассистент.

**Capabilities:**
- Q&A по базе знаний (ask_question)
- Семантический поиск (search_knowledge_base)
- Навигация по темам (list_topics, get_topic_details)
- Обзор каналов (list_channels)
- Просмотр документов (get_document)
- Связанные темы (get_related_topics)
- Кросс-канальная аналитика (get_cross_channel_stats)

**UX:**
- free-form чат
- structured-first ответы
- источники и опорные материалы в ответах
- /start, /help
- split длинных ответов
- таймауты и error handling
- allowlist

### V1.1 — Safe writes

**Capabilities (добавляются):**
- trigger_pipeline
- get_pipeline_status
- pause_channel / resume_channel

**UX:**
- явное подтверждение перед write-операцией
- preview действия

### V1.2 — Full operational interface

**Capabilities (добавляются):**
- add_channel / remove_channel
- get_llm_config / set_llm_config / reset_llm_config

**UX:**
- двухшаговое подтверждение для деструктивных операций
- role/permission model
- audit logging

---

## Scope реализации V1.0

### 1. Bot-specific settings

- `TELEGRAM_BOT_TOKEN`
- `BOT_ALLOWED_USERS` — allowlist Telegram user IDs
- `BOT_REQUEST_TIMEOUT` — timeout для LLM/DB запросов
- `BOT_MAX_MESSAGE_LENGTH` — лимит длины ответа
- `BOT_RATE_LIMIT` — ограничение запросов/минуту

### 2. Agent / Orchestrator layer

Центральный компонент, который:
- принимает free-form сообщение от пользователя;
- использует Gemini для определения намерения и выбора capabilities;
- вызывает нужные внутренние сервисы;
- формирует структурированный ответ.

Capabilities V1.0 (read-only):
- `search` — semantic search
- `answer` — RAG Q&A
- `list_topics` — список тем
- `get_topic_details` — детали темы
- `list_channels` — список каналов
- `get_document` — содержимое документа
- `get_related_topics` — связанные темы
- `get_cross_channel_stats` — кросс-канальная статистика

### 3. Response formatter

- Структурированные ответы: summary, key points, sources
- Ссылки на источники
- Split для Telegram (4096 chars limit)
- Fallback для ошибок и таймаутов

### 4. Aiogram handlers

- `/start` — приветствие и краткое описание
- `/help` — описание возможностей
- Текстовые сообщения — маршрутизация через agent layer
- Allowlist middleware
- Rate limiting middleware
- Logging middleware (telegram_user_id, request_id)

### 5. CLI entrypoint

- `tg-parser bot` — запуск бота
- compose-friendly command override

### 6. Docker service

- `tg_bot` в `docker-compose.yml`
- общий image с приложением
- `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`
- `restart: unless-stopped`
- `tg_parser_network`
- `depends_on: postgres`

### 7. Документация

- `.env.example` — bot section
- `env.production.example` — bot section
- `PRODUCTION_DEPLOYMENT.md` — Phase 3 subsection

---

## Acceptance Criteria V1.0

- `docker compose` поднимает отдельный `tg_bot` сервис.
- Allowlisted пользователь может:
  - `/start`, `/help`
  - задать вопрос и получить RAG-ответ
  - попросить "покажи каналы" и получить список
  - попросить "покажи темы по genotek" и получить список тем
  - попросить "найди материалы про витамин D" и получить результаты поиска
  - попросить "что известно про APOE" и получить structured ответ с источниками
- Ответы структурированы: summary, key points, sources.
- Бот корректно обрабатывает таймауты, ошибки и длинные ответы.
- Документация описывает запуск и переменные окружения.

---

## Out Of Scope For V1.0

- Webhooks
- Inline keyboards
- Voice / audio
- Полноценная conversation history между сессиями
- Write-операции (trigger_pipeline, channel management)
- Role/permission model
- Billing / cost tracking

---

## Риски и митигации

1. **Latency агентного слоя** — Gemini tool-calling может добавить 2-5 секунд. Митигация: "typing" indicator, timeout fallback, оптимизация промптов.
2. **Качество intent detection** — Gemini может неправильно выбирать tool. Митигация: clear tool descriptions, fallback к Q&A, итеративная доработка промптов по результатам пилота.
3. **Стоимость** — каждое сообщение вызывает LLM. Митигация: allowlist + rate limits + мониторинг cost в логах.

---

## Следующая сессия

Следующая реализационная сессия должна:
1. Прочитать этот план и `docs/prompts/PHASE3_TG_BOT_GEMINI_PROMPT.md`.
2. Реализовать V1.0: agent layer, aiogram handlers, settings, CLI, docker service, docs.
3. Не расширять scope за пределы V1.0 read-only capabilities.
