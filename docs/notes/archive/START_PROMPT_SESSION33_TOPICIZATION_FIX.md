# Session 33: Улучшение топикизации — fix bundles и coverage

**Дата:** 23 марта 2026  
**Версия:** v3.6.0 → v3.7.0  
**Приоритет:** P4  
**Оценка:** ~4-5 часов разработки  
**Предыдущие сессии:** Session 30 (Incremental), Session 31 (Parallel), Session 32 (Comment processing)

---

## Цель Session 33

Повысить **покрытие документов темами** и **качество bundle building**. Сейчас:

1. **56.1% покрытия** — только 634 из 1130 документов попали хотя бы в одну тему (496 непокрытых: 411 постов + 85 комментариев)
2. **71 из 84 bundles упёрлись в MAX_SUPPORTING_ITEMS=20** — лимит слишком жёсткий, потенциально релевантные документы отсекаются
3. **Keyword matching слишком грубый** — `_find_supporting_items_programmatic()` использует только `doc.topics` + `doc.summary`, игнорируя `text_clean`; токенизация >= 4 символов теряет короткие медицинские термины (ТТГ, СОЭ, ПЦР, IgE)
4. **Настройки не подключены** — `settings.py` определяет `topicization_supporting_min_score=0.5` и другие пороги, но `topicization.py` использует хардкод `MIN_SUPPORTING_SCORE=0.15`
5. **Документы в до 14 темах** — некоторые документы попали в 14 bundles (избыточный overlap), тогда как 496 не попали ни в одну
6. **LLM-based supporting items не используются** — промпты для supporting items существуют в `topicization_prompts.py`, но pipeline использует только программатический keyword matching

Результат: покрытие >= 80%, настраиваемые пороги, адекватная гранулярность.

---

## Диагностика проблемы

### 1. Keyword matching не учитывает `text_clean`

`_find_supporting_items_programmatic()` (строки 665-740 `topicization.py`):

```python
# Используются только topics и summary
doc_tokens: set[str] = set()
for t in (doc.topics or []):
    doc_tokens |= self._tokenize(t)
if doc.summary:
    doc_tokens |= self._tokenize(doc.summary)
```

Проблема: `text_clean` содержит основной контент документа (до 4000 символов), но не участвует в matching. Документ про ПЦР-диагностику может не попасть в тему "ПЦР-диагностика", если его `topics` и `summary` не содержат этого ключевого слова.

### 2. `_tokenize` теряет короткие термины

```python
def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Zа-яА-ЯёЁ]{4,}", text.lower())}
```

Минимум 4 символа → теряются: СОЭ, ТТГ, СРБ, ПЦР, IgE, IgG, ЛДГ, АЛТ, ХГЧ, ДНК, РНК и другие медицинские аббревиатуры.

### 3. MAX_SUPPORTING_ITEMS = 20 — искусственный потолок

71 из 84 bundles содержат ровно 20 supporting items. Это означает, что для большинства тем реально найдено больше 20 подходящих документов, но они отсечены лимитом. При 1130 документах и 84 темах более адекватный лимит — 30-50.

### 4. Непокрытые документы — не аномалия

496 непокрытых документов включают:
- Праздничные посты ("С Рождеством!", "День снятия блокады")
- Анонсы и реклама ("Запись на курс", "Подробная программа")
- Контекстные дискуссии ("Темп жизни", "Один против маркетинга")

Часть из них **не должна** попадать в медицинские темы. Но значительная часть (посты про ПЦР, спортивную генетику, COVID-19) **должна**, но не попадает из-за ограничений matching.

### 5. Настройки не wired

В `settings.py` (строки 178-194):
```python
topicization_top_n_anchors: int = 3           # не используется
topicization_singleton_min_len: int = 300      # не используется
topicization_singleton_min_score: float = 0.75 # не используется
topicization_cluster_min_anchor_score: float = 0.6 # не используется
topicization_supporting_min_score: float = 0.5 # не используется (код = 0.15)
topicization_batch_concurrency: int = 5        # ИСПОЛЬЗУЕТСЯ ✓
```

### 6. Текущие метрики

