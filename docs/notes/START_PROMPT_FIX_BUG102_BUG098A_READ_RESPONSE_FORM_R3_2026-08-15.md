# START PROMPT — R3: BUG-102 + BUG-098a, форма ответов read-поверхности

**Дата:** 2026-08-15 · **Сессия:** R3 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R3, §4 · **Баги:** [BUG-102](BUG_LOG.md) (Medium — F-04, F-05) + половина (a) [BUG-098](BUG_LOG.md) (F-07)
**Ветка:** prefix `cursor/fix-bug102-bug098a-read-response-form-r3`

**Goal (одной строкой):** деградировавшее покрытие отличимо от измеренного нуля; topic-хит несёт title/summary/channel_id/`entry_type`; `list_digests` / `list_watchlists` отдают страницу один раз, под `items`; `MCP_AGENT_GUIDE` описывает эту форму.

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: правки только по явному GO; чтения разрешены. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) требует живого Postgres, в облаке его нет. Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. R3 — **не** деплой-сессия. Деплой потом заденет `tg_parser`, `mcp` и `tg_bot` (урок R10: recreate parser сдвигает hourly tick — только после конца тика и по GO). Max local не обязателен (дефект внутри процесса). Bot-арм BUG-099, BUG-098 (b) / R12, R5 — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R3 — форма ответов read-поверхности (BUG-102 + BUG-098a).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG102_BUG098A_READ_RESPONSE_FORM_R3_2026-08-15.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, записи **BUG-102** и **BUG-098** — F-04 / F-05 / F-07, решение владельца про legacy-ключи, почему CI не поймал
> 3. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R3 (scope), §4 (очередь: R4 закрыта, эта — следующая; дальше R5)
> 4. [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) — текущие (устаревшие) формы `search_knowledge_base`, `list_channels`, `list_digests`, `list_watchlists`
> 5. `tests/README.md` — default / PR standard
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1 (хелпер проекции + red topic-хит), §3.2 (снять `subscriptions` / `interests`), §3.3 (флаг coverage + обёртка `list_channels`). Bot-арм BUG-099, performance coverage (R12), окно депрекации legacy-ключей — **вне scope**.
>
> Строки в плане — на `f005f93`. Ниже — перечитанные 2026-08-15 с `origin/main` (`07cd315`, merge `#427`). Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-15 вечер, после деплоя R4):

| Факт | Что ждать на 2026-08-15 |
|---|---|
| Очередь | R4 закрыта (`75c8c07` / `#426`, docs `#427` → `07cd315`, прод-smoke GET `download_url` → 200). Следующая — эта. Дальше **R5**. Параллельно: R12, R6. Bot-арм BUG-099 открыт, не чинить |
| Решение владельца | Legacy-ключи `subscriptions` / `interests` снимаются **одним шагом**, без окна депрекации (2026-08-13). Обёртка `list_channels` по образцу `SearchResults.degraded`. JSON Schema в `docs/contracts/` **не** заводим |
| `main` vs прод | `origin/main` = `07cd315`. Прод: образ `2984f88f4198` на `tg_parser` / `mcp` / `tg_bot` (R4, recreate 10:01 UTC). Scheduler started 10:01:22 UTC → тик ≈ старт + 3600 с, не :00 часа |
| Латентность | Topic-хит на проде наблюдался 2026-08-12 (`summary=null`). Coverage timeout на `list_channels` — 3/3 вызова в той же сессии. Workaround: coverage читать из `get_cross_channel_stats`; topic-хит добирать через `get_topic_details`; из list-ответов читать `items` |
| Не ждать | Пересечения с R12/R6 нет. R2 → R3 снята: проверки R2 уже в проекциях. `get_default_admin()` в исполнителях **не трогать** |

---

## 1. Почему эта сессия существует и почему она сейчас

Три находки — один пробел: у tool-ответов нет описанного контракта (`docs/contracts/` держит доменные артефакты, не ответы инструментов). Поэтому проекция отстала от источника, переходные ключи не имеют даты окончания, а у голого `list[ChannelSummary]` физически негде лежать маркеру деградации.

