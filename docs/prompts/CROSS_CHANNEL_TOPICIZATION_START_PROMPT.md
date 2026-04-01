# Стартовый промпт: Кросс-канальная инкрементальная топикизация

## Задача

Реализовать гибридную кросс-канальную инкрементальную топикизацию по готовому плану:
`.cursor/plans/cross-channel_incremental_topicization_243663c9.plan.md`

Прочитай план целиком перед началом работы — он содержит архитектуру, диаграммы, конкретные файлы, сигнатуры функций и порядок реализации.

## Контекст

TG_parser — система для парсинга Telegram-каналов, обработки контента через LLM, семантического поиска и RAG Q&A. Взаимодействие с AI-агентом через MCP-сервер.

**Текущее состояние:**
- 5 каналов подключено, ~5070 processed documents, ~400+ TopicCards
- Инкрементальная топикизация работает **per-channel**: новые сообщения проверяются только против тем своего канала
- Кросс-канальные TopicLinks уже реализованы (264 связи) — но они post-hoc, не влияют на процесс назначения
- Coverage: 68–82% по каналам

**Что нужно сделать (суть):**
Сейчас, когда приходит новое сообщение, оно проверяется только против тем своего канала. Нужно добавить:
1. **Phase 2 Enhancement:** LLM при поиске/создании тем видит темы ВСЕХ каналов (как контекст для предотвращения дубликатов)
2. **Phase 3 (новая):** После назначения документа на тему своего канала, автоматически создаются TopicLinks к похожим темам из других каналов
3. Фича управляется настройкой `cross_channel_topicization` (по умолчанию включена)

**Ключевой принцип:** документ ВСЕГДА остаётся в теме своего канала. Кросс-канальные связи выражаются только через TopicLinks.

## Ключевые файлы (в порядке приоритета изменений)

| Файл | Что менять |
|------|-----------|
| `tg_parser/config/settings.py` | +2 настройки: `cross_channel_topicization`, `cross_channel_link_threshold` |
| `tg_parser/domain/models.py` | +1 поле `cross_channel_links_created` в `IncrementalTopicizeResult` |
| `tg_parser/processing/topicization_prompts.py` | Расширить промпт `build_incremental_discover_prompt` для кросс-канального контекста |
| `tg_parser/processing/topicization.py` | Прокинуть `cross_channel_topics` через `discover_new_topics` → `_discover_single_batch` |
| `tg_parser/services/topicization_service.py` | Новая функция `_run_cross_channel_linking` + интеграция Phase 3 в `run_incremental_topicization` |
| `tg_parser/services/db_context.py` | Расширить context manager для Phase 3 (TopicLinkRepo + EmbeddingRepo) |
| `tg_parser/cli/app.py` | Флаг `--cross-channel/--no-cross-channel` |
| `tests/test_cross_channel_topicization.py` | Новые тесты |

## Существующий код для переиспользования

- `tg_parser/services/topic_linking_service.py` — функции `_jaccard_similarity`, `_cosine_similarity`, `_extract_keywords` (импортировать, не дублировать)
- `tg_parser/services/analytics_service.py` — `_extract_keywords` для извлечения ключевых слов из TopicCard
- `tg_parser/storage/sqlalchemy/topic_link_repo.py` — `SATopicLinkRepo` для сохранения TopicLinks
- `tg_parser/services/db_context.py` — `topic_linking_repos()` context manager уже есть

## Порядок реализации

Выполняй задачи последовательно, проверяя lint после каждого шага:

1. Settings + domain model (простые изменения, разблокируют остальное)
2. Промпты (topicization_prompts.py)
3. Pipeline (topicization.py — прокинуть параметр)
4. Phase 3 + оркестрация (topicization_service.py — основная логика)
5. db_context (расширить context manager)
6. CLI (флаг)
7. Тесты
8. Запуск тестов: `.venv/bin/pytest tests/ -v`

## Ограничения

- Не ломать существующие per-channel тесты
- Не менять поведение при `cross_channel_topicization=False` — должно работать как раньше
- Импортировать `_jaccard_similarity` / `_cosine_similarity` из `topic_linking_service.py`, не дублировать
- Тесты запускать через `.venv/bin/pytest` (не через `python -m pytest`)
- Два pre-existing failing теста (`test_e2e_pipeline::test_run_command_with_skip_options`, `test_retry_settings::test_retry_settings_integration_with_pipeline`) — игнорировать, они не связаны с этой задачей
- Обновить `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` после завершения
