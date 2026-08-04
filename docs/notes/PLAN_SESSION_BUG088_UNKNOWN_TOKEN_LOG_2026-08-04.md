# Plan — BUG-088: `fsm_confirm_unknown_token` free-text INFO hygiene

**Дата:** 2026-08-04 · **Тип:** planning note → START_PROMPT · **Ветка (impl):** `fix/bug088-unknown-token-log`  
**SoT:** [`BUG_LOG.md`](BUG_LOG.md) § **BUG-088** · предшественник privacy-слайса: BUG-087 ([PR #362](https://github.com/AlexEfimov/TG_parser/pull/362))  
**START_PROMPT:** [`START_PROMPT_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md`](START_PROMPT_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md)

**Goal (одной строкой):** на единственном INFO-сайте `fsm_confirm_unknown_token` заменить сырой `normalized=<весь ответ>` на закрытый verdict + shape-facts (+ `tool`), сохранив diagnosability BUG-032 (почему токен отвергнут) и запретив user bytes в лог-пайплайне.

---

## 1. Контекст (уже решено / не переоткрывать)

| Факт | Статус |
|---|---|
| BUG-087 (deny-list на `agent_tool_call` / `fsm_confirm_execute`) | ✅ resolved + в `main` |
| #359 / ADR-0020 | ✅ closed; BUG-088 **не** регрессия #359 (`66e8297`, 2026-05-25) |
| Call site | один: [`handlers.py`](../../tg_parser/bot/handlers.py) ~L1084–1088 |
| Wave-1 debt / Wave 3 | не блокирует; это pre-Wave-3 privacy hygiene |
| Prod logs currently off-host | да — держит severity на Medium, **не** отменяет фикс |

**Почему отдельный слайс от BUG-087.** Deny-list по именам arg'ов не работает на free-text: словарь закрыт у tool args и открыт у `normalized`. Half-fix «087 без 088» оставлял непредсказуемую половину экспозиции.

---

## 2. Owner decisions — LOCKED для сессии

BUG_LOG оставлял 5 пунктов открытыми. Для этой сессии они фиксируются так:

| # | Вопрос | Решение |
|---|---|---|
| 1 | Fix shape | **(d) + (a)** — closed-vocabulary `verdict` + `length` / `token_count` / class flags. **Не** (b) truncation, **не** (c) hash, **не** raw @ DEBUG |
| 2 | Shared PR с BUG-087 | **Нет** — 087 уже смержен; отдельный PR |
| 3 | Sweep `fsm_pagination_execute` | **Нет** (Hard OUT) — read-only cursors, zero known credential path |
| 4 | Retro-scan prod logs | **Вне code-сессии** — опциональный ops follow-up, не DoD |
| 5 | Runbook | **Да** — обновить строку `fsm_confirm_unknown_token` в [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) |

**Rationale (d)+(a):**  
- (d) даёт actionable near-miss («дя» → `near_miss_affirmative`) при **нулевом** value exposure — vocabulary compile-time.  
- (a) отличает «короткое одно слово / вероятно синоним» от «длинный paste / вероятно credential» без содержимого.  
- (b) утекает короткие секреты и correlatable prefix длинных ключей.  
- (c) unsalted hash коротких реплик обратим словарём; HMAC ломает cross-deploy correlation.  
- DEBUG-split (`b0dcef3`) уже откатывался (`8332aa3`) ради forensics — не повторять.

---

## 3. Целевой контракт лога

Событие `fsm_confirm_unknown_token` на INFO — **ровно** эти ключи (literal set пин в тестах):

| Key | Тип | Источник |
|---|---|---|
| `chat_id` | int | как сейчас |
| `tool` | str \| None | `pending_action["tool_name"]` — **добавить** (диагностический пробел сегодня) |
| `verdict` | str | закрытый enum ниже |
| `length` | int | `len(normalized)` |
| `token_count` | int | число whitespace-токенов после normalize |
| `is_single_token` | bool | `token_count == 1` |
| `has_digits` | bool | любой `\d` в normalized |
| `has_punct` | bool | любой non-alnum / non-space (после casefold) |

**Запрещено на INFO:** `normalized`, `text`, `message`, любой raw / prefix / hash пользовательского текста.

### 3.1 `verdict` vocabulary (closed)

Нормализация входа — та же, что у классификатора: `" ".join(text.split()).casefold()`.

| Verdict | Когда |
|---|---|
| `non_text` | пустая строка после normalize **или** ни одного буквенно-цифрового символа (emoji-only и т.п.) |
| `near_miss_affirmative` | single token; Levenshtein ≤ 1 к любому `AFFIRMATIVE_TOKENS` **или** равенство после strip non-alnum |
| `near_miss_negative` | то же против `NEGATIVE_TOKENS` (affirmative проверять первым при коллизии — маловероятно) |
| `single_token_unlisted` | `token_count == 1`, не near-miss |
| `multi_token_free_text` | `token_count >= 2` |

Near-miss **только** для single-token: multi-token free text не гонять по edit-distance (дорого и шумно).

### 3.2 Поведение хендлера (не менять)

- FSM остаётся armed (BUG-032).  
- User-facing текст ответа — bit-for-bit тот же.  
- Affirmative / negative / decline / TTL / new-intent ветки — не трогать.

---

## 4. Реализация (outline)

1. Новый тонкий модуль `tg_parser/bot/confirm_unknown_log.py` (не раздувать `log_redaction.py` — другой механизм).  
   - `normalize_confirm_reply(text) -> str`  
   - `classify_unknown_confirm_verdict(normalized) -> str`  
   - `unknown_confirm_log_fields(text, *, tool: str | None) -> dict` — готовый kwargs для `logger.info`.  
2. Call site в `_handle_confirmation_response`:  
   `logger.info("fsm_confirm_unknown_token", **unknown_confirm_log_fields(text, tool=pending_action.get("tool_name")))`.  
3. Комментарий у сайта: BUG-032 diagnostic preserved as closed verdict + shape; raw text never at INFO (BUG-088).  
4. `UnknownConfirmationToken.__init__` — **не** менять в этом слайсе (не log-site; OUT), но упомянуть в BUG_LOG Update как known adjacent door.

---

## 5. Тесты

Новый [`tests/test_bot_confirm_unknown_log_088.py`](../../tests/test_bot_confirm_unknown_log_088.py) (+ существующие unknown-token тесты в `test_bot_confirm_flow.py` остаются зелёными).

| # | Пин | Как |
|---|---|---|
| 1 | Privacy | armed ConfirmFlow + secret-shaped reply (`sk-live-…` / длинный paste) → event **exists**; secret ∉ `json.dumps(records)`; **нет** ключа `normalized` |
| 2 | Key-set literal | keys события == ожидаемый frozenset (future field addition must be deliberate) |
| 3 | Diagnostic near-miss | `"дя"` → `verdict=near_miss_affirmative` |
| 4 | Shape paste | длинный single-token alnum → `single_token_unlisted`, `has_digits=True`, большой `length` |
| 5 | Multi-token | `"ладно потом"` → `multi_token_free_text` |
| 6 | Tool field | `tool == "remove_channel"` из `pending_action` |
| 7 | FSM / UX | existing `TestHandleConfirmationResponseUnknownToken` still pass |

Прецедент capture: `structlog.testing.capture_logs` как в [`tests/test_bot_log_redaction_087.py`](../../tests/test_bot_log_redaction_087.py).

---

## 6. Docs / DoD

| Артефакт | Правка |
|---|---|
| BUG_LOG § BUG-088 | Status → `resolved` + Update (shape d+a, module, tests, PR) |
| CHANGELOG Unreleased | Security/Fixed — BUG-088 |
| F5C runbook table row | `normalized` caveat → new fields; «не тащить в заметки» можно снять/смягчить |
| START_PROMPT | коммитить вместе с кодом |

**DoD:** PR в `main`, CI green; raw user text отсутствует на INFO-сайте; near-miss pin зелёный; deploy — отдельное owner-решение (bot re-create per BUG-078).

---

## 7. Hard OUT

- `fsm_pagination_execute` args  
- `tool_validation_error` / `tool_permission_denied` `message=str(exc)`  
- FSM / `MemoryStorage` encryption / pending credential at rest  
- DEBUG dump сырого текста  
- Truncation / hash shapes  
- `pyproject.toml` / `requirements.txt` / methodology / Grafana / prod SSH  
- Wave 3 / T7 / Event B

---

## 8. Rough size / risk

| | |
|---|---|
| Size | ~0.5 сессии |
| Risk | Low — один call site, UX/FSM unchanged |
| Rollback | revert PR / bot re-create previous image |

---

## 9. Ссылки

- SoT: BUG_LOG § BUG-088 Proposed fix (d)+(a)  
- Precedent privacy tests: `TestWriteIntentLogPrivacy`, `tests/test_bot_log_redaction_087.py`  
- Existing unknown-token UX pins: `TestHandleConfirmationResponseUnknownToken`  
- Runbook: `F5C_DEPLOY_AND_WATCH.md` rows `fsm_confirm_execute` / `fsm_confirm_unknown_token`  
- START_PROMPT: [`START_PROMPT_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md`](START_PROMPT_BUG088_UNKNOWN_TOKEN_LOG_2026-08-04.md)
