# TG_parser Development Roadmap

> ⚠️ **ARCHIVED** — этот roadmap актуален для v3.1.0 (декабрь 2025). Актуальный roadmap: [ROADMAP_V3](/docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md) (v4.2, апрель 2026).

**Version**: 3.1.0 RELEASED 🎉  
**Created**: 26 декабря 2025  
**Updated**: 29 декабря 2025  
**Author**: Development Planning Agent  
**Revision**: v3.1.0 — Phase 4 Production Hardening (COMPLETE)  

---

## 📋 Executive Summary

### Текущее состояние (v3.0.0) ✅ RELEASED
**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных, теперь с HTTP API, агентным подходом, **Multi-Agent Architecture**, **Agent State Persistence**, **Agent Observability** и **Advanced Features**.

- ✅ **v1.2 Complete**: Multi-LLM, Docker, 126 тестов
- ✅ **HTTP API** (Session 14 Phase 2A): FastAPI, 8 endpoints, 24 теста
- ✅ **Agents SDK PoC** (Session 14 Phase 2B): TGProcessingAgent с 3 tools, 24 теста
- ✅ **LLM-Enhanced Tools** (Session 14 Phase 2C): analyze_text_deep, 14 тестов
- ✅ **Hybrid Agent Mode** (Session 15 Phase 2E): pipeline tool, 32 теста
- ✅ **API Production** (Session 16 Phase 2F): Auth, Rate Limiting, Webhooks, Persistent Jobs, 38 тестов
- ✅ **Multi-Agent Architecture** (Session 17 Phase 3A): OrchestratorAgent, ProcessingAgent, TopicizationAgent, ExportAgent, Registry, Handoffs, 42 теста
- ✅ **Agent State Persistence** (Session 18 Phase 3B): AgentState, TaskHistory, AgentStats, HandoffHistory, 25 тестов
- ✅ **Agent Observability** (Session 19 Phase 3C): CLI agents, API endpoints, Archiver, 15 тестов
- ✅ **Advanced Features** (Session 20 Phase 3D): Prometheus Metrics, Background Scheduler, Health Checks v2, 26 тестов ⭐ NEW
- ✅ **Тесты**: 366 тестов, 100% проходят
- ✅ **Docker**: Dockerfile + docker-compose.yml (370MB image)
- ✅ **Production-ready CLI**: полный E2E pipeline работает

### Видение v3.0
Превратить TG_parser из CLI-инструмента в **полноценную платформу** с:
- ✅ HTTP API для интеграций — **DONE (Phase 2A)**
- ✅ OpenAI Agents SDK — **PoC DONE (Phase 2B)**
- ✅ LLM-Enhanced Agent Tools — **DONE (Phase 2C)**
- ✅ Hybrid Agent Mode — **DONE (Phase 2E)**
- ✅ API Production (Auth, Rate Limiting, Webhooks) — **DONE (Phase 2F)**
- ✅ Docker-контейнеризацией (уже есть)
- ✅ Multi-Agent Architecture — **DONE (Phase 3A)**
- ✅ Agent State Persistence — **DONE (Phase 3B)**
- ✅ Agent Observability — **DONE (Phase 3C)**
- ✅ Prometheus Metrics & Background Scheduler — **DONE (Phase 3D)** ⭐ NEW
- ⏳ Dashboard для мониторинга (Grafana-ready)
- ⏳ Web UI

### Ключевые приоритеты
1. ~~**v1.1** (2-3 недели): Configurable Prompts (YAML), устранение технического долга~~ ✅ DONE
2. ~~**v1.2** (4 недели): Multi-LLM support, Docker, CI/CD~~ ✅ DONE (27 декабря 2025)
3. ~~**v2.0 Phase 2A** (Session 14): HTTP API Skeleton~~ ✅ DONE (27 декабря 2025)
4. ~~**v2.0 Phase 2B** (Session 14): Agents SDK PoC~~ ✅ DONE (27 декабря 2025)
5. ~~**v2.0 Phase 2C** (Session 14): LLM-Enhanced Agent Tools~~ ✅ DONE (27 декабря 2025)
6. ~~**v2.0 Phase 2E** (Session 15): Hybrid Agent Mode~~ ✅ DONE (28 декабря 2025)
7. ~~**v2.0 Phase 2F** (Session 16): API Production (Auth, Rate Limiting, Webhooks)~~ ✅ DONE (28 декабря 2025)
8. ~~**v3.0 Phase 3A** (Session 17): Multi-Agent Architecture~~ ✅ DONE (28 декабря 2025)
9. ~~**v3.0 Phase 3B** (Session 18): Agent State Persistence~~ ✅ DONE (28 декабря 2025)
10. ~~**v3.0 Phase 3C** (Session 19): Agent Observability~~ ✅ DONE (28 декабря 2025)
11. ~~**v3.0 Phase 3D** (Session 20): Advanced Features (Prometheus, Background Tasks)~~ ✅ DONE (28 декабря 2025)
12. ~~**v3.0 Phase 3 Finalization** (Session 21): E2E Integration Tests, Documentation, Release v3.0.0~~ ✅ DONE (28 декабря 2025)

---

## 🚀 Phase 4: Production Hardening (v3.1+)

### Ключевые приоритеты Phase 4

13. **v3.1 Phase 4A** (Session 22): Foundation & Tech Debt — ✅ **DONE**
14. **v3.1 Phase 4B** (Session 23): Structured JSON Logging + GPT-5 — ✅ **DONE**
15. **v3.1 Phase 4C** (Session 24): PostgreSQL Support — ✅ **DONE** 🎉 **v3.1.0 RELEASED**
16. **v3.1 Phase 4D** (Session 25): Comments Support (TR-5) ← **NEXT**
17. **v3.1 Phase 4E** (Session 26): Monitoring & Observability (Grafana, Tracing)
18. **v3.2 Phase 4F** (Session 27): Scaling (Redis, K8s)

