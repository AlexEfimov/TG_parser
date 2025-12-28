# 📚 Оглавление документации TG_parser

**Полный справочник по всей документации проекта.**

Последнее обновление: 29 декабря 2025 (v3.0.0 → v3.1.0 planning)

---

## 🎯 Быстрая навигация

### Я хочу...

| Задача | Документ | Время |
|--------|----------|-------|
| **Начать использовать TG_parser** | [README.md](README.md) → Quick Start | 10 мин |
| **Понять форматы выходных файлов** | [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md) | 15 мин |
| **Работать с несколькими каналами** | [MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md) | 10 мин |
| **Использовать HTTP API** | [README.md](README.md) → `api` команда | 5 мин |
| **Настроить API Security** | [docs/notes/SESSION16_PHASE2F_COMPLETE.md](docs/notes/SESSION16_PHASE2F_COMPLETE.md) | 10 мин |
| **Изучить полное руководство** | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 30 мин |
| **Понять архитектуру системы** | [docs/architecture.md](docs/architecture.md) | 20 мин |
| **Посмотреть реальные результаты** | [REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md) | 10 мин |
| **Продолжить разработку** | [docs/notes/README.md](docs/notes/README.md) | 5 мин |

---

## 📖 Документация по аудиториям

### 👤 Для конечных пользователей

#### Основные документы
- **[README.md](README.md)** ⭐  
  *Точка входа в проект*  
  Возможности, Quick Start, CLI команды, конфигурация  
  **Начните здесь!**

- **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**  
  *Полное руководство пользователя*  
  Детальное описание всех функций и сценариев использования

#### Специализированные руководства
- **[OUTPUT_FORMATS.md](OUTPUT_FORMATS.md)** ⭐  
  *Форматы выходных файлов*  
  NDJSON, JSON, схемы данных, примеры интеграции (ElasticSearch, MongoDB, Pinecone)  
  **~650 строк, 15+ примеров кода**

- **[MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md)** ⭐  
  *Работа с несколькими каналами*  
  Как хранятся данные, рекомендуемые подходы, практические примеры

- **[docs/DATA_FLOW.md](docs/DATA_FLOW.md)**  
  *Поток данных через систему*  
  Диаграммы, схемы данных, примеры трансформаций

- **[docs/LLM_PROMPTS.md](docs/LLM_PROMPTS.md)**  
  *Документация промптов LLM*  
  Промпты для processing и topicization, параметры, примеры

#### Практические примеры
- **[MIGRATION_GUIDE_v2_to_v3.md](MIGRATION_GUIDE_v2_to_v3.md)** ⭐  
  *Руководство по миграции v2 → v3.0*  
  Breaking changes, новые features, примеры конфигурации

- **[REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md)** ⭐  
  *Результаты тестирования на реальном канале*  
  846 сообщений обработано, 99.76% успешность, примеры данных

- **[COMPLETION_SUMMARY.md](COMPLETION_SUMMARY.md)**  
  *Краткий итог тестирования*  
  Финальные метрики, достижения, готовность к production

#### Troubleshooting
- **[README.md](README.md)** → раздел "🤝 Troubleshooting"  
  Частые проблемы и решения

- **[PYTHON_SETUP_QUICK_GUIDE.md](PYTHON_SETUP_QUICK_GUIDE.md)**  
  Настройка Python окружения

---

### 💻 Для разработчиков

#### Точка входа
- **[docs/notes/README.md](docs/notes/README.md)** ⭐  
  *Developer Handoff Documentation*  
  Навигация по документации для разработчиков, быстрый старт

#### Архитектура и дизайн
- **[docs/architecture.md](docs/architecture.md)**  
  *Архитектура системы*  
  DDL схемы баз данных, инварианты, целевая архитектура

- **[docs/pipeline.md](docs/pipeline.md)**  
  *Детали pipeline*  
  Алгоритмы ingestion, processing, topicization, export

- **[docs/tech-stack.md](docs/tech-stack.md)**  
  *Выбор технологий*  
  Обоснование выбора Python, Pydantic, SQLAlchemy, Telethon

#### Требования
- **[docs/business-requirements.md](docs/business-requirements.md)**  
  *Бизнес-требования*  
  MVP scope, функциональные требования

- **[docs/technical-requirements.md](docs/technical-requirements.md)**  
  *Технические требования*  
  Все TR-* требования с детальным описанием

- **[docs/product-overview.md](docs/product-overview.md)**  
  *Общий обзор продукта*  
  Концепция, архитектура, flow

