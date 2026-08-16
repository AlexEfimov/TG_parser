# Runbook — BUG-102: форма ответов read-поверхности (R3)

**Создан:** 2026-08-16 (closeout R3). **Статус: ВЫПОЛНЕНО** — код+деплой **2026-08-15** (merge `#428` → `4010ea7`, `c0fd5ff`); smoke F-04+F-05 **записан 2026-08-16** в эту сессию. BUG-102 `resolved`. Это запись closeout, не процедура деплоя: recreate в этой сессии не делали.

**Что вошло в `#428`:** хелпер [`project_search_result`](../../tg_parser/services/search_result_projection.py); снятие legacy-ключей `subscriptions` / `interests`; обёртка `ChannelListResult{items, degraded, …}` (F-07 закрыт в [BUG-098](../notes/BUG_LOG.md)). GUIDE описывает `entry_type` / `title`.

**Breaking:** страницу читать из `items`; topic-хит = `entry_type="topic"` + `title` / `summary` / `channel_id` из карточки. Окно депрекации не возвращать (решение владельца 2026-08-13).

**Docs-only closeout.** Код, тесты и GUIDE в этой сессии не менялись.

---

## 0. Доказательство, что R3 уже на проде

Отдельного `BUG102_R3_DEPLOY` и тега `pre-r3-…` на хосте нет — не выдумывать. Часы recreate R12 / R5 / R6 — не часы R3.

| Факт | Источник |
|---|---|
| Прод **до** R12 (2026-08-16) | HEAD `4010ea7` (R3), образ `74a1fd2b016f…` на трёх сервисах — [`BUG098_R12_DEPLOY.md`](BUG098_R12_DEPLOY.md) §0 |
| Фикс в том образе | `c0fd5ff` входит в `4010ea7`; тот же коммит живёт в каждом следующем образе волны, включая текущий R6 |
| Хост на момент closeout | Inspect ~11:20 UTC: прод-хост `4ecb592` (`#438`), образ R6 `261f178` / `5924dcfc43c3…` (включает `4010ea7`). После merge closeout-промпта `origin/main` = `44aa545` (`#439`, docs-only) — образ не менялся |

---

## 1. Деплой — не в этой сессии

Код уехал 2026-08-15 (`#428`). Recreate «чтобы совпал SHA» не делали и не повторяем: на хосте на момент smoke был `4ecb592`, образ содержит фикс. `#439` (closeout-промпт) — docs-only, образ не двигает. Процедуру Updating из [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) сюда не копировать — это не деплой.

---

## 2. Breaking-контракт

- `list_digests` / `list_watchlists` — страница только под `items`. Ключей `subscriptions` / `interests` нет.
- Topic-хит поиска: `entry_type="topic"`, `title` / `summary` не null, `channel_id` из `card.sources[0]`.
- Message-хит: `entry_type="message"`, `title=null`.
- `list_channels` — конверт `{items, degraded, …}` (F-07; карточка — BUG-098).

---

## 3. Smoke (2026-08-16 ~11:40 UTC, прод-MCP `user-tg-parser`)

Поверхность: прод-MCP. Bot и HTTP search/ask закрыты [`tests/test_bug102_search_topic_projection.py`](../../tests/test_bug102_search_topic_projection.py) — живой bot-smoke не гоняли. `trigger_*` не звали. Первый вызов `search_knowledge_base` вернул пустую ошибку транспорта; повтор тем же аргументом прошёл — форма ниже с повторного вызова.

| Проверка | Команда | Ожидание | Факт 2026-08-16 ~11:40 UTC |
|---|---|---|---|
| F-04 topic-хит | `search_knowledge_base(query="Психологическое благополучие и самооценка", channel_id="foodf4thought", mode="hybrid", limit=8)` | хит `source_ref` начинается с `topic:`, `entry_type="topic"`, `title` / `summary` / `channel_id` не null | ✅ первый хит `topic:tg:foodf4thought:post:651`, `entry_type="topic"`, `title="Психологическое благополучие и самооценка"`, `summary` не null, `channel_id="foodf4thought"`, `degraded=false` |
| F-04 message рядом | тот же ответ | хотя бы один `entry_type="message"` с `title=null` | ✅ второй хит `tg:foodf4thought:post:687`, `entry_type="message"`, `title=null` |
| F-05 digests | `list_digests(limit=5)` | есть `items`, нет `subscriptions` | ✅ ключи `count/total/offset/limit/has_more/items/pagination_pending`; `subscriptions` нет; `total=4`, `has_more=false` |
| F-05 watchlists | `list_watchlists(limit=5)` | есть `items`, нет `interests`; `total` ≈ 24 | ✅ те же ключи; `interests` нет; `total=24`, `has_more=true` |
| F-07 (регресс не открылся) | `list_channels(limit=2)` | конверт с `items` и `degraded` (bool); `coverage_percent` — число | ✅ `{items, degraded:false, total:14, …}`; `AgeManagment` 96.95, `BiocodebySechenov` 98.56 |

Цифры `total` / coverage — замер этой минуты; форма ключей важнее чисел.

---

## 4. Что этот closeout НЕ закрывает

- **Bot-арм BUG-099** — `get_default_admin()` в исполнителях. Не трогали.
- **BUG-008** — `open` by design.

---

## 5. Откат

Тега `pre-r3-…` нет — не изобретать. Предков образа искать в тегах R12 / R5 / R6:

- `tg_parser:pre-r12-2026-08-16` → `74a1fd2b016f…` — это **сам** R3-образ (прод до R12). Откат R12 возвращает R3, не состояние до него.
- `pre-r5-2026-08-16` / `pre-r6-2026-08-16` — уже новее `4010ea7`.

Откатить форму R3 (вернуть `subscriptions` / `interests` и проекцию topic-хита через `document`) записанным тегом этой волны нельзя: предка до `c0fd5ff` в R12/R5/R6 тегах нет. Если понадобится — искать образ старше `4010ea7` вне этих тегов, не собирать процедуру отсюда.
