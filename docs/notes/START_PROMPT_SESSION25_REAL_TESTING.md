# 🚀 Session 25: Real Channel Testing

**Дата создания:** 30 декабря 2025  
**Предыдущая сессия:** Session 24 (PostgreSQL Production Ready)  
**Текущая версия:** v3.1.1

---

## 📋 Контекст для AI-ассистента

Это start prompt для Session 25. Перед началом работы ознакомься с указанными документами для понимания текущего состояния проекта.

---

## 📚 Обязательные документы для изучения

### 1. Текущее состояние проекта

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| [WHATS_NEXT.md](../../WHATS_NEXT.md) | Общий статус проекта, что готово, что дальше | ⭐⭐⭐ |
| [NEXT_STEPS.md](../../NEXT_STEPS.md) | Детальный план Session 25+ | ⭐⭐⭐ |
| [CHANGELOG.md](../../CHANGELOG.md) | История изменений, v3.1.1 | ⭐⭐ |

### 2. Session 24 (только что завершена)

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| [SESSION24_FINAL_CHANGES.md](SESSION24_FINAL_CHANGES.md) | Детали всех изменений Session 24 | ⭐⭐⭐ |
| [SESSION24_COMPLETE_SUMMARY.md](../../SESSION24_COMPLETE_SUMMARY.md) | Обзор Session 24 | ⭐⭐ |

### 3. Техническая документация

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| [docs/USER_GUIDE.md](../USER_GUIDE.md) | Полное руководство пользователя | ⭐⭐ |
| [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md) | Инструкции по деплою | ⭐⭐ |
| [README.md](../../README.md) | Обзор проекта, CLI команды | ⭐⭐ |

### 4. Архитектура (при необходимости)

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| [docs/architecture.md](../architecture.md) | Архитектура системы | ⭐ |
| [docs/technical-requirements.md](../technical-requirements.md) | Технические требования | ⭐ |

---

## 🎯 Цель Session 25: Real Channel Testing

### Основная задача

Провести комплексное тестирование TG_parser на нескольких реальных Telegram каналах с разным типом контента.

### Уже протестировано (Session 24)

```
✅ Канал: @BiocodebySechenov
   - 8 постов собрано
   - 8 документов обработано (GPT-4o-mini)
   - 4 темы созданы
   - Export успешен
   - PostgreSQL backend работает
```

### План тестирования Session 25

```
1. Выбор тестовых каналов:
   - Разные языки (русский, английский)
   - Разные типы контента (новости, технические, развлекательные)
   - Разные объёмы (маленькие и большие каналы)

2. Тестовые сценарии:
   - Snapshot ingestion (полный сбор)
   - Incremental ingestion (инкрементальный)
   - Large batch processing (100+ сообщений)
   - Concurrent processing

3. Метрики для сбора:
   - Время ingestion на N сообщений
   - Качество processing (summary, topics)
   - Качество topicization
   - Использование ресурсов (память, CPU, pool connections)

4. Возможные улучшения:
   - Оптимизация промптов на основе реальных данных
   - Tuning connection pool для production
   - Улучшение error handling
```

---

## 🔧 Текущее техническое состояние

### Версия: v3.1.1 (Production Tested)

```
✅ PostgreSQL 16 — полностью работает
✅ Connection Pooling — QueuePool (5 connections + 10 overflow)
✅ CLI — все команды работают с PostgreSQL
✅ Processing — GPT-4o-mini tested
✅ Тесты — 411 passed, 24 skipped
```

### Ключевые файлы

```
tg_parser/
├── cli/                    # CLI команды (обновлены для PostgreSQL)
│   ├── add_source_cmd.py
│   ├── ingest_cmd.py
│   ├── process_cmd.py
│   ├── topicize_cmd.py
│   ├── export_cmd.py
│   └── run_cmd.py          # One-shot pipeline
├── storage/
│   ├── engine_factory.py   # SQLite/PostgreSQL selection
│   └── sqlite/
│       └── database.py     # Database.from_settings()
└── config/
    └── settings.py         # DB_TYPE, DB_HOST, etc.
```

### Docker состояние

```bash
# PostgreSQL работает
docker compose ps
# NAME                 IMAGE                STATUS
# tg_parser_postgres   postgres:16-alpine   Up (healthy)
```

### База данных

```
PostgreSQL: localhost:5432/tg_parser
├── sources (1 запись: BiocodebySechenov)
├── raw_messages (8 записей)
├── processed_documents (8 записей)
├── topic_cards (4 записи)
└── ... (14 таблиц всего)
```

---

## 📝 CLI команды для тестирования

### Добавление канала

```bash
python -m tg_parser.cli add-source \
  --source-id <channel_username> \
  --channel-id <channel_username> \
  --channel-username <channel_username> \
  --no-include-comments \
  --batch-size 100
```

### Ingestion

```bash
# Snapshot (полный сбор)
python -m tg_parser.cli ingest \
  --source <source_id> \
  --mode snapshot \
  --limit 50

# Incremental (инкрементальный)
python -m tg_parser.cli ingest \
  --source <source_id> \
  --mode incremental
```

### Processing

```bash
python -m tg_parser.cli process \
  --channel <channel_id>
```

### Topicization

```bash
python -m tg_parser.cli topicize \
  --channel <channel_id>
```

### Export

```bash
python -m tg_parser.cli export \
  --out ./output/<channel_id> \
  --channel <channel_id> \
  --pretty
```

### One-shot pipeline

```bash
python -m tg_parser.cli run \
  --source <source_id> \
  --output ./output/<channel_id> \
  --mode snapshot \
  --limit 50
```

---

## ⚙️ Конфигурация (.env)

```env
# Database (PostgreSQL)
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=<password>

# LLM
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=<key>

# Telegram
TELEGRAM_API_ID=<id>
TELEGRAM_API_HASH=<hash>
TELEGRAM_PHONE=<phone>
TELEGRAM_SESSION_NAME=tg_parser_session
```

---

## 📊 Ожидаемые результаты Session 25

### Deliverables

1. **Test Report** — документ с результатами тестирования на 3-5 каналах
2. **Performance Metrics** — замеры производительности
3. **Quality Assessment** — оценка качества processing и topicization
4. **Recommendations** — рекомендации по оптимизации

### Файлы для создания

```
docs/notes/
├── SESSION25_TEST_REPORT.md       # Отчёт о тестировании
└── REAL_CHANNEL_BENCHMARKS.md     # Бенчмарки производительности
```

---

## ⚠️ Важные замечания

### Известные ограничения

1. **Comments** — пока не собираются (`--no-include-comments`)
2. **Media** — только метаданные, без скачивания файлов
3. **Rate limits** — Telegram может ограничивать частые запросы

### Потенциальные проблемы

1. **Приватные каналы** — нужно быть подписанным
2. **Большие каналы** — может потребоваться лимит
3. **Разные языки** — GPT-4o-mini хорошо работает с русским/английским

---

## 🚀 Начало работы

1. Прочитай документы из раздела "Обязательные документы"
2. Проверь состояние Docker: `docker compose ps`
3. Проверь подключение к БД: `docker compose exec postgres psql -U tg_parser_user -d tg_parser -c '\dt'`
4. Выбери каналы для тестирования
5. Начни тестирование по плану

**Удачной сессии!** 🎉

