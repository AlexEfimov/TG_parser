# Session 31: Параллельная обработка

**Дата:** 22 марта 2026  
**Версия:** v3.4.0 → v3.5.0  
**Приоритет:** P2  
**Оценка:** ~3-4 часа разработки  
**Предыдущая сессия:** Session 30 (Инкрементальная обработка)

---

## Цель Session 31

Обеспечить **реальную параллельную обработку** при вызове LLM. Сейчас processing (Haiku) работает **последовательно** (concurrency=1), хотя rate limiter настроен на Tier 2 Anthropic (1000 RPM). Нужно:

1. Подключить `PROCESSING_CONCURRENCY` из `.env` к pipeline
2. Установить адекватный default concurrency (5-10) для processing
3. Пробросить concurrency через scheduler и pipeline service
4. Убедиться что rate limiter корректно работает при высокой параллельности

Результат: обработка 1000+ сообщений за минуты вместо десятков минут.

---

## Контекст из Session 30

### Текущее состояние проекта

```
tg_parser/
├── domain/       — доменные модели (leaf, 100% автономность)
├── config/       — Pydantic-settings (leaf, 100%)
├── storage/      — абстракции + SQLAlchemy реализация
├── ingestion/    — Telethon клиент + оркестратор
├── processing/   — LLM pipeline + топикизация
├── export/       — NDJSON/JSON экспорт
├── agents/       — мульти-агентная система
├── api/          — FastAPI HTTP-сервер + APScheduler
├── cli/          — Typer CLI (incl. scheduler subcommand)
└── services/     — бизнес-логика (pipeline, scheduler, ingestion, processing, topicization, export)
```

### Что реализовано в Session 30

- **Incremental pipeline scheduler** — APScheduler задача `incremental_pipeline` запускает `run_incremental_for_all_sources()` по расписанию
- **CLI `tg-parser scheduler`** — `run-once`, `start` (daemon), `status`
- **Ретопикизация по threshold** — после N новых документов автоматический вызов `run_topicization(force=True)`
- **source_attempts** — каждый запуск записывается с `details_json` (trigger, new_messages, duration, pipeline_stats)
- **Graceful shutdown** — SIGTERM/SIGINT handler в daemon mode

### Выявленная проблема с concurrency

Во время верификации Session 30 обнаружено, что **processing всегда работает с concurrency=1**, несмотря на настройки в `.env`. Ниже — полная диагностика.

---

## Диагностика проблемы

### 1. Мёртвая переменная `PROCESSING_CONCURRENCY`

В `.env`:
```env
PROCESSING_CONCURRENCY=20
PROCESSING_RATE_LIMIT_RPM=1000
PROCESSING_RATE_LIMIT_ITPM=450000
PROCESSING_RATE_LIMIT_OTPM=90000
```

`PROCESSING_RATE_LIMIT_*` — **работают** (читаются в `rate_limiter.py` через `from_settings()`).

`PROCESSING_CONCURRENCY=20` — **НЕ работает**. В `Settings` (pydantic) нет такого поля. Переменная игнорируется.

### 2. Цепочка вызовов с concurrency=1

```
CLI (--concurrency 1, default)
  → services/processing_service.py: run_processing(concurrency=1)
    → processing/pipeline.py: process_batch(concurrency=1)
      → _process_batch_sequential()  ← ПОСЛЕДОВАТЕЛЬНО
```

При concurrency > 1:
```
    → processing/pipeline.py: process_batch(concurrency=N)
      → _process_batch_parallel()
        → asyncio.Semaphore(N) + asyncio.gather()
```

Параллельная ветка **реализована и работает**, но никогда не вызывается из-за default=1.

### 3. Scheduler не передаёт concurrency

```
services/scheduler_service.py: run_incremental_for_all_sources()
  → services/pipeline_service.py: run_full_pipeline(mode="incremental")
    → services/processing_service.py: run_processing(channel_id, force=False)
      → concurrency=1 (default)
```

`run_full_pipeline()` не принимает параметр concurrency — он теряется.

### 4. Topicization: hardcoded concurrency=5

`processing/topicization.py`:
```python
BATCH_SIZE = 50
BATCH_CONCURRENCY = 5  # hardcoded
```