---

## 🚢 Deployment Strategy

### Матрица готовности к deploy

| Версия | После сессии | Тип deploy | Ограничения |
|--------|--------------|------------|-------------|
| v3.0.0 | — | ⚠️ Dev/Demo | SQLite, 1 user, потеря данных при update |
| v3.1.0-alpha.1 | Session 22 ✅ | ⚠️ Staging | SQLite, Alembic миграции работают |
| v3.1.0-alpha.2 | Session 23 ✅ | ✅ **Staging Ready** | + Structured JSON logging + GPT-5 + 405 тестов |
| **v3.1.0** | **Session 24 ✅** | ✅ **Production Ready** 🎉 | PostgreSQL, multi-user, 435 тестов, полностью готов |
| v3.1.x | Session 25-26 | ✅ Production+ | + Comments, Grafana, Tracing |
| v3.2.0 | Session 27 | ✅ Production Scale | + Redis, K8s, horizontal scaling |

### Рекомендуемая стратегия: "Staging First"

```
┌─────────────────────────────────────────────────────────────────┐
│  Session 22 (Alembic)                                           │
│       ↓                                                         │
│  🔶 Deploy на STAGING сервер (SQLite, для тестирования)         │
│       ↓                                                         │
│  Session 23 (Logging) → обновить staging                        │
│       ↓                                                         │
│  Session 24 (PostgreSQL)                                        │
│       ↓                                                         │
│  🟢 PRODUCTION DEPLOY (PostgreSQL, multi-user)                  │
│       ↓                                                         │
│  Sessions 25-27: Добавлять features на production               │
└─────────────────────────────────────────────────────────────────┘
```

### Минимальные требования для Production

| Требование | Session | Статус | Критичность |
|------------|---------|--------|-------------|
| Docker | — | ✅ Есть | 🔴 Required |
| Health checks | — | ✅ Есть | 🔴 Required |
| Prometheus metrics | — | ✅ Есть | 🟡 Recommended |
| Alembic migrations | 22 | ✅ Готово | 🔴 Required |
| Structured logging | 23 | ✅ Готово | 🟡 Recommended |
| PostgreSQL | 24 | ✅ Готово | 🔴 Required |
| Connection Pooling | 24 | ✅ Готово | 🔴 Required |
| Performance Indexes | 24 | ✅ Готово | 🟡 Recommended |
| Grafana dashboard | 26 | ⏳ Planned | 🟢 Optional |
| Redis queue | 27 | ⏳ Planned | 🟢 Optional |

### Что доступно для deploy сейчас (v3.0.0)

**Уже готово:**
- ✅ `Dockerfile` + `docker-compose.yml`
- ✅ HTTP API с auth, rate limiting
- ✅ Prometheus `/metrics` endpoint
- ✅ Health checks: `/health`, `/health/live`, `/health/ready`
- ✅ Environment config через `.env`

**Ограничения:**
- ❌ SQLite — не подходит для concurrent access
- ❌ Нет миграций — обновления ломают данные
- ❌ Текстовые логи — сложно отлаживать

### Возможности deploy по сценариям

#### Сценарий 1: Личное использование (сейчас)
```bash
# Deploy на VPS/домашний сервер
docker-compose up -d

# Ограничения:
# - Только 1 пользователь
# - При обновлении — backup данных вручную
```
**Подходит для:** демо, личные проекты, тестирование

#### Сценарий 2: Staging сервер (после Session 22)
```bash
# После Session 22 (Alembic)
docker-compose up -d

# Обновление без потери данных:
docker-compose exec api tg-parser db upgrade
```
**Подходит для:** dev/test окружения, команда разработчиков

#### Сценарий 3: Production (после Session 24) ⭐ Рекомендуется
```bash
# docker-compose.prod.yml с PostgreSQL
docker-compose -f docker-compose.prod.yml up -d

# Возможности:
# - Multi-user
# - Безопасные обновления
# - Production logging
# - Мониторинг
```
**Подходит для:** production с реальными пользователями

### Отладка на сервере

После Session 23 (Structured Logging):
```bash
# Найти все ошибки за последний час
docker logs tg-parser-api | jq 'select(.level == "ERROR")'

# Отследить конкретный запрос
docker logs tg-parser-api | jq 'select(.request_id == "req-abc-123")'

# Метрики производительности
curl http://localhost:8000/metrics
```

### Timeline до Production

| Session | Время | Cumulative | Milestone |
|---------|-------|------------|-----------|
| 22 | ~6ч | 6ч | Staging ready |
| 23 | ~6ч | 12ч | Logging ready |
| **24** | ~10ч | **22ч** | **Production ready** ⭐ |
| 25 | ~10ч | 32ч | Comments |
| 26 | ~10ч | 42ч | Full observability |
| 27 | ~14ч | 56ч | Scaling ready |

**Итого до Production:** ~22 часа разработки (Sessions 22-24)

---

## 🔍 Analysis

### ✅ Что работает отлично

#### 1. Ingestion (Telethon)
- Стабильный сбор из Telegram API
- Snapshot режим работает надёжно
- 846 сообщений собрано без ошибок
- Поддержка публичных каналов

#### 2. Processing (OpenAI LLM)
- 99.76% успешность (844/846)
- Качественное извлечение тем и сущностей
- Автоматическая генерация summary
- Многоязычность (RU/EN)
- Retry logic с exponential backoff

#### 3. Topicization
- 10 осмысленных тем автоматически обнаружено
- Семантическая кластеризация работает
- Корректный выбор якорных сообщений
- Критерии качества singleton/cluster соблюдаются

#### 4. Export
- NDJSON формат для RAG-систем
- JSON Schema валидация
- Детерминированные ID
- Telegram URLs в метаданных
- Фильтры по channel/topic/dates

#### 5. Архитектура
- Hexagonal Architecture (ports & adapters)
- Чёткое разделение модулей (7 модулей)
- Pydantic v2 модели с валидацией
- Async SQLAlchemy 2.x
- Типизированный код (type hints)

