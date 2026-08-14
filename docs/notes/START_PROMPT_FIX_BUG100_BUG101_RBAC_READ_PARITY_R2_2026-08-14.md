# START PROMPT — R2: BUG-100 + BUG-101, RBAC-паритет read-инструментов

**Дата:** 2026-08-14 · **Сессия:** R2 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R2, §4 · **Баги:** [BUG-100](BUG_LOG.md) (High, латентно) + [BUG-101](BUG_LOG.md) (Low)
**Ветка:** prefix `cursor/fix-bug100-bug101-rbac-read-parity-r2`

**Goal (одной строкой):** ни один read-инструмент **bot/MCP** не отдаёт чужие данные, когда чужой идентификатор задан **явно**; на HTTP — только те же дыры, что уже названы (F-02-близнец `GET /topics`, F-10 export status + download). CI ловит регресс этого класса, а не только то, что код уже делает.

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: правки только по явному GO; чтения разрешены. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) требует живого Postgres, в облаке его нет. Первый шаг в любом режиме — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. R2 — **не** деплой-сессия: прод-записи не начинать без GO. Docs-closeout R1 (`657f0e7`) на прод не подтягивать «чтобы совпали SHA». `tg_parser` на проде не пересоздавать без нужды (сдвигает hourly incremental-pipeline — урок R10).

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R2 — RBAC-паритет read-инструментов (BUG-100 + BUG-101).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG100_BUG101_RBAC_READ_PARITY_R2_2026-08-14.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, записи **BUG-100** и **BUG-101** — симптомы, проба F-02, почему CI не поймал
> 3. `docs/notes/BUG_LOG.md`, запись **BUG-093** — образец класса и прод-smoke (одноразовый `user`-токен, проверка, отзыв)
> 4. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R2 (scope), §4 (очередь: R1 задеплоена, следующая — эта; `R2 → R3`)
> 5. `tests/README.md` — режимы прогона; **PR standard обязателен** (это app-code: authz)
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1–3.3 (red/green на трёх дефектах). Bot-арм BUG-099, форма ответов R3, `process.py` jobs — **вне scope**.
>
> Строки в плане — на `f005f93`. Ниже — перечитанные 2026-08-14 с `main` (`657f0e7` docs / `963b16e` код). Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить):

| Факт | Что ждать на 2026-08-14 |
|---|---|
| Очередь | R1 задеплоена (`963b16e`, MCP-образ `5f6939dc`). Следующая — эта сессия. Параллельно: R12, R6 |
| Резолв идентичности | MCP: UUID miss/error → `PermissionError`, не admin. Bot-арм BUG-099 ещё открыт — **здесь не чинить** |
| Латентность | `list_users`: 5 строк `user`, без `user_auth_mappings`; живой `mcp_token` только у admin. Если не-admin credential уже есть — сказать вслух: High перестаёт быть латентным |
| `main` vs прод | Код MCP на проде — `963b16e`. Локальный / `origin/main` может быть `657f0e7` (docs-closeout R1). Это не drift кода. Docs на прод не подтягивать |
| Не ждать | Пересечения файлов с R12/R6 нет. Гейт R1 снят. Жёсткая зависимость осталась одна: `R2 → R3` |

---

## 1. Почему эта сессия существует и почему она сейчас

До R1 любой вердикт прав был условен: фильтр по `allowed_channel_ids` ничего не стоит, если при ошибке БД вызывающий уже admin с `allowed=None`. R1 задеплоена — проверки R2 больше не условны.

Сам фикс F-02 — четыре строки. Ценность сессии не в них. Это **третий подряд** дефект одного класса:

| Запись | Что пропущено | На какой ветке |
|---|---|---|
| BUG-093 | ownership-check | `add_channel`, канал уже существует |
| BUG-094 | поля, которые write не должен трогать | тот же `add_channel`, существующая строка |
| BUG-100 | RBAC-фильтр | `list_topics`, `channel_id` задан явно |