Для больших каналов (>50 docs) батчи обрабатываются с concurrency=5. Это работает, но не конфигурируется.

### 5. Rate limiter: suggest_processing_concurrency не используется

`AnthropicClient.suggest_processing_concurrency()` существует, но нигде не вызывается. Метод умеет снижать параллелизм при нехватке слотов в rate limit окне.

---

## Обязательные документы для изучения

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| `tg_parser/config/settings.py` | Pydantic Settings — добавить processing_concurrency | ⭐⭐⭐ |
| `tg_parser/processing/pipeline.py` | process_batch, _process_batch_parallel | ⭐⭐⭐ |
| `tg_parser/services/processing_service.py` | run_processing(concurrency=1) | ⭐⭐⭐ |
| `tg_parser/services/pipeline_service.py` | run_full_pipeline — нет concurrency | ⭐⭐⭐ |
| `tg_parser/services/scheduler_service.py` | run_incremental_for_all_sources | ⭐⭐ |
| `tg_parser/processing/llm/rate_limiter.py` | Token-bucket, suggested_parallel_cap | ⭐⭐ |
| `tg_parser/processing/llm/anthropic_client.py` | AnthropicClient, suggest_processing_concurrency | ⭐⭐ |
| `tg_parser/processing/llm/factory.py` | create_llm_client, resolve_llm_config | ⭐⭐ |
| `tg_parser/processing/topicization.py` | BATCH_CONCURRENCY=5 (hardcoded) | ⭐ |
| `tg_parser/cli/app.py` | CLI --concurrency flag | ⭐ |

---

## Scope Session 31

### 1. Добавить `processing_concurrency` в Settings

Новое поле в `config/settings.py`:
```python
processing_concurrency: int = Field(
    default=5,
    description="Number of parallel LLM requests for processing stage",
    ge=1,
    le=50,
)
```

Это подхватит `PROCESSING_CONCURRENCY=20` из `.env`.

### 2. Пробросить concurrency через всю цепочку

**`services/processing_service.py`:**
- `run_processing()` — default concurrency из `settings.processing_concurrency` вместо hardcoded 1

**`services/pipeline_service.py`:**
- `run_full_pipeline()` — добавить параметр `concurrency: int | None = None` (fallback на settings)
- Передавать в `run_processing(concurrency=...)`

**`services/scheduler_service.py`:**
- `run_incremental_for_all_sources()` — передавать concurrency в `run_full_pipeline()`

**`cli/app.py`:**
- `process` command — default `--concurrency` из settings вместо 1
- `run` command — добавить `--concurrency` флаг

### 3. Интегрировать suggest_processing_concurrency

В `processing/pipeline.py`, перед `_process_batch_parallel`:
```python
if hasattr(self.llm_client, 'suggest_processing_concurrency'):
    concurrency = self.llm_client.suggest_processing_concurrency(concurrency)
```

Это позволит rate limiter автоматически снижать параллелизм при приближении к лимитам.

### 4. Сделать BATCH_CONCURRENCY в topicization конфигурируемым

Добавить `topicization_batch_concurrency` в Settings (default=5), использовать в `topicization.py`.

### 5. Тестирование параллельности

Написать тест, проверяющий что:
- `process_batch(concurrency=5)` вызывает `_process_batch_parallel`
- `run_processing()` использует `settings.processing_concurrency`
- `suggest_processing_concurrency()` корректно ограничивает при низком remaining

---

## Конфигурация

Изменения в `.env`:

```env
# Уже существуют:
PROCESSING_CONCURRENCY=20               # станет рабочим
PROCESSING_RATE_LIMIT_RPM=1000          # работает
PROCESSING_RATE_LIMIT_ITPM=450000       # работает
PROCESSING_RATE_LIMIT_OTPM=90000        # работает

# Новое (опционально):
TOPICIZATION_BATCH_CONCURRENCY=5        # default=5
```

---

## Тестирование

### Ожидаемые сценарии

