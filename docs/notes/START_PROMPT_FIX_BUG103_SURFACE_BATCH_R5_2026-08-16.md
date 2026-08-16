# START PROMPT — R5: BUG-103, четыре мелочи поверхности bot/MCP

**Дата:** 2026-08-16 · **Сессия:** R5 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R5, §4 · **Баг:** [BUG-103](BUG_LOG.md) (Medium — батч F-06, F-08, F-09, F-11)
**Ветка:** prefix `cursor/fix-bug103-surface-batch-r5`

**Goal (одной строкой):** описание сервера совпадает с поведением; ресурс тем живой; отрицательные `offset`/`limit` не крутят «ещё»; заголовок watchlist с `<`/`&` не ломает HTML.

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: правки только по явному GO; чтения разрешены. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) требует живого Postgres, в облаке его нет. Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. R5 — **не** деплой-сессия. Деплой потом заденет `mcp` и `tg_bot` (общий образ `tg_parser` — recreate всех трёх; урок R10: recreate parser сдвигает hourly tick). R12, R6, bot-арм BUG-099 — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R5 — четыре мелочи поверхности bot/MCP одним PR (BUG-103: F-06, F-08, F-09, F-11).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG103_SURFACE_BATCH_R5_2026-08-16.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-103** — симптомы, пробы, почему CI не поймал
> 3. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R5 (scope), §4 (очередь: R3 задеплоена, следующая — эта; параллельно R12, R6)
> 4. `docs/notes/AUDIT_DOCUMENTATION_2026-08-12.md` § Workspaces — строка «неизвестный workspace_id» (вход F-06)
> 5. `tests/README.md` — default обязателен, PR standard перед merge
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1–3.4 (red/green на четырёх находках). R12 (`coverage_counts_by_channel`), R6 (стоп-лист), bot-арм BUG-099, вынос потолка страницы в `.env`, HTTP-срезы в `api/routes/` — **вне scope**.
>
> Строки в плане — на `f005f93`. Ниже — перечитанные 2026-08-16 с `main` (`4010ea7`, после R3). Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-16, после деплоя R3):

| Факт | Что ждать на 2026-08-16 |
|---|---|
| Очередь | R3 задеплоена (`4010ea7` / `#428`, [`BUG102_R3_DEPLOY.md`](../runbooks/BUG102_R3_DEPLOY.md)). Следующая в основной цепи — эта. Параллельно: R12, R6. Bot-арм BUG-099 открыт, не чинить |
| `main` vs прод | Код R3 на проде: образ `74a1fd2b016f`, HEAD `4010ea7`. Docs-record R3 — `#429` (не блокирует эту сессию) |
| Четыре дефекта живы | `_MCP_INSTRUCTIONS` 314 всё ещё «raises a 404-like error»; `resource_channel_topics` итерирует `TopicListResult`; `paginate_items` / `_paginate_read_result` / оба `list_topics` не зажимают отрицательный `limit`; watchlist confirmation без `html.escape` |
| Что R3 уже починил рядом | `resource_channels` читает `result.items` ([`test_resource_channels_iterates_items`](../../tests/test_bug098a_channel_list_degraded.py)); `list_channels` в пагинационном контракте; digest confirmation уже с `html.escape`; watchlist **preview** уже с `html.escape` (`bot/tools.py` 4652) |
| Не ждать | Пересечения с R12/R6 нет. Жёстких зависимостей после R3 не осталось |

---

## 1. Почему эта сессия существует и почему она сейчас

Четыре независимых мелких. Общего корня нет — и это причина батча, а не рефакторинга. Ни одна правка не меняет контракт ответа. F-06 / F-09 / F-11 — по несколько строк. F-08 больше: четыре среза плюс десять INTEGER в декларациях (план на `f005f93` видел два места — на `4010ea7` этого мало, см. §2.5). Дробить на четыре записи с четырьмя `Status` дороже, чем закрыть одним PR.

R3 закрыта. R5 ничего не блокирует и ничем не блокируется. В очереди она следующая не потому, что срочная, а потому что основная цепочка кончилась, а R12/R6 требуют замера / симуляции.

