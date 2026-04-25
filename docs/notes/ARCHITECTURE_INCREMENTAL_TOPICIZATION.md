# Архитектура: Стабильная инкрементальная топикизация

**Дата принятия:** 23 марта 2026  
**Сессия планирования:** Session 34  
**Статус:** Утверждён

---

## Контекст проблемы

При появлении новых сообщений в TG-канале система запускает **полную re-topicization всего корпуса**, что создаёт:

1. **Стоимость:** ~400K tokens (Claude Sonnet 4) на каждый запуск. При threshold=10 и ~50 постах/неделю — ~2M tokens/неделю.
2. **Нестабильность тем:** Каждый запуск удаляет все TopicCards/TopicBundles и генерирует заново. ID тем, заголовки и состав бандлов меняются между запусками из-за недетерминизма LLM.

---

## Принятые решения

| Вопрос | Решение | Обоснование |
|--------|---------|-------------|
| Основной подход | **B2 (Two-phase):** программный assign + LLM discover с контекстом | Баланс стоимости и полноты: 95% экономия tokens при сохранении обнаружения новых тем |
| Phase 1 | Новая функция `assign_documents_to_topics` (doc → best topic), keyword matching | Инвертированный matching эффективнее пересборки bundles; O(new_docs × topics) |
| Phase 2 | LLM видит unassigned docs + компактный список существующих тем | Контекст тем предотвращает создание дубликатов; assign + discover в одном вызове |
| Триггер Phase 2 | При каждом инкременте, если >= 1 unassigned doc | Максимальное покрытие; стоимость пропорциональна только unassigned docs |
| Обновление bundles | Инкрементальное — добавление BundleItems без пересборки | Не трогает существующие bundles, только дополняет |
| Baseline | Один финальный полный запуск → заморозить как baseline | Текущие 80 тем фиксируются; даёт стабильную точку отсчёта |
| Full re-topicization | Только CLI --force (убрать из scheduler) | Предотвращает автоматический drift; ручной запуск для исключительных случаев |
| Embeddings | Позже (P5/RAG), keyword matching пока достаточно | Поэтапный подход: keyword assign сейчас → embedding assign в рамках P5 |
| ID схема | Текущая `topic:{primary_anchor_ref}` | Работает для стабильных тем; не меняется если тема не пересоздаётся |

---

## Архитектура: Incremental flow

### Общая схема

```
Scheduler polls → Ingest new messages → Process new docs
                                            ↓
                                   Phase 1: Programmatic Assign
                                   (keyword match doc → existing topics)
                                            ↓
                              ┌─────────────┴──────────────┐
                              ↓                            ↓
                     M docs assigned               K docs unassigned
                     (add to bundles)                      ↓
                                               Phase 2: LLM Discover
                                               (K docs + 80 topics context)
                                                          ↓
                                            ┌─────────────┼──────────────┐
                                            ↓             ↓              ↓
                                    J docs assigned   L new topics   unassignable
                                    to existing       created        (logged)
                                    (add to bundles)  (+ bundles)
                                                          ↓
                                                  Recompute coverage
```

### Phase 1: Programmatic Assign

**Функция:** `assign_documents_to_topics(new_docs, channel_id)`  
**Файл:** `tg_parser/processing/topicization.py`

Алгоритм:
1. Загрузить все `TopicCard` канала
2. Для каждого нового doc: tokenize `topics + summary + text_clean[:1000]`
3. Для каждого TopicCard: tokenize `title + scope_in`
4. Score = weighted token overlap (аналогично `_find_supporting_items_programmatic`)
5. Если score >= threshold → assign; иначе → unassigned

**Стоимость:** 0 LLM tokens.  
**Ожидаемый % assign:** ~70-80% (по аналогии с текущим coverage 77.4%).

### Phase 2: LLM Discover

**Функция:** `discover_new_topics(channel_id, unassigned_docs)`  
**Файл:** `tg_parser/processing/topicization.py`

