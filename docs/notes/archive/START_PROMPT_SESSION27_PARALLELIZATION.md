# Session 27: Параллелизация обработки — Start Prompt

**Дата:** 20 марта 2026  
**Версия:** v3.1.2 → v3.2.0  
**Приоритет:** High  
**Оценка:** ~4-6 часов разработки

---

## Цель Session 27

Реализовать полноценную параллельную обработку сообщений через LLM с адаптивным rate limiting, prompt caching и поддержкой Batch API. Цель — сократить время обработки 1000+ сообщений с ~95 минут до 3-5 минут (при Tier 2 Anthropic).

---

## Контекст из Session 26

### Результаты тестирования

Канал `@labdiagnostica_logical` полностью обработан через Claude Sonnet 4:
- **1122 сообщения** обработаны успешно (99.8%), 2 ошибки
- **35 тем** выделены при топикизации
- Качество Claude значительно выше gpt-4o-mini: topics на русском, более детальные summary

### Текущие тайминги (последовательная обработка)

| Этап | Время | Причина |
|---|---|---|
| Processing (1124 сообщения) | ~95 мин | Последовательные LLM-вызовы по 5-8 сек |
| Topicization (23 батча) | ~35 мин | 65с задержка между батчами (rate limit) |
| Merge + Bundles | ~6 мин | LLM-вызовы для merge и supporting items |

### Текущий тариф Anthropic — Tier 1

| Ресурс | Лимит |
|---|---|
| RPM (requests/min) | 50 |
| ITPM (input tokens/min) | 30,000 |
| OTPM (output tokens/min) | 8,000 |
| Месячный лимит | $100 |

### Лимиты по тарифам Anthropic (Claude Sonnet 4.x)

| Тариф | Стоимость | RPM | ITPM | OTPM |
|---|---|---|---|---|
| Tier 1 | $5 | 50 | 30,000 | 8,000 |
| Tier 2 | $40 | 1,000 | 450,000 | 90,000 |
| Tier 3 | $200 | 2,000 | 800,000 | 160,000 |
| Tier 4 | $400 | 4,000 | 2,000,000 | 400,000 |

### Расчёт ожидаемого ускорения

| Тариф | Макс. параллелизм (N) | Время processing | Ускорение |
|---|---|---|---|
| Tier 1, N=1 (сейчас) | 1 | ~95 мин | 1x |
| Tier 1, N=3 | 3 | ~32 мин | 3x |
| Tier 2, N=20-30 | 30 | ~3-5 мин | 20-30x |
| Tier 3, N=50 | 50 | ~2 мин | 47x |

---

## Текущее состояние кода

### Что УЖЕ реализовано

#### 1. Базовая параллелизация в pipeline.py (заготовка)

Файл `tg_parser/processing/pipeline.py` уже содержит:
- `process_batch(messages, force, concurrency)` — диспетчер (строка ~455)
- `_process_batch_sequential(messages, force)` — последовательный цикл (строка ~496)
- `_process_batch_parallel(messages, force, concurrency)` — параллельный через `asyncio.Semaphore` + `asyncio.gather` (строка ~522)

```python
async def _process_batch_parallel(self, messages, force=False, concurrency=5):
    semaphore = asyncio.Semaphore(concurrency)
    
    async def process_with_semaphore(message):
        async with semaphore:
            try:
                return await self.process_message(message, force=force)
            except Exception as e:
                # ...log and continue
                return None
    
    tasks = [process_with_semaphore(msg) for msg in messages]
    completed_results = await asyncio.gather(*tasks)
    return [r for r in completed_results if r is not None]
```

#### 2. CLI поддержка `--concurrency`

Файл `tg_parser/cli/app.py` (строка ~153):
```
--concurrency / -c : Parallel requests (default: 1)
```

Передаётся в `process_cmd.py` → `pipeline.process_batch(concurrency=N)`.

#### 3. Multi-LLM Factory

Файл `tg_parser/processing/llm/factory.py` — фабрика LLM-клиентов (openai/anthropic/gemini/ollama).

#### 4. Anthropic Client

Файл `tg_parser/processing/llm/anthropic_client.py`:
- Использует один `httpx.AsyncClient` (до 100 одновременных соединений по умолчанию)
- Нет retry при 429 (rate limit) — retry только на уровне `process_message`
- Не поддерживает prompt caching

#### 5. Topicization с батчингом и retry

Файл `tg_parser/processing/topicization.py`:
- `BATCH_SIZE = 50`, `BATCH_DELAY_SECONDS = 65`
- Retry при 429 с экспоненциальной задержкой
- `extract_json_from_response` для обработки markdown-wrapped JSON от Claude

---

## Что НУЖНО реализовать

### 1. Адаптивный Rate Limiter (основная задача)

