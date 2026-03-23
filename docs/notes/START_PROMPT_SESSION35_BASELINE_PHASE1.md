# Session 35: Baseline + Phase 1 (Programmatic Assign)

**Дата:** [дата запуска]  
**Тип сессии:** Реализация  
**Архитектурный план:** `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` (Session 34)  
**Предыдущие сессии:** Session 34 (планирование), Session 33 (topicization fix), Session 30 (incremental pipeline)

---

## Цель сессии

Установить стабильный baseline тем и реализовать **Phase 1 инкрементальной топикизации** — программное назначение новых документов в существующие темы без LLM.

После этой сессии система:
- Имеет замороженный baseline из ~80 тем
- При появлении новых сообщений назначает их в существующие темы через keyword matching (0 LLM tokens)
- Инкрементально обновляет bundles (добавляет items, не пересобирает)
- Не запускает полную re-topicization автоматически
- Логирует unassigned docs (Phase 2 — заглушка до Session 36)

---

## Задачи

### Задача 1: Финальный baseline

Запустить один последний `topicize_channel(force=True)` для канала `labdiagnostica_logical`. Записать метрики:
- Количество тем (TopicCards)
- Покрытие (coverage %)
- Количество bundles
- Распределение: cluster vs singleton

Эти метрики — baseline для сравнения с инкрементальным flow.

**Важно:** После этого запуска полная re-topicization в автоматическом режиме больше не используется.

### Задача 2: Функция `assign_documents_to_topics`

**Файл:** `tg_parser/processing/topicization.py`  
**Класс:** `TopicizationPipelineImpl`

Новый метод, инвертированный относительно `_find_supporting_items_programmatic`:

```python
async def assign_documents_to_topics(
    self,
    new_docs: list[ProcessedDocument],
    channel_id: str,
) -> tuple[list[TopicAssignment], list[str]]:
    """
    Phase 1: Программное назначение документов в существующие темы.
    
    Для каждого doc: tokenize fields → match against topic keywords → 
    assign to best topic if score >= threshold.
    
    Returns:
        (assignments, unassigned_refs)
    """
```

Алгоритм:
1. Загрузить все TopicCards канала через `topic_card_repo.list_by_channel(channel_id)`
2. Для каждого TopicCard: tokenize `title` + все элементы `scope_in` → `topic_keywords: set[str]`
3. Для каждого нового doc:
   - Strong tokens: из `doc.topics` + `doc.summary`
   - Weak tokens: из `doc.text_clean[:text_clean_match_chars]`
   - Для каждого TopicCard: вычислить score (weighted overlap, как в `_find_supporting_items_programmatic`)
   - Выбрать best topic (max score)
   - Если best score >= `topicization_supporting_min_score` → assignment
   - Иначе → unassigned
4. Вернуть `(list[TopicAssignment], list[unassigned_source_refs])`

**Реюз:** Логика tokenization и scoring из `_find_supporting_items_programmatic` — вынести в общие helper-функции (`_tokenize` уже есть, нужен `_compute_match_score`).

**Новая модель:** `TopicAssignment` в `tg_parser/domain/models.py`:
```python
@dataclass
class TopicAssignment:
    source_ref: str
    topic_id: str
    score: float
    method: str  # "keyword" | "llm"
```

### Задача 3: Инкрементальное обновление bundles

**Порт:** `tg_parser/storage/ports.py` — добавить метод в `TopicBundleRepo`:
```python
async def add_items(self, topic_id: str, new_items: list[BundleItem]) -> TopicBundle:
    """Добавить items к существующему bundle, dedupe по source_ref."""
```

**Реализация:** `tg_parser/storage/sqlalchemy/topic_bundle_repo.py`:
1. Загрузить текущий bundle по `topic_id`
2. Собрать set существующих `source_ref`
3. Добавить только новые items (dedupe)
4. Пересортировать: anchors first, then supporting by score desc
5. Upsert обратно

### Задача 4: Оркестрация `incremental_topicize`

**Файл:** `tg_parser/services/topicization_service.py`

Новая функция:
```python
async def run_incremental_topicization(
    channel_id: str,
    new_doc_refs: list[str],
) -> IncrementalTopicizeResult:
    """
    Инкрементальная топикизация: Phase 1 (assign) + Phase 2 (stub).
    
    1. Загрузить новые ProcessedDocuments по source_refs
    2. Phase 1: assign_documents_to_topics
    3. Обновить bundles для assigned docs
    4. Phase 2: TODO (Session 36) — логировать unassigned
    5. Вернуть результат с метриками
    """
```

