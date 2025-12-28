# Quick Start Guide: v1.2 Multi-LLM + v2.0 Agents + v3.0 Multi-Agent

## 🚀 5-минутная настройка

### 1. Установка

```bash
# Клонируйте репозиторий
git clone <repo-url>
cd TG_parser

# Создайте виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate  # Windows

# Установите зависимости
pip install -r requirements.txt
pip install -e .
```

### 2. Настройка API ключей

```bash
# Скопируйте пример конфигурации
cp .env.example .env

# Откройте .env и добавьте API ключи
# Минимум нужен один из:
# - OPENAI_API_KEY (получить на platform.openai.com)
# - ANTHROPIC_API_KEY (получить на console.anthropic.com)
# - GEMINI_API_KEY (получить на aistudio.google.com)
# - Или используйте Ollama (бесплатно, локально)
```

### 3. Инициализация

```bash
# Создайте базы данных
python -m tg_parser.cli init
```

### 4. Использование

```bash
# Добавьте источник (Telegram канал)
python -m tg_parser.cli add-source \
  --source-id my_channel \
  --channel-id 1234567890

# Соберите сообщения
python -m tg_parser.cli ingest --source my_channel

# Обработайте через LLM (выберите провайдера)
python -m tg_parser.cli process --channel my_channel --provider openai
# или
python -m tg_parser.cli process --channel my_channel --provider anthropic
# или
python -m tg_parser.cli process --channel my_channel --provider gemini
# или (локально, бесплатно)
python -m tg_parser.cli process --channel my_channel --provider ollama

# Экспортируйте результаты
python -m tg_parser.cli export --out ./output
```

---

## ⚡ Быстрые команды v1.2

### Multi-LLM Support

```bash
# OpenAI (default)
python -m tg_parser.cli process --channel my_channel

# Anthropic Claude (рекомендуется для production)
python -m tg_parser.cli process --channel my_channel \
  --provider anthropic \
  --model claude-sonnet-4-20250514

# Google Gemini (самый дешёвый)
python -m tg_parser.cli process --channel my_channel \
  --provider gemini \
  --model gemini-2.0-flash-exp

# Ollama (бесплатно, локально)
python -m tg_parser.cli process --channel my_channel \
  --provider ollama \
  --model llama3.2
```

### Параллельная обработка (ускорение в 3-5x)

```bash
# Последовательная обработка (по умолчанию)
python -m tg_parser.cli process --channel my_channel

# Параллельная обработка (быстрее!)
python -m tg_parser.cli process --channel my_channel --concurrency 5

# Максимальная производительность (с локальным Ollama)
python -m tg_parser.cli process --channel my_channel \
  --provider ollama \
  --concurrency 10
```

### One-shot pipeline

```bash
# Полный цикл: ingest → process → topicize → export
python -m tg_parser.cli run \
  --source my_channel \
  --out ./output \
  --provider anthropic \
  --concurrency 5
```

---

## 🤖 Agent-based Processing (v2.0) ⭐ NEW

Альтернативный режим обработки через OpenAI Agents SDK:

### Agent Basic (без LLM, ~0.3ms/сообщение)

```bash
# Быстрая обработка без API вызовов
python -m tg_parser.cli process --channel my_channel --agent

# С параллельной обработкой
python -m tg_parser.cli process --channel my_channel --agent --concurrency 10
```

### Agent LLM (с глубоким анализом)

```bash
# Семантический анализ с LLM
python -m tg_parser.cli process --channel my_channel --agent --agent-llm

# С конкретным провайдером
python -m tg_parser.cli process --channel my_channel \
  --agent --agent-llm \
  --provider openai
```

### Сравнение режимов

| Режим | Скорость | LLM | Качество |
|-------|----------|-----|----------|
| Pipeline v1.2 | ~500-2000ms | ✅ | Высокое |
| **Agent Basic** | **~0.3ms** | ❌ | Среднее |
| Agent LLM | ~500-1500ms | ✅ | Высокое |
| **Multi-Agent v3.0** | Адаптивно | ✅ | Лучшее |

---

