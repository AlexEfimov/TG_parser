# Session 34: Стабильная инкрементальная топикизация — архитектурное планирование

**Дата:** 23 марта 2026  
**Тип сессии:** Архитектурное планирование (Plan mode)  
**Приоритет:** Архитектурный блокер для P5 (RAG) и P6 (UI)  
**Предыдущие сессии:** Session 30 (Incremental), Session 33 (Topicization fix)

---

## Проблема

Сейчас при появлении новых сообщений в TG-канале система вынуждена запускать **полную re-topicization всего корпуса**, что создаёт две критические проблемы:

### 1. Стоимость (tokens)

Полная topicization канала `labdiagnostica_logical` (1130 документов):
- 23 батча × ~8K tokens input + ~8K tokens output = **~370K tokens** за один запуск
- Используется Claude Sonnet 4 (дорогая модель)
- Merge-фаза добавляет ещё ~30K tokens
- **Итого: ~400K tokens на каждую re-topicization**

При `scheduler_retopicize_threshold=10` (каждые 10 новых документов) и активном канале с ~50 постами/неделю это **5 полных re-topicization в неделю = ~2M tokens/неделю** только на topicization.

### 2. Нестабильность тем

Каждый запуск `topicize_channel(force=True)`:
- **Удаляет** все существующие TopicCards и TopicBundles
- Генерирует темы **заново** из всего корпуса
- LLM **недетерминистичен** даже при temperature=0 (разное батчирование, разный merge)

Результат — между запусками:
- **Количество тем меняется**: 80 → 84 → 78 → 82...
- **Заголовки тем меняются**: "ПЦР-диагностика" → "Молекулярная ПЦР-диагностика инфекций" → "ПЦР и молекулярные методы"
- **Topic ID нестабильны**: `topic_id = "topic:" + primary_anchor_ref`, а LLM выбирает разные anchors в разных запусках
- **Bundles пересобираются** полностью — все связи документ→тема теряются и создаются заново

Это делает невозможным:
- Стабильные ссылки на темы (для RAG, UI, API)
- Отслеживание эволюции тем во времени
- Кеширование и инкрементальные обновления downstream (embeddings, KB)

---

## Текущая архитектура (что есть)

### Incremental pipeline (Session 30)

```
scheduler_service.py: run_incremental_for_all_sources()
  ├── run_full_pipeline(mode="incremental", skip_topicize=True)
  │     ├── ingest (только новые сообщения через last_post_id)
  │     └── process (только необработанные документы)
  └── IF new_docs >= scheduler_retopicize_threshold:
        └── _retopicize_source(channel_id)
              └── run_topicization(force=True)  ← ПОЛНАЯ пересборка!
```

### Topicization pipeline

```
topicize_channel(force=True):
  1. DELETE все TopicCards + TopicBundles канала
  2. Загрузить ВСЕ ProcessedDocuments канала
  3. Батчинг по 50 → LLM → raw_topics (23 батча для 1130 docs)
  4. Merge батчей → LLM (ещё один вызов)
  5. Построить TopicCards (проверки качества, детерминизация anchors)
  6. Для каждого TopicCard → build_topic_bundle (keyword matching, без LLM)
```

### Текущие метрики (Session 33)

| Метрика | Значение |
|---------|----------|
| Documents | 1130 (906 posts + 224 comments) |
| TopicCards | 80 (68 cluster + 12 singleton) |
| Coverage | 77.4% (875/1130) |
| Avg items/bundle | 86.4 |
| LLM cost per run | ~400K tokens (Claude Sonnet 4) |

### Ключевые файлы

| Файл | Описание |
|------|----------|
| `tg_parser/processing/topicization.py` | `TopicizationPipelineImpl`: `topicize_channel`, `_generate_topics_batch`, `_merge_topics`, `build_topic_bundle`, `_find_supporting_items_programmatic` |
| `tg_parser/services/topicization_service.py` | `run_topicization()`, `_compute_coverage()` |
| `tg_parser/services/scheduler_service.py` | `_retopicize_source()` (вызывает `force=True`), threshold logic |
| `tg_parser/config/settings.py` | `scheduler_retopicize_threshold=10`, topicization_* параметры |
| `tg_parser/domain/models.py` | `TopicCard`, `TopicBundle`, `BundleItem` |
| `tg_parser/domain/ids.py` | `make_topic_id(primary_anchor_ref)` — текущая схема ID |

---

## Варианты решения (для обсуждения)

### Вариант A: Assign-only (заморозить темы, назначать программно)

**Идея:** Существующие TopicCards фиксируются. Новые документы назначаются в существующие темы через keyword matching (уже реализован в `_find_supporting_items_programmatic`). Полная re-topicization — только по ручному запуску.

```
Incremental flow:
  ingest → process → assign_to_existing_topics (программно, без LLM)
```

- **Стоимость:** 0 LLM tokens на инкремент
- **Стабильность:** Полная — темы не меняются
- **Покрытие:** Новые документы, не совпадающие ни с одной темой, остаются "бездомными" до ручной re-topicization
- **Сложность:** Низкая — реюзается `_find_supporting_items_programmatic`

### Вариант B: Two-phase (назначить + открыть новые темы)

