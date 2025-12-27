# Quick Start Guide: v1.2 Multi-LLM

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
  --model claude-3-5-sonnet-20241022

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

## ✅ Что нового в v1.2?

- ⭐ **4 LLM провайдера**: OpenAI, Anthropic, Gemini, Ollama
- ⚡ **Параллельная обработка**: `--concurrency` флаг (ускорение в 3-5x)
- 🐳 **Docker support**: Dockerfile и docker-compose.yml
- 🔄 **GitHub Actions CI**: автоматические тесты и линтинг
- 📊 **126 тестов** (было 103)

---

**v1.2.0 готова к использованию!** 🚀

Следующая версия: v2.0 с GPT-5 (OpenAI Agents SDK)

