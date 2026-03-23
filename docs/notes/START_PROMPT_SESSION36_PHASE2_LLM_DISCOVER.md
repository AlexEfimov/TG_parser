# Session 36: Phase 2 — LLM Discover для неназначенных документов

**Дата:** [дата запуска]  
**Тип сессии:** Реализация  
**Архитектурный план:** `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` (Session 34)  
**Предыдущие сессии:** Session 35 (Phase 1 assign), Session 34 (планирование), Session 33 (topicization fix)

---

## Цель сессии

Реализовать **Phase 2 инкрементальной топикизации** — LLM-обнаружение новых тем и доназначение неназначенных документов с контекстом существующих тем.

После этой сессии система:
- Phase 1: программно назначает новые docs в существующие темы (keyword, 0 tokens) — **уже работает**
- Phase 2: для unassigned docs вызывает LLM с компактным контекстом всех ~80 тем (~20K tokens)
- LLM может: (a) назначить doc в существующую тему, (b) создать новую тему, (c) отметить doc как unassignable
- Новые TopicCards создаются с `metadata.origin = "discovered"`
- Bundles обновляются инкрементально для всех assignments
- Полный incremental flow: Phase 1 → Phase 2 → update bundles → recompute coverage

---

## Что сделано в Session 35 (контекст)

### Новые модели (`tg_parser/domain/models.py`)

```python
class TopicAssignment(BaseModel):
    source_ref: str
    topic_id: str
    score: float  # ge=0.0, le=1.0
    method: str   # "keyword" | "llm"

class IncrementalTopicizeResult(BaseModel):
    assigned_keyword: list[TopicAssignment] = []
    assigned_llm: list[TopicAssignment] = []    # ← Phase 2 заполнит
    new_topics: list[TopicCard] = []             # ← Phase 2 заполнит
    unassignable: list[str] = []
    tokens_used: int = 0                         # ← Phase 2 запишет
    coverage_before: float = 0.0
    coverage_after: float = 0.0
```

### Phase 1 (`tg_parser/processing/topicization.py`)

- `_tokenize_topic_card(topic_card)` — token set из title + scope_in
- `_tokenize_document(doc)` — (strong_tokens, weak_tokens) из topics/summary/text_clean
- `_compute_match_score(topic_keywords, strong, weak)` → (score, hits)
- `assign_documents_to_topics(new_docs, channel_id)` → (assignments, unassigned_refs)

### Инкрементальные bundles (`tg_parser/storage/sqlalchemy/topic_bundle_repo.py`)

- `add_items(topic_id, new_items)` — загрузка bundle, dedupe по source_ref, re-sort, upsert

### Оркестрация (`tg_parser/services/topicization_service.py`)

- `run_incremental_topicization(channel_id, new_doc_refs)` — Phase 1 + Phase 2 stub + bundle update + coverage
- Текущий Phase 2 stub: `logger.info("Phase 2 stub: %d unassigned docs ...")`

### Scheduler (`tg_parser/services/scheduler_service.py`)

- Убран threshold-based `_retopicize_source()` из автоматического flow
- Заменён на `run_incremental_topicization()` при любых new docs
- `_retopicize_source()` сохранён для CLI `--force`

### Тесты

- 502 passed, 0 regressions
- `tests/test_incremental_topicization.py` — 21 тестов (scoring, assign, add_items, models)
- `tests/test_scheduler_service.py` — обновлены 2 теста для нового incremental flow

---

## Задачи

### Задача 1: Промпт `INCREMENTAL_ASSIGN_DISCOVER_PROMPT`

**Файл:** `tg_parser/processing/topicization_prompts.py`

Новый промпт для Phase 2. LLM получает:
- Компактный контекст существующих тем (id, title, scope_in) — ~4K tokens для 80 тем
- Batch unassigned docs (source_ref, summary, topics, text_clean[:500])

LLM возвращает JSON:
```json
{
  "assignments": [
    {"source_ref": "tg:ch:post:123", "topic_id": "topic:tg:ch:post:100", "confidence": 0.85}
  ],
  "new_topics": [
    {
      "title": "Новая тема",
      "summary": "Описание",
      "scope_in": ["аспект 1", "аспект 2"],
      "scope_out": ["не относится"],
      "anchors": [{"source_ref": "tg:ch:post:456", "score": 0.9}]
    }
  ],
  "unassignable": ["tg:ch:post:789"]
}
```

