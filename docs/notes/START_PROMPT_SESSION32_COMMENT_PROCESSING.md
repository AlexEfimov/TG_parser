# Session 32: Улучшение обработки комментариев

**Дата:** 23 марта 2026  
**Версия:** v3.5.0 → v3.6.0  
**Приоритет:** P3  
**Оценка:** ~3-4 часа разработки  
**Предыдущие сессии:** Session 30 (Incremental), Session 31 (Parallel processing)

---

## Цель Session 32

Добиться **100% обработки всех сообщений** (включая комментарии) и повысить качество processing для комментариев за счёт контекста родительского поста. Сейчас:

1. **2 failure** (`comment:154`, `comment:4057`) — media-only комментарии с пустым текстом
2. **Промпт не знает**, что обрабатывает комментарий — нет контекста поста
3. **~31% комментариев < 50 символов** — короткие реплики обрабатываются тем же промптом что и длинные посты
4. **Ingestion пропускает media-only посты**, но **не пропускает media-only комментарии** — асимметрия

Результат: 1130/1130 processed (100%), комментарии обогащены контекстом.

---

## Диагностика проблемы

### 1. Два failing комментария — media-only сообщения

**`comment:154`** — фото без текста:
```
source_ref: tg:labdiagnostica_logical:comment:154
text: "" (пустая строка)
thread_id: 97 (принадлежит посту 97)
parent_message_id: 153 (ответ на комментарий 153)
media: {has_photo: True, type: MessageMediaPhoto}
```

**`comment:4057`** — голосовое сообщение без текста:
```
source_ref: tg:labdiagnostica_logical:comment:4057
text: "" (пустая строка)
thread_id: 58 (принадлежит посту 58)
parent_message_id: 4055 (ответ на комментарий 4055)
media: {has_document: True, mime_type: audio/ogg, size_bytes: 4555120}
```

**Причина failure:** `_validate_llm_response()` проверяет `if not response["text_clean"]` — пустая строка отклоняется. LLM получает пустой текст, не может произвести `text_clean`.

### 2. Асимметрия фильтрации при ingestion

`get_messages()` (посты):
```python
if not message.text and not message.message:
    continue  # ← Пропускает media-only посты
```

`get_comments()`:
```python
async for message in self.client.iter_messages(channel_id, **iter_kwargs):
    raw_msg = await self._convert_message(...)
    yield raw_msg  # ← Пропускает ВСЕ комментарии, включая media-only
```

### 3. Промпт не осведомлён о контексте

Текущий user template:
```
Process this Telegram message:

---
{text}
---

Extract structured information as JSON.
```

Промпт:
- Не знает, что это комментарий (а не пост)
- Не знает контекст родительского поста
- Не знает, что сообщение может быть коротким/пустым/медийным
- Одинаковый для 4000-символьного поста и для "?" / "👍" / ""

### 4. Статистика комментариев

| Метрика | Значение |
|---------|----------|
| Посты | 906 |
| Комментарии | 224 |
| Комментарии с пустым текстом | 2 (media-only) |
| Комментарии < 10 символов | 21 (9.4%) |
| Комментарии < 50 символов | 70 (31.3%) |
| Средняя длина комментария | 169 символов |
| Все комментарии имеют thread_id | 100% |
| Все комментарии имеют parent_message_id | 100% |

---

## Обязательные документы для изучения

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| `tg_parser/processing/pipeline.py` | `_validate_llm_response`, `_process_single_message`, `process_message` | ⭐⭐⭐ |
| `tg_parser/processing/prompts.py` | Текущие промпты — нужна доработка | ⭐⭐⭐ |
| `prompts/processing.yaml` | YAML-версия промптов | ⭐⭐⭐ |
| `tg_parser/ingestion/telegram/telethon_client.py` | `get_comments()`, `_convert_message()` — фильтрация media-only | ⭐⭐ |
| `tg_parser/domain/models.py` | `RawTelegramMessage`, `MessageType`, `ProcessedDocument` | ⭐⭐ |
| `tg_parser/services/processing_service.py` | `run_processing()` — здесь доступны raw_repo и processed_repo | ⭐⭐ |
| `tg_parser/processing/prompt_loader.py` | `PromptLoader`, `get_prompt_loader()` — загрузка промптов v1.2 | ⭐ |
| `tg_parser/storage/ports.py` | `RawMessageRepo.get_by_source_ref()` — для загрузки родительского поста | ⭐ |

