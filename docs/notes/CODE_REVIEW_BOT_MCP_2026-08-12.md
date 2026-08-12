# Code-Review: bot tools + MCP server (Session #3)

**Когда:** 2026-08-12, 18:41–19:05 UTC · **main@:** `f005f93` · **Ревью:** статическое, read-only; runtime-эталон — матрица [#1](AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md)
**Scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §2 · **План:** [`archive/PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md`](archive/PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md)
**Правило:** каждое утверждение о поведении — из кода, из прогона локальной пробы или из матрицы #1. Что доказать статически нельзя — помечено `needs runtime` и не утверждается.

---

## 0. Замер (вывод блока plan §2 как есть)

```
sha=f005f93
  5017 tg_parser/bot/tools.py
  4605 tg_parser/mcp_server.py
  2853 tg_parser/bot/handlers.py
   682 tg_parser/bot/agent.py
 13157 total
bot declarations: 35
mcp tools:        47
bot write-confirm: 41
tests bot|mcp:    39
```

Совпало со снимком `7bb5d6e` из плана до единицы. Ловушка с неякорённым `@mcp\.tool` воспроизведена: `rg -c '@mcp\.tool'` → 49, `rg -c '^@mcp\.tool'` → 47.

Дополнительный прогон (P7, локально, не на проде):

```
python3 -m pytest -q tests/test_mcp_pagination_contract.py tests/test_pagination_contract_tdd.py
62 passed, 1 warning in 4.36s
```

---

## 1. Резюме

1. **Обе поверхности fail-open по идентичности.** `resolve_mcp_user` при любой ошибке чтения пользователя — и при отсутствии строки — возвращает default admin, а не отказ; 34 из 35 bot-исполнителей начинаются с `current_user or await get_default_admin()`. Это не гипотеза: локальная проба на реальном коде выдала `role=admin is_admin=True` при `mcp_auth_enabled=True` (**F-01**, High).
2. **Найден живой экземпляр класса BUG-093 — пропущенный ownership-check на одной ветке.** Bot-инструмент `list_topics` фильтрует по правам только когда `channel_id` НЕ задан; с явным `channel_id` он отдаёт темы чужого канала. У MCP-близнеца эта проверка есть. Проба: bot → `total=1`, MCP → `total=0` на одном и том же входе (**F-02**, High).
3. **Механизм BUG-096 назван: это нарушение границы ADR-0004/0007.** `mcp_server.py` импортирует приватную `_run_export_job` из `tg_parser.api.routes.export` и исполняет джобу API внутри своего процесса — отсюда файл в чужом контейнере и 404. Соседние `trigger_*` из того же файла ходят по HTTP, как требует ADR-0007. Третий писатель в тот же `job_id`-less путь — bot (**F-03**).
4. **Четыре «мелочи» из #1 разобраны до кода и оказались дефектами формы ответа, а не данных:** topic-хиты проецируются через поле `document`, которого у них нет (**F-04**); `list_digests`/`list_watchlists` печатают страницу дважды (**F-05**); описание сервера обещает `raises` там, где шесть его же docstring'ов и прод возвращают пустоту (**F-06**); `list_channels` не имеет куда положить признак деградации, потому что возвращает голый `list[ChannelSummary]` — то же решение о типе уже вывело его из пагинационного контракта (**F-07**).
5. **Чисто:** `raw_payload` недостижим ни через один инструмент обеих поверхностей (ни одного упоминания, кроме двух строк описаний; `raw_message_repo` не импортируется вовсе); свободный текст пользователя в логи не уходит; confirm-контракт (ADR-0020) покрывает 16 из 18 bot-write-инструментов, оставшиеся два исключены явным решением; все 8 workspace-инструментов и все 10 admin-only инструментов проверены и закрыты.

---

## 2. Карта поверхности (P0 — сгенерирована AST-обходом, не написана руками)

### MCP — 47 инструментов

| # | инструмент | r/w | admin | access-check | `workspace_id` | пагинация |
|---|---|---|---|---|---|---|
| 1 | `search_knowledge_base` | r | — | `_resolve_workspace_scope` → `allowed_channel_ids` в сервис | yes | — |
| 2 | `ask_question` | r | — | `_resolve_workspace_scope` → сервис | yes | — |
| 3 | `list_topics` | r | — | `_resolve_workspace_scope` + явная проверка `channel_id not in effective` | yes | yes |
| 4 | `get_topic_details` | r | — | `_resolve_workspace_scope`, `allowed_channel_ids` ∩ `card.sources` | yes | — |
| 5 | `list_channels` | r | — | `_resolve_workspace_scope` → сервис | yes | n/a — голый list (F-07) |
| 6 | `get_document` | r | — | `_resolve_workspace_scope`, `doc.channel_id in allowed` | yes | — |
| 7 | `get_related_topics` | r | — | `_resolve_workspace_scope` → сервис | yes | — |
| 8 | `get_cross_channel_stats` | r | — | `_resolve_workspace_scope` → сервис | yes | — |
| 9 | `add_channel` | w | — | `assert_source_mutable` (update) / `check_channel_limit` (create) | — | — |
| 10 | `pause_channel` | w | — | `assert_channel_access` | — | — |
| 11 | `resume_channel` | w | — | `assert_channel_access` | — | — |
| 12 | `remove_channel` | w | — | `assert_channel_access` | — | — |
| 13 | `get_pipeline_status` | r | — | фильтр по `allowed_channel_ids` | — | — |
| 14 | `trigger_pipeline` | w | — | `assert_channel_access` (в `_mcp_trigger_pipeline_job`) | — | — |
| 15 | `trigger_topicization` | w | — | `assert_channel_access` (там же) | — | — |
| 16 | `trigger_link_topics` | w | — | `assert_channel_access` (там же) | — | — |
| 17 | `get_llm_config` | r | — | **нет** — provider/model видит любой аутентифицированный | — | — |
| 18 | `set_llm_config` | w | yes | `assert_admin` | — | — |
| 19 | `reset_llm_config` | w | yes | `assert_admin` | — | — |
| 20 | `register_user` | w | yes | `assert_admin` | — | — |
| 21 | `update_user` | w | yes | `assert_admin` | — | — |
| 22 | `list_users` | r | yes | `assert_admin` | — | yes |
| 23 | `whoami` | r | — | self-scoped | — | — |
| 24 | `add_user_auth` | w | yes | `assert_admin` | — | — |
| 25 | `remove_user_auth` | w | yes | `assert_admin` | — | — |
| 26 | `get_topic_versions` | r | — | `assert_topic_access` | — | — |
| 27 | `get_topic_history_diff` | r | — | `assert_topic_access` | — | — |
| 28 | `force_resummarize` | w | yes | `assert_admin` | — | — |
| 29 | `reload_prompts` | w | yes | `assert_admin` | — | — |
| 30 | `export_channel` | w | — | `assert_channel_access` | — | — |
| 31 | `get_export_status` | r | — | **НЕТ** — F-10 | — | — |
| 32 | `subscribe_digest` | w | — | `assert_channel_access` ×N, `assert_topic_access` ×N | yes | — |
| 33 | `list_digests` | r | — | owner-scoped finder `list_by_owner` | — | yes |
| 34 | `unsubscribe_digest` | w | — | `owner_id == user.id` | — | — |
| 35 | `subscribe_watchlist` | w | — | `assert_channel_access` ×N | yes | — |
| 36 | `list_watchlists` | r | — | owner-scoped finder `list_for_user` | — | yes |
| 37 | `unsubscribe_watchlist` | w | — | `requesting_user_id` в сервис | — | — |
| 38 | `get_watchlist_matches` | r | — | `interest.user_id == user.id` | — | — |
| 39 | `backfill_watchlist` | w | — | `interest.user_id == user.id` + `confirm` | — | — |
| 40 | `list_workspaces` | r | — | owner-scoped `list_by_owner` | — | — |
| 41 | `create_workspace` | w | — | owner-scoped write (`owner_id=user.id`) | — | — |
| 42 | `rename_workspace` | w | — | `assert_workspace_access` (сервис) | — | — |
| 43 | `delete_workspace` | w | — | `assert_workspace_access` | — | — |
| 44 | `add_workspace_source` | w | — | `assert_workspace_access` | — | — |
| 45 | `remove_workspace_source` | w | — | `assert_workspace_access` | — | — |
| 46 | `list_workspace_sources` | r | — | `assert_workspace_access` | — | — |
| 47 | `list_all_workspaces` | r | yes | admin в сервисе → пустой список без ошибки | — | — |

### bot — 35 деклараций

| # | инструмент | r/w | confirm | paged | ctx | access-check |
|---|---|---|---|---|---|---|
| 1 | `ask_question` | r | — | — | yes | `allowed_channel_ids` |
| 2 | `search_knowledge_base` | r | — | — | yes | `allowed_channel_ids` |
| 3 | `list_topics` | r | — | yes | yes | `allowed_channel_ids` — **пропущен при заданном `channel_id` (F-02)** |
| 4 | `get_topic_details` | r | — | — | — | `allowed_channel_ids` ∩ `card.sources` |
| 5 | `get_topic_versions` | r | — | — | — | `allowed_channel_ids` ∩ `card.sources` |
| 6 | `get_topic_history_diff` | r | — | — | — | `allowed_channel_ids` ∩ `card.sources` |
| 7 | `force_resummarize` | w | yes | — | — | `assert_admin` (до любого чтения) |
| 8 | `list_channels` | r | — | yes | — | `allowed_channel_ids` |
| 9 | `get_document` | r | — | — | — | `doc.channel_id in allowed` |
| 10 | `get_related_topics` | r | — | — | — | `allowed_channel_ids` |
| 11 | `get_cross_channel_stats` | r | — | — | yes | `allowed_channel_ids` |
| 12 | `trigger_pipeline` | w | yes | — | — | `assert_channel_access` |
| 13 | `get_pipeline_status` | r | — | — | — | фильтр по `allowed_channel_ids` |
| 14 | `pause_channel` | w | yes | — | — | `assert_channel_access` |
| 15 | `resume_channel` | w | yes | — | — | `assert_channel_access` |
| 16 | `add_channel` | w | yes | — | — | `assert_source_mutable` / `check_channel_limit` |
| 17 | `remove_channel` | w | yes | — | — | `assert_channel_access` |
| 18 | `get_llm_config` | r | — | — | — | **нет** (единственный executor без резолва user) |
| 19 | `set_llm_config` | w | yes | — | — | `assert_admin` |
| 20 | `reset_llm_config` | w | yes | — | — | `assert_admin` |
| 21 | `reload_prompts` | w | **—** | — | — | `assert_admin` (вне confirm — явное решение, `tools.py:106–109`) |
| 22 | `register_user` | w | yes | — | — | `assert_admin` |
| 23 | `update_user` | w | yes | — | — | `assert_admin` |
| 24 | `list_users` | r | — | yes | — | `assert_admin` |
| 25 | `whoami` | r | — | — | — | self-scoped |
| 26 | `add_user_auth` | w | yes | — | — | `assert_admin` |
| 27 | `remove_user_auth` | w | yes | — | — | `assert_admin` |
| 28 | `export_channel` | w | **—** | — | — | `assert_channel_access` (вне confirm — явное решение, `tools.py:106–109`) |
| 29 | `subscribe_digest` | w | yes | — | — | `assert_channel_access` ×N |
| 30 | `list_digests` | r | — | yes | — | owner-scoped finder `list_by_owner` |
| 31 | `unsubscribe_digest` | w | yes | — | — | `owner_id == user.id` |
| 32 | `subscribe_watchlist` | w | yes | — | — | `assert_channel_access` ×N |
| 33 | `list_watchlists` | r | — | yes | — | owner-scoped finder `list_for_user` |
| 34 | `unsubscribe_watchlist` | w | yes | — | — | `user_id == user.id` |
| 35 | `get_watchlist_matches` | r | — | — | — | `interest.user_id == user.id` |

---

## 3. Находки — индекс

| ID | Severity | Ось | Файл | Одной строкой |
|---|---|---|---|---|
| F-01 | **High** | authz | оба | Резолв идентичности деградирует до default admin вместо отказа |
| F-02 | **High** | authz | `bot/tools.py` | `list_topics` с явным `channel_id` не фильтрует по правам — чужие темы читаются |
| F-03 | Medium | contract-drift | `mcp_server.py` | Экспорт исполняет приватную джобу API внутри MCP-процесса (механизм BUG-096) |
| F-04 | Medium | correctness | оба | Topic-хиты поиска проецируются через `document`, которого у них нет → строка из `null` |
| F-05 | Medium | parity | оба | `list_digests` / `list_watchlists` отдают одну страницу под двумя ключами |
| F-06 | Medium | contract-drift | `mcp_server.py` | Описание сервера обещает `404-like error` там, где возвращается пустой результат |
| F-07 | Medium | correctness | оба | `list_channels` не может выразить деградацию: тип ответа не имеет для неё места |
| F-08 | Low | contract-drift | оба | `offset` / `limit` не валидируются: отрицательный `limit` даёт страницу больше страницы |
| F-09 | Low | contract-drift | `mcp_server.py` | MCP-ресурс `.../topics` итерирует Pydantic-модель как список → `AttributeError` |
| F-10 | Low | authz | `mcp_server.py` | `get_export_status` не проверяет владельца джобы; HTTP-скачивание — тоже |
| F-11 | Low | correctness | `bot/tools.py` | Заголовок watchlist уходит в HTML-сообщение без `html.escape` |
| F-12 | Low | correctness | `mcp_server.py` + bot | `shared_keywords` собираются без стоп-листа — завышен и ярлык, и сам score |

---

## 4. Находки — разбор

### F-01 (High — authz) — резолв идентичности на обеих поверхностях деградирует до default admin вместо отказа

| Поле | Значение |
|---|---|
| **Anchor** | `resolve_mcp_user`, `mcp_server.py:500–547` на `f005f93`; парно — `user = current_user or await get_default_admin()` в 34 из 35 bot-исполнителей (`bot/tools.py:2037` … `:4934`) |
| **Evidence** | `try: … db_user = await repo.get_by_id(client_id) … if db_user is not None: return CurrentUser(...) except Exception: logger.debug(...)` → далее безусловный `return await get_default_admin()`. Локальная проба (`mcp_auth_enabled=True`, DB-исключение): `db_error -> id=00000000-…-0000 role=admin is_admin=True allowed=None`; та же строка при отсутствующем пользователе: `unknown_id -> … role=admin is_admin=True` |
| **Verified** | Оба пути — сбой чтения и отсутствие строки — дают полного admin, не ошибку. `get_owned_channel_ids` для не-admin вызывается **внутри** того же `try`, поэтому под деградацию попадает каждый вызов не-администратора при любой ошибке БД. Логируется `logger.debug` (невиден на INFO) плюс `mcp.auth.static_fallback_used` — неотличимо от легального static-token пути. **Not verified:** частота на проде — записи `static_fallback_used` не смотрели (`needs runtime`) |
| **Impact** | Привилегированная эскалация: bearer-токен обычного пользователя во время сбоя БД получает права на все каналы; удаление пользователя открывает окно до 60 с (TTL кэша `resolvers._CACHE_TTL`), в котором его токен ещё проходит верификацию, а `get_by_id` уже возвращает `None` → admin. На bot-стороне единственное, что отделяет незарегистрированного Telegram-пользователя от default admin, — пустой allowlist в `UserResolutionMiddleware`, то есть конфигурация, а не код; `handlers.py:2759` явно называет это «load-bearing, not defensive» |
| **Fix direction** | Минимальный фикс: сузить `except Exception` до транспортных ошибок и в обоих случаях (`db_user is None`, исключение) поднимать `PermissionError`, как уже делает ветка `client_id is None`; static-fallback оставить только для client_id, который заведомо не UUID. Hardening (отдельно): убрать `or await get_default_admin()` из исполнителей и сделать `current_user` обязательным — сегодня безопасность bot-слоя обеспечивается дисциплиной вызывающих |
| **Runtime check needed** | Да: посчитать `mcp.auth.static_fallback_used` за 7 суток на проде и убедиться, что это только легальные static-токены |

### F-02 (High — authz) — bot `list_topics` пропускает проверку прав на ветке с явным `channel_id`

| Поле | Значение |
|---|---|
| **Anchor** | `_exec_list_topics`, `bot/tools.py:2102–2111`; MCP-близнец — `mcp_server.py:1334–1347` |
| **Evidence** | bot: `if channel_id: cards = await topic_card_repo.list_by_channel(channel_id)` — и всё; `elif user.allowed_channel_ids is not None:` применяется только когда канал НЕ задан. MCP: `if channel_id: if effective is not None and channel_id not in effective: cards = []`. Проба на одинаковом входе (не-admin владеет `own_channel`, спрашивает `foreign_channel`): `bot list_topics(foreign): total=1 titles=['Foreign topic']` против `mcp list_topics(foreign): total=0 titles=[]` |
| **Verified** | Кросс-тенантное чтение: заголовки, summary и `sources` тем чужого канала. Ветка достижима любым обычным запросом «покажи темы канала X». Почему не поймал CI: `test_f4_coverage_supplement.py:77` (`test_exec_list_topics_uses_list_by_channels_for_user`) вызывает `_exec_list_topics({})` — **без** `channel_id`, то есть тестирует ровно ту ветку, где проверка есть. Точно тот же blind-spot, что у BUG-093. **Not verified:** влияние на проде — там единственный пользователь admin, для которого `allowed_channel_ids is None` и разницы нет |
| **Impact** | То же, что BUG-093, но на стороне чтения: любой не-admin Telegram-пользователь читает содержание чужих каналов. Сегодня не стреляет по той же причине, по которой не стрелял BUG-093 — не-admin-учётных записей на проде не выпускали |
| **Fix direction** | Перенести MCP-условие в bot-ветку один в один (`if user.allowed_channel_ids is not None and channel_id not in user.allowed_channel_ids: cards = []`). Тест-обязательство: у каждого read-инструмента с параметром `channel_id` — кейс «чужой канал задан явно», а не только «канал не задан» |
| **Runtime check needed** | Нет для доказательства; да для post-fix smoke — как в BUG-093, одноразовым `user`-токеном |

### F-03 (Medium — contract-drift) — экспорт MCP исполняет приватную джобу API в своём процессе, минуя ADR-0007

| Поле | Значение |
|---|---|
| **Anchor** | `export_channel`, `mcp_server.py:2947–3020`; `get_export_status`, `:3056–3057`; `api/routes/export.py:133`; bot — `bot/tools.py:3724–3744` |
| **Evidence** | `from tg_parser.api.routes.export import _run_export_job` → `task = _asyncio.create_task(_run_export_job(job_id, request))`. В `api/routes/export.py:132–133`: `job.file_path = str(export_file)`, `job.download_url = f"/api/v1/export/download/{job_id}"`. Соседние `trigger_*` в том же файле идут через `pipeline_dispatch_client.post_pipeline_trigger` |
| **Verified** | Единственный write-инструмент MCP, который не «тонкий HTTP-клиент», а исполнитель чужого адаптера: приватный символ (`_`-префикс) импортируется через границу `api` → `mcp`. Отсюда прямо следует 404 из BUG-096 — writer и reader физически в разных контейнерах. Третий писатель того же пути найден: bot собирает `output_dir / f"raw_messages.{ext}"` (`tools.py:3740`) — тоже без `job_id`. ADR-0004 перечисляет известные deviations, экспорта среди них нет; ADR-0007 §Решение: «MCP/Bot as thin HTTP clients» |
| **Impact** | Механизм, которого не хватает записи BUG-096: она предлагает три лечения (общий том / dispatch / объектное хранилище), но не называет причину, по которой выбор вообще нужен. Вариант (b) из BUG-096 — это возврат к ADR-0007, а не одна из равных опций. Коллизия путей — трёхсторонняя, не двухсторонняя |
| **Fix direction** | Свести `export_channel` к тому же паттерну, что `trigger_*`: POST на API, `job_id` в ответ. Правку `file_path` по `job_id` делать независимо — она нужна и bot'у, который вообще не создаёт джобу |
| **Runtime check needed** | Нет — расхождение чисто статическое; 404 уже намерен в #1 |

### F-04 (Medium — correctness) — topic-хиты поиска проецируются через поле `document`, которого у них нет

| Поле | Значение |
|---|---|
| **Anchor** | `search_knowledge_base`, `mcp_server.py:1200–1211`; `_exec_search`, `bot/tools.py:2071–2080`; источник — `retrieval_service.py:293–308` |
| **Evidence** | Проекция: `summary=doc.summary if doc else None, text_preview=doc.text_clean[:300] if doc else None, channel_id=doc.channel_id if doc else None`. В `retrieval_service` topic-хит собирается как `SearchResult(source_ref=…, score=…, entry_type="topic", topic_card=card)` — `document` у него **всегда** `None`, а данные лежат в `topic_card` |
| **Verified** | Строка `summary=null, text_preview=null, channel_id=null`, которую #1 видела в гибридной выдаче, — не потеря данных, а неполная проекция: `card.title`, `card.summary`, `card.sources` доступны и выбрасываются. `entry_type` в ответ тоже не попадает, поэтому клиент не может отличить topic-хит от битого документа. **Not verified (второй, более неприятный путь):** в `retrieval_service.py:293–300` фильтр по `allowed_channel_ids` стоит под `if card:`, а `results.append(...)` — снаружи, поэтому topic-хит с незагруженной карточкой возвращается в обход RBAC. Наблюдалась ли на проде именно эта ветка, из артефакта #1 не следует — `needs runtime` |
| **Impact** | Пользователь и агент получают в выдаче строку без единого читаемого поля; для LLM это мусорный контекст, который она всё равно пересказывает. Второй путь, если он реален, — кросс-тенантная утечка `source_ref` |
| **Fix direction** | Добавить в `SearchResultItem` ветку для `entry_type="topic"` (title/summary из `topic_card`, `channel_id` из `card.sources[0]`) и отдавать `entry_type` наружу — правка целиком в двух ревьюируемых файлах. Отдельно и в другом файле: занести `results.append` под `if card:` либо явно пропускать хит без карточки |
| **Runtime check needed** | Да — для второго пути: встречается ли topic-хит с `card is None` (лог/счётчик на ветке) |

### F-05 (Medium — parity) — `list_digests` / `list_watchlists` отдают одну и ту же страницу под двумя ключами

| Поле | Значение |
|---|---|
| **Anchor** | MCP `mcp_server.py:3464–3473` и `:3854–3863`; bot `bot/tools.py:4244` и `:4765` через `_paginate_read_result(..., legacy_key=…)` (`:244–246`) |
| **Evidence** | MCP: `return ListDigestsResult(count=total, subscriptions=page, …, items=page, …)` — один и тот же `page` дважды. bot: `result[legacy_key] = page; result["count"] = total` поверх уже записанного `result["items"] = page` |
| **Verified** | Дублирование по построению на обеих поверхностях, у обоих инструментов. Комментарии моделей называют это осознанной backward-compat («legacy full/page list … `items` mirrors the page»), то есть дефект не в реализации, а в том, что переходный период не закрыт. #1 намерила 44.4 КБ на 24 интереса |
| **Impact** | Удвоенный payload на самом «болтливом» ответе surface'а; для MCP-клиента это удвоенный контекст LLM. Сюда же попадают 8 неактивных smoke-интересов с мая (адрес #7 плана): их включение **не дефект** — docstring и `MCP_AGENT_GUIDE:82` объявляют его намеренным, — но фильтра `is_active` в инструменте нет, и они удваиваются вместе со всем остальным |
| **Fix direction** | Назначить дату снятия legacy-ключей и до неё — не отдавать оба; параллельно добавить необязательный `is_active` фильтр. Смена ключей — breaking change, поэтому это решение владельца, а не правка |
| **Runtime check needed** | Нет |

### F-06 (Medium — contract-drift) — описание сервера обещает ошибку там, где возвращается пустой результат

| Поле | Значение |
|---|---|
| **Anchor** | `_MCP_INSTRUCTIONS`, `mcp_server.py:314` против docstring'ов `:1174`, `:1313`, `:1422`, `:1536`, `:1590`, `:1637` |
| **Evidence** | `:314` — «Unknown / foreign workspace_id **raises a 404-like error** (existence is never leaked)». Фактическая реализация во всех восьми read-инструментах: `except WorkspaceNotFound: return SearchResults(result=[], degraded=False)` / `return []` / `return TopicListResult(total=0, …)` / `return f"Topic not found: {topic_id}"` |
| **Verified** | Расхождение внутри одного файла: `WorkspaceNotFound` действительно поднимается в `_resolve_workspace_scope`, но каждый инструмент её ловит и превращает в пустоту. Прогон #1 согласен с docstring'ами, а не с описанием сервера. Это ровно вход, переданный сессией #2 (§6) |
| **Impact** | Описание сервера — единственный текст, который MCP-клиент читает **до** вызова. Агент, обученный отличать ошибку от пустого результата, на неизвестном `workspace_id` получит «в этом workspace ничего нет» и сделает неверный вывод о данных, а не о запросе |
| **Fix direction** | Однострочная правка `:314` под фактическое поведение («returns an empty result — existence is never leaked»). Обратный вариант — поднимать ошибку — ломает восемь инструментов и текущий контракт «не раскрывать существование» единообразно; выбирать не здесь |
| **Runtime check needed** | Нет — #1 уже прогнала неизвестный `workspace_id` |

### F-07 (Medium — correctness) — `list_channels` не имеет куда положить признак деградации

| Поле | Значение |
|---|---|
| **Anchor** | `ChannelSummary.coverage_percent: float`, `mcp_server.py:685`; `list_channels` `:1488` (`-> list[ChannelSummary]`); bot `bot/tools.py:2339`; источник подмены — `channel_service.get_all_channel_stats` |
| **Evidence** | Поле не-опциональное; инструмент возвращает голый `list[...]`, без модели-обёртки. Комментарий `_PAGINATED_READ_TOOLS` в том же файле (`:53–57`) объясняет, что `list_channels` исключён из пагинационного контракта **по той же причине**: «returns a bare `list[ChannelSummary]` … so it has no sidecar field». В сервисе на таймауте: `coverage_counts = {}` → `coverage_percent = 0.0` |
| **Verified** | In-scope половина BUG-098 — это выбор типа возврата, а не производительность запроса: пока ответ — голый список, деградацию физически некуда положить, и по этой же причине инструмент выпал из TD-D-02. Образец решения уже есть в этом же файле: `SearchResults.degraded` и `AnswerResultItem.degraded` (BUG-084) — обёртка с сайдкар-полем |
| **Impact** | Читатель не отличает «покрытия нет» от «запрос сдался»; #1 намерила 3 из 3 вызовов в деградации. Пока тип не изменён, ни один клиент — ни агент, ни человек — не может себя защитить |
| **Fix direction** | Обернуть ответ (`ChannelListResult{items, degraded}`) по образцу `SearchResults` — одна правка закрывает и маркер деградации, и исключение из пагинационного контракта. Половина (b) BUG-098 (оптимизация запроса) от этого не зависит |
| **Runtime check needed** | Нет |

### F-08 (Low — contract-drift) — `offset` / `limit` не валидируются ни в декларациях, ни в исполнителях

| Поле | Значение |
|---|---|
| **Anchor** | `_paginate_read_result`, `bot/tools.py:230–236`; `list_topics` MCP `mcp_server.py:1355`, `:1379`; `paginate_items`, `utils/pagination.py:65–67` |
| **Evidence** | Проба на 50 строках: `{'limit': 0}` → `limit 20 page 20`; `{'limit': -5}` → `limit -5 page 45 has_more True next {'offset': -5, 'limit': -5}`; `{'offset': -10, 'limit': 5}` → `page 5 has_more True next {'offset': -5, …}`. В `TOOL_DECLARATIONS` — 10 параметров типа `INTEGER` и ноль `minimum` / `maximum` (`rg -c '"minimum"' tg_parser/bot/tools.py` → 0) |
| **Verified** | Отрицательный `limit` отдаёт «страницу» в 45 строк вместо 20 и выставляет `has_more=True` с `pagination_pending`, который bot-FSM «ещё» послушно повторит; отрицательный `offset` нумерует элементы `n = -9 … -5` и листает от конца. `paginate_items` (MCP `list_users` / `list_digests` / `list_watchlists`) зажимает только `offset`, но не `limit`. Аргументы на bot-поверхности приходят от LLM, то есть источник значений не доверенный |
| **Impact** | Не authz и не потеря данных: испорченная выдача и зацикленное «ещё». Low, потому что каждый шаг всё же терминален (пользователь видит странный список, а не зависание) |
| **Fix direction** | Зажимать в одном месте — в `paginate_items` / `_paginate_read_result` (`limit = max(1, min(limit, CAP))`, `offset = max(0, offset)`), и добавить `minimum`/`maximum` в декларации, чтобы Gemini не порождал такие вызовы |
| **Runtime check needed** | Нет |

### F-09 (Low — contract-drift) — MCP-ресурс `tgparser://channels/{id}/topics` мёртв

| Поле | Значение |
|---|---|
| **Anchor** | `resource_channel_topics`, `mcp_server.py:4519–4527` |
| **Evidence** | `topics = await list_topics(channel_id=channel_id)` → `[t.model_dump() for t in topics]`. `list_topics` возвращает `TopicListResult`; в Pydantic v2 `BaseModel.__iter__` отдаёт кортежи `(key, value)`. Проба: `AttributeError: 'tuple' object has no attribute 'model_dump'` |
| **Verified** | Ресурс не может отработать ни на каком входе. Соседний `resource_topic` учитывает обёртку (`if isinstance(detail, str)`), а `resource_channels` работает, потому что `list_channels` действительно возвращает список. То есть отстал ровно один ресурс — тот, чей инструмент получил модель-конверт (`TopicListResult`) и не был обновлён. Класс BUG-096: контракт выглядит завершённым и недостижим. Тестов на MCP-ресурсы нет (`rg -l 'resource_channel_topics' tests/` → пусто) |
| **Impact** | Один из трёх объявленных MCP-ресурсов не работает. Малое влияние: клиенты проекта ходят инструментами, ресурсы — витрина |
| **Fix direction** | `[t.model_dump() for t in topics.items]`; заодно один smoke-тест на каждый из трёх ресурсов, иначе тот же класс вернётся при следующей смене типа возврата |
| **Runtime check needed** | Нет — воспроизведено локально |

### F-10 (Low — authz) — `get_export_status` не проверяет владельца джобы

| Поле | Значение |
|---|---|
| **Anchor** | `get_export_status`, `mcp_server.py:3060` (`_user = await resolve_mcp_user(...)` — резолвится и не используется); парный HTTP-путь — `api/routes/export.py:311–312` (`_user: CurrentUser = Depends(resolve_current_user)`, тоже не используется) |
| **Evidence** | Между резолвом и `return` нет ни одной ссылки на `_user`; ответ несёт `channel_id`, `download_url`, `file_size`. `Job` хранит `client=user.name`, то есть данные для проверки есть |
| **Verified** | Единственный read-инструмент MCP без какой-либо проверки доступа (см. таблицу P0). Ограничитель — только неугадываемость `job_id` (UUID4) и отсутствие инструмента, перечисляющего джобы (`rg '@router.get\("/jobs' tg_parser/api/routes/` → пусто) |
| **Impact** | Изоляция арендаторов держится на секретности идентификатора, а не на проверке. `job_id` попадает в логи и в переписку с агентом — это не секрет по своей природе |
| **Fix direction** | Сверять `job.client` (или добавить `owner_user_id` в `Job`) с вызывающим — симметрично на MCP и на HTTP-скачивании; для admin — сквозной доступ, как везде |
| **Runtime check needed** | Нет |

### F-11 (Low — correctness) — заголовок watchlist уходит в HTML-сообщение без экранирования

| Поле | Значение |
|---|---|
| **Anchor** | `_exec_subscribe_watchlist`, `bot/tools.py:4722` |
| **Evidence** | `text=(f"🔔 Watchlist <b>{created_interest.title}</b> {verb_ru}.\n…")`, `parse_mode="HTML"`. Соседний digest-путь в том же файле (`:4181`) — `f"📰 Подписка <b>{html.escape(created_sub.name)}</b> …"`; превью самого watchlist (`:4633`) тоже экранирует, с комментарием «N1: HTML-escape the user-controlled title» |
| **Verified** | Единственное место в файле, где пользовательская строка попадает в `parse_mode="HTML"` без `html.escape`, при том что соглашение N1 применено везде рядом. Заголовок задаётся пользователем |
| **Impact** | Заголовок с `<` или `&` ломает рендер подтверждения (Telegram отвергает разметку, сообщение уходит битым или не уходит вовсе). Инъекции наружу нет — сообщение читает сам автор заголовка |
| **Fix direction** | `html.escape(created_interest.title)`; проверить остальные `parse_mode="HTML"` вызовы одним свипом, а не поштучно |
| **Runtime check needed** | Нет |

### F-12 (Low — correctness) — `shared_keywords` собираются без стоп-листа, что завышает и ярлык, и сам score

| Поле | Значение |
|---|---|
| **Anchor** | Поверхность: `get_related_topics`, `mcp_server.py:1606–1614` и `bot/tools.py:2387–2396` (оба транслируют `r["shared_keywords"]` как есть). Источник: `analytics_service._extract_keywords:48–59`, потребитель — `topic_linking_service._jaccard_similarity:100` |
| **Evidence** | `for word in scope_item.lower().split(): cleaned = word.strip(".,;:!?()[]\"'"); if len(cleaned) >= 3: kws.add(cleaned)`. Единственный фильтр — длина ≥ 3, поэтому «для» (3 символа) и «участников» проходят. Стоп-листа в проекте нет вообще: `rg -rn 'STOPWORDS|stop_words|stopword' tg_parser/` → пусто |
| **Verified** | Наблюдение #1 («стоп-слова в `shared_keywords`») подтверждено до строки. Важнее, чем видел #1: те же токены формируют множества, по которым считается Jaccard, — значит завышен не только показанный список, но и `similarity_score`, и, следовательно, состав связей, прошедших порог `cross_channel_link_threshold=0.3`. Ревьюируемые файлы дефекта не вносят — они его показывают |
| **Impact** | Межканальные связи выглядят осмысленнее, чем есть, а часть из них существует только благодаря служебным словам. Это вход в качество F-фичи, не в безопасность |
| **Fix direction** | Русско-английский стоп-лист (или порог по df) в `_extract_keywords`; пересчитать линковку после — иначе старые связи останутся с завышенными score. Правка вне двух ревьюируемых файлов, поэтому это кандидат в отдельную сессию, а не в правку поверхности |
| **Runtime check needed** | Да: после фикса — сколько связей уходит ниже порога 0.3 |

---

## 5. Отчёт по проходам

- **P0 — инвентарь: пройден полностью, сгенерирован.** AST-обход обоих файлов даёт 47 MCP-инструментов и 35 bot-деклараций (совпало с замером §2); колонка access-check заполнена у каждого из 82. Символьного обхода не хватило в 14 случаях, где проверка живёт в хелпере или в сервисе (`_mcp_trigger_pipeline_job`, `WorkspaceService`) — они разрешены чтением и помечены в таблицах.
- **P1 — ownership-свип: пройден полностью, две находки.** Вердикт по каждому write-инструменту: 26 MCP-write и 18 bot-write закрыты (`assert_*`, owner-scoped запрос или `owner_id == user.id`); ноль без проверки. Дыра нашлась не на write, а на read (**F-02**) и в самом резолве идентичности (**F-01**). Десять admin-only инструментов, которые #1 не прогоняла (`not_run`), проверены статически: `assert_admin` стоит до любого чтения и до превью на обеих поверхностях.
- **P2 — write-shape: пройден выборочно.** `subscribe_*` идут через сервисный upsert по натуральному ключу с `changed_fields` — частичного затирания нет; `update_user` использует сентинел `...`, поэтому неуказанные поля не трогаются; workspace-операции пишут по одному полю. Класс BUG-094 (частичный объект против full-row upsert) воспроизводится **только** в `add_channel` — это уже заведено, дублировать не стал. Побочно: `pause_channel` / `resume_channel` на обеих поверхностях пишут полностью загруженный `Source`, то есть BUG-094 на них не распространяется.
- **P3 — parity: пройден выборочно, одна находка (F-05) плюс три нити.** Расхождения без импакта: bot `get_pipeline_status` отдаёт `retopicize_threshold`, MCP — нет; bot `get_document` режет `text_clean[:2000]`, MCP отдаёт целиком; `workspace_id` принимают 10 MCP-инструментов и ноль bot-инструментов (bot не знает про workspaces вовсе — это не дрейф, а объявленный scope F4-B).
- **P4 — восемь адресов: разобраны все восемь.** 1 → F-03, 2 → F-06, 3 → F-05, 4 → F-04, 5 → F-12, 6 → F-07. Адрес 7 (неактивные smoke-интересы) — **не дефект**: включение объявлено в docstring и в `MCP_AGENT_GUIDE:82`; в F-05 попал только отсутствующий фильтр. Адрес 8 (`get_pipeline_status` транслирует `fail_count`) — **не дефект в этих двух файлах**: инструмент побайтно зеркалит `scheduler_service.get_scheduler_status`, ничего не вычисляя; ложь пишется выше по течению (BUG-097), поверхность честна.
- **P5 — privacy: пройден полностью, чисто.** Все log-вызовы обоих файлов просмотрены — 20 в `tools.py` и 22 в `mcp_server.py` (`rg -c 'logger\.'`), из них не-`debug` 11 и 16: свободного текста пользователя (`query`, `question`, `title`, `name`) в логах нет; `redact_tool_args` применён на обоих INFO-сайтах, которые действительно логируют аргументы (`agent.py:431`, `handlers.py:987`) — в самих ревьюируемых файлах таких сайтов нет. `raw_payload` недостижим структурно: в обоих файлах слово встречается только в текстах описаний (`mcp_server.py:249`, `tools.py:943`), `raw_message_repo` не импортируется ни разу. Одно замечание без находки: `tool_permission_denied` / `tool_validation_error` кладут в лог `str(exc)`, а сообщения исключений местами содержат аргументы вызова.
- **P6 — concurrency: пройден выборочно.** Advisory-lock `force_resummarize` не трогается поверхностью и корректно пробрасывает `status='locked'`. Файловая гонка BUG-096 воспроизводится и у bot (F-03). Отмечено без находки: bot `_exec_pause_channel` / `_exec_resume_channel` читают `Source` в одной сессии и пишут в другой (`tools.py:2596` → `:2642`), а MCP делает это в одном блоке — окно потерянного обновления шире на bot-стороне; влияние ограничено тем, что пишется полная строка. **Срезано:** жизнь пагинационных курсоров в FSM (это `handlers.py` без триггера) и таймауты `trigger_*` (весь механизм — в `pipeline_dispatch_client`, вне scope).
- **P7 — дрейф контрактов: пройден выборочно, две находки.** Оба пагинационных контракт-теста прогнаны локально — 62 passed. ADR-0004: `api` не импортирует `bot` / `mcp_server` ни разу; обратно — `mcp_server` тянет из `api` три модуля, включая приватные символы (F-03), `bot` — `api.schemas` (легально, это контрактные типы) и `api.metrics` в `agent.py` (уже записано в ADR-0004 как known deviation). ADR-0007: путь `resolve_mcp_user` (`mcp_server.py:456`) соответствует принятой схеме — идентичность берётся из auth-контекста, а не из `ctx.client_id` (BUG-001), но деградация из F-01 схемой не предусмотрена. Схемы деклараций против валидации: enum'ы объявлены в 6 местах и в исполнителях не перепроверяются — для `role` спасает CHECK-констрейнт в БД (`migrations/versions/ingestion/20260416_add_users_and_ownership.py`), для остальных значение приходит из закрытого списка; числовых границ нет нигде (F-08). **Срезано:** сверка result-моделей с `docs/contracts/*.schema.json` — там лежат контракты доменных артефактов (`raw_telegram_message`, `processed_document`), а не tool-ответов, поэтому сверять нечего.

---

## 6. `handlers.py`: подключался

**`handlers.py` подключён из-за F-01** (триггер (b) plan §4: находка High требует контекста диспетчера). Прочитаны только вовлечённые пути: шесть call-site'ов `execute_tool` (`:991`, `:1309`, `:1448`, `:2165`, `:2665`, `:2789`) — все передают `current_user` дальше, ни один не подставляет admin, — и `_handle_write_intent_router` (`:2725–2800`), где отказ работать при `current_user is None` прокомментирован как «load-bearing, not defensive». Этого хватило, чтобы установить: fail-open в `tools.py` сегодня не стреляет благодаря дисциплине вызывающих и `UserResolutionMiddleware`, а не благодаря структурной защите. Весь остальной файл не читался.

---

## 7. Предложение remediation-сессий

> **Развёрнуто в отдельный план:** [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) — scope / rationale / deliverable / test strategy на каждую сессию, граф зависимостей, стыковка с открытыми записями `BUG_LOG` и один дополнительный замер на проде, уточнивший стоимость R1. Таблица ниже остаётся кратким оглавлением; при расхождении верить плану (там R4 разделена на R4a / R4b).

Группировка по признаку «одна сессия — один класс дефекта и один способ проверки». Номера BUG **не резервируются**: id выдаётся в момент записи командой из [`AUDIT_DOCUMENTATION_2026-08-12.md`](AUDIT_DOCUMENTATION_2026-08-12.md) §4.

| Сессия | Находки | Почему вместе | Предлагаемый BUG |
|---|---|---|---|
| **R1 — fail-closed идентичность** | F-01 | Один класс на двух поверхностях; проверяется одним red/green-набором на резолверах. Первая по очереди: пока резолв fail-open, вердикты остальных проверок условны | 1 запись (обе поверхности) |
| **R2 — RBAC-паритет read-инструментов** | F-02, F-10, второй путь F-04 | Все три — «проверка есть на одной ветке и нет на другой»; тест-обязательство общее: «чужой идентификатор задан явно» | 1–2 записи |
| **R3 — форма ответов read-поверхности** | F-04, F-05, F-07 | Правки в одних и тех же result-моделях обоих файлов; ломают форму ответа, значит должны выйти одним контрактным шагом с одной записью в `MCP_AGENT_GUIDE`. F-07 закрывает in-scope половину BUG-098 | F-07 → в BUG-098; F-04/F-05 → 1 запись |
| **R4 — экспорт по ADR-0007** | F-03 | Прямо в BUG-096: F-03 не новая запись, а недостающий механизм и третий писатель | в BUG-096 |
| **R5 — мелочи одним PR** | F-06, F-08, F-09, F-11 | Четыре независимые правки, каждая ≤ 10 строк, ни одна не меняет контракт; дешевле одним PR с четырьмя тестами | 1 запись на все |
| **R6 — качество keywords** | F-12 | Единственная находка вне двух файлов; требует пересчёта линковки, то есть прогона, а не правки | 1 запись |

Порядок: R1 → R2 → R4 → R3 → R5; R6 независим.

---

## 8. Передано в #4 / #5

- **#4 (ценность):** severity-карта поверхности — 2 High, 5 Medium, 5 Low, ноль Critical на 9.6k строк, через которые с системой работают и человек, и агент. Оба High — из класса «мультиарендность», и оба не стреляют сегодня ровно по одной причине: на проде не выпущено ни одного не-admin-токена. Это и есть цена входа в любой сценарий с внешними пользователями: продавать доступ второму арендатору нельзя до R1 и R2, а не «после общего security-аудита».
- **#5 (пути развития):** два аргумента при выборе контракта Wave 3. Первый — граница адаптеров: `trigger_*` живут по ADR-0007, экспорт — нет (F-03), и именно несоблюдённая граница дала единственный `fail` формата «фича закончилась, а артефакт недостижим». Второй — дрейф формы ответа: F-04, F-05, F-07 — это три разных проявления одного пробела, отсутствия описанного контракта tool-ответа (в `docs/contracts/` лежат только доменные артефакты). Любая новая поверхность Wave 3 воспроизведёт тот же дрейф, пока контракт ответа не назван.

---

**Размер артефакта.** Лимит plan §6 — ≤2000 слов narrative вне таблиц, заголовков и код-блоков:

````bash
awk 'BEGIN{inb=0} /^```/{inb=!inb;next} inb{next} /^\|/{next} /^#/{next} {print}' docs/notes/CODE_REVIEW_BOT_MCP_2026-08-12.md | wc -w
````

**1315** (эталоны: #1 — 917, #2 — 1436).