#### 6. Документация
- Качество 4.9/5 по аудиту
- 31 документ в 5 категориях
- JSON Schema контракты
- 4 ADR (Architecture Decision Records)
- Детальные примеры и руководства

### ⚠️ Что требует улучшения

#### 1. Error Handling
| Проблема | Влияние | Приоритет |
|----------|---------|-----------|
| LLM возвращает неполный JSON (0.24%) | 2 failed messages | Medium |
| Нет авто-retry для failed messages | Ручная переобработка | Medium |
| Ограниченная валидация ответов LLM | Пропуск сообщений | High |

#### 2. Производительность
| Проблема | Влияние | Приоритет |
|----------|---------|-----------|
| Последовательная обработка сообщений | 846 сообщений = 30 мин | High |
| Нет batch processing для LLM | Много API вызовов | Medium |
| Нет кэширования промптов | Избыточные вычисления | Low |

#### 3. Observability
| Проблема | Влияние | Приоритет |
|----------|---------|-----------|
| Базовое логирование | Сложная отладка | Medium |
| Нет метрик (Prometheus/StatsD) | Нет мониторинга | Low |
| Нет dashboard | Нет визуализации | Low |

#### 4. Developer Experience
| Проблема | Влияние | Приоритет |
|----------|---------|-----------|
| Ручная установка зависимостей | Сложный onboarding | Medium |
| Нет Docker | Несовместимость сред | Medium |
| Нет CI/CD | Ручное тестирование | Medium |

### ❌ Что отсутствует

#### Критично (v1.x)
| Функция | Описание | Приоритет |
|---------|----------|-----------|
| Auto-retry failed messages | Переобработка с улучшенными промптами | High |
| ProcessedDocumentRepo.list_all() | Экспорт всех каналов | High |
| Usernames из IngestionStateRepo | Лучшие Telegram URLs | Medium |

#### Запланировано (v1.1-v1.2)
| Функция | Описание | Версия |
|---------|----------|--------|
| ⭐ Configurable prompts (YAML) | Промпты без изменения кода | **v1.1** |
| ⭐ Multi-LLM support | Anthropic, Gemini, Ollama | **v1.2** |

#### Желательно (v2.0)
| Функция | Описание | Приоритет |
|---------|----------|-----------|
| ⭐ GPT-5 (Agents SDK) | Responses API, reasoning | High |
| HTTP API | REST/GraphQL для интеграций | Medium |
| Web UI | Dashboard для управления | Low |
| Scheduled updates | Автоматическое обновление | Medium |
| Comments support | Обработка комментариев | Low |

### 🔧 Technical Debt

#### Код

| Файл | Строка | Описание | Приоритет |
|------|--------|----------|-----------|
| `cli/export_cmd.py` | 82 | TODO: add list_all() method | High |
| `cli/export_cmd.py` | 99 | TODO: get usernames from IngestionStateRepo | Medium |

#### Документация

| Файл | Проблема | Действие |
|------|----------|----------|
| `docs/notes/current-state.md` | Устарел (упоминает исправленные баги) | Обновить или архивировать |
| `SESSION_COMPLETE.md` | Архивный документ | Перенести в docs/notes/archive/ |

#### Тесты

| Область | Статус | Действие |
|---------|--------|----------|
| Unit тесты | ✅ Хорошее покрытие | Поддерживать |
| Integration тесты | ✅ Есть | Расширить |
| E2E тесты | ⚠️ 1 тест | Добавить больше сценариев |
| Load тесты | ❌ Нет | Создать для v1.2 |

---

## 📅 Version Planning

## v1.1.0 — "Stability & Configurability"

**Приоритет**: High  
**Срок**: 2-3 недели  
**Фокус**: Configurable prompts, устранение технического долга, улучшение надёжности

### Goals
- ⭐ **Configurable Prompts (YAML)** — возможность менять промпты без изменения кода
- Устранить все TODOs в коде
- Улучшить error handling для LLM
- Обновить устаревшую документацию
- Добавить авто-retry для failed messages

### Tasks

#### 🔴 High Priority (неделя 1)

##### 1. ⭐ [Feature] Configurable Prompts (YAML)
**Папка**: `prompts/`  
**Файлы**: `tg_parser/processing/prompt_loader.py`  
**Время**: 6-8 часов  
**Описание**: Вынести все LLM промпты в YAML файлы с возможностью кастомизации

**Структура:**
```
prompts/
├── processing.yaml       # Processing промпты
├── topicization.yaml     # Topicization промпты
├── supporting_items.yaml # Supporting items промпты
└── README.md             # Документация формата
```

**Пример `prompts/processing.yaml`:**
```yaml
# TG_parser Processing Prompts
# Version: 1.0.0

metadata:
  version: "1.0.0"
  description: "Prompts for processing Telegram messages"
  
system:
  prompt: |
    You are a text processing assistant for Telegram messages.
    
    Your task is to:
    1. Clean and normalize the text
    2. Generate a concise summary
    3. Extract relevant topics
    4. Identify named entities
    
    Always respond in the same language as the input.
    
user:
  template: |
    Process the following Telegram message:
    
    ---
    {text}
    ---
    
    Channel: {channel_id}
    Message ID: {message_id}
  variables:
    - text
    - channel_id
    - message_id

model:
  temperature: 0
  max_tokens: 4096
  
# Для GPT-5 (будущее)
gpt5:
  reasoning_effort: low
  verbosity: low
```

**Реализация:**
```python
# tg_parser/processing/prompt_loader.py
import yaml
from pathlib import Path

class PromptLoader:
    def __init__(self, prompts_dir: Path = Path("prompts")):
        self.prompts_dir = prompts_dir
        
    def load(self, name: str) -> dict:
        """Load prompt configuration from YAML file."""
        path = self.prompts_dir / f"{name}.yaml"
        if not path.exists():
            # Fallback to built-in prompts
            return self._get_default(name)
        with open(path) as f:
            return yaml.safe_load(f)
```

