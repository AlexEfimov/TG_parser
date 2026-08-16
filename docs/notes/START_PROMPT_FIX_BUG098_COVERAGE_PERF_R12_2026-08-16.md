# START PROMPT — R12: BUG-098 (b), покрытие `list_channels` считается быстро

**Дата:** 2026-08-16 · **Сессия:** R12 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R12, §4 · **Баг:** [BUG-098](BUG_LOG.md), половина (b), Low/Medium
**Ветка:** prefix `cursor/fix-bug098-coverage-perf-r12`
**Self-review:** 2026-08-16 — строки и семантика сверены с `origin/main` (`4010ea7`); правки внесены в этот файл.

**Goal (одной строкой):** `list_channels` снова отдаёт **измеренное** покрытие; маркер `degraded` перестаёт срабатывать на каждом вызове.

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: чтения разрешены, правки — по GO. **R12 — сессия прод-чтения (EXPLAIN), не деплой.** Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) требует живого Postgres, в облаке его нет. Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. Recreate образа `tg_parser` позже сдвинет hourly tick (урок R10) и пересоздаст `mcp` + `tg_bot` (общий образ). R5, R6, bot-арм BUG-099 — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R12 — покрытие `list_channels` считается быстро (BUG-098, половина b).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG098_COVERAGE_PERF_R12_2026-08-16.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-098** — особенно «Proposed fix» (a)/(b), «Root cause (partly verified)» и связь с BUG-066 item (2)
> 3. `docs/notes/BUG_LOG.md`, запись **BUG-066** — хирургический фикс (1) уже `resolved`; отложенный пункт (2) «coverage-query optimization» — это и есть эта сессия
> 4. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R12 (scope), §4 (очередь: R3 задеплоена, R5 в `#430`, эта — параллельный трек)
> 5. `tests/README.md` — default + PR standard обязательны (app-code: service / repo)
>
> Половина (a) сделана в R3 и переоткрытию не подлежит. **Не выбирай лечение, пока нет плана запроса.** Начни с `bash scripts/dev_doctor.sh`, затем §3.1 (объём + `EXPLAIN` на проде). Поднятие `statement_timeout`, перевод `list_channels` на Python-путь `get_cross_channel_stats`, повтор маркера деградации — **вне scope**.
>
> Строки плана (§R12) — на 2026-08-12, в том числе «27 671 документ». Ниже — перечитанные 2026-08-16 с `origin/main` (`4010ea7`, после R3; **не** с ветки R5). Объём **перемерить**, не верить ни одному старому числу. Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-16, после деплоя R3):