#### ADR (Architecture Decision Records)
- **[docs/adr/0001-overall-architecture.md](docs/adr/0001-overall-architecture.md)**  
  Общая архитектура системы

- **[docs/adr/0002-telegram-ingestion-approach.md](docs/adr/0002-telegram-ingestion-approach.md)**  
  Подход к сбору данных из Telegram

- **[docs/adr/0003-storage-and-indexing.md](docs/adr/0003-storage-and-indexing.md)**  
  Хранение данных и индексация

- **[docs/adr/0004-hexagonal-architecture-and-module-boundaries.md](docs/adr/0004-hexagonal-architecture-and-module-boundaries.md)**  
  Hexagonal Architecture и границы модулей

#### Контракты данных
- **[docs/contracts/](docs/contracts/)** — JSON Schema контракты
  - `knowledge_base_entry.schema.json` — KB Entry
  - `topic_card.schema.json` — Topic Card
  - `topic_bundle.schema.json` — Topic Bundle
  - `processed_document.schema.json` — Processed Document
  - `raw_telegram_message.schema.json` — Raw Message

#### Тестирование
- **[docs/testing-strategy.md](docs/testing-strategy.md)**  
  *Стратегия тестирования*  
  Unit, integration, E2E тесты

- **[tests/README.md](tests/README.md)**  
  *Документация тестов*  
  Как запускать тесты, структура, примеры

#### Развитие проекта
- **[DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)** ⭐  
  *План развития проекта*  
  Roadmap версий v1.1, v1.2, v2.0, технический долг, приоритеты

#### Сессия 14-17 — HTTP API, Agents и Multi-Agent (v2.0-v3.0)
- **[docs/notes/SESSION14_PHASE2B_COMPLETE.md](docs/notes/SESSION14_PHASE2B_COMPLETE.md)** ⭐  
  *Agents SDK PoC (Phase 2B)*  
  TGProcessingAgent, function tools, сравнение с v1.2 pipeline

- **[docs/notes/SESSION15_PHASE2E_COMPLETE.md](docs/notes/SESSION15_PHASE2E_COMPLETE.md)** ⭐  
  *Hybrid Agent Mode (Phase 2E)*

- **[docs/notes/SESSION16_PHASE2F_COMPLETE.md](docs/notes/SESSION16_PHASE2F_COMPLETE.md)** ⭐  
  *API Production (Phase 2F)*  
  API Key Auth, Rate Limiting, Webhooks, Request Logging  
  Pipeline tool, hybrid режим, CLI флаг --hybrid

- **[docs/notes/SESSION17_PHASE3A_COMPLETE.md](docs/notes/SESSION17_PHASE3A_COMPLETE.md)**  
  *Multi-Agent Architecture (Phase 3A)*  
  OrchestratorAgent, ProcessingAgent, TopicizationAgent, ExportAgent  
  Agent Registry, Handoff Protocol, 42 новых теста, CLI флаг --multi-agent

- **[docs/notes/SESSION18_PHASE3B_COMPLETE.md](docs/notes/SESSION18_PHASE3B_COMPLETE.md)**  
  *Agent State Persistence (Phase 3B)*  
  AgentState, TaskHistory, AgentStats, HandoffHistory, 25 тестов

- **[docs/notes/SESSION19_PHASE3C_COMPLETE.md](docs/notes/SESSION19_PHASE3C_COMPLETE.md)**  
  *Agent Observability (Phase 3C)*  
  CLI команды agents, API endpoints, AgentHistoryArchiver, 15 тестов

- **[docs/notes/SESSION20_PHASE3D_COMPLETE.md](docs/notes/SESSION20_PHASE3D_COMPLETE.md)**  
  *Advanced Features (Phase 3D)*  
  Prometheus Metrics, Background Scheduler, Health Checks v2, 26 тестов

- **[docs/notes/SESSION21_PHASE3_FINALIZATION_COMPLETE.md](docs/notes/SESSION21_PHASE3_FINALIZATION_COMPLETE.md)** ✅ COMPLETE  
  *Phase 3 Finalization (завершено)*  
  E2E Integration Tests (7 новых тестов), MIGRATION_GUIDE_v2_to_v3.md, v3.0.0 Release

#### Session 22+ — Phase 4 Production Hardening (v3.1)
- **[docs/notes/START_PROMPT_SESSION22_FOUNDATION.md](docs/notes/START_PROMPT_SESSION22_FOUNDATION.md)** 🎯 NEXT  
  *Foundation & Tech Debt (Phase 4A)*  
  Alembic Migrations, docs архивация, current-state.md, RetrySettings

