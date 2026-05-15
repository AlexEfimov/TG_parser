# tg-parser — Operational Runbook

Типовые операции с системой tg-parser, основанные на сессии 2026-05-14.

---

## Index

1. [Добавление нового канала](#1-добавление-нового-канала)
2. [Топикизация нового канала](#2-топикизация-нового-канала)
3. [Дотопикизация после добавления](#3-дотопикизация-всех-каналов-после-добавления)
4. [Cross-channel linking](#4-cross-channel-linking)
5. [Диагностика «канал не обрабатывается»](#5-диагностика-канал-не-обрабатывается)
6. [Восстановление после billing-инцидента](#6-восстановление-после-billing-инцидента)
7. [Оценка стоимости перед топикизацией](#7-оценка-стоимости-перед-топикизацией)
8. [Настройка watchlist и digest](#8-настройка-watchlist-и-digest)

---

## 1. Добавление нового канала

### MCP-команды

```python
# 1. Создать channel-source
add_channel(channel_id="newchannel")

# 2. (Опционально) Добавить в workspace
add_workspace_source(
    workspace_id="<workspace-uuid>",
    channel_id="newchannel"
)
```

### Что произойдёт автоматически

Шедулер `incremental_pipeline` подхватит канал на **следующем тике** (раз в час). Выполнит:
1. `[1/4] Ingest` — выкачает посты из Telegram
2. `[2/4] Process` — обработает каждый документ через Anthropic API (тратит токены!)
3. `[3/4] Topicize` — **пропускается by design** (`--skip-topicize` хардкод в шедулере, см. ISSUE-3')
4. `[4/4] Export` — экспортирует в `./output`

### Что НЕ произойдёт автоматически

- **Топикизация** — нужно запустить вручную, см. раздел 2 (для одного канала) или раздел 3 (для всех)
- **Link-topics** — обычно не нужен после нового топикизации (см. O-9), но при необходимости см. раздел 4
- **Уведомления о новых темах** — нужно настроить watchlist/digest, см. раздел 8

### ⚠️ MCP `trigger_pipeline` не работает

Согласно ISSUE-1, `trigger_pipeline` через MCP — silent no-op. **Если нужно запустить сразу, не дожидаясь часа:**

```bash
# Через SSH на VPS:
# (До фикса ISSUE-1)
docker compose exec tg_parser tg-parser ingest --source newchannel
```

Альтернативно — просто дождаться следующего тика (≤ 1 час).

---

## 2. Топикизация нового канала

### Когда

После того как канал прошёл ingest+process (т.е. `processed_documents` в `list_channels` стал ненулевым).

### Команда

```bash
docker compose exec tg_parser tg-parser topicize --channel <channel_id>
```

### Что произойдёт

- Для нового канала (0 тем) → `--mode auto` → `full`
- Для канала с существующими темами → `--mode auto` → `incremental` (+ cross-channel context)
- `--cross-channel` по умолчанию `True` (но в `full`-режиме не используется)

### Расход

Калибровка от 2026-05-14: ~$0.0020 за документ (Sonnet 4 с тарифами $3/$15 за 1M токенов).

| Размер канала | Прогноз cost |
|---|---:|
| 300 docs | ~$0.60 |
| 800 docs | ~$1.60 |
| 1500 docs | ~$3.00 |
| 3500 docs | ~$7.00 |

### ⚠️ Проверки перед запуском

1. Баланс Anthropic API > прогнозируемой стоимости × 2 (запас)
2. Канал прошёл process: `list_channels` показывает `processed_documents > 0`
3. Если важна cross-channel связность с другими каналами — после топикизации запустить `link-topics`

### ⚠️ Verify success

CLI **может ложно рапортовать `✅ Topicization завершён`** при тотальном fail (ISSUE-7). Всегда проверяй:

```python
# После завершения CLI:
list_topics(channel_id="<channel>", limit=3)
# Должно вернуть total > 0
```

Если total = 0 и в логах CLI видны `Batch X/Y failed: ...` — это **реальный fail**, не data issue.

---

## 3. Дотопикизация всех каналов после добавления

### Контекст

Когда добавлен новый канал и/или хочется поднять coverage существующих каналов, стоит запустить incremental по всем. Это **бесплатно по сравнению с full** и **очень эффективно**.

### Команда (batch для всех каналов)

```bash
for channel in Lab4health labdiagnostica_logical genotek AgeManagment kdl_ru \
               LongevityClub foodf4thought mind_rise profendocrinologist; do
    echo "=== Топикизация $channel ==="
    docker compose exec tg_parser tg-parser topicize --channel "$channel" --mode incremental
done
```

### Что произойдёт

В режиме `incremental` для каждого канала:
1. **Phase 1 (keyword assign):** uncovered docs привязываются к существующим темам по keywords (бесплатно)
2. **Phase 2 (LLM discover):** оставшиеся docs группируются в новые темы через LLM с cross-channel context
3. **Phase 3 (cross-channel TopicLinks):** automatically создаются links между новыми темами и темами других каналов (бесплатно)

### Эффективность по типам каналов

Из сессии 2026-05-14, **Phase 1 hit rate** показывает «созревание» канала:

| Канал | hit rate | Природа |
|---|---:|---|
| profendocrinologist | 77% | Сильная предметная лексика — Phase 1 работает отлично |
| labdiagnostica_logical | 47% | Хорошая лабораторная терминология |
| AgeManagment | 14% | Специфические редкие keywords |
| foodf4thought | 4% | Общая лексика — Phase 1 почти не работает |

**Если hit rate < 20%** — это сигнал что канал слабо предметный или keyword extraction нужно улучшить.

### Стоимость batch для всей системы

Из сессии 2026-05-14 (8 каналов, 1670 uncovered docs total) → **~$4-5** на весь batch. Время **~5 минут** при rate_limit auto-adjusted (см. O-8).

### Effect на coverage

Реальные результаты сессии (incremental в обратном порядке размера):

| Канал | Coverage до | Coverage после |
|---|---:|---:|
| Lab4health | 93.0% | **99.8%** |
| LongevityClub | 89.4% | 99.1% |
| genotek | 84.1% | 99.0% |
| profendocrinologist | 75.6% | 98.7% |
| mind_rise | 86.9% | 98.5% |
| AgeManagment | 74.7% | 94.6% |
| labdiagnostica_logical | 77.6% | 94.2% |
| foodf4thought | 53.9% | 80.5% |

Каналы с предметной лексикой выходят на 94-100%. `foodf4thought` упирается в потолок ~80% из-за специфики keyword extraction.

### После batch — нужен ли link-topics?

**Обычно — нет.** Phase 3 каждого incremental уже создаёт cross-channel links для новых тем. `link-topics` нужен только в одном из случаев:
- Изменился threshold (default 0.3)
- Хочется полный пересчёт связей **между всеми** темами, не только с новыми
- После массовых изменений (новые каналы + редкие incremental'ы)

В обычном workflow добавления одного канала — Phase 3 достаточно.

---

## 4. Cross-channel linking

### Когда нужно

В **большинстве случаев — НЕ нужно**. Phase 3 каждого incremental-прогона уже создаёт cross-channel links для новых тем (см. O-9). `link-topics` нужен только когда:

1. **Изменился threshold** или другая настройка similarity → нужен полный пересчёт
2. **Массовые добавления каналов** + хочется убедиться что всё связано правильно
3. **Периодический re-build** (раз в месяц) для актуализации графа

### ⚠️ Truncate-and-rebuild semantics

`link-topics` **полностью удаляет** все существующие links и создаёт заново (см. O-10). В логах это видно как:
```
Cleared 746 old topic links
Created 746 topic links from 173510 pairs (threshold=0.30)
```

`Cleared = Created` — нормально, означает полный пересчёт.

**Любые ручные правки (если когда-нибудь будут возможны) будут потеряны.**

### Команда

```bash
docker compose exec tg_parser tg-parser link-topics
# или с custom threshold:
docker compose exec tg_parser tg-parser link-topics --threshold 0.35
```

### Что произойдёт

1. Старые links удаляются полностью
2. Все пары топиков из разных каналов оцениваются: Jaccard (keywords) + cosine (embeddings)
3. Пары с score >= threshold → создаются как `topic_link` записи

### Расход

**$0** — работает на готовых данных в БД, LLM не вызывается.

### Время

~40-46 секунд для 641 топика (173K пар).

### Threshold guide

| Threshold | Поведение |
|---|---|
| 0.20 | Много связей, включая шумовые |
| 0.30 (default) | Сбалансированно |
| 0.40 | Только сильные связи |
| 0.50+ | Только очень сильные совпадения |

При размере системы 641 топик и threshold 0.3 получили 746 links (ratio ~0.43% от всех пар).

### Verify

```python
# Через MCP после link-topics:
get_related_topics(topic_id="<какой-то существующий topic_id>")
# Должно вернуть список связей с similarity_score
```

---

## 5. Диагностика «канал не обрабатывается»

### Симптом

Канал добавлен через `add_channel`, прошло время, `list_channels` показывает `raw_messages: 0`.

### Decision tree

**Шаг 1.** Сколько прошло с момента `add_channel`?

```python
# Через MCP:
get_pipeline_status(channel_id="<channel>")
```

- **< 1 час и `last_attempt_at: null`** — нормально. Шедулер тикает раз в час. Жди.
- **> 1 час и `last_attempt_at: null`** — аномалия. См. шаг 2.
- **`last_attempt_at` есть, `raw_messages: 0`** — Telegram-проблема. Канал может быть приватный, неправильное имя, и т.д. См. шаг 3.

**Шаг 2.** Проверка scheduler:

```bash
# На VPS:
docker compose logs tg_parser --since 1h | grep -i "scheduler\|incremental_pipeline"
```

Должны быть строки `Running job "incremental_pipeline"`. Если нет — шедулер мёртв. Перезапустить контейнер:

```bash
docker compose restart tg_parser
```

**Шаг 3.** Проверка Telethon:

```bash
docker compose logs tg_parser --since 1h | grep -i "<channel_id>\|telethon\|telegram"
```

Ищи: `ChannelPrivateError`, `UsernameNotOccupiedError`, `FloodWaitError`, или session-related ошибки.

### ⚠️ MCP `trigger_pipeline` не помогает

См. ISSUE-1: `triggered: true`, но реально ничего не делает. До фикса использовать SSH-команды.

---

## 6. Восстановление после billing-инцидента

### Симптом

В логах массово:
```
{"error": "Your credit balance is too low to access the Anthropic API..."}
```

### Шаги

**1. Пополнить баланс.** Console: https://console.anthropic.com

**2. Дождаться следующего scheduler tick (≤ 1 час).** Шедулер сам подхватит обработку.

**3. Проверить что обработка идёт:**

```bash
docker compose logs tg_parser --since 5m | grep "tokens="
# Должны быть строки вида:
# "[2/4] Processing completed in N s: processed=N, failed=N, tokens=N"
# где tokens > 0
```

Если `tokens=0` — billing ещё не разблокирован.

**4. Дотопикизировать каналы, у которых упала топикизация:**

```bash
# Проверить какие каналы потеряли темы:
# Через MCP: list_channels — смотри coverage_percent

# Если у канала coverage < ожидаемого:
docker compose exec tg_parser tg-parser topicize --channel <channel> --mode incremental
```

**5. После всех топикизаций — link-topics только если нужна полная пересборка графа:**

В обычном workflow Phase 3 каждого incremental уже создаёт cross-links для новых тем (см. O-9). Запускайте link-topics только если:
- Затронуто много каналов сразу (> 50% системы)
- Хочется быть уверенным, что граф пересчитан с учётом всех изменений

```bash
docker compose exec tg_parser tg-parser link-topics
```

**⚠️ Помните:** link-topics — это truncate-and-rebuild (см. O-10), а не merge. Все существующие links будут пересозданы.

### Profilactic

Поставить alert на низкий баланс Anthropic (через их Console, есть billing alerts). Целевой минимум: 2× стоимость одного полного pipeline-цикла для всех каналов.

---

## 7. Оценка стоимости перед топикизацией

До implementaion ENH-6 (pre-flight estimate) — оценивать вручную.

### Формула

```
estimated_input_tokens  ≈ documents_count × 365   (калибровка от kdl_ru)
estimated_output_tokens ≈ documents_count × 60
estimated_cost_usd = (input/1M)*$3 + (output/1M)*$15
```

### Калькулятор

```python
def estimate_topicization_cost(docs_count: int) -> dict:
    in_tokens  = docs_count * 365
    out_tokens = docs_count * 60
    in_cost  = in_tokens  * 3.0  / 1_000_000
    out_cost = out_tokens * 15.0 / 1_000_000
    return {
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "input_cost_usd": round(in_cost, 2),
        "output_cost_usd": round(out_cost, 2),
        "total_cost_usd": round(in_cost + out_cost, 2),
        "estimated_minutes": (docs_count / 50 / 5) * 0.2  # 50/batch, 5 concurrency, ~12s/batch
    }
```

### Контрольная точка

Калибровка от 2026-05-14:
- kdl_ru: 841 docs → 306,754 in + 50,172 out → $1.67 (факт)
- Формула выше дала бы: 307,000 in + 50,500 out → $1.68 ✅

Расхождение менее 1%.

### Прогноз для всех текущих каналов

| Канал | docs | full topicize | incremental (приблизит.) |
|---|---:|---:|---:|
| profendocrinologist | 3 442 | ~$7 | ~$1.7 (840 uncovered → 0) |
| Lab4health | 1 827 | ~$3.6 | ~$0.25 (127 uncovered → 4) |
| labdiagnostica_logical | 1 148 | ~$2.3 | ~$0.50 (257 uncovered → 69) |
| AgeManagment | 1 100 | ~$2.2 | ~$0.55 (278 uncovered → 64) |
| mind_rise | 1 111 | ~$2.2 | ~$0.30 (146 uncovered → 8) |
| genotek | 1 104 | ~$2.2 | ~$0.35 (175 uncovered → 11) |
| kdl_ru | 841 | $1.67 (факт) | — |
| LongevityClub | 339 | ~$0.7 | ~$0.10 (36 uncovered → 3) |
| foodf4thought | 308 | ~$0.6 | ~$0.30 (142 uncovered → 65 unassignable) |
| **Полная re-topicization всей системы** | **11 220** | **~$23** | **~$4-5** |

**Из реального опыта сессии 2026-05-14:** полный massive incremental по всем 9 каналам обошёлся примерно в **$4-5**, занял **~25 минут**, дал прирост **+62 темы (incremental-only)** и **+571 cross-channel link**.

**Стратегический вывод:** incremental в **5-7× дешевле** full при сопоставимом качестве. Рекомендованный workflow:
- Full только при первом добавлении канала
- Incremental раз в неделю-месяц по всей системе
- link-topics только при изменении threshold или массовых правках

---

## 8. Настройка watchlist и digest

### Prerequisites

**1. Узнать Telegram chat_id**

Через бот `@userinfobot`: `/start` → возвращает `Id: <число>`. Это `chat_id` для личных пушей.

**2. Инициализировать диалог с ботом проекта**

Telegram запрещает ботам писать первым. До настройки подписок один раз отправить боту `/start`. Иначе подписки создадутся, но пуши не доставятся (ошибка `Forbidden: bot can't initiate conversation`).

### 8.1 Создать watchlist (моментальные пуши при match)

```python
# MCP:
subscribe_watchlist(
    title="Семаглутид и GLP-1",
    description="GLP-1 рецептор-агонисты, семаглутид, тирзепатид. Клинические исследования.",
    channel_ids=["profendocrinologist", "LongevityClub", "AgeManagment"],
    chat_id=5445781511,
    keywords=["семаглутид", "GLP-1", "оземпик", "тирзепатид"],
    threshold=0.6
)
```

**Принципы:**
- **Один watchlist на тему**, не валить всё в один
- **Description обязателен** — формирует embedding (без него только title+keywords, recall хуже). См. O-6 в enhancements.md
- **Channel_ids подбираются по релевантности темы**, не «все каналы». Шум — главный враг watchlist
- **Threshold 0.6 default**, повышай если много false positives, снижай если recall плохой

### 8.2 Создать digest (расписанный дайджест)

```python
subscribe_digest(
    name="Эндокринология — ежедневный дайджест",
    channel_ids=["profendocrinologist"],
    chat_id=5445781511,
    cron_expression="0 9 * * *",       # 9:00
    timezone="Europe/Nicosia",          # локальная зона
    format="summary",                   # summary | bullets | detailed
    language="ru"
)
```

**Cron-примеры:**
- `0 9 * * *` — каждый день в 9:00
- `0 9 * * 1` — каждый понедельник в 9:00
- `0 9 1 * *` — первое число каждого месяца в 9:00
- `0 9 * * 1,4` — понедельник и четверг 9:00

### 8.3 Проверить созданные подписки

```python
list_watchlists()  # все мои интересы
list_digests()     # все мои digest-подписки
```

### 8.4 Найти match'и watchlist (после следующего scheduler tick)

```python
get_watchlist_matches(interest_id="<id>", since_iso="2026-05-14T00:00:00")
```

⚠️ **Watchlist оценивает только новые документы**, появившиеся после создания подписки (см. O-4 в enhancements.md). Для поиска по историческим данным используй `search_knowledge_base` или `ask_question`.

### 8.5 Удалить подписку

```python
unsubscribe_watchlist(interest_id="<id>")
unsubscribe_digest(subscription_id="<id>")
```

### ⚠️ Подписки НЕ идемпотентны

Повторный `subscribe_*` с теми же параметрами создаст **новую** подписку с новым UUID. Если перезапускаешь скрипт настройки — сначала почисть существующие, либо проверь `list_*` перед `subscribe_*`. См. ISSUE-10 в bug-report.md.

### Best practices

1. **Validate keywords/description вручную** на этапе planning — сейчас нет preview-инструмента (см. ENH-13). Можно использовать `search_knowledge_base` с теми же keywords и оценить релевантность top results.
2. **Не более 5-7 watchlist одновременно** — иначе сложно различать пуши и легко проспать главное.
3. **Threshold tuning итеративно:** start с 0.6, через неделю смотри matches, корректируй.
4. **Periodic review:** раз в месяц `list_watchlists` → удалять устаревшие.

---

## Quick reference card

```
CHECK STATUS:           list_channels(workspace_id=...)
CHECK ONE CHANNEL:      get_pipeline_status(channel_id=...)
ADD CHANNEL:            add_channel(channel_id="...") + add_workspace_source(...)
TOPICIZE NEW:           docker compose exec tg_parser tg-parser topicize --channel X
LINK TOPICS:            docker compose exec tg_parser tg-parser link-topics
SEE RELATED:            get_related_topics(topic_id="...")
CROSS-CHANNEL STATS:    get_cross_channel_stats() or with workspace_id=...
SEARCH:                 search_knowledge_base(query="...")
ASK Q:                  ask_question(question="...")
SUBSCRIBE WATCHLIST:    subscribe_watchlist(title, channel_ids, chat_id, keywords, description)
SUBSCRIBE DIGEST:       subscribe_digest(name, channel_ids, chat_id, cron, timezone)
LIST SUBSCRIPTIONS:     list_watchlists() / list_digests()
UNSUBSCRIBE:            unsubscribe_watchlist(id) / unsubscribe_digest(id)
```

## SSH-base operations (до фикса MCP gaps)

```
SSH:                    ssh -p 2296 user@212.72.189.15
LOGS:                   docker compose logs --since 30m tg_parser
TOPICIZE:               docker compose exec tg_parser tg-parser topicize --channel X
LINK:                   docker compose exec tg_parser tg-parser link-topics
INSPECT JOBS:           docker compose logs tg_parser | grep apscheduler
RESTART:                docker compose restart tg_parser
```