1. **F-04.** `retrieval.search` отдаёт `SearchResult(entry_type="topic", topic_card=card, document=None)`. Наружу все шесть сериализаторов читают только `document` → строка из `null`. `entry_type` в ответ не попадает. Внутренний `_build_context` читает карточку правильно — ломается только сериализация.
2. **F-05.** `ListDigestsResult` / `ListWatchlistsResult` и bot `_paginate_read_result(legacy_key=…)` кладут одну и ту же страницу под `items` и под `subscriptions` / `interests`. На 24 интересах #1 намерила 44.4 КБ удвоения. Комментарии моделей называют это осознанным — дефект в незакрытом переходе, не в опечатке.
3. **F-07.** `get_all_channel_stats` при timeout coverage подставляет `0.0` и не ставит флаг. `list_channels` MCP возвращает голый список — сайдкару негде лежать. Тот же тип возврата исключил инструмент из TD-D-02. Одна обёртка закрывает оба.

R4 закрыта. R3 ничего не блокирует. Bot-арм — hardening, не гейт. Это **breaking по форме**, поэтому три находки едут одним PR с одной правкой справочника.

---

## 2. Что установлено (не переоткрывать)

1. **Окно депрекации не нужно.** Владелец 2026-08-13: ключи снимаются в R3 одним шагом. Основание — померенный состав потребителей, не оценка. Приложения: **0** читателей (`handlers.py` `_format_paginated_list` берёт `items`). HTTP list уже `{items, total}`. Соседние стеки на хосте (ADR-0021) посторонние. Клиентов с жёстким `subscriptions[0]` нет.
2. **Потребители тестов сдвинулись.** План писал «4 строки в 2 файлах». На `07cd315` — **9 строк в 4 файлах**: [`test_f6_scheduled_digests.py`](../../tests/test_f6_scheduled_digests.py) 1042, 1061, 1197; [`test_f11_bot_tools.py`](../../tests/test_f11_bot_tools.py) 278, 294; [`test_f11_mcp_tools.py`](../../tests/test_f11_mcp_tools.py) 334, 363; [`test_mcp_pagination_contract.py`](../../tests/test_mcp_pagination_contract.py) 249, 258. Все правятся тем же PR. Не искать «ещё одно окно».
3. **Проекция сломана в шести местах, не в одном.** MCP `search_knowledge_base` / `ask_question` ([`mcp_server.py`](../../tg_parser/mcp_server.py) 1236–1246, 1300–1308); HTTP [`rag.py`](../../tg_parser/api/routes/rag.py) 120–128 и 155–163; bot [`_exec_search`](../../tg_parser/bot/tools.py) 2080–2088 и [`_exec_ask_question`](../../tg_parser/bot/tools.py) 2053–2060 (ask на боте ещё и без `text_preview`). HTTP preview режет **200** символов, MCP/bot — **300**. Хелпер принимает `preview_limit`. Не копировать ветку шесть раз.
4. **R2 уже отбрасывает topic-хит без карточки.** Выживший хит всегда имеет `topic_card`. `TopicCard.sources` — `min_length=1` → `sources[0]` безопасен. Проекцию «карточки нет» не изобретать заново.
5. **`legacy_key="channels"` и `"users"` — не F-05.** Снимаем только `subscriptions` / `interests`. Хелпер `_paginate_read_result` и вызовы для `list_channels` / `list_users` остаются.
6. **HTTP `GET /channels` — другой контракт.** [`ChannelListResponse`](../../tg_parser/api/routes/channels.py) — метаданные без coverage, `get_all_channel_stats` не вызывает. Не оборачивать. HTTP `GET /channels/{id}/stats` по-прежнему отдаёт неразмеченный `0.0` — **близнец, вне R3**.
7. **`resource_channels` ждёт голый список.** [`mcp_server.py`](../../tg_parser/mcp_server.py) 4549–4557: `[ch.model_dump() for ch in channels]`. После обёртки — `result.items`. Иначе ресурс падает в рантайме. Вызов `await list_channels()` без аргументов остаётся валидным: `limit=None` = все каналы.
8. **`WorkspaceNotFound` сейчас возвращает `[]`.** [`list_channels`](../../tg_parser/mcp_server.py) 1539–1540. После обёртки это ломает тип. Образец — [`list_topics`](../../tg_parser/mcp_server.py) 1358–1367: пустой конверт (`items=[]`, `total=0`, `has_more=False`), не голый список. [`test_f4b_scoping_read_tools.py`](../../tests/test_f4b_scoping_read_tools.py) 356 сейчас `assert results == []` — переписать на пустой `ChannelListResult`. Неизвестность workspace по-прежнему не палит существование (пустая страница, stats не зовётся).
9. **Реестр пагинации — не один exception-тест.** [`test_mcp_pagination_contract.py`](../../tests/test_mcp_pagination_contract.py) 192–194: `set(_TOOL_FIXTURES) == set(_PAGINATED_READ_TOOLS)`. Параметризованные тесты зовут `fn(offset=0, limit=2)` и ждут `total == 5`. Добавить `list_channels` в реестр без `_setup_list_channels` (5 каналов) и записи в `_TOOL_FIXTURES` — красный контракт, даже если exception-тест перевёрнут. Резать через уже импортированные `paginate_items` + `build_pagination_pending`, третий пагинатор не писать.
10. **Потребители `list_channels` как списка шире `resource_channels`.** [`test_mcp_server.py`](../../tests/test_mcp_server.py) `TestListChannelsTool` (`result[0]`, `result == []`); плюс [`test_f4_ownership.py`](../../tests/test_f4_ownership.py), [`test_f4b_backward_compat.py`](../../tests/test_f4b_backward_compat.py), [`test_f4b_scoping_read_tools.py`](../../tests/test_f4b_scoping_read_tools.py). Все правятся тем же PR.
11. **Тест деградации батча — не там, куда указывает план.** План цитирует `test_channel_service_stats.py::test_batch_stats_degrades_to_zeros_on_aggregation_error`. Этот тест живёт в [`test_mcp_management.py`](../../tests/test_mcp_management.py) (645+ и сосед `…_only_coverage_…`). Плюс [`test_bug066_channel_stats_degradation.py`](../../tests/test_bug066_channel_stats_degradation.py) (`coverage_percent == 0.0`). `test_channel_service_stats.py` — single-channel `get_channel_stats`, не трогать без нужды. Моки, которые сравнивают строку `get_all_channel_stats` как точный dict, должны принять новый ключ `coverage_degraded`.
12. **GUIDE уже врёт двумя слоями.** Поиск: пишет `Returns: list[SearchResultItem]`, с BUG-084 это `{result, degraded}`. `list_digests` / `list_watchlists`: `Parameters: (none)` и только legacy-ключи — MCP уже имеет `offset`/`limit`. Править форму и этот drift одним заходом.
13. **AUDIT §6.2 снят R4.** Docs-половина этой сессии: форма GUIDE + три секции F5-C (`get_topic_versions` 2672, `get_topic_history_diff` 2738, `force_resummarize` 2849) + счётчики README. §6.1 (оговорки F11), §6.3 `ENV_VARIABLES_GUIDE` — не сюда. «43» ещё живёт в `USER_GUIDE`, ADR-0001, `product-overview`, `mcp-management-tools-spec`, compatibility-доках — **не** раздувать docs-половину; PLAN §6 = GUIDE + README.
14. **`count` рядом с `total` на MCP — не F-05.** Не снимать «за компанию», если не мешает.
15. **JSON Schema tool-ответов не заводим.** Контракт сессии = модели + GUIDE.
16. **Хелпер проекции возвращает dict / общий тип в `services/`, не MCP `SearchResultItem`.** HTTP и bot не импортируют `mcp_server` (урок R4 / ADR-0004). MCP и HTTP сами кладут dict в свои модели. Bot ask сейчас без `text_preview` (2053–2060) — хелпер принимает `preview_limit: int | None`; `None` = поле не класть. Не требовать `text_preview` у bot ask.