Ценность не в строках фикса. F-09 вернулся бы при следующей смене типа возврата — R3 уже один раз починил `resource_channels` и оставил `resource_channel_topics` мёртвым. Поэтому три smoke на ресурсы — не «ещё тесты», а страховка класса.

---

## 2. Что установлено (не переоткрывать)

1. **Поведение unknown/foreign `workspace_id` выбрано давно: не исключение наружу.** Восемь read-инструментов ловят `WorkspaceNotFound`. List/search отдают пустую страницу / пустой search / benign no-context. `get_topic_details` / `get_document` отдают строку `Topic not found: …` (`mcp_server.py` 1476–1477) — тот же «не палим существование», не пустой список. Docstring'и и [`MCP_AGENT_GUIDE`](../MCP_AGENT_GUIDE.md) («empty / 404-like result») это описывают. Врёт только `_MCP_INSTRUCTIONS` — единственный текст, который MCP-клиент читает **до** вызова. F-06 = поправить инструкцию под факт. **Не** менять инструменты, чтобы они «действительно бросали 404».
2. **`WorkspaceNotFound` внутри `_resolve_workspace_scope` остаётся.** Докстринг хелпера (`mcp_server.py` 1120–1122: «404-like; callers translate to `[]`») точен. Его не переписывать в «returns empty» — исключение живёт на границе хелпера, не на границе инструмента.
3. **`resource_channels` уже на `result.items`.** R3, тест есть. F-09 — только `resource_channel_topics` (`topics` → `topics.items`). `resource_topic` уже делает `detail.model_dump()`. Smoke всё равно на **все три** — иначе класс вернётся.
4. **Отрицательный `limit` в Python — срез с конца.** `items[0:-5]` на 50 строках = 45 элементов, `has_more=True`, `pagination_pending.offset=-5`. Bot-FSM «ещё» это послушно повторяет. `paginate_items` клампит только `offset` (`max(offset, 0)`), `limit` отдаёт в срез как есть. `_paginate_read_result` не клампит ни то, ни другое и **не вызывает** `paginate_items`.
5. **`list_topics` — третья и четвёртая копии того же среза.** План называет `paginate_items` + `_paginate_read_result`. На `4010ea7` этого мало:
   - MCP `list_topics` 1396–1421: `page = cards[offset : offset + limit]`, свой `has_more`
   - bot `_exec_list_topics` 2127–2165: то же, **не** через `_paginate_read_result` (свой `n`, свой hint)
   Если починить только хелпер, `list_topics` на обеих поверхностях останется сломанным — а проба F-08 как раз про него.
6. **INTEGER в `TOOL_DECLARATIONS` — ровно десять, без `minimum`/`maximum`:**

   | # | Инструмент | Поле |
   |---|---|---|
   | 1 | `search_knowledge_base` | `limit` |
   | 2–3 | `list_topics` | `offset`, `limit` |
   | 4 | `get_topic_versions` | `limit` (сервер уже 1..200) |
   | 5–6 | `get_topic_history_diff` | `version_a`, `version_b` |
   | 7 | `add_channel` | `batch_size` |
   | 8 | `set_llm_config` | `max_tokens` |
   | 9–10 | `register_user` / `update_user` | `max_channels` |

   `list_channels` / `list_digests` / `list_watchlists` / `list_users` в схеме Gemini **не** объявляют `offset`/`limit` (пустой `properties` или только `is_active`), хотя исполнители их читают. **Не** добавлять эти поля в декларации в этой сессии — это расширение схемы, не F-08. Код-кламп их всё равно поймает, когда LLM передаст лишнее.
