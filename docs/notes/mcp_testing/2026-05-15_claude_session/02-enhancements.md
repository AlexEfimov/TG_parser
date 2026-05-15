# tg-parser — Enhancement Proposals

Предложения по улучшениям, выявленные в сессии 2026-05-14. Это **не баги**, а целенаправленные улучшения функциональности и UX.

---

## Index

| # | Title | Priority | Effort |
|---|---|---|---|
| ENH-1 | MCP-инструмент `trigger_topicization` | High | S |
| ENH-2 | MCP-инструмент `trigger_link_topics` | Medium | S |
| ENH-3 | Health-check для stuck active sources | Medium | S |
| ENH-4 | `get_cross_channel_stats` — workspace-aware analytics | Medium | M |
| ENH-5 | Cost-control flag для топикизации | High | M |
| ENH-6 | Pre-flight check баланса Anthropic перед топикизацией | Medium | S |
| ENH-7 | Batch-mode для топикизации (50% дешевле) | Medium | M |
| ENH-8 | Dry-run для `topicize` (оценка стоимости без расхода) | Low | M |
| ENH-9 | Workspace-bound subscriptions (digest и watchlist) | High | M |
| ENH-10 | Cross-workspace keyword exclusion list | Low | S |
| ENH-11 | Topic merge/split UI для дедупликации | Low | L |
| ENH-12 | Initial backfill scan для новых watchlists | Medium | M |
| ENH-13 | Watchlist preview / dry-run по историческим данным | Medium | M |

---

## ENH-1 (High): MCP-инструмент `trigger_topicization`

### Контекст

Сейчас MCP API имеет дыру: `trigger_pipeline` есть, но `topicize` — только CLI. После добавления нового канала надо SSH-иться на сервер для запуска топикизации первый раз. Это нарушает workflow «всё через MCP».

Также через MCP можно делать `force_resummarize` (для существующего topic_id), но это не помогает каналам с 0 топиков.

### Предложение

Добавить MCP tool:
```python
trigger_topicization(
    channel_id: str,
    mode: str = "auto",  # auto | full | incremental | assign-only
    force: bool = False,
    cross_channel: bool = True
) -> {
    "triggered": bool,
    "job_id": str,
    "estimated_cost_usd": float,  # см. ENH-6
    "estimated_duration_sec": int
}
```

Параллельный `get_topicization_job_status(job_id)` для мониторинга прогресса.

### Acceptance

- Канал с 0 топиков можно дотопикизировать без SSH
- Возвращаемый estimated_cost даёт grand picture перед запуском

---

## ENH-2 (Medium): MCP-инструмент `trigger_link_topics`

### Контекст

`link-topics` — операция бесплатная (только embeddings + Jaccard), но запускается только через CLI. Должна быть в MCP по тем же причинам что и ENH-1.

### Предложение

```python
trigger_link_topics(
    threshold: float = 0.3,
    workspace_id: str | None = None  # если None — глобально
) -> {
    "triggered": bool,
    "links_created": int,
    "links_cleared": int,
    "avg_similarity": float
}
```

Поскольку операция дешёвая и быстрая (40 секунд для всей системы), можно сделать синхронной без job tracking.

### Acceptance

- После запуска через MCP топологический граф топиков обновляется
- `get_related_topics` сразу видит новые связи

---

## ENH-3 (Medium): Health-check для stuck active sources

### Контекст

Из сессии расследования: с момента `add_channel` до момента когда стало видно «канал не обработался» прошло 20+ минут. Источник был в состоянии «active, last_attempt_at=null, last_success_at=null». Это **аномалия**, которую можно обнаружить автоматически.

### Предложение

Periodic check (раз в N минут, можно в существующий `health_check` job):
```sql
SELECT channel_id FROM sources
WHERE status = 'active'
  AND last_attempt_at IS NULL
  AND created_at < now() - interval '1 hour';
```

Действие при ненулевом результате:
- лог уровня WARNING
- Prometheus metric `sources_stuck_total`
- Если в системе есть alerting — alert

Логика «1 hour» = дефолтный scheduler interval. Если за час не было попытки — что-то сломано.

