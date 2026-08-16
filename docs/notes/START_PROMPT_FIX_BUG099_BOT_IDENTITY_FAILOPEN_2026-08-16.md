# START PROMPT — BUG-099 bot-арм: исполнитель без личности больше не становится admin

**Дата:** 2026-08-16 · **Сессия:** hardening bot-арма [BUG-099](BUG_LOG.md) после R2 · **Баг:** BUG-099 (High, латентно — MCP-половина `resolved` 2026-08-14; открыт хвост в 34 исполнителях)
**Ветка:** prefix `cursor/fix-bug099-bot-identity-failopen`

**Goal (одной строкой):** вызов bot-исполнителя с `current_user=None` даёт **отказ**, а не `get_default_admin()`; живой путь через `UserResolutionMiddleware` не меняется.

> Это **не** повтор R1. MCP `resolve_mcp_user` закрыт (`#421` → `963b16e`). HTTP-близнец и TTL кэша — уже записанные диспозиции, код не трогать. Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: чтения разрешены; recreate и write — **только по GO**. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) обязателен (app-code: bot authz). Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. Recreate **только** `tg_bot` (профиль `bot`). `tg_parser` не трогать — сдвигает hourly tick (урок R10). BUG-008, HTTP `api/auth.py`, CLI, MCP — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую hardening bot-арма BUG-099 — исполнитель без личности больше не становится admin.
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG099_BOT_IDENTITY_FAILOPEN_2026-08-16.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-099** — MCP закрыта; открыт хвост «34 из 35»; диспозиции HTTP и кэша
> 3. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R1 (out of scope bot-арма), §4 (очередь: это единственный хвост после R3 closeout)
> 4. Исторический промпт R1: [`START_PROMPT_FIX_BUG099_MCP_IDENTITY_FAILOPEN_R1_2026-08-13.md`](START_PROMPT_FIX_BUG099_MCP_IDENTITY_FAILOPEN_R1_2026-08-13.md) — **не** исполнять заново; нужен как граница «что уже сделано»
> 5. `tests/README.md` — default / PR standard; **PR standard обязателен**
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1 (red/green). **Код 34 исполнителей не менять, пока красный тест не падает на сегодняшнем `main`.**
>
> Ориентируйся на имена символов. Если на `main` форма уже не такая — скажи вслух и остановись, не «чини» закрытое.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-16 ~12:20 UTC, после `#440` / хост `302fd09`):

| Факт | Что ждать на 2026-08-16 |
|---|---|
| Очередь | Основная цепочка и параллельные R10–R12 / R6 **закрыты**. Открыты: этот хвост и BUG-008 by design |
| MCP-половина | `resolved` 2026-08-14, `#421` → `963b16e`. UUID miss/error → `PermissionError`. Счётчик `tg_mcp_identity_resolve_total`. Не открывать |
| `main` vs прод-хост | `origin/main` = `302fd09` (`#440`). Хост на том же SHA. Образ контейнеров — R6 `261f178` / `5924dcfc43c3…` (включает R1). Docs-only drift образа нормален |
| Латентность | `list_users` → 7 строк: 1 `admin` (`c59d42b4`, 19 каналов) + 6 `user` (`test_user`, `MOC_User_01`, четыре `zz-retired-probe-*`). Это роли, не mappings. **Сверить** `user_auth_mappings` (telegram / mcp_token) и `BOT_ALLOWED_USERS` на хосте — не утверждать «живого не-admin нет» из одного `list_users`. Если живой не-admin credential уже есть — сказать вслух: High перестаёт быть латентным |
| Пришпиленный дефект | [`tests/test_f4_coverage_supplement.py`](../../tests/test_f4_coverage_supplement.py) `TestDefaultAdminFallback::test_none_user_falls_back_to_default_admin` — `_exec_search(..., current_user=None)` **обязан** вызвать `get_default_admin` и уйти в `allowed_channel_ids is None`. Это и есть баг |
| Счёт | `rg -c 'current_user or await get_default_admin' tg_parser/bot/tools.py` = **34**. `_TOOL_EXECUTORS` = **35**. Тридцать пятый — `_exec_get_llm_config`: личности не читает, fallback нет |
| Workaround | Не выпускать не-admin Telegram / MCP credential, пока этот хвост открыт. После деплоя bot-арма — снять |