Алгоритм:
1. Загрузить все TopicCards → компактный контекст (~4K tokens для 80 тем: id, title, scope_in)
2. Сформировать batch из unassigned docs (до 50 за вызов)
3. Вызвать LLM с промптом `INCREMENTAL_ASSIGN_DISCOVER_PROMPT`
4. Для `assignments` → обновить bundles
5. Для `new_topics` → создать TopicCards + bundles
6. Для `unassignable` → логировать

**Промпт (INCREMENTAL_ASSIGN_DISCOVER_PROMPT):**

Вход:
- Компактный список существующих тем (id, title, scope_in)
- Новые документы (source_ref, summary, topics, text_clean[:500])

Выход (JSON):
```json
{
  "assignments": [
    {"source_ref": "...", "topic_id": "...", "confidence": 0.85}
  ],
  "new_topics": [
    {
      "title": "...", "summary": "...",
      "scope_in": ["..."], "scope_out": ["..."],
      "anchors": [{"source_ref": "...", "score": 0.9}]
    }
  ],
  "unassignable": ["source_ref_1"]
}
```

**Стоимость:** ~20K tokens для 15 unassigned docs (vs 400K для полной re-topicization).

### Инкрементальное обновление bundles

**Новый метод:** `add_items_to_bundle(topic_id, new_items: list[BundleItem])`  
**Файл:** `tg_parser/storage/sqlalchemy/topic_bundle_repo.py`

Алгоритм:
1. Загрузить текущий bundle
2. Добавить новые items (dedupe по source_ref)
3. Upsert обратно

Существующие bundles не пересобираются — только дополняются.

---

## Data model изменения

### Новые модели

```python
@dataclass
class TopicAssignment:
    source_ref: str
    topic_id: str
    score: float
    method: str  # "keyword" | "llm"

@dataclass
class IncrementalTopicizeResult:
    assigned_keyword: list[TopicAssignment]
    assigned_llm: list[TopicAssignment]
    new_topics: list[TopicCard]
    unassignable: list[str]
    tokens_used: int
    coverage_before: float
    coverage_after: float
```

### Изменения в TopicCard metadata

```python
metadata = {
    ...
    "origin": "baseline" | "discovered",  # baseline — из финального полного запуска; discovered — из Phase 2
    "discovered_at": "2026-03-25T...",     # только для discovered тем
    "discovered_in_run": "incr_20260325_143000",
}
```

### Новый метод в TopicBundleRepo (port + impl)

```python
async def add_items(self, topic_id: str, new_items: list[BundleItem]) -> TopicBundle:
    """Добавить items к существующему bundle, dedupe по source_ref."""
```

---

## Разбивка по сессиям

### Session 35: Baseline + Phase 1 (Assign)

**Цель:** Установить стабильный baseline и реализовать программное назначение новых docs.

**Scope:**

1. **Финальный полный запуск** — один последний `topicize_channel(force=True)`. Записать метрики как baseline (topics_count, coverage_pct, bundles_count).

2. **Новая функция `assign_documents_to_topics(new_docs, channel_id)`** в `tg_parser/processing/topicization.py`:
   - Инвертированный keyword matching: для каждого doc ищем лучшую тему
   - Реюзает логику tokenization из `_find_supporting_items_programmatic`
   - Возвращает assignments + unassigned list

3. **Инкрементальное обновление bundles** — `add_items_to_bundle` в `tg_parser/storage/sqlalchemy/topic_bundle_repo.py` + port в `tg_parser/storage/ports.py`.

4. **Изменение scheduler** — в `tg_parser/services/scheduler_service.py`:
   - Убрать `_retopicize_source` из автоматического flow
   - Заменить на `incremental_topicize(channel_id, new_doc_refs)`
   - Phase 2 = заглушка (log "N unassigned docs, Phase 2 not yet implemented")

5. **Тесты** для `assign_documents_to_topics` и `add_items_to_bundle`.

**Deliverable:** Новые docs назначаются в существующие темы программно, bundles обновляются инкрементально, полная re-topicization не запускается автоматически.

---

### Session 36: Phase 2 (LLM Discover)

**Цель:** LLM-обнаружение новых тем для неназначенных документов.

**Scope:**

1. **Новый промпт `INCREMENTAL_ASSIGN_DISCOVER_PROMPT`** в `tg_parser/processing/topicization_prompts.py`.

