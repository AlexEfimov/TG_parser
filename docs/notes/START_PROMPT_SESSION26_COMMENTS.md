# 🚀 Session 26: Comments Support — Start Prompt

**Дата:** 10 февраля 2026  
**Версия:** v3.1.1 → v3.1.2  
**Приоритет:** Medium  
**Оценка:** ~6-8 часов разработки

---

## 🎯 Цель Session 26

Завершить и протестировать поддержку комментариев к постам Telegram каналов.

**Статус:** Функционал на ~80% готов, нужно протестировать, оптимизировать и документировать.

---

## 📊 Текущее состояние

### ✅ Что УЖЕ реализовано

#### 1. Domain Models (100% готово)
- ✅ `MessageType.COMMENT` enum
- ✅ `RawTelegramMessage` с полями:
  - `message_type: MessageType` (POST | COMMENT)
  - `parent_message_id: str | None`
  - `thread_id: str | None`
- ✅ Все downstream модели поддерживают comments:
  - `ProcessedDocument`
  - `TopicCard` → `Anchor`
  - `TopicBundle` → `BundleItem`
  - `KnowledgeBaseEntry`

#### 2. Telethon Client (100% готово)
- ✅ `TelethonClient.get_comments()` метод реализован
  ```python
  async def get_comments(
      channel_id: str,
      post_id: int,
      limit: int | None = None,
      min_id: int | None = None,
  ) -> AsyncIterator[RawTelegramMessage]
  ```
- ✅ Правильное преобразование Telethon Message → RawTelegramMessage
- ✅ Обработка `thread_id`, `parent_message_id` (TR-6)
- ✅ Error handling для "comments are disabled"

#### 3. Orchestrator (90% готово)
- ✅ `IngestionOrchestrator._ingest_comments()` метод реализован
- ✅ Сбор комментариев для всех постов канала
- ✅ Per-thread cursor management (TR-7, TR-10)
- ✅ Обработка флага `comments_unavailable`
- ⚠️ **Проблема:** Сбор комментариев для ВСЕХ постов (неэффективно)

#### 4. Storage (100% готово)
- ✅ `Source.include_comments: bool` — флаг включения комментариев
- ✅ `Source.comments_unavailable: bool` — флаг недоступности комментариев
- ✅ `IngestionStateRepo.get_comment_cursor(source_id, thread_id)` — получить курсор треда
- ✅ `IngestionStateRepo.update_cursors(source_id, comment_cursors)` — обновить курсоры тредов
- ✅ Database schemas поддерживают comments:
  - `ingestion_state.sqlite` → `sources` table с `include_comments`, `comments_unavailable`
  - `raw_storage.sqlite` → `raw_messages` поддерживает `message_type`, `parent_message_id`, `thread_id`

#### 5. CLI (100% готово)
- ✅ `add-source --include-comments` флаг работает
- ✅ `ingest` команда автоматически собирает комментарии если `include_comments=True`

#### 6. Processing/Topicization/Export (работают из коробки)
- ✅ `ProcessingPipeline` обрабатывает любой `RawTelegramMessage` (posts + comments)
- ✅ `TopicizationPipeline` работает с любыми `ProcessedDocument` (posts + comments)
- ✅ `ExportPipeline` экспортирует все `message_type` корректно

---

## 🎯 Что нужно сделать в Session 26

### 1. Testing (2-3 часа)

#### Real Channel Testing
- [ ] Найти Telegram канал с активными комментариями
- [ ] Добавить источник: `add-source --include-comments`
- [ ] Запустить полный pipeline: `run --source <channel>`
- [ ] Проверить:
  - Комментарии собираются
  - Processing работает
  - Export корректный
  - Thread structure сохраняется

#### Edge Cases Testing
- [ ] Канал без комментариев (comments disabled)
- [ ] Пост без комментариев (empty thread)
- [ ] Вложенные комментарии (replies to comments)
- [ ] Incremental mode (новые комментарии после первого запуска)

### 2. Bug Fixes & Improvements (2-3 часа)