---

## 1. Почему эта сессия существует и почему она сейчас

R1 закрыла потерю личности на MCP. На bot тот же дефолт стоит в каждом исполнителе: `user = current_user or await get_default_admin()`. Живой путь это не проявляет — `UserResolutionMiddleware` кладёт `current_user` в `data`, а `handlers.py` называет отказ работать при `current_user is None` «load-bearing, not defensive», потому что иначе write-intent re-issue ушёл бы с правами admin.

Защита сегодня — соглашение вызывающего, не контракт исполнителя. Прямой вызов `_exec_*` / дыра в middleware / будущий второй вход в `execute_tool` снова эскалирует. R2 выстроила дисциплину «вызов с явной личностью» в матрице чужих id; теперь можно снять fail-open, не смешивая его с RBAC-фильтрами.

Очередь remediation пуста. Это последний открытый дефект из ревью, который ещё чинится кодом.

---

## 2. Что установлено (не переоткрывать)

1. **MCP не трогать.** `resolve_mcp_user` fail-closed. Legacy не-UUID → admin. Dev без auth → admin. Счётчик и DB-only старт на месте. Промпт R1 — история.
2. **HTTP-близнец — диспозиция 2026-08-14, код не трогать.** `api/auth.py` + `test_valid_key_not_mapped_falls_back_to_admin` по-прежнему отдают admin на валидный ключ без DB-маппинга. Улики нет. Чинить «по докстрингу» нельзя.
3. **TTL кэша 60 с — принимаем как есть.** После R1 промах кэша на MCP даёт отказ, не эскалацию. На bot резолв идёт через `resolve_user_by_auth("telegram", …)` в middleware — не эта сессия.
4. **Middleware empty-allowlist → admin — не этот баг.** [`UserResolutionMiddleware`](../../tg_parser/bot/middleware.py): `resolve_user_by_auth` вернул `None` и `_legacy_allowed` пуст → `get_default_admin()`. Это явный **dev-режим** (нет allowlist). Не сливать с 34 исполнителями. Пуст ли `BOT_ALLOWED_USERS` на проде — **сверить на хосте**, не верить этой строке: если пуст, middleware сам отдаёт admin, и это другой класс, не scope этой сессии. Если непуст — незарегистрированный Telegram-user получает «не зарегистрированы» и `return None`.
5. **Тридцать пятый исполнитель без fallback — `_exec_get_llm_config`.** Читает процесс-локальный `llm_config.get_all()`, tenant-данных нет, в admin не эскалирует. Не добавлять ни fallback, ни обязательную личность «для симметрии».
6. **CLI `watchlist_cmd` / `workspace_cmd` зовут `get_default_admin` — вне scope.** Не bot-исполнители, не F-01.
7. **Сигнатуру `current_user: CurrentUser \| None = None` не делать обязательной.** `execute_tool` и агент передают `None`. Контракт меняется **поведением**: `None` → отказ, не `get_default_admin()`. Type-level break 35 сигнатур + всех call-site тестов — не эта сессия.
8. **Один хелпер, 34 вызова.** Не копировать `if current_user is None: return {"error": …}` вручную. Имя — `_require_current_user` (или рядом по смыслу) в [`bot/tools.py`](../../tg_parser/bot/tools.py). При `None` бросает **`PermissionError`** (builtin) — тот же класс, что MCP R1 и что уже ловит [`execute_tool`](../../tg_parser/bot/tools.py) как `tool_permission_denied` / `error_class="PermissionError"`. **Не** `PermissionDenied`: его `execute_tool` не выделяет (уходит в широкий `except Exception` → `tool_execution_error`), а `try/except PermissionDenied` у исполнителей стоит только вокруг `assert_*` **после** строки с user. Read-исполнители (`_exec_search` и соседи) этого `except` не имеют. Голый `_exec_*` с `current_user=None` после фикса даёт исключение, не dict — red-тест через `pytest.raises(PermissionError)` или через `execute_tool(...)`. Не гейтить **только** в `execute_tool`: тесты бьют в `_exec_*` напрямую.
9. **Write-intent router остаётся fail-closed.** [`handlers.py`](../../tg_parser/bot/handlers.py) `current_user is None` → не re-issue. После фикса комментарий «executors fall back to get_default_admin» станет ложью — поправить текст. Сам ранний выход оставить: defense-in-depth, snapshot без личности.
10. **Пришпиленный тест — точка red/green.** `TestDefaultAdminFallback` сегодня требует вызов `get_default_admin`. Инвертировать: `pytest.raises(PermissionError)` (или тот же вызов через `execute_tool` → `error_class="PermissionError"`), `get_default_admin` **не** звать, в retrieval не уходить. Не ждать `{"error": …}` от голого `_exec_search`. Не удалять класс — переименовать (например `TestMissingUserIsDenied`).
11. **R2 матрица чужих id не ломается.** Там везде явный `_user()` / `_admin()`. Не «улучшать» RBAC в том же PR.