| Метрика | Значение |
|---------|----------|
| Документов | 1130 (906 постов + 224 комментария) |
| TopicCards | 84 (63 cluster + 21 singleton) |
| TopicBundles | 84 |
| Items в bundles | 1744 |
| Покрытие | 634 / 1130 (56.1%) |
| Непокрытых | 496 (411 постов + 85 комментариев) |
| Документов в >1 теме | 383 |
| Макс тем на документ | 14 |
| Bundles с MAX supporting | 71 / 84 |
| Среднее items/bundle | 20.8 |
| Среднее supporting/bundle | 18.4 |

---

## Обязательные документы для изучения

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| `tg_parser/processing/topicization.py` | `_find_supporting_items_programmatic`, `_tokenize`, `build_topic_bundle`, constants | ⭐⭐⭐ |
| `tg_parser/processing/topicization_prompts.py` | `SUPPORTING_ITEMS_*` промпты (не используются), `build_supporting_items_prompt` | ⭐⭐ |
| `tg_parser/config/settings.py` | Topicization thresholds (строки 178-194) | ⭐⭐ |
| `tg_parser/services/topicization_service.py` | `run_topicization()` — orchestration | ⭐⭐ |
| `tg_parser/domain/models.py` | `TopicCard`, `TopicBundle`, `BundleItem`, `BundleItemRole` | ⭐ |
| `docs/notes/topicization_before_session32.json` | Snapshot 64 тем для сравнения | ⭐ |

---

## Scope Session 33

### 1. Улучшение `_tokenize` — поддержка коротких терминов

Снизить минимум с 4 до 2 символов и добавить whitelist медицинских аббревиатур:

```python
@staticmethod
def _tokenize(text: str) -> set[str]:
    """Extract lowercase word tokens (2+ chars) for keyword matching."""
    return {w for w in re.findall(r"[a-zA-Zа-яА-ЯёЁ]{2,}", text.lower())}
```

Риск: больше шумных совпадений (предлоги "по", "от"). Митигация: увеличить `MIN_SUPPORTING_SCORE` до 0.20-0.25.

### 2. Включить `text_clean` в matching

В `_find_supporting_items_programmatic()` добавить `text_clean` в `doc_tokens`:

```python
doc_tokens: set[str] = set()
for t in (doc.topics or []):
    doc_tokens |= self._tokenize(t)
if doc.summary:
    doc_tokens |= self._tokenize(doc.summary)
# Добавить text_clean (ограничить первые N символов для производительности)
if doc.text_clean:
    doc_tokens |= self._tokenize(doc.text_clean[:1000])
```

### 3. Увеличить MAX_SUPPORTING_ITEMS

С 20 до 40-50. При 1130 документах и 84 темах это допустимо. Рассчитать оптимальное значение: `ceil(total_docs / topics_count * 1.5)`.

### 4. Подключить настройки из settings.py

Заменить хардкод-константы на чтение из settings:

```python
MIN_SUPPORTING_SCORE = settings.topicization_supporting_min_score  # 0.5 в settings
MAX_SUPPORTING_ITEMS = settings.topicization_max_supporting_items   # новое поле
MAX_ANCHORS_PER_CLUSTER = settings.topicization_top_n_anchors      # 3 в settings
```

Добавить недостающие поля в `Settings`:
- `topicization_max_supporting_items: int = 40`
- `topicization_min_token_length: int = 2`
- `topicization_text_clean_match_chars: int = 1000`

### 5. Метрика coverage

Добавить вычисление и логирование покрытия после topicization:

```python
async def compute_coverage(self, channel_id: str) -> dict:
    """Compute topic coverage metrics for a channel."""
    all_docs = await self.processed_doc_repo.list_by_channel(channel_id)
    all_refs = {d.source_ref for d in all_docs}
    
    covered_refs = set()
    for bundle in await self.topic_bundle_repo.list_by_channel(channel_id):
        for item in bundle.items:
            covered_refs.add(item.source_ref)
    
    return {
        "total_documents": len(all_refs),
        "covered_documents": len(covered_refs),
        "coverage_pct": len(covered_refs) / len(all_refs) * 100,
        "uncovered_documents": len(all_refs - covered_refs),
    }
```

Вывести в CLI после topicization: `Coverage: 85.2% (963/1130)`.

### 6. Тесты

- Тест: `_tokenize` корректно обрабатывает короткие медицинские термины (СОЭ, IgE)
- Тест: supporting items включают документы с совпадениями в `text_clean`
- Тест: `MAX_SUPPORTING_ITEMS` из settings, а не хардкод
- Тест: метрика coverage вычисляется корректно
- Тест: backward compat — существующие тесты проходят