#### Orchestrator Optimization
**Проблема:** `_ingest_comments()` собирает комментарии для ВСЕХ последних 100 постов.  
**Решение:** Фильтровать посты с комментариями по `replies` count в `raw_payload`.

```python
# В orchestrator._ingest_comments()
for raw_msg in raw_messages:
    # Проверяем наличие комментариев в raw_payload
    if raw_msg.raw_payload and raw_msg.raw_payload.get("replies"):
        replies_count = raw_msg.raw_payload["replies"]
        if replies_count > 0:
            # Собираем комментарии только для постов с replies
            ...
```

#### Storage Methods
- [ ] Добавить `RawMessageRepo.list_posts_with_comments(channel_id)` для оптимизации
- [ ] Добавить `RawMessageRepo.get_comments_for_post(thread_id)` для удобства
- [ ] Добавить `ProcessedDocumentRepo.list_comments(channel_id)` для фильтрации

#### Error Handling
- [ ] Улучшить обработку Telethon ошибок в `get_comments()`
- [ ] Добавить логирование для debug комментариев
- [ ] Graceful degradation если comments недоступны

### 3. Export Verification (1 час)

#### kb_entries.ndjson Format
Проверить что комментарии экспортируются с правильными полями:

```json
{
  "id": "kb:msg:tg:channel123:comment:456",
  "source": {
    "type": "telegram_message",
    "channel_id": "channel123",
    "message_id": "456",
    "message_type": "comment",
    "source_ref": "tg:channel123:comment:456"
  },
  "metadata": {
    "telegram_url": "https://t.me/channel123/123?comment=456",
    "parent_message_id": "123",
    "thread_id": "123"
  }
}
```

#### Topic Cards Format
Проверить что комментарии включаются в topics:

```json
{
  "anchors": [
    {
      "channel_id": "channel123",
      "message_id": "456",
      "message_type": "comment",
      "anchor_ref": "tg:channel123:comment:456",
      "parent_message_id": "123",
      "thread_id": "123"
    }
  ]
}
```

### 4. Tests (2-3 часа)

#### Unit Tests (8-10 тестов)
- `test_telethon_client_comments.py`:
  - `test_get_comments_success()`
  - `test_get_comments_empty_thread()`
  - `test_get_comments_disabled()`
  - `test_get_comments_incremental()`
  - `test_convert_comment_message()`

#### Integration Tests (5-7 тестов)
- `test_orchestrator_comments.py`:
  - `test_ingest_comments_success()`
  - `test_ingest_comments_unavailable()`
  - `test_ingest_comments_cursor_tracking()`
  - `test_ingest_comments_per_thread()`

#### E2E Tests (2-3 теста)
- `test_e2e_comments_pipeline.py`:
  - `test_full_pipeline_with_comments()`
  - `test_incremental_comments()`
  - `test_export_comments_format()`

### 5. Documentation (1 час)

#### USER_GUIDE.md
Добавить секцию "Working with Comments":

```markdown
## 📝 Working with Comments

### Enable Comments Collection

```bash
# При добавлении источника
python -m tg_parser.cli add-source \
  --source-id my_channel \
  --channel-id @my_channel \
  --include-comments  # ← включить комментарии

# Полный pipeline с комментариями
python -m tg_parser.cli run \
  --source my_channel \
  --out ./output
```

### Comments in Output

Комментарии экспортируются в `kb_entries.ndjson` с:
- `message_type: "comment"`
- `parent_message_id` — ID родительского поста
- `thread_id` — ID треда обсуждения

### Limitations

- Comments collection может быть медленным для каналов с большим количеством постов
- Некоторые каналы имеют отключенные комментарии (будет установлен флаг `comments_unavailable`)
```

#### README.md
- Добавить примеры с `--include-comments`
- Обновить Quick Start секцию

