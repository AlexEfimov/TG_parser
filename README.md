# TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

## ✨ Возможности

- 📥 **Ingestion** — сбор сообщений и комментариев из Telegram-каналов через Telethon
- 🤖 **Processing** — обработка через OpenAI LLM: очистка текста, саммари, извлечение тем и сущностей
- 🏷️ **Topicization** — автоматическая кластеризация контента по темам
- 📤 **Export** — экспорт в форматах NDJSON/JSON для интеграции с RAG-системами

## 🚀 Quick Start

### 1. Установка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd TG_parser

# Создать виртуальное окружение
python3.12 -m venv .venv

# Активировать окружение
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Установить зависимости
pip install --upgrade pip
pip install -r requirements.txt

# Установить проект в режиме разработки
pip install -e .
```

### 2. Настройка конфигурации

```bash
# Скопировать пример конфигурации
cp .env.example .env

# Отредактировать .env файл с вашими credentials
```

### 3. Получение Telegram API credentials

1. Перейдите на https://my.telegram.org
2. Войдите под своим аккаунтом Telegram
3. Нажмите "API development tools"
4. Создайте приложение (любое имя и описание)
5. Скопируйте `api_id` и `api_hash`
6. Добавьте их в `.env` файл:
   ```env
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   TELEGRAM_PHONE=+79001234567
   ```

### 4. Настройка OpenAI API

1. Получите API ключ на https://platform.openai.com/api-keys
2. Добавьте в `.env`:
   ```env
   OPENAI_API_KEY=sk-...your-api-key...
   ```

### 5. Первый запуск

```bash
# Инициализация баз данных
python -m tg_parser.cli init

# Добавить источник (канал)
python -m tg_parser.cli add-source --source-id my_channel --channel-id @channel_username

# Запустить полный pipeline одной командой (рекомендуется)
python -m tg_parser.cli run --source my_channel --out ./output
```

При первом запуске ingestion Telethon попросит авторизацию — введите код из Telegram.

## 📖 CLI команды

### `init` — Инициализация БД

Создает SQLite базы данных и таблицы.

```bash
python -m tg_parser.cli init
```

### `add-source` — Добавление источника

Регистрирует Telegram канал для последующего сбора данных.

```bash
python -m tg_parser.cli add-source --source-id my_source --channel-id @channel_name

# С комментариями
python -m tg_parser.cli add-source --source-id my_source --channel-id @channel_name --include-comments
```

### `ingest` — Сбор сообщений

Собирает raw сообщения из Telegram канала.

```bash
# Инкрементальный сбор (только новые сообщения)
python -m tg_parser.cli ingest --source my_source --mode incremental

# Полный snapshot (все сообщения)
python -m tg_parser.cli ingest --source my_source --mode snapshot

# С ограничением количества
python -m tg_parser.cli ingest --source my_source --limit 100
```

### `process` — Обработка через LLM

Обрабатывает raw сообщения через OpenAI LLM.

```bash
python -m tg_parser.cli process --channel @channel_name

# Принудительная переобработка
python -m tg_parser.cli process --channel @channel_name --force
```

### `topicize` — Тематизация

Кластеризует документы по темам.

```bash
python -m tg_parser.cli topicize --channel @channel_name

# Без формирования bundles
python -m tg_parser.cli topicize --channel @channel_name --no-bundles

# Принудительная переобработка
python -m tg_parser.cli topicize --channel @channel_name --force
```

### `export` — Экспорт артефактов

Экспортирует данные в файлы.

```bash
python -m tg_parser.cli export --channel @channel_name --out ./output

# С фильтрами по дате
python -m tg_parser.cli export --channel @channel_name --from-date 2025-01-01 --to-date 2025-12-31

# Pretty print (форматированный JSON)
python -m tg_parser.cli export --channel @channel_name --out ./output --pretty
```

**Выходные файлы:**
- `kb_entries.ndjson` — записи базы знаний (NDJSON)
- `topics.json` — каталог тем
- `topic_<id>.json` — детальные карточки тем

### `run` — One-shot Pipeline ⭐

Запускает полный pipeline одной командой: ingest → process → topicize → export.

```bash
# Базовый запуск
python -m tg_parser.cli run --source my_channel --out ./output

