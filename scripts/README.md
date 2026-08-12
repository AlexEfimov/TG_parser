# Testing Scripts

Вспомогательные скрипты для тестирования и демонстрации Processing Pipeline.

## Скрипты

### 0. `onboard_test_users.py` — выдача тестового доступа (admin)

Создаёт пользователей на **живом** инстансе через MCP, генерирует им токены,
проверяет вход под каждым новым токеном и печатает готовое приглашение.

```bash
export TGP_MCP_URL="https://mcp.example.com/mcp"
export TGP_ADMIN_MCP_TOKEN="<admin bearer token>"

python scripts/onboard_test_users.py issue alice bob --max-channels 3
python scripts/onboard_test_users.py ledger      # что выдано
python scripts/onboard_test_users.py revoke alice
```

`mapping_id` для отзыва хранится в `onboarding_ledger.json` (в `.gitignore`) —
других способов его получить, кроме SQL к `user_auth_mappings`, нет.
Полная инструкция оператора: [`docs/runbooks/TEST_ACCESS_MULTI_USER.md`](../docs/runbooks/TEST_ACCESS_MULTI_USER.md).

### 1. `add_test_messages.py` - Добавление тестовых сообщений

Добавляет 5 тестовых raw сообщений в базу данных для проверки processing pipeline.

**Использование:**
```bash
# --channel-id обязательный (см. BUG-002 mitigation M1):
python scripts/add_test_messages.py --channel-id my_dev_channel
```

**Что делает:**
- Создаёт 5 RawTelegramMessage с разным содержимым
- Сохраняет в `raw_storage.sqlite`
- Использует идемпотентный upsert (не дублирует существующие)
- Отвергает плейсхолдер-имена (`test_channel`, `example_channel`, …)

**Пример вывода:**
```
✓ Добавлено: tg:my_dev_channel:post:1001
✓ Добавлено: tg:my_dev_channel:post:1002
...
✅ Готово! Добавлено 5 новых сообщений
```

### 2. `view_processed.py` - Просмотр обработанных документов

Показывает обработанные документы из `processing_storage.sqlite`.

**Использование:**
```bash
# Просмотреть все документы канала
python scripts/view_processed.py --channel test_channel

# Просмотреть первые 3 документа
python scripts/view_processed.py --channel test_channel --limit 3
```

**Что показывает:**
- ID и source_ref
- Очищенный текст (text_clean)
- Краткое содержание (summary)
- Темы (topics)
- Извлечённые сущности (entities)
- Язык (language)
- Метаданные обработки (pipeline_version, model_id, prompt_id)

## Полный цикл тестирования

### Шаг 1: Инициализация

```bash
# Создать базы данных
python -m tg_parser.cli init

# Добавить .env с API ключом
echo "OPENAI_API_KEY=your-key-here" > .env
```

### Шаг 2: Добавить тестовые данные

```bash
# Добавить 5 тестовых raw сообщений (укажите свой канал, не плейсхолдер):
python scripts/add_test_messages.py --channel-id my_dev_channel
```

### Шаг 3: Обработать через LLM

```bash
# Запустить processing pipeline
python -m tg_parser.cli process --channel my_dev_channel
```

**Ожидаемый вывод:**
```
⚙️  Processing канала: my_dev_channel

✅ Processing завершён:
   • Обработано: 5
   • Пропущено: 0
   • Ошибок: 0
   • Всего сообщений: 5
```

### Шаг 4: Просмотреть результаты

```bash
# Посмотреть обработанные документы
python scripts/view_processed.py --channel test_channel
```

### Шаг 5: Проверить идемпотентность

```bash
# Повторный запуск без --force должен пропустить все сообщения
python -m tg_parser.cli process --channel test_channel
```

**Ожидаемый вывод:**
```
⚙️  Processing канала: test_channel

✅ Processing завершён:
   • Обработано: 0
   • Пропущено: 5
   • Ошибок: 0
   • Всего сообщений: 5
```

### Шаг 6: Проверить переобработку (force)

```bash
# Переобработать с новыми processed_at timestamps
python -m tg_parser.cli process --channel test_channel --force
```

**Ожидаемый вывод:**
```
⚠️  Режим force (переобработка)

✅ Processing завершён:
   • Обработано: 5
   • Пропущено: 0
   • Ошибок: 0
   • Всего сообщений: 5
```

## Проверка в SQLite напрямую

```bash
# Просмотр raw сообщений
sqlite3 raw_storage.sqlite "SELECT source_ref, substr(text, 1, 50) FROM raw_messages;"

# Просмотр processed документов
sqlite3 processing_storage.sqlite "SELECT id, source_ref, processed_at FROM processed_documents;"

# Проверка metadata
sqlite3 processing_storage.sqlite "SELECT source_ref, json_extract(metadata_json, '$.pipeline_version'), json_extract(metadata_json, '$.model_id') FROM processed_documents;"
```

## Troubleshooting

### Ошибка: "OpenAI API key not provided"

**Решение:** Создайте `.env` файл с ключом:
```bash
echo "OPENAI_API_KEY=sk-your-key-here" > .env
```

### Ошибка: "No raw messages found"

**Решение:** Сначала добавьте тестовые сообщения:
```bash
python scripts/add_test_messages.py --channel-id my_dev_channel
```

### Все сообщения пропускаются (skipped)

**Причина:** Сообщения уже обработаны (идемпотентность работает)

**Решение:** Используйте `--force` для переобработки:
```bash
python -m tg_parser.cli process --channel test_channel --force
```

## Примечания

- Скрипты используют async/await и требуют Python 3.11+
- API ключ OpenAI должен быть в `.env` или переменной окружения
- Все операции идемпотентны (можно запускать многократно)
- Тестовые сообщения создаются с current timestamp