**Требования к промпту:**
- ВАЖНО: генерировать title/summary/scope на языке исходных сообщений (как в `TOPICIZATION_SYSTEM_PROMPT`)
- Не создавать тему-дубликат существующей — для этого передаётся полный контекст
- Singleton-тема: если один doc достаточно содержателен (score >= 0.75, длина >= 300)
- Cluster-тема: >= 2 anchors из unassigned docs (score >= 0.6)
- `confidence` для assignments = аналог score (0.0-1.0)
- Если doc не подходит ни к одной теме и не формирует новую — `unassignable`

**Вспомогательные функции:**
```python
def build_incremental_discover_prompt(
    existing_topics: list[dict],  # [{id, title, scope_in}]
    unassigned_docs: list[dict],  # [{source_ref, summary, topics, text_clean}]
) -> str:
    """Построить user промпт для Phase 2 LLM discover."""

def get_incremental_discover_prompt_name() -> str:
    """Имя промпта для metadata."""
    return "incremental_discover_v1"
```

### Задача 2: Функция `discover_new_topics`

**Файл:** `tg_parser/processing/topicization.py`  
**Класс:** `TopicizationPipelineImpl`

```python
async def discover_new_topics(
    self,
    channel_id: str,
    unassigned_docs: list[ProcessedDocument],
) -> tuple[list[TopicAssignment], list[TopicCard], list[str]]:
    """
    Phase 2: LLM discover — назначение + обнаружение новых тем.
    
    Returns:
        (llm_assignments, new_topic_cards, unassignable_refs)
    """
```

Алгоритм:
1. Загрузить все TopicCards канала → компактный контекст: `[{id, title, scope_in}]`
2. Сформировать batch из unassigned docs (до 50 за вызов)
3. Вызвать LLM с `INCREMENTAL_ASSIGN_DISCOVER_PROMPT`
4. Парсинг JSON ответа через `extract_json_from_response`
5. Для `assignments`: создать `TopicAssignment(method="llm")`
6. Для `new_topics`: создать TopicCards через `_build_topic_card` с metadata `origin: "discovered"`
7. Для `unassignable`: вернуть список source_refs
8. Retry логика на `JSONDecodeError` (аналогично `_generate_topics_batch`)

**Важно:**
- `llm_client` нужен для Phase 2 (в отличие от Phase 1). Передавать его в pipeline.
- `_build_topic_card` уже проверяет качество — можно переиспользовать, но metadata нужен другой (`origin: "discovered"`, `algorithm: "incremental_llm_discover"`)
- Новые TopicCards сохранять через `topic_card_repo.upsert`
- Для новых тем создавать bundles через `build_topic_bundle` или через `add_items`

### Задача 3: Интеграция Phase 2 в `run_incremental_topicization`

**Файл:** `tg_parser/services/topicization_service.py`

Заменить Phase 2 stub на реальный вызов:

```python
# Текущий stub:
if unassigned_refs:
    logger.info("Phase 2 stub: %d unassigned docs ...")

# Заменить на:
if unassigned_refs:
    unassigned_docs = [docs_by_ref[ref] for ref in unassigned_refs if ref in docs_by_ref]
    llm_assignments, new_topic_cards, truly_unassignable = \
        await pipeline.discover_new_topics(channel_id, unassigned_docs)
    
    # Update bundles for LLM assignments (аналогично Phase 1)
    # Build bundles for new topics
    # Update result
```

**Изменения:**
- `pipeline` теперь нуждается в рабочем `llm_client` → создавать LLM client в `run_incremental_topicization`
- Обновить `IncrementalTopicizeResult`: заполнить `assigned_llm`, `new_topics`, `tokens_used`
- Передать `tokens_used` из LLM response (если доступно через `llm_client`)

**Пустые unassigned_docs:** Если Phase 1 назначил все документы, Phase 2 не вызывается.

### Задача 4: Metadata `origin` для TopicCards

В `_build_topic_card` или в обёртке для Phase 2:
- Baseline темы: `metadata.origin = "baseline"` (не трогать существующие)
- Discovered темы: `metadata.origin = "discovered"`, `metadata.discovered_at = ISO timestamp`

**Вариант:** не менять `_build_topic_card`, а задавать origin после вызова:
```python
card = self._build_topic_card(raw_topic, channel_id, documents)
if card:
    card.metadata["origin"] = "discovered"
    card.metadata["discovered_at"] = datetime.now(UTC).isoformat()
```

### Задача 5: Тесты

**Файл:** `tests/test_incremental_topicization.py` (дополнить)

1. **`test_discover_new_topics_assigns_to_existing`:**
   - Mock LLM возвращает assignments к существующим темам
   - Проверить: TopicAssignment с `method="llm"`, корректный topic_id