#### Разработка
- **[docs/notes/current-state.md](docs/notes/current-state.md)**  
  *Текущее состояние проекта*  
  Что реализовано, следующие шаги, детали модулей

- **[docs/notes/implementation-plan.md](docs/notes/implementation-plan.md)**  
  *План реализации MVP*  
  Этапы, зависимости, критерии готовности

- **[docs/notes/processing-implementation.md](docs/notes/processing-implementation.md)**  
  *Детали реализации processing pipeline*  
  Технические подробности, API, соответствие TR

- **[docs/python-setup.md](docs/python-setup.md)**  
  *Настройка Python окружения*  
  Детальная инструкция

#### Scripts и утилиты
- **[scripts/README.md](scripts/README.md)**  
  *Вспомогательные скрипты*  
  `add_test_messages.py`, `view_processed.py`

---

### 🤝 Для контрибьюторов

#### Начало работы
1. **[README.md](README.md)** → Установка
2. **[docs/notes/README.md](docs/notes/README.md)** → Developer Handoff
3. **[docs/architecture.md](docs/architecture.md)** → Понимание структуры

#### Стандарты кода
- Следуйте **[docs/adr/0004-hexagonal-architecture-and-module-boundaries.md](docs/adr/0004-hexagonal-architecture-and-module-boundaries.md)**
- Проверяйте контракты через `ContractValidator`
- Используйте детерминированные ID (см. `tg_parser/domain/ids.py`)
- Форматируйте код: `ruff format .`
- Проверяйте: `ruff check .`
- Запускайте тесты: `pytest`

#### Процесс разработки
- **[docs/notes/implementation-plan.md](docs/notes/implementation-plan.md)** — общий план
- **[docs/testing-strategy.md](docs/testing-strategy.md)** — требования к тестам
- **[docs/technical-requirements.md](docs/technical-requirements.md)** — обязательные TR-*

---

## 📁 Структура документации

```
TG_parser/
├── README.md                          ⭐ Точка входа для всех
├── DOCUMENTATION_INDEX.md             ⭐ Этот файл (оглавление)
├── DEVELOPMENT_ROADMAP.md             ⭐ План развития проекта
│
├── 👤 Пользовательские руководства
│   ├── OUTPUT_FORMATS.md              ⭐ Форматы выходных файлов
│   ├── MULTI_CHANNEL_GUIDE.md         ⭐ Работа с каналами
│   ├── REAL_CHANNEL_TEST_RESULTS.md   ⭐ Результаты тестирования
│   ├── COMPLETION_SUMMARY.md             Краткий итог
│   └── PYTHON_SETUP_QUICK_GUIDE.md       Python setup
│
├── 💻 Документация для разработчиков
│   └── docs/
│       ├── USER_GUIDE.md                 Полное руководство
│       ├── DATA_FLOW.md                  Поток данных
│       ├── LLM_PROMPTS.md                Промпты LLM
│       │
│       ├── architecture.md               Архитектура
│       ├── pipeline.md                   Pipeline детали
│       ├── tech-stack.md                 Технологии
│       ├── python-setup.md               Python setup
│       │
│       ├── notes/
│       │   ├── SESSION14_PHASE2B_COMPLETE.md  ⭐ Agents SDK PoC (v2.0)
│       │   ├── SESSION15_PHASE2E_COMPLETE.md  ⭐ Hybrid Agent Mode (v2.0)
│       │   ├── SESSION16_PHASE2F_COMPLETE.md  ⭐ API Production (v2.0)
│       │   ├── SESSION17_PHASE3A_COMPLETE.md  ⭐ Multi-Agent Architecture (v3.0)
│       │   ├── SESSION18_PHASE3B_COMPLETE.md  ⭐ Agent State Persistence (v3.0)
│       │   ├── SESSION19_PHASE3C_COMPLETE.md  ⭐ Agent Observability (v3.0)
│       │   ├── SESSION20_PHASE3D_COMPLETE.md  ⭐ Advanced Features (v3.0)
│       │   └── SESSION21_PHASE3_FINALIZATION_COMPLETE.md  ✅ RELEASED
│       │
│       ├── business-requirements.md      Бизнес-требования
│       ├── technical-requirements.md     Технические требования
│       ├── product-overview.md           Обзор продукта
│       ├── testing-strategy.md           Стратегия тестирования
│       │
│       ├── contracts/                    JSON Schema контракты
│       │   ├── knowledge_base_entry.schema.json
│       │   ├── topic_card.schema.json
│       │   ├── topic_bundle.schema.json
│       │   ├── processed_document.schema.json
│       │   └── raw_telegram_message.schema.json
│       │
│       ├── adr/                          Architecture Decision Records
│       │   ├── 0001-overall-architecture.md
│       │   ├── 0002-telegram-ingestion-approach.md
│       │   ├── 0003-storage-and-indexing.md
│       │   └── 0004-hexagonal-architecture-and-module-boundaries.md
│       │
│       └── notes/                        Заметки разработчиков
│           ├── README.md                 ⭐ Developer Handoff
│           ├── QUICK_START.md            Быстрый старт
│           ├── current-state.md          Текущее состояние
│           ├── implementation-plan.md    План реализации
│           └── processing-implementation.md  Детали processing
│
├── scripts/
│   └── README.md                         Вспомогательные скрипты
│
├── tests/
│   └── README.md                         Документация тестов
│
└── 📦 Устаревшие/архивные (для справки)
    ├── SESSION_COMPLETE.md               Завершение сессии (архив)
    └── PROCESSING_COMPLETE.md            Завершение processing (архив)
```