---

## 3. Scope — строго в этом порядке

Строки ниже — перечитанные 2026-08-15 с `07cd315`.

### 3.1 Red: topic-хит читаем на всех трёх поверхностях

**Сегодня** (все шесть мест):

```
summary = doc.summary if doc else None
text_preview = doc.text_clean[:N] if doc else None
channel_id = doc.channel_id if doc else None
# entry_type и title в модели нет
```

**Нужно:** один хелпер **вне** `api.routes` (например [`tg_parser/services/search_result_projection.py`](../../tg_parser/services/search_result_projection.py)). Возвращает **dict** (или dataclass в `services/`), не MCP `SearchResultItem`. MCP, HTTP и bot импортируют оттуда и сами кладут в свои модели. В `SearchResultItem` (MCP **и** HTTP-копия) добавить `entry_type: str = "message"` и `title: str | None = None`.

- `entry_type=="topic"`: `title` / `summary` из `topic_card`; `text_preview = card.summary[:preview_limit]` если `preview_limit` задан; `channel_id = card.sources[0]`.
- Документ: как сейчас, `entry_type="message"`, `title=None`.
- `preview_limit`: 300 MCP / bot search, 200 HTTP, `None` у bot ask (поле не класть — сейчас его нет).

Тест (новый файл, например `tests/test_bug102_search_topic_projection.py`): topic-хит с карточкой → наружу `entry_type="topic"`, непустые `title`/`summary`/`channel_id` на MCP, HTTP и bot (search **и** ask sources). Red до хелпера. Существующие `test_f5a_*` / `test_f4_coverage_supplement` про внутренний `SearchResult` не заменяют этот тест.

