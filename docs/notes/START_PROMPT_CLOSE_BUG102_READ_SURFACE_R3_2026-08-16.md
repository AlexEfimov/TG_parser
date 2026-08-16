# START PROMPT — R3 closeout: BUG-102, форма ответов read-поверхности

**Дата:** 2026-08-16 · **Сессия:** closeout R3 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R3, §4 · **Баг:** [BUG-102](BUG_LOG.md) (Medium — read-surface contract, F-04 + F-05)
**Ветка:** prefix `cursor/docs-bug102-r3-closeout`

**Goal (одной строкой):** зафиксировать живой прод-smoke F-04 / F-05, дописать отсутствующий runbook, снять workaround и поставить BUG-102 в `resolved`. Код не писать.

> Это **не** сессия фикса. Код, тесты и GUIDE уехали 2026-08-15 (`#428` → `4010ea7`, `c0fd5ff`) и с тех пор живут в каждом образе, включая текущий R6. Осталось то, без чего карточка держит `in-progress`: записанный smoke и протокол. Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: чтения разрешены; recreate и write-инструменты — **не нужны**. Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. Bot-арм BUG-099, повторный R3-фикс, BUG-098 (b) — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую closeout R3 — BUG-102 уже в коде и на проде; закрываем карточку после smoke и runbook.
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_CLOSE_BUG102_READ_SURFACE_R3_2026-08-16.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-102** — Status ещё `in-progress`, `resolved` только после прод-smoke
> 3. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R3 (баннер: код задеплоен, closeout ждёт smoke), §4 (BUG-102 ещё в «открыты»)
> 4. Коммит `c0fd5ff` / PR `#428` — что именно уехало
> 5. [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) § Search — форма `entry_type` / `title`
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3 (переснять smoke, не поверить таблице ниже). **Код проекции, моделей и GUIDE не менять**, пока smoke не покажет регресс. Recreate сервисов не делать.
>
> Ориентируйся на имена символов. Если на проде форма уже не такая — скажи вслух и остановись, не «чини» закрытое.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-16 ~11:20 UTC, после R6 relink и `#438`):

| Факт | Что ждать на 2026-08-16 |
|---|---|
| Очередь | Основная цепочка `R8→…→R5` и параллельная R6 **закрыты**. Эта карточка — единственный хвост R3. Открыты ещё: bot-арм BUG-099, BUG-008 by design |
| Код | `c0fd5ff` `fix(bug102): project topic hits and mark degraded coverage (R3)`, merge `#428` → `4010ea7` |
| Тесты | [`tests/test_bug102_search_topic_projection.py`](../../tests/test_bug102_search_topic_projection.py) — helper + MCP + HTTP + bot. [`tests/test_mcp_pagination_contract.py`](../../tests/test_mcp_pagination_contract.py) 219–220: `subscriptions` / `interests` нет в `model_fields` |
| `main` vs прод-хост | `origin/main` = `4ecb592` (`#438`). Прод-хост подтянут ff-only на тот же SHA. Образ контейнеров — R6 `261f178` / `5924dcfc43c3…` (включает `4010ea7`) |
| F-07 / BUG-098 (a) | Уже `resolved` 2026-08-16. Live `list_channels(limit=2)` → конверт `{items, degraded:false, total:14, …}`, `AgeManagment` coverage **96.95**. В Artifacts BUG-098 стоит путь `docs/runbooks/BUG102_R3_DEPLOY.md` — **файла нет**. Доказательство, что R3-образ был на проде: [`BUG098_R12_DEPLOY.md`](../runbooks/BUG098_R12_DEPLOY.md) §0, «прод до pull» = `4010ea7` / `74a1fd2b016f…` |
| F-05 live | `list_digests(limit=5)`: ключи `count/total/offset/limit/has_more/items/pagination_pending`, **нет** `subscriptions`. `list_watchlists(limit=5)`: те же ключи, **нет** `interests`; `total=24`, `has_more=true` |
| F-04 live | `search_knowledge_base(query="Психологическое благополучие и самооценка", channel_id="foodf4thought", mode=hybrid)`: первый хит `source_ref=topic:tg:foodf4thought:post:651`, `entry_type="topic"`, `title` = заголовок карточки, `summary` и `channel_id="foodf4thought"` не null. Соседние хиты — `entry_type="message"`, `title=null` |
| Стартовый промпт фикса | Писался 2026-08-15 на ветке `cursor/docs-bug102-r3-start-prompt` (`4b365ee`) и **на `main` не попал**. Не открывать его как текущий scope — сессия фикса уже прошла |
| Workaround | Карточка ещё велит читать `items` и добирать topic через `get_topic_details`. После записанного smoke — снять |
| Не ждать | Деплоя нет. Recreate нет. R12/R5/R6 не пересекаются |

