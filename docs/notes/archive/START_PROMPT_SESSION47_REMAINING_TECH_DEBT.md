# Session 47: Оставшийся технический долг (перед P6)

**Дата:** [дата запуска]  
**Тип сессии:** Tech Debt — Remaining Items  
**Предыдущая сессия:** Session 46 (DI Refactoring)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md` → §"Оставшийся технический долг"  
**Закрытый план:** `docs/notes/TECH_DEBT_CLOSURE_PLAN.md` (Sessions 43-45 + 46)

---

## Цель сессии

Закрыть все оставшиеся пункты технического долга из `DEVELOPMENT_ROADMAP.md` перед началом P6 (Веб-интерфейс). Четыре задачи: расширение `LLMClient.generate()` для возврата token usage, batch splitting в инкрементальной топикизации при >50 документов, устранение прямых чтений global config из `processing/`, удаление `api/scheduler.py` re-export shim.

---

## Контекст проекта

### Текущее состояние (после Session 46)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17.9 (Docker: `pgvector/pgvector:pg17`), pgvector 0.8.2
- **Тесты:** 571 passed, 16 skipped, 0 failures
- **Последний коммит:** `2157e5d` (Sessions 44-46)
- **DI:** Реализован для 14 сервисных функций через optional repo-параметры + `AsyncExitStack`
- **db_context.py:** 7 async context managers (включая `export_repos()`), все с корректным init() error handling

### Что закрыто в Sessions 43-46

- Session 43: `.env` шаблоны, `pyproject.toml` синхронизация, Dockerfile, `.gitignore`, CI
- Session 44: Ruff/type-hint исправления, DB schema imports, settings, CLI
- Session 45: Migration тесты, RAG route тесты, contract/json_utils тесты, перемещение файлов, USER_GUIDE
- Session 46: DI в 14 сервисных функциях, `export_repos()` CM, init() handling, dead imports, abstract ports

---

## Задачи

### T1: Расширить `LLMClient.generate()` для возврата token usage (MEDIUM)

**Проблема:** `IncrementalTopicizeResult.tokens_used` всегда `= 0`. LLM-клиенты получают usage из API response, но `generate()` возвращает только `str` (текст ответа). Информация о потреблённых токенах теряется.

**Текущий интерфейс (`processing/ports.py`):**

```python
class LLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt, system_prompt, temperature, max_tokens, response_format) -> str:
```

**Текущий `IncrementalTopicizeResult` (`domain/models.py`):**

```python
class IncrementalTopicizeResult(BaseModel):
    ...
    tokens_used: int = 0  # ← всегда 0
```

**Два места где `tokens_used=0` захардкожен (`topicization_service.py`):**
- Строка ~238 (в `run_incremental_topicization`)
- Строка ~373 (в `_run_assign_only`) — здесь `0` корректен (нет LLM вызовов)

**Текущее состояние по провайдерам:**

| Провайдер | Usage в API response | Текущий код |
|-----------|---------------------|-------------|
| **Anthropic** (`anthropic_client.py`) | `data["usage"]["input_tokens"]` + `output_tokens` | Читает для rate limiter reconciliation + logging, но не возвращает |
| **OpenAI** (`openai_client.py`) | `response_data["usage"]["prompt_tokens"]` + `completion_tokens` + `total_tokens` | Не читает вообще |
| **Gemini** (`gemini_client.py`) | `usageMetadata.promptTokenCount` + `candidatesTokenCount` + `totalTokenCount` | Не читает |
| **Ollama** (`ollama_client.py`) | `response_data.get("eval_count")`, `prompt_eval_count` | Не читает |

**Решение — dataclass `LLMResponse`:**

1. Создать `LLMResponse` в `processing/ports.py`:

```python
from dataclasses import dataclass, field

