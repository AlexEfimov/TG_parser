# START PROMPT — BUG-088: `fsm_confirm_unknown_token` free-text INFO hygiene

**Дата:** 2026-08-04 · **Тип:** red→green privacy slice (bot logging only) · **Ветка:** `fix/bug088-unknown-token-log` (от актуального `main`)  
**SoT:** [`BUG_LOG.md`](BUG_LOG.md) § **BUG-088** (filed 2026-07-31).  
**Plan:** [`PLAN_SESSION_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md`](PLAN_SESSION_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md) — owner decisions LOCKED там; этот промпт исполняет план.  
**Предшественник:** BUG-087 ([PR #362](https://github.com/AlexEfimov/TG_parser/pull/362)) — deny-list на tool `args`; этот слайс — disjoint mechanism (free-text).

**Goal (одной строкой):** на единственном INFO call site `fsm_confirm_unknown_token` убрать сырой `normalized=<весь ответ пользователя>`, заменить на closed-vocabulary `verdict` + shape-facts + `tool`, закрепить privacy+diagnostic тестами; BUG_LOG → `resolved`.

---

## Opener (вставить в новый чат Cursor)

> Стартую `fix/bug088-unknown-token-log` (BUG-088).
>
> Прочитай целиком `docs/notes/START_PROMPT_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md` и план `docs/notes/PLAN_SESSION_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md`, затем исполни §1–§8 ровно.
>
> Scope: bot logging privacy on **one** INFO site.
> 1. sync `main`, ветка `fix/bug088-unknown-token-log`;
> 2. helper `confirm_unknown_log.py` — shape **(d)+(a)** per plan §2–§3;
> 3. call site `handlers.py` `fsm_confirm_unknown_token` — без `normalized`;
> 4. red→green тесты: secret absent + event exists + key-set literal + near-miss «дя»;
> 5. BUG_LOG § BUG-088 → `resolved` + CHANGELOG + runbook row;
> 6. commit + push + PR в `main`; дождаться зелёного CI.
>
> **Hard OUT:** `fsm_pagination_execute`, `tool_validation_error` / `message=str(exc)`, FSM/`MemoryStorage` encryption, DEBUG dump сырого текста, truncation/hash shapes, BUG-087 revisit, Grafana/infra, prod SSH/deploy, T7/Event B, Wave 3, `pyproject.toml` / `requirements.txt`, `docs/methodology/**`, новых deps.
> **Commit/PR — да, это и есть задача** (явный запрос owner'а через этот промпт). Push в `main` напрямую — нет; только через PR.
> **Deploy** после merge — отдельное решение owner'а (bot re-create по BUG-078, если деплоят).

---

## 0. Контекст (не переоткрывать)

| Факт | Статус |
|---|---|
| BUG-087 | ✅ resolved; helper `tg_parser/bot/log_redaction.py` — **не** расширять под free-text |
| #359 / ADR-0020 | ✅ closed; BUG-088 **не** регрессия (`66e8297`) |
| Severity | Medium — free-text на любом ConfirmFlow; шире популяции, чем admin-only 087 |
| Shape | **LOCKED: (d)+(a)** — см. plan §2. Не (b)/(c)/DEBUG-split |
| Pagination / WARNING validators | OUT — plan §7 |

**Почему поле нельзя просто удалить.** Оно существует ради BUG-032: оператор должен видеть *почему* токен отвергнут (синоним / typo / paste). Пустой event = ложное «privacy pass». Тесты обязаны требовать, что событие **существует**.

**Почему не deny-list / не truncation.** Словарь user text открыт; truncation утекает короткие секреты и correlatable prefix. Closed verdict + length/flags — единственный shape с нулевым value exposure и сохранением near-miss diagnosability.

---

## 1. Pre-flight

```bash
git checkout main
git pull --ff-only origin main
git status
git rev-parse --short HEAD
```

**Якорь при подготовке промпта (2026-08-04):** `main` @ `0b1a18a` (Prometheus v3 merged). Worktree может содержать этот START_PROMPT / PLAN как untracked — ок.

**CORRECTION 2026-08-04 (при коммите заметок в [PR #366](https://github.com/AlexEfimov/TG_parser/pull/366)).** Якорь выше устарел между подготовкой промпта и стартом сессии: в `main` успел смержиться BUG-089 ([PR #365](https://github.com/AlexEfimov/TG_parser/pull/365)), поэтому фактический `main` на момент ветвления — `7e37907`, а не `0b1a18a`. Исходная строка оставлена как есть; на исполнение расхождение не повлияло, так как pre-flight выше делает `git pull --ff-only origin main` и берёт актуальный `main`. Читать `0b1a18a` как «anchor at authoring time», не как требование к базе ветки.

Подтвердить живой call site:

```bash
rg -n 'fsm_confirm_unknown_token' tg_parser/bot/handlers.py
# ожидаемо ~L1084–1088:
#   logger.info("fsm_confirm_unknown_token", chat_id=..., normalized=" ".join(text.split()).casefold())
```

Прочитать SoT **перед кодом:**
- [`BUG_LOG.md`](BUG_LOG.md) § BUG-088 — Proposed fix (d)+(a), Adjacent excluded, Left open (теперь locked в plan)
- Plan: [`PLAN_SESSION_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md`](PLAN_SESSION_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md) §2–§3
- Existing UX pins: `TestHandleConfirmationResponseUnknownToken` в [`tests/test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py)
- Privacy capture precedent: [`tests/test_bot_log_redaction_087.py`](../../tests/test_bot_log_redaction_087.py) (`structlog.testing.capture_logs`)
- Whitelists: `AFFIRMATIVE_TOKENS` / `NEGATIVE_TOKENS` в [`handlers.py`](../../tg_parser/bot/handlers.py)
- Runbook row: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) ~`fsm_confirm_unknown_token`

---

## 2. Ветка

```bash
git checkout -b fix/bug088-unknown-token-log
```

---

## 3. Реализация

### 3.1 Helper module

Новый [`tg_parser/bot/confirm_unknown_log.py`](../../tg_parser/bot/confirm_unknown_log.py).

**Не** класть в `log_redaction.py` — другой механизм (shape summary vs arg deny-list).  
**Не** импортировать `tg_parser.api.*` (hexagonal / ADR-0004).  
Stdlib only (нет новых deps). Levenshtein — простая локальная функция, max distance 1.

Контракт (имена можно уточнить, семантика — нет):

```python
# Pseudocode — shape, not final API

_UNKNOWN_CONFIRM_LOG_KEYS: frozenset[str] = frozenset({
    "chat_id", "tool", "verdict", "length", "token_count",
    "is_single_token", "has_digits", "has_punct",
})

_VERDICTS: frozenset[str] = frozenset({
    "non_text",
    "near_miss_affirmative",
    "near_miss_negative",
    "single_token_unlisted",
    "multi_token_free_text",
})

def normalize_confirm_reply(text: str | None) -> str:
    """Same normalize as classify_confirmation_token: split/join + casefold."""
    ...

def classify_unknown_confirm_verdict(normalized: str) -> str:
    """Closed vocabulary only — never echo user bytes."""
    ...

def unknown_confirm_log_fields(
    text: str | None,
    *,
    chat_id: int,
    tool: str | None,
) -> dict[str, object]:
    """Kwargs for logger.info('fsm_confirm_unknown_token', **fields).
    Must NOT contain normalized/text/message/raw/hash/prefix of user content.
    Key set must equal _UNKNOWN_CONFIRM_LOG_KEYS.
    """
    ...
```

**Verdict rules (plan §3.1):**
1. Normalize first.
2. `non_text` — empty **or** no alphanumeric character.
3. If `token_count >= 2` → `multi_token_free_text` (no edit-distance).
4. If single token: near-miss vs `AFFIRMATIVE_TOKENS` (edit distance ≤ 1 **or** equal after stripping non-alnum) → `near_miss_affirmative`; else same vs `NEGATIVE_TOKENS` → `near_miss_negative`; else `single_token_unlisted`.
5. Import token sets from `handlers` **или** передать их аргументом — избегай циклов импорта. Предпочтительно: импортировать `AFFIRMATIVE_TOKENS` / `NEGATIVE_TOKENS` из `handlers` только если нет cycle; иначе вынести frozensets в маленький `confirm_tokens.py` **только если** cycle реален. На практике `handlers` уже тяжёлый — helper должен импортировать tokens из `handlers`, а `handlers` импортирует helper: **это cycle**. Решение: либо перенести оба frozenset'а в `confirm_tokens.py` (минимальный move + update imports в handlers/tests), либо передать tokens в `classify_*` из call site. **Предпочтение сессии:** тонкий `confirm_tokens.py` с двумя frozenset + re-export/import из `handlers` (handlers остаётся каноническим публичным местом через `from tg_parser.bot.confirm_tokens import AFFIRMATIVE_TOKENS` **или** handlers сохраняет определения и helper получает их параметром с default из lazy import). Самый простой без большого move: **helper принимает optional token sets; call site передаёт `AFFIRMATIVE_TOKENS`/`NEGATIVE_TOKENS`**. Ещё проще для тестов: helper импортирует tokens через локальный import внутри функции. Выбери вариант без cycle и без широкого churn — предпочтительно **local import inside classify** или **pass-through from call site**.

**Shape flags:**
- `length = len(normalized)`
- `token_count = 0 if not normalized else len(normalized.split())`
- `is_single_token = token_count == 1`
- `has_digits = any(ch.isdigit() for ch in normalized)`
- `has_punct = any(not (ch.isalnum() or ch.isspace()) for ch in normalized)`

### 3.2 Call site (обязательно один)

[`tg_parser/bot/handlers.py`](../../tg_parser/bot/handlers.py) — блок unknown-token (~L1078–1093):

```python
logger.info(
    "fsm_confirm_unknown_token",
    **unknown_confirm_log_fields(
        text,
        chat_id=message.chat.id,
        tool=pending_action.get("tool_name"),
    ),
)
```

- Удалить `normalized=...`.
- Сохранить BUG-032 комментарий; добавить одну строку: raw reply never at INFO (BUG-088); verdict+shape preserve diagnosability.
- User-facing `message.answer(...)` — **bit-for-bit** без изменений.
- FSM clear / execute — не трогать.

### 3.3 Что НЕ менять

| Вне scope | Почему |
|---|---|
| `log_redaction.py` / BUG-087 sites | Уже закрыты; другой механизм |
| `fsm_pagination_execute` | Read-only; plan Hard OUT |
| `tool_validation_error` `message=str(exc)` | WARNING; другой механизм |
| `UnknownConfirmationToken.__init__` message | Не log-site; не raised in prod |
| DEBUG line with raw text | Отвергнутый precedent `b0dcef3`/`8332aa3` |
| Truncation / hash | Отвергнутые shapes (b)/(c) |
| Confirm classifier / whitelists contents | Не эта задача |

---

## 4. Тесты (red → green)

Новый [`tests/test_bot_confirm_unknown_log_088.py`](../../tests/test_bot_confirm_unknown_log_088.py).

Fixtures: копируй тонкий pattern из `test_bot_log_redaction_087.py` / `TestHandleConfirmationResponseUnknownToken` (`_make_state`, `_make_message`, armed `ConfirmFlow` + `pending_action`).

### 4.1 Privacy pin (обязательно)

1. Armed ConfirmFlow, `pending_action.tool_name="remove_channel"`.
2. Reply = secret-shaped string, e.g. `"sk-live-ABCDEFGHijklmnop123456"`.
3. `capture_logs` around `_handle_confirmation_response`.
4. Assert:
   - ровно одна запись `event == "fsm_confirm_unknown_token"` (или ≥1 и взять её);
   - `secret not in json.dumps(records, default=str)`;
   - `"normalized" not in record`;
   - `"text" not in record` / `"message" not in record`;
   - `set(record) - {"event", "log_level", ...structlog extras...}` покрывает ожидаемые ключи — проще: для каждого key из `_UNKNOWN_CONFIRM_LOG_KEYS` `assert key in record`, и `normalized` absent.

### 4.2 Key-set / tool pin

- `record["tool"] == "remove_channel"`.
- Export `_UNKNOWN_CONFIRM_LOG_KEYS` (или публичный `UNKNOWN_CONFIRM_LOG_KEYS`) и pin: business-keys ⊆ record keys; no `normalized`.

### 4.3 Diagnostic pins

| Input | Expected `verdict` |
|---|---|
| `"дя"` | `near_miss_affirmative` |
| `"ладно потом"` | `multi_token_free_text` |
| `"🚀"` / emoji-only | `non_text` |
| длинный single-token с цифрами | `single_token_unlisted`, `has_digits is True`, `length >= 20` |

Unit-тесты напрямую на `classify_unknown_confirm_verdict` / `unknown_confirm_log_fields` допустимы и предпочтительны для таблицы; handler-level privacy pin (§4.1) обязателен отдельно.

### 4.4 Regression — existing suite

```bash
.venv/bin/python -m pytest \
  tests/test_bot_confirm_unknown_log_088.py \
  tests/test_bot_confirm_flow.py \
  tests/test_bot_log_redaction_087.py \
  -q
# + ruff check на изменённых файлах
```

`TestHandleConfirmationResponseUnknownToken` должен остаться зелёным без правок (или с минимальной правкой, если что-то assert'ило на log — сейчас не assert'ит).

---

## 5. Docs

| Файл | Правка |
|---|---|
| [`BUG_LOG.md`](BUG_LOG.md) § BUG-088 | Status → `resolved`; Update: shape (d)+(a), module path, key set, tests file, PR/commit; отметить Adjacent still excluded |
| [`CHANGELOG.md`](../../CHANGELOG.md) `## [Unreleased]` | **отдельная** Security/Fixed секция (не внутрь Infra/F11): BUG-088 — `fsm_confirm_unknown_token` больше не логирует raw reply |
| [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) | Строка таблицы `fsm_confirm_unknown_token`: заменить caveat про `normalized` на описание новых полей; убрать «Дословно в заметки не тащить» **или** смягчить до historical. Строка `fsm_confirm_execute` — если всё ещё указывает на BUG-088 `normalized`, обновить cross-link. Исторические deploy-абзацы **не** ретушировать |
| Plan + этот START_PROMPT | коммитить в том же PR |

---

## 6. Diff-gate перед коммитом

```bash
git diff
git status
```

**Ожидаемо примерно:**
- `tg_parser/bot/confirm_unknown_log.py` (новый)
- `tg_parser/bot/handlers.py` — call site (+ возможен минимальный import)
- `tests/test_bot_confirm_unknown_log_088.py` (новый)
- `docs/notes/BUG_LOG.md`, `CHANGELOG.md`, runbook row
- `docs/notes/PLAN_SESSION_BUG088_…` + этот START_PROMPT

Не коммитить `.env`, секреты, unrelated untracked (в т.ч. старый Grafana START_PROMPT, если всё ещё висит).

---

## 7. Commit

```bash
git add tg_parser/bot/confirm_unknown_log.py tg_parser/bot/handlers.py \
  tests/test_bot_confirm_unknown_log_088.py \
  docs/notes/BUG_LOG.md CHANGELOG.md \
  docs/runbooks/F5C_DEPLOY_AND_WATCH.md \
  docs/notes/PLAN_SESSION_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md \
  docs/notes/START_PROMPT_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md
# подправить список под фактический diff

git commit -m "$(cat <<'EOF'
fix(bot): stop logging raw reply on fsm_confirm_unknown_token (BUG-088)

Replace normalized=<full user text> with a closed-vocabulary verdict plus
shape facts (length/token_count/flags) and the pending tool name. Preserves
BUG-032 diagnosability (near-miss typos, paste-vs-synonym shape) without
putting user bytes on the INFO pipeline.
EOF
)"
```

---

## 8. Push + PR

```bash
git push -u origin fix/bug088-unknown-token-log
gh pr create --title "fix(bot): BUG-088 unknown-token log hygiene" --body "$(cat <<'EOF'
## Summary
- Close BUG-088: `fsm_confirm_unknown_token` no longer logs the raw user reply at INFO.
- Shape **(d)+(a)** from BUG_LOG: closed `verdict` + length/token_count/class flags + missing `tool` field.
- Privacy + diagnostic pins in `tests/test_bot_confirm_unknown_log_088.py`; runbook row updated.

## Test plan
- [ ] `pytest tests/test_bot_confirm_unknown_log_088.py tests/test_bot_confirm_flow.py tests/test_bot_log_redaction_087.py -q` green
- [ ] Secret-shaped unknown reply → event exists, secret absent from captured logs, no `normalized` key
- [ ] `"дя"` → `verdict=near_miss_affirmative`; FSM stays armed; user-facing prompt unchanged
- [ ] CI green on this PR
- [ ] After merge: owner decides bot re-create deploy (BUG-078); not required for merge

EOF
)"
```

Дождаться зелёного CI. Compose-integration nightly — ожидаемо skipped в PR.

После merge: сообщить owner'у, что для prod нужен re-create `tg_parser_bot` (не `restart`), если хотят закрыть дыру на живом контейнере. SSH/deploy из этого чата — только по явному запросу.

---

## 9. Definition of Done

| # | Критерий |
|---|---|
| 1 | Ветка от актуального `main` |
| 2 | INFO-сайт без `normalized` / raw text; key set = plan §3 |
| 3 | `verdict` только из closed vocabulary; near-miss pin зелёный |
| 4 | Privacy pin: event exists ∧ secret absent ∧ no `normalized` |
| 5 | Existing unknown-token UX tests green |
| 6 | BUG_LOG `resolved` + CHANGELOG + runbook row |
| 7 | PR в `main`, CI green |
| 8 | Hard OUT соблюдён; deploy не делался без owner GO |

**Hard OUT reminder:** methodology workspace, `pyproject.toml`, `requirements.txt`, pagination sweep, DEBUG raw dump, T7/Wave 3.
