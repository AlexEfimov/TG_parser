# START PROMPT — R14: удалённый канал невидим везде + чистка `murashko_med` (BUG-107)

**Дата:** 2026-09-25 · **Сессия:** R14 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](../PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §4a · **Баг:** [BUG-107](../BUG_LOG.md); побочно DF-5 из [`FUTURE_FEATURES.md`](../FUTURE_FEATURES.md)
**Ветка:** новая от `main`, например `cursor/fix-bug107-soft-delete-invisible`.

**Goal (одной строкой):** soft-deleted канал перестаёт влиять на что-либо, кроме пути восстановления. Его нет в поиске, RAG, навигации, аналитике, линковке, каталоге Phase 2 и счётчиках владения, в том числе для admin. Данные `murashko_med` вычищены с прода в объёме, который выберет владелец.

> **Семантика утверждена владельцем 2026-09-23 и не пересматривается** ([`PLAN_POST_FORCED_DP_2026-09-23.md`](../PLAN_POST_FORCED_DP_2026-09-23.md) §3, решение 2): удалённый канал невидим **везде, включая admin, кроме пути восстановления**.
>
> Путь восстановления — повторный `add_channel`: upsert сбрасывает `deleted_at` в NULL.
>
> Прод трогать только через `ssh prod` с `required_permissions: ["all"]`. До GO — только чтение. Деплой и чистка данных — по явному GO владельца, коммит — по его запросу.
>
> R16 / R18 / O1 / R17 здесь не начинать. R15 (DF-4, нормализация `t.me`) идёт параллельно и может уехать этим же деплоем.

---

## 0. Opener (вставить в новый чат)

> Стартую R14 — удалённый канал невидим везде (BUG-107) + чистка `murashko_med`.
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_R14_SOFT_DELETE_INVISIBLE_2026-09-25.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md` — запись **BUG-107**; у BUG-108 строки Status и «(a) — что сделано» (там базовая линия Phase 2 — ей измеряется эффект чистки)
> 3. `docs/notes/PLAN_POST_FORCED_DP_2026-09-23.md` §1 (замер удалённых каналов) и §3 (решение 2; открытое решение 2 — объём чистки, закрыто 2026-09-25: полное удаление)
> 4. `docs/runbooks/BUG108A_R13_DEPLOY.md` §3 и §5 — как сверять расход Phase 2 и как попасть в Grafana
> 5. `tests/README.md` — режимы; обязательный для app-code — PR standard (`TEST_POSTGRES=1`)
>
> Начни с `bash scripts/dev_doctor.sh`, сверь `main` с продом, затем read-only снимок из §1. Если код или прод уже не такие, как в таблице, — скажи вслух, не чини исчезнувшее.

---

## 1. Состояние на входе (сверить, а не поверить; снято 2026-09-25 с `main` = `71181e0`, прод — `54350bc`, образ `a6977308e61d`)

| Факт | Где |
|---|---|
| `get_owned_channel_ids` — `SELECT channel_id FROM sources WHERE owner_id = :user_id` **без** `deleted_at IS NULL`. На `main` 12 вызовов в `tg_parser/` (в BUG-107 записано 15 — сверить, откуда разница): `auth/resolvers.py` (→ `allowed_channel_ids`), `mcp_server.py` ×3, `bot/tools.py` ×2, `api/routes/users.py` ×4, `cli/workspace_cmd.py`, `cli/watchlist_cmd.py` | `tg_parser/storage/sqlalchemy/user_repo.py:69`; `rg -n 'get_owned_channel_ids\(' tg_parser` |
| Для admin `allowed_channel_ids = None` («всё») → поиск и RAG идут **без** фильтра по каналам (`effective_channel_ids = None`), удалённые каналы в выдаче. Scope кэшируется на `_CACHE_TTL = 60` с | `auth/resolvers.py`; `services/retrieval_service.py` (~141–154, фильтр карточек ~299) |
| `assert_channel_access(user, channel_id)` — для admin (`allowed_channel_ids is None`) **всегда пропускает**. 18 вызовов: `api/routes` (`channels`, `export`, `pipeline`, `process`), `bot/tools.py` ×7, `mcp_server.py` ×7. Сюда входит `export_channel`: admin выгружает raw / processed / topic-данные soft-deleted канала через `export_service`. Рядом стоит `assert_topic_access` с той же логикой для admin | `tg_parser/auth/ownership.py:39`; `rg -n -e 'assert_channel_access\(' -e 'assert_topic_access\(' tg_parser` |
| `topic_card_repo.list_all()` — `SELECT … FROM topic_cards` без условий; **7** вызовов: `_load_cross_channel_topics` и инкрементальная линковка (`topicization_service.py` ~2382 / ~2453), `topic_linking_service.link_topics` (~148), `analytics_service` (~106), `list_topics` в MCP (~1395), боте (~2167), API (`routes/topics.py` ~99) | `rg -n 'topic_card_repo\.list_all\(' tg_parser` |
| Soft-delete = только `sources.deleted_at` (+ частичный индекс `idx_sources_active`). `topic_cards`, `topic_bundles`, `document_embeddings`, `processed_documents`, `raw_messages` с ним не связаны. Фильтр стоит в отдельных запросах: `ingestion_state_repo` (`include_deleted`), `workspace_repo` | `rg -n 'deleted_at' tg_parser --glob '*.py'` |
| Три engine / sessionmaker — `ingestion` (`sources`), `raw`, `processing` (`topic_cards`, `processed_documents`, эмбеддинги) — смотрят в **одну** базу: все три строятся из одной и той же `settings.db_name`, различаются только пулы. SQL-join с `sources` из processing-сессии возможен (`workspace_repo` уже фильтрует `s.deleted_at IS NULL` в join). Выбор между (A) и (B) в §2 — вопрос единообразия и числа мест, а не доступности | `storage/engine_factory.py` `create_engine_from_settings`; `storage/sqlalchemy/database.py` `init()` |
| Эмбеддинги несут собственный `channel_ids` (миграция `20260416_add_embedding_channel_ids`), `sources_json` у карточек — **`TEXT`**, не `jsonb`: в SQL нужен `sources_json::jsonb`, как в `topic_card_repo` (`jsonb_array_elements_text(tc.sources_json::jsonb)`) | `_metadata.py` (`Column("sources_json", Text())`); `topic_card_repo.py:186` |
| Повторный `add_channel` существующей строки (в том числе soft-deleted) — это «update»: `check_channel_limit` вызывается **только при `existing is None`**. Восстановление удалённого канала обходит `max_channels`; после R14, когда удалённые перестанут считаться, круг «удалить → добавить новый → восстановить старый» даст больше каналов, чем лимит | `bot/tools.py` ~2866–2890 (MCP — паритет по BUG-093) |
| ⚠️ **`topic_links` без внешнего ключа** на `topic_cards` (только `PRIMARY KEY (topic_id_a, topic_id_b)`), в `topic_link_repo` нет удаления по теме — только `delete_all()`. Утверждение BUG-107 «связи удаляются вместе с карточками, relink не нужен» по коду **неверно**: 904 связи `murashko_med` переживут удаление карточек. Проверить на проде `\d topic_links` — вдруг там есть FK вне миграций | `migrations/versions/processing/20260419_bootstrap_topic_links_and_bundle_uniques.py`; `topic_link_repo.py` |
| ⚠️ `topic_card_repo.delete_by_channel` удаляет по `sources_json LIKE '%"<канал>"%'` и **сам делает commit** — под шаблон попадёт любая карточка, в источниках которой упомянут канал, а транзакцию с остальной чисткой не объединить. `topic_card_versions` удаляются каскадом (FK `ON DELETE CASCADE`) | `topic_card_repo.py:214`; `migrations/…/20260426_add_topic_card_versions.py` |
| `delete_by_channel` есть и у `processed_document_repo`, `raw_message_repo`, `embedding_repo`, `topic_bundle_repo`, `processing_failure_repo`, `job_repo`, `task_history_repo` — кандидаты для чистки, а не готовая процедура | `rg -n 'async def delete_by_channel' tg_parser` |
| Прод 2026-09-23: 7 soft-deleted строк `sources`, данные только у `murashko_med` — **850** карточек, **904** из 5 516 связей, **18 056** processed, **33 248** raw, **17 630** эмбеддингов; остальные шесть — пустые фантомы (`t.me/…` — зона R15) | `PLAN_POST_FORCED_DP_2026-09-23.md` §1 |
| Базовая линия Phase 2 «до R14» (2026-09-24, `mediamedics`): `own_topics=260 cross_channel_topics=2042 prompt_chars=757515`, **290 961** input-токенов Sonnet за вызов; `murashko_med` — ≈ 25 % символов каталога | BUG-108 Status; runbook R13 §3 |

---

## 2. Scope

**Входит:**

1. **Единое определение «живого канала»** вместо фильтра, который каждый новый потребитель забывает. Выбор формы — в сессии, варианты:
   - **(A)** хелпер «активные channel_id» из `sources WHERE deleted_at IS NULL`; admin получает явный список активных каналов вместо `None`, и всё, что фильтрует по `allowed_channel_ids`, начинает работать само;
   - **(B)** предикат в SQL каждого запроса.

   Учесть кэш scope на 60 с и цену (A) на каждом запросе admin: список всех активных каналов вместо `None`.
2. **`get_owned_channel_ids`** — `deleted_at IS NULL`. Отсюда чинятся `allowed_channel_ids`, `whoami` / `list_users` (DF-5: «3 из 3» при одном живом канале) и лимит `max_channels`.
3. **Потребители `list_all()` карточек** получают только карточки живых каналов:
   - каталог Phase 2;
   - обе линковки;
   - аналитика;
   - `list_topics` в MCP, боте и API.

   Нужен новый метод или параметр — **не** менять семантику `list_all` вслепую: у неё есть потребители, которым нужно всё (миграции, чистка).
4. **Поиск и RAG** (`search_knowledge_base`, `ask_question`, `get_document`, `get_topic_details`, `get_related_topics`, `get_cross_channel_stats`) не показывают удалённые каналы никому, в том числе admin.
   **Проверки доступа по каналу** (`assert_channel_access` / `assert_topic_access`, §1) отказывают по удалённому каналу всем, в том числе admin. Это закрывает `export_channel`, запуск пайплайна и обработки, статистику канала — всё, что приходит с явным `channel_id`. Единственное пользовательское исключение — путь восстановления (`add_channel`, который уже ищет строку с `include_deleted=True`). Повторный `remove_channel` удалённого канала остаётся «не найдено», как сейчас в MCP (`_resolve_source` без `include_deleted`). Операторская чистка на деплое идёт SQL-ом, а не через пользовательские инструменты, и исключения не требует.
5. **Подписки с `channel_ids`** — дайджесты (`digest_service` фильтра по `deleted_at` не имеет) и watchlist, включая `backfill_watchlist`, который сканирует уже накопленные документы. Сверить, что удалённый канал не попадает ни в тело дайджеста, ни в матчи. Workspaces уже фильтруют (`workspace_repo`) — пин тестом, не правка.
6. **Путь восстановления не сломан:** повторный `add_channel` удалённого канала возвращает его и его данные в выдачу. **Лимит при восстановлении** (§1, обход `check_channel_limit`) — решение в сессии: считать восстановление созданием для лимита (рекомендуется, иначе R14 откроет обход) или явно записать как известный обход.
7. **Ops-чистка `murashko_med`** на деплое — **полное удаление** (решение владельца 2026-09-25, открытое решение 2 закрыто): карточки, связи, бандлы, версии, processed, raw, эмбеддинги.

   Процедура: пробный подсчёт, свежий бэкап, удаление в транзакции, повторный подсчёт. Строку `sources` не удалять: на ней держится путь восстановления.

   Список таблиц не брать из этого промпта. В начале сессии перечислить все таблицы с `channel_id`, `source_id`, `source_ref`, `sources_json` или `channel_ids` через `information_schema.columns` и для каждой решить: чистить, оставить (например, `source_attempts` — история попыток) или не касается.

**Не входит:**

- нормализация `t.me` и фантомные строки `sources` (R15);
- потолок контекста Phase 2 (R17);
- линковка полного прогона и `link_topics` по одному каналу (R18);
- модель владения каналом (отдельное обсуждение);
- перетопикизация (O1).

---

## 3. Ловушки

- **Связи не уйдут сами** (§1, `topic_links` без FK). При чистке удалять связи явно по id удаляемых карточек (`topic_id_a` / `topic_id_b`) — **в той же транзакции**, иначе в таблице останутся висячие id. Глобальный `delete_all` + relink — нет: это необратимая операция, которую план убрал из очереди.
- **`delete_by_channel` у карточек** — `LIKE` по `sources_json` плюс собственный commit. Для чистки нужен SQL по точному условию (`sources_json::jsonb ->> 0 = 'murashko_med'` — колонка `TEXT`; сначала сверить, есть ли вообще карточки с несколькими источниками: `jsonb_array_length(sources_json::jsonb) > 1`), выполняемый вместе с остальным в одной транзакции и сначала как `SELECT count(*)`.
- **Бэкап — вне рабочей копии.** `.gitignore` защищает только точное имя `.env`, а на хосте уже дважды лежали полные копии прод-`.env` в репозитории (R13, 2026-09-24). Дампы БД — в каталог вне `/home/user/TG_parser`, по образцу `/home/user/env-backups/` (`700`). Размер дампа прикинуть до запуска: на `/mnt/data` было ~11 ГБ свободно.
- **Admin теряет «всё».** Если выбран вариант (A), каждое место, где `None` означало «без фильтра», должно получить список — найти их все, включая `channel_id`-проверки доступа («`if channel_id not in allowed_channel_ids`»).
- **Вариант (B) не закрывает прямой доступ по `channel_id`.** Фильтр в SQL поиска не мешает admin вызвать экспорт, пайплайн или статистику удалённого канала напрямую. При (B) проверки доступа (§1) всё равно нужно править отдельно.
- **Кэш scope 60 с** — после `remove_channel` удалённый канал ещё минуту живёт в `allowed_channel_ids`. Решить: инвалидировать кэш при удалении или принять и записать.
- **Эмбеддинги и документы в поиске** фильтруются по-разному: keyword / semantic / hybrid идут разными путями (`embedding_repo`, processed docs). Тест должен покрыть **все три режима**, иначе один останется дырой.
- **Пересоздание стирает логи**, фаза тика сдвигается на «старт плюс интервал» (урок R10). Хост 2026-09-24 перезагружался — фаза сейчас `:31`, сверить в снимке.
- **Два параллельных полных прогона** на одной `tg_parser_test` конфликтуют (`DROP SCHEMA`) — если R15 гоняет тесты, PR standard по очереди.

---

## 4. Тесты (минимум)

- **Параметризованный тест «удалённый канал не виден»** по всем поверхностям: MCP, бот, API; поиск во всех трёх режимах, RAG, навигация, аналитика, каталог Phase 2, обе линковки, счётчики владения, дайджест и `backfill_watchlist`, `export_channel` (все три уровня — raw / processed / full) и прочие вызовы `assert_channel_access` / `assert_topic_access` с `channel_id` удалённого канала. Прецедент — BUG-093 / BUG-100, класс «тест на то, чего быть не должно». Тест должен падать на текущем `main`.
- **Тот же набор от лица admin** — именно там сейчас утечка.
- **Восстановление:** после повторного `add_channel` канал снова виден; если выбрано «восстановление считается в лимите» — пользователь на лимите не может восстановить канал (MCP и бот).
- **`get_owned_channel_ids`** не возвращает удалённые; `whoami` / `list_users` считают только живые (DF-5).
- **Для процедуры чистки**, если она оформлена кодом или скриптом: удаляет ровно карточки канала и их связи, не трогает чужие карточки с похожим именем в `sources_json`.
- **Полный PR standard** (`TEST_POSTGRES=1`) зелёный; ожидание — около 4.48k passed на 2026-09-24.
- Перед commit — `code-reviewer` (diff затрагивает `tg_parser/**` и `tests/**`).

---

## 5. Деплой, чистка и проверка (только по GO)

1. **Снимок до:**
   - образы трёх контейнеров, фаза тика;
   - контрольные подсчёты по `murashko_med` во всех таблицах из §1, а также связи с его темами по обе стороны;
   - `whoami` оператора и `Ye_Ale`;
   - ответ `search_knowledge_base(mode=keyword)` от admin, который на 2026-09-23 возвращал `topic:tg:murashko_med:post:12528`.
2. **Точка отката** — тег текущего `latest` (`a6977308e61d` на 2026-09-25). Один тег на три сервиса — откат всех трёх на него (урок R13).
3. **Код:** build, пересоздать `tg_parser`, `mcp`, `tg_bot` (код меняется во всех трёх). Если R15 готова — едет этим же деплоем.
4. **Проверка кода:** тот же поиск от admin больше не возвращает `murashko_med`; счётчики `whoami` сходятся с живыми каналами; первый тик прошёл.
5. **Чистка** (полное удаление, объём утверждён) — отдельный шаг, после проверки кода и по отдельному GO на запуск:
   - пробный `SELECT count(*)` по каждой таблице;
   - дамп вне рабочей копии;
   - `BEGIN` … `DELETE` … контрольные `count(*)` … `COMMIT`;
   - повторный подсчёт: связи с темами канала = 0.
6. **Эффект на Phase 2** (отложенно, не блокирует закрытие): первый вызов после деплоя — `cross_channel_topics` и `prompt_chars` в логе меньше базовой линии примерно на долю `murashko_med`, прирост сырого счётчика `stage="topicization_discover"` меньше 290 961. Сверка — как в runbook R13 §3.
7. **Протокол** — `docs/runbooks/BUG107_R14_DEPLOY.md`. BUG-107 → `resolved` после проверки; DF-5 закрывается им же.

---

## 6. Definition of Done

- PR смержен, прод на новом образе, поверхности из §4 не показывают удалённый канал ни одному пользователю, включая admin. Восстановление работает.
- Чистка выполнена в утверждённом объёме, висячих связей нет, бэкап лежит вне репозитория.
- Расход Phase 2 после R14 записан рядом с базовой линией в BUG-108 — это вход в R17.
- BUG-107 закрыт, DF-5 закрыт; в BUG-107 исправлено утверждение «связи удаляются вместе с карточками».
- `PLAN_REMEDIATION` §4a: R14 отмечена. Этот промпт переезжает в `docs/notes/archive/` в PR, закрывающем сессию.