@dataclass
class LLMResponse:
    """Result of an LLM generation call, including token usage metadata."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
```

2. Изменить сигнатуру `LLMClient`:

```python
class LLMClient(ABC):
    @abstractmethod
    async def generate(self, ...) -> str:
        """..."""

    async def generate_with_usage(self, ...) -> LLMResponse:
        """Generate with token usage tracking. Default: delegates to generate()."""
        text = await self.generate(...)
        return LLMResponse(text=text)
```

**Важно:** `generate()` остаётся для обратной совместимости — 50+ call-sites используют `str` return. Новый `generate_with_usage()` — opt-in метод. Default-реализация в базовом классе позволяет не менять Ollama/Gemini если не нужно.

3. Реализовать `generate_with_usage()` в клиентах:

- **`OpenAIClient`**: извлечь `usage.prompt_tokens`, `usage.completion_tokens` из response_data
- **`AnthropicClient`**: использовать уже парсящийся `data["usage"]`
- **`GeminiClient`**: извлечь `usageMetadata`
- **`OllamaClient`**: наследовать default (или извлечь `eval_count`/`prompt_eval_count`)

4. В `topicization.py` → `discover_new_topics()`:
   - Заменить `await self.llm_client.generate(...)` → `await self.llm_client.generate_with_usage(...)`
   - Вернуть `total_tokens` из метода (добавить в return tuple или отдельный атрибут)

5. В `topicization_service.py` → `run_incremental_topicization()`:
   - Получить `tokens_used` из результата `discover_new_topics`
   - Передать в `IncrementalTopicizeResult(tokens_used=actual_tokens)`

**Файлы для изменения:**

| Файл | Изменение |
|------|-----------|
| `processing/ports.py` | `LLMResponse` dataclass + `generate_with_usage()` method |
| `processing/llm/openai_client.py` | Override `generate_with_usage()` — parse usage from response |
| `processing/llm/anthropic_client.py` | Override `generate_with_usage()` — use existing usage parsing |
| `processing/llm/gemini_client.py` | Override `generate_with_usage()` — parse `usageMetadata` |
| `processing/llm/ollama_client.py` | Опционально — или наследовать default |
| `processing/topicization.py` | `discover_new_topics()` → использовать `generate_with_usage()`, вернуть tokens |
| `services/topicization_service.py` | Прокинуть `tokens_used` в `IncrementalTopicizeResult` |
| `domain/models.py` | Без изменений (поле уже есть) |

**Тесты:**
- Unit-тест: mock LLM client → `generate_with_usage()` возвращает `LLMResponse(text=..., input_tokens=100, output_tokens=50)` → проверить `tokens_used=150` в результате
- Проверить, что существующие тесты `generate()` не сломались

---

### T2: Batch splitting для `--mode incremental` (MEDIUM)

**Проблема:** `discover_new_topics()` отправляет все unassigned документы одним LLM-запросом. При ~255 uncovered docs в текущем канале промпт может быть слишком длинным для LLM context window или давать некачественные результаты.

**Текущий flow (`topicization_service.py` → `topicization.py`):**

```
run_incremental_topicization(channel_id, new_doc_refs)
  → pipeline.assign_documents_to_topics(new_docs)  # Phase 1: keyword, OK for any size
  → pipeline.discover_new_topics(channel_id, unassigned_docs)  # Phase 2: SINGLE LLM call
```

**Текущий код (`topicization.py`, строка ~853):**

```python
async def discover_new_topics(self, channel_id, unassigned_docs):
    # ... builds prompt from ALL unassigned_docs at once ...
    docs_payload = [{"source_ref": ..., "summary": ..., "topics": ..., "text_clean": ...} for doc in unassigned_docs]
    prompt = build_incremental_discover_prompt(existing_topics, docs_payload)
    response = await self.llm_client.generate(prompt=prompt, ...)
```

**Решение — batch splitting в `discover_new_topics()`:**

1. Добавить параметр `batch_size: int = 50` в `discover_new_topics()`:

```python
async def discover_new_topics(
    self,
    channel_id: str,
    unassigned_docs: list,
    batch_size: int = 50,
) -> tuple[list[TopicAssignment], list[TopicCard], list[str]]:
```

2. Если `len(unassigned_docs) > batch_size`:
   - Разбить на батчи по `batch_size`
   - Каждый батч обработать отдельным LLM-вызовом
   - Агрегировать результаты: merge assignments + new_topic_cards + unassignable
   - **Важно:** между батчами обновить `existing_topics` — новые темы из предыдущего батча добавляются в список существующих для следующего батча (чтобы не создавать дубликаты)

3. Добавить настройку `topicization_batch_size` в `config/settings.py` (default: `50`).

4. Прокинуть из `topicization_service.py`:
   - `run_incremental_topicization()` → `discover_new_topics(batch_size=settings.topicization_batch_size)`
   - `run_incremental_topicization_for_uncovered()` → через `run_incremental_topicization()`

**Файлы для изменения:**

| Файл | Изменение |
|------|-----------|
| `processing/topicization.py` | `discover_new_topics()` — batch loop, merge results |
| `config/settings.py` | `topicization_batch_size: int = 50` |
| `services/topicization_service.py` | Прокинуть `batch_size` из settings |

**Тесты:**
- Unit-тест: 120 mock docs, batch_size=50 → 3 LLM calls, results correctly merged
- Unit-тест: 30 mock docs, batch_size=50 → 1 LLM call (no splitting)
- Убедиться, что `new_topic_cards` из batch 1 видны как existing topics в batch 2

---

### T3: Устранить прямые чтения global config из `processing/` (LOW)

**Проблема:** 3 файла в `processing/` импортируют и читают `settings` на уровне модуля или в конструкторах. Это затрудняет тестирование и нарушает принцип DI.

**Текущее состояние:**

| Файл | Использование `settings` | Сложность |
|------|--------------------------|-----------|
| `processing/topicization.py` | 9 module-level constants (строки 42-50) + 2 reads в `__init__` и `topicize_channel` | Средняя |
| `processing/pipeline.py` | 1 read в `__init__` (`settings.pipeline_version_processing`) + 3 reads в `_make_llm_call` (temperature, max_tokens) + 1 read в `create_processing_pipeline` | Средняя |
| `processing/llm/openai_client.py` | 1 read в `__init__` (`settings.openai_base_url` as fallback) | Низкая |

**Файл `processing/llm/factory.py`** — уже имеет DI: принимает `settings: Any = None` с lazy import fallback. Это целевой паттерн.

**Решение:**

#### T3a: `openai_client.py` (простой)

`base_url` уже передаётся через `__init__` параметр. Единственная проблема:

```python
# Строка 48
self.base_url = base_url or settings.openai_base_url
```

**Fix:** Удалить import `settings`, заменить fallback на `base_url or "https://api.openai.com/v1"` (значение из settings default). Caller (`factory.py:create_llm_client`) уже может передать `base_url` через параметр.

#### T3b: `pipeline.py` (средний)

Три категории чтений:
1. `settings.pipeline_version_processing` в `__init__` → передаётся через `pipeline_version` параметр. **Fix:** default → `"v1.0"` (текущий settings default).
2. `settings.llm_temperature`, `settings.llm_max_tokens` в `_make_llm_call` → **Fix:** передать через `__init__` или сохранить как атрибуты.
3. `create_processing_pipeline()` (строка ~762): `app_settings.llm_base_url`, `app_settings.llm_reasoning_effort`, `app_settings.llm_verbosity` → **Fix:** принимать `settings` parameter с lazy fallback (как в `factory.py`).

#### T3c: `topicization.py` (сложный)

9 module-level констант из settings (строки 42-50):

```python
MIN_SINGLETON_SCORE = settings.topicization_singleton_min_score
MIN_SINGLETON_LENGTH = settings.topicization_singleton_min_len
# ... ещё 6 ...
TEXT_CLEAN_MATCH_CHARS = settings.topicization_text_clean_match_chars
```

Плюс 2 чтения в runtime:
- `settings.pipeline_version_topicization` в `__init__` (строка 87)
- `settings.topicization_batch_concurrency` в `topicize_channel` (строка 170)

**Fix:** 
1. Module-level constants → оставить как есть (они read-once на import, подменяются в тестах через `patch`). Альтернатива: перенести в `__init__` как параметры с defaults — но это слишком инвазивно для 9 параметров.
2. Runtime чтения → параметры `__init__` с defaults.

**Рекомендация:** Для T3c принять прагматичный подход — module-level constants допустимы, они являются конфигурационными defaults, читаются один раз. Сфокусироваться на T3a и T3b, для T3c — только runtime чтения.

**Файлы для изменения:**

| Файл | Изменение |
|------|-----------|
| `processing/llm/openai_client.py` | Убрать `import settings`, hardcoded default для `base_url` |
| `processing/pipeline.py` | Параметры `__init__` для temperature/max_tokens, `settings` parameter в `create_processing_pipeline` |
| `processing/topicization.py` | Параметры `__init__` для `pipeline_version` и `batch_concurrency`, module-level constants оставить |

**Тесты:**
- Убедиться, что существующие тесты pipeline и topicization проходят
- Новый тест: создать `ProcessingPipelineImpl(llm_client=mock, ..., temperature=0.5)` → проверить, что параметр используется

---

### T4: Удалить `api/scheduler.py` re-export shim (LOW)

**Проблема:** `api/scheduler.py` — шим обратной совместимости, созданный в Session 39. Реальный код в `services/background_scheduler.py` и `services/scheduler_service.py`.

**Текущее содержимое (`api/scheduler.py`, 18 строк):**

```python
"""Backward-compatibility shim — real code lives in services/background_scheduler.py."""
from tg_parser.services.background_scheduler import (  # noqa: F401
    BackgroundScheduler, cleanup_expired_records, get_scheduler,
    health_check_task, setup_default_tasks,
)
from tg_parser.services.scheduler_service import (  # noqa: F401
    incremental_pipeline_task,
)
```

**Текущие импортёры (5 файлов, ~12 import-строк):**

| Файл | Import | Заменить на |
|------|--------|-------------|
| `api/main.py:140` | `from tg_parser.api.scheduler import get_scheduler, setup_default_tasks` | `from tg_parser.services.background_scheduler import ...` |
| `api/routes/health.py:17` | `from tg_parser.api.scheduler import get_scheduler` | `from tg_parser.services.background_scheduler import get_scheduler` |
| `api/health_checks.py:248` | `from tg_parser.api.scheduler import get_scheduler` | `from tg_parser.services.background_scheduler import get_scheduler` |
| `tests/test_phase3d_advanced.py` | 7 строк `from tg_parser.api.scheduler import ...` | `from tg_parser.services.background_scheduler import ...` |
| `tests/test_scheduler_service.py:292,307` | 2 строки `from tg_parser.api.scheduler import ...` | `from tg_parser.services.{background_scheduler,scheduler_service} import ...` |

**Решение:**
1. Обновить все 12 import-строк в 5 файлах (заменить `api.scheduler` → `services.background_scheduler` / `services.scheduler_service`)
2. Удалить файл `tg_parser/api/scheduler.py`
3. Если есть `@patch("tg_parser.api.scheduler.*")` в тестах — обновить пути

**Файлы для изменения:**

| Файл | Изменение |
|------|-----------|
| `api/main.py` | Обновить import |
| `api/routes/health.py` | Обновить import |
| `api/health_checks.py` | Обновить import |
| `tests/test_phase3d_advanced.py` | Обновить 7 imports |
| `tests/test_scheduler_service.py` | Обновить 2 imports + patch paths |
| `api/scheduler.py` | **Удалить** |

**Тесты:**
- Все scheduler-тесты проходят
- `grep -r "api.scheduler" tg_parser/ tests/` — 0 результатов (кроме docs/notes)

---

## Порядок выполнения

| # | Задача | Файлы | Риск | Оценка |
|---|--------|-------|------|--------|
| 1 | T4: Удалить `api/scheduler.py` shim | 6 файлов | Низкий | Простая замена imports |
| 2 | T3: Global config в `processing/` | 3 файла | Средний | DI параметры в конструкторы |
| 3 | T1: `LLMResponse` + `generate_with_usage()` | 7 файлов | Средний | Новый метод в 4 клиентах |
| 4 | T2: Batch splitting для discover_new_topics | 3 файла | Средний | Batch loop + merge logic |
| 5 | Тесты | — | — | Полный тест-сьют |

**Совет:** T4 — самая простая, начать с неё. T3 — независима от T1/T2. T1 и T2 могут зависеть друг от друга (если T2 хочет суммировать tokens — нужен T1), поэтому T1 → T2.

---

## Критерии завершения

- [ ] `api/scheduler.py` удалён, все импорты обновлены на `services/background_scheduler` / `services/scheduler_service`
- [ ] `processing/llm/openai_client.py` не импортирует `settings` напрямую
- [ ] `processing/pipeline.py` — temperature, max_tokens передаются через параметры, не через global settings в runtime
- [ ] `LLMResponse` dataclass в `processing/ports.py`
- [ ] `generate_with_usage()` реализован минимум в OpenAI и Anthropic клиентах
- [ ] `IncrementalTopicizeResult.tokens_used` заполняется реальными данными после `discover_new_topics()`
- [ ] `discover_new_topics()` поддерживает batch splitting при `len(docs) > batch_size`
- [ ] Настройка `topicization_batch_size` в `config/settings.py`
- [ ] Все 571+ тестов + новые тесты проходят
- [ ] Технический коммит

---

## Справка по файлам

### LLM клиенты (`processing/llm/`)

```
openai_client.py      — OpenAIClient: Chat Completions + Responses API (GPT-5), httpx
anthropic_client.py   — AnthropicClient: Messages API, rate limiter, prompt caching
gemini_client.py      — GeminiClient: REST API generativelanguage.googleapis.com
ollama_client.py      — OllamaClient: OpenAI-compatible localhost API
factory.py            — create_llm_client(), resolve_llm_config() — уже с DI для settings
rate_limiter.py       — LLMRateLimiter: token bucket с reconcile_usage()
```

### Ключевые порты (`processing/ports.py`)

```python
class LLMClient(ABC):
    async def generate(prompt, system_prompt, temperature, max_tokens, response_format) -> str

class ProcessingPipeline(ABC):
    async def process_message(message, force) -> ProcessedDocument
    async def process_batch(messages, force) -> list[ProcessedDocument]

class TopicizationPipeline(ABC):
    async def topicize_channel(channel_id, force) -> list[TopicCard]
    async def build_topic_bundle(topic_card, channel_id) -> TopicBundle
```

### Config settings (relevant)

```python
# config/settings.py — relevant fields
topicization_singleton_min_score: float = 0.3
topicization_singleton_min_len: int = 3
topicization_cluster_min_anchor_score: float = 0.25
topicization_supporting_min_score: float = 0.15
topicization_max_supporting_items: int = 20
topicization_top_n_anchors: int = 10
topicization_min_token_length: int = 3
topicization_text_clean_match_chars: int = 500
topicization_batch_concurrency: int = 5
pipeline_version_processing: str = "v1.0"
pipeline_version_topicization: str = "v1.0"
llm_temperature: float = 0.0
llm_max_tokens: int = 4096
openai_base_url: str = "https://api.openai.com/v1"
```

---

**Подготовлено:** Session 46  
**Следующий шаг:** T4 (scheduler shim) → T3 (processing config) → T1 (LLMResponse) → T2 (batch splitting)