Все три прошли мимо CI по одной причине: тест описывал, что код делает, а не чего он делать не должен. `test_exec_list_topics_uses_list_by_channels_for_user` вызывает `_exec_list_topics({})` — без `channel_id`, то есть ровно ту ветку, где проверка есть.

На проде по-прежнему нет не-admin credential — High латентный. Гейт тот же, что у R1: закрыть **до выпуска первого не-admin credential**, не «срочно».

---

## 2. Что установлено (не переоткрывать)

1. **R1 закрыта на MCP.** Merge `#421` → `963b16e`, деплой 2026-08-14, протокол [`BUG099_R1_DEPLOY.md`](../runbooks/BUG099_R1_DEPLOY.md). UUID без строки / с ошибкой БД → `PermissionError`. Счётчик `tg_mcp_identity_resolve_total`. Smoke в ту же минуту: рабочий admin-токен жив, выдуманный UUID отказан. **Bot-арм записи открыт** — hardening после R2, не эта сессия.
2. **Три дефекта на `main` 2026-08-14 ещё живы** (перечитано, не из плана). Код не уехал из-под находок.
3. **MCP-близнец F-02 уже правильный.** Его не «улучшать» и не переносить workspace-логику в bot: у bot `list_topics` нет `workspace_id`. Копируется только условие на `channel_id`.
4. **`Job.client` уже пишется.** И HTTP `start_export` (`export.py:237`), и MCP `export_channel` (`mcp_server.py:3044`) ставят `client=user.name`. Поля `owner_user_id` нет. Что сверять — `job.client` против `user.name` или новое поле — решает эта сессия (§3.2), не «придумать заново, есть ли данные».
5. **У bot нет `get_export_status`.** F-10 на bot-поверхности не с чем парить. Третья точка, которой в плане не было: HTTP `GET /export/status/{job_id}` (`export.py:275–276`) резолвит `_user` и тоже не использует — тот же дефект, что download. `GET /api/v1/jobs` и `GET /api/v1/status/{job_id}` в `process.py` тоже резолвят `_user` вхолостую — это **PROCESSING**-джобы, не export; список export-джоб по-прежнему нет. Не расширять F-10 туда.
6. **HTTP-близнец F-02 жив.** `GET /api/v1/topics?channel_id=` (`api/routes/topics.py` `91–92`) — та же ветка, что bot: явный `channel_id` → `list_by_channel` без проверки. План называл только bot; это те же четыре строки, не новая сессия. Остальной HTTP (rag/documents/`process.py`/watchlists) **не** трогать.
7. **Первая половина F-04 — форма ответа — это R3 / BUG-102.** Topic-хит проецируется через `document`, которого у него нет → строка из `null`. Здесь чинится только второй путь (append вне `if card:`). Проекцию и `entry_type` в ответе не трогать.
8. **Прод-smoke этого класса уже отработан на BUG-093:** одноразовый `user`-токен, вызов, сверка, отзыв, пользователь в `zz-retired-…`. После деплоя и только по GO. Эта сессия — код и тесты.

---

## 3. Scope — строго в этом порядке

Строки ниже — перечитанные 2026-08-14. План §R2 цитирует `f005f93`; drift есть, поведение то же.

### 3.1 F-02 / BUG-100 — bot и HTTP `list_topics` с явным `channel_id`

**Сегодня** (`_exec_list_topics`, [`bot/tools.py`](../../tg_parser/bot/tools.py) `2089–2111`; ветка с `channel_id` — `2103–2105`):

```
if channel_id:
    cards = await topic_card_repo.list_by_channel(channel_id)
    bundles = await topic_bundle_repo.list_by_channel(channel_id)
elif user.allowed_channel_ids is not None:
    cards = await topic_card_repo.list_by_channels(user.allowed_channel_ids)
    …
```

Явный `channel_id` идёт в `list_by_channel` без проверки. `elif` срабатывает только когда канал **не** задан.

**Образец, который копировать** (`list_topics`, [`mcp_server.py`](../../tg_parser/mcp_server.py) `1370–1376`; в плане было `1334–1347` — съехало из-за docstring / `workspace_id`):

