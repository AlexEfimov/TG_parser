# Session 30: Инкрементальная обработка

**Дата:** 22 марта 2026  
**Версия:** v3.3.0 → v3.4.0  
**Приоритет:** HIGH  
**Оценка:** ~4-6 часов разработки  
**Предыдущая сессия:** Session 29 (Модульный рефакторинг)

---

## Цель Session 30

Реализовать **автоматическую инкрементальную обработку** — система сама подхватывает новые сообщения из Telegram-каналов и прогоняет их через полный pipeline (ingest → process → topicize → export) без ручного вмешательства.

Результат: переход из режима "ручной запуск CLI" в режим "запустил и забыл".

---

## Контекст из Session 29

### Текущее состояние проекта

```
tg_parser/
├── domain/       — доменные модели (leaf, 100% автономность)
├── config/       — Pydantic-settings (leaf, 100%)
├── storage/      — абстракции + SQLAlchemy реализация (~76%)
├── ingestion/    — Telethon клиент + оркестратор (~85%)
├── processing/   — LLM pipeline + топикизация (~76%)
├── export/       — NDJSON/JSON экспорт (~88%)
├── agents/       — мульти-агентная система (~52%)
├── api/          — FastAPI HTTP-сервер (~52%)
├── cli/          — Typer CLI (~31%)
└── services/     — бизнес-логика (новый, Session 29)
```

### Что уже есть для инкрементальной обработки

1. **`--mode incremental` в ingestion** — работает. Использует `source.last_post_id` как курсор, передаёт `min_id` в Telethon. После ingestion обновляет курсор через `state_repo.update_cursors()`.

2. **Модель Source** (`storage/ports.py`) — уже содержит все нужные поля:
   ```
   source_id, channel_id, channel_username, status,
   include_comments, poll_interval_seconds, batch_size,
   last_post_id, backfill_completed_at,
   last_attempt_at, last_success_at, fail_count, last_error,
   rate_limit_until, comments_unavailable,
   created_at, updated_at
   ```

3. **APScheduler** (`api/scheduler.py`) — уже интегрирован в FastAPI. `BackgroundScheduler` с `IntervalTrigger`. Есть `cleanup_expired_records` и `health_check_task` как примеры.

4. **Processing skip-логика** — `pipeline.py` автоматически пропускает уже обработанные сообщения (`processed_repo.exists(source_ref)`).

5. **Full pipeline** (`services/pipeline_service.py`) — `run_full_pipeline()` уже поддерживает `mode="incremental"` и передаёт его в ingestion.

### Чего не хватает

1. **Scheduled pipeline job** — нет периодической задачи "обойти все активные источники и запустить incremental pipeline".

2. **Автоматическая ретопикизация** — после добавления новых документов темы не обновляются автоматически.

3. **Отслеживание состояния запусков** — `source_attempts` таблица существует, но не используется для записи результатов pipeline runs.

4. **CLI-команда для управления scheduler** — нет способа запустить scheduler из CLI (только через `tg-parser api`).

5. **Логика "когда ретопикизировать"** — нужна стратегия: после каждого ingestion? По расписанию? При накоплении N новых документов?

---

## Обязательные документы для изучения

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| `tg_parser/services/pipeline_service.py` | Full pipeline orchestration | ⭐⭐⭐ |
| `tg_parser/services/ingestion_service.py` | Ingestion service | ⭐⭐⭐ |
| `tg_parser/ingestion/orchestrator.py` | Orchestrator с incremental логикой | ⭐⭐⭐ |
| `tg_parser/api/scheduler.py` | APScheduler integration | ⭐⭐⭐ |
| `tg_parser/storage/ports.py` | Source модель, IngestionStateRepo | ⭐⭐ |
| `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` | Cursor persistence, source_attempts | ⭐⭐ |
| `tg_parser/api/main.py` | FastAPI startup (scheduler init) | ⭐⭐ |
| `docs/notes/DEVELOPMENT_ROADMAP_SESSION29.md` | Roadmap и приоритеты | ⭐ |

---

## Scope Session 30

### 1. Scheduled Incremental Pipeline Job

Реализовать periodic task в APScheduler, который:
- Получает список всех источников со `status='active'`
- Для каждого источника запускает `run_full_pipeline(mode="incremental")`
- Использует `poll_interval_seconds` из Source для определения частоты (или глобальный default)
- Записывает результат в `source_attempts` + обновляет `last_attempt_at`, `last_success_at`, `fail_count`

### 2. CLI-команда `tg-parser scheduler`

Новая CLI-команда для запуска standalone scheduler (без HTTP API):
```bash
# Запустить scheduler (daemon mode)
tg-parser scheduler start

# Показать статус задач
tg-parser scheduler status

# Одноразовый прогон всех активных источников
tg-parser scheduler run-once
```

### 3. Стратегия ретопикизации