---

## 3. Scope — строго в этом порядке

### 3.1 Red/green первым, до правок

На сегодняшнем `main` красный тест **обязан упасть** (сейчас зелёный — он кодирует баг):

| Вызов | Сегодня | Должно быть |
|---|---|---|
| `_exec_search({query}, current_user=None)` | `get_default_admin()` + `allowed_channel_ids is None` | `pytest.raises(PermissionError)`; `get_default_admin` не вызван; retrieval не идёт |
| тот же контракт на **каждом** из 34 исполнителей с fallback | admin | `PermissionError`; не dict от голого `_exec_*` |

Параметризовать по именам из `_TOOL_EXECUTORS` минус `get_llm_config`. Не мокать «как удобно»: патч `tg_parser.auth.resolvers.get_default_admin` (как в пришпиленном тесте) + минимальные args, чтобы исполнитель не падал на `KeyError` до проверки личности. Если для write-инструмента нужны `confirm` / `channel_id` — подставить столько, чтобы дойти до `_require_current_user`, не до мутации.

`_exec_get_llm_config(current_user=None)` остаётся валидным чтением конфига — отдельный тест «не регрессировал».

### 3.2 Хелпер и замена 34 строк

`user = current_user or await get_default_admin()` → `user = _require_current_user(current_user)` (хелпер синхронный: `None` проверяется без I/O). Импорт `get_default_admin` из этих 34 функций убрать, если больше не нужен.

`rg -c 'current_user or await get_default_admin' tg_parser/bot/tools.py` после правки = **0**.
`rg -c 'get_default_admin' tg_parser/bot/tools.py` = **0** (или только комментарий / докстринг, если оставите отсылку).

Не менять `execute_tool` как единственный гейт. Дополнительный отказ в `execute_tool` при `current_user is None` и `name != "get_llm_config"` — можно как defense-in-depth, не вместо хелпера.

### 3.3 Комментарий и тест write-intent

[`tests/test_bot_write_intent_trigger_359.py`](../../tests/test_bot_write_intent_trigger_359.py) `test_no_current_user_never_re_issues` — поведение оставить (re-issue не должен случиться). Докстринг «executors fall back to get_default_admin» поправить под новый контракт. Комментарий в `handlers.py` ~2759–2761 — тоже.

### 3.4 Журнал

После зелёного PR standard, в том же PR:

1. **BUG-099** — Status: bot-арм закрыт этой сессией (дата + SHA/PR); MCP-половина уже `resolved` 2026-08-14. Workaround снять. В блоке «что открыто» — как у BUG-103/104. Artifacts — тесты + (после деплоя) runbook.
2. **PLAN §4** — убрать bot-арм из «открыты». §R1 — одна строка, что хвост закрыт.