### 3.2 Снять `subscriptions` / `interests`

**Сегодня:** модели [`ListDigestsResult`](../../tg_parser/mcp_server.py) 947–962 / [`ListWatchlistsResult`](../../tg_parser/mcp_server.py) 1052–1067 держат оба ключа; runtime кладёт один `page` дважды (`3505–3513`, `3895–3903`). Bot: `_exec_list_digests` `legacy_key="subscriptions"` (~4265), `_exec_list_watchlists` `legacy_key="interests"` (~4786).

**Нужно:** убрать поля из моделей и присваивания. Bot — вызовы без `legacy_key` (тогда не пишется и `count` — это следствие хелпера, для этих двух инструментов нормально). Пагинационный контракт требует `items`, не legacy.

Попутно `is_active: bool | None = None` на MCP и bot `list_watchlists`. `None` = нынешнее «все, включая inactive». `True` — только активные. `False` — только inactive (фильтр `== value`, не изобретать третье значение). CLI `--active-only` уже есть — не переписывать. HTTP `GET` watchlists — по желанию тем же PR, не обязательно.

Gemini-схема бота: [`TOOL_DECLARATIONS`](../../tg_parser/bot/tools.py) `list_watchlists` сейчас `properties: {}` (1176–1186). Без `is_active` в декларации LLM параметр не передаст — правка модели/исполнителя без схемы недостаточна.

Переписать 9 строк тестов на `items`. Контракт-тесты, которые `assert len(result.subscriptions)` — на `items`.

### 3.3 Флаг coverage + обёртка MCP `list_channels`

**Сегодня** [`get_all_channel_stats`](../../tg_parser/services/channel_service.py) 154–178: `except` → `coverage_counts = {}` → `coverage_percent = 0.0`. MCP `list_channels` 1520–1554 → `list[ChannelSummary]`, `coverage_percent: float`. Не в [`_PAGINATED_READ_TOOLS`](../../tg_parser/mcp_server.py) 58–65. Тест [`test_list_channels_documented_exception`](../../tests/test_mcp_pagination_contract.py) 196–198 это закрепляет.

**Нужно:**