7. **Watchlist preview уже экранирует, confirmation — нет.** Preview (`bot/tools.py` 4650–4653): `html.escape(title)`. Confirmation (~4741): сырой `created_interest.title` внутри `<b>`. Digest confirmation (~4200) уже с `html.escape(created_sub.name)`. `html` уже импортирован (`bot/tools.py:12`). F-11 = confirmation. Другой `parse_mode="HTML"` в том же файле — прогресс экспорта `<code>{normalized}</code>` (~3731); это не F-11. Свип — **read-only**: чинить ещё один сайт только если это пользовательский текст внутри HTML-тегов. Не трогать `bot/handlers.py` и `DefaultBotProperties(parse_mode="HTML")` в `main.py`.
8. **Верхний потолок страницы в коде не обязателен.** F-08 закрывается клампом «отрицательное / ноль», не `limit=500 → 200`. `paginate_items` сегодня отдаёт запрошенный положительный `limit` как есть (MCP `list_topics(limit=500)`, `list_users(limit=1000)`). **Не** вводить `MAX_PAGE_LIMIT` в `paginate_items`. `maximum` — только в десяти Gemini-декларациях (подсказка модели). Потолок в `.env` не заводить (BUG-092).
9. **`limit=None` на MCP list-инструментах (кроме `list_topics`) значит «вся страница».** Кламп не должен превратить `None` в число. `list_topics` MCP: `limit: int = 50`, не `None`.
10. **`limit=0` уже расходится на двух путях — выбрать одно и записать в тесте.** `_paginate_read_result` делает `int(args.get("limit", default) or default)`: ноль ложный → **default страницы (20)**. Bot/MCP `list_topics` оставляют `0` и режут пустую страницу с `has_more=True`. `get_topic_versions` на `limit=0` уже возвращает ошибку «1..200» ([`tests/test_f5c_mcp_tools.py`](../../tests/test_f5c_mcp_tools.py) 253) — **не** клампить его в 1 и не ломать этот тест. Правило этой сессии: в `paginate_items` и в обоих `list_topics` ноль и отрицательное → **1**; в `_paginate_read_result` оставить `or default` (ноль → 20), затем отдать уже положительный `limit` в `paginate_items`. Отрицательный `limit` в хелпере: не полагаться на `or` (минус истинный) — зажать до 1 **до** вызова `paginate_items` либо после, но не оставлять `-5` в срезе.
11. **`get_default_admin()` не трогать.** В `_exec_list_topics` и `_exec_subscribe_watchlist` он стоит — это bot-арм BUG-099.
12. **HTTP-срезы — тот же класс, не этот баг.** `api/routes/topics.py:105`, `watchlists.py:315`, `digests.py:342` режут `offset : offset + limit` руками. В компонентах BUG-103 их нет. Не «закрывать класс» по HTTP.

---

## 3. Scope — строго в этом порядке

Строки ниже — перечитанные 2026-08-16 с `4010ea7`.

### 3.1 F-06 — `_MCP_INSTRUCTIONS` под факт

**Сегодня** (`mcp_server.py` 310–315):

```
Read tools (…) accept optional workspace_id …
Unknown / foreign workspace_id raises a 404-like error (existence is never leaked).
```

**Нужно:** одна строка по гайду, не «raises» и не голое «empty result» (это врёт для get-details): unknown / foreign `workspace_id` **returns an empty / 404-like result** (existence is never leaked). Не трогать docstring'и инструментов и гайд — они уже правы.

Тест: `assert "raises a 404-like error" not in _MCP_INSTRUCTIONS`; плюс позитив на «empty / 404-like» (или эквивалент, где есть и empty, и 404-like). Файл рядом с остальными bug-тестами, например `tests/test_bug103_surface_batch.py`.

После правки в [`AUDIT_DOCUMENTATION_2026-08-12.md`](AUDIT_DOCUMENTATION_2026-08-12.md) строка Workspaces «неизвестный workspace_id» может стать `agrees` — одной правкой статуса, без переписывания аудита.

### 3.2 F-09 — `resource_channel_topics` читает `.items`

**Сегодня** (`mcp_server.py` 4607–4615):

```
topics = await list_topics(channel_id=channel_id)
return json.dumps([t.model_dump() for t in topics], …)
```

`list_topics` возвращает `TopicListResult`. Итерация Pydantic v2 по модели даёт кортежи `(field, value)` → `AttributeError: 'tuple' object has no attribute 'model_dump'`.

**Нужно:** `[t.model_dump() for t in topics.items]` — как `resource_channels` уже делает с `result.items`.

Тесты (все три, даже если два зелёные на текущем коде):

| Ресурс | Что assert |
|---|---|
| `resource_channels` | JSON-список, элементы с `channel_id` (уже есть — не дублировать слепо, можно оставить тот и добавить два новых) |
| `resource_channel_topics` | JSON-список topic-summary, не exception; мок `list_topics` → `TopicListResult` |
| `resource_topic` | JSON-объект карточки либо `{"error": …}` |