### Affected files

- `tg_parser/services/health_check.py` (создать или расширить)
- `tg_parser/api/metrics.py` — новый Prometheus gauge

---

## ENH-4 (Medium): workspace-aware analytics

### Контекст

`get_cross_channel_stats` принимает `workspace_id`, но возвращает только статистику внутри workspace. Полезное расширение — статистика **между** workspaces. Например: «топики в Эндокринологии, которые связаны с топиками в Longevity».

### Предложение

Новый MCP tool или расширение существующего:
```python
get_workspace_overlap(
    workspace_a: str,
    workspace_b: str
) -> {
    "workspace_a_topics": int,
    "workspace_b_topics": int,
    "cross_links": int,
    "avg_similarity": float,
    "top_bridging_topics": [  # топики с самыми сильными cross-links
        {"topic_id": "...", "title": "...", "linked_count": N, "best_score": 0.45}
    ]
}
```

### Use case

В текущей системе:
- Эндокринология ↔ Лабдиагностика (b12, crispr, аутоиммунные, беременности)
- Эндокринология ↔ Longevity (GLP-1 агонисты, семаглутид)
- Лабдиагностика ↔ Longevity (mtor, альцгеймера)

Сейчас эти пересечения видны только косвенно через `get_related_topics` для отдельных топиков. Workspace overlap дал бы big picture.

---

## ENH-5 (High): Cost-control для топикизации

### Контекст

В сессии: топикизация `kdl_ru` стоила $1.67 (841 doc). Для `profendocrinologist` (3440 docs) был только грубый прогноз. У оператора нет встроенного механизма ограничить расходы.

### Предложение

CLI и MCP-параметр:
```bash
tg-parser topicize --channel X --max-cost-usd 10.00
```

Поведение:
1. Pre-flight estimate (см. ENH-6) — если прогноз > max-cost → отказ с понятным сообщением
2. Во время выполнения: каждые N батчей пересчитывать накопленную стоимость, при превышении — graceful stop и сохранение уже созданных топиков

### Default

`max-cost-usd` = unset (текущее поведение). Опционально env-var `TOPICIZE_DEFAULT_MAX_COST_USD` как safety net.

---

## ENH-6 (Medium): Pre-flight estimate стоимости

### Контекст

Прогноз стоимости в сессии делался вручную через калибровку на одном канале (kdl_ru дал реальный $1.67 → линейный прогноз для profendocrinologist ~$7). Это можно автоматизировать.

### Предложение

CLI флаг `--estimate-only` (без запуска):
```bash
$ tg-parser topicize --channel profendocrinologist --estimate-only
Channel: profendocrinologist
  Documents to topicize: 3440
  Estimated batches: 69
  Estimated input tokens: 1,254,000
  Estimated output tokens: 205,000
  Estimated cost: $6.84 (Sonnet 4.6: $3 in / $15 out per 1M)
  Estimated duration: ~14 min
```

Внутри: использовать **средние input/output tokens на документ** из последних N успешных топикизаций. Калибровка по факту.

### Pricing source

Цены за токены брать из конфига или env (не хардкод):
```
ANTHROPIC_PRICE_INPUT_PER_MTOK=3.00
ANTHROPIC_PRICE_OUTPUT_PER_MTOK=15.00
```

Это позволит легко обновлять при изменении тарифов.

---

## ENH-7 (Medium): Batch API mode для топикизации

### Контекст

Anthropic Batch API даёт **50% скидку** на не-real-time запросы. Топикизация — идеальный кандидат: оператор запускает её осознанно, не критично к latency, занимает минуты.

### Предложение

CLI флаг:
```bash
tg-parser topicize --channel X --batch-mode
```

В batch-mode:
- Запросы группируются в Batch API jobs (до 10K запросов в job)
- Возвращается batch job ID
- Polling статуса либо `tg-parser topicize-status <job_id>` либо webhook

### Trade-off

- ⚡ −50% стоимость
- 🐢 +до 24 часов latency на ответ от Anthropic (обычно гораздо меньше)
- ⚙️ +сложность кода (нужна batch-aware logic, persistence batch_id, polling)

