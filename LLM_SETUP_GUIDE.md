# Multi-LLM Configuration Guide

**Version**: v3.0.0-alpha.3  
**Date**: 28 декабря 2025

> **Note**: Конфигурация LLM используется как в Pipeline v1.2, так и в Multi-Agent Architecture v3.0 с Agent Observability.

---

## 📋 Быстрый старт

### 1. Создайте .env файл

```bash
cp .env.example .env
```

### 2. Заполните API ключи в .env

```env
# Выберите провайдера
LLM_PROVIDER=openai

# Добавьте API key для выбранного провайдера
OPENAI_API_KEY=sk-...
```

### 3. Готово!

```bash
# Система автоматически загрузит настройки из .env
python -m tg_parser.cli process --channel my_channel
```

---

## 🔑 Как получить API ключи

### OpenAI (GPT-4, GPT-4o-mini)

1. Зарегистрируйтесь на https://platform.openai.com/
2. Перейдите в раздел "API keys": https://platform.openai.com/api-keys
3. Нажмите "Create new secret key"
4. Скопируйте ключ в `.env`:

```env
OPENAI_API_KEY=sk-proj-...
```

**Стоимость**: ~$0.15-0.60 за 1000 сообщений (зависит от модели)

---

### Anthropic Claude (рекомендуется)

1. Зарегистрируйтесь на https://console.anthropic.com/
2. Перейдите в "API Keys"
3. Нажмите "Create Key"
4. Скопируйте ключ в `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=anthropic
```

**Стоимость**: ~$0.30 за 1000 сообщений  
**Преимущества**: отличное качество, быстрая обработка, надёжный API

---

### Google Gemini (самый дешевый)

1. Перейдите на https://aistudio.google.com/app/apikey
2. Войдите через Google аккаунт
3. Нажмите "Create API Key"
4. Скопируйте ключ в `.env`:

```env
GEMINI_API_KEY=AIza...
LLM_PROVIDER=gemini
```

**Стоимость**: ~$0.075 за 1000 сообщений (в 2-4 раза дешевле OpenAI/Anthropic)  
**Примечание**: API может быть нестабильным (новый сервис)

---

### Ollama (бесплатно, локально)

Ollama — это локальный LLM сервер. **API key не требуется!**

#### macOS

```bash
# Установка
brew install ollama

# Запуск сервера
ollama serve

# В другом терминале: загрузка модели
ollama pull llama3.2

# Готово! Используйте в .env:
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2
```

#### Linux

```bash
# Установка
curl -fsSL https://ollama.com/install.sh | sh

# Запуск
ollama serve

# Загрузка модели
ollama pull llama3.2
```

#### Docker

```bash
# Используйте docker-compose (Ollama уже включен)
docker-compose up -d ollama
docker-compose exec ollama ollama pull llama3.2
```

**Стоимость**: Бесплатно!  
**Преимущества**: 
- Приватность (данные не покидают вашу машину)
- Нет rate limits
- Нет затрат на API

**Требования**: 
- Минимум 8GB RAM (рекомендуется 16GB)
- ~4GB места на диске для модели

---

## 🚀 Примеры использования

### OpenAI (default)

```bash
export OPENAI_API_KEY=sk-...
python -m tg_parser.cli process --channel my_channel
```

### Anthropic Claude

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m tg_parser.cli process --channel my_channel --provider anthropic
```

### Google Gemini

```bash
export GEMINI_API_KEY=AIza...
python -m tg_parser.cli process --channel my_channel --provider gemini
```

### Ollama (локально)

```bash
# Запустить Ollama server
ollama serve

# В другом терминале
python -m tg_parser.cli process --channel my_channel --provider ollama --model llama3.2
```

---

## ⚙️ Переопределение через CLI

API ключи можно задать **не только через .env**, но и через переменные окружения:

```bash
# Временное переопределение для одной команды
OPENAI_API_KEY=sk-test python -m tg_parser.cli process --channel test

# Переопределение через export
export ANTHROPIC_API_KEY=sk-ant-...
python -m tg_parser.cli process --channel my_channel --provider anthropic
```

---

## 🐳 Docker

### С .env файлом

```bash
# .env автоматически подхватывается docker-compose
docker-compose run tg_parser process --channel my_channel
```

### С переменными окружения

```bash
docker run --rm \
  -e OPENAI_API_KEY=sk-... \
  -e LLM_PROVIDER=openai \
  tg_parser process --channel my_channel
```

---

## 🔒 Безопасность

### ✅ Правильно

- ✅ Хранить ключи в `.env` (файл в `.gitignore`)
- ✅ Использовать переменные окружения
- ✅ Использовать секреты в CI/CD (GitHub Secrets)
- ✅ Регулярно ротировать ключи

### ❌ Неправильно

- ❌ Хардкодить ключи в коде
- ❌ Коммитить `.env` в git
- ❌ Делиться ключами публично
- ❌ Использовать один ключ для всех проектов

---

## 📊 Сравнение провайдеров

| Провайдер | Стоимость* | Качество | Скорость | Надёжность |
|-----------|------------|----------|----------|------------|
| **OpenAI** | $0.15-0.60 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Anthropic** | $0.30 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Gemini** | $0.075 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Ollama** | Бесплатно | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

*За 1000 сообщений

### Рекомендации

- **Production**: Anthropic Claude (лучшее соотношение качество/надёжность)
- **Development**: Ollama (бесплатно, приватно)
- **Cost-effective**: Gemini (дешево, но менее стабильно)
- **Проверенный вариант**: OpenAI (стандарт индустрии)

---

## 🆘 Troubleshooting

### "API key not provided"

```bash
# Проверьте, что .env загружается
python -c "from tg_parser.config import settings; print(settings.openai_api_key)"

# Если None, создайте .env из .env.example
cp .env.example .env
# Заполните API ключи
```

### "Unknown LLM provider"

```bash
# Проверьте доступные провайдеры
python -m tg_parser.cli process --help

# Используйте: openai, anthropic, gemini, ollama
```

### "Ollama connection refused"

```bash
# Убедитесь что Ollama запущен
ollama serve

# Проверьте доступность
curl http://localhost:11434/api/version
```

---

## 📚 См. также

- [README.md](../README.md) — Основная документация
- [DEVELOPMENT_ROADMAP.md](../DEVELOPMENT_ROADMAP.md) — Roadmap v1.2
- [SESSION_HANDOFF_v1.2.md](docs/notes/SESSION_HANDOFF_v1.2.md) — Детали реализации

---

**Version**: 1.1  
**Last Updated**: 28 декабря 2025

