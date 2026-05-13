# Session 48 — Roadmap v2 (по итогам обсуждения Q1–Q5)

**Дата:** 26 марта 2026
**Статус:** Утверждён
**Предыдущий документ:** `SESSION48_PRODUCT_STRATEGY.md` (черновик стратегии)

> **⚠️ Superseded (2026-05-02).** Этот roadmap был актуален на момент Session 48
> (~март 2026, v3.3 → v4.0 transition). Текущая версия roadmap — двухслойная:
>
> - **Operational track:**
>   [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) —
>   что построено / что в backlog инфраструктурно.
> - **Strategic track:**
>   [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) —
>   audience-driven Wave 1 (Bot UX → F4-B Core → Surface Parity →
>   Shareable Digest).
>
> Этот файл сохраняется для исторического контекста; **не использовать как
> source of truth** для приоритезации или старта новых sprint'ов. Cross-links
> к завершённому Living-KB-контракту и текущему статусу — см.
> [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md).

---

## Принятые решения

| Вопрос | Решение | Обоснование |
|--------|---------|-------------|
| **Q1: Порядок фаз** | MCP-first: P6a → P6b → валидация → P6c → P6d | Самый быстрый путь к "AI-агент как интерфейс", валидирует API-контракты до Web UI |
| **Q2: Frontend** | React / Next.js (production-grade) | Без промежуточного прототипа, не нужно переписывать позже |
| **Q3: Валидация MCP** | Глубокая (5–7 дней, acceptance criteria) | MCP — ядро продуктовой идеи; реальное использование выявит проблемы API и данных |
| **Q4: Мульти-канал** | Каналы на стыке P6a/P6b | API разрабатывается на 1 канале (проще отладка), 2–3 канала к валидации MCP |
| **Q5: History** | PostgreSQL | Уже в стеке, персистентно, масштабируемо, можно анализировать |

---

## Roadmap

### Phase P6a: API Enrichment (Foundation)

**Цель:** Все данные доступны программно — фундамент для MCP, Web UI, интеграций.

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

**Артефакты:** `routes/topics.py`, `routes/channels.py`, `routes/documents.py`

**Данные:** 1 канал (@labdiagnostica_logical)

**Критерий готовности:** Все endpoints работают, покрыты тестами, документированы (OpenAPI).

---

### Phase P6b: MCP Server

**Цель:** TG_parser как набор инструментов для любого AI-агента (Claude Desktop, Cursor, ChatGPT).

**Scope — MCP Tools:**

| Tool | Описание |
|------|----------|
| `search_knowledge_base` | Семантический поиск (query, channel?, limit) |
| `ask_question` | Q&A: вопрос → ответ с источниками |
| `list_topics` | Каталог тем (channel_id?) |
| `get_topic_details` | Карточка темы + bundle items |
| `list_channels` | Список каналов со статистикой |
| `get_document` | Содержимое документа |

**Scope — MCP Resources:**
- `tgparser://channels` — список каналов
- `tgparser://channels/{id}/topics` — темы канала
- `tgparser://topics/{id}` — карточка темы

**Реализация:** Python MCP SDK (`mcp` package)

**Данные:** Подключить 2–3 новых канала в начале этой фазы (пока идёт разработка — данные проходят pipeline).

**Критерий готовности:** MCP Server запускается, подключается к Claude Desktop и Cursor.

---

### Phase P6b-validation: Глубокая валидация MCP (5–7 дней)

**Цель:** Убедиться, что MCP tools дают ценность, исправить проблемы до Web UI.

**Acceptance criteria:**
- 10–15 типичных пользовательских сценариев протестированы в Claude Desktop и Cursor
- Каждый MCP tool вызван минимум 5 раз в реальных диалогах
- Проблемы с форматами ответов зафиксированы и исправлены
- Tool descriptions оптимизированы для AI-агентов
- Кросс-канальный поиск работает на 3–4 каналах

**Результат:** Стабильные API-контракты, проверенные реальным использованием.

---

### Phase P6c: Web Catalog (Next.js)

**Цель:** Веб-интерфейс для навигации по базе знаний.

**Стек:** Next.js (React), подключение к REST API

**Scope:**
- Главная страница: список каналов с метриками, глобальный поиск
- Страница канала: статистика, каталог тем (карточки), фильтры/сортировка
- Страница темы: полная карточка, якорные посты, bundle items, timeline
- Поиск: семантический поиск, результаты со ссылками на документ и тему

**Данные:** 3–4 канала (уже обработанные на предыдущих фазах).

---

### Phase P6d: Web Chat

**Цель:** Встроенный чат-бот в веб-интерфейсе для диалога с базой знаний.

**Scope:**
- Chat UI: поле ввода, streaming ответов (SSE), источники как карточки
- `POST /api/v1/chat` с `conversation_id`
- Conversation history: хранение в PostgreSQL (новая таблица `conversations` / `chat_messages`)
- Передача предыдущих Q&A как контекста для LLM

---

### Phase P7: Multi-Channel (Scale)

**Цель:** Полноценная работа с 10+ каналами.

**Scope:**
- Масштабирование до 10+ каналов
- Кросс-канальные темы (одна тема из материалов разных каналов)
- Сравнительная аналитика каналов

---

### Phase P8: Production Readiness

**Цель:** Готовность к деплою для внешних пользователей.

**Scope:**
- `docker-compose.yml` (API + Next.js + PostgreSQL + scheduler)
- Auth/авторизация (API keys, JWT)
- Prometheus metrics + Grafana dashboards
- Rate limiting
- Backup/restore

---

## Визуальная схема

```
P6a (API Enrichment, 1 канал)
 │
 ▼
P6b (MCP Server, +2–3 канала)
 │
 ▼
P6b-val (Валидация MCP, 5–7 дней, 3–4 канала)
 │
 ▼
P6c (Web Catalog, Next.js)
 │
 ▼
P6d (Web Chat, PostgreSQL history)
 │
 ▼
P7 (Multi-Channel, 10+ каналов)
 │
 ▼
P8 (Production: Docker, Auth, Metrics)
```

---

## Следующий шаг

Начать Phase P6a: API Enrichment. Стартовый промпт подготовлен в `START_PROMPT_SESSION49_API_ENRICHMENT.md`.
