# Что нового в v3.1.0-alpha.2: User-Facing Changes

**Дата релиза:** 29 декабря 2025  
**Код релиза:** Session 23

---

## 🎉 Основные изменения для пользователей

### 1. ✅ Structured JSON Logging

**Что это дает:**
- Production-ready логирование с JSON форматом
- Простая фильтрация и анализ логов через `jq`
- Request ID tracing для отладки API запросов
- Colored human-readable формат для development

**Как использовать:**

```bash
# Development (readable)
LOG_FORMAT=text LOG_LEVEL=DEBUG python -m tg_parser.cli process --channel my_channel

# Production (structured)
LOG_FORMAT=json LOG_LEVEL=INFO python -m tg_parser.cli process --channel my_channel

# Фильтрация логов
LOG_FORMAT=json python -m tg_parser.cli process --channel my_channel 2>&1 | \
  jq 'select(.level == "error")'

# Трейсинг конкретного запроса
curl -H "X-Request-ID: my-trace-123" http://localhost:8000/api/v1/process
```

**Новые переменные:**
- `LOG_FORMAT` — `json` или `text` (default: `text`)
- `LOG_LEVEL` — `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (default: `INFO`)

---

### 2. 🤖 GPT-5 Support

**Что это дает:**
- Полная поддержка GPT-5 моделей: `gpt-5.2`, `gpt-5-mini`, `gpt-5-nano`
- Автоматический routing через `/v1/responses` API
- Настраиваемые параметры reasoning и verbosity
- Backward compatible с GPT-4o-mini

**Как использовать:**

```bash
# Основной GPT-5
LLM_MODEL=gpt-5.2 python -m tg_parser.cli process --channel my_channel

# GPT-5 mini (дешевле)
LLM_MODEL=gpt-5-mini python -m tg_parser.cli process --channel my_channel

# С настройками reasoning
LLM_MODEL=gpt-5.2 \
LLM_REASONING_EFFORT=high \
LLM_VERBOSITY=medium \
  python -m tg_parser.cli process --channel my_channel
```

**Новые переменные:**
- `LLM_REASONING_EFFORT` — `minimal`, `low`, `medium`, `high` (default: `low`)
- `LLM_VERBOSITY` — `low`, `medium`, `high` (default: `low`)

**Доступные модели:**
- `gpt-5.2` — основная модель GPT-5
- `gpt-5-mini` — быстрая и дешевая
- `gpt-5-nano` — сверхбыстрая для простых задач
- `gpt-4o-mini` — продолжает работать (без изменений)

---

### 3. ⚙️ Configurable Retry Settings

**Что это дает:**
- Настраиваемые параметры retry логики
- Exponential backoff с jitter
- Конфигурация через ENV переменные
- Устойчивость к временным сбоям API

**Как использовать:**

```bash
# Агрессивные retry (для нестабильных API)
RETRY_MAX_ATTEMPTS=5 \
RETRY_BACKOFF_BASE=2.0 \
RETRY_BACKOFF_MAX=120.0 \
RETRY_JITTER=0.5 \
  python -m tg_parser.cli process --channel my_channel

# Минимальные retry (для стабильных API)
RETRY_MAX_ATTEMPTS=2 \
RETRY_BACKOFF_BASE=0.5 \
  python -m tg_parser.cli process --channel my_channel
```

**Новые переменные:**
- `RETRY_MAX_ATTEMPTS` — 1-10, количество попыток (default: `3`)
- `RETRY_BACKOFF_BASE` — 0.1-60.0, базовая задержка в секундах (default: `1.0`)
- `RETRY_BACKOFF_MAX` — 1.0-300.0, максимальная задержка (default: `60.0`)
- `RETRY_JITTER` — 0.0-1.0, фактор случайности (default: `0.3`)

**Формула retry:**
```
delay = min(backoff_base * (2 ^ attempt), backoff_max) * (1 + jitter * random())
```

---

## 📖 Обновленная документация

### Основные гайды:
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — полное руководство пользователя
- [QUICKSTART_v1.2.md](QUICKSTART_v1.2.md) — быстрый старт с v3.1
- [ENV_VARIABLES_GUIDE.md](ENV_VARIABLES_GUIDE.md) — справочник по всем переменным
- [LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md) — настройка GPT-5 и других LLM
- [MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md) — работа с несколькими каналами

### Технические документы:
- [CHANGELOG.md](CHANGELOG.md) — полный список изменений
- [docs/notes/SESSION23_QUICK_REFERENCE.md](docs/notes/SESSION23_QUICK_REFERENCE.md) — краткая справка по Session 23
- [docs/notes/current-state.md](docs/notes/current-state.md) — текущее состояние проекта

---

## 🧪 Тестирование

**Статус тестов:**
- ✅ 405 tests passed (100%)
- ✅ 24 новых тестов для Session 23
- ✅ Coverage: все новые features
- ✅ Backward compatibility: сохранена

**Прогон тестов:**
```bash
# Все тесты
python -m pytest tests/ -v

