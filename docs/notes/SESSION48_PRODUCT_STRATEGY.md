# Session 48 — Стратегия развития продукта

**Дата:** 26 марта 2026
**Статус:** Черновик для обсуждения

---

## 1. Текущее состояние продукта

### Что реализовано (v4.0, Sessions 1–47)

**Full pipeline:**
```
Telegram каналы → Ingestion → RawMessages → LLM Processing → ProcessedDocuments
    → Topicization (full/incremental) → TopicCards + TopicBundles
    → Embeddings (pgvector) → Semantic Search + RAG Q&A
```

**Инфраструктура:**
- PostgreSQL 17 + pgvector 0.8.2
- 4 LLM-провайдера (OpenAI, Anthropic, Gemini, Ollama)
- Hexagonal архитектура, чистые порты/адаптеры
- Background scheduler (APScheduler) для автообновления
- REST API (FastAPI): health, processing jobs, export, search, ask
- CLI (Typer): 15+ команд для полного управления
- 571 тест, 0 failures

**Тестовые данные:**
- 1 канал (@labdiagnostica_logical)
- 1130 raw → 1128 processed
- 80 тем (68 cluster + 12 singleton), 77.4% coverage
- Embeddings + RAG Q&A работают

### Существующие API endpoints

| Endpoint | Метод | Назначение |
|----------|-------|------------|
| `/health` | GET | Health check |
| `/status` | GET | Компоненты + DB counts |
| `/status/detailed` | GET | Детальная диагностика |
| `/scheduler` | GET | Статус scheduler |
| `/api/v1/process` | POST | Запуск обработки |
| `/api/v1/status/{job_id}` | GET | Статус job |
| `/api/v1/jobs` | GET | Список jobs |
| `/api/v1/export` | POST | Запуск экспорта |
| `/api/v1/export/status/{job_id}` | GET | Статус экспорта |
| `/api/v1/export/download/{job_id}` | GET | Скачать файл |
| `/api/v1/search` | POST | Семантический поиск |
| `/api/v1/ask` | POST | RAG Q&A |
| `/api/v1/agents` | GET | Список агентов |
| `/api/v1/agents/{name}` | GET | Детали агента |
| `/api/v1/agents/{name}/stats` | GET | Статистика агента |
| `/api/v1/agents/{name}/history` | GET | История задач |
| `/api/v1/agents/stats/handoffs` | GET | Статистика handoff |

### Чего нет (пробелы)

- **Нет API для тем**: list topics, get topic details, get bundle items
- **Нет API для каналов**: list channels, channel stats, coverage metrics
- **Нет MCP Server**: нельзя использовать как tool для внешних LLM-агентов
- **Нет веб-интерфейса**: вся работа через CLI
- **Нет истории диалогов**: RAG Q&A stateless (нет контекста предыдущих вопросов)
- **Нет streaming**: ответы RAG Q&A приходят целиком, без потокового вывода
- **`_call_llm()` в retrieval_service обходит LLMClient абстракцию**: hardcoded httpx

---

## 2. Видение продукта (по итогам обсуждения)

### Целевая аудитория (эволюция)

1. **Сейчас:** Небольшая команда (2–5 человек) — совместная работа с базой знаний
2. **Далее:** Внешние клиенты/заказчики — продукт для конкретных проектов
3. **Перспектива:** SaaS / открытый сервис

### Основная идея

**TG_parser** — платформа знаний, построенная на контенте Telegram-каналов.
Основной способ взаимодействия — **диалог с ИИ-агентом**, для которого TG_parser является набором инструментов (tools).

### Модель взаимодействия

```
Пользователь
    ├── Веб-чат (встроенный агент) → RAG Q&A с историей диалога
    ├── Веб-каталог тем → навигация, поиск, детальные страницы
    ├── Внешний ИИ-агент (Claude/GPT/custom) → MCP tools / REST API
    └── CLI → управление pipeline, экспорт (для администраторов)
```

### Масштаб

- 10+ Telegram-каналов, разные направления
- Деплой: Docker на собственном сервере

---

## 3. Предлагаемый пересмотренный roadmap

### P6a: API Enrichment (Foundation)

**Цель:** Расширить REST API так, чтобы ВСЕ данные были доступны программно — это фундамент для Web UI, MCP и внешних интеграций.

**Scope:**

1. **Topics API:**
   - `GET /api/v1/topics?channel_id=...` — список тем канала (title, type, items_count, updated_at)
   - `GET /api/v1/topics/{topic_id}` — детали темы (full TopicCard + scope + anchors)
   - `GET /api/v1/topics/{topic_id}/bundle` — bundle items со ссылками на документы

2. **Channels API:**
   - `GET /api/v1/channels` — список подключённых каналов
   - `GET /api/v1/channels/{channel_id}/stats` — статистика (raw/processed/covered, coverage %, тем)

3. **Documents API:**
   - `GET /api/v1/documents/{source_ref}` — детали ProcessedDocument

4. **Рефакторинг retrieval_service:**
   - `_call_llm()` → использовать `LLMClient` абстракцию вместо hardcoded httpx
   - Подготовка к conversation history

**Артефакты:** Новые route-файлы `routes/topics.py`, `routes/channels.py`, `routes/documents.py`

---

### P6b: MCP Server

**Цель:** Сделать TG_parser инструментом для любого внешнего ИИ-агента через протокол MCP (Model Context Protocol).

**Scope:**

MCP tools (набор функций, которые агент может вызывать):

