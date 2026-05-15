# tg-parser — Bug Report

**Period:** 2026-05-14 session
**Reporter:** alexanderefimov
**Total issues:** 11 (1 отозван, 10 активных)

---

## Index

| # | Title | Severity | Type |
|---|---|---|---|
| 1 | `trigger_pipeline` через MCP — silent no-op | High | Architecture |
| 2 | Нет observability для silent failure в MCP | Medium | Observability |
| ~~3~~ | ~~`--skip-topicize` оставлен после mitigation~~ | — | **Retracted (by design)** |
| 3' | Misleading log message про `--skip-topicize` | Low | UX |
| 4 | `last_attempt_at` не пишется при работе scheduler | Medium | Observability |
| 5 | Retry без изменения промпта для JSON-parsing ошибок | Medium | Cost/Reliability |
| 6 | HTTP 520 errors от Anthropic API без exp.backoff | Low | Reliability |
| 7 | CLI `topicize` рапортует ✅ при тотальном fail | High | UX/Safety |
| 8 | `get_cross_channel_stats` не использует `topic_links` | Medium | Data integrity |
| 9 | Keywords не лемматизированы — дублирование оверлапов | Low | Data quality |
| 10 | `subscribe_*` не идемпотентны — повторный вызов создаёт дубль | Medium | API contract |
| 11 | «Topic failed quality criteria, skipping» — отбрасывание без деталей | Low | Observability |

---

## ISSUE-1 (High): `trigger_pipeline` через MCP — silent no-op

### Симптом

`trigger_pipeline(channel_id=...)` через MCP всегда возвращает `{triggered: true}`, но в логах основного контейнера `tg_parser` нет ни одной строки про запрошенный канал. Воспроизведено дважды (~05:43 UTC и ~06:00 UTC, см. investigation log) для канала `profendocrinologist`. Канал был обработан только при штатном тике `incremental_pipeline` в 06:28 UTC.

### Root cause (подтверждён архитектурно)

MCP-сервер живёт в отдельном контейнере `tg_parser_mcp`, шедулер и пайплайн — в контейнере `tg_parser`. У контейнеров нет общего канала связи, через который MCP мог бы триггернуть APScheduler в `tg_parser`. Вероятно `trigger_pipeline` запускает `asyncio.create_task` локально в MCP, но:
- task гибнет при возврате ответа на MCP-запрос (event loop замыкается)
- даже если выживает — у MCP нет Telethon-клиента с правильной session

### Suggested fix

`trigger_pipeline` в MCP должен делать HTTP-вызов в API `tg_parser` (`http://tg_parser:8000/...`), который добавляет one-shot job в APScheduler. HTTP API в `tg_parser` уже есть (видно по `docker compose ps`).

### Affected files

- `tg_parser/mcp/tools.py` — handler `trigger_pipeline`
- `tg_parser/api/main.py` — нужен эндпоинт `POST /pipeline/trigger`
- `tg_parser/services/scheduler_service.py` — метод для добавления one-shot job
- `docker-compose.yml` — проверить network reachability

### Acceptance

- После `triggered: true` в логах `tg_parser` в течение 60 сек появляется `Starting ingestion: source=<channel>`

---

## ISSUE-2 (Medium): нет observability для silent failure в MCP

### Симптом

Сейчас `trigger_pipeline` возвращает `triggered: true` без какой-либо гарантии и без логирования. Нет:
- лога «MCP received trigger_pipeline for X»
- лога «enqueued / dispatched / failed to dispatch»
- записи в `sources.last_attempt_at` синхронно до возврата

### Suggested fix

1. Логировать каждый вызов `trigger_pipeline` в MCP с уровнем INFO: `mcp_trigger_pipeline_received {channel_id}`
2. Логировать результат диспетчеризации: `mcp_trigger_pipeline_dispatched {channel_id, dispatch_method, status}`
3. Внешний try/except на любой фоновой задаче, которую `trigger_pipeline` создаёт — в `except` писать `last_error` и `fail_count++`
4. Инвариант: `triggered: true` → в течение 60 сек либо `last_attempt_at IS NOT NULL`, либо `last_error IS NOT NULL`

### Acceptance

- Integration-тест: моком ломаем диспетчеризацию → `last_error` заполнен или `triggered: false`

---

## ISSUE-3 (Retracted)

~~`--skip-topicize` оставлен после mitigation~~

Это не баг. Найден `tg_parser/services/scheduler_service.py:112`:
```python
skip_topicize=True,
```

Хардкод — **архитектурное решение**: топикизация дорогая, шедулер тикает раз в час, делать топикизацию на каждом тике расточительно. Топикизация выводится в отдельный manual workflow через CLI `tg-parser topicize <channel>`.

