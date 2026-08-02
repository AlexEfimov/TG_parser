# START PROMPT — BUG-087: redact secret-bearing tool args at INFO (`agent_tool_call` + `fsm_confirm_execute`)

**Дата:** 2026-08-02 · **Тип:** red→green privacy slice (bot logging only) · **Ветка:** `fix/bug087-log-redaction` (от актуального `main`)  
**SoT:** [`BUG_LOG.md`](BUG_LOG.md) § **BUG-087** (filed 2026-07-31; second site widened same day).  
**Предшественник:** [#359](https://github.com/AlexEfimov/TG_parser/issues/359) / ADR-0020 — закрыты (merge, deploy, 3 e2e, 24h watch PASS). Этот баг **не** регрессия #359; вскрыт при adjudication Bugbot-находки про FSM.

**Goal (одной строкой):** один общий redaction-helper на deny-list secret-arg'ов, потребляемый **обоими** INFO-сайтами (`agent_tool_call` и `fsm_confirm_execute`), так чтобы сырой `add_user_auth.identifier` никогда не попадал в лог-пайплайн, а forensic-ценность BUG-002/004 (остальные args видны) сохранялась; закрепить privacy-тестами на **оба** события + declaration-tripwire.

---

## Opener (вставить в новый чат Cursor)

> Стартую `fix/bug087-log-redaction` (BUG-087).
>
> Прочитай целиком `docs/notes/START_PROMPT_BUG087_LOG_REDACTION_2026-08-02.md`, затем исполни §1–§8 ровно.
>
> Scope: bot logging privacy only.
> 1. sync `main`, ветка `fix/bug087-log-redaction`;
> 2. общий helper (deny-list) → оба call site'а `agent_tool_call` и `fsm_confirm_execute`;
> 3. red→green тесты: секрет отсутствует в **обоих** событиях; tripwire на декларации;
> 4. BUG_LOG § BUG-087 → `resolved` + CHANGELOG Unreleased;
> 5. commit + push + PR в `main`; дождаться зелёного CI.
>
> **Hard OUT:** BUG-088 (`normalized`), FSM/`MemoryStorage` encryption, `fsm_pagination_execute`, `message=str(exc)` audit, Grafana/infra, prod SSH/deploy, `pyproject.toml` / `requirements.txt`, `docs/methodology/**`, новых deps, DEBUG-дамп сырых args (не возвращать `b0dcef3`-split).
> **Commit/PR — да, это и есть задача** (явный запрос owner'а через этот промпт). Push в `main` напрямую — нет; только через PR.
> **Deploy** после merge — отдельное решение owner'а (не hotfix; bot re-create по BUG-078, если деплоят).

---

## 0. Контекст (не переоткрывать #359)

| Факт | Статус |
|---|---|
| #359 merge + deploy + 3 e2e + 24h watch | ✅ закрыто; повторный deploy **не** нужен ради этого слайса |
| CI коммита `73b4e2c` (закрытие watch) | ✅ все check-runs `success` (проверено 2026-08-02) |
| Grafana 11→13 | ✅ уже в `main` ([PR #361](https://github.com/AlexEfimov/TG_parser/pull/361), merge `b81c658`) — **не** трогать |
| BUG-087 severity | Medium — credential hygiene; admin-only `add_user_auth`; логи пока не ship'ятся off-host |
| BUG-088 | `open`, **отдельный** слайс после этого; disjoint mechanism |

**Почему два сайта — один номер / один PR.** Redact только `agent_tool_call` оставляет credential на confirm-turn через `fsm_confirm_execute`. Half-fix = ложное закрытие. См. BUG_LOG § «Second call site» / «Record-keeping decision».

**Почему deny-list, не allow-list / не `arg_keys`-only.** Линии `agent_tool_call` / `fsm_confirm_execute` существуют ради forensics BUG-002/004 (`remove_channel args={'channel_id':…,'confirm':true}`). Перевод на keys-only уничтожил бы эту ценность. Deny-list редактирует только известные secret-ключи; всё остальное остаётся.

**История уровней (не переписывать заново):** `b0dcef3` (F9 Phase 1) demoted args → DEBUG; `8332aa3` вернул на INFO ради forensics. Redaction — примирение security + forensics, не откат к DEBUG.

---

## 1. Pre-flight

```bash
git checkout main
git pull --ff-only origin main
git status   # ожидаемо: clean (или только этот START_PROMPT untracked / уже закоммичен)
git rev-parse --short HEAD
```

**Якорь при подготовке промпта (2026-08-02):** `main` ≥ `b81c658` (Grafana chore merged). Worktree может содержать этот файл как untracked — ок.

Подтвердить оба живых call site'а (номера строк — ориентир; якорь — содержимое):

```bash
rg -n 'logger\.info\(\s*"agent_tool_call"|logger\.info\(\s*"fsm_confirm_execute"' tg_parser/bot/
# ожидаемо:
#   agent.py  — args=tool_args
#   handlers.py — args=confirmed_args
```

Прочитать SoT **целиком** перед кодом:
- [`BUG_LOG.md`](BUG_LOG.md) § BUG-087 (Proposed fix + Precedent + Second call site)
- Прецедент нормы keys-only: `write_intent_set` / `TestWriteIntentLogPrivacy` в [`tests/test_bot_write_intent_trigger_359.py`](../../tests/test_bot_write_intent_trigger_359.py)
- Tripwire-прецедент: `TestPreviewSuppressingArgRegistryIsComplete` в [`tests/test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py)
- Реальный secret-arg: `add_user_auth` → **`identifier`** ([`tools.py`](../../tg_parser/bot/tools.py) declaration + `hash_credential` в executor) — **не** выдуманное имя `credential`
- Форма redact-прецедента (API, **не** импортировать в bot): `_redacted_key_prefix` в [`tg_parser/api/auth.py`](../../tg_parser/api/auth.py) — первые 4 + `****`, короткие → `****`

---

## 2. Ветка

```bash
git checkout -b fix/bug087-log-redaction
```

---

## 3. Реализация

### 3.1 Общий helper (один модуль, два consumer'а)

Рекомендуемое место: новый [`tg_parser/bot/log_redaction.py`](../../tg_parser/bot/log_redaction.py) (bot-local; **не** импортировать `tg_parser.api.auth` — hexagonal boundary / ADR-0004).

Контракт (имена можно уточнить, семантика — нет):

```python
# Pseudocode — shape, not final API
_SECRET_ARGS_BY_TOOL: dict[str, frozenset[str]] = {
    "add_user_auth": frozenset({"identifier"}),
}

def redact_tool_args(tool_name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow copy safe for INFO logs. Never drop a secret key
    silently — replace its value with a redacted forensic token
    (prefix and/or length). Non-secret keys pass through unchanged."""
    ...
```

**Правила:**
1. **Deny-list per tool**, не глобальный strip по имени ключа. Сегодня единственный secret-bearing arg в bot declarations — `add_user_auth.identifier`. Соседние admin-tools **не** имеют поля `identifier` вовсе (`register_user` / `update_user` / `remove_user_auth` — проверено 2026-08-02 против `TOOL_DECLARATIONS`); формулировка BUG_LOG «несут identifiers, но не secrets» устарела относительно деклараций — не копировать как факт о коде. Per-tool deny-list всё равно обязателен: будущий `*.identifier` / `*.token` не должен редактироваться «потому что имя совпало».
2. Значение secret-ключа → `_redacted_key_prefix`-стиль: `len < 8` → `****` (или `len=N` без содержимого); иначе первые 4 + `****`. Это **redaction, не криптографическая необратимость** — короткий prefix коррелируем; не обещать «non-reversible». Ключ **остаётся** в dict.
3. Не мутировать исходный `tool_args` / `confirmed_args` in-place — shallow copy **только для лога**. `execute_tool(...)` получает **оригинал** (пин в §4.1).
4. Неизвестный tool / пустой deny-set → args as-is (forensic default).
5. **Не** возвращать raw args отдельной строкой на `logger.debug` (`agent_tool_call_args` из `b0dcef3`): при `LOG_LEVEL=DEBUG` дыра откроется снова.

### 3.2 Call sites (оба обязательны)

| Сайт | Файл | Было | Стало |
|---|---|---|---|
| (1) | [`agent.py`](../../tg_parser/bot/agent.py) ~L424–429 | `args=tool_args` | `args=redact_tool_args(tool_name, tool_args)` |
| (2) | [`handlers.py`](../../tg_parser/bot/handlers.py) ~L982–987 | `args=confirmed_args` | `args=redact_tool_args(tool_name, confirmed_args)` |

Комментарий BUG-002/004 над `agent_tool_call` **сохранить**, добавив одну строку: secret-bearing keys redacted (BUG-087); non-secret values remain for forensics.

### 3.3 Что НЕ менять в этом слайсе

| Вне scope | Почему |
|---|---|
| **BUG-088** `fsm_confirm_unknown_token` / `normalized` | Free-text; deny-list по arg names не достаёт. Отдельный слайс, форма (d)+(a) уже рекомендована в BUG_LOG |
| Сырой `identifier` в FSM / `pending_action` / `pending_write_intent` | RAM/`MemoryStorage`, TTL 5 мин; кандидат на отдельный slice (Bugbot/#359 finding 5) |
| `fsm_pagination_execute` full `args` | Read-only cursors; zero known credential path. Cheap consistency **после** helper'а — только если owner явно расширит scope |
| `tool_validation_error` / `tool_permission_denied` `message=str(exc)` | WARNING; другой механизм; гигиена после 087→088 |
| Downgrade всего `args` обратно на DEBUG | Откат forensics; противоречит Proposed fix |
| Allow-list / только `arg_keys` на этих двух событиях | Уничтожает BUG-002/004 forensic value |

---

## 4. Тесты (red → green)

Новый класс (предпочтительно рядом с confirm / write-intent privacy):
- либо [`tests/test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py),
- либо тонкий [`tests/test_bot_log_redaction_087.py`](../../tests/test_bot_log_redaction_087.py).

### 4.1 Privacy pin — оба события (обязательно)

В духе `TestWriteIntentLogPrivacy`, scoped на `{"agent_tool_call", "fsm_confirm_execute"}`.

**Не обязателен один тяжёлый e2e через GeminiAgent.** Достаточно (и предпочтительно) двух тонких unit-тестов + общий assert-хелпер:

1. **Site (1):** вызвать путь, который доходит до `logger.info("agent_tool_call", …)` с `add_user_auth` + `identifier=<secret>` (мок agent loop / прямой вызов с `capture_logs`) — **или** unit на helper + source/import pin, что `agent.py` зовёт тот же `redact_tool_args`.
2. **Site (2):** то же для `_handle_confirmation_response` affirmative branch → `fsm_confirm_execute` (прецедент fixtures: [`tests/test_bot_admin_confirm_flow.py`](../../tests/test_bot_admin_confirm_flow.py) уже знает `add_user_auth` preview/confirm; при необходимости подключить `capture_logs`).
3. На каждом событии: `assert secret not in json.dumps(record, …)`; ключ `identifier` **присутствует**; значение — redacted token.
4. Meta-пин half-fix trap: один тест (или parametrize) явно требует, что **оба** event name покрыты suite'ом (например, константа `_BUG087_EVENTS` и assert set equality против собранных покрытых имён). Один сайт зелёный / второй забыт → red.
5. **Executor pin:** после log-call `execute_tool` / хендлер всё ещё видит **сырой** `identifier` (redact только для лога). Иначе «починили лог» ценой сломанного `hash_credential`.

Имя аргумента в фикстуре — **`identifier`**, не выдуманный `credential` (урок #359 finding 9).

### 4.2 Forensic pin — non-secret tool не кастрируется

`redact_tool_args("remove_channel", {"channel_id": "ch_x", "confirm": True})` → `channel_id` value всё ещё `"ch_x"`. Иначе deny-list случайно стал allow-list.

### 4.3 Tripwire — declaration registry (обязательно)

В духе `TestPreviewSuppressingArgRegistryIsComplete`:

- Явный реестр `_SECRET_ARGS_BY_TOOL` не вакуумен: `assert "identifier" in _SECRET_ARGS_BY_TOOL["add_user_auth"]`.
- Скан **parameter** `description` в `TOOL_DECLARATIONS` (не tool-level description целиком — у `add_user_auth` фраза «hashed automatically» есть и на уровне tool, что размывает привязку к параметру): если description параметра содержит `"Raw credential"` **или** `"hashed automatically"`, пара `(tool, param)` **обязана** быть в реестре — иначе CI red.
- Дополнительный name-heuristic (`password` / `secret` / `api_key` как **имена параметров**) — опционален; **не** включать голое `token` без привязки к description (ложные срабатывания / шум). Не требовать регистрации всех будущих `identifier` подряд (см. §3.1 п.1).

### 4.4 Команда gate

```bash
.venv/bin/python -m pytest \
  tests/test_bot_log_redaction_087.py \
  tests/test_bot_confirm_flow.py \
  tests/test_bot_write_intent_trigger_359.py \
  -q
# + ruff check на изменённых файлах
```

Режим — default suite из [`tests/README.md`](../../tests/README.md). Postgres не обязателен, если тесты pure-unit с `capture_logs`.

---

## 5. Docs

| Файл | Правка |
|---|---|
| [`BUG_LOG.md`](BUG_LOG.md) § BUG-087 | Status → `resolved` + короткий Update: helper path, оба сайта, тесты, PR/commit |
| [`CHANGELOG.md`](../../CHANGELOG.md) `## [Unreleased]` | Краткая Security/Fixed строка про BUG-087 redaction на двух bot INFO sites |
| Runbook [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) | **Обязательно:** строка таблицы про `fsm_confirm_execute` сейчас говорит «⚠️ **полные значения** … на `add_user_auth` в лог контейнера попадает сырой `identifier`» (~L449). После фикса переписать: args redacted для secret-bearing keys (BUG-087); caveat «не тащить в заметки» можно оставить мягче или сузить до BUG-088 `normalized`. Исторические deploy-record абзацы **не** ретушировать |
| BUG-088 / Grafana START_PROMPT | **не** трогать |

---

## 6. Diff-gate перед коммитом

```bash
git diff
git status
```

**Ожидаемо примерно:**
- `tg_parser/bot/log_redaction.py` (новый) — или согласованное место helper'а
- `tg_parser/bot/agent.py` — один call site
- `tg_parser/bot/handlers.py` — один call site
- tests (новый или расширенный файл)
- `docs/notes/BUG_LOG.md`, `CHANGELOG.md`
- этот START_PROMPT (если ещё не в git)

Не коммитить `.env`, секреты, unrelated untracked.

---

## 7. Commit

```bash
git add tg_parser/bot/log_redaction.py tg_parser/bot/agent.py tg_parser/bot/handlers.py \
  tests/test_bot_log_redaction_087.py docs/notes/BUG_LOG.md CHANGELOG.md \
  docs/notes/START_PROMPT_BUG087_LOG_REDACTION_2026-08-02.md
# подправить список файлов под фактический diff

git commit -m "$(cat <<'EOF'
fix(bot): redact secret tool args at INFO (BUG-087)

Shared deny-list helper for agent_tool_call and fsm_confirm_execute so
add_user_auth.identifier never lands in logs while non-secret args keep
BUG-002/004 forensic value. Privacy pins cover both events; declaration
tripwire blocks silent reopen.
EOF
)"
```

---

## 8. Push + PR

```bash
git push -u origin fix/bug087-log-redaction
gh pr create --title "fix(bot): redact secret tool args at INFO (BUG-087)" --body "$(cat <<'EOF'
## Summary
- Shared deny-list redaction helper for bot INFO logs: `agent_tool_call` and `fsm_confirm_execute`.
- `add_user_auth.identifier` redacted (prefix/length); key retained for forensics; other args unchanged.
- Privacy tests assert the secret is absent from **both** events; declaration tripwire prevents silent reopen.
- Resolves BUG-087 in `BUG_LOG.md` (not a GitHub issue — do **not** use `Closes #N` unless an issue exists). Does **not** touch BUG-088 (`normalized`), FSM-in-memory credential storage, or `fsm_pagination_execute`.

## Test plan
- [ ] Targeted pytest (redaction + confirm-flow + write-intent privacy) green
- [ ] `ruff check` on touched files clean
- [ ] CI on this PR green
- [ ] Manual review: `json.dumps` of a captured `add_user_auth` pair shows redacted `identifier` on both events; `remove_channel` still shows `channel_id`

EOF
)"
```

Дождаться зелёного CI. Merge — по статусу owner'а.

**Deploy (не часть этого чата, если owner не попросил):** после merge на VPS — `git pull` + rebuild image + **re-create** `tg_parser_bot` (BUG-078: не `restart`). `tg_parser` / `tg_parser_mcp` не обязательны. Миграций нет.

---

## 9. Definition of Done

| # | Критерий |
|---|---|
| 1 | Один helper, **два** consumer'а; нет двух независимых redact-копий |
| 2 | Сырой `identifier` отсутствует в INFO-логах обоих событий; ключ присутствует в redacted виде |
| 3 | Non-secret args (напр. `channel_id`) по-прежнему видны |
| 4 | Privacy-тесты покрывают **оба** event name; tripwire non-vacuous |
| 5 | BUG_LOG BUG-087 → `resolved`; CHANGELOG Unreleased обновлён |
| 6 | PR в `main`, CI green |
| 7 | BUG-088 / FSM encryption / `str(exc)` / pagination — **не** смешаны в этот PR |

**Hard OUT reminder:** methodology workspace, `docs/methodology/**`, `pyproject.toml`, `requirements.txt`, prod SSH без явной просьбы, merge BUG-088 «заодно».

---

## 10. После этого слайса (не делать здесь)

1. **BUG-088** — `fsm_confirm_unknown_token`: убрать полный `normalized`; форма **(d)+(a)** из BUG_LOG (closed-vocabulary + length/token_count + поле `tool`); отдельный privacy + diagnostic тест.
2. Опциональная гигиена: дублирующийся номер BUG-081 (оба уже `resolved` — только numbering); audit `message=str(exc)` в WARNING.
3. Опционально: протянуть тот же helper на `fsm_pagination_execute` ради consistency.
4. Отдельный slice: не хранить/шифровать secret values в FSM для всего confirm-протокола.