## 🤖 Multi-Agent Architecture (v3.0) ⭐ NEW

Мультиагентная архитектура с оркестратором и специализированными агентами:

### Базовое использование

```bash
# Multi-Agent режим
python -m tg_parser.cli process --channel my_channel --multi-agent

# С конкретным провайдером
python -m tg_parser.cli process --channel my_channel --multi-agent --provider anthropic

# С параллельной обработкой
python -m tg_parser.cli process --channel my_channel --multi-agent --concurrency 3
```

### Архитектура

```
┌──────────────────────────┐
│    OrchestratorAgent     │  ← Координация workflow
└──────────────────────────┘
     │         │         │
     ▼         ▼         ▼
┌─────────┐ ┌──────────┐ ┌───────────┐
│Process- │ │Topiciz-  │ │Export-    │
│ingAgent │ │ationAgent│ │Agent      │
└─────────┘ └──────────┘ └───────────┘
```

### Когда использовать Multi-Agent?

- Сложные документы требующие специализированной обработки
- Расширяемые workflow с возможностью добавления новых агентов
- Детальный мониторинг по агентам

---

## 🐳 Docker

```bash
# Build
docker build -t tg_parser .

# Инициализация
docker-compose run tg_parser init

# Processing с выбранным провайдером
docker-compose run tg_parser process --channel my_channel \
  --provider anthropic \
  --concurrency 5

# С локальным Ollama
docker-compose up -d ollama
docker-compose exec ollama ollama pull llama3.2
docker-compose run tg_parser process --channel my_channel \
  --provider ollama
```

---

## 📚 Документация

- **[LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md)** — Полная инструкция по настройке LLM провайдеров
- **[SESSION_HANDOFF_v1.2.md](docs/notes/SESSION_HANDOFF_v1.2.md)** — Детали реализации v1.2
- **[CHANGELOG.md](CHANGELOG.md)** — История изменений
- **[README.md](README.md)** — Полная документация

---

## ✅ Что нового?

### v1.2
- ⭐ **4 LLM провайдера**: OpenAI, Anthropic, Gemini, Ollama
- ⚡ **Параллельная обработка**: `--concurrency` флаг (ускорение в 3-5x)
- 🐳 **Docker support**: Dockerfile и docker-compose.yml

### v2.0
- 🌐 **HTTP API**: REST API с FastAPI на `/docs`
- 🤖 **Agent-based Processing**: OpenAI Agents SDK
- 🚀 **Agent Basic**: обработка без LLM (~0.3ms/сообщение)
- 🧠 **Agent LLM**: глубокий семантический анализ

### v3.0 ⭐ NEW
- 🤖 **Multi-Agent Architecture**: OrchestratorAgent + специализированные агенты
- 📋 **Agent Registry**: централизованное управление агентами
- 🔄 **Handoff Protocol**: стандартизированный обмен данными между агентами
- 🎯 **Specialized Agents**: ProcessingAgent, TopicizationAgent, ExportAgent

### v3.0.0-alpha.2 (Phase 3B)
- 💾 **Agent State Persistence**: сохранение состояния агентов в SQLite
- 📊 **Task History**: полный input/output с TTL и ретенцией
- 📈 **Agent Stats**: ежедневная агрегированная статистика
- 🔗 **Handoff History**: отслеживание передач между агентами

### v3.0.0-alpha.3 (Phase 3C)
- 📊 **Agent Observability**: CLI команды `agents` для мониторинга
- 🌐 **API Endpoints**: `/api/v1/agents/*` для агентов
- 📦 **Archiver**: архивация истории в NDJSON.gz
- 🧪 **340 тестов** (было 325)

### v3.0.0-alpha.4 ⭐ NEW (Phase 3D)
- 📈 **Prometheus Metrics**: endpoint `/metrics` для мониторинга
- ⏰ **Background Scheduler**: APScheduler для периодических задач
- 🏥 **Health Checks v2**: `/status/detailed`, `/scheduler` endpoints
- 🧪 **366 тестов** (было 340)

---

**v3.0.0-alpha.4 готова к использованию!** 🚀