---

## 🔄 Flowchart: Какой документ читать?

```
                    ┌─────────────────┐
                    │  Кто вы?        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌──────────────┐
      │ Пользователь │ │Разработчик│ │Контрибьютор │
      └──────┬───────┘ └─────┬────┘ └──────┬───────┘
             │               │              │
             ▼               ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌──────────────┐
      │  README.md   │ │docs/notes│ │README.md +   │
      │     ⭐       │ │/README.md│ │ ADRs         │
      └──────┬───────┘ └─────┬────┘ └──────┬───────┘
             │               │              │
       Что нужно?      Что делать?    Понять
             │               │         архитектуру
      ┌──────┴────────┐      │              │
      │               │      ▼              ▼
      ▼               ▼  ┌──────────┐ ┌──────────────┐
┌──────────┐  ┌──────────┐│current   │ │architecture  │
│Форматы   │  │Несколько ││-state.md │ │    .md       │
│файлов?   │  │каналов?  │└──────────┘ └──────────────┘
└────┬─────┘  └─────┬────┘      │              │
     │              │            ▼              ▼
     ▼              ▼       ┌──────────┐ ┌──────────────┐
┌──────────┐  ┌──────────┐ │Следующие │ │Стандарты     │
│OUTPUT_   │  │MULTI_    │ │задачи    │ │кода          │
│FORMATS.md│  │CHANNEL_  │ └──────────┘ └──────────────┘
│    ⭐    │  │GUIDE.md  │
└──────────┘  └──────────┘
```

---

## 📊 Метрики документации

| Категория | Файлов | Строк | Статус |
|-----------|--------|-------|--------|
| **Пользовательские** | 7 | ~2,500 | ✅ Полно |
| **Технические** | 8 | ~4,000 | ✅ Полно |
| **ADR** | 4 | ~1,200 | ✅ Полно |
| **Развитие** | 1 | ~700 | ✅ Полно |
| **Разработка** | 5 | ~1,500 | ✅ Полно |
| **Контракты** | 5 | ~300 | ✅ Полно |
| **Тесты/Scripts** | 2 | ~300 | ✅ Полно |
| **ИТОГО** | **32** | **~10,500** | **✅ Полно** |

---

## 🔍 Поиск по темам

### Архитектура
- [docs/architecture.md](docs/architecture.md) — DDL, инварианты
- [docs/adr/0001-overall-architecture.md](docs/adr/0001-overall-architecture.md) — общая архитектура
- [docs/adr/0004-hexagonal-architecture-and-module-boundaries.md](docs/adr/0004-hexagonal-architecture-and-module-boundaries.md) — Hexagonal

### Pipeline и обработка данных
- [docs/pipeline.md](docs/pipeline.md) — алгоритмы
- [docs/DATA_FLOW.md](docs/DATA_FLOW.md) — поток данных
- [docs/notes/processing-implementation.md](docs/notes/processing-implementation.md) — детали processing

### Ingestion
- [docs/adr/0002-telegram-ingestion-approach.md](docs/adr/0002-telegram-ingestion-approach.md) — подход
- [docs/pipeline.md](docs/pipeline.md) → раздел Ingestion

### Storage
- [docs/adr/0003-storage-and-indexing.md](docs/adr/0003-storage-and-indexing.md) — подход
- [docs/architecture.md](docs/architecture.md) → DDL схемы