---

## ISSUE-3' (Low): misleading log message

### Симптом

Шедулер логирует:
```
[3/4] Topicization skipped (--skip-topicize)
```

Звучит как «пользователь передал флаг» (runtime-опция, которую можно поменять). Реальный смысл: «шедулер не делает топикизацию by design». В результате час потрачен на гипотезу «флаг забыли снять после billing incident».

### Suggested fix

Заменить на:
```
[3/4] Topicization skipped (scheduler does not auto-topicize by design;
       run 'tg-parser topicize <channel>' manually)
```

Или сделать топикизацию опцией шедулера с дефолтом False и env-переменной `SCHEDULER_AUTO_TOPICIZE` — тогда лог-сообщение естественно: `Topicization skipped (SCHEDULER_AUTO_TOPICIZE=false)`.

### Affected files

- `tg_parser/services/pipeline_service.py:236`

---

## ISSUE-4 (Medium): `last_attempt_at` не обновляется при работе шедулера

### Симптом

После успешного прогона `profendocrinologist` шедулером в 06:28-06:30 UTC `get_pipeline_status` показал:
```json
{
  "last_attempt_at": null,
  "last_success_at": "2026-05-14T06:30:47",
  "fail_count": 0,
  "last_error": null
}
```

`last_success_at` заполнен, но `last_attempt_at` остался `null`. Логически это невозможно: success без attempt.

Также `last_success_at` фиксирует завершение **первого этапа** (ingest), а не всего пайплайна (4 этапа).

### Root cause hypothesis

Поля обновляются только определёнными code paths (вероятно — только при manual trigger или legacy flow), но не везде.

### Suggested fix

1. Инвариант: при старте любого этапа пайплайна — синхронно пишем `last_attempt_at = now()` **до** первого await
2. `last_success_at` обновлять только после **всего** пайплайна, не первого этапа
3. Добавить отдельное `last_stage_*` для отслеживания прогресса по этапам

### Affected files

- `tg_parser/services/scheduler_service.py`
- `tg_parser/services/pipeline_service.py`
- `tg_parser/persistence/sources.py`

---

## ISSUE-5 (Medium): retry без изменения промпта при JSON parse errors

### Симптом

При обработке `profendocrinologist` LLM возвращал невалидный JSON:
```
post:1799 attempt 1 → "Invalid JSON response from LLM: Expecting ',' delimiter: line 2 column 435"
post:1799 attempt 2 → тот же error
post:1799 attempt 3 → тот же error → parallel_message_processing_failed
```

`max_attempts=3`, но **повторяется тот же промпт без изменений**. Гарантированный детерминированный фейл за 3 попытки и ~18 секунд накладных расходов.

### Suggested fix

Несколько опций (от лёгких к серьёзным):
1. **Tool use / structured output mode** Anthropic API — гарантирует валидный JSON со стороны провайдера. Самое надёжное.
2. **Retry с hint'ом**: «previous response had JSON parse error: <error>, please return strictly valid JSON».
3. **Retry с `temperature=0`** на повторных попытках если изначально использовался t > 0.

### Affected files

- `tg_parser/processing/pipeline.py`

---

## ISSUE-6 (Low): HTTP 520 errors от Anthropic API

### Симптом

В логах в 07:01–07:02 UTC видны `Server error '520 <none>' for url 'https://api.anthropic.com/v1/messages'` для нескольких постов подряд. Cloudflare 520 — обычно временное (downtime/rate-limit на стороне Anthropic). Retry-логика отрабатывает.

### Suggested fix

- Exponential backoff с jitter для 520/529/503 ответов
- Метрика `anthropic_api_5xx_errors_total{status}` в Prometheus

### Affected files

- `tg_parser/processing/pipeline.py` (или там, где Anthropic client)

---

## ISSUE-7 (High, misleading): CLI `topicize` рапортует успех при тотальном fail

### Симптом

Запущена топикизация `kdl_ru` в 07:33 UTC после пополнения баланса. Все 17 батчей упали с `Your credit balance is too low to access the Anthropic API`. Тем не менее CLI вывел:

```
✅ Topicization завершён:
   • Создано тем: 0
   • Создано подборок: 0
   • Coverage: 0.0% (0/841 documents)

⚠️  Темы не созданы (возможно, недостаточно данных)
```

И вернул exit code 0 (предположительно).

### Почему критично

1. **Misleading status:** `✅ завершён` при нулевом результате
2. **Misleading diagnosis:** «возможно, недостаточно данных» — фактическая причина «все батчи отказали из-за billing-ошибки API»
3. **Exit code:** скрипт автоматизации будет считать вызов успешным
4. **Тратится время оператора:** легко не заметить

