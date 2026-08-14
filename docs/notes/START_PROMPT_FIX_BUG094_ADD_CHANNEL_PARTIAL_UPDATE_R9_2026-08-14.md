# START PROMPT — R9: BUG-094, `add_channel` перестаёт затирать то, чего не просили

**Дата:** 2026-08-14 · **Сессия:** R9 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R9, §4 · **Баг:** [BUG-094](BUG_LOG.md) (Medium — ingestion state)
**Ветка:** prefix `cursor/fix-bug094-add-channel-partial-update-r9`

**Goal (одной строкой):** «изменить одну настройку канала» меняет одну настройку. Курсор и служебные поля `sources` переживают повторный `add_channel`; следующий тик не перечитывает историю канала из Telegram.

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: правки только по явному GO; чтения разрешены. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) требует живого Postgres, в облаке его нет. Первый шаг в любом режиме — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. R9 — **не** деплой-сессия. `tg_parser` на проде не пересоздавать: HTTP `add_channel` нет, правка живёт в MCP и bot. Recreate `tg_parser` сдвигает hourly incremental-pipeline (урок R10).

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R9 — `add_channel` перестаёт затирать курсор ingestion (BUG-094, вариант a).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG094_ADD_CHANNEL_PARTIAL_UPDATE_R9_2026-08-14.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-094** — симптомы, цепочка `last_post_id=NULL` → полный re-fetch, решение владельца (a)
> 3. `docs/notes/BUG_LOG.md`, запись **BUG-093** — образец red/green на том же вызове; ownership уже закрыт, объём записи — нет
> 4. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R9 (scope), §4 (очередь: R2 задеплоена, следующая — эта; дальше R4)
> 5. `tests/README.md` — режимы прогона; **PR standard обязателен** (repo-путь)
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1 (red на курсоре), §3.2 (дефолт ≠ «не передано»), §3.3 (soft-delete lookup). Вариант (b) `update_channel`, bot-арм BUG-099, форма ответов R3 — **вне scope**.
>
> Строки в плане — на `f005f93`. Ниже — перечитанные 2026-08-14 с `main` (`96b01e2`). Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить):

| Факт | Что ждать на 2026-08-14 вечер |
|---|---|
| Очередь | R2 задеплоена (`ca737fc` / `#422`, образ `63de8a1123c5`, все три сервиса). Docs-closeout `#423` → `96b01e2` на `main` и на проде (docs-only pull, recreate не было). Следующая — эта сессия. Дальше R4. Параллельно: R12, R6 |
| Решение владельца | Вариант **(a)** частичный update. **(b)** `add_channel` + `update_channel` — parking-lot Wave 3, [ADR-0009](../adr/0009-idempotency.md) не трогать |
| Латентность | Симптомов на проде не видно: `add_channel` на канал с историей после BUG-093 smoke не вызывали именно из-за этого бага. `medportal_rfed.last_post_id` на момент BUG-093 был `119` |
| `main` vs прод | Оба `96b01e2` (docs). Код на проде — образ R2 `63de8a1123c5`. Это не drift |
| Postgres локально | `dev_doctor` может показать `MISS postgres` — поднять `docker compose up -d postgres` до PR standard. Default suite без него проходит |
| Не ждать | Пересечения файлов с R12/R6 нет. Bot-арм BUG-099 не блокирует: `UserResolutionMiddleware` держит защиту; строку `current_user or await get_default_admin()` в `_exec_add_channel` **не трогать** |

---

## 1. Почему эта сессия существует и почему она сейчас

Это **третий подряд** дефект одного класса тестового пробела:

| Запись | Что пропущено | На какой ветке |
|---|---|---|
| BUG-093 | ownership-check | `add_channel`, канал уже существует |
| BUG-094 | поля, которые write не должен трогать | тот же `add_channel`, существующая строка |
| BUG-100 | RBAC-фильтр | `list_topics`, `channel_id` задан явно |

R2 закрыла третью строку и оставила дисциплину: тест описывает, чего операция делать **не** должна. R9 берёт ту же дисциплину на другую ось — объём записи, не read-RBAC. Проверка другая: сверка живой строки `sources`, не отказ по id.