# С режимом snapshot
python -m tg_parser.cli run --source my_channel --out ./output --mode snapshot

# Пропустить некоторые этапы
python -m tg_parser.cli run --source my_channel --out ./output --skip-ingest
python -m tg_parser.cli run --source my_channel --out ./output --skip-process --skip-topicize

# Force режим (переобработка всех документов)
python -m tg_parser.cli run --source my_channel --out ./output --force

# С ограничением для отладки
python -m tg_parser.cli run --source my_channel --out ./output --limit 10
```

**Опции:**
- `--source` — ID источника (обязательно)
- `--out` — директория вывода (по умолчанию `./output`)
- `--mode` — режим ingestion: `snapshot` или `incremental` (по умолчанию)
- `--skip-ingest` — пропустить этап сбора
- `--skip-process` — пропустить этап обработки
- `--skip-topicize` — пропустить этап тематизации
- `--force` — принудительная переобработка
- `--limit` — лимит сообщений для ingestion

## 📚 Работа с несколькими каналами

TG_parser поддерживает работу с любым количеством Telegram каналов одновременно.

### Хранение данных

**Базы данных (SQLite)**:
- ✅ Все каналы хранятся **вместе** в одних и тех же файлах `*.sqlite`
- ✅ При добавлении нового канала данные **добавляются**, а не заменяются
- ✅ Каждый канал идентифицируется по уникальному `channel_id`

**Export файлы**:
- ⚠️ Файлы в директории export **перезаписываются** при каждом запуске
- ✅ **Решение**: используйте разные директории для каждого канала

### Рекомендуемый подход

```bash
# Канал 1
python -m tg_parser.cli run \
  --source channel1 \
  --out ./output_channel1

# Канал 2
python -m tg_parser.cli add-source \
  --source-id channel2 \
  --channel-id @channel2_username

python -m tg_parser.cli run \
  --source channel2 \
  --out ./output_channel2

# Канал 3
python -m tg_parser.cli add-source \
  --source-id channel3 \
  --channel-id @channel3_username

python -m tg_parser.cli run \
  --source channel3 \
  --out ./output_channel3
```

**Результат**:
```
TG_parser/
├── *.sqlite              # Все каналы вместе
├── output_channel1/      # Export канала 1
│   ├── kb_entries.ndjson
│   └── topics.json
├── output_channel2/      # Export канала 2
│   ├── kb_entries.ndjson
│   └── topics.json
└── output_channel3/      # Export канала 3
    ├── kb_entries.ndjson
    └── topics.json
```

### Альтернативный подход: раздельный export

```bash
# Собрать данные всех каналов (без export)
python -m tg_parser.cli run --source channel1 --skip-export
python -m tg_parser.cli run --source channel2 --skip-export
python -m tg_parser.cli run --source channel3 --skip-export

# Экспортировать отдельно по мере необходимости
python -m tg_parser.cli export --channel channel1_id --out ./output_channel1
python -m tg_parser.cli export --channel channel2_id --out ./output_channel2
python -m tg_parser.cli export --channel channel3_id --out ./output_channel3
```

**Преимущества**:
- Все данные накапливаются в базах данных
- Export можно делать в любой момент
- Гибкий контроль над выходными файлами

**Подробнее**: См. [`MULTI_CHANNEL_GUIDE.md`](MULTI_CHANNEL_GUIDE.md) для детального руководства.

## 🏗️ Архитектура

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

### Data Pipeline

```
RawTelegramMessage → ProcessedDocument → (TopicCard/TopicBundle) → KnowledgeBaseEntry
```

### Базы данных (SQLite)

- `ingestion_state.sqlite` — состояние источников и курсоры
- `raw_storage.sqlite` — raw сообщения из Telegram
- `processing_storage.sqlite` — обработанные документы, темы, ошибки

## ⚙️ Конфигурация

Все настройки задаются через переменные окружения или `.env` файл.

См. [`.env.example`](.env.example) для полного списка настроек.

### Основные настройки

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `OPENAI_API_KEY` | API ключ OpenAI | — |
| `TELEGRAM_API_ID` | Telegram API ID | — |
| `TELEGRAM_API_HASH` | Telegram API Hash | — |
| `TELEGRAM_PHONE` | Номер телефона для авторизации | — |
| `LLM_MODEL` | Модель LLM | `gpt-4o-mini` |

## 🧪 Тестирование

```bash
# Все тесты (85 тестов)
pytest