**Критерии готовности**:
- [ ] Структура `prompts/` создана
- [ ] PromptLoader реализован с fallback на defaults
- [ ] Все существующие промпты вынесены в YAML
- [ ] CLI флаг `--prompts-dir` для кастомной директории
- [ ] Валидация YAML схемы
- [ ] Документация формата промптов
- [ ] Тесты для PromptLoader

##### 2. [Bug Fix] Добавить `list_all()` в ProcessedDocumentRepo
**Файл**: `tg_parser/storage/sqlite/processed_document_repo.py`  
**Время**: 2 часа  
**Описание**: Реализовать метод для экспорта всех каналов без фильтра

```python
async def list_all(self, limit: int | None = None) -> list[ProcessedDocument]:
    """Return all processed documents across all channels."""
    ...
```

**Критерии готовности**:
- [ ] Метод реализован
- [ ] Тест написан
- [ ] CLI export работает без `--channel`

##### 3. [Bug Fix] Получение usernames из IngestionStateRepo
**Файл**: `tg_parser/cli/export_cmd.py`  
**Время**: 3 часа  
**Описание**: Использовать channel_username из источника для лучших URLs

```python
# В export_cmd.py
source = await ingestion_repo.get_source(source_id)
channel_username = source.channel_username if source else None
```

**Критерии готовности**:
- [ ] Реализовано
- [ ] Telegram URLs используют username если доступен
- [ ] Тест покрывает сценарий

##### 4. [Feature] Auto-retry для failed messages
**Файлы**: `tg_parser/processing/pipeline.py`, `tg_parser/cli/process_cmd.py`  
**Время**: 4 часа  
**Описание**: Добавить команду `--retry-failed` для переобработки

```bash
python -m tg_parser.cli process --channel X --retry-failed
```

**Критерии готовности**:
- [ ] Флаг `--retry-failed` работает
- [ ] Используется улучшенный промпт для retry
- [ ] Failed messages обновляются после успеха

##### 5. [Improvement] Улучшенная валидация ответов LLM
**Файл**: `tg_parser/processing/pipeline.py`  
**Время**: 3 часа  
**Описание**: Более робастный parsing JSON ответов

**Критерии готовности**:
- [ ] Валидация всех required полей
- [ ] Fallback для частичных ответов
- [ ] Логирование проблемных ответов

#### 🟡 Medium Priority (недели 2-3)

##### 6. [Docs] Обновить current-state.md
**Файл**: `docs/notes/current-state.md`  
**Время**: 2 часа  
**Описание**: Синхронизировать с актуальным состоянием кода

##### 7. [Docs] Архивировать устаревшие документы
**Действие**: Создать `docs/notes/archive/` и перенести:
- `SESSION_COMPLETE.md` → `docs/notes/archive/`
- `PROCESSING_COMPLETE.md` → `docs/notes/archive/`  
**Время**: 1 час

##### 8. [Test] Добавить E2E тесты
**Файл**: `tests/test_e2e_scenarios.py`  
**Время**: 4 часа  
**Описание**: Тесты для типовых сценариев использования

##### 9. [Improvement] Улучшенное логирование
**Файлы**: все модули  
**Время**: 3 часа  
**Описание**: Структурированное логирование с уровнями

### Success Criteria v1.1
- [x] ⭐ Промпты вынесены в YAML и документированы
- [x] Все TODOs устранены (0 в коде)
- [x] Error rate < 0.1% (сейчас 0.24%)
- [x] Документация синхронизирована
- [x] 90+ тестов проходят
- [x] Auto-retry работает

**Status**: ✅ COMPLETED (26 декабря 2025)

### Risks v1.1
| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| LLM API изменения | Low | Medium | Мониторинг OpenAI changelog |
| Breaking changes в Telethon | Low | High | Pin версию в requirements.txt |

---

## v1.2.0 — "Multi-LLM & Performance" ✅

**Статус**: ✅ COMPLETED (27 декабря 2025)  
**Приоритет**: Medium  
**Срок**: 4 недели → **Завершено за 1 сессию**  
**Фокус**: Multi-LLM support, производительность, Docker, CI/CD

### Goals ✅
- ✅ **Multi-LLM Support** — Anthropic Claude, Google Gemini, Ollama (через Chat Completions API)
- ✅ Параллельная обработка (3-5x ускорение через --concurrency)
- ✅ Docker-контейнеризация (Dockerfile + docker-compose.yml)
- ✅ GitHub Actions CI/CD (tests + docker build)
- ⚠️ Улучшенный CLI — отложено на v2.0 (базовая функциональность есть)

### Tasks

#### 🔴 High Priority (недели 1-2)

##### 1. ⭐ [Feature] Multi-LLM Support (Chat Completions API)
**Файлы**: `tg_parser/processing/llm/`, `tg_parser/config/settings.py`  
**Время**: 12 часов  
**Описание**: Поддержка нескольких LLM провайдеров через Chat Completions API

**Архитектура:**
```
tg_parser/processing/llm/
├── __init__.py
├── base.py              # Абстрактный LLMClient (уже есть)
├── openai_client.py     # OpenAI (уже есть)
├── anthropic_client.py  # ⭐ NEW: Anthropic Claude
├── gemini_client.py     # ⭐ NEW: Google Gemini
├── ollama_client.py     # ⭐ NEW: Ollama (local)
└── factory.py           # ⭐ NEW: LLM factory по провайдеру
```

**Конфигурация (`.env`):**
```env
# Выбор провайдера
LLM_PROVIDER=openai  # openai | anthropic | gemini | ollama

# OpenAI (default)
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-20250514

# Google Gemini
GEMINI_API_KEY=...
LLM_MODEL=gemini-2.0-flash-exp

# Ollama (local)
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=llama3.2
```