---

## 1. Почему эта сессия существует и почему она сейчас

R3 сделали в правильном порядке: один breaking-PR на три проявления одного пробела (нет контракта tool-ответов). F-07 закрыли вместе с деплоем `#428` и дописали в карточке BUG-098. F-04 и F-05 уехали тем же коммитом, но карточку BUG-102 оставили на `in-progress` «пока нет прод-smoke», а runbook так и не появился. Очередь ушла вперёд (R5, R12, R6). Хвост висит только в журнале.

Повторно писать хелпер / снимать ключи / править GUIDE — это открыть уже закрытый класс. Ценность сессии — доказательство на живой поверхности и одна запись в runbook, чтобы ссылка из BUG-098 перестала быть битой.

---

## 2. Что установлено (не переоткрывать)

1. **Один хелпер, три поверхности.** [`project_search_result`](../../tg_parser/services/search_result_projection.py) в `services/` (ADR-0004: HTTP/bot не импортируют `mcp_server`). Topic: `entry_type`, `title`, `summary`, `channel_id=card.sources[0]`, preview = `summary[:limit]`. Message: `entry_type="message"`, `title=None`. `preview_limit=None` опускает ключ (bot ask). Вызывают: MCP `search_knowledge_base` / `ask_question`, HTTP `rag.py`, bot `_exec_search` / `_exec_ask_question`.
2. **Legacy-ключи сняты одним шагом.** `ListDigestsResult` / `ListWatchlistsResult` — страница только под `items`. Bot `_exec_list_digests` / `_exec_list_watchlists` зовут `_paginate_read_result` **без** `legacy_key`. `legacy_key="channels"` и `"users"` — не F-05, не трогать.
3. **`is_active` на `list_watchlists` уже есть** (MCP аргумент + bot `args.get("is_active")`). Не добавлять второй раз.
4. **F-07 сделан и задеплоен.** `ChannelListResult{items, degraded, …}` в пагинационном реестре. Coverage на проде — число, не `0.0`. Половина (b) — R12, закрыта.
5. **GUIDE и README правились тем же `#428`.** Поиск описывает `entry_type` / `title`. F5-C секции на месте. Шапка GUIDE: «Tools: 47» + команда пересчёта. `rg -c '^@mcp\.tool' tg_parser/mcp_server.py` = **47**. AUDIT §6.4 / §6.5 **не переоткрывать**. README «Bot 32 tools» — это subset без трёх F5-C (`35 − 3 = 32`), не баг closeout. Счётчики не трогать.
6. **R2 уже отбрасывает topic-хит без карточки.** Выживший хит всегда имеет `topic_card`. Ветку `card is None` в проекции не изобретать.
7. **JSON Schema tool-ответов не заводим.** Контракт = модели + GUIDE. Решение владельца 2026-08-13.
8. **Окно депрекации не возвращать.** Ключи сняты; потребителей с `subscriptions[0]` не было.

---

## 3. Scope — строго в этом порядке

### 3.1 Переснять прод-smoke (чтение)

Поверхность: прод-MCP `user-tg-parser`. Bot и HTTP search/ask уже закрыты `test_bug102_search_topic_projection.py` — живой bot-smoke не обязателен. HTTP write и `trigger_*` не звать.

| Проверка | Команда | Ожидание |
|---|---|---|
| F-04 topic-хит | `search_knowledge_base(query="Психологическое благополучие и самооценка", channel_id="foodf4thought", mode="hybrid", limit=8)` | Есть хит `source_ref` начинается с `topic:`, `entry_type="topic"`, `title` не null, `summary` не null, `channel_id` не null |
| F-04 message рядом | тот же ответ | Хотя бы один `entry_type="message"` с `title=null` — чтобы отличить формы, а не «все хиты стали topic» |
| F-05 digests | `list_digests(limit=5)` | Есть `items`, нет ключа `subscriptions` |
| F-05 watchlists | `list_watchlists(limit=5)` | Есть `items`, нет ключа `interests`. `total` ≈ 24 |
| F-07 (регресс не открылся) | `list_channels(limit=2)` | Конверт с `items` и `degraded` (bool). `coverage_percent` — число; **не** требовать «не 0.0» (нулевое покрытие у канала законно) |

Если F-04/F-05 не сходятся — **стоп**, это регресс образа, не «дописать хелпер с нуля». Сравнить установленный `project_search_result` в контейнере `tg_parser_mcp` с `c0fd5ff`.