Определить и реализовать логику автоматического обновления тем:
- **Вариант A:** Ретопикизация после каждого successful ingestion (простой, но может быть дорого по LLM-вызовам)
- **Вариант B:** Ретопикизация при накоплении N новых документов (экономичнее)
- **Вариант C:** Ретопикизация по отдельному расписанию (независимо от ingestion)

### 4. Отслеживание состояния

Использовать `source_attempts` таблицу для записи:
- Время начала/окончания каждого запуска
- Количество новых сообщений
- Количество обработанных документов
- Ошибки (если были)
- Trigger: scheduled / manual

### 5. Graceful Shutdown и Error Handling

- Корректное завершение при SIGTERM/SIGINT
- Обработка ошибок отдельных источников (один failed — остальные продолжают)
- Rate limit handling (Telegram flood wait)
- Экспоненциальный backoff при повторных ошибках

---

## Конфигурация

Новые переменные в `.env`:

```env
# Scheduler
SCHEDULER_ENABLED=true
SCHEDULER_DEFAULT_INTERVAL=3600    # секунд (1 час по умолчанию)
SCHEDULER_RETOPICIZE_THRESHOLD=10  # количество новых документов для ретопикизации
SCHEDULER_MAX_CONCURRENT_SOURCES=1 # параллельная обработка источников
```

---

## Тестирование

### Ожидаемые сценарии

1. **Один источник, новые посты** — scheduler запускает incremental ingestion, обрабатывает только новые
2. **Несколько источников** — scheduler обрабатывает каждый по очереди (или параллельно)
3. **Источник без новых постов** — ingestion возвращает 0, processing/topicize скипаются
4. **Ошибка в одном источнике** — не блокирует обработку остальных
5. **Ретопикизация по threshold** — после накопления N новых документов автоматически запускается topicize
6. **Graceful shutdown** — текущий pipeline завершается, scheduler останавливается

### Верификация на реальном канале

Запустить scheduler для @labdiagnostica_logical на 30 минут:
- Проверить, что incremental ingestion подхватывает только новые посты
- Проверить, что processing обрабатывает только необработанные
- Проверить, что source_attempts записывает результаты

---

## Техническое состояние

### База данных (локальный PostgreSQL)

```
PostgreSQL 16 (Homebrew): localhost:5432/tg_parser
├── sources (1 запись: labdiagnostica)
├── raw_messages (1130 записей)
├── processed_documents (1128 записей)
├── topic_cards (64 записи)
├── topic_bundles (64 записи)
├── processing_failures (115 записей)
├── source_attempts (пусто — не используется)
└── comment_cursors
```

### LLM конфигурация

```
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
LLM_PROCESSING_PROVIDER=anthropic
LLM_PROCESSING_MODEL=claude-haiku-4-5-20251001  (для processing)
LLM_TOPICIZATION_PROVIDER=anthropic
LLM_TOPICIZATION_MODEL=claude-sonnet-4-20250514  (для topicization)
```

### Тесты

```
295 passed, 8 skipped (sandbox network restrictions)
Предварительно failing: test_full_pipeline_e2e, test_comments_ingestion, test_error_handling_and_retry_logic
```

---

## Ограничения

1. **Telegram rate limits** — Telethon может получить FloodWait; нужен exponential backoff
2. **LLM costs** — каждый вызов processing стоит денег; не запускать чаще, чем нужно
3. **Обратная совместимость CLI** — все существующие команды должны работать как прежде
4. **Single instance** — scheduler не должен запускать две обработки одного источника одновременно
5. **Тесты** — существующие тесты не должны ломаться

---

## Критерии завершения Session 30

### Must Have:
- [ ] Scheduled incremental pipeline job работает в APScheduler
- [ ] CLI-команда `tg-parser scheduler run-once` — одноразовый прогон
- [ ] Source.last_attempt_at и last_success_at обновляются после каждого запуска
- [ ] Ошибка одного источника не блокирует остальные
- [ ] Graceful shutdown при SIGTERM
- [ ] Существующие тесты проходят

### Should Have:
- [ ] Стратегия ретопикизации по threshold
- [ ] CLI `tg-parser scheduler start` для daemon mode
- [ ] source_attempts запись с деталями каждого запуска
- [ ] Тесты для scheduler логики

### Nice to Have:
- [ ] `tg-parser scheduler status` — показывает состояние задач
- [ ] Параллельная обработка нескольких источников
- [ ] Метрики scheduler (время последнего запуска, количество ошибок)

---

## Начало работы

1. Изучить документы из раздела "Обязательные документы"
2. Проверить PostgreSQL: `psql -U tg_parser_user -d tg_parser -c '\dt'`
3. Проверить текущие источники: `psql -U tg_parser_user -d tg_parser -c 'SELECT source_id, status, poll_interval_seconds FROM sources'`
4. Запустить тесты: `.venv/bin/python -m pytest tests/ -q --ignore=tests/test_agents.py --ignore=tests/test_multi_agent.py --ignore=tests/test_gpt5_responses_api.py --ignore=tests/test_llm_clients.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_postgres_integration.py`
5. Начать реализацию по плану