### Root cause

В `topicization_service.py` (или вызывающем коде) отсутствует проверка, что критическое число батчей упало по системной причине. Logic типа:
```python
result = await run_batches(...)  # все упали — но silently
return TopicizationResult(topic_cards=0, ...)  # ← false success
```

### Suggested fix

1. **Различать «0 тем» vs «все батчи провалены»**: если `failed_batches / total_batches > threshold` (например > 50%) — failure, не success
2. **Различать класс ошибки**: billing/auth → exit code 2 (системный фейл), parser errors → exit code 0 с warning
3. **CLI message** при тотальном fail:
   ```
   ❌ Topicization failed: 17/17 batches errored
   First error: Your credit balance is too low...
   No topics created. Fix API credentials/billing and retry.
   ```
4. **Минимальный фикс:** поднимать non-zero exit code если все батчи провалены

### Affected files

- `tg_parser/services/topicization_service.py`
- `tg_parser/processing/topicization.py`
- `tg_parser/cli/app.py` — handler команды `topicize`

### Acceptance

- При billing-ошибке API: non-zero exit code и явное сообщение причины
- Partial fail (3 из 17): exit code 0, явное указание N успехов / M провалов

---

## ISSUE-8 (Medium): `get_cross_channel_stats` игнорирует `topic_links`

### Симптом

После запуска `link-topics` создаются связи между топиками на основе Jaccard + cosine similarity (создано 746 связей при threshold=0.3). `get_cross_channel_stats` про эти связи не знает и продолжает считать overlap только по keywords.

Воспроизведение: `get_cross_channel_stats` до и после `link-topics` возвращает идентичный JSON.

### Почему важно

Реальная семантическая связность системы недооценена. Из примера: тема `topic:tg:profendocrinologist:post:582` (Микробиота в эндокринологии) связана с 5 темами из 4 каналов через embedding-similarity, при этом у топовой связи `shared_keywords: []` — то есть keyword-overlap ноль, а семантическая связь сильная (0.41).

### Suggested fix

Добавить в `get_cross_channel_stats` секцию `topic_link_stats`:
```json
{
  "topic_link_stats": {
    "total_links": 746,
    "avg_similarity": 0.3352,
    "links_by_channel_pair": [
      {"channels": ["kdl_ru", "profendocrinologist"], "link_count": 23, "avg_sim": 0.38},
      ...
    ],
    "strongly_connected_components": [...]
  }
}
```

### Affected files

- `tg_parser/services/analytics_service.py` (или эквивалент)
- `tg_parser/mcp/tools.py` — handler `get_cross_channel_stats`

---

## ISSUE-9 (Low): keywords не лемматизированы — дубли в overlap

### Симптом

В keyword overlaps видны группы:
- `аллергия` / `аллергии` / `аллергические` — 3 разные формы одного концепта
- `анализ` / `анализа` / `анализам` / `анализов` / `анализы` — 5 форм
- `адаптация` / `адаптации` — 2 формы

Каждый создаёт отдельный overlap-record, раздувая `overlap_count` (сейчас 795) и засоряя топ keywords.

### Suggested fix

Применить лемматизацию на этапе keyword extraction:
- Для русского: `pymorphy3` или `natasha`
- Для английского: `nltk.WordNetLemmatizer` или `spacy`
- Хранить и lemma, и оригинальную форму (lemma для overlap, оригинал для display)

### Affected files

- `tg_parser/processing/pipeline.py` (этап keyword extraction)
- Возможно нужна миграция: пересчёт keywords для существующих документов

### Note

Может быть отнесено к Enhancement, не Bug, в зависимости от того, как организован keyword-extraction в проекте. Если он LLM-based — возможно решается через prompt engineering.

---

## ISSUE-10 (Medium): `subscribe_watchlist` / `subscribe_digest` не идемпотентны

### Симптом

Повторный вызов `subscribe_watchlist` с **теми же параметрами** (title, channel_ids, keywords) создаёт **новую** подписку с новым UUID. Никакой deduplication / merge / update on conflict. То же самое для `subscribe_digest`.

Воспроизведение — реальное наблюдение: после создания 4 watchlist'ов любой повторный запуск того же скрипта создаст ещё 4 (итого 8), хотя смысл этого действия был только один — гарантировать наличие подписок.

### Сравнение с другими MCP

`add_workspace_source` корректно идемпотентно: возвращает `changed: false` если канал уже в workspace. То есть **паттерн «идемпотентность для read-modify-write»** в системе есть, но не применён к subscriptions.

### Почему важно