BUG-093 нарочно не чинил это: «кто может писать» и «что писать» не должны ехать в одном коммите. Ownership уже стоит (`assert_source_mutable`). Объём записи — нет.

На проде единственный путь сменить `include_comments` / `batch_size` — повторный `add_channel`. Он выглядит как settings edit (`created=false`, «updated») и молча обнуляет курсор.

---

## 2. Что установлено (не переоткрывать)

1. **Вариант выбран.** (a) частичный update. (b) снят: ломает принятый ADR-0009 («`add_channel` идемпотентен, UPSERT, reanimates soft-deleted»), меняет поверхность MCP 47→48 / bot 35→36, оставляет без дома оживление. Не предлагать (b) заново.
2. **`upsert_source` честный.** [`ingestion_state_repo.py`](../../tg_parser/storage/sqlalchemy/ingestion_state_repo.py) `112–155`: INSERT перечисляет 20 колонок; `ON CONFLICT DO UPDATE SET` берёт **18** из `excluded` плюс `deleted_at = NULL` (BUG-002 M3). `created_at` в UPDATE **нет** — он переживает даже сегодняшний баг. В BUG-094 «twenty columns from excluded» — это колонки INSERT, не SET. Репозиторий не чинить и не делать «частичный SQL» — его вызывают pause/resume/orchestrator с полной строкой. Чинится **вызывающий**.
3. **Оба писателя собирают восемь полей** и отдают upsert. MCP [`add_channel`](../../tg_parser/mcp_server.py) `1798–1808`; bot [`_exec_add_channel`](../../tg_parser/bot/tools.py) `2868–2880`. Поля: `source_id`, `channel_id`, `channel_username`, `status="active"`, `include_comments`, `batch_size`, `created_at` (с existing), `owner_id` (с existing). Всё остальное в `Source.__init__` — дефолты (`last_post_id=None`, `fail_count=0`, …).
4. **Дефолты инструмента — не «не указано».** MCP: `include_comments: bool = False`, `batch_size: int = 100`. Bot: `args.get("include_comments", False)`, `int(args.get("batch_size", 100))`. Вызов без этих ключей *утверждает* оба значения. Без `None` / сентинела «включи комментарии» сбросит чужой `batch_size=500` на `100`.
5. **Soft-deleted скрыт от lookup — на обеих поверхностях.** `get_source` / `get_source_by_username` по умолчанию `deleted_at IS NULL`. Хелперы **разные копии**, не один импорт: MCP [`_resolve_source`](../../tg_parser/mcp_server.py) `1703–1714` и bot [`_resolve_source`](../../tg_parser/bot/tools.py) `1874–1886`. Оба deleted не видят. Повторный `add_channel` на soft-deleted идёт в ветку **create** (восьмипольный `Source`) и только потом `ON CONFLICT` + `deleted_at=NULL`. Оживление сегодня **тоже** затирает курсор. Lookup обязан видеть deleted-строку (`include_deleted=True` или `find_deleted_source`) **в обоих** хелперах — или в общем, которым оба начнут пользоваться. Иначе тест «reanimate сохраняет курсор» на bot останется зелёным вранья. Побочный эффект сегодняшнего miss: чужой `add_channel` на soft-deleted идёт как create и через `ON CONFLICT` может переписать `owner_id` — `assert_source_mutable` не вызывается, потому что `existing is None`. Lookup+guard закрывает и это.
6. **HTTP `add_channel` нет.** Третьей поверхности нет. CLI [`add_source_cmd.py`](../../tg_parser/cli/add_source_cmd.py) `63–75` — та же форма (восьмипольный `Source` + upsert). Как в BUG-093, CLI operator-local. Если из MCP+bot вынимается общий хелпер — подключить CLI в том же PR дёшево. Не переписывать флаги CLI. Не подключать — записать близнецом в BUG-094, как HTTP-резолв в BUG-099.
7. **`status="active"` на update — намеренно.** Повторный `add_channel` реактивирует. Оставить. `deleted_at=NULL` в SQL upsert — единственный намеренный сброс (BUG-002 M3). Не убирать.
8. **BUG-093 тесты живы** и должны остаться зелёными: чужой existing → отказ, `upsert` не вызван; свой / admin — update проходит. [`tests/test_bug093_add_channel_foreign_source.py`](../../tests/test_bug093_add_channel_foreign_source.py) не заменять. `test_own_existing_source_still_updatable` проверяет `include_comments` и `owner_id`, не курсор — дополнить новым файлом, не этим.
9. **Прод-smoke этого класса надо делать read-only**, пока фикс не на проде. BUG-093 нарочно не вызывал owner-`add_channel` на `medportal_rfed`: именно этот баг стер бы `last_post_id`. После деплоя и только по GO — снимок строки → owner `add_channel` без лишних полей → сверка (кроме `updated_at`).