**Пример factory:**
```python
# tg_parser/processing/llm/factory.py
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient
from .gemini_client import GeminiClient
from .ollama_client import OllamaClient

def create_llm_client(provider: str, **kwargs) -> LLMClient:
    clients = {
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "gemini": GeminiClient,
        "ollama": OllamaClient,
    }
    if provider not in clients:
        raise ValueError(f"Unknown LLM provider: {provider}")
    return clients[provider](**kwargs)
```

**Критерии готовности**:
- [x] AnthropicClient реализован и протестирован
- [x] GeminiClient реализован и протестирован
- [x] OllamaClient реализован и протестирован
- [x] Factory создаёт клиент по `LLM_PROVIDER`
- [x] CLI флаги `--provider` и `--model` добавлены
- [x] Документация по настройке провайдеров (LLM_SETUP_GUIDE.md)
- [x] PromptLoader интегрирован в pipeline

**Status**: ✅ COMPLETED (26-27 декабря 2025)

##### 2. [Performance] Параллельная обработка сообщений
**Файлы**: `tg_parser/processing/pipeline.py`  
**Время**: 8 часов → **Завершено**  
**Описание**: asyncio.gather для параллельных LLM вызовов

**Реализация:**
```python
async def _process_batch_parallel(self, messages, concurrency: int = 5):
    semaphore = asyncio.Semaphore(concurrency)
    async def process_with_semaphore(msg):
        async with semaphore:
            return await self._process_single(msg)
    return await asyncio.gather(*[process_with_semaphore(m) for m in messages])
```

**Критерии готовности**:
- [x] Concurrency configurable (`--concurrency N`)
- [x] Rate limiting через Semaphore
- [x] Методы `_process_batch_parallel` и `_process_batch_sequential` реализованы
- [x] Backward compatible (default concurrency=1)

**Status**: ✅ COMPLETED (27 декабря 2025)

##### 3. [DevOps] Dockerfile
**Файл**: `Dockerfile`  
**Время**: 4 часа → **Завершено**  
**Описание**: Multi-stage build для production

**Критерии готовности**:
- [x] Multi-stage `docker build` работает
- [x] `docker run` выполняет CLI команды
- [x] Volumes для SQLite и .env настроены
- [x] Образ оптимизирован (< 1GB)

**Status**: ✅ COMPLETED (27 декабря 2025)

##### 4. [DevOps] docker-compose.yml
**Файл**: `docker-compose.yml`  
**Время**: 2 часа → **Завершено**  
**Описание**: Compose для локальной разработки + опциональный Ollama service

**Критерии готовности**:
- [x] docker-compose.yml создан
- [x] Volumes монтируются
- [x] ENV переменные передаются
- [x] Ollama service добавлен (опционально)

**Status**: ✅ COMPLETED (27 декабря 2025)

##### 5. [DevOps] GitHub Actions CI
**Файл**: `.github/workflows/ci.yml`  
**Время**: 4 часа → **Завершено**  
**Описание**: Автоматические тесты на PR + Docker build

**Критерии готовности**:
- [x] Test job (pytest, ruff)
- [x] Docker job (build, test image)
- [x] Markdown link check job
- [x] Triggers: push to main, PRs

**Status**: ✅ COMPLETED (27 декабря 2025)

#### 🟡 Medium Priority (недели 3-4)

##### 6. [UX] Progress bars и цвета в CLI
**Файлы**: `tg_parser/cli/*.py`  
**Время**: 4 часа  
**Описание**: Rich для красивого вывода

```python
from rich.progress import Progress
with Progress() as progress:
    task = progress.add_task("Processing...", total=len(messages))
    ...
```

##### 7. [Feature] Dry-run mode
**Файлы**: все CLI команды  
**Время**: 3 часа  
**Описание**: `--dry-run` для предпросмотра без изменений

##### 8. [Performance] LLM response caching
**Файлы**: `tg_parser/processing/pipeline.py`  
**Время**: 4 часа  
**Описание**: Кэширование для идентичных входных данных

##### 9. [Test] Load тесты
**Файл**: `tests/test_load.py`  
**Время**: 4 часа  
**Описание**: Тесты производительности

##### 10. [Docs] CONTRIBUTING.md
**Файл**: `CONTRIBUTING.md`  
**Время**: 2 часа  
**Описание**: Руководство для контрибьюторов

### Success Criteria v1.2
- [x] ⭐ Минимум 3 LLM провайдера работают (OpenAI, Anthropic, Ollama)
- [x] Обработка 846 сообщений < 10 минут (сейчас 30)
- [x] Docker image работает
- [x] CI/CD на GitHub Actions
- [x] Все PR проходят автотесты
- [x] Progress bars в CLI (отложено)

**Status**: ✅ COMPLETED (26 декабря 2025)

### Risks v1.2
| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Rate limiting от OpenAI | Medium | High | Adaptive concurrency |
| Docker build fails | Low | Medium | Multi-stage build |
| CI flaky тесты | Medium | Low | Retries, test isolation |

---

## v2.0.0 — "Platform & GPT-5"

**Приоритет**: Long-term  
**Срок**: 8+ недель  
**Фокус**: GPT-5 (Agents SDK), HTTP API, Web UI

### Goals
- ⭐ **GPT-5 Support** — OpenAI Agents SDK с Responses API
- HTTP API для интеграций
- Web Dashboard для мониторинга
- Scheduled processing
- Kubernetes deployment

### Tasks

#### Phase 1: API (недели 1-3)

##### 1. [Feature] FastAPI HTTP Server
**Файлы**: `tg_parser/api/`  
**Время**: 16 часов  
**Описание**: REST API для всех операций

```
POST /api/v1/sources          - Add source
GET  /api/v1/sources          - List sources
POST /api/v1/sources/{id}/ingest - Trigger ingestion
POST /api/v1/process          - Process messages
GET  /api/v1/topics           - Get topics
GET  /api/v1/export           - Export data
GET  /api/v1/health           - Health check
```