- В `except` coverage выставить флаг. В строке `coverage_percent=None` (не `0.0`). Честный ноль при успешном агрегате остаётся `0.0`. Ключ `coverage_degraded: bool` на **каждой** строке (одно значение на батч) — `list[dict]` у моков не ломается.
- `ChannelSummary.coverage_percent: float | None`.
- MCP: `ChannelListResult { items, degraded, total, offset, limit=None, has_more, pagination_pending }`. `limit=None` = все каналы (как `list_digests`), **не** внезапная страница 20. Резать через `paginate_items` + `build_pagination_pending`. Включить в `_PAGINATED_READ_TOOLS` **и** в `_TOOL_FIXTURES` (`_setup_list_channels` на 5 каналов — контракт ждёт `total == 5`). Перевернуть exception-тест: инструмент **в** реестре.
- `WorkspaceNotFound` → пустой `ChannelListResult`, не `[]`.
- Bot: прокинуть `degraded` в результат `_exec_list_channels`; `legacy_key="channels"` оставить.
- `resource_channels`: итерировать `result.items`. Обновить потребителей-списков в `test_mcp_server.py` / `test_f4_ownership.py` / `test_f4b_*`.

Тесты: деградировавший ответ отличим от здорового нуля (`degraded=True`, `coverage_percent is None`) на MCP и bot; успешный агрегат с нулевым covered → `0.0` и `degraded=False`. Обновить `test_bug066_*` и degrade-тесты в `test_mcp_management.py`.

### 3.4 GUIDE + README