**Идея:** Фаза 1 — программное назначение новых docs в существующие темы. Фаза 2 — LLM обрабатывает только **неназначенные** документы для обнаружения новых тем.

```
Incremental flow:
  ingest → process → assign_to_existing_topics
                    → IF unassigned > threshold:
                        LLM topicize ONLY unassigned docs → new TopicCards
                        merge_new_topics_into_registry
```

- **Стоимость:** Пропорциональна количеству неназначенных документов (не всему корпусу)
- **Стабильность:** Существующие темы стабильны, новые добавляются
- **Покрытие:** Хорошее — новые темы обнаруживаются
- **Сложность:** Средняя — нужна логика merge новых тем с существующими

### Вариант C: Stable Topic Registry (каноническая карта тем)

**Идея:** Ввести отдельный слой "Topic Registry" — канонические темы со стабильными ID, заголовками и описаниями. LLM-генерированные темы **не заменяют** реестр, а **мэтчатся** к нему. Новые темы добавляются в реестр через approval flow (автоматический или ручной).

```
Topic Registry: [stable_id, title, description, keywords, status]
  ↓
TopicCards привязываются к registry entries
  ↓
Bundles привязываются к registry entries (не к ephemeral TopicCard IDs)
```

- **Стабильность:** Максимальная — ID из реестра не зависят от LLM
- **Стоимость:** Зависит от стратегии обновления реестра
- **Покрытие:** Зависит от полноты реестра
- **Сложность:** Высокая — новый слой, миграции, matching logic

### Вариант D: Diff-based topicization (LLM только на новых)

**Идея:** LLM topicization запускается только на новых документах. Полученные темы мержатся с существующими (LLM-based dedup, как текущий `_merge_topics`).

```
Incremental flow:
  ingest → process → LLM topicize ONLY new_docs → merge with existing topics
                                                 → rebuild bundles
```

- **Стоимость:** Пропорциональна новым документам (~10 docs = 1 batch = ~16K tokens vs 400K)
- **Стабильность:** Частичная — merge может изменить существующие темы
- **Покрытие:** Хорошее
- **Сложность:** Средняя — нужна надёжная merge-логика

### Вариант E: Embedding-based assignment (перекрытие с P5/RAG)

**Идея:** Использовать embeddings для semantic matching документов к темам. Это естественно объединяется с P5 (RAG), который всё равно требует embeddings.

```
Incremental flow:
  ingest → process → embed new docs → cosine similarity с topic embeddings
                                     → assign to nearest topic (threshold)
                                     → unmatched → queue for new topic discovery
```

- **Стабильность:** Хорошая — темы не пересоздаются
- **Покрытие:** Лучшее — semantic matching сильнее keyword matching
- **Стоимость:** Embedding дешевле LLM generation (10-100x)
- **Сложность:** Высокая — требует embedding инфраструктуру (pgvector/ChromaDB)
- **Синергия:** Прямая с P5 (RAG) — одна и та же embedding-инфраструктура

---

## Вопросы для обсуждения

### Стратегические

1. **Какой вариант (A-E) или комбинация оптимальны?** Учитывая, что P5 (RAG) — следующий приоритет, вариант E выглядит привлекательно, но он самый сложный.
2. **Нужна ли полная re-topicization вообще?** Или можно перейти на модель "темы только добавляются, никогда не удаляются"?
3. **Как версионировать темы?** Если тема эволюционирует (расширяется scope), нужно ли хранить историю?

### Технические

4. **Схема стабильных topic ID:** Текущая `topic:tg:channel:post:123` привязана к anchor. Нужна ли content-based схема (hash от title+scope)?
5. **Bundle rebuilding:** Сейчас bundles перестраиваются для всех тем. Можно ли обновлять только bundles затронутых тем?
6. **Threshold strategy:** `scheduler_retopicize_threshold=10` — это грубый порог. Нужна ли более умная стратегия (по % непокрытых документов)?

### Связь с RAG (P5)

7. **Если выбран вариант E** — стоит ли объединить Session 34 и P5 в один deliverable?
8. **Embedding model:** OpenAI `text-embedding-3-small` vs Anthropic vs open-source (e5, multilingual-e5)?
9. **Векторное хранилище:** pgvector (уже есть PostgreSQL) vs ChromaDB (отдельный)?

---

## Ограничения и контекст

1. **Один канал, ~1130 документов** — масштаб пока небольшой, но архитектура должна работать для 10K+ документов
2. **Русскоязычный контент** — embedding модель должна хорошо работать с русским
3. **PostgreSQL уже в production** — pgvector будет проще внедрить, чем отдельный ChromaDB
4. **Keyword matching (Session 33)** даёт 77.4% coverage — semantic matching может дать 90%+
5. **Budget-conscious** — решение должно минимизировать LLM token cost при масштабировании

---

## Формат сессии

Это **сессия планирования**, а не реализации. Ожидаемый результат:

1. **Выбранный подход** (один из A-E или комбинация) с обоснованием
2. **Архитектурный дизайн** выбранного подхода: компоненты, flow, data model
3. **Scope для следующих 2-3 сессий** — что реализовывать первым
4. **Решение по связке с RAG** — делать вместе или раздельно
5. **Обновлённый DEVELOPMENT_ROADMAP** с учётом принятых решений