1. **Processing с concurrency=5** — 5 параллельных LLM запросов, rate limiter не блокирует (1000 RPM / 5 = 200 RPM per slot, запас 5x)
2. **Processing с concurrency=20** — rate limiter адаптивно снижает через suggested_parallel_cap
3. **Scheduler incremental run** — processing этап использует concurrency из settings
4. **CLI `tg-parser process --concurrency 10`** — работает, override settings
5. **CLI `tg-parser run`** — processing с default concurrency из settings

### Верификация на реальном канале

Запустить processing для @labdiagnostica_logical с разной concurrency:
```bash
# Текущее поведение (sequential)
time tg-parser process --channel labdiagnostica_logical --concurrency 1

# Параллельная обработка
time tg-parser process --channel labdiagnostica_logical --concurrency 5
time tg-parser process --channel labdiagnostica_logical --concurrency 10
```

Ожидание: при concurrency=10 обработка в 5-8x быстрее чем sequential (с учётом rate limiting overhead).

**Важно:** для честного бенчмарка нужен `--force` (переобработать всё) или свежие данные, иначе всё будет skipped.

---

## Техническое состояние

### База данных (локальный PostgreSQL)

```
PostgreSQL 16 (Homebrew): localhost:5432/tg_parser
├── sources (1 запись: labdiagnostica, status=active)
├── raw_messages (1130 записей)
├── processed_documents (1128 записей)
├── topic_cards (64 записи)
├── topic_bundles (64 записи)
├── processing_failures (115 записей)
└── source_attempts (11 записей)
```

### LLM конфигурация

```
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514

PROCESSING_LLM_PROVIDER=anthropic
PROCESSING_LLM_MODEL=claude-haiku-4-5-20251001    (для processing)
TOPICIZATION_LLM_PROVIDER=anthropic
TOPICIZATION_LLM_MODEL=claude-sonnet-4-20250514    (для topicization)

# Anthropic Tier 2 rate limits
PROCESSING_RATE_LIMIT_RPM=1000
PROCESSING_RATE_LIMIT_ITPM=450000
PROCESSING_RATE_LIMIT_OTPM=90000
```

### Тесты

```
306 passed, 8 skipped, 2 pre-existing failures
Failing: test_full_pipeline_e2e, test_comments_ingestion_with_per_thread_cursors
```

---

## Ограничения

1. **Anthropic rate limits** — Tier 2: 1000 RPM, 450K ITPM, 90K OTPM. При concurrency=20 и среднем запросе ~2000 input tokens: 20 * 2000 = 40K tokens/batch, далеко до лимита 450K
2. **PostgreSQL connections** — pool_size=5, max_overflow=10. При concurrency=20 все запросы идут через один session — не проблема (DB пишет после LLM)
3. **Обратная совместимость** — `--concurrency 1` должен работать как раньше (sequential path)
4. **Тесты** — существующие тесты не должны ломаться

---

## Критерии завершения Session 31

### Must Have:
- [ ] `processing_concurrency` в Settings, подхватывает `PROCESSING_CONCURRENCY` из .env
- [ ] `run_processing()` использует settings.processing_concurrency как default
- [ ] `run_full_pipeline()` пробрасывает concurrency в processing
- [ ] Scheduler передаёт concurrency через pipeline
- [ ] `suggest_processing_concurrency()` вызывается перед параллельным батчем
- [ ] Существующие тесты проходят

### Should Have:
- [ ] CLI `tg-parser run` принимает `--concurrency`
- [ ] `topicization_batch_concurrency` в Settings (вместо hardcoded 5)
- [ ] Тесты для concurrency pipeline: parallel path, settings integration
- [ ] Бенчмарк: время обработки при concurrency 1 vs 5 vs 10

### Nice to Have:
- [ ] Логирование effective concurrency при старте processing ("Processing with concurrency=10 (suggested=8 by rate limiter)")
- [ ] Metrics: concurrency_effective gauge в Prometheus

---

## Начало работы

1. Изучить документы из раздела "Обязательные документы"
2. Запустить тесты: `.venv/bin/python -m pytest tests/ -q --ignore=tests/test_agents.py --ignore=tests/test_multi_agent.py --ignore=tests/test_gpt5_responses_api.py --ignore=tests/test_llm_clients.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_postgres_integration.py`
3. Начать реализацию: Settings → processing_service → pipeline_service → scheduler_service → CLI