### LLM и промпты
- [docs/LLM_PROMPTS.md](docs/LLM_PROMPTS.md) — все промпты
- [docs/pipeline.md](docs/pipeline.md) → Processing

### Форматы данных
- [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md) — выходные файлы
- [docs/contracts/](docs/contracts/) — JSON Schema
- [docs/DATA_FLOW.md](docs/DATA_FLOW.md) — трансформации

### Тестирование
- [REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md) — реальный канал
- [docs/testing-strategy.md](docs/testing-strategy.md) — стратегия
- [tests/README.md](tests/README.md) — запуск тестов

### CLI и использование
- [README.md](README.md) → CLI команды
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — полное руководство

### Работа с несколькими каналами
- [MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md) — детальное руководство
- [README.md](README.md) → раздел "Работа с несколькими каналами"

---

## 🆕 Недавно добавлено

- ✅ **SESSION21_PHASE3_FINALIZATION_COMPLETE.md** (28 дек 2025) — Phase 3 Finalization (v3.0.0 Release!)
- ✅ **MIGRATION_GUIDE_v2_to_v3.md** (28 дек 2025) — Руководство по миграции v2→v3
- ⭐ **SESSION20_PHASE3D_COMPLETE.md** (28 дек 2025) — Advanced Features (Phase 3D)
- ⭐ **SESSION19_PHASE3C_COMPLETE.md** (28 дек 2025) — Agent Observability (Phase 3C)
- ⭐ **SESSION18_PHASE3B_COMPLETE.md** (28 дек 2025) — Agent State Persistence (Phase 3B)
- ⭐ **SESSION17_PHASE3A_COMPLETE.md** (28 дек 2025) — Multi-Agent Architecture (Phase 3A)
- ⭐ **SESSION16_PHASE2F_COMPLETE.md** (28 дек 2025) — API Production (Phase 2F)
- ⭐ **SESSION15_PHASE2E_COMPLETE.md** (28 дек 2025) — Hybrid Agent Mode (Phase 2E)
- ⭐ **DEVELOPMENT_ROADMAP.md** (26 дек 2025, обновлено 28 дек) — План развития v1.1, v1.2, v2.0, v3.0
- ⭐ **OUTPUT_FORMATS.md** (26 дек 2025) — Форматы выходных файлов (~650 строк)
- ⭐ **MULTI_CHANNEL_GUIDE.md** (26 дек 2025) — Работа с несколькими каналами
- ⭐ **REAL_CHANNEL_TEST_RESULTS.md** (26 дек 2025) — Результаты тестирования на 846 сообщениях
- ⭐ **COMPLETION_SUMMARY.md** (26 дек 2025) — Краткий итог тестирования
- ⭐ **DOCUMENTATION_INDEX.md** (26 дек 2025) — Этот файл

---

## 📝 Рекомендации по использованию

### Для новых пользователей
1. Начните с **[README.md](README.md)** (Quick Start)
2. Изучите **[OUTPUT_FORMATS.md](OUTPUT_FORMATS.md)** для понимания данных
3. Прочитайте **[REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md)** для примеров

### Для разработчиков
1. Начните с **[docs/notes/README.md](docs/notes/README.md)**
2. Изучите **[docs/architecture.md](docs/architecture.md)**
3. Следуйте **[docs/notes/current-state.md](docs/notes/current-state.md)**

### Для контрибьюторов
1. Прочитайте все ADR в **[docs/adr/](docs/adr/)**
2. Изучите **[docs/technical-requirements.md](docs/technical-requirements.md)**
3. Следуйте **[docs/testing-strategy.md](docs/testing-strategy.md)**

---

## 🔗 Внешние ссылки

- **GitHub Issues**: [Issues](../../issues) (если доступно)
- **Telegram API**: https://my.telegram.org
- **OpenAI API**: https://platform.openai.com/docs
- **JSON Schema**: https://json-schema.org

---

## ✏️ Как обновлять эту документацию

При добавлении новых документов:
1. Добавьте файл в соответствующую категорию
2. Обновите этот index (DOCUMENTATION_INDEX.md)
3. Добавьте ссылку в README.md → раздел "Документация"
4. Обновите дату "Последнее обновление" вверху

---

**Версия**: 1.6 (v3.0.0 Release)  
**Последнее обновление**: 28 декабря 2025  
**Всего документов**: 41  
**Общий объём**: ~15,000 строк

---

💡 **Совет**: Добавьте эту страницу в закладки для быстрого доступа к любой документации!