---

## Конфигурация

Новые/изменённые поля в `.env` (опционально):

```env
# Supporting items matching
TOPICIZATION_MAX_SUPPORTING_ITEMS=40
TOPICIZATION_SUPPORTING_MIN_SCORE=0.2
TOPICIZATION_MIN_TOKEN_LENGTH=2
TOPICIZATION_TEXT_CLEAN_MATCH_CHARS=1000
```

---

## Техническое состояние

### База данных (после Session 32)

```
PostgreSQL 16 (Homebrew): localhost:5432/tg_parser
├── sources (1 запись: labdiagnostica, status=active)
├── raw_messages (1130 записей: 906 постов + 224 комментария)
├── processed_documents (1130 записей, 100% processed)
├── topic_cards (84 записи: 63 cluster + 21 singleton)
├── topic_bundles (84 записи, 1744 items)
├── processing_failures (0 записей)
└── source_attempts (11+ записей)
```

### LLM конфигурация

```
# Processing
PROCESSING_LLM_PROVIDER=anthropic
PROCESSING_LLM_MODEL=claude-haiku-4-5-20251001
PROCESSING_CONCURRENCY=20

# Topicization
TOPICIZATION_LLM_PROVIDER=anthropic
TOPICIZATION_LLM_MODEL=claude-sonnet-4-20250514
TOPICIZATION_BATCH_CONCURRENCY=5
```

### Тесты

```
329 passed, 8 skipped, 2 pre-existing failures
Failing: test_full_pipeline_e2e, test_comments_ingestion_with_per_thread_cursors
Нет отдельных тестов для topicization pipeline (!)
```

### Ключевые изменения Session 32

- Comment processing с parent context (222/224 комментариев)
- Media-only synthetic documents (comment:154, comment:4057)
- Дифференцированный промпт для комментариев
- Re-topicization: 64 → 84 темы, bundles 1247 → 1744 items, покрытие 56.1%

---

## Ограничения

1. **Keyword matching vs semantic matching** — programmatic matching по ключевым словам принципиально ограничен. Для Session 33 улучшаем его максимально, но для принципиального прорыва (>90% quality coverage) потребуется embedding-based matching (P5/RAG).
2. **Детерминизм** — LLM-часть topicization (генерация TopicCards) недетерминистична при `temperature=0` из-за батчирования и merge. Улучшения в bundle building программатические и полностью детерминистичны.
3. **Производительность `text_clean` matching** — добавление text_clean в tokenization увеличит объём сравнений (1130 документов × 84 темы × ~200 токенов). При программатическом matching это O(секунды), но стоит мониторить.
4. **Не все документы должны быть покрыты** — праздничные поздравления, анонсы курсов, off-topic дискуссии могут быть за пределами тематического ядра канала. Целевое покрытие 75-85%, не 100%.

---

## Критерии завершения Session 33

### Must Have:
- [ ] Покрытие >= 75% (>= 848 / 1130 документов в bundles)
- [ ] `_tokenize` поддерживает термины >= 2 символов
- [ ] `text_clean` участвует в matching supporting items
- [ ] Constants из settings.py, а не хардкод
- [ ] Метрика coverage выводится в CLI после topicization
- [ ] Существующие тесты проходят (329+)

### Should Have:
- [ ] Новые тесты для topicization pipeline (tokenize, supporting items, coverage)
- [ ] MAX_SUPPORTING_ITEMS настраивается через `.env`
- [ ] Верификация на реальном канале: покрытие, кол-во тем, distribution
- [ ] Логирование: "Coverage: X% (N/M documents)"

### Nice to Have:
- [ ] Анализ непокрытых документов: categorize (off-topic, short, media-only)
- [ ] Weighted scoring: `text_clean` hits score меньше чем `topics` hits
- [ ] Опциональный LLM-based supporting items (как fallback для low-coverage тем)

---

## Начало работы

1. Изучить документы из раздела "Обязательные документы"
2. Запустить тесты: `.venv/bin/python -m pytest tests/ -q --ignore=tests/test_agents.py --ignore=tests/test_multi_agent.py --ignore=tests/test_gpt5_responses_api.py --ignore=tests/test_llm_clients.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_postgres_integration.py`
3. Начать реализацию: tokenize fix → text_clean matching → settings wiring → MAX increase → coverage metric → tests → верификация