---

## Scope Session 32

### 1. Обработка media-only комментариев (fix 2 failures)

**Вариант A (рекомендуется):** Генерировать синтетический `text_clean` для media-only сообщений **до** вызова LLM:

В `_process_single_message()` или в начале `process_message()`:
```python
if not message.text or not message.text.strip():
    media = (message.raw_payload or {}).get("media")
    if media:
        media_type = media.get("type", "unknown")
        # Формируем дескриптор: "[Фото]", "[Голосовое сообщение]", "[Документ]"
        text_clean = _describe_media(media)
        # Возвращаем ProcessedDocument без вызова LLM
        return self._build_media_only_document(message, text_clean)
    else:
        # Пустое сообщение без медиа — skip или минимальный документ
        ...
```

**Вариант B:** Сделать `text_clean` optional для media-only — изменить `_validate_llm_response()`.

**Вариант C:** Фильтровать media-only комментарии при ingestion (как для постов). Минус: потеря данных.

### 2. Контекст родительского поста при обработке комментария

Для комментариев — загружать текст родительского поста и передавать в промпт. Это значительно улучшит качество summary/topics для коротких ответов.

**В `process_message()` или `_process_single_message()`:**
```python
parent_context = None
if message.message_type == MessageType.COMMENT and message.thread_id:
    parent_ref = f"tg:{message.channel_id}:post:{message.thread_id}"
    parent_doc = await self.processed_doc_repo.get_by_source_ref(parent_ref)
    if parent_doc:
        parent_context = parent_doc.text_clean[:500]  # ограничиваем размер
```

**Проблема:** `process_message()` сейчас не имеет доступа к `raw_repo` (только `processed_doc_repo`). Варианты:
- Использовать `processed_doc_repo.get_by_source_ref(parent_ref)` — берём `text_clean` из уже обработанного поста (работает если пост обработан раньше комментария — что гарантировано порядком)
- Добавить `raw_repo` в pipeline constructor

### 3. Дифференцированный промпт для комментариев

Добавить второй user template в `prompts.py` и `processing.yaml`:

```yaml
user_comment:
  template: |
    Process this Telegram comment (reply to a post).

    --- PARENT POST ---
    {parent_text}
    --- END PARENT POST ---

    --- COMMENT ---
    {text}
    --- END COMMENT ---

    Extract structured information as JSON.
    For short comments (reactions, agreement, questions), use the parent post context
    to determine topics and generate a meaningful summary.

  variables:
    - text
    - parent_text
```

System prompt — добавить инструкции для комментариев:
```
Additional rules for comments:
- For very short comments (emojis, "?", one-word replies), infer context from parent post
- text_clean should preserve the original comment text, even if short
- summary should reflect what the comment adds to the discussion
- topics should be inherited from parent post when the comment is a reaction
```

### 4. Обработка коротких комментариев

Для комментариев < N символов (например, 10) — не тратить LLM вызов, а формировать ProcessedDocument программно:

```python
if message.message_type == MessageType.COMMENT and len(message.text.strip()) < 10:
    return self._build_short_comment_document(message, parent_context)
```

Или оставить LLM, но с обогащённым промптом (п.3) — LLM справится, если видит контекст поста.

### 5. Тесты

- Тест: media-only комментарий обрабатывается без ошибки
- Тест: короткий комментарий ("?", "👍") обрабатывается корректно
- Тест: комментарий получает контекст родительского поста в промпте
- Тест: обратная совместимость — посты обрабатываются как раньше
- Тест: 100% processed на реальном канале (0 failures)

