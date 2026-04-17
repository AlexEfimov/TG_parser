# F8-A: Hardening — Стартовый промпт

**Версия проекта:** 4.3.0+ (post Wave 1.5)  
**Предыдущая сессия:** Wave 1.5 (RAG & Prompt Config — все 6 фаз)  
**Зафиксированная последовательность:** Wave 1.5 ✅ → **F8-A** → F5-A

---

## Цель сессии

Завершить Level A Hardening: добавить 5xx retry в Anthropic и Ollama клиенты, обогатить `/health` реальной проверкой БД, исправить двойной подсчёт метрики scheduler, документировать connection pool tuning. Большинство пунктов F8-A уже реализовано — осталось 5 конкретных задач.

---

## Контекст: текущее состояние F8-A

### Что уже сделано (56 тестов в `tests/test_f8a_hardening.py`)

| Шаг из Level A | Статус | Тесты |
|-----------------|--------|-------|
| 1. Unified retry: OpenAI 429/5xx + exponential backoff | ✅ DONE | `TestOpenAIRetry` (14) |
| 1. Unified retry: Gemini 429/5xx + exponential backoff | ✅ DONE | `TestGeminiRetry` (11) |
| 2. Wire `rate_limit_until` в ingestion | ✅ DONE | `TestIngestionRateLimit` (7) |
| 3. DB pool metrics: `DB_CONNECTIONS_ACTIVE` checkout/checkin | ✅ DONE | `TestDBPoolMetrics` (1) |
| 4. Fix duplicate processing engine в JobStore | ✅ DONE | `TestJobStoreSharedEngine` (3) |
| 5. Bot healthcheck: HTTP probe на порту 8081 | ✅ DONE | `TestBotHealthServer` (1) |
| 7. LLM response cache (in-memory TTL) | ✅ DONE | `TestLLMResponseCache` (13), `TestInstrumentedCacheIntegration` (3) |
| Factory retry wiring | ✅ DONE | `TestFactoryRetryWiring` (3) |

### Что НЕ сделано (gaps)

| Gap | Проблема |
|-----|----------|
| **Anthropic 5xx retry** | `AnthropicClient.generate_with_usage()` ретраит **только 429**. Статусы 500/502/503/529 вызывают `raise_for_status()` без retry. OpenAI и Gemini уже ретраят все эти статусы. |
| **Ollama retry** | `OllamaClient.generate()` — один POST без retry вообще. Сетевые ошибки и 5xx не обрабатываются. |
| **`/health` без проверки БД** | `GET /health` возвращает статический `{"status": "ok"}` без проверки DB. Kubernetes/Docker probes не детектят отказ базы. |
| **Двойной подсчёт метрики scheduler** | `incremental_pipeline_task()` вызывает `record_scheduler_task()` в `finally`, но `BackgroundScheduler.add_task()` тоже оборачивает каждую задачу вызовом `record_scheduler_task()`. Метрика `incremental_pipeline` считается дважды за запуск. |
| **Connection pool документация** | Нет документации формулы `replicas × pools × (size + overflow) < pg max_connections`. |

---

## План реализации (5 фаз)

### Phase 1: Add 5xx retry to Anthropic client

**Файл:** `tg_parser/processing/llm/anthropic_client.py`

Текущая структура retry в `generate_with_usage()` (строка ~134):
```python
for attempt in range(1, self._max_retries_429 + 1):
    ...
    if response.status_code == 429:   # ← только 429
        retry_after = _parse_retry_after_seconds(response)
        ...
        await asyncio.sleep(retry_after)
        continue
    response.raise_for_status()       # ← 500/502/503 сразу raise
```

Изменения:
1. Добавить константу `_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}` (как в `gemini_client.py`)
2. Переименовать `_max_retries_429` → `_max_retries` (конструктор + factory)
3. В retry loop: заменить `if response.status_code == 429:` на `if response.status_code in _RETRYABLE_STATUS_CODES:`
4. Для **429**: сохранить текущую логику (`_parse_retry_after_seconds` + rate limiter refund)
5. Для **5xx**: использовать exponential backoff `min(2 ** attempt, 60) + jitter` (как в Gemini `_compute_delay`)
6. В `except httpx.HTTPStatusError`: расширить retry ветку на все `_RETRYABLE_STATUS_CODES`
7. Rate limiter: `refund_acquire` при любом retryable (не только 429)

**Не трогаем:**
- `_parse_retry_after_seconds()` — работает корректно для 429
- Rate limiter integration — только расширяем refund на все retryable
- `generate()` — делегирует в `generate_with_usage()`

### Phase 2: Add retry to Ollama client

**Файл:** `tg_parser/processing/llm/ollama_client.py`

Текущая структура — один POST без retry:
```python
async def generate(self, prompt, ...):
    response = await self._client.post(url, json=payload)
    response.raise_for_status()
    ...
```

Изменения:
1. Добавить `_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}` (как в Gemini)
2. Добавить `max_retries: int = 5` в конструктор → `self._max_retries`
3. Обернуть POST в retry loop (по образцу `gemini_client.py`):
   - Retryable HTTP статусы: `min(2 ** attempt, 60) + jitter`
   - Network errors (`httpx.HTTPError`): `min(2 ** attempt + jitter, 60)`
   - Parse errors (`json.JSONDecodeError`, `ValueError`): НЕ ретраить
4. Обновить factory (`factory.py`): передавать `max_retries` из kwargs (default 5, как для OpenAI/Gemini)

**Эталон:** `gemini_client.py` lines 108-175 — полная retry loop с `_compute_delay`

### Phase 3: Enrich `/health` with DB ping

**Файл:** `tg_parser/api/routes/health.py`

Текущий handler (строка ~25):
```python
@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.pipeline_version_processing,
        timestamp=datetime.now(UTC),
    )
```

