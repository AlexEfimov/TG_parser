# Session 9: Documentation Agent

## Роль

Привет! Ты Documentation Agent для проекта TG_parser. Твоя задача — создать полную техническую документацию для проекта.

## Контекст проекта

TG_parser — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных.

### Текущее состояние
- ✅ Проект полностью работает и протестирован на реальных каналах
- ✅ 85 тестов проходят
- ✅ Код на GitHub актуален

### Основные компоненты
```
tg_parser/
├── cli/           # CLI команды (init, add-source, ingest, process, topicize, export, run)
├── config/        # Настройки (pydantic-settings)
├── domain/        # Доменные модели (Pydantic v2)
├── ingestion/     # Сбор данных из Telegram (Telethon)
├── processing/    # Обработка через LLM (OpenAI)
├── storage/       # SQLite репозитории
└── export/        # Экспорт в NDJSON/JSON
```

### Pipeline этапы
1. **Ingestion** → сбор raw сообщений из Telegram
2. **Processing** → обработка через LLM (очистка, summary, topics, entities)
3. **Topicization** → кластеризация по темам
4. **Export** → экспорт KB entries + topics

---

## Задачи Session 9

### Задача 1: Пользовательская документация

**Файл:** `docs/USER_GUIDE.md`

Создать подробное руководство пользователя:

1. **Установка и настройка**
   - Требования (Python 3.12+, зависимости)
   - Получение Telegram API credentials
   - Получение OpenAI API key
   - Настройка .env файла

2. **Использование CLI**
   - Все команды с примерами
   - Параметры и опции
   - Типичные сценарии использования

3. **Примеры использования**
   - Quick start (минимальный пример)
   - Полный pipeline для нового канала
   - Incremental обновление
   - Экспорт с фильтрами

4. **Troubleshooting**
   - Частые ошибки и решения
   - Проблемы с авторизацией Telegram
   - Проблемы с OpenAI API

---

### Задача 2: Документация Data Flow

**Файл:** `docs/DATA_FLOW.md`

Создать детальное описание движения данных:

1. **Обзор архитектуры**
   - Диаграмма потока данных (текстовая/ASCII)
   - Связи между компонентами

2. **Этап Ingestion**
   - Входные данные (Telegram API)
   - Трансформации (Telethon Message → RawTelegramMessage)
   - Выходные данные (raw_storage.sqlite)
   - Таблицы и поля

3. **Этап Processing**
   - Входные данные (RawTelegramMessage)
   - Вызов LLM (промпты, параметры)
   - Трансформации (raw → ProcessedDocument)
   - Выходные данные (processing_storage.sqlite)
   - Извлекаемые поля (text_clean, summary, topics, entities, language)

4. **Этап Topicization**
   - Входные данные (ProcessedDocument[])
   - Алгоритм кластеризации (LLM-based)
   - Критерии качества тем (singleton vs cluster)
   - Выходные данные (TopicCard, TopicBundle)
   - Детерминизм (сортировка, tie-break)

5. **Этап Export**
   - Маппинг в KnowledgeBaseEntry
   - Форматы вывода (NDJSON, JSON)
   - Структура файлов

6. **Схемы данных**
   - Ссылки на JSON Schema контракты
   - Примеры данных на каждом этапе

---

### Задача 3: Документация промптов LLM

**Файл:** `docs/LLM_PROMPTS.md`

Создать документацию всех промптов:

1. **Processing Prompts**
   - `PROCESSING_SYSTEM_PROMPT` — полный текст
   - `PROCESSING_USER_PROMPT_TEMPLATE` — шаблон
   - Параметры LLM (temperature=0, max_tokens)
   - Формат ответа (JSON schema)
   - Примеры входа/выхода

2. **Topicization Prompts**
   - `TOPICIZATION_SYSTEM_PROMPT` — полный текст
   - `TOPICIZATION_USER_PROMPT_TEMPLATE` — шаблон
   - Критерии качества (singleton: score≥0.75, len≥300; cluster: ≥2 anchors, score≥0.6)
   - Формат ответа

3. **Supporting Items Prompts**
   - `SUPPORTING_ITEMS_SYSTEM_PROMPT` — полный текст
   - `SUPPORTING_ITEMS_USER_PROMPT_TEMPLATE` — шаблон
   - Формат ответа

4. **Мультиязычность**
   - Инструкция определения языка контента
   - Генерация на языке источника

5. **Механизм применения**
   - Когда вызывается каждый промпт
   - Как формируются параметры
   - Как парсится ответ
   - Обработка ошибок

---

## Существующая документация (для справки)

### Основные файлы
- `README.md` — общее описание, quick start
- `docs/architecture.md` — архитектура, DDL схемы
- `docs/pipeline.md` — описание pipeline
- `docs/technical-requirements.md` — требования TR-*
- `docs/contracts/*.schema.json` — JSON Schema контракты

### ADR (Architecture Decision Records)
- `docs/adr/0001-overall-architecture.md`
- `docs/adr/0002-telegram-ingestion-approach.md`
- `docs/adr/0003-storage-and-indexing.md`
- `docs/adr/0004-hexagonal-architecture-and-module-boundaries.md`

### Код с промптами
- `tg_parser/processing/prompts.py` — processing промпты
- `tg_parser/processing/topicization_prompts.py` — topicization промпты
- `tg_parser/processing/pipeline.py` — processing pipeline
- `tg_parser/processing/topicization.py` — topicization pipeline

---

## Требования к документации

1. **Язык:** Русский (основной), технические термины на английском
2. **Формат:** Markdown с примерами кода
3. **Стиль:** Практический, с примерами
4. **Аудитория:** Разработчики и технические пользователи

---

## Команды для работы

```bash
# Активировать окружение
source .venv/bin/activate

# Проверить тесты
pytest --tb=short -q

# Запустить CLI
python -m tg_parser.cli --help

# Пример pipeline
python -m tg_parser.cli init
python -m tg_parser.cli add-source --source-id test --channel-id @channel
python -m tg_parser.cli run --source test --out ./output --limit 10
```

---

## Порядок выполнения

1. Изучить существующую документацию и код
2. Создать `docs/USER_GUIDE.md`
3. Создать `docs/DATA_FLOW.md`
4. Создать `docs/LLM_PROMPTS.md`
5. Обновить `README.md` со ссылками на новые документы
6. Коммит и push

---

**Начинай с изучения кода и создания USER_GUIDE.md!**