# Только новые Session 23 тесты
python -m pytest tests/test_logging.py -v
python -m pytest tests/test_gpt5_responses_api.py -v
python -m pytest tests/test_retry_settings.py -v
```

---

## 🔄 Миграция с v3.0.0

### Breaking Changes:
**Нет breaking changes!** v3.1.0-alpha.2 полностью обратно совместима с v3.0.0.

### Рекомендуемые действия:

1. **Обновите `.env` файл:**
```bash
# Добавьте новые переменные (опционально)
LOG_FORMAT=text
LOG_LEVEL=INFO
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_BASE=1.0
RETRY_BACKOFF_MAX=60.0
RETRY_JITTER=0.3

# Для GPT-5 (если планируете использовать)
LLM_MODEL=gpt-5.2
LLM_REASONING_EFFORT=low
LLM_VERBOSITY=low
```

2. **Для production: переключитесь на JSON логи:**
```bash
LOG_FORMAT=json
LOG_LEVEL=INFO
```

3. **Для GPT-5: обновите модель:**
```bash
LLM_MODEL=gpt-5.2  # или gpt-5-mini, gpt-5-nano
```

---

## 🚀 Production Deployment

### Рекомендуемая конфигурация для production:

```env
# Logging
LOG_FORMAT=json
LOG_LEVEL=INFO

# LLM (выберите один)
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.2              # или gpt-4o-mini для экономии
LLM_REASONING_EFFORT=medium    # для GPT-5
LLM_VERBOSITY=low              # для GPT-5

# Retry (агрессивный для production)
RETRY_MAX_ATTEMPTS=5
RETRY_BACKOFF_BASE=2.0
RETRY_BACKOFF_MAX=120.0
RETRY_JITTER=0.5

# API (если используете)
API_PORT=8000
API_KEY=your-secure-api-key
```

### Docker Compose пример:

```yaml
version: "3.8"
services:
  tg_parser:
    build: .
    environment:
      - LOG_FORMAT=json
      - LOG_LEVEL=INFO
      - LLM_MODEL=gpt-5.2
      - LLM_REASONING_EFFORT=medium
      - RETRY_MAX_ATTEMPTS=5
      - RETRY_BACKOFF_BASE=2.0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./data:/app/data
    ports:
      - "8000:8000"
```

---

## 💡 Best Practices

### 1. Logging

**Development:**
```bash
LOG_FORMAT=text LOG_LEVEL=DEBUG
```

**Production:**
```bash
LOG_FORMAT=json LOG_LEVEL=INFO
```

**Debugging Production:**
```bash
LOG_FORMAT=json LOG_LEVEL=DEBUG
# Фильтруйте с jq:
docker logs tg_parser | jq 'select(.level == "error")'
```

### 2. GPT-5 Configuration

**Fast & Cheap (для тестов):**
```bash
LLM_MODEL=gpt-5-mini
LLM_REASONING_EFFORT=minimal
LLM_VERBOSITY=low
```

**Balanced (для production):**
```bash
LLM_MODEL=gpt-5.2
LLM_REASONING_EFFORT=low
LLM_VERBOSITY=low
```

**High Quality (для сложных задач):**
```bash
LLM_MODEL=gpt-5.2
LLM_REASONING_EFFORT=high
LLM_VERBOSITY=medium
```

### 3. Retry Configuration

**Stable API (Google Gemini, Claude):**
```bash
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_BASE=1.0
```

**Unstable API (rate limits, timeouts):**
```bash
RETRY_MAX_ATTEMPTS=5
RETRY_BACKOFF_BASE=2.0
RETRY_BACKOFF_MAX=120.0
RETRY_JITTER=0.5
```

---

## 🐛 Troubleshooting

### 1. "Multiple head revisions" error in Alembic

**Решено в v3.1.0-alpha.2!** Все миграции теперь работают корректно.

### 2. JSON логи не парсятся

**Проверьте:**
```bash
# Убедитесь, что LOG_FORMAT=json
echo $LOG_FORMAT

# Попробуйте явно указать
LOG_FORMAT=json python -m tg_parser.cli process --channel test
```

### 3. GPT-5 не работает

**Проверьте:**
```bash
# Убедитесь, что OpenAI API key актуален
echo $OPENAI_API_KEY

# Проверьте модель
echo $LLM_MODEL

# Попробуйте явно указать
LLM_MODEL=gpt-5.2 python -m tg_parser.cli process --channel test
```

### 4. Retry не работает как ожидается

**Проверьте:**
```bash
# Проверьте значения
echo $RETRY_MAX_ATTEMPTS
echo $RETRY_BACKOFF_BASE

# Включите DEBUG логи
LOG_LEVEL=DEBUG python -m tg_parser.cli process --channel test
```

---

## 📞 Поддержка

**Документация:**
- [README.md](README.md) — основная информация
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — подробное руководство
- [ENV_VARIABLES_GUIDE.md](ENV_VARIABLES_GUIDE.md) — справка по переменным

**Технические детали:**
- [CHANGELOG.md](CHANGELOG.md) — полный список изменений
- [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) — roadmap проекта
- [docs/notes/SESSION23_QUICK_REFERENCE.md](docs/notes/SESSION23_QUICK_REFERENCE.md) — Session 23 справка

---

**Приятного использования TG_parser v3.1.0-alpha.2! 🚀**