| Tool | Описание |
|------|----------|
| `search_knowledge_base` | Семантический поиск по базе знаний (query, channel?, limit) |
| `ask_question` | Q&A: задать вопрос, получить ответ с источниками |
| `list_topics` | Каталог тем канала (channel_id?) |
| `get_topic_details` | Полная карточка темы + bundle items |
| `list_channels` | Список подключённых каналов со статистикой |
| `get_document` | Содержимое конкретного документа |

MCP resources (данные, которые агент может читать):
- `tgparser://channels` — список каналов
- `tgparser://channels/{id}/topics` — темы канала
- `tgparser://topics/{id}` — карточка темы

**Реализация:** Python MCP SDK (`mcp` package), запуск как отдельный процесс или в составе API.

**Ценность:** После этого шага можно подключить TG_parser к Claude Desktop, Cursor, ChatGPT (через plugins), или любому агентскому фреймворку.

---

### P6c: Web Catalog

**Цель:** Веб-интерфейс для навигации по базе знаний: каталог тем, детальные страницы, поиск.

**Scope:**

1. **Главная страница:**
   - Список подключённых каналов с ключевыми метриками
   - Глобальный поиск

2. **Страница канала:**
   - Статистика: raw/processed/covered, coverage %, количество тем
   - Каталог тем (карточки с title, type, items_count)
   - Фильтры: по типу (singleton/cluster), сортировка (по дате, по количеству items)

3. **Страница темы:**
   - Полная карточка: title, summary, scope_in/scope_out, type
   - Якорные посты с ссылками в Telegram
   - Все bundle items (посты + комментарии) с текстом и ссылками
   - Timeline публикаций по теме

4. **Поиск:**
   - Семантический поиск с результатами
   - Каждый результат — ссылка на документ и его тему

**Технический стек:** Требует обсуждения (см. раздел "Открытые вопросы").

---

### P6d: Web Chat

**Цель:** Встроенный чат-бот для диалога с базой знаний через веб-интерфейс.

**Scope:**

1. **Chat UI:**
   - Поле ввода вопроса
   - Streaming ответов (SSE / WebSocket)
   - Источники отображаются как карточки с ссылками

2. **Conversation history:**
   - Сохранение контекста в рамках сессии
   - Передача предыдущих Q&A как контекста для LLM

3. **Backend:**
   - `POST /api/v1/chat` — новый endpoint с поддержкой `conversation_id`
   - Хранение истории (в памяти или PostgreSQL)

---

### P7: Multi-Channel (Scale)

**Цель:** Полноценная работа с 10+ каналами.

**Scope:**
- Тестирование pipeline на множестве каналов
- Кросс-канальный поиск (поиск по всем каналам одновременно)
- Кросс-канальные темы (одна тема может объединять материалы из разных каналов)
- Сравнительная аналитика каналов

---

### P8: Production Readiness

**Цель:** Готовность к деплою для внешних пользователей.

**Scope:**
- `docker-compose.yml` для полного стека (API + Web + PostgreSQL + scheduler)
- Prometheus metrics + Grafana dashboards
- Auth/авторизация (API keys, JWT)
- Rate limiting для публичных endpoints
- Backup/restore для данных

---

## 4. Открытые вопросы для обсуждения

### Q1: Порядок фаз

Предложенный порядок: P6a (API) → P6b (MCP) → P6c (Web Catalog) → P6d (Web Chat).

Альтернативы:
- **MCP-first**: P6a → P6b → сразу попробовать с Claude/Cursor → потом Web
- **Web-first**: P6a → P6c → P6d → P6b (если хочется быстрее увидеть визуальный результат)
- **Chat-first**: P6a → P6d (чат) → P6c (каталог) → P6b (MCP)

### Q2: Frontend-стек

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| **React / Next.js** | Полноценный SPA, максимум гибкости, экосистема | Отдельный проект, нужен Node.js, сложнее деплой |
| **Streamlit** | Python-only, быстрый прототип, chat widget из коробки | Ограничения кастомизации, не production-grade для SaaS |
| **FastAPI + Jinja2 + htmx** | Единый Python-стек, серверный рендеринг | Меньше интерактивности, больше кода для chat UI |

### Q3: MCP как приоритет

MCP Server позволит сразу получить "ИИ-агент как интерфейс" без написания frontend.
Стоит ли начать с MCP и попробовать взаимодействие через Claude Desktop / Cursor прежде чем строить свой Web UI?

### Q4: Scope мульти-канала

Когда начинать подключать новые каналы? Варианты:
- **Параллельно с P6**: подключить 2–3 канала для тестирования API/Web на реальных данных
- **После P6**: сначала довести один канал до идеала
- **Поэтапно**: по 2–3 канала на каждой фазе

### Q5: Conversation history

Для полноценного чат-бота нужна история диалога. Варианты хранения:
- **In-memory** (простой dict) — пропадает при перезапуске
- **PostgreSQL** — персистентно, масштабируемо
- **Redis** — быстро, TTL для автоочистки

---

## 5. Рекомендации

1. **Начать с P6a (API Enrichment)** — без полного API невозможны ни Web UI, ни MCP, ни внешние интеграции. Это фундамент для всего остального.

2. **P6b (MCP Server) как следующий шаг** — это самый быстрый путь к "ИИ-агент как интерфейс", потому что:
   - Не нужен frontend
   - Сразу можно попробовать в Claude Desktop или Cursor
   - Валидирует API-контракты прежде чем строить Web UI

3. **Streamlit для первого прототипа Web** — позволит быстро увидеть результат без React/Node.js. Если ограничений будет слишком много — мигрировать на Next.js.

4. **Подключить 2–3 новых канала уже на этапе P6a** — чтобы API и Web тестировались на реальных данных с множеством каналов.

---

**Следующий шаг:** Обсудить этот документ, принять решения по Q1–Q5, и подготовить стартовый промпт для первой фазы.