---

## 3. Scope — строго в этом порядке

Строки ниже — перечитанные 2026-08-14 с `96b01e2`.

### 3.1 Red: существующий source с курсором → `add_channel` → курсор жив

**Сегодня** (MCP `1798–1808`, bot `2868–2880` — одна форма):

```
source = Source(
    source_id=normalized,
    channel_id=normalized,
    channel_username=channel_username,
    status="active",
    include_comments=include_comments,
    batch_size=batch_size,
    created_at=existing.created_at if existing else None,
    owner_id=existing.owner_id if existing else user.id,
)
await state_repo.upsert_source(source)
```

На существующей строке с `last_post_id="119"`, `backfill_completed_at=…`, `fail_count=3`, `channel_username="foo"` upsert пишет `NULL` / `0` во все непереданные колонки.

**Фикс:** при `existing is not None` начать с загруженной строки и наложить **только** переданные поля, затем тот же `upsert_source`. Репозиторий не менять.

Поля, которые **нельзя** затирать (минимум из записи и плана):

`last_post_id`, `backfill_completed_at`, `last_attempt_at`, `last_success_at`, `fail_count`, `last_error`, `rate_limit_until`, `comments_unavailable`, `history_from`, `history_to`, `poll_interval_seconds`, `channel_username` (если не передали), `owner_id`, `created_at`.

Намеренно менять: `status="active"`; `deleted_at=NULL` (уже в SQL); `updated_at`; overlay `include_comments` / `batch_size` / `channel_username` **если переданы**.

Предпочтительная форма — один хелпер на MCP и bot (например рядом с `Source` или в маленьком модуле ingestion), чтобы две поверхности не разъехались. Не раздувать `channel_service`.

**Red до правки.** Owner (или admin) вызывает `add_channel` на existing с курсором, передаёт одно поле (`include_comments=True`) или ничего сверх дефолтов. `upsert_source` получает объект, у которого `last_post_id is None`. С откатом фикса тот же тест снова красный. Образец стиля: [`tests/test_bug093_add_channel_foreign_source.py`](../../tests/test_bug093_add_channel_foreign_source.py).

Существующие `test_add_channel_sets_owner_id` / `test_exec_add_channel_sets_owner_id` / `test_own_existing_source_still_updatable` **дополнить не ими** — они про create / ownership / одно выставленное поле. Новый файл `tests/test_bug094_add_channel_preserves_cursor.py` — нормально.

### 3.2 Дефолт ≠ «не передано»

Без этого фикс неполон: `include_comments=False` и `batch_size=100` — дефолты схемы инструмента.

| Вызов на existing (`batch_size=500`, `include_comments=True`) | Ожидание |
|---|---|
| MCP `add_channel("ch")` — оба аргумента опущены | `batch_size` остаётся 500, `include_comments` остаётся True |
| MCP `add_channel("ch", include_comments=True)` | comments=True (уже было), `batch_size` остаётся 500 |
| MCP `add_channel("ch", batch_size=100)` | `batch_size` становится **100** (передано явно), comments не трогать |
| MCP `add_channel("ch", include_comments=False)` | comments становится **False** (передано явно), `batch_size` не трогать |
| Create (`existing is None`), аргументы опущены | как сегодня: `include_comments=False`, `batch_size=100` |

Как отличить: `include_comments: bool \| None = None`, `batch_size: int \| None = None` на MCP; в bot — `args.get("include_comments")` / `args.get("batch_size")` **без** дефолта, `None` = не передано. Create-ветка подставляет False/100 сама.

Это меняет JSON-схему MCP (поля становятся nullable). Опущенное поле по-прежнему валидно. Не добавлять новый tool и не переименовывать.

