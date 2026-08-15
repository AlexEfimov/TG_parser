# AUDIT — документация (Session #2)

**Когда:** 2026-08-12, 15:12–15:37 UTC · **main@:** `a7171ff` · **Эталон:** [`AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md`](AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md)
**Scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) (строка #2) · **План:** [`PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`](PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md)
**Правило:** эталон — матрица #1. `FUTURE_FEATURES` / `ROADMAP_*` / `USER_GUIDE` — предмет проверки, не источник. Каждое число ниже приходит из команды, которая напечатана рядом.

---

## 0. Замер (вывод блока plan §2 как есть)

```
sha=a7171ff
docs files:      438
docs lines:      137614
root files:      13
root lines:      7463
notes total:     310
notes toplevel:  249
notes archive:   53
START_PROMPT top:107
ADR:             21
banner files:    48
SoT mentions:    94
   5905 docs/notes/BUG_LOG.md
   3311 docs/notes/FUTURE_FEATURES.md
   2840 docs/USER_GUIDE.md
  2494 CHANGELOG.md
   1648 docs/notes/START_PROMPT_SPRINT_F5C.md
   1241 docs/archive/DEVELOPMENT_ROADMAP.md
   1207 docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md
   1155 docs/MCP_AGENT_GUIDE.md
  1133 ENV_VARIABLES_GUIDE.md
   1120 docs/notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md
  1062 PRODUCTION_DEPLOYMENT.md
   1015 docs/notes/START_PROMPT_FIX_BUG011_READ_CONTEXT_SESSION_H_2026-05-02.md
   1011 docs/runbooks/F5C_DEPLOY_AND_WATCH.md
    911 docs/plans/DEV_RESURRECTION_PLAN.md
   908 README.md
    881 docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md
    836 docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md
    833 docs/plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md
```

Сверка со снимком `dbadc69` из plan §2: разошлись только `docs lines` 137 479 → 137 614, `root lines` 7 436 → 7 463 и `BUG_LOG` 5 803 → 5 905 (легли BUG-095…098 из PR [#398](https://github.com/AlexEfimov/TG_parser/pull/398)); остальное совпало до единицы.

**Свип битых ссылок** (команда plan §4) на `a7171ff` до правок: **207** — **140** в `archive/**`, **67** в живых документах, **5** root-anchored. Со снимком плана совпал точно.

---

## TL;DR

**Counts (42 строки матрицы):** `agrees` 28 · `contradicts` 5 · `silent` 3 · `stale-status` 0 · `no-reference` 6.

**Вердикт по канону: частично.** Где канон назначен явно — баги, деплой, reverse-proxy-инвариант — он работает. Где не назначали, роль SoT занял документ, который чаще редактировали: статус-карту продукта де-факто держит 3 311-строчный бэклог, а «архитектуру системы» — файл с баннером «Historical / MVP», отсылающий к документу вчетверо короче и про другое.

1. **F11 обещают пять живых документов, доставки нет с 2026-06-15** — `FUTURE_FEATURES:1818`, `ROADMAP_KARPATHY:26` и `:302`, `MCP_AGENT_GUIDE:81`, `README:13`, `USER_GUIDE:762`, и ни один не оговаривается. Одно сломанное плечо продублировано пятикратно.
2. **Стоимости нет ни в одном живом документе — не «наврали», а «нечем врать».** «$4–5/неделя», против которых #1 выставила $33.23 / ≈$16, лежат только в датированных `mcp_testing/2026-05-15…` и в SUPERSEDED prep в `archive/`. Живая стоимостная величина ровно одна — `$215–380` из ADR-0021, и она с прогоном согласна. Риск в том, что #4 пойдёт за единственным сохранившимся — архивным.
3. **Справочник MCP отстал от сервера на три инструмента.** `rg -c '@mcp\.tool' tg_parser/mcp_server.py` → **47**; шапка `MCP_AGENT_GUIDE` заявляла 43, её собственные таблицы перечисляют **44**. Не описаны ровно три F5-C-инструмента, два из которых #1 прогнала успешно. `README` в четырёх местах повторяет «43 tools» и «32 tools» при 47 и 35.
4. **Обратная сторона: F1 работает и нигде не отмечен сделанным** — `prompts/` (10 YAML), настройка `PROMPTS_DIR`, живой `reload_prompts` из тех же 47, и ни одной отметки DONE. Там же F2 помечен DONE в шапке и в теле, но не в сводной таблице.
5. **Дедупликация после LLM описана за месяц до того, как её «нашли»** — `CODE_REVIEW_…FABLE5_2026-07-07:199` (F-01, High), тогда как `USER_GUIDE:467–488` говорит только про экономию embedding. Дефект не в тексте, а в отсутствии пути из ревью-артефакта в канон: находка пролежала в корпусе до BUG-097.

---

## 1. Truth-check (провенанс: #1)

Класс — на строку матрицы. `no-reference` стоит ровно у шести строк, у которых в #1 вердикт `not_run`.

### Навигация / KB

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `list_channels` | «Channel overview: status, counts, coverage»; в схеме ответа `coverage_percent: float` без признака деградации | `MCP_AGENT_GUIDE:34`, `:238` | **contradicts** | добавить в схему маркер деградации (текст следует за фиксом BUG-098, не опережает его) |
| `list_topics` | пагинация, offset/limit | `MCP_AGENT_GUIDE:32` | agrees | — |
| `get_topic_details` | полная карточка с anchors и items | `MCP_AGENT_GUIDE:33`, `:219` | agrees | — |
| `get_document` | документ целиком; `raw_payload` исключён | `MCP_AGENT_GUIDE:35`, `:956` | agrees | — |
| `get_related_topics` | связанные темы по similarity | `MCP_AGENT_GUIDE:42` | agrees | стоп-слова в `shared_keywords` — вход #3, не документный дефект |
| `get_cross_channel_stats` | «Topic counts, coverage, keyword overlaps» | `MCP_AGENT_GUIDE:41` | agrees | какой из двух источников покрытия достоверен, сказано только в `BUG_LOG:177` — этого достаточно |

### Search / RAG

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `search_knowledge_base` (hybrid) | гибрид FTS + pgvector | `MCP_AGENT_GUIDE:25` | agrees | topic-хит с `summary=null` — вход #3 |
| `ask_question` | RAG с цитированием источников | `MCP_AGENT_GUIDE:26` | agrees | — |
| HTTP auth | `api_key` → заголовок `X-API-Key`, per-endpoint колонка auth | `MCP_AGENT_GUIDE:1087`, `:1111+` | agrees | коды `401`/`403` не названы; мелочь, не расхождение |

### Workspaces F4-B

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `list_workspaces` · `create_workspace` · `add_workspace_source` · `list_workspace_sources` · read-tool с `workspace_id` · `rename_workspace` · `remove_workspace_source` · `delete_workspace` · `list_all_workspaces` (9 строк) | § Workspaces (F4-B Core) описывает все девять; `list_workspace_sources` отдаёт `channel_ids` — как и в прогоне | `MCP_AGENT_GUIDE:106–…`, `:884` | agrees ×9 | — |
| неизвестный `workspace_id` | **описание сервера**: «raises a 404-like error»; **docstring'и list/search-инструментов**: «returns an empty …»; **docstring'и get-details**: «treated as 404»; **гайд**: «empty / 404-like result» | `mcp_server.py:314` против `:1174`, `:1313`, `:1590`, `:1637`; `MCP_AGENT_GUIDE:108`, `:1078` | **contradicts** | врёт не гайд (он хеджирует), а описание сервера — единственный текст, который MCP-клиент читает до вызова. Правка кода — вход #3 |

### Digests F6

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `list_digests` | подписки, admin/user-видимость | `MCP_AGENT_GUIDE:74` | agrees | доставка живая, документация ей не противоречит |
| `subscribe_digest` / `unsubscribe_digest` | — | — | **no-reference** | `not_run` в #1 |

### Watchlist F11

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `list_watchlists` | неактивные интересы включены намеренно | `MCP_AGENT_GUIDE:82` | agrees | — |
| `get_watchlist_matches` | сохранённые матчи, `since_iso` | `MCP_AGENT_GUIDE:84` | agrees | — |
| **доставка алертов** | «реализован полным контуром… push-уведомления»; «instant push via aiogram»; «instant notify»; «chat_id receives instant pushes after each scheduler tick»; «F11 topic watchlist alerts»; «сразу же дёргает `notify(matches, bot)`» | `FUTURE_FEATURES:1818`, `ROADMAP_KARPATHY:26` и `:302`, `MCP_AGENT_GUIDE:81`, `README:13`, `USER_GUIDE:762` | **contradicts** | утверждение неверно **с 2026-06-16**; до фикса BUG-095 снабдить все пять оговоркой, а не удалять — F11 действительно доезжает до БД |
| `subscribe_watchlist` / `unsubscribe_watchlist` | — | — | **no-reference** | `not_run` |
| `backfill_watchlist` | — | — | **no-reference** | `not_run` |

### Export F2

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `export_channel` (level=raw) | `✅ DONE`; создание джобы на обеих поверхностях | `FUTURE_FEATURES:311`, `MCP_AGENT_GUIDE:66` | agrees | сводная таблица `FUTURE_FEATURES:21` отметки DONE не несёт — см. §3 |
| `get_export_status` | статус + `download_url` | `MCP_AGENT_GUIDE:67`, `:379–393` | agrees | — |
| **скачивание по объявленному URL** | «poll … until `completed`, then fetch the file via `download_url`»; рецепт «GET `status.download_url` with the same MCP/API credentials» — **без** оговорки о поверхности | `MCP_AGENT_GUIDE:375–377`, `:948` | **contradicts** | дописать: URL рабочий для джобы, созданной по HTTP; для созданной через MCP — 404 до фикса BUG-096 |
| privacy: нет `raw_payload` | «intentionally excluded from all levels» | `MCP_AGENT_GUIDE:956` | agrees | инвариант подтверждён прогоном |

### Topics F5-C

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `get_topic_versions` | audit-trail, ownership через доступ к любому из `topic.sources` | `USER_GUIDE:1015`, `FUTURE_FEATURES:782` | agrees | но в справочнике MCP отсутствует — см. §3 |
| `get_topic_history_diff` | описан **только** в `FUTURE_FEATURES:798` — документе бэклога, который сам предмет проверки; в `MCP_AGENT_GUIDE` и `USER_GUIDE` отсутствует | `FUTURE_FEATURES:798` | **silent** | завести секцию в справочнике MCP |
| `force_resummarize` | `USER_GUIDE:1031` — пример вызова | `USER_GUIDE:1031` | **no-reference** | `not_run`; попутно отсутствует в `MCP_AGENT_GUIDE` |

### Channel ops и pipeline path

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `get_pipeline_status` | «после исчерпания попыток: фиксировать `last_error`… увеличивать `fail_count` и переводить источник в `error`» | `pipeline.md:184` | **contradicts** | на проде `fail_count` считает дедупликации: 81 «отказ» из 85 за 12 ч при нуле настоящих. Документ описывает контракт, которого поведение не держит |
| `trigger_pipeline` / `trigger_topicization` / `trigger_link_topics` | — | — | **no-reference** | `not_run` |
| ingest → process → export | § Deduplication: хэш от нормализованного `text_clean`, дубликат пропускается, «embedding не генерируется» — про уже оплаченный LLM-вызов ни слова | `USER_GUIDE:467–488` | **silent** | факт есть в `CODE_REVIEW_…FABLE5:199` (F-01) с 2026-07-07 и в BUG-097 с 2026-08-12; в пользовательский документ не дошёл |
| инкрементальная топикизация / resummarize | F5-C MVP + P2 описан | `FUTURE_FEATURES:767+`, `ROADMAP_KARPATHY:408` | agrees | — |
| digest hook | F6 `✅ DONE` | `FUTURE_FEATURES:25` | agrees | — |
| watchlist hook (запись матчей) | scoring + `watch_matches` | `MCP_AGENT_GUIDE:85`, `ROADMAP_KARPATHY:302` | agrees | ломается следующее звено, не это |

### LLM config и cost

| возможность | что утверждают docs | где | класс | действие |
|---|---|---|---|---|
| `get_llm_config` | provider/model по стадиям | `MCP_AGENT_GUIDE:91` | agrees | — |
| `set_llm_config` / `reset_llm_config` | — | — | **no-reference** | `not_run` |
| cost snapshot | в живых документах стоимости прогона нет: ни `$/неделя`, ни `$/документ`. `$4–5/неделя` — только `mcp_testing/2026-05-15…` (5 файлов) и `archive/PLANNING_AUDIT_AND_STRATEGY_PREP:88`; `$215–380` из ADR-0021 — согласуется | `rg -n '\$[0-9]' docs *.md --glob '*.md'` | **silent** | §4 придётся считать заново либо цитировать #1; архивный prep как источник не годится |

**Про `stale-status` = 0.** Класс сработал на метаданных документов, а не на возможностях: пять рукописных счётчиков и дат отстали от собственного содержимого (перечень — §3). Разносить это по строкам матрицы было бы подгонкой: счётчик инструментов относится сразу к тридцати. Исправлено в §5.

---

## 1b. Расхождения из `BUG_LOG` (провенанс: BUG_LOG, не #1)

| расхождение | документы | состояние на `a7171ff` | действие |
|---|---|---|---|
| **BUG-090 follow-up** — «два deploy-документа, противоречащих друг другу»: канонический рецепт против рецепта в runbook'е F5-C | `PRODUCTION_DEPLOYMENT.md` § deploy step 4b ↔ [`F5C_DEPLOY_AND_WATCH.md:627`](../runbooks/F5C_DEPLOY_AND_WATCH.md) | **закрыто структурно**: runbook теперь пишет «Канонический источник — `PRODUCTION_DEPLOYMENT.md` § deploy step 4b; здесь только выжимка, при расхождении верить ему» | остаточный дефект — рукописный `Last Updated: April 25, 2026` в самом каноне при содержимом от 2026-06-18 и августа; исправлено (§5) |
| **BUG-091** — инвариант стриминга nginx записан в двух документах и четыре месяца не выполнялся на живом периметре | [`SERVER_ARCHITECTURE.md:80`](../SERVER_ARCHITECTURE.md) (инвариант 3) ↔ `PRODUCTION_DEPLOYMENT.md:611` (рецепт, Option B) | **закрыто правильно**: чинили мир, а не текст; `PRODUCTION_DEPLOYMENT.md:495` теперь явно называет `SERVER_ARCHITECTURE.md` § Reverse proxy единственной спецификацией, а себя — «просто рецептами» | эталон для §2: одна тема — один канон, второй документ с указателем |
| **BUG-092** — обращение с `.env` против compose allow-list | `SERVER_ARCHITECTURE.md:39–54` (§ Configuration channel, новая) ↔ `ENV_VARIABLES_GUIDE.md` (корень, 1 133 строки) | **закрыто наполовину.** Канон записан верно. Но `ENV_VARIABLES_GUIDE` — документ, который оператор открывает, чтобы поменять переменную, — не содержит ни `allow-list`, ни `BUG-092`, ни `BUG-078`, ни ссылки на § Configuration channel: `rg -n 'allow-list\|OS-env\|BUG-092\|BUG-078' ENV_VARIABLES_GUIDE.md` → пусто. Он учит «скопируй шаблон в `.env`» без единственной оговорки, от которой это работает | **главный незакрытый пункт W1-b**; правка длиннее pointer-фикса, вынесена в §6 |
| **prep §1** — счётчики тестов в `tests/README.md` разошлись на ~900 | [`tests/README.md:5`](../../tests/README.md) | **закрыто, и закрыто образцово** (коммит `3eabcc1`, «stop hand-maintaining lists that rot»): «Порядок величины на 2026-08-12: default ≈ 3.7k passed… Точное число: `.venv/bin/python -m pytest -q \| tail -1`». Сверка: `rg -c 'def test_'` по `tests/` → 3646 | это ровно форма из DECISION §3 (величина + дата + команда пересчёта); принята за образец для §4 |

---

## 2. Кто SoT по теме

**Метрика «94» непригодна, и регуляркой не чинится.** Декомпозиция: `rg -il 'SoT scope:'` → **4** (форма-указатель); `rg -il 'этот файл — SoT|— SoT по|is the source of truth|единый источник правды|единственный источник правды'` → **14**. Но и эти 14 не притязания: восемь — отработавшие `START_PROMPT_*` с заявлением на свой спринт, а в `FUTURE_FEATURES:2419` и `ROADMAP_V3:454` «единственный источник правды» сказано про **alembic и схему БД**, а не про сам файл. Поиск не отличает «я канон» от «канон — вон там» и от «канон вообще не документ». Таблица ниже собрана чтением.

| тема | канон | остальные |
|---|---|---|
| Продукт: направление | [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | `ROADMAP_V3` (DEPRECATED, баннер верен), `DEVELOPMENT_ROADMAP*` ×2, `SESSION48_ROADMAP_V2`, `docs/archive/DEVELOPMENT_ROADMAP` |
| Продукт: статусы фич | **вакансия, де-факто занята** [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) (3 311 строк) | документ сам называет себя «Living backlog + shipped-status map»; две роли в одном файле и расходятся между собой (F1, F2) |
| Архитектура: production-топология | [`SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md) (156) | `PRODUCTION_DEPLOYMENT.md` явно с указателем — эталонная связка |
| Архитектура: система целиком | **вакансия** | `architecture.md` (775) с баннером «Historical / MVP» ведёт на `SERVER_ARCHITECTURE` (156) — цель не покрывает ту же площадь; `DATA_ARCHITECTURE` (789), `DATA_FLOW` (655), `pipeline.md` (399) не подчинены никому |
| Технический долг | [`docs/technical-debt-roadmap.md`](../technical-debt-roadmap.md) | подтверждается извне: `BUG-091` ссылается на его § 7 как на живое место |
| Баги | [`BUG_LOG.md`](BUG_LOG.md) | конкурентов нет; проблема не в притязании, а в размере — §4 |
| Деплой | `PRODUCTION_DEPLOYMENT.md` (корень) | `F5C_DEPLOY_AND_WATCH.md` с явным указателем — связка починена в BUG-090 |
| Тесты | [`tests/README.md`](../../tests/README.md) | — |
| Контракты | `docs/adr/` (21) + `docs/contracts/` | нормативны по AGENTS.md; аудит их не трогает |

---

## 3. Диспозиции

Строки мерены `wc -l` на `a7171ff`. Каждая диспозиция — с одной причиной.

### Роадмап-жанр (по имени)

| файл | строк | жанр | диспозиция | причина |
|---|---|---|---|---|
| `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` | 408 | forward roadmap | **canon** | единственный роадмап, который редактируется: § Next open обновлён 2026-08-12 |
| `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` | 508 | forward roadmap | **historical-keep** | DEPRECATED 2026-05-13, баннер ведёт на текущий канон — работает как надо |
| `docs/technical-debt-roadmap.md` | 175 | debt register | **canon** (тема «долг») | живой: § 5 / § 6 / § 7 закрыты 2026-08-10…11. Шапка врала датой — **fix-pointer, §5** |
| `docs/notes/DEVELOPMENT_ROADMAP.md` | 297 | forward roadmap | **fix-pointer → historical-keep** | SUPERSEDED-баннер вёл на `ROADMAP_V3`, который сам DEPRECATED. Цепочка указателей на протухшее — исправлена, §5 |
| `docs/notes/DEVELOPMENT_ROADMAP_SESSION29.md` | 128 | исторический | **historical-keep** | Superseded 2026-05-02, баннер корректен |
| `docs/notes/SESSION48_ROADMAP_V2.md` | 191 | исторический | **historical-keep** | Superseded 2026-05-02, баннер корректен |
| `docs/archive/DEVELOPMENT_ROADMAP.md` | 1 241 | исторический | **archive (уже там), fix-pointer предложением** | баннер ведёт на `/docs/notes/ROADMAP_V3…` — путь root-anchored **и** цель deprecated; в archive не чиню (plan §4) |

### Роадмап-жанр (кандидаты по содержанию)

| файл | строк | жанр | диспозиция | причина |
|---|---|---|---|---|
| `docs/notes/FUTURE_FEATURES.md` | 3 311 | **статус-карта + бэклог** | **split** (предложение, §4) | две роли в одном файле; расходится сама с собой: F2 `✅ DONE` в шапке и теле, но не в сводной таблице; F1 не помечен нигде при живом `prompts/` + `reload_prompts` |
| `docs/notes/implementation-plan.md` | 214 | MVP-план (CLI-only, «без HTTP API») | **archive** (предложение) | описывает границы продукта, которых нет уже год; баннера нет |
| `docs/notes/CROSS_DEV_PLAN.md` | 132 | план фазы | **historical-keep + указатель** | в шапке «Родительский документ: `ROADMAP_V3_PRODUCTION_FIRST.md`» — родитель DEPRECATED; не ссылка, поэтому свип его не видит |
| `docs/plans/DEV_RESURRECTION_PLAN.md` | 911 | infra-план | **historical-keep** | 7 пунктов DONE, 2 PENDING (F6 smoke, DI-хвосты) — не мёртв |
| `docs/session-plan-S1-S3.md` | 145 | план сессий | **archive** (предложение) | без даты и статуса; S1–S3 закрыты |
| `docs/notes/PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` | 309 | operational companion | **historical-keep** | подчинён `PRODUCT_STRATEGY…` явным указателем в шапке |
| `docs/notes/DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md` | 95 | decision-input | **canon (временный)** | вход сессии #5; предшественник помечен SUPERSEDED в собственной шапке |

### Архитектурный жанр (ADR не в счёт)

| файл | строк | описывает | диспозиция | причина |
|---|---|---|---|---|
| `docs/SERVER_ARCHITECTURE.md` | 156 | production-топологию | **canon (свой срез)** | инварианты + команды чтения живой правды; шапка врала датой — fix-pointer, §5 |
| `docs/architecture.md` | 775 | систему целиком (MVP: 3× SQLite, CLI-only) | **historical-keep + перецелить баннер** | баннер отсылает к 156-строчному документу про деплой как к «текущей архитектуре» — цель не покрывает площадь. Куда именно целить, решать не здесь: канона на эту тему нет |
| `docs/DATA_ARCHITECTURE.md` | 789 | данные целиком | **historical-keep** (предложение) | «Версия 1.0, 31 декабря 2025», баннера нет, выглядит живым |
| `docs/DATA_FLOW.md` | 655 | поток данных | **merge-into `pipeline.md`** (предложение) | ни даты, ни баннера, ни указателя на главного; предмет пересекается с `pipeline.md` |
| `docs/pipeline.md` | 399 | контракт пайплайна (TR-*) | **canon (свой срез)** | единственный, кто описывает пайплайн через требования; `:184` расходится с поведением — §1 |
| `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` | 317 | один срез | **historical-keep** | «Утверждён», март 2026; законный срез, нужен указатель на главного |

### Метаданные, разошедшиеся с телом

| файл | было | измерено | диспозиция |
|---|---|---|---|
| `docs/MCP_AGENT_GUIDE.md:3` | «Tools: 43» | 47 в коде, 44 в его же таблицах | **fix-pointer** (§5) |
| `README.md:13`, `:32`, `:649`, `:748–749` | «43 tools», «32 tools» | 47 MCP (`rg -c '@mcp\.tool'`), 35 bot (`TOOL_DECLARATIONS`) | **отложено в §6** — число расходится с кодом, а не с телом README; §6 плана таких правок не разрешает |
| `PRODUCTION_DEPLOYMENT.md` footer | «April 25, 2026» | § step 4b от 2026-06-18, § Reverse proxy от августа | **fix-pointer** (§5) |
| `docs/SERVER_ARCHITECTURE.md:3` | «Updated: June 2026» | § Configuration channel от 2026-08-11 | **fix-pointer** (§5) |
| `docs/technical-debt-roadmap.md` | «Обновлён 2026-03-30» | § 5 / § 6 / § 7 закрыты 2026-08-10…11 | **fix-pointer** (§5) |
| `docs/notes/current-state.md` | имя обещает текущее состояние | «Version 3.1.0, 29 декабря 2025», 4 битые ссылки | **fix-pointer → archive** (предложение) |

### Свип ссылок: живой слой

67 живых попаданий (свип считает уникальные пары «источник → цель») делятся на «неверная база» — цель существует, путь считан не от той точки — **56**, и «цель отсутствует» — **11**. Второе опаснее:

| подкласс | сколько | примеры | что делать |
|---|---|---|---|
| неверная база в живых справочниках | 2 пары (3 вхождения) | `docs/USER_GUIDE.md → ../../ENV_VARIABLES_GUIDE.md` (стр. 169 и 246) и `→ ../../PRODUCTION_DEPLOYMENT.md` (стр. 245) | **исправлено** (§5) |
| неверная база в отработавших `START_PROMPT*` / `PR_BODY_*` / `SESSION*` | 54 | `SESSION_HANDOFF_v1.1 → ../../DEVELOPMENT_ROADMAP.md` | не чинить поштучно — уедет вместе с файлами по правилу §4 |
| цель отсутствует | 9 | `BUG_LOG.md` ×2 → `mcp_testing/2026-05-16_claude_session/{analysis_and_options,tg_parser_pipeline_regression_report}.md`; ADR `0006-karpathy-like-principles.md` / `0007-mcp-scheduler-split.md` (файлы переименованы в `0006-karpathy-like-living-kb-principles.md` / `0007-mcp-scheduler-dispatch.md`) | **BUG_LOG — единственный канон в списке**: каталога `2026-05-16_claude_session` нет, есть только `2026-05-15_claude_session` (и README внутри озаглавлен «Session 2026-05-14»). Артефакты той сессии в репозиторий не попали — перецелить не на что, см. §6 |
| ложные срабатывания | 2 | `AGENT_PLAYBOOK.md → incidents/<file>.md` — плейсхолдер | не трогать |

---

## 4. Политика роста

### `BUG_LOG.md` (5 905 строк) и выдача `BUG-NNN`

Как искать открытые баги, не читая 5 905 строк, — **уже решено, и решено правильно** 2026-08-12: блок «⚠️ Что открыто прямо сейчас» несёт шесть строк (`sed -n '/## ⚠️ Что открыто/,/^Этот блок/p' … | rg -c '^\| \[?\*\*BUG-'` → 6), знаменатель приходит со своей командой (`rg -o 'BUG-[0-9]{3}' … | sort -u | wc -l` → 98), а workflow объявляет блок единственным местом, обновляемым при смене статуса. Тело растёт, вход дешёвый — новой политики не нужно. Добавить остаётся одно: **запись без парной строки в блоке незавершённа**.

**Выдача id — вот где дефект.** #1 предложила 093–096; пока она шла, PR [#392](https://github.com/AlexEfimov/TG_parser/pull/392) и [#396](https://github.com/AlexEfimov/TG_parser/pull/396) заняли 093 и 094, находки уехали на 095…098 (PR [#398](https://github.com/AlexEfimov/TG_parser/pull/398)). Причина — рукописный счётчик без точки выдачи.

> **Правило.** Следующий id выводится **в момент записи** одной командой:
> ```bash
> printf 'BUG-%03d\n' $(( 10#$(rg -o 'BUG-([0-9]{3})' -r '$1' docs/notes/BUG_LOG.md | sort -rn | head -1) + 1 ))
> ```
> На `a7171ff` выдаёт `BUG-099`. Заранее зафиксированное «свободно 095» протухает за часы и резервированием не является: планирующие документы называют находки описательно, номер выдаётся при коммите.
>
> **Префикс `10#` — не украшение.** Первая редакция правила была напечатана без него и падала на `098`: bash читает ведущий ноль как восьмеричную запись. Команда выглядела рабочей ровно до первого запуска — дефект из plan §2, воспроизведённый внутри артефакта, который его ищет.

### `FUTURE_FEATURES.md` (3 311 строк)

**Разделять.** Документ сам заявляет две роли — «Living backlog + shipped-status map» — и они уже разошлись (F1, F2 выше). Статус-карта обязана быть короткой и сверяемой с прогоном, бэклог — длинным и не сверяемым ни с чем; пока они в одном файле, читатель не знает, какую дисциплину применять к строке.

> **Правило до разделения:** статус фичи живёт **только** в сводной таблице; тело секции на статус не претендует и ссылается на таблицу. Один статус — одно место.

### `USER_GUIDE.md` (2 840 строк) — опционально, взято

Делить не нужно, жанр один. Нужно другое: **у документа нет владельца поверхности** — три его расхождения (дедупликация без цены, отсутствие кодов ответа, `../../`-ссылки) держались потому, что его никто не сверяет с прогоном.

> **Правило:** каждая функциональная секция несёт строку «сверено с прогоном: `<дата>`». Несверённая секция — подозреваемый, а не источник.

### Правило для 107 `START_PROMPT*` на верхнем уровне

107 отработавших промптов против 53 файлов в `archive/`: около четверти `docs/notes/` лежит вперемешку с живыми документами и тянет за собой 54 из 56 битых ссылок класса «неверная база».

> **Правило.** `START_PROMPT_*` (и парный `PLAN_*`) переезжают в `docs/notes/archive/` **в том PR, который закрывает их сессию** — последний момент, когда автор ещё знает, закончилась ли работа. Промпт на верхнем уровне означает «сессия не закрыта»; иного значения у расположения нет. Накопленные 107 уезжают одной исполнительной сессией по списку, собранному командой из фактов смерженных PR, а не руками.

---

## 5. Исправлено здесь (7 pointer-фиксов из ≤10)

| # | файл | что было | что стало |
|---|---|---|---|
| 1 | `docs/notes/DEVELOPMENT_ROADMAP.md` | SUPERSEDED-баннер вёл на `ROADMAP_V3`, сам DEPRECATED с 2026-05-13 | ведёт на `ROADMAP_KARPATHY_LIKE_LIVING_KB.md`; промежуточное звено названо явно |
| 2 | `docs/USER_GUIDE.md` (3 ссылки, стр. 169 / 245 / 246) | `../../ENV_VARIABLES_GUIDE.md`, `../../PRODUCTION_DEPLOYMENT.md` — база на уровень выше корня | `../` |
| 3 | `docs/notes/current-state.md` | имя обещает текущее состояние, тело — v3.1.0 от 29 декабря 2025 | баннер SUPERSEDED с тремя рабочими указателями (направление / статусы / топология) |
| 4 | `docs/MCP_AGENT_GUIDE.md:3` | «Tools: 43» при 44 в собственных таблицах и 47 в коде | величина + дата + команда пересчёта; названы три отсутствующих F5-C-инструмента |
| 5 | `docs/technical-debt-roadmap.md` | «Обновлён 2026-03-30» при закрытиях § 5 / § 6 / § 7 от 2026-08-10…11 | дата исправлена + команда сверки вместо ручного счётчика |
| 6 | `PRODUCTION_DEPLOYMENT.md` footer | «Last Updated: April 25, 2026» при § step 4b от 2026-06-18 и § Reverse proxy от августа | команда `git log -1` вместо рукописной даты, с объяснением, что именно протухло |
| 7 | `docs/SERVER_ARCHITECTURE.md:3` | «Updated: June 2026» при § Configuration channel от 2026-08-11 | то же |

Свип после правок (та же команда plan §4): **205** против 207, живой слой **65** против 67, `archive/` без изменений — **140**. Три слота из десяти не израсходованы намеренно: остальные кандидаты требуют решения (куда целить баннер `architecture.md`), а не указателя.

---

## 6. Отложено в исполнительную сессию

1. Оговорки к пяти утверждениям про F11 — до фикса BUG-095; формулировка одна на все пять, но правка содержательная, не pointer.
2. ~~Оговорка к `download_url` в `MCP_AGENT_GUIDE:375–377` и `:948` — до фикса BUG-096.~~ **Снято фиксом R4** (2026-08-15): гайд оставляет утверждение о download как есть; оговорку про 404 не писать. Статус BUG-096 — `resolved` только после прод-деплоя.
3. `ENV_VARIABLES_GUIDE.md` — врезка про compose allow-list со ссылкой на § Configuration channel. **Единственный незакрытый пункт W1-b.**
4. Счётчики инструментов в `README.md` (4 места) — по образцу фикса № 4; §6 плана правку по коду не разрешала.
5. Три секции F5-C в `MCP_AGENT_GUIDE`.
6. Разделение `FUTURE_FEATURES`; попутно F1 → DONE и F2 в сводной таблице.
7. Переезд отработавших `START_PROMPT*` одной миграцией по правилу §4.
8. Битые ссылки `BUG_LOG` ×2 — перецелить не на что; владельцу решать: положить артефакты сессии 2026-05-16 в репозиторий или снять ссылки.
9. Баннер `architecture.md` и судьба пары `DATA_FLOW` / `pipeline.md` — требуют назначения канона на «архитектуру целиком».
10. `docs/archive/DEVELOPMENT_ROADMAP.md` — root-anchored баннер на deprecated цель; в archive эта сессия не правит.

**Вход для #3:** `mcp_server.py:314` обещает `raises`, шесть его же docstring'ов — пустой результат, прогон согласен с docstring'ами. **Для #4:** стоимости в живом корпусе нет, брать из #1, не из `archive/PLANNING_AUDIT_AND_STRATEGY_PREP:88`. **Для #5:** роадмап-жанр сведён (7 по имени + 7 по содержанию), вакансии канона названы в §2.

---

## 7. Не сделано и почему

Бюджет не резался: W1, W1-b, W2 и W3 пройдены. Сознательно не сделано следующее.

- **Живой слой ссылок разобран классами, а не поштучно:** 54 из 67 сидят в отработавших промптах, и поштучный разбор был бы выброшен ближайшим переездом.
- **`docs/notes/mcp_testing/**` и `docs/notes/archive/**` только грепались** (plan §4, Hard OUT); 140 битых ссылок в archive сосчитаны и не тронуты.
- **Отработавшие `START_PROMPT*` и `docs/prompts/**` не читались** — только счёт и правило.
- **Ни одна диспозиция `archive` / `merge-into` / `delete` не исполнена** — по §5 и §6 это предложения.
- **Метрика «94» записана как непригодная, а не интерпретирована:** команда, отделяющая притязание от ссылки, не нашлась, и её отсутствие записано вместо вывода.

**Размер артефакта.** Лимит plan §7 — «≤3 стр. narrative вне таблиц», но страница в словах нигде не определена, поэтому вот измерение вместо оценки. Команда считает слова, выбросив таблицы, заголовки и код-блоки (включая вывод замера §0):

````bash
awk 'BEGIN{inb=0} /^```/{inb=!inb;next} inb{next} /^\|/{next} /^#/{next} {print}' <файл> | wc -w
````

**1436** здесь против **917** у эталона #1. Разница — не запас прозы, а объём мандата: шаблон plan §7 требует 10 секций (`rg -c '^##'` по его блоку) против 6 у #1, и потоков работы четыре против одного.