```
if channel_id:
    if effective is not None and channel_id not in effective:
        cards = []
        bundles = []
    else:
        cards = await topic_card_repo.list_by_channel(channel_id)
        …
```

В bot нет workspace-scope: вместо `effective` — `user.allowed_channel_ids`. Форма из записи BUG-100:

`if user.allowed_channel_ids is not None and channel_id not in user.allowed_channel_ids: cards = []`

Admin (`allowed_channel_ids is None`) проходит первым — это и есть закрытие побочного риска из плана.

**Red до правки.** Не-admin владеет `own_channel`, спрашивает `foreign_channel` → bot `total≥1` с чужим title. С откатом фикса тот же тест снова красный. Образец стиля: [`tests/test_bug093_add_channel_foreign_source.py`](../../tests/test_bug093_add_channel_foreign_source.py) (3 из 11 падают без гарда). Существующий `test_exec_list_topics_uses_list_by_channels_for_user` **дополнить, не заменить** — он закрывает ветку без `channel_id`.

В этом же файле на `2096` стоит `user = current_user or await get_default_admin()`. Это bot-арм BUG-099. Строку видеть и **не трогать**.

**Тот же `if channel_id:` без проверки** — HTTP `list_topics` в [`api/routes/topics.py`](../../tg_parser/api/routes/topics.py) `91–96`. Та же форма гарда (`allowed_channel_ids is not None and channel_id not in …` → пустая страница, не 403). Red на этом пути — в матрице §3.4, не отдельная сессия. Другие HTTP-роуты (`rag.py`, `documents.py`, `process.py`) не трогать.

### 3.2 F-10 / BUG-101 — владелец джобы на трёх read-путях

`_user` резолвится и не используется в трёх местах (план называл два; третье — тот же дефект, всплыло при перечитывании):

| Поверхность | Символ | Строка 2026-08-14 | В плане |
|---|---|---|---|
| MCP | `get_export_status` | `3082`, `_user` на `3095` | `3060` |
| HTTP | `get_export_status` | `275–276` | не было |
| HTTP | `download_export` | `311–312` | `311` — совпало |

Между резолвом и `return` ссылок на `_user` нет. Что утекает: MCP — `channel_id`, `download_url`, `file_size`; HTTP status (`ExportResponse`) — `download_url` / status / format / level, **не** `channel_id` и не `file_size`; download отдаёт файл. Изоляция export-джоб держится на неугадываемости UUID4: `GET /api/v1/jobs` существует, но фильтрует `job_type=PROCESSING` и export не перечисляет. `job_id` при этом попадает в логи и в переписку с агентом.

**Источник истины — решить в сессии и записать.** Сегодня в `Job` есть `client: str | None` («Authenticated client name»), и оба писателя кладут туда `user.name`, не `user.id`. Два хода:

- сверять `job.client == user.name` (данные уже есть, миграции нет);
- завести `owner_user_id` (сравнение по id устойчивее к переименованию; миграция / бэкфилл старых джоб).

Admin — сквозь, как везде (`user.is_admin` / `allowed_channel_ids is None`). Отказ не должен отличаться от «джобы нет» так, чтобы по ответу было видно, что UUID существует: MCP сегодня на unknown отдаёт `status="unknown"` и `channel_id=None`; HTTP status и download на unknown — 404. Чужой `job_id` должен выглядеть так же, не 403 с «это не твоё». На download проверка владельца — **до** проверки `COMPLETED`: иначе чужой pending даст 400, а неизвестный — 404.

Bot-близнеца нет — не выдумывать.

Существующие тесты экспорта ([`tests/test_f2_parse_only_export.py`](../../tests/test_f2_parse_only_export.py)) гоняют lifecycle под одной личностью. Их не ломать и не «исправлять» под новый отказ. Кейс «вторая личность спрашивает чужой `job_id`» — новый, на MCP и на обоих HTTP-путях.

### 3.3 Второй путь F-04 / BUG-101 — topic-хит без карточки