| Факт | Что ждать на 2026-08-16 |
|---|---|
| Очередь | R3 задеплоена (`4010ea7` / `#428`, [`BUG102_R3_DEPLOY.md`](../runbooks/BUG102_R3_DEPLOY.md)). R5 в PR `#430` — **не** зависимость. Параллельно ещё R6 (стоп-лист, без симуляции не включать). Bot-арм BUG-099 открыт, не чинить |
| База для ветки | `origin/main` = `4010ea7`. R5 (`#430`) трогает MCP `list_channels` только ради `clamp_page_bounds`; эта сессия в `mcp_server.py` не ходит — ждать мерж незачем |
| Честность (a) уже на проде | MCP и bot `list_channels` → обёртка с `degraded`; при таймауте `coverage_percent=null`, `degraded=true`. raw/processed/topics живые. Это **не** баг этой сессии |
| Где число ещё живое | `get_channel_stats` (один канал, Python-путь) **не** зовёт упавший агрегат. HTTP `GET /channels/{id}/stats` уже отдаёт покрытие. HTTP `GET /channels` покрытия **не** несёт — не смокить его |
| Ложь, которая осталась | batched-покрытие не считается: `coverage_counts_by_channel` бьёт 30s timeout **на каждом** вызове `get_all_channel_stats` (MCP и bot `list_channels`; 3/3 в сессии #1, 2026-08-12). Workaround числа: `get_cross_channel_stats` (другая семантика, §2.6) |
| Объём — устарел | план: 27 671 документ (2026-08-12). R11: 45 757 `processed_documents` (2026-08-13, из них 1 564 с `raw_content_hash`). Оба числа — история. §3.1 пересчитывает |
| Не ждать | пересечения с R5/R6 нет. Жёстких зависимостей после R3 не осталось |

---

## 1. Почему эта сессия существует и почему она сейчас

BUG-066 в июне изолировал таймаут покрытия: остальные статы остались правдой, `coverage_percent` деградировал в `0.0`. Пункт (2) — «оптимизировать запрос» — отложили. К аудиту 2026-08-12 деградация перестала быть исключением: агрегат падал **всегда**. Это и есть BUG-098.

R3 закрыла половину (a): подмена больше не маскируется под измеренный ноль. На проде это уже видно — `degraded=true`, `coverage_percent=null`. Числа по-прежнему нет. R12 закрывает отложенный пункт BUG-066 (2): запрос (или его замена) должен укладываться в 30s, чтобы маркер R3 снова стал исключением, а не нормой.

Поднять `stats_statement_timeout_ms` — не фикс. Это обмен неверного числа на медленную поверхность, которую BUG-008 H2 как раз ограничил.

---

## 2. Что установлено (не переоткрывать)

1. **Семантика покрытия уже записана и её нельзя «улучшить».** Докстринг `coverage_counts_by_channel` ([`processed_document_repo.py`](../../tg_parser/storage/sqlalchemy/processed_document_repo.py) 294–315): документ `(channel_id=C, source_ref=S)` покрыт ⇔ `S` есть в **активном** бандле (`time_from IS NULL AND time_to IS NULL`), у которого либо `C` ∈ `channels_json`, либо `channels_json IS NULL` (channel-agnostic — для каждого канала). Это поведение старого per-channel пути (`list_source_refs_by_channel` + `list_by_channel` + `_compute_coverage`). Любое лечение обязано сохранить эти два правила. Snapshot-бандлы (`time_from`/`time_to` не NULL) не считаются.

2. **Запрос, который падает — один, строки 316–350 того же файла.** CTE `active_bundles` → `bundle_refs` (`jsonb_array_elements` по `items_json::jsonb`) → `named_refs` / `null_refs` → `EXISTS` / `IN` против `processed_documents` + `COUNT(DISTINCT)` + `GROUP BY channel_id`. Leading-wildcard `LIKE` по `channels_json` уже убран (BUG-008 H1). То, что осталось — correlated `EXISTS`/`IN` по развёрнутому jsonb.

3. **Индексов под эту форму нет.** [`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py): у `processed_documents` PK `source_ref`, btree `processed_documents_channel_idx` на `channel_id`, плюс `processed_at` и partial `(channel_id, content_hash)`. У `topic_bundles` — `topic_id`, snapshot `(topic_id, time_from, time_to)`, partial unique current/snapshot. `channels_json` и `items_json` — **Text**, в btree как jsonb их не положить без смены типа или generated column. Не предлагать «просто индекс на `channels_json`».

4. **Таймаут живёт только на stats-сессии.** `stats_statement_timeout_ms` default **30000** ([`settings.py`](../../tg_parser/config/settings.py) 169–181). `SET LOCAL` через `set_config(..., true)` в [`db_context.py`](../../tg_parser/services/db_context.py) `_apply_read_statement_timeout` 55–85, навешивается в `stats_repos` 404–421. На ingestion/topicization не действует (BUG-008 H2). `0` отключает. **Не** поднимать и **не** отключать в приложении.

5. **Честность (a) уже на проде — не переделывать.** [`channel_service.py`](../../tg_parser/services/channel_service.py) `get_all_channel_stats` 154–165: свой `try/except` на покрытие; при ошибке `coverage_counts={}`, `coverage_degraded=True`, в строке `coverage_percent=None` (171–186). Обе поверхности списка зовут **этот** метод: MCP `list_channels` 1527–1595 (`degraded = any(coverage_degraded)` → `ChannelListResult`) и bot `_exec_list_channels` 2331–2354 (`result["degraded"] = …`). Фикс агрегата закрывает обе. В bot-исполнителе стоит `get_default_admin()` — **не трогать** (bot-арм BUG-099). Тесты [`tests/test_bug098a_channel_list_degraded.py`](../../tests/test_bug098a_channel_list_degraded.py) и [`tests/test_bug066_channel_stats_degradation.py`](../../tests/test_bug066_channel_stats_degradation.py) должны остаться зелёными: маркер нужен, когда запрос *действительно* не успеет.

6. **`get_cross_channel_stats` — другой путь и другая семантика, не замена.** [`analytics_service.py`](../../tg_parser/services/analytics_service.py) 109–127. `topic_bundle_repo.list_all` (192–206) **уже** режет snapshot (`time_from IS NULL AND time_to IS NULL`) — это не отличие. Отличие: бандлы отбираются по `card.sources` (строка 119–120 перезаписывает черновик-фильтр по `tg:{cid}:` / `b.channels`), не по `channels_json` / NULL-agnostic правилу; округление до 1 знака, не до 2. Сейчас возвращает 81.6–100 % — поэтому его и назвали workaround. **Не** вести `list_channels` через него: это сломает BUG-008 H1 (batched SQL) и подменит число.

7. **`get_channel_stats` (один канал) — задуманный близнец и живой оракул, не этот баг.** Тот же файл, 35–86: `list_source_refs_by_channel` + `list_by_channel` + `_compute_coverage`. HTTP `GET /channels/{id}/stats` ([`api/routes/channels.py`](../../tg_parser/api/routes/channels.py) 79–92) зовёт его и **сегодня** отдаёт число — агрегат R12 тут не участвует. Тесты [`tests/test_channel_service_stats.py`](../../tests/test_channel_service_stats.py) проверяют **его**, не batched-запрос. Не «закрывать класс», переписывая этот путь.
   Оговорка к сверке: `list_by_channel` ([`topic_bundle_repo.py`](../../tg_parser/storage/sqlalchemy/topic_bundle_repo.py) 172–190) фильтрует `channels_json LIKE '%"{id}"%'`, а SQL — точный `jsonb_array_elements_text`. LIKE может дать ложное включение, если id — подстрока другого. При расхождении после переписи **сначала** проверить этот зазор, а не подгонять `get_channel_stats`.

8. **Почему запрос пересёк 30s — не измерено.** BUG-098 прямо говорит: data growth / plan regression / missing index — все правдоподобны, ни одно не снято. Объём с июня (BUG-066: 17 945 processed) вырос; к 12 и 13 августа числа уже расходятся. Сессия начинается с плана, не с догадки.

---

## 3. Scope — строго в этом порядке

### 3.1 Сначала замер: объём + план запроса

Read-only, `required_permissions: ["all"]`. Хост `prod`. Каждый `docker exec … psql` — **новая** сессия; `SET` ниже живёт только в ней, не в `postgresql.conf` и не в приложении.

**Объём — пересчитать, не цитировать план** (четыре числа; `-c`, не интерактивный psql):

```bash
ssh prod "docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -P pager=off -c \"
SELECT COUNT(*) AS processed_documents FROM processed_documents;
SELECT COUNT(*) AS active_bundles
  FROM topic_bundles WHERE time_from IS NULL AND time_to IS NULL;
SELECT COALESCE(SUM(jsonb_array_length(items_json::jsonb)), 0) AS active_bundle_items
  FROM topic_bundles WHERE time_from IS NULL AND time_to IS NULL;
SELECT COUNT(*) AS snapshot_bundles
  FROM topic_bundles WHERE time_from IS NOT NULL OR time_to IS NOT NULL;
\""
```

Если `jsonb_array_length` падает на кривом `items_json` — это данные, не повод крутить запрос покрытия. Посчитать валидные строки отдельно.

**Ловушка EXPLAIN.** Если гонять запрос через приложение (`list_channels` / `stats_repos`), `SET LOCAL statement_timeout = 30000` отменит и сам запрос, и `EXPLAIN ANALYZE`. Диагностический psql ставит таймаут **только в своём соединении** (`SET`, не `ALTER SYSTEM`):

```sql
SET statement_timeout = 0;
```

Порядок:

1. Сначала `EXPLAIN` **без** `ANALYZE` — оценочный план, без нагрузки.
2. Потом `EXPLAIN (ANALYZE, BUFFERS)` — один раз. Это *исполняет* запрос. Если wall time > 2–3 мин — отменить (`Ctrl-C` в psql) и работать с оценочным планом плюс `EXPLAIN (ANALYZE, BUFFERS)` на урезанном эксперименте (например, один `channel_id`), а не крутить полный прогон повторно.
3. SQL — тот, что в `coverage_counts_by_channel` (строки 317–350). Не «похожий».

Артефакт сессии — сам план (текст) + **четыре** числа объёма + wall time. Без него лечение не выбирать. `WITH` в Postgres не обязан материализоваться — смотреть Actual, не имя CTE.

### 3.2 Выбор лечения — по плану, не заранее

Три формы. Четвёртой (поднять таймаут) нет.

| Форма | Когда выбирать | Чего бояться |
|---|---|---|
| **(1) Индекс** | план показывает seq scan / nested loop, который исчезнет от индекса, который planner **реально возьмёт**. | Text `channels_json` / `items_json` btree не индексирует. `source_ref` уже PK — композит `(channel_id, source_ref)` не выдумывать заранее. Индекс «на всякий случай» без подтверждения планом — не лечение |
| **(2) Перепись запроса** | план = nested loop / seq scan `processed_documents` × развёрнутые items (класс O(bundles × items × docs)). Типичный ход: развернуть бандлы **один** раз, hash-join / join по PK `source_ref`, потом `GROUP BY channel_id`; убрать correlated `EXISTS`+`OR`+`IN` | семантика §2.1 (NULL `channels_json`, только active). Перепись, которая «почти» совпадает с `analytics_service`, — регресс |
| **(3) Предподсчёт** | даже переписанный запрос не держится в 30s на текущем объёме, либо стоимость растёт каждым тиком | новое состояние, drift. Писать во **всех** писателях бандла, не cron'ом того же агрегата: `topicization.py` `upsert` (~723, ~1874), `topicization_service.py` `upsert` / `add_items` (~842, ~2320), `resummarization_service` → `add_items`. Нужны миграция и, если это новая сущность, ADR |

Записать в BUG-098: какая форма, какой узел плана это решил, почему не соседняя. Если (3) — явно сказать, что является источником истины и как ловится drift.

Гипотезы (не выбор): seq scan всех `processed_documents` + nested loop на unindexed CTE; повторный explode jsonb на каждый вызов; `OR` + `IN (null_refs)` мешает индексу; `COUNT(DISTINCT)` на большом множестве. Подтверждает или снимает только план.

### 3.3 Реализация + тесты, которые держат выбранную форму

- Индекс — миграция Alembic + тот же SQL. Поведенческий тест может не понадобиться; план после миграции на прод-объёме — да (после GO на migrate).
- Перепись — тот же метод, те же ключи `{channel_id: covered}`. Новый тест: семантика §2.1 на маленьком фикстурном наборе (active vs snapshot; named channel vs `channels_json IS NULL`; ref чужого канала не надувает).
- Предподсчёт — запись на topicization-пути + чтение в `coverage_counts_by_channel` (или рядом). Тест: смена бандла обновляет число; повторный read без смены бандла не пересчитывает тяжёлое.

Существующие тесты честности (BUG-066 / BUG-098a) и pagination `list_channels` не трогать по смыслу. Если фикс их ломает — это разговор про контракт, не «поправь assert».

`get_channel_stats` не переписывать «за компанию».

### 3.4 Вне scope

- Маркер деградации и обёртка `ChannelListResult` — R3, на проде.
- `stats_statement_timeout_ms` — не поднимать, не отключать.
- Перевод `list_channels` на `analytics_service` / `_compute_coverage` fan-out.
- R5 (`#430`), R6 (стоп-лист), bot-арм BUG-099, HTTP-срезы в `api/routes/`.
- Recreate / деплой — только по GO; это не деплой-сессия.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.

---

## 4. Acceptance criteria

1. Артефакт §3.1 есть: объём (четыре числа), оценочный план, и либо `EXPLAIN (ANALYZE, BUFFERS)`, либо явная запись, почему ANALYZE оборвали.
2. Форма выбрана из трёх, обоснование записано в BUG-098 — каким узлом плана, почему не соседняя.
3. Семантика §2.1 сохранена (тест или сверка с `get_channel_stats` / `GET /channels/{id}/stats` на одном канале — не с `get_cross_channel_stats`). При расхождении сначала §2.7 (LIKE vs jsonb), не правка оракула.
4. Тесты BUG-066 / BUG-098a зелёные: при *настоящем* таймауте по-прежнему `coverage_percent=null` / `degraded=true`.
5. `default` и **PR standard (`TEST_POSTGRES=1`)** зелёные. Max local / compose — только если предподсчёт трогает E2E пайплайна.
6. Deliverable: на объёме, сопоставимом с продом, агрегат укладывается в 30s с запасом (цель — секунды, не 29s). После деплоя (отдельный GO) `list_channels` отдаёт измеренное покрытие, `degraded` не горит на каждом вызове. Маркер R3 остаётся для будущего таймаута.

---

## 5. Замеры: чем мерить до и после

Все read-only до GO. Песочница — `required_permissions: ["all"]`.

Симптом (приложение, 30s guard включён — это и есть баг, не диагностика):

```bash
# в логах mcp / через MCP list_channels:
# QueryCanceledError: canceling statement due to statement timeout
# ChannelListResult.degraded == true, coverage_percent is null
```

Диагностика (psql, `statement_timeout = 0` только в этой сессии) — §3.1.

После фикса, до деплоя: тот же SQL в локальном Postgres с прод-подобным объёмом, если он есть; иначе — честный «на фикстуре N мс, на проде проверим после GO».

После деплоя (GO, не эта сессия): MCP и bot `list_channels` → `degraded=false`, `coverage_percent` число; в логах mcp нет `QueryCanceledError` на этом запросе. Сверить одно число с `GET /channels/{id}/stats` того же канала (§2.7), не с `get_cross_channel_stats` и не с `GET /channels`.

⚠️ Recreate `tg_parser` сдвинет сетку hourly tick (`IntervalTrigger(seconds=3600)`), не cron. Якорь — строка `Background scheduler started`. Общий образ = mcp и bot пересоздаются вместе.

---

## 6. Ограничения (CRITICAL)

- Не выбирать индекс / перепись / предподсчёт до плана §3.1.
- Не поднимать и не отключать `stats_statement_timeout_ms`.
- Не вести `list_channels` через `analytics_service`.
- Не переписывать маркер R3 и не менять смысл тестов BUG-066 / BUG-098a.
- Не ждать мерж R5 и не трогать её файлы.
- Прод — только чтения до явного GO. `SET statement_timeout = 0` — только в диагностическом psql, не в приложении.
- Коммит и PR — по явному запросу владельца.

---

## 7. Финальный ответ сессии

Одним сообщением: четыре числа объёма; какой узел плана был дорогим; какая из трёх форм выбрана и почему не соседние; как сохранена семантика §2.1; результаты default и PR standard; и отдельной строкой — что осталось на деплой (migrate? recreate каких сервисов? какой smoke).

---

## 8. Ссылки

- [BUG-098](BUG_LOG.md) — (a) честность в R3, (b) эта сессия; «Root cause (partly verified)»: план не снят.
- [BUG-066](BUG_LOG.md) — изоляция таймаута `resolved`; item (2) = R12.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R12, §4 — scope и очередь. Scope-пули плана не править; ориентир — этот файл.
- `tg_parser/storage/sqlalchemy/processed_document_repo.py` — `coverage_counts_by_channel` (294–352).
- `tg_parser/services/channel_service.py` — `get_all_channel_stats` (89–190), `_compute_coverage` / `get_channel_stats` (15–86).
- `tg_parser/services/db_context.py` — `_apply_read_statement_timeout` (55–85), `stats_repos` (404–421).
- `tg_parser/config/settings.py` — `stats_statement_timeout_ms` (169–181).
- `tg_parser/mcp_server.py` — `list_channels` (1527–1595), `ChannelListResult` (725–741).
- `tg_parser/bot/tools.py` — `_exec_list_channels` (2331–2354); тот же `get_all_channel_stats`.
- `tg_parser/api/routes/channels.py` — `GET /channels` без покрытия (51–76); `GET /channels/{id}/stats` → `get_channel_stats` (79–92), живой оракул.
- `tg_parser/services/analytics_service.py` (109–127) — workaround, отбор по `card.sources`, не по `channels_json`.
- `tg_parser/storage/sqlalchemy/topic_bundle_repo.py` — `list_by_channel` LIKE (172–190), `list_all` только active (192–206).
- `tg_parser/storage/sqlalchemy/_metadata.py` — `processed_documents` (589–623), `topic_bundles` (755–781).
- Тесты честности: [`tests/test_bug066_channel_stats_degradation.py`](../../tests/test_bug066_channel_stats_degradation.py), [`tests/test_bug098a_channel_list_degraded.py`](../../tests/test_bug098a_channel_list_degraded.py). Single-channel арифметика: [`tests/test_channel_service_stats.py`](../../tests/test_channel_service_stats.py).
- [`BUG102_R3_DEPLOY.md`](../runbooks/BUG102_R3_DEPLOY.md) — (a) уже на проде.
- [`tests/README.md`](../../tests/README.md) — режимы прогона.
