# Cross-dev: План реализации кросс-канальных улучшений

**Дата:** 1 апреля 2026
**Предпосылки:** Фазы D1–D3, Perf и Cross-val выполнены. 5 каналов, ~5070 документов, 382 темы, полный embedding.
**Родительский документ:** `ROADMAP_V3_PRODUCTION_FIRST.md`

---

## Задачи

### Cross-dev 2: Кросс-канальная статистика (MCP tool)

**Проблема:** Нет агрегированного инструмента для аналитики по нескольким каналам. `list_channels` показывает базовые метрики, но не даёт картину пересечений и сравнений.

**Решение:** Новый MCP tool `get_cross_channel_stats`.

**API-паттерн:** Все существующие MCP tools поддерживают опциональный `channel_id` для фильтрации по каналу. Новый tool должен следовать этому паттерну:
- `get_cross_channel_stats(channel_id=None)` — если `channel_id` задан, вернуть детальную статистику по одному каналу (keywords, coverage, темы); если не задан — агрегированную кросс-канальную аналитику с пересечениями.

**Возвращаемые данные (режим без channel_id):**
- Общее количество документов, тем (singleton / cluster) по каждому каналу
- Coverage по каждому каналу
- Топ-10 ключевых слов (из `topics`) для каждого канала
- Пересечения ключевых слов между каналами (какие темы встречаются в 2+ каналах)

**Возвращаемые данные (режим с channel_id):**
- Детальная статистика по конкретному каналу: документы, темы (singleton/cluster), coverage
- Полный список ключевых слов канала
- Каналы с пересекающимися keywords (связанные каналы)

**Реализация:**
1. Создать функцию `get_cross_channel_analytics(channel_id=None)` в новом файле `tg_parser/services/analytics_service.py`
2. Логика:
   - Загрузить все TopicCard через `topic_card_repo.list_all()`
   - Загрузить все TopicBundle через `topic_bundle_repo.list_all()`
   - Сгруппировать по `channel_id` (берётся из `card.sources[0]`)
   - Подсчитать singleton/cluster по каждому каналу
   - Извлечь keywords из `card.keywords` (список строк в каждом TopicCard)
   - Найти пересечения keywords между каналами
   - Если `channel_id` задан — отфильтровать результат по конкретному каналу
3. Зарегистрировать MCP tool `get_cross_channel_stats` в `tg_parser/mcp_server.py`
4. Добавить pydantic-модели для ответа в mcp_server.py

**Файлы:**
- `tg_parser/services/analytics_service.py` (новый)
- `tg_parser/mcp_server.py` (новый tool)
- `tests/test_analytics_service.py` (новый)

**Оценка:** 1–2 часа

---

### Cross-dev 3: Кросс-канальная топикизация

**Проблема:** Темы формируются per-channel. Одинаковые темы в разных каналах (например, «Генная терапия CRISPR» в genotek и Lab4health) существуют изолированно. AI-агент не может найти связь между ними автоматически.

**Решение:** Связывание тем из разных каналов по семантическому сходству.

**Подход — topic linking (не merge):**
Не объединять темы (это разрушит per-channel структуру), а создать таблицу связей `topic_links` — пары тем из разных каналов с similarity score.

**Реализация:**
1. Добавить модель `TopicLink` в `tg_parser/domain/models.py`:
   ```
   topic_id_a: str
   topic_id_b: str
   similarity_score: float
   shared_keywords: list[str]
   ```
2. Создать таблицу `topic_links` (миграция) и репозиторий `TopicLinkRepo` в `tg_parser/storage/ports.py`
3. Реализовать алгоритм в `tg_parser/services/topic_linking_service.py`:
   - Для каждой пары каналов: сравнить keywords каждой темы
   - Jaccard similarity по keywords + cosine similarity по embedding средних TopicCard.summary
   - Порог: score > 0.5 → создать TopicLink
4. CLI команда `tg-parser link-topics` для запуска
5. MCP tool `get_related_topics(topic_id)` — показать связанные темы из других каналов
6. Обновить `get_topic_details` — добавить секцию `related_topics`

**Файлы:**
- `tg_parser/domain/models.py` (TopicLink)
- `tg_parser/storage/ports.py` (TopicLinkRepo)
- `tg_parser/storage/sqlalchemy/topic_link_repo.py` (новый)
- `tg_parser/services/topic_linking_service.py` (новый)
- `tg_parser/cli/app.py` (команда link-topics)
- `tg_parser/mcp_server.py` (get_related_topics, обновление get_topic_details)
- Миграция для таблицы `topic_links`

**Оценка:** 3–4 часа

---

### Cross-dev 4: Улучшение coverage

**Проблема:** Значительная часть документов не покрыта темами:
- AgeManagment: 68.3% (341 uncovered из 1075)
- labdiagnostica_logical: 76.1% (~270 uncovered из 1124)
- Lab4health: 82.0% (~323 uncovered из 1797)

**Решение:** Запустить инкрементальную топикизацию (`topicize --mode incremental`) для каналов с низким coverage.

**Реализация:** Операционная задача (не требует нового кода):
1. `docker compose run --rm -e DB_HOST=postgres tg_parser topicize --channel AgeManagment --mode incremental`
2. `docker compose run --rm -e DB_HOST=postgres tg_parser topicize --channel labdiagnostica_logical --mode incremental`
3. `docker compose run --rm -e DB_HOST=postgres tg_parser topicize --channel Lab4health --mode incremental`
4. Проверить итоговый coverage через `list_channels`

**Примечание:** Инкрементальная топикизация использует Phase 1 (keyword assign, 0 tokens) + Phase 2 (LLM discover для unassigned, Sonnet). Ожидаемый рост coverage: +10–15% на канал.

**Оценка:** 30 мин (запуск + ожидание)

---

## Порядок выполнения

1. **Cross-dev 4** (30 мин) — улучшение coverage. Операционная задача, не блокирует остальные. Запуск incremental topicization.
2. **Cross-dev 2** (1–2 часа) — кросс-канальная статистика. Создаёт фундамент (analytics_service) для Cross-dev 3.
3. **Cross-dev 3** (3–4 часа) — кросс-канальная топикизация (topic linking). Наиболее сложная задача, зависит от analytics_service.

**Общая оценка:** ~5–7 часов

---

## Критерии приёмки

- [ ] Coverage всех каналов ≥ 80%
- [ ] MCP tool `get_cross_channel_stats` возвращает аналитику по всем каналам с пересечениями keywords
- [ ] MCP tool `get_cross_channel_stats(channel_id=X)` возвращает детальную статистику по конкретному каналу
- [ ] Таблица `topic_links` содержит связи между темами разных каналов
- [ ] MCP tool `get_related_topics` показывает связанные темы из других каналов
- [ ] `get_topic_details` включает секцию `related_topics`
- [ ] Все существующие тесты проходят
- [ ] Новые тесты для analytics_service и topic_linking_service