[`retrieval_service.py`](../../tg_parser/services/retrieval_service.py) `293–308` (строки плана **совпали**):

```
elif sim.entry_type == "topic":
    card = card_map.get(sim.topic_id) if sim.topic_id else None
    if card:
        if channel_id and channel_id not in card.sources:
            continue
        if allowed_channel_ids is not None:
            if not any(s in allowed_channel_ids for s in card.sources):
                continue
    results.append(SearchResult(..., entry_type="topic", topic_card=card))
```

`results.append` стоит **вне** `if card:`. Хит, чью карточку не загрузили, уходит в выдачу с `topic_card=None` и минует `allowed_channel_ids`. Утечка — `source_ref` (и score), не текст карточки.

Занести append под `if card:` либо явно `continue`, если карточки нет. Молча отдавать хит без карточки нельзя: это и есть дыра.

В [`tests/test_f4_coverage_supplement.py`](../../tests/test_f4_coverage_supplement.py) `TestSearchEdgeCases` есть `test_topic_filtered_by_channel_id` (карточка загружена, sources не совпали) и нет ветки `card is None`. Дополнить, не заменить.

**Не делать здесь:** ветку `entry_type="topic"` в `SearchResultItem`, отдачу `entry_type` наружу, чтение `card.title` / `card.summary` в проекции MCP/bot. Это R3.

### 3.4 Тест-обязательство — главный deliverable, не четыре строки фикса

Параметризованный кейс **«чужой идентификатор задан явно»** для каждого read-инструмента из таблицы ниже, на MCP + bot; HTTP — только строки, где колонка HTTP не «не в этой сессии».

Идентификаторы из плана: `channel_id`, `topic_id`, `source_ref`, `job_id`, `interest_id`. Инвентарь — таблица P0 ревью (bot+MCP) плюс HTTP-близнец F-02, которого в P0 не было; не выдумывать инструменты сверх этого:

| id | MCP | bot | HTTP (только названное) | Что уже есть и чего не хватает |
|---|---|---|---|---|
| `channel_id` | `list_topics`, `search_knowledge_base`, `ask_question`, `get_cross_channel_stats`, `get_pipeline_status` | те же `_exec_*` (`search` = `_exec_search`) | `GET /topics?channel_id=` — дыра F-02, как bot | F4-тесты гоняют «канал не задан» / прокидывание `allowed_channel_ids`. Явный чужой `channel_id` на `list_topics` bot **и** HTTP — дыра F-02; на MCP уже пусто. `get_pipeline_status` фильтрует `allowed` после `channel_id` — содержимое не утекает; в матрицу, чтобы ветка не отвалилась. `get_related_topics` **не** принимает `channel_id` (только `topic_id`) |
| `topic_id` | `get_topic_details`, `get_topic_versions`, `get_topic_history_diff`, `get_related_topics` | те же | не в этой сессии | `test_access_denied_for_non_allowed_topic` / `test_topic_denied_for_non_owner` есть; включить в общую параметризацию, не считать «закрыто, значит можно выкинуть». Сегодня отказ — `"No access …"`, unknown — `"not found"`: **не унифицировать** (это форма ответа, R3) |
| `source_ref` | `get_document` | `_exec_get_document` | не в этой сессии | `test_document_denied_for_non_owner` есть — в матрицу. Тот же `"No access"` vs `"not found"` — оставить |
| `job_id` | `get_export_status` | нет | status + download | кейса «вторая личность» нет. Чужой = unknown (MCP `status="unknown"` / HTTP 404), не 403 |
| `interest_id` | `get_watchlist_matches` | `_exec_get_watchlist_matches` | не в этой сессии | owner-check в коде есть (MCP → `count=0`; bot → `"permission"` error). В матрицу как есть, форму не сглаживать |

Не read, не включать: `export_channel`, `unsubscribe_*`, `backfill_watchlist`, `force_resummarize`, write-каналы. `workspace_id` уже закрыт F4-B (`test_f4b_scoping_read_tools.py`, unknown/foreign → пусто, existence не утекает) — не дублировать, не считать частью этой матрицы. MCP-ресурсы (`resource_channel_topics`) — R5 / BUG-103.