#### CHANGELOG.md
```markdown
## [3.1.2] - 2026-02-10

### Added

#### Comments Support (Session 26) ⭐
- **Comments Collection** — полная поддержка сбора комментариев из Telegram
  - CLI флаг `--include-comments` при добавлении источника
  - Incremental сбор новых комментариев
  - Per-thread cursor tracking
  - Graceful handling когда комментарии недоступны
- **Comments Processing** — обработка комментариев через LLM pipeline
  - Автоматическая обработка как постов
  - Thread context preservation
- **Comments Export** — комментарии в kb_entries.ndjson
  - `message_type: "comment"`
  - Thread metadata (parent_message_id, thread_id)
  - Telegram URLs с комментариями

### Changed
- Оптимизирован сбор комментариев (только для постов с replies)
- Улучшен error handling для "comments disabled"

### Tests
- **15 новых тестов** для comments support
- Общее количество тестов: **426** (было 411)
```

---

## 📋 Technical Details

### Thread Structure

```
Post (message_id=123)
├── Comment 1 (message_id=456, parent_message_id=123, thread_id=123)
├── Comment 2 (message_id=457, parent_message_id=123, thread_id=123)
└── Comment 3 (message_id=458, parent_message_id=456, thread_id=123)  # reply to Comment 1
```

### Cursor Management

Per-thread cursors хранятся в `ingestion_state.sqlite`:

```sql
-- TR-10: per-thread cursor tracking
comment_cursors: {
  "thread_123": "458",  -- last comment_id in thread 123
  "thread_456": "789",  -- last comment_id in thread 456
}
```

### Performance Considerations

- **Проблема:** Сбор комментариев для всех постов медленный
- **Решение:** Фильтровать посты по `replies` count > 0
- **Оптимизация:** Собирать комментарии только для последних N постов (configurable)

---

## ✅ Success Criteria

Session 26 считается успешным если:

1. ✅ **Функционал работает:**
   - Комментарии собираются из реальных каналов
   - Processing/topicization/export работают с комментариями
   - Incremental mode работает корректно

2. ✅ **Edge cases обработаны:**
   - "Comments disabled" не роняет pipeline
   - Empty threads не вызывают ошибок
   - Nested replies работают корректно

3. ✅ **Тесты написаны:**
   - 15+ новых тестов (unit + integration + e2e)
   - 100% pass rate
   - Coverage для comments logic

4. ✅ **Документация готова:**
   - USER_GUIDE.md с примерами comments
   - README.md обновлён
   - CHANGELOG.md обновлён

5. ✅ **Production ready:**
   - Оптимизация сбора комментариев
   - Правильный error handling
   - Graceful degradation

---

## 🔧 Development Commands

```bash
# 1. Добавить канал с комментариями
python -m tg_parser.cli add-source \
  --source-id test_comments \
  --channel-id @durov \
  --channel-username durov \
  --include-comments

# 2. Собрать посты + комментарии
python -m tg_parser.cli ingest \
  --source test_comments \
  --mode snapshot \
  --limit 10

# 3. Обработать (postsкомментарии)
python -m tg_parser.cli process \
  --channel durov

# 4. Экспортировать
python -m tg_parser.cli export \
  --channel durov \
  --out ./output_comments \
  --pretty

# 5. Проверить результат
cat ./output_comments/kb_entries.ndjson | jq 'select(.source.message_type == "comment")'
```

---

## 🎓 Expected Outcomes

После Session 26:

- ✅ **v3.1.2 Released** с полной поддержкой комментариев
- ✅ **426+ тестов** (было 411)
- ✅ **Production tested** на реальных каналах с комментариями
- ✅ **Documentation complete** с примерами и limitations

---

## 📚 References

### Technical Requirements
- TR-5: Comments collection support
- TR-6: Thread structure (parent_message_id, thread_id)
- TR-7: Per-thread cursor tracking
- TR-8: Idempotent comment storage
- TR-10: Comment cursor persistence

### Related Files
- `tg_parser/ingestion/telegram/telethon_client.py` — Telethon integration
- `tg_parser/ingestion/orchestrator.py` — Ingestion orchestration
- `tg_parser/domain/models.py` — Domain models
- `tg_parser/storage/ports.py` — Storage interfaces

### Documentation
- `docs/USER_GUIDE.md` — User documentation
- `CHANGELOG.md` — Change log
- `README.md` — Project overview

---

**Ready to start! 🚀**

**Next:** Начать с тестирования существующего функционала на реальном канале.