##### 2. [Feature] OpenAPI Schema
**Файл**: `docs/openapi.yaml`  
**Время**: 4 часа  
**Описание**: Swagger документация

##### 3. [Feature] API Authentication
**Файлы**: `tg_parser/api/auth/`  
**Время**: 6 часов  
**Описание**: API keys или JWT

#### Phase 2: Scheduling (недели 4-5)

##### 4. [Feature] APScheduler integration
**Файлы**: `tg_parser/scheduler/`  
**Время**: 8 часов  
**Описание**: Cron-like scheduling для обновлений

```python
# Пример конфигурации
sources:
  my_channel:
    schedule: "0 */4 * * *"  # каждые 4 часа
```

##### 5. [Feature] Background workers
**Файлы**: `tg_parser/workers/`  
**Время**: 8 часов  
**Описание**: Async workers для длительных операций

#### Phase 3: UI (недели 6-8)

##### 6. [Feature] React Dashboard
**Папка**: `web/`  
**Время**: 24 часа  
**Описание**: Web UI для управления

- Список источников
- Статус обработки
- Просмотр тем
- Экспорт данных
- Логи и метрики

##### 7. [Feature] Real-time updates
**Технология**: WebSocket  
**Время**: 8 часов  
**Описание**: Live обновления статуса

#### Phase 4: GPT-5 & Extensions (ongoing)

##### 8. ⭐ [Feature] GPT-5 Support (OpenAI Agents SDK)
**Файлы**: `tg_parser/processing/llm/agents_client.py`  
**Время**: 16 часов  
**Описание**: Полная интеграция с GPT-5 через OpenAI Agents SDK

**Новая архитектура:**
```python
# Установка
pip install openai-agents[litellm]

# Использование нового API
from agents import Agent, Runner, ModelSettings
from openai.types.shared import Reasoning

agent = Agent(
    name="TG Processor",
    instructions=PROCESSING_SYSTEM_PROMPT,
    model="gpt-5-nano",  # или gpt-5, gpt-5-mini
    model_settings=ModelSettings(
        reasoning=Reasoning(effort="low"),  # minimal/low/medium/high
        verbosity="low"
    ),
    output_type=ProcessedOutput,  # Pydantic для structured output
)

result = await Runner.run(agent, message_text)
processed = result.final_output_as(ProcessedOutput)
```

**Ключевые отличия от Chat Completions:**
| Аспект | Chat Completions (v1.x) | Responses API (v2.0) |
|--------|-------------------------|----------------------|
| Паттерн | `client.chat.completions.create()` | `Runner.run(agent, ...)` |
| Модели | gpt-4o-mini | gpt-5, gpt-5-mini, gpt-5-nano |
| Reasoning | ❌ Нет | ✅ `reasoning.effort` |
| Structured output | Manual JSON parsing | Нативный Pydantic |

**Критерии готовности**:
- [ ] AgentsClient реализован как альтернатива OpenAIClient
- [ ] Поддержка `reasoning.effort` (minimal/low/medium/high)
- [ ] Поддержка `verbosity` (low/medium/high)
- [ ] Нативные structured outputs через Pydantic
- [ ] Обратная совместимость с Chat Completions
- [ ] Конфигурация через `LLM_API=responses` или `LLM_API=chat_completions`
- [ ] Документация по миграции на GPT-5

##### 9. [Feature] Comments processing (TR-5)
**Файлы**: `tg_parser/ingestion/`, `tg_parser/processing/`  
**Время**: 16 часов  
**Описание**: Полная поддержка комментариев

##### 10. [DevOps] Kubernetes manifests
**Папка**: `k8s/`  
**Время**: 8 часов  
**Описание**: Helm chart для K8s deployment

### Success Criteria v2.0
- [ ] ⭐ GPT-5 (gpt-5-nano, gpt-5-mini, gpt-5) работает через Agents SDK
- [ ] HTTP API работает и задокументирован
- [ ] Web Dashboard доступен
- [ ] Scheduled processing функционирует
- [ ] Kubernetes deployment готов

### Risks v2.0
| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Сложность Web UI | Medium | Medium | Использовать готовые компоненты |
| API security | Medium | High | Аудит безопасности |
| K8s complexity | Medium | Medium | Helm templates |
| Multi-LLM совместимость | High | Medium | Адаптеры и тесты |

---

## 📊 Task Breakdown Summary

### По версиям

| Версия | Задач | High | Medium | Low | Время |
|--------|-------|------|--------|-----|-------|
| v1.1.0 | 9 | 5 | 4 | 0 | 2-3 недели |
| v1.2.0 | 10 | 5 | 5 | 0 | 4 недели |
| v2.0.0 | 10 | 5 | 4 | 1 | 8+ недель |
| **Всего** | **29** | **15** | **13** | **1** | **14-15 недель** |

### По категориям

| Категория | Задач | v1.1 | v1.2 | v2.0 |
|-----------|-------|------|------|------|
| Bug Fixes | 2 | 2 | 0 | 0 |
| **LLM Features** | 3 | 1 (YAML) | 1 (Multi-LLM) | 1 (GPT-5) |
| Features | 11 | 1 | 3 | 7 |
| Performance | 3 | 0 | 2 | 1 |
| DevOps | 5 | 0 | 4 | 1 |
| Docs | 3 | 2 | 1 | 0 |
| Tests | 2 | 1 | 1 | 0 |

---

## 🎯 Risk Assessment

### Общие риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| OpenAI API изменения | Medium | High | Абстракция LLM, pin versions |
| Telethon deprecation | Low | Critical | Мониторинг, план миграции |
| Python 3.12 issues | Low | Medium | Тестирование в CI |
| Scope creep | High | Medium | Строгое следование roadmap |
| Resource constraints | Medium | Medium | Приоритизация, MVP подход |

### Зависимости

