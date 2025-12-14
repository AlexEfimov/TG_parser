# TG_parser

TG_parser — система, которая собирает контент из Telegram‑каналов, обрабатывает его с участием ИИ и предоставляет результаты в виде экспортируемых артефактов (MVP: CLI‑экспорт файлов).

## Быстрый старт

### Установка зависимостей

```bash
# Создать виртуальное окружение (если его нет)
python3.12 -m venv .venv

# Активировать окружение
source .venv/bin/activate  # macOS/Linux
# или .venv\Scripts\activate на Windows

# Обновить pip
pip install --upgrade pip

# Установить зависимости
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Установить проект в режиме разработки
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e .
```

> **Примечание**: Подробная документация по настройке Python окружения доступна в `docs/python-setup.md`

### Конфигурация

Создать файл `.env` в корне проекта:

```env
# LLM настройки (обязательно)
OPENAI_API_KEY=your-openai-api-key

# SQLite пути (опционально, по умолчанию в корне проекта)
INGESTION_STATE_DB_PATH=ingestion_state.sqlite
RAW_STORAGE_DB_PATH=raw_storage.sqlite
PROCESSING_STORAGE_DB_PATH=processing_storage.sqlite
```

### Базовое использование (MVP)

```bash
# Инициализация БД (создание таблиц)
python -m tg_parser.cli init

# Добавить источник (канал)
python -m tg_parser.cli add-source --channel-id mychannel

# Собрать raw сообщения
python -m tg_parser.cli ingest --channel mychannel

# Обработать сообщения (processing)
python -m tg_parser.cli process --channel mychannel

# Сформировать темы (topicization)
python -m tg_parser.cli topicize --channel mychannel

# Экспортировать артефакты
python -m tg_parser.cli export --channel mychannel --out ./output
```

## Документация

- **Архитектура**: `docs/architecture.md`
- **Пайплайн**: `docs/pipeline.md`
- **Требования**: `docs/business-requirements.md`, `docs/technical-requirements.md`
- **Стек**: `docs/tech-stack.md`
- **Контракты данных**: `docs/contracts/*.schema.json`
- **ADR**: `docs/adr/`
- **План реализации**: `docs/notes/implementation-plan.md`

## Ключевая идея MVP

Данные проходят через фиксированную магистраль контрактов:

`RawTelegramMessage` → `ProcessedDocument` → (`TopicCard`/`TopicBundle`) → export → `KnowledgeBaseEntry`

А доступ внешних потребителей в MVP обеспечивается через CLI‑экспорт (`topics.json`, `topic_<topic_id>.json`, `kb_entries.ndjson`).

## Архитектура кода

```
tg_parser/
├── domain/          # Pydantic v2 модели, ID утилиты, валидация контрактов
├── config/          # Настройки (pydantic-settings)
├── storage/         # Порты репозиториев + SQLite реализации
├── ingestion/       # Telegram ingestion (Telethon)
├── processing/      # LLM обработка и topicization
├── export/          # Формирование экспортных артефактов
└── cli/             # Typer CLI команды
```

## Технологии

- **Python 3.12**
- **Pydantic v2** (модели и настройки)
- **SQLAlchemy 2.x async** + **aiosqlite** (хранилище MVP)
- **Telethon** (Telegram MTProto клиент)
- **httpx** (LLM API вызовы)
- **Typer** (CLI)

## Разработка

```bash
# Форматирование и линтинг
ruff format .
ruff check .

# Тесты
pytest
```

## Лицензия

См. `LICENSE`