2. **`test_discover_new_topics_creates_new_topic`:**
   - Mock LLM возвращает new_topics
   - Проверить: TopicCard создан, `metadata.origin == "discovered"`, upsert вызван

3. **`test_discover_new_topics_marks_unassignable`:**
   - Mock LLM возвращает unassignable refs
   - Проверить: они в возвращённом списке

4. **`test_discover_handles_json_parse_error`:**
   - Mock LLM возвращает невалидный JSON
   - Проверить: retry, после 3 попыток — fallback (все docs → unassignable)

5. **`test_phase2_not_called_when_all_assigned`:**
   - Phase 1 назначает все docs
   - Phase 2 не вызывается, `assigned_llm` пустой

6. **`test_full_incremental_flow_phase1_plus_phase2`:**
   - 5 new docs: 3 → Phase 1 (keyword), 2 → Phase 2 (1 assigned LLM, 1 new topic)
   - Bundles обновлены для 4 docs (3 keyword + 1 LLM)
   - 1 новая тема создана
   - Coverage пересчитан

---

## Контекст: текущая кодовая база

### Ключевые функции для реюза

**`_generate_topics_batch` в `topicization.py`:**
- Содержит retry логику для JSONDecodeError (3 попытки)
- Использует `extract_json_from_response` для извлечения JSON из markdown
- Паттерн: `llm_client.generate(prompt, system_prompt, temperature=0.0, max_tokens, response_format)`

**`_build_topic_card` в `topicization.py`:**
- Парсит raw LLM output в TopicCard
- Проверяет качество (singleton/cluster criteria)
- Генерирует `topic_id = make_topic_id(primary_anchor_ref)`
- Metadata содержит `algorithm`, `pipeline_version`, `model_id`, `prompt_id`

**`build_topic_bundle` в `topicization.py`:**
- Полная сборка bundle (anchors + supporting items)
- Можно вызвать для новых тем (создать bundle с нуля)

**`add_items` в `topic_bundle_repo.py`:**
- Дополнение существующего bundle новыми items
- Использовать для LLM assignments к существующим темам

### Текущие промпты (`topicization_prompts.py`)

| Промпт | Роль |
|--------|------|
| `TOPICIZATION_SYSTEM_PROMPT` | System prompt для полной topicization |
| `TOPICIZATION_USER_PROMPT_TEMPLATE` | User prompt с {messages_text} |
| `SUPPORTING_ITEMS_SYSTEM_PROMPT` | System prompt для supporting items (не используется в Phase 2) |
| `build_topicization_prompt(messages)` | Форматирует messages для полной topicization |

### LLM Client API

```python
response = await self.llm_client.generate(
    prompt=prompt,
    system_prompt=system_prompt,
    temperature=0.0,
    max_tokens=8192,
    response_format={"type": "json_object"},
)
```

### Текущие метрики (Session 33 baseline)

| Метрика | Значение |
|---------|----------|
| Documents | 1130 (906 posts + 224 comments) |
| TopicCards | 80 (68 cluster + 12 singleton) |
| Coverage | 77.4% (875/1130) |
| Avg items/bundle | 86.4 |

### Ожидаемый эффект Phase 2

- Phase 1 назначает ~70-80% new docs (keyword match)
- Phase 2 получает ~20-30% (unassigned)
- Из них: ~60% → assign to existing, ~20% → new topics, ~20% → unassignable
- Token cost: ~20K на batch из 15 unassigned docs (vs 400K full re-topicization)

---

## Критерии приёмки

1. `INCREMENTAL_ASSIGN_DISCOVER_PROMPT` — промпт создан, содержит контекст существующих тем
2. `discover_new_topics` — работает корректно (мок-тесты проходят)
3. LLM assignments → bundles обновлены через `add_items`
4. Новые TopicCards создаются с `metadata.origin = "discovered"`, bundles собираются
5. Phase 2 stub заменён на реальный вызов в `run_incremental_topicization`
6. Retry логика на JSONDecodeError (3 попытки)
7. Если Phase 1 назначил все docs — Phase 2 не вызывается
8. Все тесты проходят (включая Session 35, no regressions)

---

## Чего НЕ делаем в этой сессии

- CLI команды `--mode incremental-topicize` — Session 37
- E2E тест на реальных данных — Session 37
- Token cost tracking (подробный) — Session 37
- Embedding matching — P5/RAG
- Batch splitting для > 50 unassigned docs (если < 50, одного вызова достаточно)