### Decision

Стоит ли — зависит от бюджета и темпа добавления каналов. Если каналы добавляются часто и общий cost > $50/мес — окупится за пару итераций.

---

## ENH-8 (Low): Dry-run для `topicize`

### Контекст

Расширение ENH-6: не просто estimate, а полная симуляция, показывающая какие документы попадут в какие батчи, какие keywords будут использованы для группировки и т.д. Полезно для debug сложных кейсов.

### Предложение

```bash
tg-parser topicize --channel X --dry-run --verbose
```

Выводит:
- Список будущих батчей с их составом
- Топовые keywords каждого батча
- Прогноз сколько топиков создастся
- Где будут конфликты (документы попадающие в несколько потенциальных топиков)

### Use case

Помогает понять «почему канал X получил мало топиков» **до** запуска и расхода API. Особенно для слабых каналов типа `foodf4thought` (10 топиков на 308 docs).

---

## ENH-9 (High): Workspace-bound subscriptions (digest и watchlist)

### Контекст — обновлено после фактической работы

**Подтверждено через MCP**:
- `subscribe_digest(channel_ids: array, ...)` — принимает только список каналов
- `subscribe_watchlist(channel_ids: array, ...)` — принимает только список каналов

То есть **ни одна из подписок не знает про workspaces**. Чтобы создать «дайджест по эндокринологии» приходится явно перечислять каналы. Для одного канала это не проблема, но:
1. Если в workspace 4-6 каналов — нужно копировать UUID/ids руками
2. При добавлении канала в workspace **подписки не обновляются автоматически** — придётся unsubscribe + resubscribe

### Предложение

Расширить API:
```python
subscribe_digest(
    target: {"type": "channels", "channel_ids": [...]} 
          | {"type": "workspace", "workspace_id": "..."},
    ...
)
```

Поведение для `workspace`:
- На момент tick'а шедулера digest резолвит текущий состав workspace
- Если канал добавлен/удалён из workspace — следующий digest учитывает это
- При delete_workspace подписки на этот workspace автодеактивируются с явным notification

Аналогично для `subscribe_watchlist`.

### Use case

«Каждое утро присылай мне дайджест Эндокринологии». Если завтра добавлю второй эндокринологический канал в workspace — он автоматически попадёт в дайджест.

### Affected files

- `tg_parser/services/digest_service.py`
- `tg_parser/services/watchlist_service.py`
- `tg_parser/mcp/tools.py`
- Возможна миграция: новое поле в таблице subscriptions для target_type

### Связано

- ENH-1 (MCP `trigger_topicization`) — паттерн «отдельная команда работает с workspace»
- ISSUE-10 (subscribe не идемпотентны) — стоит фиксить вместе

---

## ENH-10 (Low): Cross-workspace keyword exclusion

### Контекст

В keyword overlaps много шумовых слов: `анализ`, `активность`, `безопасность`, `аспекты`, `влияние`. Они встречаются в 4-7 каналах, но содержательной ценности не несут.

### Предложение

Глобальный или per-workspace stop-list:
```yaml
keyword_exclusion:
  global:
    - анализ
    - активность
    - безопасность
    - влияние
    - влияния
    - аспекты
  workspaces:
    лабораторная_диагностика:
      - акции  # маркетинговый шум в kdl_ru
      - офис
```

Применяется при keyword extraction или при overlap calculation.

### Альтернатива

TF-IDF фильтрация: слова с высокой document frequency автоматически отсеиваются.

---

## ENH-11 (Low): Topic merge/split для дедупликации

### Контекст

После добавления `profendocrinologist` в системе появилось несколько кластеров топиков на одну тему (микробиота: в `profendocrinologist`, `kdl_ru`, `LongevityClub`, `mind_rise`, `Lab4health` — 5 разных топиков). Это часть by design (per-channel topic-cards), но для аналитики иногда хочется иметь единый «meta-topic».

### Предложение