[`MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md):

- `search_knowledge_base`: конверт `{result, degraded}` (BUG-084, уже правда) + поля `entry_type`, `title`.
- `list_channels`: `ChannelListResult`, `coverage_percent` nullable, `degraded`.
- `list_digests` / `list_watchlists`: `items` + пагинация; `Parameters` включают `offset`/`limit`; у watchlists — `is_active`. Убрать `subscriptions` / `interests`.
- Три секции F5-C, которых нет в GUIDE (заголовок файла это признаёт): `get_topic_versions`, `get_topic_history_diff`, `force_resummarize`. Брать сигнатуры из `mcp_server.py`, не выдумывать.

[`README.md`](../../README.md): счётчик MCP-инструментов. AUDIT §6.4 писал «4 места»; на `07cd315` «43» стоит как минимум в 13, 31, 649, 748, 823. Живое число — `rg -c '^@mcp\.tool' tg_parser/mcp_server.py` (сейчас **47**). Не брать 43 из памяти.

BUG-102 / BUG-098a в сессии фикса → `in-progress`; `resolved` только после прод-smoke. Workaround снять когда новая форма жива на проде.

### 3.5 Что не ломать / вне scope

- Bot-арм BUG-099 (`get_default_admin` в исполнителях).
- BUG-098 (b) / R12 — performance `coverage_counts_by_channel`, `EXPLAIN`, индекс, precompute.
- HTTP `GET /channels` и `GET /channels/{id}/stats`.
- `legacy_key="channels"` / `"users"`.
- Окно депрекации, второй ключ «на всякий случай».
- JSON Schema в `docs/contracts/`.
- AUDIT §6.1, §6.3; R5 (F-06/F-08/F-09/F-11); `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Recreate прод-контейнеров в этой сессии.

---

## 4. Acceptance criteria

1. Topic-хит на MCP, HTTP и bot (search и ask sources) несёт `entry_type="topic"`, непустые `title` / `summary` / `channel_id`. Документный хит не деградировал.
2. Шесть сериализаторов зовут один хелпер вне `api.routes`. Хелпер не возвращает MCP-модель; HTTP/bot не импортируют `mcp_server`.
3. `ListDigestsResult` / `ListWatchlistsResult` и bot-ответы этих двух инструментов не содержат `subscriptions` / `interests`. Пагинация по `items` зелёная.
4. `list_watchlists(is_active=True)` не возвращает soft-deleted. `is_active=None` — как сейчас. `is_active=False` — только inactive. Параметр есть в MCP-сигнатуре и в bot `TOOL_DECLARATIONS`.
5. При падении coverage-агрегата: `degraded=True`, `coverage_percent is None`, raw/processed/topics живые. При успехе и нуле covered: `0.0`, `degraded=False`.
6. MCP `list_channels` в `_PAGINATED_READ_TOOLS` **и** в `_TOOL_FIXTURES`; `test_list_channels_documented_exception` перевёрнут; `test_registry_and_fixtures_agree` зелёный. `limit=None` возвращает все каналы. `WorkspaceNotFound` и пустой список — пустой конверт. `resource_channels` не падает.
7. GUIDE описывает новую форму (включая конверт поиска и F5-C). README-счётчик совпадает с `rg`.
8. Default + PR standard зелёные. Red-by-revert по одной ноге на F-04 / F-05 / F-07.
9. R5, R12, bot-арм не начаты. Контейнеры на проде эта сессия не recreate.

---

## 5. Ограничения (CRITICAL)

- Коммит / PR / прод — только по явному запросу / GO.
- Не оставлять `subscriptions` / `interests` «на переход». Не предлагать окно депрекации заново.
- Не класть хелпер проекции в `api.routes` — MCP оттуда не импортирует (урок R4 / ADR-0004). Не возвращать из хелпера MCP `SearchResultItem` и не импортировать `mcp_server` из HTTP/bot.
- Не менять `coverage_percent` на `None` при **успешном** агрегате с нулём covered.
- Не вводить default `limit=20` на MCP `list_channels` — сломает «вернуть все».
- Не оставлять `WorkspaceNotFound` как `return []` после смены типа возврата.
- Не добавлять `list_channels` в `_PAGINATED_READ_TOOLS` без `_setup_list_channels` в `_TOOL_FIXTURES`.
- Не чинить «43» за пределами GUIDE + README.
- Не трогать `get_default_admin()`.
- Не оптимизировать `coverage_counts_by_channel` «раз уж здесь».
- Recreate `tg_parser` на проде — отдельный GO, после конца incremental-тика.
- Ноль правок `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.

---

## 6. Финальный ответ сессии

Одним сообщением: как выглядит `SearchResultItem` и где живёт хелпер; что стало с `subscriptions` / `interests`; как `list_channels` отдаёт `degraded` и nullable coverage; что с `resource_channels`; какие тесты красные→зелёные; прогнан ли PR standard; что записано в GUIDE / README / BUG-102 / BUG-098. Отдельной строкой: деплой не делался — нужен GO на recreate `tg_parser`+`mcp`+`tg_bot` (tick сдвинется). Вне сессии: R5, R12, bot-арм BUG-099.

---

## 7. Ссылки

- [BUG-102](BUG_LOG.md) — F-04 / F-05; решение про legacy-ключи.
- [BUG-098](BUG_LOG.md) — половина (a) форма; (b) = R12.
- [BUG-084](BUG_LOG.md) — образец `SearchResults.degraded`.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R3, §4.
- [`AUDIT_DOCUMENTATION_2026-08-12.md`](AUDIT_DOCUMENTATION_2026-08-12.md) §6.4–6.5 — README counts, F5-C.
- [`BUG096_R4_DEPLOY.md`](../runbooks/BUG096_R4_DEPLOY.md) — предыдущая закрытая сессия.
- `tg_parser/mcp_server.py` — `SearchResultItem` 637, `list_channels` 1520, `ListDigestsResult` 947, `list_watchlists` 3841, `resource_channels` 4549.
- `tg_parser/api/routes/rag.py` — HTTP-копия проекции.
- `tg_parser/bot/tools.py` — `_exec_search`, `_exec_ask_question`, `_exec_list_channels`, `_paginate_read_result`.
- `tg_parser/services/channel_service.py` — `get_all_channel_stats`.
- `tg_parser/services/retrieval_service.py` — `SearchResult`, `_build_context` (правильная внутренняя проекция).
- `tests/test_mcp_pagination_contract.py` (`_TOOL_FIXTURES`, exception-тест), `tests/test_pagination_contract_tdd.py`, `tests/test_bug066_channel_stats_degradation.py`, `tests/test_mcp_management.py`.
- `tests/test_mcp_server.py` (`TestListChannelsTool`), `tests/test_f4_ownership.py`, `tests/test_f4b_scoping_read_tools.py`, `tests/test_f4b_backward_compat.py`.
- `tg_parser/bot/tools.py` `TOOL_DECLARATIONS` — `list_watchlists` (пустые `properties`).
- `tests/README.md` — PR standard.