Red до правки — только topics-ресурс. Два других smoke ловят следующий drift типа.

### 3.3 F-08 — один кламп нижней границы, все срезы через него

**Сегодня четыре места режут список:**

| Место | Срез | Кламп offset | Кламп limit |
|---|---|---|---|
| `paginate_items` | `items[safe_offset : safe_offset + limit]` | да (`max(0, …)`) | нет; `None` = вся страница |
| `_paginate_read_result` | `rows[offset : offset + limit]` | нет | нет; `0` → default через `or` |
| MCP `list_topics` | `cards[offset : offset + limit]` | нет | нет |
| bot `_exec_list_topics` | то же | нет | нет |

**Нужно:**

1. В `paginate_items` (нижняя граница, **без** верхнего потолка):
   - `limit is None` — как сейчас (полная выдача, `has_more=False`).
   - `offset < 0` → `0`.
   - `limit is not None` и `limit < 1` → `1` (отрицательный и ноль больше не значат «с конца» / «пустая страница с has_more»).
   - Положительный `limit` (в т.ч. 500, 1000) — как есть.
2. `_paginate_read_result` вызывает `paginate_items`. Ноль по-прежнему `or default` (20). Отрицательный `limit` зажать до 1 **до** среза. Нумерация `n` и поля ответа / `pagination_pending` — по **зажатым** `offset`/`limit`. Тогда «ещё» не реплеит `-5`.
3. MCP `list_topics` и bot `_exec_list_topics` режут через `paginate_items`. В `TopicListResult` / bot-dict тоже зажатые значения. Не прогонять `list_topics` через `_paginate_read_result` — у него свой `n` и нет `legacy_key`; это лишний рефакторинг.

Декларации: добавить `minimum`/`maximum` к десяти INTEGER из §2.6. Границы = уже существующая серверная валидация, где она есть (`get_topic_versions` 1..200). Для пагинации в схеме: `offset` ≥ 0, `limit` ≥ 1; `maximum` у `list_topics.limit` не меньше живого MCP-дефолта 50. Для `batch_size` / `max_channels` / `max_tokens` / `version_*` — не отвергнуть документированные дефолты **и живые прод-значения** (batch 100 в схеме, на проде бывает 500 — `maximum` не ставить 100). Схема Gemini — подсказка модели, не замена клампа и не серверная валидация `add_channel`.

Тесты:

- `paginate_items(items, offset=0, limit=-5)` на 50 элементах → **страница из 1 элемента**, не 45; `has_more` согласован с зажатым limit (на 50 элементах — `True`).
- `paginate_items(..., offset=-10, limit=5)` → те же 5, что с `offset=0`.
- `paginate_items(..., limit=None)` без изменений.
- `paginate_items(..., limit=500)` на 50 элементах → все 50, не обрезать до 200.
- `_paginate_read_result("list_watchlists", {"limit": -5}, rows)` → `limit` в ответе ≥ 1, `pagination_pending.args.offset` ≥ 0 (если `has_more`).
- `_paginate_read_result(..., {"limit": 0}, rows)` → `limit == default` (20), не 1 и не пустая страница.
- MCP `list_topics` и/или bot `_exec_list_topics` с `limit=-5` — не 45 из 50; с `limit=0` — страница из 1 (правило §2.10).
- `get_topic_versions(limit=0)` по-прежнему ошибка 1..200.
- Сторож деклараций: у каждого INTEGER в `TOOL_DECLARATIONS` есть `minimum` и `maximum` (иначе следующий параметр приедет голым).

Контракт-тесты на **валидных** входах (`test_mcp_pagination_contract.py`, `test_pagination_contract_tdd.py`) должны остаться зелёными без подгонки ожиданий.

### 3.4 F-11 — `html.escape` на confirmation watchlist

**Сегодня** (`bot/tools.py` 4738–4746):

```
f"🔔 Watchlist <b>{created_interest.title}</b> {verb_ru}.\n"
…
parse_mode="HTML",
```

**Нужно:** `html.escape(created_interest.title)` — как у digest на `created_sub.name`. Preview уже экранирует — не дублировать работу там. Свип `parse_mode="HTML"` в `bot/tools.py` — read-only (см. §2.7).