Ожидание на чужой id: **нет чужого содержимого**. Форму отказа не унифицировать по поверхностям: `job_id` должен совпасть с unknown (новый контракт F-10); `topic_id` / `source_ref` / `interest_id` оставляют сегодняшние строки (`"No access"` / `"permission"` / пусто). Search/ask с явным чужим `channel_id` сегодня поднимают `PermissionDenied` в `retrieval_service` (`test_channel_id_not_in_allowed_raises`) — не менять на пустой список. Admin на том же id — доступ, как сейчас.

Существующие файлы **расширять, не заменять**:

- [`tests/test_f4_ownership.py`](../../tests/test_f4_ownership.py)
- [`tests/test_f4_coverage_supplement.py`](../../tests/test_f4_coverage_supplement.py) — в том числе `test_exec_list_topics_uses_list_by_channels_for_user`
- [`tests/test_f4b_scoping_read_tools.py`](../../tests/test_f4b_scoping_read_tools.py)
- [`tests/test_f2_parse_only_export.py`](../../tests/test_f2_parse_only_export.py)
- образец red/green: [`tests/test_bug093_add_channel_foreign_source.py`](../../tests/test_bug093_add_channel_foreign_source.py)

Новый файл для матрицы — нормально (как `test_bug093_…` / `test_bug099_…`). Три точечных red/green на F-02 / F-10 / второй путь F-04 могут жить рядом с матрицей; матрица не заменяет их: она ловит **класс**, они — конкретный механизм.

### 3.5 Вне scope

- **Bot-арм BUG-099 / F-01** — `current_user or await get_default_admin()` в 34 исполнителях. Hardening **после** R2. В `_exec_list_topics` эта строка остаётся как была.
- **Любые изменения формы ответа** — R3 / BUG-102 / BUG-098a: проекция topic-хита, `entry_type` в ответе, legacy-ключи `subscriptions`/`interests`, обёртка `list_channels`. Не сглаживать `"No access"` / `"permission"` в `"not found"`.
- **HTTP кроме названного.** Не трогать `process.py` (`list_jobs` / `get_job_status` — PROCESSING), `rag.py`, `documents.py`, `watchlists.py`, `channels.py`. HTTP-близнец резолва `api/auth.py` и TTL кэша — диспозиции R1.
- **Деплой / прод-записи / recreate `tg_parser`.** Smoke после деплоя — по GO, формой BUG-093.
- **R9 / BUG-094** — тот же класс тестового пробела, другая ось (объём записи). Дисциплина тестов отсюда переиспользуется там; чинить `add_channel` здесь нельзя.
- **MCP-ресурсы** (`resource_channel_topics`) — R5 / BUG-103.

---

## 4. Acceptance criteria

1. Красные тесты трёх дефектов зелёные; с откатом соответствующей правки каждый снова красный.
2. Параметризованная матрица «чужой id задан явно» покрывает `channel_id` / `topic_id` / `source_ref` / `job_id` / `interest_id` на MCP + bot; HTTP — `GET /topics?channel_id=` плюс export status + download. Admin-pass и «своё остаётся своим» в наборе есть. Формы `"No access"` / `"permission"` не переписаны под unknown.
3. Default (`.venv/bin/python -m pytest -q`) и **PR standard** (`TEST_POSTGRES=1 .venv/bin/python -m pytest -q`) зелёные. Ожидание порядка — `tests/README.md` (≈4.2k passed на 2026-08-12); точное число — хвост команды, не цифра из памяти.
4. BUG-100 и BUG-101 обновлены: что сделано, какой тест ловит класс, что осталось. Статус — по факту закрытия, не заранее.
5. Bot-арм BUG-099 не тронут: в 34 исполнителях по-прежнему `current_user or await get_default_admin()`.
6. Форма ответов R3 не менялась: ни проекция topic-хита, ни ключи `items`/`subscriptions`/`interests`, ни тип `list_channels`.
7. Диспозиция по источнику истины джобы (`Job.client` vs `owner_user_id`) записана в BUG-101.
8. Прод-smoke **после деплоя и только по GO**: одноразовый `user`-токен, явный чужой `channel_id` на bot `list_topics` → пусто; свой канал → темы; токен отозван. Пока credential'а нет — High остаётся латентным, и это надо сказать, а не имитировать smoke admin-токеном.