```
v1.1.0 ────────────────────> v1.2.0 ────────────────────> v2.0.0
  │                            │                            │
  │ обеспечивает               │ обеспечивает               │ обеспечивает
  ▼                            ▼                            ▼
YAML промпты               Multi-LLM                   GPT-5 + API
(prerequisite)             Docker/CI                   Web UI
```

### Миграционный путь LLM

```
v1.0 (OpenAI only)
  │
  ▼
v1.1 (Configurable YAML prompts) ←── Промпты можно менять без кода
  │
  ▼
v1.2 (Multi-LLM via Chat Completions) ←── Anthropic, Gemini, Ollama
  │
  ▼
v2.0 (GPT-5 via Agents SDK) ←── Responses API, reasoning, structured outputs
```

---

## 📈 Success Metrics

### v1.1.0 Metrics
| Метрика | Текущее | Цель |
|---------|---------|------|
| **Prompts in YAML** | 0 | 3 (processing, topicization, supporting) |
| Error rate | 0.24% | < 0.1% |
| TODOs в коде | 2 | 0 |
| Test count | 85 | 90+ |
| Docs sync | Partial | Full |

### v1.2.0 Metrics
| Метрика | Текущее | Цель |
|---------|---------|------|
| **LLM providers** | 1 (OpenAI) | 4 (+ Anthropic, Gemini, Ollama) |
| Processing time (846 msgs) | 30 min | < 10 min |
| Docker support | ❌ | ✅ |
| CI/CD | ❌ | ✅ |
| Test coverage | ~80% | > 85% |

### v2.0.0 Metrics
| Метрика | Текущее | Цель |
|---------|---------|------|
| **GPT-5 models** | 0 | 3 (gpt-5, gpt-5-mini, gpt-5-nano) |
| API endpoints | 0 | 10+ |
| UI pages | 0 | 5+ |
| K8s ready | ❌ | ✅ |

---

## 🗓️ Timeline

```
2025
│
├─ Декабрь 26 ─────────── v1.0.0 Released ✅
│
├─ Январь (недели 1-2) ── v1.1.0 Development
│  ├─ Week 1: Bug fixes, error handling
│  └─ Week 2: Docs, tests, polish
│
├─ Январь 10 ─────────── v1.1.0 Release
│
├─ Январь - Февраль ──── v1.2.0 Development
│  ├─ Weeks 1-2: Performance, Docker
│  └─ Weeks 3-4: CI/CD, CLI improvements
│
├─ Февраль 7 ─────────── v1.2.0 Release
│
├─ Февраль - Апрель ──── v2.0.0 Development
│  ├─ Phase 1 (3 weeks): API
│  ├─ Phase 2 (2 weeks): Scheduling
│  ├─ Phase 3 (3 weeks): UI
│  └─ Phase 4 (ongoing): Extensions
│
└─ Апрель ────────────── v2.0.0 Release
```

---

## v3.1.0 — "Production Hardening" 🎯 NEXT

**Статус**: 🚧 PLANNED  
**Приоритет**: High  
**Срок**: 6 сессий (Sessions 22-27)  
**Фокус**: Production readiness, PostgreSQL, Structured Logging, Comments

### Goals
- ⭐ **Alembic Migrations** — версионирование схемы БД
- ⭐ **Structured JSON Logging** — production-ready logs
- ⭐ **PostgreSQL Support** — масштабируемая БД
- ⭐ **Comments Support (TR-5)** — полная обработка комментариев
- ⭐ **Grafana Dashboard** — визуализация метрик
- ⭐ **OpenTelemetry Tracing** — distributed tracing

### Session 22: Foundation & Tech Debt 🎯 NEXT

**Приоритет**: 🔴 Critical  
**Время**: ~6 часов  
**Блокирует**: PostgreSQL, любые изменения схемы

| # | Задача | Приоритет | Время |
|---|--------|-----------|-------|
| 1 | **Alembic Migrations Setup** | 🔴 Critical | 3-4ч |
| 2 | **Архивация устаревших docs** | 🔴 High | 30мин |
| 3 | **Обновить current-state.md** | 🔴 High | 1ч |
| 4 | **Вынести retry параметры в config** | 🟡 Medium | 1ч |

**Критерии готовности**:
- [ ] Alembic настроен для 3 SQLite баз
- [ ] Initial миграции созданы
- [ ] CLI `init` использует Alembic
- [ ] Устаревшие docs в archive/
- [ ] current-state.md актуален

### Session 23: Structured JSON Logging

**Приоритет**: 🔴 High  
**Время**: ~6 часов

**Start prompt**: `docs/notes/START_PROMPT_SESSION23_LOGGING_GPT5.md`

| # | Задача | Приоритет | Время |
|---|--------|-----------|-------|
| 1 | **structlog integration** | 🔴 High | 3-4ч |
| 2 | **Correlation IDs (request_id)** | 🔴 High | 2ч |
| 3 | **OpenAI GPT-5 support (Responses API)** | 🔴 High | 1-2ч |
| 4 | **LOG_FORMAT config** | 🟡 Medium | 30мин |

**Критерии готовности**:
- [ ] JSON логи в production mode
- [ ] Text логи в development mode
- [ ] request_id во всех логах API
- [ ] OpenAI `gpt-5.*` работает через Responses API (`/responses`)
- [ ] Поддержка `reasoning.effort` и `verbosity` для `gpt-5.*` (config-driven)
- [ ] Документация логирования

### Session 24: PostgreSQL Support

**Приоритет**: 🔴 Critical  
**Время**: ~10 часов  
**Зависит от**: Session 22 (Alembic)

| # | Задача | Приоритет | Время |
|---|--------|-----------|-------|
| 1 | **PostgreSQL adapter** | 🔴 Critical | 4-5ч |
| 2 | **Connection pooling** | 🔴 High | 2ч |
| 3 | **docker-compose с PG** | 🟡 Medium | 1ч |
| 4 | **Data migration script** | 🟡 Medium | 2ч |