**Новая модель:** `IncrementalTopicizeResult` в `tg_parser/domain/models.py`:
```python
@dataclass
class IncrementalTopicizeResult:
    assigned_keyword: list[TopicAssignment]
    assigned_llm: list[TopicAssignment]  # пустой до Session 36
    new_topics: list[TopicCard]           # пустой до Session 36
    unassignable: list[str]
    tokens_used: int
    coverage_before: float
    coverage_after: float
```

### Задача 5: Изменение scheduler

**Файл:** `tg_parser/services/scheduler_service.py`

В `run_incremental_for_all_sources`:
- Убрать блок `if new_doc_count >= settings.scheduler_retopicize_threshold: _retopicize_source(...)`
- Заменить на: если есть new docs → вызвать `run_incremental_topicization(channel_id, new_doc_refs)`
- Всегда запускать Phase 1 для новых docs (без threshold)
- `_retopicize_source` оставить как метод, но вызывать только из CLI `--force`

### Задача 6: Тесты

**Файл:** `tests/test_topicization.py` (или новый `tests/test_incremental_topicization.py`)

1. **`test_assign_documents_to_topics`:**
   - Создать 3 TopicCards с известными scope_in
   - Создать docs: 2 matching, 1 не matching
   - Проверить: 2 assigned с правильными topic_id, 1 unassigned

2. **`test_assign_best_topic_selected`:**
   - Doc матчится с 2 темами → выбрана тема с max score

3. **`test_add_items_to_bundle`:**
   - Существующий bundle с 3 items
   - Добавить 2 новых → bundle содержит 5 items
   - Добавить duplicate → bundle остаётся 5 items (dedupe)

4. **`test_incremental_topicize_flow`:**
   - E2E: 5 new docs → 3 assigned, 2 unassigned (logged)
   - Bundles обновлены для 3 тем
   - Coverage пересчитан

---

## Контекст: текущая кодовая база

### Ключевые функции для реюза

**`_find_supporting_items_programmatic` в `topicization.py`:**
- Содержит логику tokenization (`_tokenize`) и scoring
- Работает от темы к документам (topic → docs)
- Нужен инвертированный вариант (doc → topics)
- `_tokenize` и scoring logic — вынести в helpers

**`_compute_coverage` в `topicization_service.py`:**
- Считает coverage: union source_refs в bundles vs all docs
- Реюзать для `coverage_before` и `coverage_after`

**`build_topic_bundle` в `topicization.py`:**
- Полная пересборка bundle (anchor + supporting)
- Для Phase 1 **не нужна** — используем `add_items` (дополнение)

### Текущие настройки (settings.py)

| Параметр | Значение | Роль в Phase 1 |
|----------|----------|----------------|
| `topicization_supporting_min_score` | 0.10 | Threshold для assign |
| `topicization_min_token_length` | 3 | Минимальная длина token |
| `topicization_text_clean_match_chars` | 1000 | Префикс text_clean для weak matching |
| `scheduler_retopicize_threshold` | 10 | Больше не используется для auto-retopic |

### Текущие метрики (Session 33)

| Метрика | Значение |
|---------|----------|
| Documents | 1130 (906 posts + 224 comments) |
| TopicCards | 80 (68 cluster + 12 singleton) |
| Coverage | 77.4% (875/1130) |
| Avg items/bundle | 86.4 |

---

## Критерии приёмки

1. Финальный baseline запущен, метрики записаны
2. `assign_documents_to_topics` работает корректно (тесты проходят)
3. `add_items_to_bundle` добавляет items инкрементально с dedupe (тесты проходят)
4. `run_incremental_topicization` вызывает Phase 1 и логирует unassigned
5. Scheduler не запускает полную re-topicization автоматически
6. E2E тест: новые docs → часть assigned, bundles обновлены, coverage пересчитан
7. Все существующие тесты проходят (no regressions)

---

## Чего НЕ делаем в этой сессии

- Phase 2 (LLM discover) — Session 36
- Новые промпты для LLM — Session 36
- CLI команды `--mode incremental-topicize` — Session 37
- Embedding matching — P5/RAG
- Миграции data model для `origin` в metadata — Session 36 (при создании новых тем)