Runbook — после деплоя, не в этом стартовом промпте. Образец тона: [`BUG099_R1_DEPLOY.md`](../runbooks/BUG099_R1_DEPLOY.md) (там пересоздавали только `mcp`; здесь — только `tg_bot`).

---

## 4. Acceptance criteria

1. `TestDefaultAdminFallback` инвертирован (`pytest.raises(PermissionError)` или `execute_tool` → `error_class="PermissionError"`) и зелёный; параметризация покрывает все 34 имени; `get_llm_config` без личности жив.
2. `rg` из §3.2: fallback-строк 0.
3. Write-intent при `current_user=None` по-прежнему не re-issue.
4. Middleware empty-allowlist и HTTP/MCP/CLI не менялись.
5. Default + **PR standard** зелёные. Точное число — командой из `tests/README.md`, не снимок.
6. BUG-099 и PLAN §4 обновлены.
7. Прод-smoke **после деплоя и только по GO**: живой admin в Telegram по-прежнему получает ответ бота (например `/start` или «кто я»). Не-admin credential для smoke не заводить. Recreate только `tg_bot`.

---

## 5. Ограничения (CRITICAL)

- Не трогать `resolve_mcp_user`, `create_mcp_server`, счётчик R1.
- Не трогать `api/auth.py` и `test_valid_key_not_mapped_falls_back_to_admin`.
- Не трогать `UserResolutionMiddleware` empty-allowlist → admin.
- Не трогать CLI `get_default_admin`.
- Не делать `current_user: CurrentUser` обязательным в сигнатурах.
- Не добавлять fallback или admin-гейт в `_exec_get_llm_config`.
- Не «улучшать» RBAC / R2-матрицу / форму ответов.
- Не recreate `tg_parser` / `mcp`.
- Не выпускать не-admin credential «чтобы проверить».
- Не править `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Коммит / PR / прод-запись — по явному запросу владельца.
- PR standard обязателен.

---

## 6. Финальный ответ сессии

Одним сообщением: сколько исполнителей перестали звать `get_default_admin`; что делает `_exec_get_llm_config` без личности; результаты default и PR standard; трогали ли middleware/HTTP/MCP (должно быть нет). После деплоя — отдельно: SHA образа `tg_bot` и что живой admin-чат ответил. Если red на `main` не воспроизводится — что именно уже не так, и стоп.

---

## 7. Ссылки

- [BUG-099](BUG_LOG.md); F-01 — [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](CODE_REVIEW_BOT_MCP_2026-08-12.md).
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R1, §4.
- R1 (закрыта): [`START_PROMPT_FIX_BUG099_MCP_IDENTITY_FAILOPEN_R1_2026-08-13.md`](START_PROMPT_FIX_BUG099_MCP_IDENTITY_FAILOPEN_R1_2026-08-13.md), [`BUG099_R1_DEPLOY.md`](../runbooks/BUG099_R1_DEPLOY.md).
- `tg_parser/bot/tools.py` — `_require_current_user` (новый), 34 `_exec_*`, `_TOOL_EXECUTORS`, `execute_tool`.
- `tg_parser/bot/middleware.py` — `UserResolutionMiddleware` (не менять).
- `tg_parser/bot/handlers.py` — write-intent, комментарий ~2759.
- `tg_parser/bot/tools.py` `execute_tool` — ловит `PermissionError`, не `PermissionDenied`.
- `tg_parser/auth/ownership.py` — `PermissionDenied` (только `assert_*` после того, как user уже есть).
- `tests/test_f4_coverage_supplement.py` — пришпиленный fallback.
- `tests/test_bot_write_intent_trigger_359.py` — `test_no_current_user_never_re_issues`.
- `tests/test_bug100_bug101_explicit_id_matrix.py` — не ломать.
