# Стартовый промпт: Cross-dev — кросс-канальные улучшения

## Задача

Реализовать три задачи фазы Cross-dev для улучшения мультиканальности TG_parser. Подробный план: `docs/notes/CROSS_DEV_PLAN.md`.

## Контекст

TG_parser — система для парсинга Telegram-каналов, обработки контента через LLM, семантического поиска и RAG Q&A. Работает в Docker (docker-compose.yml). Взаимодействие с AI-агентом через MCP-сервер.

**Текущее состояние:**
- 5 каналов подключено: labdiagnostica_logical, AgeManagment, genotek, Lab4health, plus один тестовый
- ~5070 processed documents, ~382 TopicCards, embedding выполнен для всех
- Coverage: AgeManagment 68%, labdiagnostica 76%, Lab4health 82%, genotek 81%
- Фазы D1–D3, Perf, Cross-val выполнены
- Код упакован в Docker image (не bind-mount), для изменений кода нужен `docker compose build tg_parser`
- Для запуска CLI в Docker: `docker compose run --rm -e DB_HOST=postgres tg_parser <command>`

## Ключевые файлы

- `tg_parser/mcp_server.py` — MCP tools (search, ask_question, list_topics, list_channels, get_topic_details и т.д.)
- `tg_parser/services/retrieval_service.py` — поиск и RAG
- `tg_parser/processing/topicization.py` — логика топикизации (TopicizationPipelineImpl)
- `tg_parser/services/topicization_service.py` — запуск топикизации (run_topicization, run_incremental_topicization)
- `tg_parser/domain/models.py` — доменные модели (TopicCard, TopicBundle, ProcessedDocument и т.д.)
- `tg_parser/storage/ports.py` — интерфейсы репозиториев
- `tg_parser/cli/app.py` — CLI commands
- `tg_parser/services/db_context.py` — async context managers для доступа к репозиториям
- `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — актуальный roadmap

## Задачи (выполнять последовательно)

### 1. Cross-dev 4: Улучшение coverage (~30 мин)

Запустить incremental topicization для каналов с низким coverage:
```
docker compose run --rm -e DB_HOST=postgres tg_parser topicize --channel AgeManagment --mode incremental
docker compose run --rm -e DB_HOST=postgres tg_parser topicize --channel labdiagnostica_logical --mode incremental
docker compose run --rm -e DB_HOST=postgres tg_parser topicize --channel Lab4health --mode incremental
```
Затем проверить coverage через MCP tool `list_channels`. Цель: ≥ 80% по всем каналам.

### 2. Cross-dev 2: Кросс-канальная статистика (1–2 часа)

Создать новый MCP tool `get_cross_channel_stats(channel_id=None)`:
- Новый файл `tg_parser/services/analytics_service.py` — функция `get_cross_channel_analytics(channel_id=None)`
- Загрузить все TopicCard и TopicBundle
- Сгруппировать статистику по каналам (singleton/cluster count, keywords)
- Найти пересечения keywords между каналами
- Если `channel_id` задан — вернуть детальную статистику по конкретному каналу; если не задан — агрегированную кросс-канальную аналитику
- **Важно:** Все существующие MCP tools поддерживают опциональный `channel_id` (search, ask_question, list_topics). Новый tool должен следовать этому паттерну.
- Зарегистрировать tool в `tg_parser/mcp_server.py` с pydantic-моделями ответа
- Написать тесты в `tests/test_analytics_service.py`

### 3. Cross-dev 3: Кросс-канальная топикизация (3–4 часа)

Связывание тем из разных каналов по семантическому сходству:
- Модель `TopicLink` в `tg_parser/domain/models.py`
- Таблица `topic_links` + SQLAlchemy миграция
- `TopicLinkRepo` в storage
- `tg_parser/services/topic_linking_service.py` — Jaccard по keywords + cosine по embedding
- CLI команда `tg-parser link-topics`
- MCP tool `get_related_topics(topic_id)`
- Обновить `get_topic_details` — добавить `related_topics`

## Важные ограничения

- **Per-channel фильтрация:** Все MCP tools поддерживают опциональный `channel_id`. Новые tools должны следовать этому паттерну — работать как в кросс-канальном режиме (без `channel_id`), так и в режиме одного канала (с `channel_id`).
- Для любых изменений кода требуется `docker compose build tg_parser` перед тестированием в Docker
- Обновить `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` по мере выполнения задач
- Не объединять темы из разных каналов — только linking (связи)
- Использовать существующие async context managers из `tg_parser/services/db_context.py`
- Тесты запускать через `pytest` (проверить что все существующие тесты проходят)