2. **Новая функция `discover_new_topics(channel_id, unassigned_docs)`** в `tg_parser/processing/topicization.py`:
   - Формирование компактного контекста существующих тем
   - Вызов LLM, парсинг ответа
   - Создание новых TopicCards через `_build_topic_card`
   - Обновление bundles для assignments и новых тем

3. **Интеграция Phase 1 + Phase 2** — полный `incremental_topicize`:
   - Phase 1 → assign → собрать unassigned
   - Phase 2 → discover_new_topics(unassigned)
   - Update coverage

4. **Тесты:** мок LLM ответов, проверка создания новых TopicCards, проверка что existing topics не затронуты.

**Deliverable:** Полный incremental flow работает end-to-end.

---

### Session 37: Интеграция, тестирование, polish

**Цель:** End-to-end валидация на реальных данных, оптимизация, документация.

**Scope:**

1. **E2E тест на реальных данных:**
   - Запустить baseline
   - Имитировать инкремент: "скрыть" 50 последних docs, прогнать pipeline, "добавить" их инкрементально
   - Сравнить coverage: baseline vs incremental
   - Убедиться что ID существующих тем не изменились

2. **CLI команды:**
   - `--mode incremental-topicize` — запуск Phase 1 + Phase 2
   - `--force` — полная re-topicization (ручной запуск)
   - `--assign-only` — только Phase 1, без LLM

3. **Метрики и логирование:**
   - Token cost per increment
   - Coverage delta
   - Assignment stats: keyword / LLM / new topics / unassignable

4. **Обновлённый DEVELOPMENT_ROADMAP**

**Deliverable:** Надёжная, оттестированная инкрементальная топикизация. Документация обновлена.

---

## Экономический эффект

| Сценарий | Tokens per increment (50 new docs) |
|----------|-----------------------------------|
| Текущий (full re-topicization) | ~400K |
| Phase 1 only (assign-only fallback) | 0 |
| Phase 1 + Phase 2 (15 unassigned) | ~20K |
| **Экономия** | **~95%** |

---

## Риски и митигации

| Риск | Митигация |
|------|-----------|
| LLM в Phase 2 создаёт дубликат существующей темы | Промпт даёт полный контекст тем; post-hoc проверка title similarity |
| Keyword matching пропускает семантически близкие docs | Приемлемо на текущем этапе; embedding matching в P5 решит |
| Unassignable docs копятся | Мониторинг % unassignable; если > 30% — сигнал к ручной re-topicization |
| Phase 2 LLM-batch падает в середине прогона | **Sprint D.1: per-batch checkpointing** — `topicization_service.run_incremental_topicization` вызывает `_discover_single_batch` в цикле и после каждого успешного батча немедленно персистит `topic_card_repo.upsert(...)` + `topic_bundle_repo.add_items(...)`. Если упадёт N+1-й батч, прогресс первых N сохранён; ошибка пробрасывается наверх, в `source_attempts.failed_stage` пишется `topicize`. |
| Канал-баг: docs есть, а topic_cards = 0 (incremental "залипает") | **Sprint D.1: эскалация incremental→full** — если `existing_cards == 0 and new_docs > 0`, `run_incremental_topicization` вызывает `run_topicization(force=True)` и не запускает дальнейшие incremental-фазы. |
| Anthropic вернул `400 invalid_request_error: credit balance` (нет non-retryable классификации) | **Sprint D.1: AnthropicBillingError** — поднимается из `anthropic_client.generate_with_usage` при credit-balance-сообщении (case-insensitive); pipeline-loops её НЕ ретраят, scheduler ловит её в `finally`, инкрементит `tg_parser_anthropic_billing_block_total`, вызывает `_pause_source_for_billing` → `source.rate_limit_until = now + BILLING_BLOCK_BACKOFF_S` (default 1h, см. `docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`). |

---

## Sprint D.1: Topicization Hardening (25 апреля 2026)

К базовому incremental-flow выше добавлены три инварианта (см. также `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` и `docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`):

