# Session 28: Per-Stage LLM Provider/Model Routing — Start Prompt

**Дата:** 21 марта 2026  
**Версия:** v3.2.0 → v3.3.0  
**Приоритет:** Medium  
**Оценка:** ~2-3 часа разработки

---

## Цель Session 28

Реализовать возможность использовать **разные LLM-провайдеры и модели на разных стадиях pipeline**. Сейчас один глобальный `LLM_PROVIDER` + `LLM_MODEL` используется везде — и для обработки сообщений (простая задача), и для топикизации (сложная задача). Это приводит к избыточным затратам: дорогая модель (Sonnet) используется там, где достаточно дешёвой (Haiku).

---

## Контекст из Session 27

### Архитектура LLM-вызовов в проекте

В проекте 3 ключевых точки вызова LLM в основном pipeline:

| # | Стадия | Файл | Функция | Сложность задачи |
|---|---|---|---|---|
| 1 | **Обработка сообщений** | `pipeline.py` | `_process_single_message` | Средняя — извлечение text_clean, summary, topics, entities из одного сообщения |
| 2 | **Генерация тем** | `topicization.py` | `_generate_topics_batch` | **Высокая** — кластеризация 50 документов, формирование тем с anchors и scores |
| 3 | **Merge тем** | `topicization.py` | `_merge_topics` | Средняя — дедупликация тем по заголовкам, вывод массивов ID |

Дополнительно есть 3 агентских инструмента в `text_tools.py` (analyze_text_deep, extract_topics_llm, extract_entities_llm) — они используются опционально и не являются приоритетом.

### Рекомендуемые модели по стадиям

```
Сложность     Стадия                       Подходящие модели
─────────────────────────────────────────────────────────────
███████████   Генерация тем (batch 50)     Sonnet, GPT-4o, Gemini Pro
██████░░░░░   Merge тем                    Sonnet, Haiku, GPT-4o-mini
██████░░░░░   Обработка сообщений          Haiku, GPT-4o-mini, Flash
███░░░░░░░░   Агентские инструменты        Любая
```

### Экономический эффект (канал из 1100 сообщений)

| Стадия | Вызовов | Сейчас (всё на Sonnet) | С Haiku для обработки |
|---|---|---|---|
| Обработка | ~1100 | ~$3.85 | **~$0.17** |
| Топикизация | ~25 | ~$2.25 | ~$2.25 (остаётся на Sonnet) |
| **Итого** | | ~$6.10 | **~$2.42** (экономия ~60%) |

### Текущее состояние кода

- Интерфейс `LLMClient` (в `ports.py`) — абстрактный, pipeline'ы не зависят от конкретного провайдера
- `ProcessingPipelineImpl` и `TopicizationPipelineImpl` принимают `llm_client` как аргумент конструктора — никаких изменений в pipeline-коде не требуется
- Фабрика `create_llm_client()` в `factory.py` уже умеет создавать клиент для любого провайдера
- `LLMRateLimiter` в `rate_limiter.py` — адаптивный token-bucket limiter для Anthropic

### Текущие настройки LLM в `.env`

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-api03-...
GEMINI_API_KEY=AIzaSy...
```

---

## Что нужно реализовать

### 1. Новые настройки в `settings.py`

Добавить 4 опциональных поля в класс `Settings` (секция "LLM настройки", строки 119-131):

```python
# Per-stage LLM overrides (fallback to global llm_provider/llm_model)
processing_llm_provider: str | None = None
processing_llm_model: str | None = None
topicization_llm_provider: str | None = None
topicization_llm_model: str | None = None
```

Если не заданы — используется глобальный `llm_provider` / `llm_model` (полная обратная совместимость).

### 2. Helper `resolve_llm_config(stage)` в `factory.py`

Добавить функцию, которая разрешает (provider, api_key, model) для стадии:

```python
def resolve_llm_config(stage: str) -> tuple[str, str | None, str | None]:
    """Return (provider, api_key, model) for 'processing' or 'topicization'.
    
    Falls back to global LLM_PROVIDER/LLM_MODEL when per-stage not set.
    """
```

Логика:
- Прочитать `{stage}_llm_provider` из settings; fallback на `settings.llm_provider`
- Прочитать `{stage}_llm_model` из settings; fallback на `settings.llm_model`
- Определить API key по провайдеру (`openai_api_key`, `anthropic_api_key`, `gemini_api_key`, None для ollama)
- Вернуть кортеж

### 3. Shared rate limiter registry

Лимиты Anthropic — на уровне организации, не модели. Если два клиента (Haiku и Sonnet) используют один API key, они должны делить один `LLMRateLimiter`.

Добавить кеш в `factory.py`:

```python
_rate_limiter_cache: dict[str, LLMRateLimiter] = {}