**Ловушка клиента:** in-process `add_channel("ch")` опускает kwargs. Живой MCP-клиент может **прислать** schema-default `false`/`100`, и сервер увидит «передано явно». Тест §3.2 обязан имитировать оба: вызов без ключа в args **и** вызов с явным `batch_size=100`. Если окажется, что FastMCP подставляет дефолт до входа в функцию — сказать вслух и выбрать сентинел / raw-args, не делать вид, что `None` на сигнатуре достаточно.

**Bot preview** (`_exec_add_channel` `2844–2859`, `confirm=false`): сегодня в `settings` всегда лежат уже подставленные False/100. На update preview должен показывать **текущие** значения плюс overlay, не дефолты инструмента. Иначе оператор подтвердит ложный сброс. Create-preview может по-прежнему показывать будущие дефолты.

В `_exec_add_channel` на `2784` стоит `user = current_user or await get_default_admin()`. Это bot-арм BUG-099. Строку видеть и **не трогать**.

### 3.3 Soft-delete lookup — иначе reanimate всё ещё BUG-094

`_resolve_source` не видит `deleted_at IS NOT NULL`. Повторный `add_channel` на удалённый канал = create из восьми полей + `ON CONFLICT` + `deleted_at=NULL`. Курсор умирает в момент «оживления».

**Обязательно:** искать и soft-deleted (`get_source(..., include_deleted=True)` и то же для username, либо `find_deleted_source` после miss) в **MCP и bot** `_resolve_source` (это два файла, §2.5). Нашли — это `existing`, не create: overlay, `assert_source_mutable`, без `check_channel_limit` (это не новый канал). Сегодня reanimate идёт как create и **попадает** в лимит; после фикса — нет. Принять и записать в BUG-094, не оставлять «как create, чтобы лимит жил». `created=False` честнее, чем сегодняшний `True` на reanimate — тоже записать, не прятать.

Третий тест из плана §R9 («`add_channel` на soft-deleted по-прежнему оживляет») **сегодня уже зелёный**: SQL `deleted_at=NULL` работает. Его недостаточно. Нужен тест «оживает **и** курсор жив» на MCP **и** bot. Существующий [`tests/test_ingestion_state_repo_soft_delete.py`](../../tests/test_ingestion_state_repo_soft_delete.py) проверяет репозиторий, не вызывающего. Не заменять его — он про M3 SQL.

Не убирать `deleted_at = NULL` из `upsert_source`.

### 3.4 Что не ломать

- BUG-093: чужой existing → `"No access to channel …"`, upsert не вызван; preview чужого не показывает `current_status`.
- Create: новый канал, лимит, placeholder-guard (BUG-002), `validate_channel_username` на bot (BUG-034), `owner_id=user.id`, audit `ACTION_CHANNEL_ADD`.
- pause / resume / orchestrator — они передают полную загруженную строку в тот же upsert. Не менять SQL.
- ADR-0009: `add_channel` остаётся идемпотентным UPSERT и по-прежнему оживляет soft-deleted.

### 3.5 Вне scope

- **Вариант (b)** — новый tool `update_channel`, правка ADR-0009, `prompts/bot.yaml`, `MCP_AGENT_GUIDE`. Parking-lot Wave 3.
- **Bot-арм BUG-099** — `get_default_admin()` в `_exec_add_channel` и в остальных 33 исполнителях.
- **Форма ответов R3** / ключи `items`/`subscriptions`. Сообщение «updated» / `created=false` не переписывать ради красоты (кроме честного `created=False` на reanimate, §3.3).
- **`upsert_source` → частичный SQL.** Сломает pause/resume/scheduler.
- **HTTP** — `add_channel` там нет. Не искать «близнеца» в `channels.py`.
- **Деплой / прод-записи / recreate `tg_parser`.** После деплоя recreate только `mcp` и `tg_bot`. Smoke — по GO, сначала read-only снимок, потом owner-вызов.
- **R4 / BUG-096** — следующая сессия, экспорт. Не начинать.
- **`docs/methodology/**`** — папки нет в этом workspace.

---

## 4. Acceptance criteria