1. **Per-batch checkpointing в Phase 2.** `_discover_single_batch` пробрасывает `RuntimeError` / `ValueError` / `OSError` наружу вместо «скрытого» fallback’а в `unassignable`. Оркестратор `run_incremental_topicization` сохраняет результат каждого успешного батча сразу (assignments → bundles, new topics → cards + bundles), поэтому частичный прогресс не откатывается.
2. **Escalation incremental → full.** Если на канале есть новые документы, но 0 `TopicCard` (например, после первого силент-фейла), incremental-проход эскалирует в полный `run_topicization(force=True)` и не делает Phase 1/2 дальше.
3. **Truthful `source_attempts`.** Scheduler ведёт `stage_errors[]` и в `finally` пишет `record_attempt(success, failed_stage, error_class, error_message)`. Любой сбой на любом этапе отражается в БД (раньше топикизация падала «молча»). `error_message` усекается до 4096 символов.
4. **Anthropic billing pause.** `AnthropicBillingError` (`tg_parser/processing/llm/errors.py`) — non-retryable; scheduler ставит источник в `rate_limit_until = now + BILLING_BLOCK_BACKOFF_S` и инкрементит счётчик `tg_parser_anthropic_billing_block_total{stage=...}`. Источники с активным `rate_limit_until` пропускаются на следующем тике.

**Связанные файлы:**

- `tg_parser/processing/topicization.py::_discover_single_batch` — пробрасывает исключения
- `tg_parser/services/topicization_service.py::run_incremental_topicization` — checkpoint-loop + escalation
- `tg_parser/services/scheduler_service.py::_process_source` / `_safe_record_attempt` / `_pause_source_for_billing`
- `tg_parser/processing/llm/anthropic_client.py` — детект billing 400
- `tg_parser/api/metrics.py::ANTHROPIC_BILLING_BLOCK_TOTAL`
- `tg_parser/config/settings.py::billing_block_backoff_s` (env: `BILLING_BLOCK_BACKOFF_S`, default 3600s)
- Миграция `migrations/versions/ingestion/20260425_add_source_attempts_failed_stage.py` (revision `ac6a4414ac58`)
- Тесты: `tests/test_anthropic_client_billing.py`, `tests/test_incremental_topicization.py`, `tests/test_scheduler_service.py`

---

## Связь с другими приоритетами

- **P5 (RAG):** Embedding-инфраструктура заменит keyword matching в Phase 1 assign. Стабильные topic ID — prerequisite для RAG retrieval.
- **P6 (UI):** Стабильные topic ID позволяют строить постоянные ссылки на темы в UI.
- **P7 (Multi-channel):** Incremental flow естественно расширяется на несколько каналов.

---

## Ключевые файлы (для reference)

| Файл | Роль |
|------|------|
| `tg_parser/processing/topicization.py` | Основной pipeline: `topicize_channel`, `_generate_topics_batch`, `_merge_topics`, `build_topic_bundle`, `_find_supporting_items_programmatic` + **новые:** `assign_documents_to_topics`, `discover_new_topics`, `incremental_topicize` |
| `tg_parser/processing/topicization_prompts.py` | Промпты: `TOPICIZATION_SYSTEM_PROMPT`, `build_topicization_prompt` + **новый:** `INCREMENTAL_ASSIGN_DISCOVER_PROMPT` |
| `tg_parser/services/topicization_service.py` | `run_topicization()`, `_compute_coverage()` + **новый:** `run_incremental_topicization()` |
| `tg_parser/services/scheduler_service.py` | `_retopicize_source()` (будет заменён), `run_incremental_for_all_sources` |
| `tg_parser/storage/ports.py` | Порты репозиториев + **новый метод:** `add_items` в `TopicBundleRepo` |
| `tg_parser/storage/sqlalchemy/topic_bundle_repo.py` | SQLite impl + **новый:** `add_items()` |
| `tg_parser/domain/models.py` | `TopicCard`, `TopicBundle`, `BundleItem` + **новые:** `TopicAssignment`, `IncrementalTopicizeResult` |
| `tg_parser/domain/ids.py` | `make_topic_id(primary_anchor_ref)` — без изменений |
| `tg_parser/config/settings.py` | Параметры topicization — возможно, новые параметры для incremental flow |