Тест: `_exec_subscribe_watchlist` с title `A < B & C`, замоканный bot; `send_message` содержит `<b>A &lt; B &amp; C</b>`. Обёртки `<b>`/`</b>` законны — не писать assert «в тексте нет сырых `<`». Образец мока — [`tests/test_f11_bot_tools.py`](../../tests/test_f11_bot_tools.py).

---

## 4. Тесты и прогоны

- Новый файл на батч (`tests/test_bug103_surface_batch.py`) **или** четыре точечных рядом с существующими — на вкус, но red-by-revert обязан быть по каждой находке отдельно (откатил F-09 — падает только topics-smoke, не F-06).
- Default обязателен после правки.
- PR standard (`TEST_POSTGRES=1`) перед merge: это app-code (bot / MCP / utils).
- Max local / compose **не** нужны: дефекты внутрипроцессные.
- Не расширять CI compose job.

---

## 5. Не делать

- Не оптимизировать `coverage_counts_by_channel` и не поднимать `statement_timeout` (R12).
- Не вводить стоп-лист keywords (R6).
- Не трогать `get_default_admin()` (bot-арм BUG-099).
- Не вводить `MAX_PAGE_LIMIT` в `paginate_items` и не выносить потолок в `.env` (BUG-092).
- Не менять `WorkspaceNotFound` на исключение наружу и не «чинить» docstring'и, которые уже говорят «empty» / «404-like».
- Не добавлять `offset`/`limit` в Gemini-схемы `list_channels` / `list_digests` / `list_watchlists` / `list_users`.
- Не прогонять `list_topics` через `_paginate_read_result`.
- Не трогать HTTP `GET /channels` / `GET /channels/{id}/stats` и не чинить срезы в `api/routes/topics.py` / `watchlists.py` / `digests.py`.
- Не ломать `get_topic_versions(limit=0)` → ошибка 1..200.
- Не ставить `batch_size.maximum=100` — на проде бывает 500.
- Не править `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Не recreate прод без GO. Коммит и PR — по явному запросу.

---

## 6. Финальный ответ сессии

Одним сообщением: что изменилось в инструкции (формулировка empty / 404-like), в ресурсе тем, в клампе нижней границы (и что `list_topics` на обеих поверхностях теперь через `paginate_items`, без верхнего потолка), как разведены ноль в хелпере (20) и в `list_topics` (1), что сделано с десятью INTEGER, как экранируется watchlist confirmation; какие тесты краснели на revert по каждой находке; результаты default и PR standard. Отдельной строкой — что осталось: R12 (покрытие), R6 (стоп-лист), bot-арм BUG-099, HTTP-срезы. Почему это не сделано здесь.

---

## 7. Ссылки

- [BUG-103](BUG_LOG.md) — батч F-06 / F-08 / F-09 / F-11.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R5, §4.
- [`AUDIT_DOCUMENTATION_2026-08-12.md`](AUDIT_DOCUMENTATION_2026-08-12.md) § Workspaces — вход F-06.
- [`BUG102_R3_DEPLOY.md`](../runbooks/BUG102_R3_DEPLOY.md) — вход: R3 на проде, `resource_channels` уже на `.items`.
- TD-D-02 / #40 — пагинационный контракт; эта сессия чинит невалидный вход, не форму хинта.
- Соглашение N1 — HTML-escape пользовательского текста; F-11 — confirmation watchlist (preview уже экранирован).
- [`tests/README.md`](../../tests/README.md) — default / PR standard.
- `tg_parser/mcp_server.py` — `_MCP_INSTRUCTIONS` (314), `list_topics` (1396–1421), `get_topic_details` (1476–1477), `resource_*` (4596–4624).
- `tg_parser/bot/tools.py` — `_paginate_read_result` (208–251), `_exec_list_topics` (2094–2172), watchlist preview (4650–4653), confirmation (4738–4746), `TOOL_DECLARATIONS` INTEGER.
- `tg_parser/utils/pagination.py` — `paginate_items` (48–68).
- HTTP-близнецы (не трогать): `api/routes/topics.py:105`, `watchlists.py:315`, `digests.py:342`.