1. Красные тесты §3.1–3.3 зелёные; с откатом overlay-хелпера (или эквивалента) снова красные.
2. Три формы, которых в наборе не было:
   - existing с курсором → `add_channel` с одним полем → курсор и служебные поля байт-в-байт (кроме `updated_at` / намеренного `status`);
   - явный `batch_size=100` на existing с 500 ставит 100; опущенный `batch_size` 500 не трогает;
   - soft-deleted с курсором оживает (`deleted_at is None`, `status=active`) и курсор жив.
3. Create-путь без регресса: опущенные аргументы → `include_comments=False`, `batch_size=100`. BUG-093 зелёный.
4. Default (`.venv/bin/python -m pytest -q`) и **PR standard** (`TEST_POSTGRES=1 .venv/bin/python -m pytest -q`) зелёные. Ожидание порядка — `tests/README.md`; точное число — хвост команды.
5. BUG-094 обновлён: что сделано, какой тест ловит класс, CLI-близнец (починен хелпером или записан). Статус `resolved` — после merge, не заранее.
6. `upsert_source` SQL и ADR-0009 не менялись. `get_default_admin` в bot не тронут.
7. Прод-проверка **после деплоя и только по GO**, read-only сначала. Живой owner-`add_channel` — только со снимком строки до/после.

---

## 5. Ограничения (CRITICAL)

- Не предлагать и не делать `update_channel`.
- Не менять `ON CONFLICT` в `upsert_source` на частичный UPDATE.
- Не убирать `deleted_at = NULL` из upsert (BUG-002 M3).
- Не подставлять False/100 на update, если вызывающий их не передал.
- Не чинить bot-арм BUG-099 «заодно».
- Не пересоздавать `tg_parser` на проде. Эта правка его не касается.
- Не трогать `docs/methodology/**`.
- Не править `pyproject.toml` / `requirements.txt`.
- Прод — только чтения, пока не будет явного GO. Коммит и PR — по явному запросу владельца.
- PR standard обязателен: правки — ingestion app-code / repos.
- Граф `graphify-out/graph.json` может быть; `.graphifyignore` исключает `docs/notes/` и `tests/`. Для структуры `add_channel` → `upsert_source` — `graphify path` уместен; для точечного чтения — Read/Grep.

---

## 6. Финальный ответ сессии

Одним сообщением: как overlay устроен (хелпер или нет); как отличили «не передано» от False/100; видит ли lookup soft-deleted; что покрывают новые тесты (курсор / явная сотня / reanimate); результаты default и PR standard; CLI — починен или записан близнецом — и отдельной строкой, что осталось: bot-арм BUG-099 и R4 (BUG-096). Почему это не сделано здесь.

---

## 7. Ссылки

- [BUG-094](BUG_LOG.md) — частичный `Source` × full-row upsert; решение (a) 2026-08-13.
- [BUG-093](BUG_LOG.md) — ownership на той же ветке, resolved; образец red/green.
- [BUG-002](BUG_LOG.md) M3 — намеренный `deleted_at=NULL` при upsert.
- [ADR-0009](../adr/0009-idempotency.md) — `add_channel` идемпотентен, reanimates soft-deleted.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R9, §4.
- [`BUG100_R2_DEPLOY.md`](../runbooks/BUG100_R2_DEPLOY.md) — вход: R2 сделана, следующая — R9.
- [`TEST_ACCESS_MULTI_USER.md`](../runbooks/TEST_ACCESS_MULTI_USER.md) §6 — workaround для операторов (не менять настройки через `add_channel`).
- [`tests/README.md`](../../tests/README.md) — default / PR standard.
- `tg_parser/mcp_server.py` — `_resolve_source` (`1703–1714`), `add_channel` (`1718`, сборка `1798–1808`).
- `tg_parser/bot/tools.py` — свой `_resolve_source` (`1874–1886`), `_exec_add_channel` (`2766`, дефолты `2796–2797`, preview `2844`, сборка `2868–2880`).
- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` — `upsert_source` (`112–155`), `get_source(include_deleted=…)`.
- `tg_parser/storage/ports.py` — `Source`.
- `tg_parser/cli/add_source_cmd.py` — близнец (`63–75`).
- `tests/test_bug093_add_channel_foreign_source.py`, `tests/test_f4_ownership.py`, `tests/test_ingestion_state_repo_soft_delete.py`.