1. **Опасно для автоматизации:** скрипт-настройщик подписок при повторном запуске создаст дубли. Пользователь получит **двойные пуши** на каждое match.
2. **Нет защиты от случайной двойной кнопки:** через UI/MCP легко создать 2 идентичные подписки и не заметить.
3. **Mass-cleanup сложен:** нужно вручную перебирать `list_*` → `unsubscribe_*` для каждой дубликата.

### Suggested fix

Несколько опций:

**A. Strict deduplication.** При `subscribe_*` сначала ищем существующую запись с теми же `(user_id, title, channel_ids hash)`. Если есть — возвращаем её с `created: false`.

**B. Upsert по title.** Title уникален для пользователя. При повторе с тем же title — апдейтим описание/keywords/threshold, возвращаем существующий ID.

**C. Хотя бы warning.** Если за последние 60 секунд от того же user_id уже была subscribe с теми же `title`/`name` — отбить с 409 Conflict и текстом «duplicate, use update instead».

Рекомендация: **B (upsert по title)** — наиболее естественное API для конфигурационных entities.

### Affected files

- `tg_parser/services/watchlist_service.py`
- `tg_parser/services/digest_service.py`
- `tg_parser/mcp/tools.py` — handlers `subscribe_*`

### Acceptance

- Повторный `subscribe_watchlist` с теми же параметрами не создаёт второй записи
- Поведение задокументировано в docstring инструмента

---

## ISSUE-11 (Low): «Topic failed quality criteria, skipping» — недостаточно деталей

### Симптом

При incremental-топикизации в логах нескольких каналов (AgeManagment, labdiagnostica_logical, genotek) появилась строка:
```
{"event": "Topic failed quality criteria, skipping"}
```

Несколько раз за прогон у одного канала (в AgeManagment — 6 раз, в labdiagnostica_logical — 1, в genotek — 1).

### Что не так

Сообщение **не содержит**:
- Названия предложенной темы
- Какому quality criterion она не соответствует (минимальный bundle size? дублирование? тональность? content type?)
- Сырое предложение LLM

В результате нельзя:
- Понять, теряются ли полезные кандидаты
- Калибровать quality threshold
- Воспроизвести «потерянные» темы при ручном анализе

В отличие от других мест (где есть отчёты типа `Phase 2 batch: N assigned, M new topics, K unassignable`), здесь чистая «чёрная дыра».

### Контекст

Quality filter — полезная фича (отбрасывает шумные темы), но без observability невозможно понять, **что именно он считает шумом**. Это особенно важно для каналов вроде `foodf4thought`, где много пограничного контента.

### Suggested fix

1. Логировать **причину skip**: `Topic failed quality criteria (reason=min_items_too_low, title='X', items=1)`
2. В конце прогона выводить агрегат: `Quality filter rejected 7 topics: 4 by min_items, 2 by duplicate_title, 1 by toxicity`
3. Опциональный CLI флаг `--show-rejected-topics` для debug

### Affected files

- `tg_parser/processing/topicization.py`
- `tg_parser/services/topicization_service.py`
- CLI handler для `topicize`

### Acceptance

После фикса оператор может ответить на вопрос «что система не пропустила и почему», глянув в логи или вывод CLI.

---

## Summary patterns

### Pattern 1: слабая differentiation между «работа выполнена» и «работа не выполнена»

Несколько issue имеют общую природу — система не различает успех / частичный успех / системный fail:

- **ISSUE-1**: silent no-op (`triggered: true` без работы)
- **ISSUE-2**: нет observability на эту аномалию
- **ISSUE-3'**: misleading log («skipped» звучит как пользовательский выбор)
- **ISSUE-4**: `last_attempt_at` не пишется при success
- **ISSUE-7**: CLI рапортует ✅ при тотальном fail
- **ISSUE-11**: «failed quality criteria» — отбрасывание без указания причины

Системно решается через:
- Структурированные результаты со статусом (`success` / `partial` / `failed` / `degraded`)
- Различение классов ошибок (user error / API error / internal error)
- Consistent exit codes в CLI
- Инварианты на состояние БД («triggered → attempt_at within N seconds»)

### Pattern 2: inconsistent API behavior

- **ISSUE-10**: `subscribe_*` не идемпотентны (в отличие от `add_workspace_source`)
- Возможно есть и другие — стоит провести audit всех write-операций в MCP API на предмет идемпотентности

### Pattern 3: ad-hoc reliability vs systematic retry/backoff

- **ISSUE-5**: retry того же промпта на JSON parse errors (детерминированный fail × 3)
- **ISSUE-6**: HTTP 520 без exponential backoff

Системно: общая retry-стратегия для всех external API calls с jitter, exponential backoff, classification ошибок (transient vs permanent).