---

## 5. Ограничения (CRITICAL)

- Не чинить bot-арм BUG-099 и не «заодно» убирать `get_default_admin` из `_exec_list_topics`.
- Не менять форму ответов (R3). Второй путь F-04 — только «вернуть или нет», не «как выглядит строка». Не унифицировать `"No access"` с `"not found"`.
- Не расширять F-10 на `process.py` (`list_jobs` / processing `job_id`) и не «заодно» чинить весь HTTP.
- Не подтягивать `657f0e7` на прод «чтобы SHA совпали».
- Не пересоздавать `tg_parser` на проде без нужды.
- Не трогать `docs/methodology/**` — папки нет в этом workspace намеренно.
- Не править `pyproject.toml` / `requirements.txt`.
- Прод — только чтения, пока не будет явного GO. Коммит и PR — по явному запросу владельца.
- PR standard обязателен: правки — authz app-code.
- Граф `graphify-out/graph.json` может быть; `.graphifyignore` исключает `docs/notes/` и `tests/`. Этот промпт в графе не появится; код, на который он указывает, — да. Для структуры `list_topics` / `get_export_status` / retrieval — `graphify query` уместен; для точечного чтения файла — Read/Grep.

---

## 6. Финальный ответ сессии

Одним сообщением: что изменилось на какой поверхности (bot + HTTP `list_topics` / MCP+HTTP export / retrieval); что покрывает новая матрица (какие id × какие поверхности); результаты default и PR standard; записанная диспозиция по `Job.client` vs `owner_user_id` — и отдельной строкой, что осталось: bot-арм BUG-099 (hardening после R2) и форма ответов R3. Почему это не сделано здесь.

---

## 7. Ссылки

- [BUG-100](BUG_LOG.md) — пропущенный фильтр на явный `channel_id`; проба bot `total=1` / MCP `total=0`.
- [BUG-101](BUG_LOG.md) — обход проверки ветвью: `get_export_status` + HTTP download + topic-хит без карточки.
- [BUG-093](BUG_LOG.md) — тот же класс; red/green и прод-smoke одноразовым `user`-токеном.
- [BUG-099](BUG_LOG.md) — MCP fail-closed с 2026-08-14; bot-арм открыт.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R2, §4 — scope, очередь, `R2 → R3`.
- [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](CODE_REVIEW_BOT_MCP_2026-08-12.md) — F-02, F-04 (второй путь), F-10; таблица P0.
- [`BUG099_R1_DEPLOY.md`](../runbooks/BUG099_R1_DEPLOY.md) — вход: R1 сделана, MCP fail-closed, следующая — R2.
- [`tests/README.md`](../../tests/README.md) — default / PR standard.
- `tg_parser/bot/tools.py` — `_exec_list_topics` (`2089`, ветка `2103–2105`).
- `tg_parser/mcp_server.py` — `list_topics` (`1370–1376`), `get_export_status` (`3082` / `_user` `3095`).
- `tg_parser/api/routes/topics.py` — HTTP F-02-близнец (`91–96`).
- `tg_parser/api/routes/export.py` — HTTP status (`275`), download (`311`); запись `client=user.name` (`237`).
- `tg_parser/services/retrieval_service.py` — topic-хит (`293–308`).
- `tg_parser/storage/ports.py` — `Job.client`.
- `tests/test_bug093_add_channel_foreign_source.py`, `tests/test_f4_coverage_supplement.py`, `tests/test_f4_ownership.py`, `tests/test_f4b_scoping_read_tools.py`, `tests/test_f2_parse_only_export.py`.