CLI или MCP:
```
tg-parser topic merge <topic_id_1> <topic_id_2> ...
tg-parser topic split <topic_id> --by-keyword <kw1,kw2>
```

Создаёт meta-topic поверх существующих или разбивает большой topic-bundle на части.

### Сложность

L (Large) — требует структурных изменений в storage.

---

## ENH-12 (Medium): Initial backfill scan для новых watchlists

### Контекст — обнаружено при создании watchlist

После создания watchlist `get_watchlist_matches` возвращает `count: 0`. Из документации к инструменту: «After every incremental pipeline tick, new ProcessedDocuments are scored». Это означает **только forward-looking логика** — исторические документы никогда не оцениваются.

Для системы с 11 220 уже накопленными документами это:
- ❌ Все исторические темы не попадут в watchlist'ы пока не появятся новые посты на те же темы
- ❌ Невозможно «подгрузить» интересные старые посты по теме
- ❌ Невозможно валидировать watchlist (хорошо ли подобраны keywords/description) до того, как пойдут новые посты

### Предложение

Опциональный параметр при создании:
```python
subscribe_watchlist(
    ...,
    backfill: bool = False  # default False — текущее поведение
)
```

Если `backfill=True`:
1. Сразу после создания запускается one-time scan существующих `processed_documents` из указанных каналов
2. Все docs >= threshold добавляются в `watch_matches` с пометкой `is_backfill: true`
3. Пуши не отправляются (или только одно агрегированное «found N historical matches»)
4. Возвращается count найденных matches

### Параллельная альтернатива

Отдельная команда `tg-parser watchlist backfill <interest_id> [--since-iso ...]` — explicit operation, не часть subscribe.

### Стоимость

Расход — только embedding similarity по уже существующим embeddings. **LLM не используется**, операция дешёвая.

### Use case

Создал watchlist «семаглутид» → сразу получаю список из ~15 исторических постов в `profendocrinologist`, `LongevityClub`, `AgeManagment`, релевантных теме. Можно сразу оценить качество подбора и подкрутить threshold/keywords.

### Affected files

- `tg_parser/services/watchlist_service.py`
- `tg_parser/processing/watchlist_matcher.py`

---

## ENH-13 (Medium): Watchlist preview / dry-run

### Контекст

Связано с ENH-12, но **до создания** подписки. Хочется проверить «как сработала бы эта watchlist», не создавая её.

### Предложение

MCP tool:
```python
preview_watchlist(
    channel_ids: array[str],
    keywords: array[str] = None,
    description: str = None,
    threshold: float = 0.6,
    sample_size: int = 20
) -> {
    "estimated_matches_total": int,
    "sample_matches": [
        {"doc_id": ..., "channel_id": ..., "score": 0.74, "snippet": "..."},
        ...
    ],
    "score_distribution": {"0.6-0.7": 12, "0.7-0.8": 5, "0.8+": 2}
}
```

Никакого изменения состояния, чистый readonly запрос. Embedding similarity по уже существующим документам, без LLM.

### Use case

Перед `subscribe_watchlist`:
1. `preview_watchlist(keywords=["мicrобиоta", "пробиотики"], ...)` 
2. Видишь: estimated 47 matches, top scores 0.81/0.79/0.76
3. Подкручиваешь threshold/keywords пока не достигнешь нужного баланса
4. Только после этого делаешь `subscribe_watchlist`

### Стоимость

$0. Использует уже посчитанные embeddings.

---

## Architectural observations (не предложения, а наблюдения)

### O-1: MCP-API асимметрично

Через MCP есть **много инструментов чтения** (`list_*`, `get_*`, `search_*`) и **мало инструментов записи** (`add_channel`, `subscribe_*`, `create_workspace`, `trigger_pipeline`). При этом:
- Топикизация → только CLI
- Link-topics → только CLI
- Force topicization re-run → только CLI

Это создаёт ситуацию когда «обычная работа» возможна через MCP, но «администрирование» требует SSH. Стоит сознательно решить — это by design (safety) или legacy (надо закрыть гэп).

### O-2: Pipeline-этапы атомарны на уровне канала