---

## Конфигурация

Изменения в `.env` (опционально):

```env
# Порог для short-path обработки комментариев (без LLM)
PROCESSING_COMMENT_MEDIA_ONLY_MODE=synthetic    # synthetic | skip | error
# Максимальная длина контекста родительского поста в промпте
PROCESSING_PARENT_CONTEXT_MAX_CHARS=500
```

---

## Техническое состояние

### База данных (после Session 31)

```
PostgreSQL 16 (Homebrew): localhost:5432/tg_parser
├── sources (1 запись: labdiagnostica, status=active)
├── raw_messages (1130 записей: 906 постов + 224 комментария)
├── processed_documents (1128 записей)
├── topic_cards (64 записи)
├── topic_bundles (64 записи)
├── processing_failures (2 записи: comment:154, comment:4057)
└── source_attempts (11+ записей)
```

### LLM конфигурация

```
PROCESSING_LLM_PROVIDER=anthropic
PROCESSING_LLM_MODEL=claude-haiku-4-5-20251001
PROCESSING_CONCURRENCY=20
PROCESSING_RATE_LIMIT_RPM=1000
```

### Тесты

```
314 passed, 8 skipped, 2 pre-existing failures
Failing: test_full_pipeline_e2e, test_comments_ingestion_with_per_thread_cursors
```

### Ключевые изменения Session 31

- `processing_concurrency` в Settings — подхватывает `PROCESSING_CONCURRENCY` из `.env`
- Concurrency пробрасывается через всю цепочку: CLI → pipeline_service → processing_service → pipeline
- `_db_lock` в pipeline для защиты SQLAlchemy сессии при параллельных записях
- `suggest_processing_concurrency()` интегрирован — rate limiter адаптивно снижает параллелизм
- Верификация: 1130 сообщений за 6:33 при concurrency=10 (ускорение ~6x)

---

## Ограничения

1. **Медиа-контент не доступен** — TR-19: скачиваем только метаданные, не файлы. Голосовые сообщения нельзя транскрибировать (нет аудио).
2. **Порядок обработки** — при `--force` посты и комментарии обрабатываются параллельно. Если комментарию нужен контекст уже обработанного поста, надо гарантировать что пост обработан первым, или загружать сырой текст из raw_repo.
3. **Обратная совместимость** — обработка постов не должна измениться. Все существующие тесты должны проходить.
4. **Промпт-версионирование** — при изменении промпта меняется `prompt_id` (SHA256), что ожидаемо.

---

## Критерии завершения Session 32

### Must Have:
- [ ] 0 failures при `tg-parser process --channel labdiagnostica_logical --force`
- [ ] Media-only комментарии обрабатываются (synthetic text_clean)
- [ ] Комментарии получают контекст родительского поста в промпте
- [ ] Дифференцированный промпт для комментариев vs постов
- [ ] Существующие тесты проходят (314+)

### Should Have:
- [ ] Новые тесты: media-only, short comment, parent context, backward compat
- [ ] Верификация на реальном канале: 1130/1130 processed
- [ ] Логирование: "Processing comment with parent context from post:XXX"
- [ ] `processing.yaml` обновлён с comment template

### Nice to Have:
- [ ] Настройки в `.env`: `PROCESSING_PARENT_CONTEXT_MAX_CHARS`
- [ ] Метрика: кол-во комментариев обработанных с/без контекста
- [ ] Short-path для emoji-only комментариев (без LLM вызова)

---

## Начало работы

1. Изучить документы из раздела "Обязательные документы"
2. Запустить тесты: `.venv/bin/python -m pytest tests/ -q --ignore=tests/test_agents.py --ignore=tests/test_multi_agent.py --ignore=tests/test_gpt5_responses_api.py --ignore=tests/test_llm_clients.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_postgres_integration.py`
3. Начать реализацию: media-only handling → parent context loading → comment prompt → tests → верификация