Создать `RateLimiter` класс на базе token bucket, который:
- Отслеживает RPM, ITPM, OTPM лимиты
- Автоматически определяет лимиты из response headers Anthropic:
  - `anthropic-ratelimit-requests-remaining`
  - `anthropic-ratelimit-input-tokens-remaining`
  - `anthropic-ratelimit-output-tokens-remaining`
  - `retry-after`
- Адаптивно регулирует concurrency: снижает при приближении к лимиту, повышает при свободных ресурсах
- Интегрируется с существующим `AnthropicClient` и `OpenAIClient`

Предлагаемое расположение: `tg_parser/processing/llm/rate_limiter.py`

### 2. Настройка concurrency через .env

Добавить в `tg_parser/config/settings.py`:
```python
processing_concurrency: int = 1  # Параллельные LLM-запросы
processing_rate_limit_rpm: int | None = None  # Авто-определение если None
processing_rate_limit_itpm: int | None = None
processing_rate_limit_otpm: int | None = None
```

### 3. Prompt Caching для Anthropic

Anthropic поддерживает prompt caching — кэшированные input tokens **не считаются** в ITPM rate limit (для Sonnet 4.x). System prompt + template (~700 tokens) одинаковы для каждого сообщения.

Реализовать в `AnthropicClient`:
- Добавить cache control headers для system prompt
- Это снижает эффективный ITPM на ~60%, позволяя увеличить concurrency в ~2.5x при том же тарифе

Документация: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching

### 4. Retry с учётом rate limit headers

Улучшить retry в `AnthropicClient.generate()`:
- При 429 использовать `retry-after` header вместо фиксированной задержки
- Логировать оставшиеся tokens/requests из response headers

### 5. Обновление topicization rate limiting

Заменить фиксированные `BATCH_DELAY_SECONDS = 65` на адаптивный rate limiter:
- Использовать тот же `RateLimiter` что и для processing
- Задержка определяется динамически по остатку токенов

### 6. (Опционально) Message Batches API

Anthropic предлагает Batch API для асинхронной обработки:
- До 10,000 запросов в одном батче
- Стоимость на 50% ниже
- Обработка обычно в течение 1 часа (гарантия 24 часа)
- Нет rate limit ограничений

Это альтернатива real-time параллелизации для полной переобработки канала. Может быть реализовано как отдельная CLI команда `process --batch-mode`.

---

## Ключевые файлы для изменений

| Файл | Что менять |
|---|---|
| `tg_parser/processing/llm/rate_limiter.py` | **Новый** — адаптивный rate limiter |
| `tg_parser/processing/llm/anthropic_client.py` | Prompt caching, retry с headers, интеграция rate limiter |
| `tg_parser/processing/llm/openai_client.py` | Интеграция rate limiter (опционально) |
| `tg_parser/processing/pipeline.py` | Передача rate limiter в parallel batch |
| `tg_parser/processing/topicization.py` | Адаптивный rate limiting вместо фиксированных задержек |
| `tg_parser/config/settings.py` | Новые настройки concurrency и rate limits |
| `tg_parser/cli/app.py` | Дефолт concurrency из settings |

---

## Порядок реализации

### Этап 1: Rate Limiter + базовая параллелизация
1. Создать `RateLimiter` с token bucket алгоритмом
2. Добавить настройки concurrency в settings
3. Интегрировать rate limiter в `AnthropicClient`
4. Протестировать `process --concurrency 3` на текущем Tier 1

### Этап 2: Prompt Caching
5. Реализовать prompt caching в `AnthropicClient`
6. Протестировать снижение ITPM и увеличение эффективного throughput

### Этап 3: Адаптивный topicization
7. Заменить фиксированные задержки в topicization на rate limiter
8. Протестировать полный pipeline (process + topicize) с параллелизацией

### Этап 4 (опционально): Batch API
9. Реализовать Anthropic Message Batches API
10. Добавить CLI команду `process --batch-mode`

---

## Тестирование

### Функциональное
- Обработка 50 сообщений с `--concurrency 3` (Tier 1)
- Проверка корректности: результаты идентичны последовательной обработке
- Rate limiter корректно ограничивает запросы при приближении к лимиту

### Нагрузочное (при наличии Tier 2+)
- Обработка 1124 сообщений с `--concurrency 20`
- Замер времени и сравнение с baseline (~95 мин)
- Мониторинг rate limit headers и отсутствия 429 ошибок

### Регрессионное
- Все существующие тесты проходят
- Последовательная обработка (`--concurrency 1`) работает как прежде

---

## Зависимости и ограничения

- **Тариф Anthropic**: Tier 1 ($5) — максимум N=3. Для полноценного тестирования нужен Tier 2 ($40).
- **DB Pool**: Текущий `db_pool_size=5, max_overflow=10` (15 соединений) — достаточно для N=30.
- **httpx**: Дефолтный пул — 100 соединений, без изменений хватит.
- **Prompt Caching**: Требует `anthropic-version >= 2023-06-01` (уже используется) и специальных cache control блоков в API запросе.