def _get_or_create_rate_limiter(api_key: str) -> LLMRateLimiter:
    if api_key not in _rate_limiter_cache:
        _rate_limiter_cache[api_key] = LLMRateLimiter.from_settings(app_settings)
    return _rate_limiter_cache[api_key]
```

Использовать в ветке `elif provider == "anthropic"` вместо прямого `LLMRateLimiter.from_settings()`.

### 4. Обновить `create_processing_pipeline()` в `pipeline.py`

В `pipeline.py` строки 575-659 заменить чтение глобальных `settings.llm_provider`/`settings.llm_model` на вызов `resolve_llm_config("processing")`. Изменения ~5 строк.

### 5. Обновить `topicize_cmd.py`

В `topicize_cmd.py` строки 42-54 заменить создание клиента на вызов `resolve_llm_config("topicization")` + `create_llm_client()`. Изменения ~5 строк.

### 6. Обновить `.env` и `.env.example`

Добавить новые переменные:

```env
# Per-stage LLM overrides (optional, fallback to LLM_PROVIDER/LLM_MODEL)
PROCESSING_LLM_PROVIDER=anthropic
PROCESSING_LLM_MODEL=claude-3-5-haiku-20241022
TOPICIZATION_LLM_PROVIDER=anthropic
TOPICIZATION_LLM_MODEL=claude-sonnet-4-20250514
```

### 7. CLI logging

Добавить лог при старте каждой стадии, чтобы пользователь видел какая модель используется:

```
Processing 1122 messages with anthropic/claude-3-5-haiku-20241022
Topicization with anthropic/claude-sonnet-4-20250514
```

### 8. Тесты

- Unit test для `resolve_llm_config()`: проверить fallback на глобальные, per-stage override, mixed-provider сценарии
- Unit test для shared rate limiter: проверить что два вызова с одинаковым API key возвращают один экземпляр

---

## Что НЕ меняется

- `LLMClient` интерфейс (`ports.py`)
- `ProcessingPipelineImpl` — уже принимает `llm_client` как аргумент
- `TopicizationPipelineImpl` — уже принимает `llm_client` как аргумент
- Реализации клиентов: `AnthropicClient`, `OpenAIClient`, `GeminiClient`, `OllamaClient`
- `LLMRateLimiter` — без изменений
- Промпты — без изменений
- Агентские инструменты в `text_tools.py` — пока остаются на глобальных настройках

---

## Файлы для изменения

| Файл | Что меняется |
|---|---|
| `tg_parser/config/settings.py` | +4 новых поля |
| `tg_parser/processing/llm/factory.py` | +`resolve_llm_config()`, +rate limiter cache |
| `tg_parser/processing/pipeline.py` | Использовать `resolve_llm_config("processing")` |
| `tg_parser/cli/topicize_cmd.py` | Использовать `resolve_llm_config("topicization")` |
| `tg_parser/cli/process_cmd.py` | Лог effective model для стадии обработки |
| `.env` / `.env.example` | Новые переменные |
| `tests/test_llm_factory.py` (новый) | Тесты resolve + shared limiter |

---

## Порядок реализации

1. Добавить settings fields
2. Реализовать `resolve_llm_config()` и rate limiter cache в `factory.py`
3. Обновить `create_processing_pipeline()` в `pipeline.py`
4. Обновить `topicize_cmd.py`
5. Обновить `.env` и `.env.example`
6. Добавить logging в CLI
7. Написать тесты
8. Запустить обработку + топикизацию и проверить, что используются разные модели

---

## Верификация

После реализации запустить полный цикл на канале `@labdiagnostica_logical`:

```bash
# 1. Обработка (должна использовать Haiku)
uv run python -m tg_parser.cli process --channel labdiagnostica_logical --concurrency 20

# 2. Топикизация (должна использовать Sonnet)
uv run python -m tg_parser.cli topicize --channel labdiagnostica_logical --force
```

Ожидаемый результат:
- В логах видно разные модели для разных стадий
- Обработка быстрее (Haiku отвечает в 2-3x быстрее)
- Качество топикизации не деградирует (Sonnet как и раньше)
- ~67 тем без дубликатов (как в Session 27)