Каждый этап (ingest/process/topicize) — отдельный, прерываемый, перезапускаемый. Это хорошо. Но между этапами нет ясного контракта: `processed_documents` лежат в БД и могут быть топикизированы когда угодно, дотопикизированы, переэкспортированы. Это значит **расход API tokens идемпотентен** на уровне этапа: один раз процесстили → одни тратили на process, отдельно тратим на topicize.

### O-3: Items_count = 102-103 у большинства тем

В выводе `list_topics` многие топики имеют `items_count: 102` или `103`. Это похоже на технический потолок на размер topic_bundle. Стоит проверить — это by design (управление контекстом промпта) или артефакт.

Источник наблюдения: kdl_ru (46 топиков, большинство с 102-103) и profendocrinologist (92 топика, тот же паттерн).

### O-4: Watchlist'ы не переоценивают исторические документы

Обнаружено при создании 4 watchlist'ов в сессии. После `subscribe_watchlist` `get_watchlist_matches` возвращает `count: 0`, даже если в системе уже есть 11 220 документов и многие соответствуют теме. Логика watchlist строго forward-looking: только новые `processed_documents` с момента создания подписки.

**Следствие:**
- Невозможна валидация watchlist на исторических данных
- Невозможно «найти всё прошлое по теме X» через watchlist (нужно `search_knowledge_base` или `ask_question`)
- Качество подбора keywords/description проявится только когда пойдут новые посты

Закрывается через ENH-12 (backfill) или ENH-13 (preview).

### O-5: Подписочные API принимают `channel_ids`, не `workspace_id`

Подтверждено реальным вызовом MCP:
- `subscribe_digest(channel_ids: array, ...)`
- `subscribe_watchlist(channel_ids: array, ...)`

Workspace-context в подписках отсутствует. Если состав workspace меняется — подписки на «дайджест workspace» (которые на самом деле дайджест-канала-Х) не обновляются. Закрывается через ENH-9.

### O-6: Параметр `description` критичен для качества watchlist

По документации `subscribe_watchlist`: «If description omitted, the embedding falls back to title + keywords». То есть **description формирует embedding** для семантической части матчинга. Короткое title + bag-of-keywords создаёт плохой embedding; развёрнутый description — гораздо лучше.

**Практический вывод:** при создании watchlist всегда писать осмысленный description в 1-3 предложения. Это улучшает recall на семантически похожих, но текстуально различающихся постах.

В сессии все 4 watchlist'а созданы с description'ами именно по этой причине.

### O-7: Подписки не идемпотентны, в отличие от workspace-операций

В системе **смешанные паттерны идемпотентности**:
- ✅ `add_workspace_source` — корректно возвращает `changed: false` при дубликате
- ❌ `subscribe_watchlist` — создаёт новую запись с новым UUID при тех же параметрах
- ❌ `subscribe_digest` — то же поведение

Это inconsistent API behavior. См. ISSUE-10 для подробностей и предложения по фиксу.

### O-8: Auto-adjusted rate limits (наблюдение, не баг)

При каждом incremental-вызове в логах появляются строки:
```
rate_limit_rpm_adjusted: 50 → 4000
rate_limit_itpm_adjusted: 30000 → 2000000
rate_limit_otpm_adjusted: 8000 → 400000
```

**Что происходит:** rate limiter стартует с очень консервативными default-значениями (50 rpm), затем, проверяя реальные limits аккаунта через ответы API, **автоматически поднимает их в 60-80 раз** до фактических значений (4000 rpm, 2M input tokens/min, 400K output tokens/min).

**Это хорошо:**
- Адаптивное поведение, не нужно вручную конфигурировать
- Защита от первоначального burst при низком стартовом tier

**Это потенциальный риск:**
- **Стоимость становится непредсказуемой**. После adjustment один operator может за минуту потратить в 80 раз больше токенов чем ожидал — особенно при high-cost запросах вроде Opus или длинных контекстов
- Adjustment происходит молча, без warning'а пользователю
- Нет cost-cap mechanism (см. ENH-5)