# С verbose выводом
pytest -v

# Конкретный файл
pytest tests/test_e2e_pipeline.py

# С покрытием
pytest --cov=tg_parser
```

### Работа с тестовыми данными

```bash
# Добавить тестовые сообщения (без Telegram)
python scripts/add_test_messages.py

# Просмотреть обработанные документы
python scripts/view_processed.py --channel test_channel
```

## 🔧 Разработка

```bash
# Форматирование кода
ruff format .

# Проверка линтером
ruff check .

# Автоисправление
ruff check . --fix
```

## 📚 Документация

**[📖 Полное оглавление документации](DOCUMENTATION_INDEX.md)** ⭐ — навигация по всем 31 документам проекта

### 👤 Руководства пользователя

#### Начало работы
- **[User Guide](docs/USER_GUIDE.md)** — полное руководство с примерами и сценариями
- **[Output Formats](OUTPUT_FORMATS.md)** ⭐ — форматы выходных файлов (NDJSON, JSON), примеры интеграции
- **[Multi-Channel Guide](MULTI_CHANNEL_GUIDE.md)** — как работать с несколькими каналами одновременно

#### Углублённое изучение
- **[Data Flow](docs/DATA_FLOW.md)** — поток данных через систему, диаграммы, схемы
- **[LLM Prompts](docs/LLM_PROMPTS.md)** — документация всех промптов для LLM
- **[Real Channel Test Results](REAL_CHANNEL_TEST_RESULTS.md)** — результаты тестирования на 846 сообщениях

### 💻 Техническая документация

#### Архитектура и дизайн
- **[Architecture](docs/architecture.md)** — архитектура системы, DDL схемы баз данных
- **[Pipeline](docs/pipeline.md)** — детали обработки данных (ingestion, processing, topicization)
- **[ADRs](docs/adr/)** — архитектурные решения (4 документа)

#### Требования и спецификации
- **[Technical Requirements](docs/technical-requirements.md)** — технические требования (TR-*)
- **[Business Requirements](docs/business-requirements.md)** — бизнес-требования
- **[Data Contracts](docs/contracts/)** — JSON Schema контракты (5 схем)
- **[Tech Stack](docs/tech-stack.md)** — используемые технологии

#### Для разработчиков
- **[Developer Guide](docs/notes/README.md)** — документация для разработчиков, handoff

## 🛠️ Технологии

- **Python 3.12**
- **Pydantic v2** — валидация данных и настройки
- **SQLAlchemy 2.x + aiosqlite** — async хранилище
- **Telethon** — Telegram MTProto клиент
- **httpx** — async HTTP клиент для LLM API
- **Typer** — CLI интерфейс
- **pytest** — тестирование

## 🤝 Troubleshooting

### Ошибка авторизации Telethon

```
FloodWaitError: You must wait X seconds
```

Подождите указанное время. Telegram ограничивает частоту запросов авторизации.

### Ошибка API ключа

```
openai.AuthenticationError: Invalid API Key
```

Проверьте правильность `OPENAI_API_KEY` в `.env` файле.

### Пустой вывод при export

Убедитесь, что выполнены все предыдущие этапы:
1. `ingest` — собраны raw сообщения
2. `process` — обработаны через LLM
3. `topicize` — сформированы темы

Используйте команду `run` для автоматического выполнения всех этапов.

### Данные заменяются при работе с несколькими каналами

**Вопрос**: Если работать с другим каналом, данные заменятся?

**Ответ**:
- ✅ **Базы данных (SQLite)**: данные **НЕ заменяются**, новый канал добавляется к существующим
- ⚠️ **Export файлы**: **заменяются**, если использовать ту же директорию `--out`

**Решение**: Используйте разные директории для каждого канала:
```bash
python -m tg_parser.cli run --source channel1 --out ./output_channel1
python -m tg_parser.cli run --source channel2 --out ./output_channel2
```

Подробнее: [`MULTI_CHANNEL_GUIDE.md`](MULTI_CHANNEL_GUIDE.md)

## 📄 Лицензия

См. [LICENSE](LICENSE)