Изменения:
1. Добавить быструю проверку `SELECT 1` через `Database.get_instance()` с коротким timeout (~3s)
2. При успехе: `status="ok"`
3. При ошибке DB: `status="degraded"` (NOT "error" — endpoint должен возвращать HTTP 200 для корректной работы load balancer)
4. Обернуть в `try/except` — при любой ошибке не ломать endpoint

**Не трогаем:**
- `/status` — уже делает полную проверку через `check_all_components()`
- `/status/detailed` — уже защищён API key
- `HealthResponse` модель — может потребоваться добавить optional `database` field

### Phase 4: Fix double-counted scheduler metric

**Файл:** `tg_parser/services/scheduler_service.py`

Текущая проблема (строка ~335):
```python
async def incremental_pipeline_task() -> dict:
    success = True
    try:
        result = await run_incremental_for_all_sources()
    except Exception:
        success = False
        raise
    finally:
        record_scheduler_task(task_name="incremental_pipeline", success=success)  # ← дубль!
```

Но `BackgroundScheduler.add_task()` уже оборачивает каждую задачу:
```python
async def wrapped_func() -> None:
    try:
        await func(**kwargs)
        record_scheduler_task(task_id, success=True)   # ← первый вызов
    except Exception:
        record_scheduler_task(task_id, success=False)   # ← первый вызов
```

**Исправление:** Удалить `record_scheduler_task` из `incremental_pipeline_task()` (строки ~341, ~351). Wrapper в `add_task` уже делает это корректно.

### Phase 5: Connection pool tuning documentation + Tests

**Файл (документация):** `docs/USER_GUIDE.md` — новая секция "Connection Pool Tuning" рядом с "Database Setup"

Содержание:
- 3 engine pools: `ingestion`, `raw`, `processing` (DB_POOL_SIZE + DB_MAX_OVERFLOW каждый)
- Формула: `replicas × 3 × (pool_size + max_overflow) < pg max_connections`
- Defaults: `pool_size=5`, `max_overflow=10` → 1 process = 3 × 15 = 45 connections
- PostgreSQL default `max_connections=100` → safe for 1-2 processes

**Файл (тесты):** `tests/test_f8a_hardening.py` — новые тест-классы:

| Класс | Тестов | Покрытие |
|-------|--------|----------|
| `TestAnthropicRetry` | ~8 | 429 retry (уже работает), 500 retry, 502 retry, exhaustion raises, 400 not retried, network error retry, `_parse_retry_after` |
| `TestOllamaRetry` | ~6 | success no retry, 500 retry, network error retry, exhaustion raises, 400 not retried, parse error not retried |
| `TestHealthDBPing` | ~3 | healthy (DB ok), degraded (DB unreachable), returns 200 in both cases |
| `TestSchedulerMetricNotDoubled` | ~2 | incremental_pipeline_task does NOT call record_scheduler_task; wrapper calls it once |

---

## Ключевые файлы для изучения

| Файл | Назначение |
|------|-----------|
| `tg_parser/processing/llm/anthropic_client.py` | Anthropic LLM client — **основной target Phase 1** |
| `tg_parser/processing/llm/ollama_client.py` | Ollama LLM client — **основной target Phase 2** |
| `tg_parser/processing/llm/gemini_client.py` | **Эталон** retry loop + `_compute_delay` + `_RETRYABLE_STATUS_CODES` |
| `tg_parser/processing/llm/openai_client.py` | Второй эталон retry (`_request_with_retry`, `_parse_retry_after`) |
| `tg_parser/processing/llm/factory.py` | Factory — обновить kwargs для Anthropic (rename) и Ollama (добавить max_retries) |
| `tg_parser/api/routes/health.py` | `/health` endpoint — **target Phase 3** |
| `tg_parser/api/schemas.py` | `HealthResponse` model (может потребоваться расширение) |
| `tg_parser/storage/sqlalchemy/database.py` | `Database.get_instance()` для DB ping |
| `tg_parser/services/scheduler_service.py` | `incremental_pipeline_task()` — **target Phase 4** |
| `tg_parser/services/background_scheduler.py` | `add_task` wrapper с `record_scheduler_task` |
| `tests/test_f8a_hardening.py` | Существующие 56 тестов — **расширить** |

---

## Что НЕ входит в scope

- **Circuit breaker / provider failover** — Level C (3+ сессий), требует архитектурных изменений
- **Graceful degradation** (частичные ответы) — Level B/C
- **Redis caching / task queue** — Level B
- **Pool wait-time histograms в Prometheus** — nice-to-have, не в Level A
- **Horizontal scaling** — Level C
- **Processing pipeline retry** (`pipeline.py`) — уже работает через `retry_settings`
- **Topicization JSON retry** — уже работает (3 attempts, `llm_json_retry_delay`)

---

## Критерии завершённости

1. `AnthropicClient` ретраит 500/502/503/529 с exponential backoff (по аналогии с Gemini)
2. `OllamaClient` ретраит network errors и 5xx с exponential backoff
3. `GET /health` возвращает `"degraded"` при недоступной БД (HTTP 200)
4. Метрика `incremental_pipeline` не считается дважды за запуск
5. Документация connection pool tuning добавлена в USER_GUIDE.md
6. Все существующие тесты проходят + новые тесты для gaps
7. Factory передаёт `max_retries` в Anthropic и Ollama

---

## Тесты

Запуск тестов:
```bash
.venv/bin/pytest tests/ -x -q
# Или с PostgreSQL integration:
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

Текущее состояние: **1213+ тестов** (post Wave 1.5), все проходят.
F8-A тесты: **56 тестов** в `tests/test_f8a_hardening.py` — расширить до ~75.