**Рекомендация:**
- Логировать adjustment на уровне WARNING, не INFO
- Добавить env-var `RATE_LIMIT_MAX_RPM` как hard ceiling
- В CLI выводить «Rate limit raised to X — your bursty cost ceiling is now ~$Y/min»

### O-9: Phase 3 в incremental-топикизации создаёт cross-channel links автоматически

Раньше предполагалось, что `link-topics` — единственный способ создания связей. Реально каждый incremental-прогон в **Phase 3** уже создаёт connections для **новых** топиков канала:

| Канал (incremental) | Phase 3 cross_links | Touched topics |
|---|---:|---:|
| profendocrinologist | 128 | 96 |
| foodf4thought | 31 | 20 |
| AgeManagment | 99 | 60 |
| labdiagnostica_logical | 124 | 36 |
| Lab4health | 105 | 41 |
| mind_rise | 68 | 27 |
| LongevityClub | 26 | 11 |
| genotek | 26 | 25 |

**Архитектурное следствие:**
- `link-topics` нужен только когда **существующие** темы в системе должны быть пересмотрены под новый порядок (пересчёт всех пар)
- При обычном workflow «добавил канал → incremental → ...» **link-topics не обязателен** — Phase 3 сделает links для новых тем
- Но `link-topics` всё ещё ценен после **массовых добавлений** или при изменении threshold

### O-10: `link-topics` — truncate-and-rebuild, не merge

Из логов второго запуска link-topics: `Cleared 746 old topic links / Created 746 topic links from 173510 pairs`. Cleared = Created — это **намеренный полный пересчёт**, а не инкрементальное добавление. Раньше первый запуск показывал `Cleared 175 / Created 708`, что подтверждает: `Cleared` = всё что было в БД (включая то, что создавалось Phase 3 incremental'ов).

**Архитектурное следствие:**
- Любые ручные правки topic_links (если они когда-нибудь будут возможны через future feature) **будут потеряны** при следующем link-topics
- Гарантирует консистентность графа со spec'ом (threshold, embedding model, и т.д.)
- При смене threshold нужно перезапускать link-topics

**Замечание для документации проекта:** стоит явно прописать в `--help` для link-topics: «*This command rebuilds the entire topic link graph from scratch. Any out-of-band edits to topic_links will be lost.*»

### O-11: Singletons как индикатор зрелости топикизации канала

Изначально у `profendocrinologist` было `singleton_count: 0` после full-режима — мы записали это как аномалию A1. После incremental с cross-channel context singletons появились (0 → 7). То же для других каналов после incremental.

**Закономерность:** full-режим (без cross-channel) **не создаёт singletons**, все темы кластерные. Incremental с cross-channel — создаёт singletons естественным образом.

Объяснение: в full LLM группирует «всё со всем» при отсутствии context, поэтому минимальная тема — это всегда минимум 2 документа. В incremental LLM знает темы других каналов и может пометить отдельный документ как singleton-тему, если он уникален.

**Singleton/cluster ratio — индикатор зрелости топикизации канала:**
- 0% singletons → канал был топикизирован только в full-режиме, никогда incremental
- 5-15% singletons → один incremental после full (типичный case)
- 20-50% singletons → канал прошёл много incremental проходов с разнообразным контентом
- 78% (Lab4health) → исключение: возможно, специфика канала или legacy state до cross-channel features

Это **полезная метрика для health-check** системы топикизации.

### O-12: `foodf4thought` keyword extraction улучшился после incremental

До incremental top keywords канала: `благополучие, вебинары, влияние, восприятие, врачей, гормональное, городской, для, доказательная` — почти всё общая лексика.

После incremental: `mind-body, wellness-туризм, активация, активный, благополучие, вебинары, велнеса, вкус, влияние, влияния` — появились **предметные термины** (`mind-body`, `wellness-туризм`, `велнеса`).

**Почему так:** новые темы, созданные incremental'ом для канала, дополнили keyword storage канала с предметными словами из их title/content. Это значит **keyword extraction зависит от существующих topic-cards**, не только от raw documents. То есть итеративная топикизация сама улучшает keyword quality. Это полезное emergent behavior.