**Критерии готовности**:
- [ ] `DATABASE_TYPE=postgresql` работает
- [ ] Все тесты проходят на PostgreSQL
- [ ] docker-compose с PostgreSQL service
- [ ] Скрипт миграции SQLite→PostgreSQL

### Session 25: Comments Support (TR-5)

**Приоритет**: 🟡 Medium  
**Время**: ~10 часов

| # | Задача | Приоритет | Время |
|---|--------|-----------|-------|
| 1 | **Ingestion комментариев** | 🟡 Medium | 3-4ч |
| 2 | **Processing комментариев** | 🟡 Medium | 3ч |
| 3 | **Comment→Post связи** | 🟡 Medium | 2ч |
| 4 | **Export с комментариями** | 🟡 Medium | 2ч |

**Критерии готовности**:
- [ ] `--include-comments` работает
- [ ] Комментарии обрабатываются через LLM
- [ ] Связи comment→post в топиках
- [ ] Export включает комментарии

### Session 26: Monitoring & Observability

**Приоритет**: 🟡 Medium  
**Время**: ~10 часов

| # | Задача | Приоритет | Время |
|---|--------|-----------|-------|
| 1 | **Grafana Dashboard JSON** | 🟡 Medium | 3ч |
| 2 | **OpenTelemetry Tracing** | 🟡 Medium | 5ч |
| 3 | **Alerting rules** | 🟢 Low | 2ч |

**Критерии готовности**:
- [ ] grafana-dashboard.json для импорта
- [ ] Traces в Jaeger/Tempo
- [ ] Span correlation с logs
- [ ] Alert rules документированы

### Session 27: Scaling

**Приоритет**: 🟢 Low-Medium  
**Время**: ~14 часов

| # | Задача | Приоритет | Время |
|---|--------|-----------|-------|
| 1 | **Redis Job Queue** | 🟡 Medium | 6-8ч |
| 2 | **Worker processes** | 🟡 Medium | 4ч |
| 3 | **Kubernetes Helm Chart** | 🟢 Low | 6ч |

### Phase 4 Critical Path

```
Session 22: Alembic ──────► Session 24: PostgreSQL
                                   │
Session 23: Logging ───────────────┤
                                   │
                                   ▼
                    Sessions 25-27: Features & Scaling
```

### Success Criteria v3.1
- [ ] PostgreSQL production-ready
- [ ] Structured JSON logging
- [ ] Comments fully supported
- [ ] Grafana dashboard available
- [ ] Distributed tracing works
- [ ] 400+ тестов

### Technical Debt Closure

| # | Проблема | Session |
|---|----------|---------|
| 1 | Нет Alembic миграций | 22 |
| 2 | current-state.md устарел | 22 |
| 3 | Архивные docs в корне | 22 |
| 4 | Hardcoded retry params | 22 |
| 5 | Текстовые логи | 23 |
| 6 | Нет correlation IDs | 23 |
| 7 | SQLite only | 24 |

---

## 🚀 Quick Wins

Задачи с высокой ценностью и низкой сложностью для быстрого старта:

| Задача | Время | Ценность | Версия |
|--------|-------|----------|--------|
| ⭐ Configurable prompts (YAML) | 6-8h | **Very High** | v1.1 |
| Auto-retry failed messages | 4h | High | v1.1 |
| Улучшенная валидация LLM | 3h | High | v1.1 |
| ⭐ OllamaClient (local LLM) | 3h | High | v1.2 |
| Progress bars в CLI | 4h | Medium | v1.2 |
| Dockerfile | 4h | High | v1.2 |

---

## 📚 Связанные документы

- [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) — Полное оглавление
- [README.md](README.md) — Основная документация
- [docs/technical-requirements.md](docs/technical-requirements.md) — Технические требования
- [docs/architecture.md](docs/architecture.md) — Архитектура
- [REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md) — Результаты тестирования

---

## 🤔 Вопросы для обсуждения

1. ✅ ~~**Configurable prompts** — YAML или JSON?~~ → **Решено: YAML**
2. ✅ ~~**Multi-LLM priority** — Какие провайдеры?~~ → **Решено: Anthropic, Gemini, Ollama в v1.2**
3. ✅ ~~**GPT-5 timing** — Когда интегрировать?~~ → **Решено: v2.0 (требует Agents SDK)**
4. ✅ ~~**Приоритет HTTP API vs Web UI**~~ → **Решено: API first, Web UI позже**
5. ✅ ~~**Comments support**~~ → **Решено: Session 25 (TR-5)**
6. ✅ ~~**PostgreSQL migration**~~ → **Решено: Session 24**
7. **Monetization** — Есть ли планы коммерциализации?
8. **Kubernetes** — Нужен ли Helm chart в v3.1?

---

## ✅ Рекомендации

### Начать с Session 22 (Phase 4A)
1. ⭐ **Alembic Migrations** — фундамент для PostgreSQL и изменений схемы
2. Закрыть технический долг (docs, config)
3. Structured JSON Logging (Session 23)
4. PostgreSQL Support (Session 24)
5. Comments TR-5 (Session 25)

### Следовать Git Workflow
- `main` — стабильные релизы
- `develop` — текущая разработка
- `feature/*` — новые фичи
- `bugfix/*` — исправления

### Использовать Semantic Versioning
- **PATCH** (v1.0.x): bug fixes
- **MINOR** (v1.x.0): new features, backward compatible
- **MAJOR** (vx.0.0): breaking changes

---

**Готов к реализации Phase 4!** 🚀

Начните с Session 22 (Foundation & Tech Debt) — это займёт ~6 часов и создаст фундамент для PostgreSQL и дальнейшего развития.

**Критический путь**: Alembic → PostgreSQL → Scaling

---

**Version**: 1.1  
**Status**: Active  
**Key Changes**: Добавлены Configurable Prompts (YAML), Multi-LLM (v1.2), GPT-5 (v2.0)  
**Next Review**: После релиза v1.1.0