Цифры §0 — замер 2026-08-16; тик мог сдвинуть `total` watchlists / coverage. Форма ключей важнее чисел.

### 3.2 Runbook, которого нет

Создать [`docs/runbooks/BUG102_R3_DEPLOY.md`](../runbooks/BUG102_R3_DEPLOY.md). Образец тона — [`BUG104_R6_DEPLOY.md`](../runbooks/BUG104_R6_DEPLOY.md) / [`BUG098_R12_DEPLOY.md`](../runbooks/BUG098_R12_DEPLOY.md).

Обязательно в файле:

- статус **ВЫПОЛНЕНО**: код+деплой **2026-08-15** (`#428` → `4010ea7`); smoke F-04+F-05 **записан в эту сессию**;
- что вошло: хелпер проекции, снятие `subscriptions`/`interests`, `ChannelListResult` (F-07 закрыт в BUG-098);
- breaking: читать `items`; topic-хит = `entry_type="topic"`;
- smoke-таблица из §3.1 с фактами этой сессии;
- доказательство деплоя R3, **не выдумывать часы recreate**: R12 runbook §0 фиксирует прод **до** R12 как `4010ea7` / образ `74a1fd2b016f…`. Отдельного `BUG102_R3_DEPLOY` и тега `pre-r3-…` на хосте может не быть;
- откат: предков образа искать в R12/R5/R6 тегах, не изобретать `pre-r3`;
- что не закрывает: bot-арм BUG-099, BUG-008.

Не писать процедуру recreate «как будто деплоим сейчас». Не копировать часы recreate из R12/R6 как будто это R3.

### 3.3 Журнал и план

Одним docs-PR, после §3.1:

1. **BUG-102** — `Status` = `resolved` 2026-08-16; в блоке «что открыто» как у BUG-103/104; Workaround снять; Artifacts — job-less, живые вызовы §3.1 + runbook.
2. **PLAN §R3** — баннер «исполнена и задеплоена 2026-08-15 / smoke 2026-08-16»; в §4 убрать BUG-102 из «открыты».
3. Битая ссылка в BUG-098 Artifacts на `BUG102_R3_DEPLOY.md` начинает резолвиться файлом из §3.2.

Этот closeout-промпт уезжает в `docs/notes/archive/` **в том же PR**, который ставит BUG-102 в `resolved` (AUDIT §4: промпт на верхнем уровне = сессия не закрыта; этот PR сессию закрывает). Исторический промпт фикса с ветки `cursor/docs-bug102-r3-start-prompt` на `main` не тащить.

---

## 4. Что не делать

- Не менять `project_search_result`, модели MCP/HTTP/bot, `_paginate_read_result`.
- Не возвращать `subscriptions` / `interests` «для совместимости».
- Не заводить JSON Schema tool-ответов.
- Не трогать `legacy_key="channels"` / `"users"`.
- Не трогать `get_default_admin()` и bot-арм BUG-099.
- Не открывать R12 / coverage SQL.
- Не recreate `tg_parser` / `mcp` / `tg_bot` «чтобы совпал SHA» — на хосте уже `4ecb592`, образ содержит фикс.
- Не вызывать `trigger_*`.
- Не править `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Не брать в работу AUDIT §6.3 (`ENV_VARIABLES_GUIDE`) и переезд всех `START_PROMPT*`.
- Не править счётчики «47 / 32 tools» в README — 32 это subset без F5-C, не дефект.

---

## 5. Тесты

Код не меняется, README-счётчики не трогать — полный PR standard **не** обязателен. Docs-only PR. Если §3.1 показал регресс — стоп, это уже другая сессия, и тогда PR standard обязателен.

---

## 6. Финальный ответ сессии

Одним сообщением: сошлась ли форма на проде (topic-хит + отсутствие legacy-ключей); SHA runbook / записи; BUG-102 `resolved` или нет. Если smoke не сошёлся — что именно расходится и стоп.

---

## 7. Ссылки

- [BUG-102](BUG_LOG.md); F-04 / F-05 — [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](CODE_REVIEW_BOT_MCP_2026-08-12.md).
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R3, §4.
- `#428` / `c0fd5ff` / `4010ea7`.
- `tg_parser/services/search_result_projection.py`.
- `tg_parser/mcp_server.py` — `SearchResultItem`, `ListDigestsResult`, `ListWatchlistsResult`, `ChannelListResult`.
- `tests/test_bug102_search_topic_projection.py`, `tests/test_mcp_pagination_contract.py`.
- Исторический промпт фикса (не на `main`): ветка `cursor/docs-bug102-r3-start-prompt`, коммит `4b365ee`.
